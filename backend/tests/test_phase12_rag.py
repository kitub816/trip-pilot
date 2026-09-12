"""Phase 12: source-aware local travel evidence retrieval and validation."""

import json
from datetime import date

import pytest

from app.models.knowledge import EvidenceFacts, TravelEvidence
from app.models.schemas import Attraction, Budget, DayPlan, DayRoute, Location, POIInfo, TripPlan, TripRequest
from app.services.constraint_service import build_travel_constraints
from app.services.rag_service import FileEvidenceStore, TravelRagService
from app.services.validation_service import PlanValidator


POI = POIInfo(
    id="bund", name="外滩", type="景点", address="中山东一路",
    location=Location(longitude=121.49, latitude=31.24),
)


def evidence(**updates) -> TravelEvidence:
    value = {
        "poi_id": "bund", "topic": "opening_hours", "content": "官方公告：10 月 1 日闭园。",
        "source_url": "https://example.org/official-notice", "captured_at": "2026-09-01T00:00:00Z",
        "status": "verified", "facts": {"closed_dates": ["2026-10-01"]},
    }
    value.update(updates)
    return TravelEvidence.model_validate(value)


@pytest.mark.anyio
async def test_file_rag_filters_candidate_and_date_then_preserves_provenance(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"evidence": [
        evidence().model_dump(mode="json"),
        evidence(poi_id="other").model_dump(mode="json"),
        evidence(applicable_to="2026-09-30").model_dump(mode="json"),
    ]}), encoding="utf-8")
    result = await TravelRagService(FileEvidenceStore(path)).retrieve(
        (POI,), date(2026, 10, 1), date(2026, 10, 2),
    )
    assert len(result.evidence) == 1
    assert str(result.evidence[0].source_url) == "https://example.org/official-notice"
    assert result.evidence[0].facts.closed_dates == [date(2026, 10, 1)]
    assert result.warnings == ()


@pytest.mark.anyio
async def test_missing_or_invalid_corpus_yields_uncertainty_without_invented_facts(tmp_path):
    result = await TravelRagService(FileEvidenceStore(tmp_path / "missing.json")).retrieve(
        (POI,), date(2026, 10, 1), date(2026, 10, 1),
    )
    assert result.evidence == ()
    assert result.warnings[0].code == "EVIDENCE_UNAVAILABLE"


def trip_plan() -> TripPlan:
    return TripPlan(
        city="上海", start_date="2026-10-01", end_date="2026-10-01",
        days=[DayPlan(
            date="2026-10-01", day_index=0, description="fixture", transportation="步行",
            accommodation="民宿", attractions=[Attraction(
                name="外滩", poi_id="bund", address="中山东一路",
                location=POI.location, visit_duration=60, description="fixture",
            )], meals=[], route=DayRoute(route_type="walking"),
        )], overall_suggestions="fixture", budget=Budget(total=0),
    )


def constraints():
    return build_travel_constraints(TripRequest(
        city="上海", start_date="2026-10-01", end_date="2026-10-01",
        transportation="步行", accommodation="民宿",
    ))


def test_validator_rejects_only_applicable_verified_closure_evidence():
    result = PlanValidator().validate(trip_plan(), constraints(), (evidence(),))
    assert {item.code for item in result.violations} == {"ATTRACTION_CLOSED"}

    uncertain = evidence(status="uncertain")
    result = PlanValidator().validate(trip_plan(), constraints(), (uncertain,))
    assert {item.code for item in result.violations} == {"EVIDENCE_UNAVAILABLE"}
