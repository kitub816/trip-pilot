"""Scheduled visits are checked against duration and actual route legs."""

import asyncio

import pytest
from pydantic import ValidationError

from app.models.schemas import Attraction, Budget, DayPlan, DayRoute, Location, RouteLeg, TripPlan, TripRequest
from app.services.constraint_service import build_travel_constraints
from app.services.route_service import RouteOptimizer
from app.services.validation_service import PlanValidator


def attraction(name, start, end, duration=60):
    return Attraction(name=name, address=name, location=Location(longitude=121, latitude=31),
                      visit_duration=duration, visit_start=start, visit_end=end,
                      description="fixture", poi_id=name)


def plan(items, leg_seconds=600):
    return TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
                    days=[DayPlan(date="2026-10-01", day_index=0, description="fixture",
                                  transportation="步行", accommodation="民宿", attractions=items,
                                  route=DayRoute(route_type="walking", legs=[
                                      RouteLeg(origin_name=items[0].name, destination_name=items[1].name,
                                               duration=leg_seconds, route_type="walking",
                                               status="available")] if len(items) > 1 else []))],
                    overall_suggestions="fixture", budget=Budget())


def constraints():
    return build_travel_constraints(TripRequest(city="上海", start_date="2026-10-01",
        end_date="2026-10-01", transportation="步行", accommodation="民宿"))


def test_time_window_requires_both_endpoints():
    with pytest.raises(ValidationError):
        attraction("A", "09:00", None)


def test_time_window_rejects_timezone_offsets():
    with pytest.raises(ValidationError):
        attraction("A", "09:00Z", "10:00Z")


def test_valid_schedule_and_transport_gap():
    result = PlanValidator().validate(plan([
        attraction("A", "09:00", "10:00"), attraction("B", "10:10", "11:10")]), constraints())
    assert result.is_valid
    assert not result.violations


@pytest.mark.parametrize("items,leg_seconds,code", [
    ([("A", "09:00", "09:30", 60)], 0, "VISIT_DURATION_CONFLICT"),
    ([("A", "23:30", "00:30", 60)], 0, "VISIT_TIME_INVALID"),
    ([("A", "09:00", "10:00", 60), ("B", "10:05", "11:05", 60)], 600, "VISIT_TIME_CONFLICT"),
])
def test_invalid_schedule_is_hard_violation(items, leg_seconds, code):
    source = plan([attraction(*item) for item in items], leg_seconds)
    result = PlanValidator().validate(source, constraints())
    assert code in {item.code for item in result.errors}


class Provider:
    async def aplan_route(self, origin, destination, origin_city=None, destination_city=None, route_type="walking"):
        from app.models.schemas import RouteInfo
        return RouteInfo(distance=1, duration=1 if origin == "A" else 100,
                         route_type=route_type, description="fixture")


def test_route_optimizer_keeps_scheduled_order():
    source = plan([attraction("A", "09:00", "10:00"),
                   attraction("B", "10:10", "11:10"),
                   attraction("C", "11:20", "12:20")])
    result = asyncio.run(RouteOptimizer(Provider()).aapply(source, constraints()))
    assert [item.name for item in result.days[0].attractions] == ["A", "B", "C"]
