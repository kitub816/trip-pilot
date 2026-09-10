"""Typed, partial-failure-tolerant trip retrieval orchestration."""

import asyncio
import anyio
from dataclasses import dataclass
from typing import Protocol

from ..models.schemas import POIInfo, WeatherInfo
from .amap_service import get_amap_service
from ..errors import AppError, NoCandidates, UpstreamTimeout
from .constraint_service import TravelConstraints


class MapRetriever(Protocol):
    async def asearch_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]: ...
    async def aget_weather(self, city: str) -> list[WeatherInfo]: ...


@dataclass(frozen=True)
class RetrievalWarning:
    source: str
    code: str


@dataclass(frozen=True)
class TripRetrievalResult:
    attractions: tuple[POIInfo, ...]
    hotels: tuple[POIInfo, ...]
    weather: tuple[WeatherInfo, ...]
    warnings: tuple[RetrievalWarning, ...]


class TripRetrievalService:
    """Run independent searches concurrently while keeping individual failures visible."""

    def __init__(self, map_service: MapRetriever | None = None, *, timeout: float = 60) -> None:
        self._map_service = map_service or get_amap_service()
        self._timeout = timeout

    async def retrieve(self, constraints: TravelConstraints) -> TripRetrievalResult:
        keywords = tuple(dict.fromkeys(("景点", *constraints.must_visit, *constraints.preferences)))
        jobs = [
            (f"attraction:{index}", lambda keyword=keyword: self._map_service.asearch_poi(keyword, constraints.city))
            for index, keyword in enumerate(keywords)
        ]
        jobs.extend([
            ("hotel", lambda: self._map_service.asearch_poi(str(constraints.accommodation), constraints.city)),
            ("weather", lambda: self._map_service.aget_weather(constraints.city)),
        ])
        quota = asyncio.Semaphore(3)

        async def run(job):
            # Includes local queue time; expired tasks never start another tool call.
            try:
                with anyio.fail_after(self._timeout):
                    async with quota:
                        return await job()
            except TimeoutError as exc:
                raise UpstreamTimeout() from exc

        results = await asyncio.gather(*(run(job) for _, job in jobs), return_exceptions=True)
        attractions: list[POIInfo] = []
        hotels: list[POIInfo] = []
        weather: list[WeatherInfo] = []
        warnings: list[RetrievalWarning] = []
        for (source, _), result in zip(jobs, results):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                warnings.append(RetrievalWarning(source=source, code=result.code if isinstance(result, AppError) else "UPSTREAM_ERROR"))
            elif source == "hotel":
                hotels.extend(result)
            elif source == "weather":
                weather.extend(result)
            else:
                attractions.extend(result)
        if not attractions:
            raise NoCandidates()
        return TripRetrievalResult(
            attractions=self._dedupe(attractions), hotels=self._dedupe(hotels),
            weather=tuple(weather), warnings=tuple(warnings),
        )

    @staticmethod
    def _dedupe(pois: list[POIInfo]) -> tuple[POIInfo, ...]:
        seen: set[str] = set()
        result: list[POIInfo] = []
        for poi in pois:
            key = poi.id or poi.name.casefold()
            if key not in seen:
                seen.add(key)
                result.append(poi)
        return tuple(result)


def retrieve_trip_context(constraints: TravelConstraints, service: TripRetrievalService | None = None) -> TripRetrievalResult:
    """Synchronous bridge used by the current sync FastAPI worker and LangGraph node."""
    return asyncio.run((service or TripRetrievalService()).retrieve(constraints))
