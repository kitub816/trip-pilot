"""Deterministic hard-constraint validation for a fully derived TripPlan."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from ..errors import PlanValidationError
from ..models.schemas import DayPlan, TripPlan
from ..models.knowledge import TravelEvidence
from ..models.validation import PlanValidationResult, PlanViolation
from .constraint_service import TravelConstraints


class PlanValidator:
    """Validate only facts available in the current typed plan and constraints."""

    def validate(
        self, plan: TripPlan, constraints: TravelConstraints,
        evidence: tuple[TravelEvidence, ...] = (),
    ) -> PlanValidationResult:
        violations: list[PlanViolation] = []
        self._validate_dates(plan, constraints, violations)
        self._validate_budget(plan, constraints, violations)
        self._validate_places(plan, constraints, violations)
        self._validate_routes(plan, violations)
        self._validate_visit_windows(plan, violations)
        if evidence:
            self._validate_evidence(plan, evidence, violations)
        return PlanValidationResult(violations=violations)

    def validate_or_raise(
        self, plan: TripPlan, constraints: TravelConstraints,
        evidence: tuple[TravelEvidence, ...] = (),
    ) -> None:
        if self.validate(plan, constraints, evidence).is_valid:
            return
        raise PlanValidationError()

    @staticmethod
    def _add(
        violations: list[PlanViolation], code: str, severity: str,
        *, day_index: int | None = None, subject: str | None = None,
    ) -> None:
        violations.append(PlanViolation(
            code=code, severity=severity, day_index=day_index, subject=subject,
        ))

    def _validate_dates(
        self, plan: TripPlan, constraints: TravelConstraints,
        violations: list[PlanViolation],
    ) -> None:
        expected_days = constraints.travel_days
        if len(plan.days) != expected_days:
            self._add(violations, "PLAN_DAY_COUNT_MISMATCH", "error")
        for position, day in enumerate(plan.days):
            expected = constraints.start_date + timedelta(days=position)
            if day.day_index != position or day.date != expected.isoformat():
                self._add(
                    violations, "PLAN_DATE_MISMATCH", "error",
                    day_index=day.day_index if day.day_index >= 0 else position,
                )

    def _validate_budget(
        self, plan: TripPlan, constraints: TravelConstraints,
        violations: list[PlanViolation],
    ) -> None:
        if plan.budget is None:
            self._add(violations, "BUDGET_MISSING", "error")
            return
        if (constraints.budget_limit is not None
                and Decimal(plan.budget.total) > constraints.budget_limit):
            self._add(violations, "BUDGET_EXCEEDED", "error")
        if not plan.budget.is_complete:
            self._add(violations, "BUDGET_INCOMPLETE", "warning")

    def _validate_places(
        self, plan: TripPlan, constraints: TravelConstraints,
        violations: list[PlanViolation],
    ) -> None:
        names: list[str] = []
        seen: set[str] = set()
        for position, day in enumerate(plan.days):
            day_index = day.day_index if day.day_index >= 0 else position
            for attraction in day.attractions:
                names.append(attraction.name)
                key = attraction.poi_id.strip() or attraction.name.casefold()
                if key in seen:
                    self._add(
                        violations, "DUPLICATE_ATTRACTION", "error",
                        day_index=day_index, subject=attraction.name,
                    )
                else:
                    seen.add(key)
                if any(self._matches(forbidden, attraction.name)
                       for forbidden in constraints.avoid_places):
                    self._add(
                        violations, "AVOID_PLACE_INCLUDED", "error",
                        day_index=day_index, subject=attraction.name,
                    )
        for required in constraints.must_visit:
            if not any(self._matches(required, name) for name in names):
                self._add(
                    violations, "MUST_VISIT_MISSING", "error", subject=required,
                )

    def _validate_routes(
        self, plan: TripPlan, violations: list[PlanViolation],
    ) -> None:
        for position, day in enumerate(plan.days):
            day_index = day.day_index if day.day_index >= 0 else position
            if day.route is None:
                if len(day.attractions) > 1:
                    self._add(violations, "ROUTE_MISSING", "error", day_index=day_index)
                continue
            warning_map = {
                "ROUTE_UNAVAILABLE": ("ROUTE_UNAVAILABLE", "error"),
                "SEGMENT_TIME_EXCEEDED": ("SEGMENT_TIME_EXCEEDED", "error"),
                "DAILY_WALKING_EXCEEDED": ("DAILY_WALKING_EXCEEDED", "error"),
                "MATRIX_TRUNCATED": ("ROUTE_MATRIX_TRUNCATED", "warning"),
            }
            for warning in day.route.warning_codes:
                mapped = warning_map.get(warning)
                if mapped is not None:
                    self._add(
                        violations, mapped[0], mapped[1], day_index=day_index,
                    )

    def _validate_visit_windows(
        self, plan: TripPlan, violations: list[PlanViolation],
    ) -> None:
        for day in plan.days:
            attractions = day.attractions
            if not any(item.visit_start is not None for item in attractions):
                continue
            if any(item.visit_start is None or item.visit_end is None for item in attractions):
                self._add(violations, "VISIT_TIME_INCOMPLETE", "warning",
                          day_index=day.day_index)
            for item in attractions:
                if item.visit_start is None or item.visit_end is None:
                    continue
                start = datetime.combine(date.min, item.visit_start)
                end = datetime.combine(date.min, item.visit_end)
                if end <= start:
                    self._add(violations, "VISIT_TIME_INVALID", "error",
                              day_index=day.day_index, subject=item.name)
                elif end - start < timedelta(minutes=item.visit_duration):
                    self._add(violations, "VISIT_DURATION_CONFLICT", "error",
                              day_index=day.day_index, subject=item.name)
            for index, (earlier, later) in enumerate(zip(attractions, attractions[1:])):
                if earlier.visit_end is None or later.visit_start is None:
                    continue
                required = 0
                if day.route is not None and index < len(day.route.legs):
                    duration = day.route.legs[index].duration
                    if duration is None:
                        continue  # Route validation reports unavailable travel separately.
                    required = duration
                elif day.route is None:
                    continue
                gap = (datetime.combine(date.min, later.visit_start)
                       - datetime.combine(date.min, earlier.visit_end)).total_seconds()
                if gap < required:
                    self._add(violations, "VISIT_TIME_CONFLICT", "error",
                              day_index=day.day_index, subject=later.name)

    def _validate_evidence(
        self, plan: TripPlan, evidence: tuple[TravelEvidence, ...],
        violations: list[PlanViolation],
    ) -> None:
        by_poi: dict[str, list[TravelEvidence]] = {}
        for item in evidence:
            by_poi.setdefault(item.poi_id, []).append(item)
        for position, day in enumerate(plan.days):
            day_index = day.day_index if day.day_index >= 0 else position
            try:
                plan_date = date.fromisoformat(day.date)
            except ValueError:
                continue
            for attraction in day.attractions:
                records = [item for item in by_poi.get(attraction.poi_id, [])
                           if item.status == "verified" and item.applies_on(plan_date)]
                if not records:
                    self._add(violations, "EVIDENCE_UNAVAILABLE", "warning",
                              day_index=day_index, subject=attraction.name)
                elif any(plan_date in item.facts.closed_dates for item in records):
                    self._add(violations, "ATTRACTION_CLOSED", "error",
                              day_index=day_index, subject=attraction.name)

    @staticmethod
    def _matches(constraint_name: str, attraction_name: str) -> bool:
        return constraint_name.casefold() in attraction_name.casefold()


_plan_validator = PlanValidator()


def get_plan_validator() -> PlanValidator:
    return _plan_validator
