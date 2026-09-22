"""Regression for observed transit throttling and unhelpful revision feedback."""
import asyncio
import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.errors import ToolRateLimit
from app.services.amap_service import AmapService
from app.services.route_service import RouteOptimizer
from app.services.validation_service import PlanValidator
from evaluation.live_smoke import ToolEventCounter
from test_phase19_time_windows import attraction, plan, constraints, Provider
from test_phase20_coordinate_routes import points, Runtime


@pytest.mark.parametrize("recover", [True, False])
def test_http_200_rate_limit_has_one_bounded_retry(monkeypatch, recover):
    import app.services.amap_service as module
    monkeypatch.setattr(module, "get_settings", lambda: SimpleNamespace(
        amap_api_key=SecretStr("fixture"), tool_timeout=1))
    attempts = []
    def handler(request):
        attempts.append(1)
        if recover and len(attempts) == 2:
            return httpx.Response(200, json={"status": "1", "route": {"transits": [
                {"distance": "500", "duration": "600"}]}})
        return httpx.Response(200, json={"status": "0", "infocode": "10021"})
    service = AmapService(Runtime(), transit_transport=httpx.MockTransport(handler))
    if recover:
        assert asyncio.run(service.aplan_route_by_coordinates(*points(), "上海", "transit")).duration == 600
    else:
        with pytest.raises(ToolRateLimit):
            asyncio.run(service.aplan_route_by_coordinates(*points(), "上海", "transit"))
    assert len(attempts) == 2


def test_scheduled_route_queries_only_required_directed_legs():
    class CountingProvider(Provider):
        def __init__(self):
            self.calls = []
        async def aplan_route(self, origin, destination, *args):
            self.calls.append((origin, destination))
            return await super().aplan_route(origin, destination, *args)
    provider = CountingProvider()
    source = plan([attraction("A", "09:00", "10:00"),
                   attraction("B", "10:10", "11:10"),
                   attraction("C", "11:20", "12:20")])
    result = RouteOptimizer(provider).apply(source, constraints())
    assert provider.calls == [("A", "B"), ("B", "C")]
    assert result.days[0].route.is_complete


def test_replan_feedback_contains_observed_gap_and_required_duration():
    result = PlanValidator().validate(plan([
        attraction("A", "09:00", "10:00"),
        attraction("B", "10:30", "11:30")], 4105), constraints())
    finding = next(v for v in result.errors if v.code == "VISIT_TIME_CONFLICT")
    assert finding.origin == "A" and finding.subject == "B"
    assert finding.required_travel_seconds == 4105
    assert finding.available_gap_seconds == 1800


def test_live_counter_formats_error_arguments_and_validation_codes():
    counter = ToolEventCounter()
    counter.emit(logging.LogRecord("trippilot.tools", logging.WARNING, __file__, 1,
        "tool.failed.%s.%s", ("maps_direction_transit_direct", "TOOL_RATE_LIMIT"), None))
    counter.emit(logging.LogRecord("trippilot.workflow", logging.INFO, __file__, 1,
        "validation.finding.%s.%s", ("error", "VISIT_TIME_CONFLICT"), None))
    assert counter.failed == 1
    assert counter.failure_codes["tool.failed.maps_direction_transit_direct.TOOL_RATE_LIMIT"] == 1
    assert counter.validation_codes["validation.finding.error.VISIT_TIME_CONFLICT"] == 1


@pytest.mark.parametrize("operation", ["get", "set"])
def test_cache_total_deadline_is_normalized_and_cancels_work(monkeypatch, operation):
    from redis.exceptions import TimeoutError as RedisTimeoutError
    from app.services.cache_service import RedisBackend

    async def run():
        cancelled = asyncio.Event()
        async def stall(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        backend = RedisBackend("redis://unused", timeout=0.01)
        monkeypatch.setattr(backend, "_" + operation, stall)
        with pytest.raises(RedisTimeoutError):
            if operation == "get":
                await backend.get("fixture")
            else:
                await backend.set("fixture", b"value", 1)
        assert cancelled.is_set()
    asyncio.run(run())
