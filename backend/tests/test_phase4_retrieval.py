import asyncio
from types import SimpleNamespace

from app.models.schemas import POIInfo, TripRequest
from app.services.amap_service import AmapService
from app.services.constraint_service import build_travel_constraints
from app.services.retrieval_service import TripRetrievalService


def test_amap_parses_poi_and_weather_payloads(monkeypatch):
    replies = iter([
        '{"pois":[{"id":"p1","name":"外滩","type":"风景名胜","address":"上海","location":"121.49,31.24"}]}',
        '{"forecasts":[{"casts":[{"date":"2026-10-01","dayweather":"晴","nightweather":"多云","daytemp":"25","nighttemp":"18","daywind":"东","daypower":"3"}]}]}',
    ])
    async def call(name, arguments):
        return SimpleNamespace(payload=next(replies))
    service = AmapService(SimpleNamespace(call=call))
    poi = service.search_poi("景点", "上海")
    weather = service.get_weather("上海")
    assert poi[0].name == "外滩" and poi[0].location.longitude == 121.49
    assert weather[0].day_weather == "晴" and weather[0].day_temp == 25


def test_retrieval_keeps_pois_when_weather_fails_and_dedupes():
    poi = POIInfo(id="p1", name="外滩", type="景点", address="上海", location={"longitude": 121.49, "latitude": 31.24})

    class FakeMap:
        async def asearch_poi(self, keywords, city, citylimit=True):
            return [poi]

        async def aget_weather(self, city):
            raise RuntimeError("upstream unavailable")

    constraints = build_travel_constraints(TripRequest(
        city="上海", start_date="2026-10-01", end_date="2026-10-02",
        transportation="步行", accommodation="民宿", preferences=["历史", "历史"],
    ))
    result = asyncio.run(TripRetrievalService(FakeMap()).retrieve(constraints))
    assert result.attractions == (poi,)
    assert result.weather == ()
    assert result.warnings and result.warnings[0].source == "weather"
