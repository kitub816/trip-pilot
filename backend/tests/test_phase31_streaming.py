"""Progress events correspond to completed workflow work, not elapsed time."""
import json
import asyncio
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import main
from app.api.routes import trip
from app.errors import ServiceBusy
from app.models.schemas import TripPlan, TripPlanResponse, TripRequest
from app.models.validation import PlanValidationResult
from app.services.constraint_service import build_travel_constraints
from app.services.retrieval_service import TripRetrievalResult
from app.services.persistence_service import PlanStore
from app.workflows import trip_workflow


REQUEST = {
    "city": "上海", "start_date": "2026-10-01", "end_date": "2026-10-01",
    "transportation": "步行", "accommodation": "民宿",
}


def test_workflow_reports_only_completed_stages(monkeypatch):
    stages = []
    constraints = build_travel_constraints(TripRequest.model_validate(REQUEST))
    plan = TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
                    days=[], overall_suggestions="fixture")
    retrieval = TripRetrievalResult((), (), (), ())
    monkeypatch.setattr(trip_workflow, "retrieve_trip_context", lambda _: retrieval)
    monkeypatch.setattr(trip_workflow, "retrieve_trip_evidence",
                        lambda *_: SimpleNamespace(evidence=()))
    workflow = trip_workflow.TripPlanningWorkflow(
        planner_factory=lambda: SimpleNamespace(plan_trip=lambda _: plan),
        route_optimizer=SimpleNamespace(apply=lambda value, _: value),
        budget_engine=SimpleNamespace(apply=lambda value, _: value),
        validator=SimpleNamespace(validate=lambda *_: PlanValidationResult()),
        on_progress=stages.append,
    )
    assert workflow.plan(constraints).city == "上海"
    assert stages == ["retrieved", "drafted", "routed", "budgeted", "validated"]


def _events(body: str):
    return [(line.split("\n", 1)[0][7:], json.loads(line.split("data: ", 1)[1]))
            for line in body.strip().split("\n\n") if line.startswith("event: ")]


def test_stream_sends_progress_then_persisted_result(monkeypatch):
    plan = TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
                    days=[], overall_suggestions="fixture")

    def run(_request, recovery_id, _owner, callback):
        assert recovery_id == "a" * 32
        callback("retrieved")
        callback("validated")
        return TripPlanResponse(success=True, message="ok", data=plan,
                                plan_id=recovery_id, version=2)

    monkeypatch.setattr(trip, "_plan_trip", run)
    with TestClient(main.create_app()) as client:
        response = client.post("/api/trip/plan/stream", json=REQUEST,
                               headers={"X-Trip-Plan-ID": "a" * 32})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [(event, data.get("stage")) for event, data in events[:2]] == [
        ("progress", "retrieved"), ("progress", "validated")]
    assert events[-1][0] == "result"
    assert events[-1][1]["plan_id"] == "a" * 32
    assert events[-1][1]["version"] == 2


def test_stream_emits_safe_terminal_error(monkeypatch):
    def fail(*_args):
        raise ServiceBusy()

    monkeypatch.setattr(trip, "_plan_trip", fail)
    with TestClient(main.create_app()) as client:
        response = client.post("/api/trip/plan/stream", json=REQUEST)
    events = _events(response.text)
    assert events == [("error", {"error_code": "SERVICE_BUSY",
                                "message": ServiceBusy.message, "status_code": 503})]


def test_progress_is_available_before_planning_finishes(monkeypatch):
    release = Event()

    def run(_request, _recovery_id, _owner, callback):
        callback("retrieved")
        assert release.wait(5)
        plan = TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
                        days=[], overall_suggestions="fixture")
        return TripPlanResponse(success=True, message="ok", data=plan)

    monkeypatch.setattr(trip, "_plan_trip", run)
    response = trip.stream_plan_trip(TripRequest.model_validate(REQUEST))
    async def read():
        stream = response.body_iterator
        try:
            first = await stream.__anext__()
            assert _events(first)[0] == ("progress", {"stage": "retrieved"})
            release.set()
            assert _events(await stream.__anext__())[0][0] == "result"
        finally:
            release.set()
            await stream.aclose()

    asyncio.run(read())


def test_stream_result_follows_durable_store_completion(tmp_path, monkeypatch):
    store = PlanStore(f"sqlite+pysqlite:///{(tmp_path / 'plans.db').as_posix()}")
    store.initialize()
    plan = TripPlan(city="上海", start_date="2026-10-01", end_date="2026-10-01",
                    days=[], overall_suggestions="fixture")
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(trip, "get_checkpoint_path", lambda: tmp_path / "checkpoints.sqlite")
    monkeypatch.setattr(trip, "get_trip_planner_agent",
                        lambda: SimpleNamespace(plan_trip=lambda _: plan))
    monkeypatch.setattr(trip_workflow, "retrieve_trip_context",
                        lambda _: TripRetrievalResult((), (), (), ()))
    monkeypatch.setattr(trip_workflow, "retrieve_trip_evidence",
                        lambda *_: SimpleNamespace(evidence=()))
    monkeypatch.setattr(trip_workflow, "get_route_optimizer",
                        lambda: SimpleNamespace(apply=lambda value, _: value))
    monkeypatch.setattr(trip_workflow, "get_budget_engine",
                        lambda: SimpleNamespace(apply=lambda value, _: value))
    monkeypatch.setattr(trip_workflow, "get_plan_validator",
                        lambda: SimpleNamespace(validate=lambda *_: PlanValidationResult()))
    owner = "1" * 64
    recovery_id = "b" * 32
    with TestClient(main.create_app()) as client:
        response = client.post("/api/trip/plan/stream", json=REQUEST, headers={
            "X-Trip-Plan-ID": recovery_id, "X-Trip-Owner-Token": owner,
        })
        events = _events(response.text)
        assert [data["stage"] for event, data in events if event == "progress"] == [
            "started", "retrieved", "drafted", "routed", "budgeted", "validated",
        ]
        assert events[-1][0] == "result"
        assert events[-1][1]["plan_id"] == recovery_id
        assert events[-1][1]["version"] == 2
        stored = client.get(f"/api/trip/plans/{recovery_id}",
                            headers={"X-Trip-Owner-Token": owner})
        assert stored.json()["status"] == "completed"
        assert stored.json()["data"]["city"] == "上海"
    store.close()
