import asyncio
from types import SimpleNamespace

import pytest

from app.errors import NoCandidates, ToolProtocolError
from app.models.schemas import TripRequest
from app.services.amap_service import AmapService
from app.services.constraint_service import build_travel_constraints
from app.services.retrieval_service import TripRetrievalService


REQUEST = dict(city="上海", start_date="2026-10-01", end_date="2026-10-02",
               transportation="步行", accommodation="民宿")


class ActualFormatRuntime:
    def __init__(self):
        self.calls = []

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "maps_text_search":
            payload = {"pois": [{"id": "p1", "name": "外滩", "address": "上海", "typecode": "110000"}]}
        elif name == "maps_search_detail":
            payload = {"id": arguments["id"], "name": "外滩", "address": "上海", "location": "121.49,31.24"}
        elif name == "maps_weather":
            payload = {"city": "上海", "forecasts": [{"date": "2026-10-01", "dayweather": "晴",
                       "nightweather": "阴", "daytemp": "0", "nighttemp": "-3"}]}
        elif name == "maps_geo":
            payload = {"return": [{"location": "121.49,31.24"}]}
        else:
            payload = {"route": {"paths": [{"distance": "123", "duration": "60", "steps": []}]}}
        return SimpleNamespace(payload=payload)


def test_server_0111_shapes_hydrate_coordinates_weather_geo_and_routes():
    runtime = ActualFormatRuntime()
    service = AmapService(runtime)
    assert service.search_poi("景点", "上海")[0].location.longitude == 121.49
    assert service.get_weather("上海")[0].day_temp == 0
    assert service.geocode("外滩").latitude == 31.24
    assert service.plan_route("a", "b").distance == 123
    assert [name for name, _ in runtime.calls][:2] == ["maps_text_search", "maps_search_detail"]


def test_retrieval_is_not_globally_mocked_here_and_covers_every_preference():
    runtime = ActualFormatRuntime()
    constraints = build_travel_constraints(TripRequest(**REQUEST, preferences=["历史", "美食"], must_visit=["豫园"]))
    result = asyncio.run(TripRetrievalService(AmapService(runtime)).retrieve(constraints))
    assert len(result.attractions) == 1 and result.weather[0].night_temp == -3
    queries = {args["keywords"] for name, args in runtime.calls if name == "maps_text_search"}
    assert {"景点", "历史", "美食", "豫园"} <= queries


def test_empty_candidates_stop_before_any_llm():
    class Empty:
        async def asearch_poi(self, *args): return []
        async def aget_weather(self, *args): return []
    with pytest.raises(NoCandidates):
        asyncio.run(TripRetrievalService(Empty()).retrieve(build_travel_constraints(TripRequest(**REQUEST))))


def test_slow_weather_is_cancelled_and_valid_pois_survive():
    closed = []
    class SlowWeather(AmapService):
        async def aget_weather(self, city):
            try:
                await asyncio.sleep(10)
            finally:
                closed.append(True)
    result = asyncio.run(TripRetrievalService(SlowWeather(ActualFormatRuntime()), timeout=0.02).retrieve(
        build_travel_constraints(TripRequest(**REQUEST))))
    assert result.attractions and closed == [True]
    assert result.warnings[0].code == "UPSTREAM_TIMEOUT"


@pytest.mark.parametrize("value", ["181,30", "nan,30", "120,91", "invalid"])
def test_invalid_coordinates_never_become_candidates(value):
    from app.services.amap_service import location
    with pytest.raises(ToolProtocolError):
        location(value)
