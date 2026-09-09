"""Existing MCP mappings; unfinished parsers fail explicitly until Phase 4."""
import json
import re
from threading import RLock
from typing import Any, NoReturn

from hello_agents.tools import MCPTool
from ..config import get_settings
from ..errors import upstream_failure, AppError, ConfigurationError, FeatureUnavailable, UpstreamError
from ..models.schemas import Location, POIInfo, WeatherInfo

_service_lock = RLock()
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

    def _unparsed(self, tool_name: str, arguments: dict[str, str]) -> NoReturn:
        # Retain the original tool/argument mapping without spending an external
        # request on a response we cannot yet parse. Implement this in Phase 4.
        raise FeatureUnavailable()

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        return self._unparsed("maps_text_search", {
            "keywords": keywords, "city": city, "citylimit": str(citylimit).lower()})

    def get_weather(self, city: str) -> list[WeatherInfo]:
        return self._unparsed("maps_weather", {"city": city})

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
        return self._unparsed(tool_map.get(route_type, tool_map["walking"]), arguments)

    def geocode(self, address: str, city: str | None = None) -> Location | None:
        arguments = {"address": address}
        if city:
            arguments["city"] = city
        return self._unparsed("maps_geo", arguments)

    def get_poi_detail(self, poi_id: str) -> dict[str, Any]:
        try:
            result = self.mcp_tool.run({"action": "call_tool", "tool_name": "maps_search_detail", "arguments": {"id": poi_id}})
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if not match:
                raise UpstreamError()
            data = json.loads(match.group())
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
