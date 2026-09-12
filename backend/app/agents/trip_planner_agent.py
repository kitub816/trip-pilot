"""Structured LLM planner backed by service-provided candidate IDs."""

import json
import logging
from datetime import timedelta
from threading import Lock

from hello_agents import SimpleAgent

from ..config import get_settings
from ..errors import (
    AppError, ConfigurationError, PlanParseError, ServiceBusy, upstream_failure,
)
from ..models.planner import PlannerDraft
from ..models.schemas import (
    Attraction, DayPlan, Hotel, Meal, POIInfo, TripPlan, WeatherInfo,
)
from ..services.constraint_service import TravelConstraints
from ..services.llm_service import get_llm


PLANNER_AGENT_PROMPT = """你是行程规划专家。根据服务端提供的候选ID生成旅行计划。

只返回一个JSON对象，不要输出Markdown代码围栏或解释。严格使用以下格式，不得增加字段：
{
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "transportation_cost": 30,
      "accommodation": "住宿类型",
      "hotel": {
        "candidate_id": "H001",
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "estimated_cost": 400
      },
      "attractions": [
        {
          "candidate_id": "A001",
          "visit_duration": 120,
          "description": "景点安排说明",
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
  "overall_suggestions": "总体建议"
}

要求：
1. 景点和酒店只能填写候选列表中的candidate_id，禁止自行填写名称、地址或坐标
2. 每个日期和day_index必须与请求中的日期序列完全一致
3. 每天安排1-3个景点，且必须包含一次breakfast、lunch、dinner
4. 没有酒店候选时hotel必须为null
5. 单价无法确认时使用null，不要猜测
6. 不要返回city、start_date、end_date、weather_info、route或budget，这些由服务端生成
"""

PLANNER_REPAIR_PROMPT = """上一回复未通过严格校验。请依据最初提供的候选ID和日期重新输出。
只返回一个符合系统JSON格式的对象；不要输出Markdown、解释或新增字段。不得引用列表外的候选ID。"""


class MultiAgentTripPlanner:
    """Single decision Agent; deterministic code validates and hydrates its draft."""

    def __init__(self):
        settings = get_settings()
        if not settings.amap_api_key.get_secret_value().strip():
            raise ConfigurationError()
        self._run_lock = Lock()
        self._repair_attempts = settings.planner_repair_attempts
        self._max_response_chars = settings.planner_max_response_chars
        self.llm = get_llm()
        try:
            self.planner_agent = SimpleAgent(
                name="行程规划专家", llm=self.llm, system_prompt=PLANNER_AGENT_PROMPT,
            )
        except AppError:
            raise
        except Exception as exc:
            raise upstream_failure(exc) from exc

    def _clear_history(self) -> None:
        agent = getattr(self, "planner_agent", None)
        if agent is not None:
            agent.clear_history()

    def plan_from_retrieval(
        self,
        request: TravelConstraints,
        attractions: tuple[POIInfo, ...],
        weather: tuple[WeatherInfo, ...],
        hotels: tuple[POIInfo, ...],
    ) -> TripPlan:
        """Plan from typed candidates and allow only a bounded format repair."""
        if not self._run_lock.acquire(blocking=False):
            raise ServiceBusy()
        try:
            self._clear_history()
            logger.info("planning.started")
            attraction_payload, attraction_catalog = self._candidate_catalog(attractions, "A")
            hotel_payload, hotel_catalog = self._candidate_catalog(hotels, "H")
            query = self._build_planner_query(
                request,
                json.dumps(attraction_payload, ensure_ascii=False),
                json.dumps([item.model_dump(mode="json") for item in weather], ensure_ascii=False),
                json.dumps(hotel_payload, ensure_ascii=False),
            )
            response = self.planner_agent.run(query)
            plan: TripPlan | None = None
            repair_attempts = getattr(self, "_repair_attempts", 1)
            for attempt in range(repair_attempts + 1):
                try:
                    plan = self._parse_response(
                        response, request, attraction_catalog, hotel_catalog, weather,
                    )
                    break
                except PlanParseError:
                    if attempt >= repair_attempts:
                        raise
                    logger.info("planning.format_repair", extra={"attempt": attempt + 1})
                    response = self.planner_agent.run(PLANNER_REPAIR_PROMPT)
            if plan is None:
                raise PlanParseError()
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

    def plan_trip(self, request: TravelConstraints) -> TripPlan:
        """Compatibility entry point delegates retrieval to the existing Service."""
        from ..models.schemas import TripRequest
        from ..services.constraint_service import build_travel_constraints
        from ..services.retrieval_service import retrieve_trip_context

        if isinstance(request, TripRequest):
            request = build_travel_constraints(request)
        context = retrieve_trip_context(request)
        return self.plan_from_retrieval(
            request, context.attractions, context.weather, context.hotels,
        )

    def _build_planner_query(
        self,
        request: TravelConstraints,
        attractions: str,
        weather: str,
        hotels: str = "",
    ) -> str:
        query = f"""请根据以下信息生成{request.city}的{request.travel_days}天旅行计划：

基本信息：
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

景点候选（只能引用candidate_id）：
{attractions}

天气事实（不要复制到输出）：
{weather}

酒店候选（只能引用candidate_id）：
{hotels}

输出要求：
1. 日期与day_index覆盖请求中的每一天且顺序一致
2. 每天安排1-3个景点并包含早中晚三餐
3. 有酒店候选时选择一个candidate_id；没有候选时hotel为null
4. 不得填写候选外的景点或酒店
5. 只返回系统要求的JSON对象
"""
        if request.free_text_input:
            query += f"\n额外要求：{request.free_text_input}"
        return query

    @staticmethod
    def _candidate_catalog(
        candidates: tuple[POIInfo, ...], prefix: str,
    ) -> tuple[list[dict[str, object]], dict[str, POIInfo]]:
        payload: list[dict[str, object]] = []
        catalog: dict[str, POIInfo] = {}
        for index, candidate in enumerate(candidates, start=1):
            candidate_id = f"{prefix}{index:03d}"
            catalog[candidate_id] = candidate
            payload.append({
                "candidate_id": candidate_id,
                "name": candidate.name,
                "type": candidate.type,
                "address": candidate.address,
                "location": candidate.location.model_dump(mode="json"),
            })
        return payload, catalog

    def _parse_response(
        self,
        response: str,
        request: TravelConstraints,
        attractions: dict[str, POIInfo] | None = None,
        hotels: dict[str, POIInfo] | None = None,
        weather: tuple[WeatherInfo, ...] = (),
    ) -> TripPlan:
        """Validate the private LLM schema, then hydrate trusted domain models."""
        try:
            if not isinstance(response, str) or len(response) > getattr(
                self, "_max_response_chars", 50000,
            ):
                raise ValueError("invalid response size")
            payload = response.strip()
            if payload.startswith("```json") and payload.endswith("```"):
                payload = payload[7:-3].strip()
            elif payload.startswith("```") and payload.endswith("```"):
                payload = payload[3:-3].strip()
            if not (payload.startswith("{") and payload.endswith("}")):
                raise ValueError("response must contain only one JSON object")
            draft = PlannerDraft.model_validate(json.loads(payload))
            return self._hydrate_plan(
                draft, request, attractions or {}, hotels or {}, weather,
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise PlanParseError() from exc

    @staticmethod
    def _hydrate_plan(
        draft: PlannerDraft,
        request: TravelConstraints,
        attractions: dict[str, POIInfo],
        hotels: dict[str, POIInfo],
        weather: tuple[WeatherInfo, ...],
    ) -> TripPlan:
        expected_dates = [
            request.start_date + timedelta(days=index)
            for index in range(request.travel_days)
        ]
        if len(draft.days) != len(expected_dates):
            raise ValueError("plan day count does not match request")
        days: list[DayPlan] = []
        for index, (day, expected_date) in enumerate(zip(draft.days, expected_dates)):
            if day.day_index != index or day.date != expected_date:
                raise ValueError("plan date sequence does not match request")
            selected_attractions: list[Attraction] = []
            for selection in day.attractions:
                candidate = attractions.get(selection.candidate_id)
                if candidate is None:
                    raise ValueError("unknown attraction candidate")
                selected_attractions.append(Attraction(
                    name=candidate.name,
                    address=candidate.address,
                    location=candidate.location,
                    visit_duration=selection.visit_duration,
                    description=selection.description,
                    category=candidate.type,
                    poi_id=candidate.id,
                    ticket_price=selection.ticket_price,
                ))
            selected_hotel = None
            if day.hotel is not None:
                candidate = hotels.get(day.hotel.candidate_id)
                if candidate is None:
                    raise ValueError("unknown hotel candidate")
                selected_hotel = Hotel(
                    name=candidate.name,
                    address=candidate.address,
                    location=candidate.location,
                    price_range=day.hotel.price_range,
                    rating=day.hotel.rating,
                    distance=day.hotel.distance,
                    type=candidate.type,
                    estimated_cost=day.hotel.estimated_cost,
                )
            days.append(DayPlan(
                date=day.date.isoformat(),
                day_index=day.day_index,
                description=day.description,
                transportation=day.transportation,
                transportation_cost=day.transportation_cost,
                accommodation=day.accommodation,
                hotel=selected_hotel,
                attractions=selected_attractions,
                meals=[Meal(**meal.model_dump()) for meal in day.meals],
            ))
        expected_date_strings = {item.isoformat() for item in expected_dates}
        return TripPlan(
            city=request.city,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            days=days,
            weather_info=[item for item in weather if item.date in expected_date_strings],
            overall_suggestions=draft.overall_suggestions,
        )


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
    """Clear request history and release the singleton after handlers drain."""
    global _multi_agent_planner
    with _init_lock:
        if _multi_agent_planner is not None:
            with _multi_agent_planner._run_lock:
                _multi_agent_planner._clear_history()
                _multi_agent_planner = None
