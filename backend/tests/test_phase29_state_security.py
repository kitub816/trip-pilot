"""Ownership, Alembic migration, cross-instance lease and retention cleanup."""
from datetime import datetime, timedelta
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import main
from app.api.routes import trip
from app.config import get_settings
from app.errors import PlanNotFound
from app.models.schemas import TripPlan, TripRequest
from app.models.validation import PlanValidationResult
from app.services.checkpoint_service import sqlite_checkpointer
from app.services.persistence_service import PlanStore
from app.services.state_cleanup_service import cleanup_terminal_state
from app.workflows.trip_workflow import TripPlanningWorkflow


REQUEST = {
    "city": "上海",
    "start_date": "2026-10-01",
    "end_date": "2026-10-01",
    "transportation": "步行",
    "accommodation": "民宿",
}
PLAN_ID = "e" * 32
OWNER_TOKEN = "1" * 64


@pytest.fixture(autouse=True)
def clear_settings_cache_after_test():
    yield
    get_settings.cache_clear()


def sqlite_url(path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def make_plan() -> TripPlan:
    return TripPlan(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-01",
        days=[],
        overall_suggestions="fixture",
    )


def test_alembic_upgrades_legacy_table_in_place(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE trip_plans (
            id VARCHAR(32) PRIMARY KEY,
            status VARCHAR(20) NOT NULL,
            version INTEGER NOT NULL,
            request_json TEXT NOT NULL,
            plan_json TEXT,
            error_code VARCHAR(64),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    store = PlanStore(sqlite_url(path))
    store.initialize()
    with store._engine.connect() as database:
        columns = {
            row[1]
            for row in database.execute(text("PRAGMA table_info(trip_plans)"))
        }
        revision = database.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert {
        "owner_token_hash",
        "lease_owner",
        "lease_expires_at",
        "workflow_version",
    } <= columns
    assert revision == "0001_plan_ownership"
    store.close()


def test_owner_token_protects_new_plan_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("REQUIRE_PLAN_OWNER_TOKEN", "true")
    get_settings.cache_clear()
    store = PlanStore(sqlite_url(tmp_path / "plans.db"))
    store.initialize()
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(
        trip,
        "get_trip_workflow",
        lambda: SimpleNamespace(plan=lambda _: make_plan()),
    )

    with TestClient(main.create_app()) as client:
        created = client.post(
            "/api/trip/plan",
            json=REQUEST,
            headers={
                "X-Trip-Plan-ID": PLAN_ID,
                "X-Trip-Owner-Token": OWNER_TOKEN,
            },
        )
        assert created.status_code == 200
        assert OWNER_TOKEN not in created.text

        missing = client.get(f"/api/trip/plans/{PLAN_ID}")
        assert missing.status_code == 403
        assert missing.json()["error_code"] == "PLAN_ACCESS_DENIED"

        wrong = client.get(
            f"/api/trip/plans/{PLAN_ID}",
            headers={"X-Trip-Owner-Token": "2" * 64},
        )
        assert wrong.status_code == 403

        allowed = client.get(
            f"/api/trip/plans/{PLAN_ID}",
            headers={"X-Trip-Owner-Token": OWNER_TOKEN},
        )
        assert allowed.status_code == 200
        assert "owner_token_hash" not in allowed.json()

    store.close()


def test_database_lease_coordinates_store_instances(tmp_path):
    url = sqlite_url(tmp_path / "plans.db")
    first = PlanStore(url)
    first.initialize()
    second = PlanStore(url)
    second.initialize()
    record = first.start(TripRequest(**REQUEST), PLAN_ID)

    assert first.acquire_lease(record.plan_id, "a" * 32, 60)
    assert not second.acquire_lease(record.plan_id, "b" * 32, 60)
    assert first.renew_lease(record.plan_id, "a" * 32, 60)
    first.release_lease(record.plan_id, "a" * 32)
    assert second.acquire_lease(record.plan_id, "b" * 32, 60)
    second.release_lease(record.plan_id, "b" * 32)
    first.close()
    second.close()


def test_cleanup_deletes_terminal_record_and_checkpoint_thread(tmp_path):
    database_path = tmp_path / "plans.db"
    checkpoint_path = tmp_path / "workflow.sqlite"
    store = PlanStore(sqlite_url(database_path))
    store.initialize()
    record = store.start(TripRequest(**REQUEST), PLAN_ID)

    with sqlite_checkpointer(checkpoint_path) as saver:
        workflow = TripPlanningWorkflow(
            checkpointer=saver,
            planner_factory=lambda: SimpleNamespace(plan_trip=lambda _: make_plan()),
            route_optimizer=SimpleNamespace(apply=lambda value, _: value),
            budget_engine=SimpleNamespace(apply=lambda value, _: value),
            validator=SimpleNamespace(validate=lambda *_: PlanValidationResult()),
        )
        plan = workflow.plan(
            trip.build_travel_constraints(TripRequest(**REQUEST)),
            PLAN_ID,
        )
    store.complete(record.plan_id, plan, record.version)
    cutoff = datetime.now() + timedelta(days=1)

    dry_run = cleanup_terminal_state(
        store,
        checkpoint_path,
        cutoff,
        dry_run=True,
    )
    assert dry_run.candidates == 1 and dry_run.deleted == 0
    assert store.get(PLAN_ID).status == "completed"

    result = cleanup_terminal_state(store, checkpoint_path, cutoff)
    assert result.candidates == 1 and result.deleted == 1
    with pytest.raises(PlanNotFound):
        store.get(PLAN_ID)
    with sqlite_checkpointer(checkpoint_path) as saver:
        assert not list(saver.list({"configurable": {"thread_id": PLAN_ID}}))
    store.close()

def test_resume_rejects_incompatible_workflow_version(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_PATH", str(tmp_path / "workflow.sqlite"))
    monkeypatch.setenv("REQUIRE_PLAN_OWNER_TOKEN", "false")
    get_settings.cache_clear()
    store = PlanStore(sqlite_url(tmp_path / "plans.db"))
    store.initialize()
    store.start(TripRequest(**REQUEST), PLAN_ID)
    with store._engine.begin() as database:
        database.execute(
            text("UPDATE trip_plans SET workflow_version = 0 WHERE id = :plan_id"),
            {"plan_id": PLAN_ID},
        )
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)

    with TestClient(main.create_app()) as client:
        response = client.post(f"/api/trip/plans/{PLAN_ID}/resume")

    assert response.status_code == 409
    assert response.json()["error_code"] == "WORKFLOW_VERSION_UNSUPPORTED"
    store.close()

