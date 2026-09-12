"""Deterministic hard-constraint validation for a fully derived TripPlan."""

from datetime import timedelta
from decimal import Decimal

from ..errors import PlanValidationError
from ..models.schemas import DayPlan, TripPlan
from ..models.validation import PlanValidationResult, PlanViolation
from .constraint_service import TravelConstraints


class PlanValidator:
    """Validate only facts available in the current typed plan and constraints."""

    def validate(
        self, plan: TripPlan, constraints: TravelConstraints,
    ) -> PlanValidationResult:
        violations: list[PlanViolation] = []
        self._validate_dates(plan, constraints, violations)
        self._validate_budget(plan, constraints, violations)
        self._validate_places(plan, constraints, violations)
        self._validate_routes(plan, violations)
        return PlanValidationResult(violations=violations)

    def validate_or_raise(self, plan: TripPlan, constraints: TravelConstraints) -> None:
        if self.validate(plan, constraints).is_valid:
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

    @staticmethod
    def _matches(constraint_name: str, attraction_name: str) -> bool:
        return constraint_name.casefold() in attraction_name.casefold()


_plan_validator = PlanValidator()


def get_plan_validator() -> PlanValidator:
    return _plan_validator
