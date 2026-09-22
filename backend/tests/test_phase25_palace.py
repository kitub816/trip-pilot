import asyncio
from datetime import date, time
from pathlib import Path
import pytest
from app.models.schemas import TripRequest
from app.services.constraint_service import build_travel_constraints
from app.services.rag_service import FileEvidenceStore, retrieve_plan_evidence
from app.services.validation_service import PlanValidator
from test_phase12_rag import trip_plan

def corpus():
    return asyncio.run(FileEvidenceStore(Path(__file__).parents[1] / "data/palace_evidence.json").load())

def source(start="09:00", end="10:00"):
    p = trip_plan()
    p.days[0].attractions[0].poi_id = "B000A8UIN8"
    p.days[0].attractions[0].visit_start = time.fromisoformat(start) if start else None
    p.days[0].attractions[0].visit_end = time.fromisoformat(end) if end else None
    return p

def constraints(strict=False):
    return build_travel_constraints(TripRequest(city="上海", start_date="2026-10-01",
        end_date="2026-10-01", transportation="步行", accommodation="民宿",
        avoid_reservation_required=strict))

@pytest.mark.parametrize("start,end,invalid", [
    ("08:00","09:00", True), ("16:00","17:00", True),
    ("15:30","17:01", True), ("09:00","10:00", False),
])
def test_official_opening_window(start,end,invalid):
    result = PlanValidator().validate(source(start,end), constraints(), corpus())
    assert ("OUTSIDE_OPENING_HOURS" in {v.code for v in result.errors}) is invalid

def test_reservation_warning_becomes_error_only_for_explicit_constraint():
    assert PlanValidator().validate(source(), constraints(), corpus()).is_valid
    assert "RESERVATION_REQUIRED" in {v.code for v in
        PlanValidator().validate(source(), constraints(True), corpus()).errors}

def test_unknown_reservation_is_not_assumed_free():
    assert "RESERVATION_STATUS_UNKNOWN" in {v.code for v in
        PlanValidator().validate(source(), constraints(True), ()).errors}

def test_missing_times_does_not_claim_opening_validation():
    result = PlanValidator().validate(source(None,None), constraints(), corpus())
    assert "OPENING_TIME_UNVERIFIED" in {v.code for v in result.violations}

def test_edit_reloads_sources_instead_of_client_evidence():
    p=source()
    p.evidence=[]
    result=retrieve_plan_evidence(p)
    assert len(result)==2
    assert all("dpm.org.cn" in str(v.source_url) for v in result)

def test_corpus_is_date_bounded_and_matches_only_main_poi():
    assert all(v.poi_id == "B000A8UIN8" for v in corpus())
    assert all(not v.applies_on(date(2027,1,1)) for v in corpus())


def test_checked_empty_evidence_is_visible_uncertainty():
    result = PlanValidator().validate(source(), constraints(), ())
    assert "EVIDENCE_UNAVAILABLE" in {v.code for v in result.violations}
