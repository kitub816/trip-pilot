"""Optional Redis cache for validated retrieval results, never full user plans."""
import asyncio
import hashlib
import inspect
import json
import logging
import time
from contextvars import ContextVar
from functools import wraps
from typing import Awaitable, Callable, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from ..config import get_settings

logger = logging.getLogger("trippilot.cache")
T = TypeVar("T")
TTL = {"poi": 86400, "weather": 600, "route": 1800, "geocode": 86400}
_cacheable: ContextVar[bool] = ContextVar("retrieval_cacheable", default=True)


def skip_cache_write() -> None:
    """A partial result may be returned to the caller but must not hide a failure in cache."""
    _cacheable.set(False)


class CacheBackend(Protocol):
    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: int) -> None: ...


class RedisBackend:
    def __init__(self, url: str, timeout: float = 0.3):
        self._url, self._timeout = url, timeout

    def _client(self) -> Redis:
        # Existing sync API workers use independent event loops. Clients are scoped
        # to each operation, so no async connection leaks into another loop.
        return Redis.from_url(self._url, socket_timeout=self._timeout,
            socket_connect_timeout=self._timeout, retry=Retry(NoBackoff(), 0))

    async def get(self, key: str) -> bytes | None:
        return await asyncio.wait_for(self._get(key), timeout=self._timeout)

    async def set(self, key: str, value: bytes, ttl: int) -> None:
        await asyncio.wait_for(self._set(key, value, ttl), timeout=self._timeout)

    async def _get(self, key: str) -> bytes | None:
        async with self._client() as client:
            return await client.get(key)

    async def _set(self, key: str, value: bytes, ttl: int) -> None:
        async with self._client() as client:
            await client.set(key, value, ex=ttl)


class CacheEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    key: str
    expires_at: float = Field(gt=0, allow_inf_nan=False)
    payload: JsonValue


def cache_key(operation: str, arguments: dict[str, JsonValue], version: str = "amap-0.1.11-schema1") -> str:
    normalized = {key: value.strip() if isinstance(value, str) else value for key, value in arguments.items()}
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"trippilot:{version}:{operation}:{digest}"


class RetrievalCache:
    def __init__(self, backend: CacheBackend | None = None, *, clock: Callable[[], float] = time.time):
        self.backend, self.clock = backend, clock
        self.version = "amap-0.1.11-schema1"

    async def load(self, operation: str, arguments: dict[str, JsonValue], adapter: TypeAdapter[T],
                   loader: Callable[[], Awaitable[T]], ttl: int) -> T:
        if self.backend is None:
            return await loader()
        key = cache_key(operation, arguments, self.version)
        try:
            raw = await self.backend.get(key)
            if raw is not None:
                envelope = CacheEnvelope.model_validate_json(raw)
                if envelope.version == self.version and envelope.key == key and envelope.expires_at > self.clock():
                    value = adapter.validate_python(envelope.payload)
                    if value is not None and value != []:
                        logger.info("cache.hit.%s", operation)
                        return value
        except (RedisError, TimeoutError, OSError, ValidationError, ValueError):
            logger.warning("cache.read_degraded.%s", operation)
        logger.info("cache.miss.%s", operation)
        token = _cacheable.set(True)
        try:
            value = await loader()
            # Do not negative-cache missing data or persist partial retrievals.
            if value is not None and value != [] and _cacheable.get():
                envelope = CacheEnvelope(version=self.version, key=key, expires_at=self.clock() + ttl,
                    payload=adapter.dump_python(value, mode="json"))
                try:
                    await self.backend.set(key, envelope.model_dump_json().encode("utf-8"), ttl)
                except (RedisError, TimeoutError, OSError, ValueError):
                    logger.warning("cache.write_degraded.%s", operation)
            return value
        finally:
            _cacheable.reset(token)


def cached(kind: str, result_type):
    """Bind defaults before keying so positional and keyword calls share a key."""
    adapter = TypeAdapter(result_type)
    def decorate(function):
        signature = inspect.signature(function)
        @wraps(function)
        async def wrapper(self, *args, **kwargs):
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            arguments = {name: value.model_dump(mode="json") if isinstance(value, BaseModel) else value
                         for name, value in bound.arguments.items() if name != "self"}
            return await self.cache.load(function.__name__, arguments, adapter,
                lambda: function(self, *args, **kwargs), TTL[kind])
        return wrapper
    return decorate


def get_retrieval_cache() -> RetrievalCache:
    settings = get_settings()
    url = settings.redis_url.get_secret_value()
    return RetrievalCache(RedisBackend(url, settings.redis_timeout) if url else None)
