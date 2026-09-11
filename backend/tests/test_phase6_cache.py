import asyncio
import json

import pytest
from pydantic import TypeAdapter
from redis.exceptions import ConnectionError as RedisConnectionError

from app.errors import UpstreamError
from app.models.schemas import POIInfo
from app.services.amap_service import AmapService
from app.services.cache_service import RetrievalCache, TTL, cache_key, RedisBackend
from test_phase5_retrieval_integration import ActualFormatRuntime


class MemoryBackend:
    def __init__(self):
        self.values = {}
        self.ttls = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl):
        self.values[key] = value
        self.ttls.append(ttl)


def test_cache_hit_and_normalized_default_arguments_do_not_call_tools():
    async def run():
        backend, runtime = MemoryBackend(), ActualFormatRuntime()
        service = AmapService(runtime, RetrievalCache(backend))
        first = await service.asearch_poi("景点", "上海")
        count = len(runtime.calls)
        second = await service.asearch_poi(city=" 上海 ", keywords="景点", citylimit=True)
        assert len(runtime.calls) == count
        assert second == first and second is not first
        assert backend.ttls == [TTL["poi"]]
    asyncio.run(run())


def test_tool_city_mode_and_version_have_different_keys():
    arguments = {"city": "上海", "keywords": "景点"}
    base = cache_key("poi", arguments)
    assert "上海" not in base and "景点" not in base
    assert base == cache_key("poi", {"keywords": "景点", "city": " 上海 "})
    assert base != cache_key("weather", arguments)
    assert base != cache_key("poi", {**arguments, "city": "北京"})
    assert base != cache_key("poi", arguments, "new-version")
    assert cache_key("route", {"route_type": "walking"}) != cache_key("route", {"route_type": "driving"})


def test_application_expiry_uses_injected_clock_and_refetches():
    async def run():
        now = [100.0]
        backend, runtime = MemoryBackend(), ActualFormatRuntime()
        service = AmapService(runtime, RetrievalCache(backend, clock=lambda: now[0]))
        await service.aget_weather("上海")
        await service.aget_weather("上海")
        assert len(runtime.calls) == 1
        now[0] += TTL["weather"] + 1
        await service.aget_weather("上海")
        assert len(runtime.calls) == 2
    asyncio.run(run())


@pytest.mark.parametrize("broken", [b"not-json", b"{}", b'{"error":"bad"}'])
def test_corrupt_cache_falls_back_and_repairs(broken):
    async def run():
        backend, runtime = MemoryBackend(), ActualFormatRuntime()
        service = AmapService(runtime, RetrievalCache(backend))
        key = cache_key("aget_weather", {"city": "上海"})
        backend.values[key] = broken
        assert await service.aget_weather("上海")
        assert len(runtime.calls) == 1
        assert json.loads(backend.values[key])["payload"]
    asyncio.run(run())


def test_valid_envelope_but_invalid_model_is_refetched():
    async def run():
        backend, runtime = MemoryBackend(), ActualFormatRuntime()
        service = AmapService(runtime, RetrievalCache(backend))
        await service.asearch_poi("景点", "上海")
        key = next(iter(backend.values))
        envelope = json.loads(backend.values[key])
        envelope["payload"] = [{"name": "missing location"}]
        backend.values[key] = json.dumps(envelope).encode()
        await service.asearch_poi("景点", "上海")
        assert len(runtime.calls) == 4
    asyncio.run(run())


def test_cache_outage_does_not_hide_successful_origin_response():
    class Broken:
        async def get(self, key): raise RedisConnectionError("private URL")
        async def set(self, key, value, ttl): raise RedisConnectionError("private URL")
    service = AmapService(ActualFormatRuntime(), RetrievalCache(Broken()))
    assert asyncio.run(service.aget_weather("上海"))


def test_no_empty_or_failure_negative_caching():
    async def run():
        backend = MemoryBackend()
        cache = RetrievalCache(backend)
        async def empty(): return []
        async def failure(): raise UpstreamError()
        assert await cache.load("empty", {}, TypeAdapter(list[POIInfo]), empty, 10) == []
        with pytest.raises(UpstreamError):
            await cache.load("bad", {}, TypeAdapter(list[POIInfo]), failure, 10)
        assert backend.values == {}
    asyncio.run(run())


def test_partial_poi_result_does_not_poison_later_search():
    class Partial(ActualFormatRuntime):
        async def call(self, name, args):
            result = await super().call(name, args)
            if name == "maps_text_search":
                result.payload["pois"].append({"id": "failed", "name": "failed"})
            if name == "maps_search_detail" and args["id"] == "failed":
                raise UpstreamError()
            return result
    async def run():
        backend = MemoryBackend()
        service = AmapService(Partial(), RetrievalCache(backend))
        assert await service.asearch_poi("景点", "上海")
        assert backend.values == {}
    asyncio.run(run())


def test_cancellation_is_not_converted_into_cache_miss():
    class Cancelled:
        async def get(self, key): raise asyncio.CancelledError()
        async def set(self, *args): raise AssertionError()
    async def run():
        async def loader(): raise AssertionError("must not call origin")
        with pytest.raises(asyncio.CancelledError):
            await RetrievalCache(Cancelled()).load("poi", {}, TypeAdapter(list[POIInfo]), loader, 10)
    asyncio.run(run())


def test_route_and_geocode_cache_ttls_and_no_cross_event_loop_clients():
    backend, runtime = MemoryBackend(), ActualFormatRuntime()
    service = AmapService(runtime, RetrievalCache(backend))
    service.plan_route("a", "b")
    service.plan_route("a", "b")
    service.geocode("外滩")
    service.geocode("外滩")
    assert len(runtime.calls) == 2
    assert backend.ttls == [TTL["route"], TTL["geocode"]]
