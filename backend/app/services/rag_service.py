"""Local, provenance-preserving retrieval for travel facts.

The bundled corpus covers only the verified Palace Museum POI.  Production evidence must be supplied
through ``RAG_KNOWLEDGE_PATH`` as source-attributed JSON; this service never
creates opening-hours or reservation claims from an LLM response.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from ..config import get_settings
from ..models.knowledge import EvidenceWarning, TravelEvidence
from ..models.schemas import POIInfo, TripPlan


class EvidenceStore(Protocol):
    async def load(self) -> tuple[TravelEvidence, ...]: ...


class FileEvidenceStore:
    """Read an externally maintained JSON evidence corpus without network I/O."""

    def __init__(self, path: Path | None) -> None:
        self._path = path

    async def load(self) -> tuple[TravelEvidence, ...]:
        if self._path is None or not self._path.is_file():
            return ()
        try:
            raw = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
            payload = json.loads(raw)
            rows = payload["evidence"] if isinstance(payload, dict) else payload
            return tuple(TypeAdapter(list[TravelEvidence]).validate_python(rows))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValidationError):
            # A broken corpus is not evidence.  Callers receive uncertainty instead.
            return ()


@dataclass(frozen=True)
class TripEvidenceResult:
    evidence: tuple[TravelEvidence, ...]
    warnings: tuple[EvidenceWarning, ...]


class TravelRagService:
    def __init__(self, store: EvidenceStore, max_evidence_per_poi: int = 3) -> None:
        self._store = store
        self._max_evidence_per_poi = max_evidence_per_poi

    async def retrieve(
        self, candidates: tuple[POIInfo, ...], start_date: date, end_date: date,
    ) -> TripEvidenceResult:
        candidate_ids = {item.id for item in candidates}
        grouped: dict[str, list[TravelEvidence]] = {item.id: [] for item in candidates}
        for item in await self._store.load():
            if item.poi_id not in candidate_ids:
                continue
            if item.applicable_to is not None and item.applicable_to < start_date:
                continue
            if item.applicable_from is not None and item.applicable_from > end_date:
                continue
            grouped[item.poi_id].append(item)
        evidence = tuple(
            record
            for poi_id in sorted(grouped)
            for record in sorted(grouped[poi_id], key=lambda value: value.captured_at, reverse=True)
            [:self._max_evidence_per_poi]
        )
        evidenced_ids = {item.poi_id for item in evidence}
        return TripEvidenceResult(
            evidence=evidence,
            warnings=tuple(EvidenceWarning(code="EVIDENCE_UNAVAILABLE", poi_id=item.id)
                           for item in candidates if item.id not in evidenced_ids),
        )


def retrieve_trip_evidence(
    candidates: tuple[POIInfo, ...], start_date: date, end_date: date,
) -> TripEvidenceResult:
    """Synchronous boundary for the current worker-thread LangGraph workflow."""
    return asyncio.run(get_travel_rag_service().retrieve(candidates, start_date, end_date))


_rag_service: TravelRagService | None = None


def get_travel_rag_service() -> TravelRagService:
    global _rag_service
    if _rag_service is None:
        config_path = get_settings().rag_knowledge_path.strip()
        _rag_service = TravelRagService(
            FileEvidenceStore(Path(config_path) if config_path else
                              Path(__file__).resolve().parents[2] / "data" / "palace_evidence.json"),
            get_settings().rag_max_evidence_per_poi,
        )
    return _rag_service


def reset_travel_rag_service() -> None:
    global _rag_service
    _rag_service = None


def retrieve_plan_evidence(plan: TripPlan) -> tuple[TravelEvidence, ...]:
    """Reload trusted local evidence for edits; never trust client-submitted sources."""
    candidates = tuple(POIInfo(id=item.poi_id, name=item.name, address=item.address,
                              location=item.location, type="景点")
                       for day in plan.days for item in day.attractions if item.poi_id)
    return retrieve_trip_evidence(candidates, date.fromisoformat(plan.start_date),
                                 date.fromisoformat(plan.end_date)).evidence
