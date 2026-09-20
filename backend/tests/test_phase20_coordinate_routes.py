"""Retrieved POI coordinates go directly to Amap route tools."""
import asyncio
from types import SimpleNamespace

import pytest
import httpx
from pydantic import SecretStr

from app.errors import ToolArgumentError, UpstreamError, UpstreamTimeout
from app.models.schemas import Attraction, DayPlan, Location, TripPlan, TripRequest
from app.services.amap_service import AmapService
from app.services.cache_service import RetrievalCache
from app.services.constraint_service import build_travel_constraints
from app.services.route_service import RouteOptimizer


class MemoryCache:
    def __init__(self):
        self.values = {}
    async def get(self, key):
        return self.values.get(key)
    async def set(self, key, value, ttl):
        self.values[key] = value


class Runtime:
    def __init__(self):
        self.calls = []
    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        key = "transits" if "transit" in name else "paths"
        return SimpleNamespace(payload={"route": {key: [
            {"distance": "1200", "duration": "900", "steps": []}]}})


def points():
    return Location(longitude=121.49, latitude=31.24), Location(longitude=121.50, latitude=31.25)


@pytest.mark.parametrize("mode,tool", [
    ("walking", "maps_direction_walking_by_coordinates"),
    ("driving", "maps_direction_driving_by_coordinates"),
])
def test_coordinate_route_uses_expected_mcp_tool_and_cache(mode, tool):
    runtime = Runtime()
    service = AmapService(runtime, RetrievalCache(MemoryCache()))
    start, end = points()
    first = asyncio.run(service.aplan_route_by_coordinates(start, end, "上海", mode))
    second = asyncio.run(service.aplan_route_by_coordinates(start, end, "上海", mode))
    assert first.duration == second.duration == 900
    assert len(runtime.calls) == 1
    assert runtime.calls[0][0] == tool
    assert runtime.calls[0][1]["origin"] == "121.49,31.24"
    assert runtime.calls[0][1]["destination"] == "121.5,31.25"
    assert "origin_address" not in runtime.calls[0][1]
    assert ("city" in runtime.calls[0][1]) is (mode == "transit")


def test_transit_uses_bounded_direct_api_when_vendor_mcp_breaks_stdio(monkeypatch):
    from types import SimpleNamespace
    import app.services.amap_service as amap_module

    monkeypatch.setattr(amap_module, "get_settings", lambda: SimpleNamespace(
        amap_api_key=SecretStr("fixture"), tool_timeout=1))
    observed = []

    def handler(request):
        observed.append(request)
        return httpx.Response(200, json={"status": "1", "route": {"transits": [
            {"distance": "1200", "duration": "900"}]}})

    runtime = Runtime()
    service = AmapService(runtime, RetrievalCache(MemoryCache()),
                          transit_transport=httpx.MockTransport(handler))
    start, end = points()
    result = asyncio.run(service.aplan_route_by_coordinates(start, end, "上海", "transit"))
    assert result.duration == 900 and result.distance == 1200
    assert len(observed) == 1 and observed[0].url.path.endswith("/direction/transit/integrated")
    assert observed[0].url.params["city"] == "上海"
    assert runtime.calls == []


def test_transit_rejects_provider_error_without_fabricating_route(monkeypatch):
    from types import SimpleNamespace
    import app.services.amap_service as amap_module

    monkeypatch.setattr(amap_module, "get_settings", lambda: SimpleNamespace(
        amap_api_key=SecretStr("fixture"), tool_timeout=1))
    service = AmapService(Runtime(), transit_transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "0", "infocode": "10001"})))
    with pytest.raises(UpstreamError):
        asyncio.run(service.aplan_route_by_coordinates(*points(), "上海", "transit"))


def test_transit_retries_one_timeout_then_uses_valid_response(monkeypatch):
    from types import SimpleNamespace
    import app.services.amap_service as amap_module

    monkeypatch.setattr(amap_module, "get_settings", lambda: SimpleNamespace(
        amap_api_key=SecretStr("fixture"), tool_timeout=1))
    attempts = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise httpx.ReadTimeout("fixture")
        return httpx.Response(200, json={"status": "1", "route": {"transits": [
            {"distance": "500", "duration": "600"}]}})

    service = AmapService(Runtime(), transit_transport=httpx.MockTransport(handler))
    result = asyncio.run(service.aplan_route_by_coordinates(*points(), "上海", "transit"))
    assert result.duration == 600 and len(attempts) == 2


def test_transit_timeout_is_bounded(monkeypatch):
    from types import SimpleNamespace
    import app.services.amap_service as amap_module

    monkeypatch.setattr(amap_module, "get_settings", lambda: SimpleNamespace(
        amap_api_key=SecretStr("fixture"), tool_timeout=1))
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ReadTimeout("fixture")

    service = AmapService(Runtime(), transit_transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamTimeout):
        asyncio.run(service.aplan_route_by_coordinates(*points(), "上海", "transit"))
    assert len(attempts) == 2


def test_http_client_log_filter_hides_key_bearing_route_url():
    import logging
    from app.services.amap_service import _RedactAmapRouteRequest

    guard = _RedactAmapRouteRequest()
    sensitive = logging.LogRecord("httpx", logging.INFO, __file__, 1,
        "HTTP Request: GET https://restapi.amap.com/v3/direction/transit/integrated?key=fixture",
        (), None)
    ordinary = logging.LogRecord("httpx", logging.INFO, __file__, 1,
        "HTTP Request: GET https://example.com/health", (), None)
    assert not guard.filter(sensitive)
    assert guard.filter(ordinary)


def test_bad_coordinates_are_rejected_before_tool_call():
    runtime = Runtime()
    service = AmapService(runtime)
    with pytest.raises(ToolArgumentError):
        asyncio.run(service.aplan_route_by_coordinates(
            Location(longitude=999, latitude=31), points()[1]))
    assert runtime.calls == []


def test_route_optimizer_uses_candidate_coordinates_not_addresses():
    runtime = Runtime()
    service = AmapService(runtime)
    start, end = points()
    attractions = [
        Attraction(name="A", address="模糊地址", location=start,
                   visit_duration=60, description="fixture"),
        Attraction(name="B", address="另一个模糊地址", location=end,
                   visit_duration=60, description="fixture"),
    ]
    plan = TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
        days=[DayPlan(date="2026-10-01", day_index=0, description="fixture",
                      transportation="步行", accommodation="民宿", attractions=attractions)],
        overall_suggestions="fixture")
    constraints = build_travel_constraints(TripRequest(
        city="上海", start_date="2026-10-01", end_date="2026-10-01",
        transportation="步行", accommodation="民宿"))
    result = RouteOptimizer(service).apply(plan, constraints)
    assert result.days[0].route.is_complete
    assert all(name == "maps_direction_walking_by_coordinates" for name, _ in runtime.calls)
    assert len(runtime.calls) == 2
