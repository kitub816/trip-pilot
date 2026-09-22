"""Bounded deterministic route-matrix construction and daily ordering."""

import asyncio
from typing import Protocol

from ..config import get_settings
from ..errors import AppError
from ..models.schemas import Attraction, DayRoute, Location, RouteInfo, RouteLeg, TripPlan
from .amap_service import get_amap_service
from .constraint_service import TransportationMode, TravelConstraints


class RouteProvider(Protocol):
    async def aplan_route(
        self, origin_address: str, destination_address: str,
        origin_city: str | None = None, destination_city: str | None = None,
        route_type: str = "walking",
    ) -> RouteInfo: ...


class RouteOptimizer:
    """Use a bounded directed matrix and deterministic nearest-neighbour order."""

    def __init__(self, provider: RouteProvider | None = None, *, max_points: int = 6,
                 concurrency: int = 4, leg_timeout: float = 60,
                 matrix_timeout: float = 90):
        if max_points < 2 or concurrency < 1 or leg_timeout <= 0 or matrix_timeout <= 0:
            raise ValueError("invalid route limits")
        self.provider = provider or get_amap_service()
        self.max_points = max_points
        self.concurrency = concurrency
        self.leg_timeout = leg_timeout
        self.matrix_timeout = matrix_timeout

    def apply(self, plan: TripPlan, constraints: TravelConstraints) -> TripPlan:
        return asyncio.run(self.aapply(plan, constraints))

    async def aapply(self, plan: TripPlan, constraints: TravelConstraints) -> TripPlan:
        days = []
        for day in plan.days:
            ordered, summary = await self._optimize_day(list(day.attractions), constraints)
            days.append(day.model_copy(update={"attractions": ordered, "route": summary}))
        return plan.model_copy(update={"days": days})

    async def _optimize_day(
        self, attractions: list[Attraction], constraints: TravelConstraints,
    ) -> tuple[list[Attraction], DayRoute]:
        route_type = self._route_type(constraints.transportation)
        if len(attractions) <= 1:
            return attractions, DayRoute(route_type=route_type)

        points = attractions[:self.max_points]
        trailing = attractions[self.max_points:]
        scheduled = any(item.visit_start is not None for item in points)
        matrix = await self._matrix(points, constraints.city, route_type, adjacent_only=scheduled)
        # Explicit visit times fix the order; reordering would invalidate the schedule.
        order = (list(range(len(points))) if scheduled
                 else self._order(points, matrix, constraints.max_single_transport_minutes))
        ordered = [points[index] for index in order] + trailing
        legs, warnings = self._legs(points, order, matrix, constraints)
        if trailing:
            warnings.append("MATRIX_TRUNCATED")
        warning_codes = list(dict.fromkeys(warnings))
        total_distance = sum(leg.distance or 0 for leg in legs)
        total_duration = sum(leg.duration or 0 for leg in legs)
        complete = not trailing and all(leg.status != "unavailable" for leg in legs)
        within_limits = not any(code in warning_codes for code in (
            "SEGMENT_TIME_EXCEEDED", "DAILY_WALKING_EXCEEDED", "MATRIX_TRUNCATED",
        ))
        return ordered, DayRoute(
            route_type=route_type,
            legs=legs,
            total_distance=total_distance,
            total_duration=total_duration,
            is_complete=complete,
            within_limits=within_limits,
            warning_codes=warning_codes,
        )

    async def _matrix(
        self, points: list[Attraction], city: str, route_type: str,
        *, adjacent_only: bool = False,
    ) -> dict[tuple[int, int], RouteInfo | None]:
        quota = asyncio.Semaphore(self.concurrency)
        matrix: dict[tuple[int, int], RouteInfo | None] = {}

        async def fetch(origin: int, destination: int) -> None:
            async with quota:
                try:
                    coordinate_route = getattr(self.provider, "aplan_route_by_coordinates", None)
                    if coordinate_route is not None:
                        pending = coordinate_route(
                            points[origin].location, points[destination].location,
                            city if route_type == "transit" else None, route_type,
                        )
                    else:
                        pending = self.provider.aplan_route(
                            self._address(points[origin]), self._address(points[destination]),
                            city if route_type == "transit" else None,
                            city if route_type == "transit" else None,
                            route_type,
                        )
                    route = await asyncio.wait_for(pending, timeout=self.leg_timeout)
                except asyncio.CancelledError:
                    raise
                except (AppError, asyncio.TimeoutError, TimeoutError):
                    route = None
                matrix[(origin, destination)] = route

        tasks = [asyncio.create_task(fetch(origin, destination))
                 for origin in range(len(points)) for destination in range(len(points))
                 if (destination == origin + 1 if adjacent_only else origin != destination)]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=self.matrix_timeout)
        except (asyncio.TimeoutError, TimeoutError):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return matrix

    @staticmethod
    def _order(points: list[Attraction], matrix: dict[tuple[int, int], RouteInfo | None],
               max_minutes: int | None) -> list[int]:
        order = [0]
        remaining = set(range(1, len(points)))
        while remaining:
            origin = order[-1]
            candidates = []
            for destination in remaining:
                route = matrix.get((origin, destination))
                if route is None:
                    continue
                over_limit = max_minutes is not None and route.duration > max_minutes * 60
                candidates.append((over_limit, route.duration, route.distance,
                                   destination, points[destination].name.casefold()))
            destination = min(candidates)[3] if candidates else min(remaining)
            order.append(destination)
            remaining.remove(destination)
        return order

    @staticmethod
    def _legs(points: list[Attraction], order: list[int],
              matrix: dict[tuple[int, int], RouteInfo | None],
              constraints: TravelConstraints) -> tuple[list[RouteLeg], list[str]]:
        legs: list[RouteLeg] = []
        warnings: list[str] = []
        route_type = RouteOptimizer._route_type(constraints.transportation)
        for origin, destination in zip(order, order[1:]):
            route = matrix.get((origin, destination))
            if route is None:
                warnings.append("ROUTE_UNAVAILABLE")
                legs.append(RouteLeg(
                    origin_name=points[origin].name,
                    destination_name=points[destination].name,
                    route_type=route_type,
                    status="unavailable",
                ))
                continue
            over_time = (constraints.max_single_transport_minutes is not None
                         and route.duration > constraints.max_single_transport_minutes * 60)
            if over_time:
                warnings.append("SEGMENT_TIME_EXCEEDED")
            legs.append(RouteLeg(
                origin_name=points[origin].name,
                destination_name=points[destination].name,
                distance=route.distance,
                duration=route.duration,
                route_type=route.route_type,
                status="over_time_limit" if over_time else "available",
            ))
        total_distance = sum(leg.distance or 0 for leg in legs)
        if (route_type == "walking" and constraints.max_daily_walking_km is not None
                and total_distance > constraints.max_daily_walking_km * 1000):
            warnings.append("DAILY_WALKING_EXCEEDED")
        return legs, warnings

    @staticmethod
    def _route_type(mode: TransportationMode) -> str:
        return {
            TransportationMode.WALKING: "walking",
            TransportationMode.DRIVING: "driving",
            TransportationMode.PUBLIC_TRANSIT: "transit",
            TransportationMode.MIXED: "transit",
        }[mode]

    @staticmethod
    def _address(attraction: Attraction) -> str:
        return attraction.address.strip() or attraction.name


def get_route_optimizer() -> RouteOptimizer:
    settings = get_settings()
    return RouteOptimizer(
        max_points=settings.route_max_points,
        concurrency=min(settings.route_concurrency, settings.tool_concurrency),
        leg_timeout=settings.route_leg_timeout,
        matrix_timeout=settings.route_matrix_timeout,
    )
