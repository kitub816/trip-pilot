"""Typed, partial-failure-tolerant trip retrieval orchestration."""

import asyncio
from dataclasses import dataclass
from typing import Protocol

from ..models.schemas import POIInfo, WeatherInfo
from .amap_service import AmapService, get_amap_service
from .constraint_service import TravelConstraints


class MapRetriever(Protocol):
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]: ...
    def get_weather(self, city: str) -> list[WeatherInfo]: ...


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

    def __init__(self, map_service: MapRetriever | None = None) -> None:
        self._map_service = map_service or get_amap_service()

    async def retrieve(self, constraints: TravelConstraints) -> TripRetrievalResult:
        keywords = tuple(dict.fromkeys(("景点", *constraints.preferences)))
        jobs = [
            (f"attraction:{keyword}", asyncio.to_thread(self._map_service.search_poi, keyword, constraints.city))
            for keyword in keywords
        ]
        jobs.extend([
            ("hotel", asyncio.to_thread(self._map_service.search_poi, str(constraints.accommodation), constraints.city)),
            ("weather", asyncio.to_thread(self._map_service.get_weather, constraints.city)),
        ])
        results = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        attractions: list[POIInfo] = []
        hotels: list[POIInfo] = []
        weather: list[WeatherInfo] = []
        warnings: list[RetrievalWarning] = []
        for (source, _), result in zip(jobs, results):
            if isinstance(result, BaseException):
                warnings.append(RetrievalWarning(source=source, code="UPSTREAM_ERROR"))
            elif source == "hotel":
                hotels.extend(result)
            elif source == "weather":
                weather.extend(result)
            else:
                attractions.extend(result)
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
