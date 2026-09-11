"""Typed Amap adapters backed by the bounded native MCP runtime."""
import asyncio
import math
from datetime import date
from threading import RLock

from pydantic import JsonValue, ValidationError

from ..errors import AppError, ToolArgumentError, ToolProtocolError, UpstreamError
from ..models.schemas import Location, POIInfo, RouteInfo, WeatherInfo
from .tool_runtime import ToolRuntime, get_tool_runtime, parse_payload
from .cache_service import RetrievalCache, cached, get_retrieval_cache, skip_cache_write


def records(payload: JsonValue, key: str) -> list[dict[str, JsonValue]]:
    payload = parse_payload(payload)
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = parse_payload(payload["data"])
    value = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ToolProtocolError()
    return value


def location(value: JsonValue) -> Location:
    if isinstance(value, str) and "," in value:
        lng, lat = value.split(",", 1)
    elif isinstance(value, dict):
        lng, lat = value.get("longitude"), value.get("latitude")
    else:
        raise ToolProtocolError()
    try:
        lng, lat = float(lng), float(lat)
        if not math.isfinite(lng) or not math.isfinite(lat) or not -180 <= lng <= 180 or not -90 <= lat <= 90:
            raise ValueError()
        return Location(longitude=lng, latitude=lat)
    except (TypeError, ValueError) as exc:
        raise ToolProtocolError() from exc


def string(value: JsonValue) -> str:
    # Amap sometimes uses [] for absent optional strings.
    return value.strip() if isinstance(value, str) else ""


class AmapService:
    def __init__(self, runtime: ToolRuntime | None = None, cache: RetrievalCache | None = None):
        self.runtime = runtime or get_tool_runtime()
        self.cache = cache or get_retrieval_cache()

    @cached("poi", list[POIInfo])
    async def asearch_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        result = await self.runtime.call("maps_text_search", {
            "keywords": keywords, "city": city, "citylimit": str(citylimit).lower()})
        items = records(result.payload, "pois")
        pois: list[POIInfo] = []
        # 0.1.11 omits coordinates from search. Hydrate at most six unique IDs per search.
        seen: set[str] = set()
        for item in items:
            poi_id = string(item.get("id"))
            if not poi_id:
                skip_cache_write()
                continue
            if poi_id in seen:
                continue
            if len(seen) == 6:
                break
            seen.add(poi_id)
            try:
                if not item.get("location"):
                    item = await self.aget_poi_detail(poi_id)
                name = string(item.get("name"))
                if not name:
                    raise ToolProtocolError()
                pois.append(POIInfo(id=poi_id, name=name, address=string(item.get("address")),
                    type=string(item.get("type") or item.get("typecode")),
                    location=location(item.get("location")), tel=string(item.get("tel")) or None))
            except AppError:
                # Individual bad details cannot discard valid candidates already retrieved.
                skip_cache_write()
                continue
        if items and not pois:
            raise ToolProtocolError()
        return pois

    @cached("weather", list[WeatherInfo])
    async def aget_weather(self, city: str) -> list[WeatherInfo]:
        result = await self.runtime.call("maps_weather", {"city": city})
        rows = records(result.payload, "forecasts")
        # Accept both server 0.1.11 and direct Amap REST fixture envelopes.
        if rows and "casts" in rows[0]:
            rows = records(rows[0], "casts")
        weather: list[WeatherInfo] = []
        try:
            for row in rows:
                day = date.fromisoformat(string(row.get("date")))
                weather.append(WeatherInfo(date=str(day),
                    day_weather=string(row.get("dayweather")), night_weather=string(row.get("nightweather")),
                    day_temp=int(row["daytemp"]), night_temp=int(row["nighttemp"]),
                    wind_direction=string(row.get("daywind")), wind_power=string(row.get("daypower"))))
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolProtocolError() from exc
        return weather

    async def aget_poi_detail(self, poi_id: str) -> dict[str, JsonValue]:
        result = await self.runtime.call("maps_search_detail", {"id": poi_id})
        data = parse_payload(result.payload)
        if not isinstance(data, dict) or string(data.get("id")) != poi_id or not string(data.get("name")):
            raise ToolProtocolError()
        return data

    @cached("geocode", Location | None)
    async def ageocode(self, address: str, city: str | None = None) -> Location | None:
        arguments = {"address": address}
        if city is not None:
            arguments["city"] = city
        result = await self.runtime.call("maps_geo", arguments)
        rows = records(result.payload, "return")
        return location(rows[0].get("location")) if rows else None

    @cached("route", RouteInfo)
    async def aplan_route(self, origin_address: str, destination_address: str,
                         origin_city: str | None = None, destination_city: str | None = None,
                         route_type: str = "walking") -> RouteInfo:
        tool_map = {"walking": "maps_direction_walking_by_address",
                    "driving": "maps_direction_driving_by_address",
                    "transit": "maps_direction_transit_integrated_by_address"}
        if route_type not in tool_map or (route_type == "transit" and not (origin_city and destination_city)):
            raise ToolArgumentError()
        arguments = {"origin_address": origin_address, "destination_address": destination_address}
        if origin_city is not None:
            arguments["origin_city"] = origin_city
        if destination_city is not None:
            arguments["destination_city"] = destination_city
        result = await self.runtime.call(tool_map[route_type], arguments)
        data = parse_payload(result.payload)
        if not isinstance(data, dict) or not isinstance(data.get("route"), dict):
            raise ToolProtocolError()
        route = data["route"]
        paths = records(route, "transits" if route_type == "transit" else "paths")
        if not paths:
            raise UpstreamError()
        try:
            choices = [RouteInfo(distance=float(path.get("distance", route.get("distance"))),
                        duration=int(path["duration"]), route_type=route_type, description="高德路线") for path in paths]
            if any(not math.isfinite(p.distance) or p.distance < 0 or p.duration < 0 for p in choices):
                raise ValueError()
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ToolProtocolError() from exc
        return min(choices, key=lambda path: (path.duration, path.distance))

    # Compatibility for synchronous map API workers. Retrieval uses the async methods.
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        return asyncio.run(self.asearch_poi(keywords, city, citylimit))

    def get_weather(self, city: str) -> list[WeatherInfo]:
        return asyncio.run(self.aget_weather(city))

    def get_poi_detail(self, poi_id: str) -> dict[str, JsonValue]:
        return asyncio.run(self.aget_poi_detail(poi_id))

    def geocode(self, address: str, city: str | None = None) -> Location | None:
        return asyncio.run(self.ageocode(address, city))

    def plan_route(self, origin_address: str, destination_address: str,
                   origin_city: str | None = None, destination_city: str | None = None,
                   route_type: str = "walking") -> RouteInfo:
        return asyncio.run(self.aplan_route(origin_address, destination_address, origin_city, destination_city, route_type))


_service_lock = RLock()
_amap_service: AmapService | None = None


def get_amap_service() -> AmapService:
    global _amap_service
    with _service_lock:
        if _amap_service is None:
            _amap_service = AmapService()
        return _amap_service


def reset_amap_service() -> None:
    global _amap_service
    with _service_lock:
        _amap_service = None
