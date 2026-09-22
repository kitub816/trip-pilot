from app.models.validation import PlanValidationResult
"""Phase 7 durable plan records, optimistic versions, and API retrieval."""

import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.api.routes import trip
from app.errors import PlanNotFound, PlanVersionConflict, ServiceBusy
from app.models.schemas import TripPlan, TripRequest
from app.services.persistence_service import PlanStore


REQUEST = {
    "city": "上海",
    "start_date": "2026-10-01",
    "end_date": "2026-10-02",
    "transportation": "步行",
    "accommodation": "民宿",
}


def make_plan(suggestion: str = "fixture") -> TripPlan:
    return TripPlan(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-02",
        days=[],
        overall_suggestions=suggestion,
    )


def sqlite_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{(tmp_path / 'plans.db').as_posix()}"


def test_save_read_and_restart_recovery(tmp_path):
    url = sqlite_url(tmp_path)
    first = PlanStore(url)
    first.initialize()
    pending = first.start(TripRequest(**REQUEST))
    assert pending.status == "planning" and pending.version == 1 and pending.plan is None
    completed = first.complete(pending.plan_id, make_plan(), pending.version)
    assert completed.status == "completed" and completed.version == 2
    first.close()

    restarted = PlanStore(url)
    restarted.initialize()
    loaded = restarted.get(pending.plan_id)
    assert loaded == completed
    restarted.close()


def test_optimistic_version_conflict_and_not_found(tmp_path):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    pending = store.start(TripRequest(**REQUEST))
    completed = store.complete(pending.plan_id, make_plan(), pending.version)
    updated = store.replace(pending.plan_id, make_plan("edited"), completed.version)
    assert updated.version == 3 and updated.plan.overall_suggestions == "edited"
    with pytest.raises(PlanVersionConflict):
        store.replace(pending.plan_id, make_plan("stale"), completed.version)
    with pytest.raises(PlanNotFound):
        store.get("0" * 32)
    store.close()


def test_failure_state_persists_only_safe_error_code(tmp_path):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    pending = store.start(TripRequest(**REQUEST))
    failed = store.fail(pending.plan_id, ServiceBusy.code, pending.version)
    assert failed.status == "failed"
    assert failed.version == 2
    assert failed.error_code == "SERVICE_BUSY"
    assert failed.plan is None
    store.close()


def test_api_records_unexpected_failure_without_exception_text(tmp_path, monkeypatch):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    created_ids = []
    original_start = store.start

    def record_start(request):
        record = original_start(request)
        created_ids.append(record.plan_id)
        return record

    monkeypatch.setattr(store, "start", record_start)
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(
        trip,
        "get_trip_workflow",
        lambda: SimpleNamespace(
            plan=lambda _: (_ for _ in ()).throw(RuntimeError("private database input"))
        ),
    )
    with TestClient(main.create_app()) as client:
        response = client.post("/api/trip/plan", json=REQUEST)
    assert response.status_code == 500
    record = store.get(created_ids[0])
    assert record.status == "failed"
    assert record.error_code == "INTERNAL_ERROR"
    assert "private database input" not in response.text
    store.close()


def test_api_returns_id_reads_and_updates_persisted_plan(tmp_path, monkeypatch):
    store = PlanStore(sqlite_url(tmp_path))
    store.initialize()
    monkeypatch.setattr(trip, "get_plan_store", lambda: store)
    monkeypatch.setattr(
        trip, "get_plan_validator", lambda: SimpleNamespace(validate=lambda *_: PlanValidationResult()),
    )
    monkeypatch.setattr(
        trip,
        "get_trip_workflow",
        lambda: SimpleNamespace(plan=lambda _: make_plan()),
    )
    with TestClient(main.create_app()) as client:
        created = client.post("/api/trip/plan", json=REQUEST)
        assert created.status_code == 200
        created_body = created.json()
        assert created_body["version"] == 2
        plan_id = created_body["plan_id"]

        loaded = client.get(f"/api/trip/plans/{plan_id}")
        assert loaded.status_code == 200
        assert loaded.json()["request"]["city"] == "上海"

        replacement = make_plan("edited by client").model_dump(mode="json")
        updated = client.put(
            f"/api/trip/plans/{plan_id}",
            json={"expected_version": 2, "data": replacement},
        )
        assert updated.status_code == 200
        assert updated.json()["version"] == 3

        stale = client.put(
            f"/api/trip/plans/{plan_id}",
            json={"expected_version": 2, "data": replacement},
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "PLAN_VERSION_CONFLICT"
    store.close()


def test_persistence_endpoint_is_explicitly_unavailable_when_disabled(monkeypatch):
    monkeypatch.setattr(trip, "get_plan_store", lambda: None)
    with TestClient(main.create_app()) as client:
        response = client.get("/api/trip/plans/" + "0" * 32)
    assert response.status_code == 503
    assert response.json()["error_code"] == "PERSISTENCE_UNAVAILABLE"


def test_live_mysql_restart_roundtrip():
    url = os.environ.get("TRIPPILOT_TEST_MYSQL_URL")
    if not url:
        pytest.skip("Set TRIPPILOT_TEST_MYSQL_URL to a disposable MySQL database")
    first = PlanStore(url)
    first.initialize()
    pending = first.start(TripRequest(**REQUEST))
    completed = first.complete(pending.plan_id, make_plan("mysql"), pending.version)
    first.close()

    restarted = PlanStore(url)
    restarted.initialize()
    assert restarted.get(completed.plan_id) == completed
    restarted.close()
