"""Bounded, cancellable MCP calls. Each attempt owns and closes its session."""
import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock
from typing import AsyncContextManager, Callable, Literal, Protocol

import anyio
from jsonschema import validate as validate_schema
from jsonschema.exceptions import SchemaError, ValidationError as SchemaValidationError
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, ListToolsResult
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from ..config import get_settings
from ..errors import (AppError, ConfigurationError, ServiceBusy, ToolArgumentError,
                      ToolProtocolError, ToolRateLimit, UpstreamError, UpstreamTimeout)

logger = logging.getLogger("trippilot.tools")


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchArguments(Arguments):
    keywords: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    citylimit: Literal["true", "false"] = "true"


class WeatherArguments(Arguments):
    city: str = Field(min_length=1, max_length=100)


class DetailArguments(Arguments):
    id: str = Field(min_length=1, max_length=100)


class GeoArguments(Arguments):
    address: str = Field(min_length=1, max_length=300)
    city: str | None = Field(default=None, min_length=1, max_length=100)


class CoordinateRouteArguments(Arguments):
    origin: str = Field(pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$")
    destination: str = Field(pattern=r"^-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?$")


class CoordinateTransitArguments(CoordinateRouteArguments):
    city: str = Field(min_length=1, max_length=100)
    cityd: str = Field(min_length=1, max_length=100)


class RouteArguments(Arguments):
    origin_address: str = Field(min_length=1, max_length=300)
    destination_address: str = Field(min_length=1, max_length=300)
    origin_city: str | None = Field(default=None, min_length=1, max_length=100)
    destination_city: str | None = Field(default=None, min_length=1, max_length=100)


TOOL_SCHEMAS: dict[str, type[Arguments]] = {
    "maps_text_search": SearchArguments, "maps_weather": WeatherArguments,
    "maps_search_detail": DetailArguments, "maps_geo": GeoArguments,
    "maps_direction_walking_by_address": RouteArguments,
    "maps_direction_driving_by_address": RouteArguments,
    "maps_direction_transit_integrated_by_address": RouteArguments,
    "maps_direction_walking_by_coordinates": CoordinateRouteArguments,
    "maps_direction_driving_by_coordinates": CoordinateRouteArguments,
    "maps_direction_transit_integrated_by_coordinates": CoordinateTransitArguments,
}


class ToolProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool: str
    provider: str = "amap-mcp"
    retrieved_at: datetime
    attempts: int
    elapsed_ms: float


class ToolResult(BaseModel):
    payload: JsonValue
    provenance: ToolProvenance


class Session(Protocol):
    async def initialize(self): ...
    async def list_tools(self) -> ListToolsResult: ...
    async def call_tool(self, name: str, arguments: dict[str, JsonValue]) -> CallToolResult: ...


@asynccontextmanager
async def amap_session():
    settings = get_settings()
    key = settings.amap_api_key.get_secret_value()
    if not key.strip():
        raise ConfigurationError()
    child_env = {"AMAP_MAPS_API_KEY": key}
    # Explicit MCP env replaces the default inherited environment. Preserve a
    # caller-selected direct route for Amap without exposing proxy credentials.
    for name in ("NO_PROXY", "no_proxy"):
        if os.environ.get(name):
            child_env[name] = os.environ[name]
    params = StdioServerParameters(command="uvx", args=["amap-mcp-server==0.1.11"],
                                  env=child_env)
    # Child stderr can contain credentials and queries; never forward it to API logs.
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                yield session


def parse_payload(value: JsonValue) -> JsonValue:
    """Accept JSON or a whole fenced JSON block, never scrape arbitrary error prose."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            if lines[0].strip() not in ("```", "```json"):
                raise ToolProtocolError()
            text = "\n".join(lines[1:-1])
        try:
            value = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise ToolProtocolError() from exc
    if not isinstance(value, (dict, list)):
        raise ToolProtocolError()
    if isinstance(value, dict):
        if str(value.get("infocode", "")) in {"10003", "10004", "10019", "10020", "10021", "429"}:
            raise ToolRateLimit()
        if value.get("error") or value.get("isError") or value.get("status") in (0, "0"):
            raise UpstreamError()
    return value


def decode_result(result: CallToolResult) -> JsonValue:
    if result.isError:
        raise UpstreamError()
    if result.structuredContent is not None:
        return parse_payload(result.structuredContent)
    texts = [part.text for part in result.content if part.type == "text"]
    if len(texts) != 1:
        raise ToolProtocolError()
    return parse_payload(texts[0])


def classify_failure(exc: BaseException) -> AppError:
    # AnyIO task-group cleanup may wrap a public error in an ExceptionGroup.
    if isinstance(exc, AppError):
        return exc
    for child in getattr(exc, "exceptions", ()):
        error = classify_failure(child)
        if type(error) is not UpstreamError:
            return error
    if isinstance(exc, TimeoutError):
        return UpstreamTimeout()
    return UpstreamError()


class ToolRuntime:
    def __init__(self, session_factory: Callable[[], AsyncContextManager[Session]] = amap_session,
                 *, timeout: float = 20, total_timeout: float = 50,
                 max_attempts: int = 2, concurrency: int = 3, backoff: float = 0.2):
        if timeout <= 0 or total_timeout <= 0 or not 1 <= max_attempts <= 3 or concurrency < 1:
            raise ValueError("invalid runtime limits")
        self.session_factory = session_factory
        self.timeout, self.total_timeout = timeout, total_timeout
        self.max_attempts, self.backoff = max_attempts, backoff
        # Safe across the existing synchronous API worker threads and their event loops.
        self._quota = BoundedSemaphore(concurrency)
        self._closed = False

    async def call(self, name: str, arguments: dict[str, JsonValue]) -> ToolResult:
        if self._closed:
            raise ServiceBusy()
        schema = TOOL_SCHEMAS.get(name)
        if schema is None:
            raise ToolArgumentError()
        try:
            normalized = schema.model_validate(arguments).model_dump(mode="json", exclude_none=True)
        except ValidationError as exc:
            raise ToolArgumentError() from exc
        start = time.monotonic()
        try:
            with anyio.fail_after(self.total_timeout):
                # A saturated process rejects immediately, avoiding unbounded queues.
                if not self._quota.acquire(blocking=False):
                    raise ServiceBusy()
                try:
                    for attempt in range(1, self.max_attempts + 1):
                        try:
                            with anyio.fail_after(self.timeout):
                                async with self.session_factory() as session:
                                    await session.initialize()
                                    tools = await session.list_tools()
                                    spec = next((tool for tool in tools.tools if tool.name == name), None)
                                    if spec is None:
                                        raise ToolProtocolError()
                                    try:
                                        validate_schema(normalized, spec.inputSchema)
                                    except (SchemaError, SchemaValidationError) as exc:
                                        raise ToolProtocolError() from exc
                                    payload = decode_result(await session.call_tool(name, normalized))
                            logger.info("tool.completed.%s", name)
                            return ToolResult(payload=payload, provenance=ToolProvenance(
                                tool=name, retrieved_at=datetime.now(timezone.utc), attempts=attempt,
                                elapsed_ms=round((time.monotonic() - start) * 1000, 3)))
                        except asyncio.CancelledError:
                            logger.info("tool.cancelled.%s", name)
                            raise
                        except Exception as exc:
                            error = classify_failure(exc)
                            # Read-only tools: retry only explicit timeout / rate-limit signals.
                            if not isinstance(error, (UpstreamTimeout, ToolRateLimit)) or attempt == self.max_attempts:
                                logger.warning("tool.failed.%s.%s", name, error.code)
                                raise error from exc
                            logger.info("tool.retry.%s", name)
                            await asyncio.sleep(self.backoff * 2 ** (attempt - 1))
                finally:
                    self._quota.release()
        except TimeoutError as exc:
            raise UpstreamTimeout() from exc

    def close(self) -> None:
        # Sessions close inside each call. ASGI shutdown drains active sync handlers.
        self._closed = True


_runtime: ToolRuntime | None = None
_lock = Lock()


def get_tool_runtime() -> ToolRuntime:
    global _runtime
    with _lock:
        if _runtime is None:
            settings = get_settings()
            _runtime = ToolRuntime(timeout=settings.tool_timeout, total_timeout=settings.tool_total_timeout,
                                   max_attempts=settings.tool_max_attempts, concurrency=settings.tool_concurrency)
        return _runtime


def reset_tool_runtime() -> None:
    global _runtime
    with _lock:
        if _runtime is not None:
            _runtime.close()
            _runtime = None
