"""Deterministic validation findings and bounded LangGraph replan behavior."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.errors import PlanValidationError
from app.agents.trip_planner_agent import MultiAgentTripPlanner
from app.api.routes import trip
from app.models.schemas import (
    Attraction, Budget, DayPlan, DayRoute, Location, TripPlan, TripPlanUpdateRequest, TripRequest,
)
from app.models.validation import PlanValidationResult, PlanViolation
from app.services.constraint_service import build_travel_constraints
from app.services.retrieval_service import TripRetrievalResult
from app.services.validation_service import PlanValidator
from app.workflows import trip_workflow
from app.workflows.trip_workflow import TripPlanningWorkflow


def constraints(**updates):
    values = {
        "city": "上海",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "transportation": "步行",
        "accommodation": "民宿",
        "budget_limit": "100",
        "must_visit": ["外滩"],
        "avoid_places": ["迪士尼"],
    }
    values.update(updates)
    return build_travel_constraints(TripRequest(**values))


def attraction(name: str, poi_id: str) -> Attraction:
    return Attraction(
        name=name, poi_id=poi_id, address="测试地址",
        location=Location(longitude=121.4, latitude=31.2),
        visit_duration=60, description="fixture", ticket_price=0,
    )


def day(index: int, item: Attraction) -> DayPlan:
    return DayPlan(
        date=f"2026-10-0{index + 1}", day_index=index,
        description="fixture", transportation="步行", transportation_cost=0,
        accommodation="民宿", attractions=[item], meals=[],
        route=DayRoute(route_type="walking"),
    )


def plan(*, total=100, complete=True, days=None) -> TripPlan:
    return TripPlan(
        city="上海", start_date="2026-10-01", end_date="2026-10-02",
        days=days or [
            day(0, attraction("上海外滩", "bund")),
            day(1, attraction("豫园", "yuyuan")),
        ],
        overall_suggestions="fixture",
        budget=Budget(total=total, is_complete=complete),
    )


def codes(result: PlanValidationResult) -> set[str]:
    return {item.code for item in result.violations}


def test_clean_derived_plan_has_no_validation_errors():
    result = PlanValidator().validate(plan(), constraints())
    assert result.is_valid is True
    assert result.violations == []


def test_budget_exceeded_is_error_but_unknown_cost_is_warning():
    exceeded = PlanValidator().validate(plan(total=101), constraints())
    assert codes(exceeded) == {"BUDGET_EXCEEDED"}
    assert exceeded.is_valid is False

    incomplete = PlanValidator().validate(plan(total=99, complete=False), constraints())
    assert codes(incomplete) == {"BUDGET_INCOMPLETE"}
    assert incomplete.is_valid is True


def test_required_avoided_and_duplicate_places_are_explicit():
    source = plan(days=[
        day(0, attraction("迪士尼乐园", "disney")),
        day(1, attraction("迪士尼乐园", "disney")),
    ])
    result = PlanValidator().validate(source, constraints())
    assert codes(result) == {
        "MUST_VISIT_MISSING", "AVOID_PLACE_INCLUDED", "DUPLICATE_ATTRACTION",
    }
    assert all(item.severity == "error" for item in result.violations)


def test_day_count_and_date_sequence_are_checked_independently():
    source = plan(days=[day(1, attraction("上海外滩", "bund"))])
    result = PlanValidator().validate(source, constraints())
    assert codes(result) == {"PLAN_DAY_COUNT_MISMATCH", "PLAN_DATE_MISMATCH"}


def test_route_warning_codes_have_deterministic_validation_severity():
    source = plan(days=[
        day(0, attraction("上海外滩", "bund")).model_copy(update={
            "route": DayRoute(
                route_type="walking", is_complete=False, within_limits=False,
                warning_codes=[
                    "ROUTE_UNAVAILABLE", "SEGMENT_TIME_EXCEEDED",
                    "DAILY_WALKING_EXCEEDED", "MATRIX_TRUNCATED",
                ],
            ),
        }),
        day(1, attraction("南京路", "nanjing-road")),
    ])
    result = PlanValidator().validate(source, constraints())
    assert codes(result) == {
        "ROUTE_UNAVAILABLE", "SEGMENT_TIME_EXCEEDED",
        "DAILY_WALKING_EXCEEDED", "ROUTE_MATRIX_TRUNCATED",
    }
    assert next(item for item in result.violations if item.code == "ROUTE_MATRIX_TRUNCATED").severity == "warning"


def test_missing_route_is_an_error_only_when_day_has_multiple_attractions():
    source = plan(days=[
        day(0, attraction("上海外滩", "bund")).model_copy(update={
            "attractions": [attraction("上海外滩", "bund"), attraction("豫园", "yuyuan")],
            "route": None,
        }),
        day(1, attraction("南京路", "nanjing-road")),
    ])
    assert codes(PlanValidator().validate(source, constraints())) == {"ROUTE_MISSING"}


def test_validate_or_raise_uses_safe_validation_error():
    with pytest.raises(PlanValidationError):
        PlanValidator().validate_or_raise(plan(total=101), constraints())


def test_plan_update_revalidates_before_persistence(monkeypatch):
    store = SimpleNamespace(
        get=lambda _: SimpleNamespace(request=TripRequest(
            city="上海", start_date="2026-10-01", end_date="2026-10-02",
            transportation="步行", accommodation="民宿", budget_limit="100",
        )),
        replace=Mock(),
    )
    validator = SimpleNamespace(validate_or_raise=Mock(side_effect=PlanValidationError()))
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(trip, "get_route_optimizer", lambda: PassThrough([], "route"))
    monkeypatch.setattr(trip, "get_budget_engine", lambda: PassThrough([], "budget"))
    monkeypatch.setattr(trip, "get_plan_validator", lambda: validator)
    with pytest.raises(PlanValidationError):
        trip.update_plan("plan-id", TripPlanUpdateRequest(expected_version=1, data=plan()))
    validator.validate_or_raise.assert_called_once()
    store.replace.assert_not_called()


def test_planner_replan_passes_only_typed_violations_to_the_existing_generator():
    planner = MultiAgentTripPlanner.__new__(MultiAgentTripPlanner)
    planner.plan_from_retrieval = Mock(return_value=plan())
    violations = (PlanViolation(
        code="MUST_VISIT_MISSING", severity="error", subject="外滩",
    ),)
    assert planner.replan_from_retrieval(constraints(), (), (), (), violations).city == "上海"
    revision = planner.plan_from_retrieval.call_args.kwargs["revision_instructions"]
    assert "MUST_VISIT_MISSING" in revision and "外滩" in revision


class PassThrough:
    def __init__(self, events, name):
        self.events = events
        self.name = name

    def apply(self, value, received):
        self.events.append(self.name)
        return value


class ReplanPlanner:
    def __init__(self, invalid, valid):
        self.invalid = invalid
        self.valid = valid
        self.replans = []

    def plan_from_retrieval(self, *args):
        return self.invalid

    def replan_from_retrieval(self, *args):
        self.replans.append(args[-1])
        return self.valid


def test_workflow_replans_once_then_returns_valid_plan(monkeypatch):
    invalid = plan(days=[
        day(0, attraction("迪士尼乐园", "disney")),
        day(1, attraction("豫园", "yuyuan")),
    ])
    valid = plan()
    planner = ReplanPlanner(invalid, valid)
    events = []
    monkeypatch.setattr(
        trip_workflow, "retrieve_trip_context",
        lambda _: TripRetrievalResult((), (), (), ()),
    )
    workflow = TripPlanningWorkflow(
        planner_factory=lambda: planner,
        route_optimizer=PassThrough(events, "route"),
        budget_engine=PassThrough(events, "budget"),
        max_replan_attempts=1,
    )
    assert workflow.plan(constraints()).days[0].attractions[0].name == "上海外滩"
    assert events == ["route", "budget", "route", "budget"]
    assert {item.code for item in planner.replans[0]} == {
        "MUST_VISIT_MISSING", "AVOID_PLACE_INCLUDED",
    }


def test_workflow_stops_at_replan_limit(monkeypatch):
    invalid = plan(days=[
        day(0, attraction("迪士尼乐园", "disney")),
        day(1, attraction("豫园", "yuyuan")),
    ])
    planner = ReplanPlanner(invalid, invalid)
    monkeypatch.setattr(
        trip_workflow, "retrieve_trip_context",
        lambda _: TripRetrievalResult((), (), (), ()),
    )
    workflow = TripPlanningWorkflow(
        planner_factory=lambda: planner,
        route_optimizer=PassThrough([], "route"),
        budget_engine=PassThrough([], "budget"),
        max_replan_attempts=1,
    )
    with pytest.raises(PlanValidationError):
        workflow.plan(constraints())
    assert len(planner.replans) == 1
