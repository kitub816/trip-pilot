"""Existing MCP mappings; unfinished parsers fail explicitly until Phase 4."""
import json
import re
from threading import RLock
from typing import Any

from hello_agents.tools import MCPTool
from ..config import get_settings
from ..errors import upstream_failure, AppError, ConfigurationError, FeatureUnavailable, UpstreamError
from ..models.schemas import Location, POIInfo, WeatherInfo

_service_lock = RLock()
_tool_call_lock = RLock()
_amap_mcp_tool: MCPTool | None = None
_amap_service: "AmapService | None" = None


def get_amap_mcp_tool() -> MCPTool:
    global _amap_mcp_tool
    with _service_lock:
        if _amap_mcp_tool is None:
            settings = get_settings()
            if not settings.amap_api_key.get_secret_value().strip():
                raise ConfigurationError()
            try:
                tool = MCPTool(name="amap", description="高德地图服务",
                    server_command=["uvx", "amap-mcp-server"],
                    env={"AMAP_MAPS_API_KEY": settings.amap_api_key.get_secret_value()}, auto_expand=True)
                if not tool.get_expanded_tools():
                    raise UpstreamError()
                _amap_mcp_tool = tool
            except AppError:
                raise
            except Exception as exc:
                raise upstream_failure(exc) from exc
        return _amap_mcp_tool


class AmapService:
    @property
    def mcp_tool(self) -> MCPTool:
        return get_amap_mcp_tool()

    def _call_tool(self, tool_name: str, arguments: dict[str, str]) -> Any:
        """Call the shared SDK wrapper serially until Tool Runtime owns sessions."""
        try:
            # MCPTool 0.2.9 has no documented concurrent-session guarantee.
            with _tool_call_lock:
                return self.mcp_tool.run({
                    "action": "call_tool", "tool_name": tool_name, "arguments": arguments,
                })
        except AppError:
            raise
        except Exception as exc:
            raise upstream_failure(exc) from exc

    @staticmethod
    def _json_payload(result: Any) -> dict[str, Any] | list[Any]:
        if isinstance(result, (dict, list)):
            return result
        if not isinstance(result, str):
            raise UpstreamError()
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            match = re.search(r"```(?:json)?\\s*(\\{.*?\\}|\\[.*?\\])\\s*```", result, re.DOTALL)
            if match is None:
                match = re.search(r"(\\{.*\\}|\\[.*\\])", result, re.DOTALL)
            if match is None:
                raise UpstreamError()
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                raise UpstreamError() from exc

    @staticmethod
    def _records(payload: dict[str, Any] | list[Any], *keys: str) -> list[dict[str, Any]]:
        candidate: Any = payload
        if isinstance(candidate, dict) and isinstance(candidate.get("data"), dict):
            candidate = candidate["data"]
        if isinstance(candidate, dict):
            for key in keys:
                if isinstance(candidate.get(key), list):
                    candidate = candidate[key]
                    break
        if not isinstance(candidate, list):
            return []
        return [item for item in candidate if isinstance(item, dict)]

    @staticmethod
    def _location(value: Any) -> Location | None:
        if isinstance(value, dict):
            longitude, latitude = value.get("longitude"), value.get("latitude")
        elif isinstance(value, str) and "," in value:
            longitude, latitude = value.split(",", 1)
        else:
            return None
        try:
            return Location(longitude=float(longitude), latitude=float(latitude))
        except (TypeError, ValueError):
            return None

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        payload = self._json_payload(self._call_tool("maps_text_search", {
            "keywords": keywords, "city": city, "citylimit": str(citylimit).lower()}))
        pois: list[POIInfo] = []
        for item in self._records(payload, "pois"):
            location = self._location(item.get("location"))
            name = item.get("name")
            if not location or not isinstance(name, str) or not name.strip():
                continue
            pois.append(POIInfo(
                id=str(item.get("id") or item.get("poi_id") or ""), name=name.strip(),
                type=str(item.get("type") or item.get("typecode") or ""),
                address=str(item.get("address") or ""), location=location,
                tel=str(item["tel"]) if item.get("tel") else None,
            ))
        return pois

    def get_weather(self, city: str) -> list[WeatherInfo]:
        payload = self._json_payload(self._call_tool("maps_weather", {"city": city}))
        forecasts = self._records(payload, "forecasts")
        casts = forecasts[0].get("casts", []) if forecasts else self._records(payload, "casts")
        if not isinstance(casts, list):
            return []
        return [WeatherInfo(
            date=str(item.get("date") or ""),
            day_weather=str(item.get("dayweather") or item.get("day_weather") or ""),
            night_weather=str(item.get("nightweather") or item.get("night_weather") or ""),
            day_temp=item.get("daytemp") or item.get("day_temp") or 0,
            night_temp=item.get("nighttemp") or item.get("night_temp") or 0,
            wind_direction=str(item.get("daywind") or item.get("wind_direction") or ""),
            wind_power=str(item.get("daypower") or item.get("wind_power") or ""),
        ) for item in casts if isinstance(item, dict)]

    def plan_route(self, origin_address: str, destination_address: str,
                   origin_city: str | None = None, destination_city: str | None = None,
                   route_type: str = "walking") -> dict[str, Any]:
        tool_map = {"walking": "maps_direction_walking_by_address",
                    "driving": "maps_direction_driving_by_address",
                    "transit": "maps_direction_transit_integrated_by_address"}
        arguments = {"origin_address": origin_address, "destination_address": destination_address}
        if origin_city:
            arguments["origin_city"] = origin_city
        if destination_city:
            arguments["destination_city"] = destination_city
        raise FeatureUnavailable()

    def geocode(self, address: str, city: str | None = None) -> Location | None:
        arguments = {"address": address}
        if city:
            arguments["city"] = city
        raise FeatureUnavailable()

    def get_poi_detail(self, poi_id: str) -> dict[str, Any]:
        try:
            data = self._json_payload(self._call_tool("maps_search_detail", {"id": poi_id}))
            if not isinstance(data, dict) or not data or data.get("error") or data.get("status") in (0, "0"):
                raise UpstreamError()
            return data
        except AppError:
            raise
        except Exception as exc:
            raise upstream_failure(exc) from exc


def get_amap_service() -> AmapService:
    global _amap_service
    with _service_lock:
        if _amap_service is None:
            _amap_service = AmapService()
        return _amap_service


def reset_amap_service() -> None:
    """SDK MCPClient contexts close per operation; reset only cached wrappers."""
    global _amap_service, _amap_mcp_tool
    with _service_lock:
        _amap_service = None
        _amap_mcp_tool = None
