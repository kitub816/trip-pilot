"""Strict candidate references, deterministic hydration, and bounded repair."""

import json
from threading import Lock

import pytest

from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.errors import PlanParseError
from app.models.schemas import Location, POIInfo, TripRequest, WeatherInfo
from app.services.constraint_service import build_travel_constraints


ATTRACTION = POIInfo(
    id="amap-attraction", name="真实景点", type="博物馆", address="可信景点地址",
    location=Location(longitude=121.4737, latitude=31.2304),
)
HOTEL = POIInfo(
    id="amap-hotel", name="真实酒店", type="舒适型酒店", address="可信酒店地址",
    location=Location(longitude=121.48, latitude=31.22),
)
WEATHER = WeatherInfo(
    date="2026-10-01", day_weather="晴", night_weather="多云",
    day_temp=25, night_temp=18,
)


def constraints():
    return build_travel_constraints(TripRequest(
        city="上海", start_date="2026-10-01", end_date="2026-10-02",
        transportation="公共交通", accommodation="舒适型酒店",
    ))


def day(date: str, index: int, *, attraction_id="A001", hotel_id="H001"):
    return {
        "date": date,
        "day_index": index,
        "description": "按天气安排",
        "transportation": "公共交通",
        "transportation_cost": None,
        "accommodation": "舒适型酒店",
        "hotel": None if hotel_id is None else {
            "candidate_id": hotel_id,
            "price_range": "未知",
            "rating": "",
            "distance": "",
            "estimated_cost": None,
        },
        "attractions": [{
            "candidate_id": attraction_id,
            "visit_duration": 90,
            "description": "参观",
            "ticket_price": None,
        }],
        "meals": [
            {"type": kind, "name": kind, "description": None, "estimated_cost": None}
            for kind in ("breakfast", "lunch", "dinner")
        ],
    }


def draft(**updates):
    value = {
        "days": [day("2026-10-01", 0), day("2026-10-02", 1)],
        "overall_suggestions": "fixture",
    }
    value.update(updates)
    return value


def planner():
    value = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    value._max_response_chars = 50000
    return value


def catalogs():
    return {"A001": ATTRACTION}, {"H001": HOTEL}


def parse(value, *, weather=(WEATHER,)):
    attraction_catalog, hotel_catalog = catalogs()
    return planner()._parse_response(
        json.dumps(value), constraints(), attraction_catalog, hotel_catalog, weather,
    )


def test_candidate_catalog_uses_stable_scoped_ids_and_minimal_payload():
    payload, catalog = planner()._candidate_catalog((ATTRACTION,), "A")
    assert payload == [{
        "candidate_id": "A001", "name": "真实景点", "type": "博物馆",
        "address": "可信景点地址",
        "location": {"longitude": 121.4737, "latitude": 31.2304},
    }]
    assert catalog == {"A001": ATTRACTION}
    assert "amap-attraction" not in json.dumps(payload, ensure_ascii=False)


def test_valid_draft_hydrates_trusted_candidate_and_request_facts():
    result = parse(draft())
    attraction = result.days[0].attractions[0]
    assert (result.city, result.start_date, result.end_date) == (
        "上海", "2026-10-01", "2026-10-02",
    )
    assert (attraction.name, attraction.address, attraction.poi_id) == (
        "真实景点", "可信景点地址", "amap-attraction",
    )
    assert result.days[0].hotel.name == "真实酒店"
    assert result.weather_info == [WEATHER]
    assert result.budget is None and result.days[0].route is None


def test_unknown_hotel_text_fields_accept_null_without_inventing_facts():
    value = draft()
    for day_value in value["days"]:
        day_value["hotel"].update(price_range=None, rating=None, distance=None)
    result = parse(value)
    assert all(item.hotel.price_range == "" and item.hotel.rating == ""
               and item.hotel.distance == "" for item in result.days)


@pytest.mark.parametrize("kind", ["attraction", "hotel"])
def test_unknown_candidate_id_is_rejected(kind):
    value = draft()
    if kind == "attraction":
        value["days"][0]["attractions"][0]["candidate_id"] = "A999"
    else:
        value["days"][0]["hotel"]["candidate_id"] = "H999"
    with pytest.raises(PlanParseError):
        parse(value)


@pytest.mark.parametrize(
    "days",
    [
        [day("2026-10-01", 0)],
        [day("2026-10-01", 0), day("2026-10-03", 1)],
        [day("2026-10-01", 1), day("2026-10-02", 0)],
    ],
)
def test_day_count_dates_and_indexes_must_match_request(days):
    with pytest.raises(PlanParseError):
        parse(draft(days=days))


def test_extra_domain_fields_cannot_spoof_server_facts():
    value = draft(city="伪造城市")
    value["days"][0]["attractions"][0]["name"] = "伪造景点"
    with pytest.raises(PlanParseError):
        parse(value)


def test_each_day_requires_exactly_one_main_meal():
    value = draft()
    value["days"][0]["meals"][2]["type"] = "lunch"
    with pytest.raises(PlanParseError):
        parse(value)


def test_oversized_or_prose_wrapped_response_is_rejected():
    value = planner()
    value._max_response_chars = 10
    with pytest.raises(PlanParseError):
        value._parse_response(json.dumps(draft()), constraints())
    value._max_response_chars = 50000
    with pytest.raises(PlanParseError):
        value._parse_response("结果如下：" + json.dumps(draft()), constraints())


class SequenceAgent:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.clear_count = 0

    def run(self, query):
        self.calls.append(query)
        return next(self.responses)

    def clear_history(self):
        self.clear_count += 1


def runnable(responses):
    value = planner()
    value._run_lock = Lock()
    value._repair_attempts = 1
    value.planner_agent = SequenceAgent(responses)
    return value


def test_one_invalid_response_gets_one_bounded_repair():
    value = runnable(["invalid", json.dumps(draft())])
    result = value.plan_from_retrieval(
        constraints(), (ATTRACTION,), (WEATHER,), (HOTEL,),
    )
    assert result.city == "上海"
    assert len(value.planner_agent.calls) == 2
    assert "上一回复未通过严格校验" in value.planner_agent.calls[1]
    assert value.planner_agent.clear_count == 2


def test_repair_is_not_repeated_after_configured_limit():
    value = runnable(["invalid", "still invalid", json.dumps(draft())])
    with pytest.raises(PlanParseError):
        value.plan_from_retrieval(
            constraints(), (ATTRACTION,), (WEATHER,), (HOTEL,),
        )
    assert len(value.planner_agent.calls) == 2
    assert value.planner_agent.clear_count == 2


def test_prompt_contains_only_scoped_ids_and_no_instruction_to_invent_coordinates():
    attraction_payload, _ = planner()._candidate_catalog((ATTRACTION,), "A")
    hotel_payload, _ = planner()._candidate_catalog((HOTEL,), "H")
    prompt = planner()._build_planner_query(
        constraints(), json.dumps(attraction_payload, ensure_ascii=False), "[]",
        json.dumps(hotel_payload, ensure_ascii=False),
    )
    assert "A001" in prompt and "H001" in prompt
    assert "经纬度坐标要真实准确" not in prompt
    assert "不得填写候选外" in prompt
