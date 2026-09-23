"""HTTP and browser-facing recovery contract for durable trip planning."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import main
from app.api.routes import trip
from app.models.schemas import TripPlan
from app.models.validation import PlanValidationResult
from app.services.persistence_service import PlanStore
from app.workflows.trip_workflow import TripPlanningWorkflow


REQUEST = {
    "city": "上海",
    "start_date": "2026-10-01",
    "end_date": "2026-10-01",
    "transportation": "步行",
    "accommodation": "民宿",
}
RECOVERY_ID = "a" * 32


def sqlite_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'plans.db').as_posix()}"


def test_http_resume_continues_checkpoint_without_repeating_planner(tmp_path, monkeypatch):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    calls: list[str] = []
    should_interrupt = [True]

    def make_workflow(saver):
        def plan(constraints):
            calls.append("plan")
            return TripPlan(
                city=constraints.city,
                start_date=str(constraints.start_date),
                end_date=str(constraints.end_date),
                days=[],
                overall_suggestions="fixture",
            )

        def route(plan_value, _constraints):
            calls.append("route")
            if should_interrupt and should_interrupt.pop(0):
                raise RuntimeError("simulated process interruption")
            return plan_value

        return TripPlanningWorkflow(
            checkpointer=saver,
            planner_factory=lambda: SimpleNamespace(plan_trip=plan),
            route_optimizer=SimpleNamespace(apply=route),
            budget_engine=SimpleNamespace(apply=lambda value, _: value),
            validator=SimpleNamespace(
                validate=lambda *_: PlanValidationResult()
            ),
        )

    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(trip, "get_checkpoint_path", lambda: tmp_path / "workflow.sqlite")
    monkeypatch.setattr(trip, "build_durable_workflow", make_workflow)

    with TestClient(main.create_app()) as client:
        interrupted = client.post(
            "/api/trip/plan",
            json=REQUEST,
            headers={"X-Trip-Plan-ID": RECOVERY_ID},
        )
        assert interrupted.status_code == 500
        pending = client.get(f"/api/trip/plans/{RECOVERY_ID}")
        assert pending.status_code == 200
        assert pending.json()["status"] == "planning"

        resumed = client.post(f"/api/trip/plans/{RECOVERY_ID}/resume")
        assert resumed.status_code == 200
        body = resumed.json()
        assert body["status"] == "completed"
        assert body["data"]["city"] == "上海"
        assert body["version"] == 2

        repeated = client.post(f"/api/trip/plans/{RECOVERY_ID}/resume")
        assert repeated.status_code == 200
        assert repeated.json()["message"] == "旅行计划已完成"

    assert calls == ["plan", "route", "route"]
    store.close()


def test_resume_rejects_terminal_failure_and_disabled_checkpoint(tmp_path, monkeypatch):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    failed = store.start(
        trip.TripRequest.model_validate(REQUEST),
        "b" * 32,
    )
    store.fail(failed.plan_id, "SERVICE_BUSY", failed.version)
    pending = store.start(
        trip.TripRequest.model_validate(REQUEST),
        "c" * 32,
    )
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(trip, "get_checkpoint_path", lambda: None)

    with TestClient(main.create_app()) as client:
        terminal = client.post(f"/api/trip/plans/{failed.plan_id}/resume")
        assert terminal.status_code == 409
        assert terminal.json()["error_code"] == "PLAN_NOT_RESUMABLE"

        disabled = client.post(f"/api/trip/plans/{pending.plan_id}/resume")
        assert disabled.status_code == 503
        assert disabled.json()["error_code"] == "CHECKPOINT_UNAVAILABLE"

        invalid = client.post(
            "/api/trip/plan",
            json=REQUEST,
            headers={"X-Trip-Plan-ID": "not-valid"},
        )
        assert invalid.status_code == 422

    store.close()
