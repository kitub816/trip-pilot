"""Deterministic visit windows follow measured route durations."""

from datetime import time

from app.models.schemas import Attraction, Location, RouteLeg
from app.services.route_service import RouteOptimizer


def attraction(name: str, start: time, end: time, duration: int) -> Attraction:
    return Attraction(
        name=name,
        address=f"{name}地址",
        location=Location(longitude=108.9, latitude=34.2),
        visit_duration=duration,
        visit_start=start,
        visit_end=end,
        description="fixture",
    )


def test_measured_travel_shifts_later_visit_and_recomputes_end():
    visits = [
        attraction("A", time(9, 0), time(11, 0), 120),
        attraction("B", time(11, 5), time(12, 5), 60),
    ]
    legs = [RouteLeg(
        origin_name="A",
        destination_name="B",
        distance=1000,
        duration=901,
        route_type="transit",
        status="available",
    )]

    aligned = RouteOptimizer._align_visit_windows(visits, legs)

    assert aligned[0].visit_start == time(9, 0)
    assert aligned[0].visit_end == time(11, 0)
    assert aligned[1].visit_start == time(11, 16)
    assert aligned[1].visit_end == time(12, 16)


def test_unavailable_leg_does_not_invent_a_travel_duration():
    visits = [
        attraction("A", time(9, 0), time(10, 0), 60),
        attraction("B", time(10, 5), time(11, 5), 60),
    ]
    legs = [RouteLeg(
        origin_name="A",
        destination_name="B",
        route_type="transit",
        status="unavailable",
    )]

    aligned = RouteOptimizer._align_visit_windows(visits, legs)

    assert aligned[1].visit_start == time(10, 5)
    assert aligned[1].visit_end == time(11, 5)
