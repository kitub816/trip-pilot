"""Real Redis integration is opt-in; socket timeout is always tested locally."""
import asyncio
import os
import uuid

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.services.cache_service import RedisBackend


def test_real_client_timeout_closes_connection():
    async def run():
        closed = asyncio.Event()

        async def stall(reader, writer):
            try:
                while await reader.read(1024):
                    pass
            finally:
                writer.close()
                await writer.wait_closed()
                closed.set()

        server = await asyncio.start_server(stall, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with server:
            with pytest.raises(RedisTimeoutError):
                await RedisBackend(f"redis://127.0.0.1:{port}", timeout=0.05).get("trippilot:test")
            await asyncio.wait_for(closed.wait(), 2)

    asyncio.run(run())


def test_live_redis_roundtrip_and_expiration():
    url = os.environ.get("TRIPPILOT_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set TRIPPILOT_TEST_REDIS_URL to a local disposable Redis instance")

    async def run():
        backend = RedisBackend(url, timeout=1)
        key = "trippilot:integration:" + uuid.uuid4().hex
        assert await backend.get(key) is None
        await backend.set(key, b"validated fixture", 1)
        assert await backend.get(key) == b"validated fixture"
        await asyncio.sleep(1.1)
        assert await backend.get(key) is None

    asyncio.run(run())
