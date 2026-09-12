"""Bounded route matrices, deterministic ordering, limits, and partial failure."""

import asyncio
from types import SimpleNamespace

import pytest

from app.errors import UpstreamError
from app.models.schemas import Attraction, DayPlan, Location, RouteInfo, TripPlan, TripRequest
from app.models.validation import PlanValidationResult
from app.services.constraint_service import build_travel_constraints
from app.services.route_service import RouteOptimizer
from app.workflows.trip_workflow import TripPlanningWorkflow


def attraction(name: str) -> Attraction:
    return Attraction(
        name=name,
        address=name,
        location=Location(longitude=121.4, latitude=31.2),
        visit_duration=60,
        description="fixture",
        ticket_price=0,
    )


def plan(names: list[str]) -> TripPlan:
    return TripPlan(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-01",
        days=[DayPlan(
            date="2026-10-01",
            day_index=0,
            description="fixture",
            transportation="步行",
            transportation_cost=0,
            accommodation="民宿",
            attractions=[attraction(name) for name in names],
            meals=[],
        )],
        overall_suggestions="fixture",
    )


def constraints(mode="步行", **updates):
    values = dict(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-01",
        transportation=mode,
        accommodation="民宿",
    )
    values.update(updates)
    return build_travel_constraints(TripRequest(**values))


class MatrixProvider:
    def __init__(self, routes=None, *, delay=0):
        self.routes = routes or {}
        self.delay = delay
        self.calls = []
        self.active = 0
        self.max_active = 0

    async def aplan_route(self, origin, destination, origin_city=None,
                          destination_city=None, route_type="walking"):
        self.calls.append((origin, destination, origin_city, destination_city, route_type))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            value = self.routes.get((origin, destination), (9999, 9999))
            if isinstance(value, Exception):
                raise value
            distance, duration = value
            return RouteInfo(
                distance=distance,
                duration=duration,
                route_type=route_type,
                description="fixture",
            )
        finally:
            self.active -= 1


def test_directed_matrix_produces_reproducible_nearest_neighbour_order():
    routes = {
        ("A", "B"): (100, 10), ("A", "C"): (100, 5), ("A", "D"): (100, 8),
        ("C", "B"): (100, 2), ("C", "D"): (100, 6), ("B", "D"): (100, 1),
    }
    provider = MatrixProvider(routes)
    result = RouteOptimizer(provider).apply(plan(["A", "B", "C", "D"]), constraints())
    day = result.days[0]
    assert [item.name for item in day.attractions] == ["A", "C", "B", "D"]
    assert [(leg.origin_name, leg.destination_name) for leg in day.route.legs] == [
        ("A", "C"), ("C", "B"), ("B", "D"),
    ]
    assert day.route.total_duration == 8
    assert len(provider.calls) == 12
    assert result is not None


@pytest.mark.parametrize(
    "mode,route_type,needs_city",
    [("步行", "walking", False), ("自驾", "driving", False),
     ("公共交通", "transit", True), ("混合", "transit", True)],
)
def test_transportation_mode_maps_to_supported_amap_route(mode, route_type, needs_city):
    provider = MatrixProvider({("A", "B"): (10, 10), ("B", "A"): (10, 10)})
    result = RouteOptimizer(provider).apply(plan(["A", "B"]), constraints(mode))
    assert result.days[0].route.route_type == route_type
    assert all(call[4] == route_type for call in provider.calls)
    assert all((call[2] == "上海") is needs_city for call in provider.calls)


def test_matrix_is_bounded_and_concurrency_is_limited():
    provider = MatrixProvider(delay=0.01)
    result = RouteOptimizer(provider, max_points=3, concurrency=2).apply(
        plan(["A", "B", "C", "D", "E"]), constraints()
    )
    assert len(provider.calls) == 6
    assert provider.max_active == 2
    assert result.days[0].route.is_complete is False
    assert "MATRIX_TRUNCATED" in result.days[0].route.warning_codes
    assert [item.name for item in result.days[0].attractions][-2:] == ["D", "E"]


def test_unreachable_selected_leg_is_explicit_not_fabricated():
    routes = {
        ("A", "B"): UpstreamError(), ("A", "C"): (100, 1),
        ("C", "B"): UpstreamError(),
    }
    result = RouteOptimizer(MatrixProvider(routes)).apply(
        plan(["A", "B", "C"]), constraints()
    )
    route = result.days[0].route
    assert [item.name for item in result.days[0].attractions] == ["A", "C", "B"]
    assert route.legs[-1].status == "unavailable"
    assert route.legs[-1].distance is None
    assert route.is_complete is False
    assert route.warning_codes == ["ROUTE_UNAVAILABLE"]


def test_time_limit_affects_order_and_marks_unavoidable_over_limit_leg():
    routes = {
        ("A", "B"): (100, 600), ("A", "C"): (100, 100),
        ("C", "B"): (100, 700),
    }
    result = RouteOptimizer(MatrixProvider(routes)).apply(
        plan(["A", "B", "C"]),
        constraints(max_single_transport_minutes=5),
    )
    route = result.days[0].route
    assert [item.name for item in result.days[0].attractions] == ["A", "C", "B"]
    assert route.legs[-1].status == "over_time_limit"
    assert "SEGMENT_TIME_EXCEEDED" in route.warning_codes
    assert route.within_limits is False


def test_daily_walking_limit_uses_selected_route_distance():
    routes = {
        ("A", "B"): (1200, 100), ("B", "C"): (1200, 100),
        ("A", "C"): (5000, 1000),
    }
    result = RouteOptimizer(MatrixProvider(routes)).apply(
        plan(["A", "B", "C"]),
        constraints(max_daily_walking_km=2),
    )
    route = result.days[0].route
    assert route.total_distance == 2400
    assert route.within_limits is False
    assert "DAILY_WALKING_EXCEEDED" in route.warning_codes


def test_route_cancellation_propagates():
    class CancelProvider:
        async def aplan_route(self, *args, **kwargs):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(RouteOptimizer(CancelProvider()).aapply(plan(["A", "B"]), constraints()))


def test_matrix_deadline_cancels_slow_calls_and_marks_route_unavailable():
    closed = []

    class SlowProvider:
        async def aplan_route(self, *args, **kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                closed.append(True)

    result = RouteOptimizer(
        SlowProvider(), concurrency=2, leg_timeout=20, matrix_timeout=0.02,
    ).apply(plan(["A", "B"]), constraints())
    route = result.days[0].route
    assert route.is_complete is False
    assert route.warning_codes == ["ROUTE_UNAVAILABLE"]
    assert closed == [True, True]


def test_workflow_runs_route_before_budget():
    events = []
    original = plan([])

    class Route:
        def apply(self, value, received):
            events.append("route")
            return value.model_copy(update={"overall_suggestions": "routed"})

    class Budget:
        def apply(self, value, received):
            assert value.overall_suggestions == "routed"
            events.append("budget")
            return value

    workflow = TripPlanningWorkflow(
        planner_factory=lambda: SimpleNamespace(plan_trip=lambda _: original),
        route_optimizer=Route(),
        budget_engine=Budget(),
        validator=SimpleNamespace(validate=lambda *_: PlanValidationResult()),
    )
    assert workflow.plan(constraints()).overall_suggestions == "routed"
    assert events == ["route", "budget"]
