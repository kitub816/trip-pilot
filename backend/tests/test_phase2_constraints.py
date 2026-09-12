from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import main
from app.api.routes import trip
from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.models.schemas import (
    AccommodationType,
    TransportationMode,
    TripPlan,
    TripRequest,
)
from app.services.constraint_service import (
    ExtractedConstraints,
    TravelConstraints,
    build_travel_constraints,
)


LEGACY_REQUEST = {
    "city": "上海",
    "start_date": "2026-10-01",
    "end_date": "2026-10-03",
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化"],
    "free_text_input": "希望安排博物馆",
}


def test_legacy_request_derives_inclusive_duration():
    request = TripRequest(**LEGACY_REQUEST)
    assert request.start_date == date(2026, 10, 1)
    assert request.end_date == date(2026, 10, 3)
    assert request.travel_days == 3
    assert request.transportation is TransportationMode.PUBLIC_TRANSIT
    assert request.accommodation is AccommodationType.ECONOMY_HOTEL


def test_matching_legacy_travel_days_is_accepted():
    assert TripRequest(**LEGACY_REQUEST, travel_days=3).travel_days == 3


@pytest.mark.parametrize(
    "updates",
    [
        {"travel_days": 2},
        {"start_date": "2026-10-04"},
        {"end_date": "2026-11-01"},
        {"transportation": "飞机"},
        {"accommodation": "随便"},
        {"travelers": 0},
        {"budget_limit": 0},
        {"currency": "USD"},
        {"max_daily_walking_km": 101},
        {"max_single_transport_minutes": 0},
        {"must_visit": "外滩"},
        {"avoid_places": [123]},
        {"preferences": "历史文化"},
    ],
)
def test_invalid_or_inconsistent_requests_are_rejected(updates):
    with pytest.raises(ValidationError):
        TripRequest(**{**LEGACY_REQUEST, **updates})


def test_constraints_normalize_lists_and_apply_defaults():
    request = TripRequest(**{
        **LEGACY_REQUEST,
        "must_visit": [" 外滩 ", "外滩", "豫园"],
        "avoid_places": ["迪士尼", " 迪士尼 "],
        "preferences": [" 历史文化 ", "历史文化", "美食"],
    })
    constraints = build_travel_constraints(request)
    assert constraints.travelers == 1
    assert constraints.currency == "CNY"
    assert constraints.must_visit == ("外滩", "豫园")
    assert constraints.avoid_places == ("迪士尼",)
    assert constraints.preferences == ("历史文化", "美食")
    assert constraints.requires_semantic_extraction is True


def test_explicit_fields_override_extraction_and_empty_list_is_explicit():
    request = TripRequest(
        **LEGACY_REQUEST,
        travelers=2,
        budget_limit="5000.50",
        must_visit=[],
        max_daily_walking_km=8,
    )
    extracted = ExtractedConstraints(
        travelers=6,
        budget_limit="9000",
        must_visit=["不应采用"],
        avoid_places=["酒吧"],
        max_daily_walking_km=20,
        max_single_transport_minutes=45,
    )
    constraints = build_travel_constraints(request, extracted)
    assert constraints.travelers == 2
    assert constraints.budget_limit == Decimal("5000.50")
    assert constraints.must_visit == ()
    assert constraints.avoid_places == ("酒吧",)
    assert constraints.max_daily_walking_km == 8
    assert constraints.max_single_transport_minutes == 45


def test_extraction_only_fills_omitted_structured_fields():
    request = TripRequest(**{**LEGACY_REQUEST, "free_text_input": ""})
    constraints = build_travel_constraints(
        request,
        ExtractedConstraints(travelers=3, budget_limit="1200", must_visit=["外滩"]),
    )
    assert constraints.travelers == 3
    assert constraints.budget_limit == Decimal("1200")
    assert constraints.must_visit == ("外滩",)
    assert constraints.requires_semantic_extraction is False


def test_required_and_avoided_place_conflict_is_rejected_case_insensitively():
    with pytest.raises(ValidationError):
        TripRequest(
            **LEGACY_REQUEST,
            must_visit=["The Bund"],
            avoid_places=["the bund"],
        )


def test_constraint_model_is_immutable():
    constraints = build_travel_constraints(TripRequest(**LEGACY_REQUEST))
    with pytest.raises(ValidationError):
        constraints.travelers = 4
    with pytest.raises(AttributeError):
        constraints.must_visit.append("外滩")


def test_planner_prompt_receives_normalized_hard_constraints():
    constraints = build_travel_constraints(TripRequest(
        **LEGACY_REQUEST,
        travelers=2,
        budget_limit="5000",
        must_visit=["外滩"],
        avoid_places=["酒吧"],
        max_daily_walking_km=8,
        max_single_transport_minutes=45,
    ))
    planner = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    prompt = planner._build_planner_query(constraints, "pois", "weather", "hotels")
    for expected in ("出行人数: 2", "5000 CNY", "必去地点: 外滩", "避开地点: 酒吧", "8.0公里", "45分钟"):
        assert expected in prompt


def test_trip_endpoint_passes_normalized_constraints(monkeypatch):
    received: list[TravelConstraints] = []

    def plan(constraints: TravelConstraints) -> TripPlan:
        received.append(constraints)
        return TripPlan(
            city=constraints.city,
            start_date=str(constraints.start_date),
            end_date=str(constraints.end_date),
            days=[],
            overall_suggestions="fixture",
        )

    monkeypatch.setattr(trip, "get_trip_workflow", lambda: SimpleNamespace(plan=plan))
    with TestClient(main.create_app()) as client:
        response = client.post("/api/trip/plan", json=LEGACY_REQUEST)
    assert response.status_code == 200
    assert len(received) == 1
    assert isinstance(received[0], TravelConstraints)
    assert received[0].travel_days == 3


def test_trip_endpoint_rejects_duration_conflict_before_planner(monkeypatch):
    called = False

    def get_planner():
        nonlocal called
        called = True
        raise AssertionError("planner must not be initialized")

    monkeypatch.setattr(trip, "get_trip_planner_agent", get_planner)
    with TestClient(main.create_app()) as client:
        response = client.post(
            "/api/trip/plan",
            json={**LEGACY_REQUEST, "travel_days": 2},
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert called is False


def test_trip_endpoint_rejects_place_conflict_as_validation_error():
    with TestClient(main.create_app()) as client:
        response = client.post(
            "/api/trip/plan",
            json={
                **LEGACY_REQUEST,
                "must_visit": ["外滩"],
                "avoid_places": ["外滩"],
            },
        )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
