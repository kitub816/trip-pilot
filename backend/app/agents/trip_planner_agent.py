"""多智能体旅行规划系统"""

import json
import logging
from threading import Lock
from hello_agents import SimpleAgent
from hello_agents.tools import MCPTool
from ..services.llm_service import get_llm
from ..models.schemas import TripPlan
from ..services.constraint_service import TravelConstraints
from ..errors import upstream_failure, AppError, ConfigurationError, PlanParseError, ServiceBusy, UpstreamError
from ..config import get_settings

# ============ Agent提示词 ============

ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。你的任务是根据城市和用户偏好搜索合适的景点。

**重要提示:**
你必须使用工具来搜索景点!不要自己编造景点信息!

**工具调用格式:**
使用maps_text_search工具时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=景点关键词,city=城市名]`

**示例:**
用户: "搜索北京的历史文化景点"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=北京]

用户: "搜索上海的公园"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=公园,city=上海]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
3. 参数用逗号分隔
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。你的任务是查询指定城市的天气信息。

**重要提示:**
你必须使用工具来查询天气!不要自己编造天气信息!

**工具调用格式:**
使用maps_weather工具时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_weather:city=城市名]`

**示例:**
用户: "查询北京天气"
你的回复: [TOOL_CALL:amap_maps_weather:city=北京]

用户: "上海的天气怎么样"
你的回复: [TOOL_CALL:amap_maps_weather:city=上海]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
"""

HOTEL_AGENT_PROMPT = """你是酒店推荐专家。你的任务是根据城市和景点位置推荐合适的酒店。

**重要提示:**
你必须使用工具来搜索酒店!不要自己编造酒店信息!

**工具调用格式:**
使用maps_text_search工具搜索酒店时,必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=酒店,city=城市名]`

**示例:**
用户: "搜索北京的酒店"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=酒店,city=北京]

**注意:**
1. 必须使用工具,不要直接回答
2. 格式必须完全正确,包括方括号和冒号
3. 关键词使用"酒店"或"宾馆"
"""

PLANNER_AGENT_PROMPT = """你是行程规划专家。你的任务是根据景点信息和天气信息,生成详细的旅行计划。

请严格按照以下JSON格式返回旅行计划:
```json
{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "hotel": {
        "name": "酒店名称",
        "address": "酒店地址",
        "location": {"longitude": 116.397128, "latitude": 39.916527},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "经济型酒店",
        "estimated_cost": 400
      },
      "attractions": [
        {
          "name": "景点名称",
          "address": "详细地址",
          "location": {"longitude": 116.397128, "latitude": 39.916527},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }
      ],
      "meals": [
        {"type": "breakfast", "name": "早餐推荐", "description": "早餐描述", "estimated_cost": 30},
        {"type": "lunch", "name": "午餐推荐", "description": "午餐描述", "estimated_cost": 50},
        {"type": "dinner", "name": "晚餐推荐", "description": "晚餐描述", "estimated_cost": 80}
      ]
    }
  ],
  "weather_info": [
    {
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }
  ],
  "overall_suggestions": "总体建议",
  "budget": {
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }
}
```

**重要提示:**
1. weather_info数组必须包含每一天的天气信息
2. 温度必须是纯数字(不要带°C等单位)
3. 每天安排2-3个景点
4. 考虑景点之间的距离和游览时间
5. 每天必须包含早中晚三餐
6. 提供实用的旅行建议
7. **必须包含预算信息**:
   - 景点门票价格(ticket_price)
   - 餐饮预估费用(estimated_cost)
   - 酒店预估费用(estimated_cost)
   - 预算汇总(budget)包含各项总费用
"""


class MultiAgentTripPlanner:
    """Legacy sequential workflow; serialize access and clear all request history."""

    def __init__(self):
        settings = get_settings()
        if not settings.amap_api_key.get_secret_value().strip():
            raise ConfigurationError()
        self._run_lock = Lock()
        self.llm = get_llm()
        try:
            self.amap_tool = MCPTool(name="amap", description="高德地图服务",
                server_command=["uvx", "amap-mcp-server"],
                env={"AMAP_MAPS_API_KEY": settings.amap_api_key.get_secret_value()}, auto_expand=True)
            self.amap_tool.expandable = True
            if not self.amap_tool.get_expanded_tools():
                raise UpstreamError()
            self.attraction_agent = SimpleAgent(name="景点搜索专家", llm=self.llm, system_prompt=ATTRACTION_AGENT_PROMPT)
            self.weather_agent = SimpleAgent(name="天气查询专家", llm=self.llm, system_prompt=WEATHER_AGENT_PROMPT)
            self.hotel_agent = SimpleAgent(name="酒店推荐专家", llm=self.llm, system_prompt=HOTEL_AGENT_PROMPT)
            self.planner_agent = SimpleAgent(name="行程规划专家", llm=self.llm, system_prompt=PLANNER_AGENT_PROMPT)
            for agent in (self.attraction_agent, self.weather_agent, self.hotel_agent):
                agent.add_tool(self.amap_tool)
        except AppError:
            raise
        except Exception as exc:
            raise upstream_failure(exc) from exc

    def _clear_history(self) -> None:
        for agent in (self.attraction_agent, self.weather_agent, self.hotel_agent, self.planner_agent):
            agent.clear_history()

    def plan_trip(self, request: TravelConstraints) -> TripPlan:
        # Temporary isolation until request-scoped LangGraph state is introduced.
        # Reject overlap instead of accumulating unbounded work behind a slow model.
        if not self._run_lock.acquire(blocking=False):
            raise ServiceBusy()
        try:
            self._clear_history()
            logger.info("planning.started")
            attractions = self.attraction_agent.run(self._build_attraction_query(request))
            weather = self.weather_agent.run(f"请查询{request.city}的天气信息")
            hotels = self.hotel_agent.run(f"请搜索{request.city}的{request.accommodation}酒店")
            response = self.planner_agent.run(self._build_planner_query(request, attractions, weather, hotels))
            plan = self._parse_response(response, request)
            logger.info("planning.completed")
            return plan
        except AppError:
            raise
        except Exception as exc:
            raise upstream_failure(exc) from exc
        finally:
            try:
                self._clear_history()
            finally:
                self._run_lock.release()

    def _build_attraction_query(self, request: TravelConstraints) -> str:
        """构建景点搜索查询 - 直接包含工具调用"""
        keywords = "景点"
        if request.preferences:
            # 只取第一个偏好作为关键词
            keywords = request.preferences[0]
        else:
            keywords = "景点"

        # 直接返回工具调用格式
        query = f"请使用amap_maps_text_search工具搜索{request.city}的{keywords}相关景点。\n[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={request.city}]"
        return query

    def _build_planner_query(self, request: TravelConstraints, attractions: str, weather: str, hotels: str = "") -> str:
        """构建行程规划查询"""
        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划:

**基本信息:**
- 城市: {request.city}
- 日期: {request.start_date} 至 {request.end_date}
- 天数: {request.travel_days}天
- 交通方式: {request.transportation}
- 住宿: {request.accommodation}
- 偏好: {', '.join(request.preferences) if request.preferences else '无'}
- 出行人数: {request.travelers}
- 总预算上限: {f'{request.budget_limit} {request.currency}' if request.budget_limit is not None else '未指定'}
- 必去地点: {', '.join(request.must_visit) if request.must_visit else '无'}
- 避开地点: {', '.join(request.avoid_places) if request.avoid_places else '无'}
- 每日步行上限: {f'{request.max_daily_walking_km}公里' if request.max_daily_walking_km is not None else '未指定'}
- 单段交通时间上限: {f'{request.max_single_transport_minutes}分钟' if request.max_single_transport_minutes is not None else '未指定'}

**景点信息:**
{attractions}

**天气信息:**
{weather}

**酒店信息:**
{hotels}

**要求:**
1. 每天安排2-3个景点
2. 每天必须包含早中晚三餐
3. 每天推荐一个具体的酒店(从酒店信息中选择)
3. 考虑景点之间的距离和交通方式
4. 返回完整的JSON格式数据
5. 景点的经纬度坐标要真实准确
"""
        if request.free_text_input:
            query += f"\n**额外要求:** {request.free_text_input}"

        return query
    
    def _parse_response(self, response: str, request: TravelConstraints) -> TripPlan:
        """Retain legacy JSON extraction, but never fabricate a fallback plan."""
        try:
            if "```" in response:
                marker = "```json" if "```json" in response else "```"
                start = response.index(marker) + len(marker)
                end = response.find("```", start)
                if end < 0:
                    raise ValueError("Unclosed JSON fence")
                payload = response[start:end].strip()
            elif "{" in response and "}" in response:
                payload = response[response.index("{"):response.rfind("}") + 1]
            else:
                raise ValueError("Missing JSON")
            return TripPlan.model_validate(json.loads(payload))
        except (ValueError, TypeError, AttributeError) as exc:
            raise PlanParseError() from exc


logger = logging.getLogger("trippilot.planner")
_multi_agent_planner: MultiAgentTripPlanner | None = None
_init_lock = Lock()


def get_trip_planner_agent() -> MultiAgentTripPlanner:
    global _multi_agent_planner
    if not _init_lock.acquire(blocking=False):
        raise ServiceBusy()
    try:
        if _multi_agent_planner is None:
            _multi_agent_planner = MultiAgentTripPlanner()
        return _multi_agent_planner
    finally:
        _init_lock.release()


def reset_trip_planner() -> None:
    """ASGI shutdown drains sync handlers first; reset references after drain.

    MCPTool 0.2.9 opens/closes MCPClient in an async context per operation;
    it exposes no persistent session close method.
    """
    global _multi_agent_planner
    with _init_lock:
        if _multi_agent_planner is not None:
            with _multi_agent_planner._run_lock:
                _multi_agent_planner._clear_history()
                _multi_agent_planner = None
