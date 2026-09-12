from types import SimpleNamespace

import pytest

from app.errors import ServiceBusy
from app.models.schemas import TripPlan, TripRequest
from app.models.validation import PlanValidationResult
from app.services.constraint_service import build_travel_constraints
from app.workflows.trip_workflow import TripPlanningWorkflow


class PassValidator:
    def validate(self, plan, constraints):
        return PlanValidationResult()


REQUEST = {
    "city": "上海",
    "start_date": "2026-10-01",
    "end_date": "2026-10-02",
    "transportation": "步行",
    "accommodation": "民宿",
}


def test_workflow_runs_request_scoped_typed_state():
    constraints = build_travel_constraints(TripRequest(**REQUEST))
    calls = []

    def factory():
        return SimpleNamespace(plan_trip=lambda received: calls.append(received) or TripPlan(
            city=received.city,
            start_date=str(received.start_date),
            end_date=str(received.end_date),
            days=[],
            overall_suggestions="fixture",
        ))

    workflow = TripPlanningWorkflow(planner_factory=factory, validator=PassValidator())
    assert workflow.plan(constraints).city == "上海"
    assert calls == [constraints]


def test_workflow_exposes_app_error_in_terminal_failure_state():
    constraints = build_travel_constraints(TripRequest(**REQUEST))
    workflow = TripPlanningWorkflow(
        planner_factory=lambda: SimpleNamespace(plan_trip=lambda _: (_ for _ in ()).throw(ServiceBusy()))
    )
    state = workflow._graph.invoke({
        "constraints": constraints,
        "status": "planning",
        "plan": None,
        "error": None,
    })
    assert state["status"] == "failed"
    assert isinstance(state["error"], ServiceBusy)
    with pytest.raises(ServiceBusy):
        workflow.plan(constraints)
