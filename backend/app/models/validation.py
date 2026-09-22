"""Typed deterministic plan-validation results used inside the workflow."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ViolationCode = Literal[
    "PLAN_DAY_COUNT_MISMATCH",
    "PLAN_DATE_MISMATCH",
    "BUDGET_MISSING",
    "BUDGET_EXCEEDED",
    "BUDGET_INCOMPLETE",
    "MUST_VISIT_MISSING",
    "AVOID_PLACE_INCLUDED",
    "DUPLICATE_ATTRACTION",
    "ROUTE_MISSING",
    "ROUTE_UNAVAILABLE",
    "SEGMENT_TIME_EXCEEDED",
    "DAILY_WALKING_EXCEEDED",
    "ROUTE_MATRIX_TRUNCATED",
    "ATTRACTION_CLOSED",
    "OUTSIDE_OPENING_HOURS",
    "OPENING_TIME_UNVERIFIED",
    "RESERVATION_REQUIRED",
    "RESERVATION_STATUS_UNKNOWN",
    "CALENDAR_EXCEPTION_UNVERIFIED",
    "EVIDENCE_UNAVAILABLE",
    "VISIT_TIME_INCOMPLETE",
    "VISIT_TIME_INVALID",
    "VISIT_DURATION_CONFLICT",
    "VISIT_TIME_CONFLICT",
]


class PlanViolation(BaseModel):
    """A bounded, model-safe explanation of one deterministic validation finding."""

    model_config = ConfigDict(extra="forbid")

    code: ViolationCode
    severity: Literal["error", "warning"]
    day_index: int | None = Field(default=None, ge=0)
    subject: str | None = Field(default=None, max_length=200)
    origin: str | None = Field(default=None, max_length=200)
    required_travel_seconds: int | None = Field(default=None, ge=0)
    available_gap_seconds: int | None = None


class PlanValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    violations: list[PlanViolation] = Field(default_factory=list)

    @property
    def errors(self) -> tuple[PlanViolation, ...]:
        return tuple(item for item in self.violations if item.severity == "error")

    @property
    def is_valid(self) -> bool:
        return not self.errors
