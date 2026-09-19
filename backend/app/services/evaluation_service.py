"""Small deterministic offline evaluation runner; it never calls external services."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from ..models.schemas import TripRequest
from .constraint_service import build_travel_constraints


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    request: dict[str, object]
    expected: str


def run_constraint_cases(path: Path) -> dict[str, int]:
    cases = [EvaluationCase.model_validate(item) for item in json.loads(path.read_text("utf-8"))]
    matched = 0
    for case in cases:
        try:
            build_travel_constraints(TripRequest.model_validate(case.request))
            actual = "accepted"
        except ValueError:
            actual = "rejected"
        matched += actual == case.expected
    return {"total": len(cases), "matched": matched}
