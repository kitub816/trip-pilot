"""Deterministic construction and validation of normalized travel constraints."""

from datetime import date
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..models.schemas import (
    AccommodationType,
    TransportationMode,
    TripRequest,
)


def _normalize_names(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for raw_value in values or []:
        value = raw_value.strip()
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return tuple(result)


class ExtractedConstraints(BaseModel):
    """Optional semantic extraction output; it never overrides explicit input."""

    model_config = ConfigDict(extra="forbid")

    travelers: int | None = Field(default=None, ge=1, le=20)
    budget_limit: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^CNY$")
    must_visit: list[str] | None = Field(default=None, max_length=30)
    avoid_places: list[str] | None = Field(default=None, max_length=30)
    max_daily_walking_km: float | None = Field(default=None, gt=0, le=100)
    max_single_transport_minutes: int | None = Field(default=None, ge=1, le=720)


class TravelConstraints(BaseModel):
    """Request-level constraints consumed by planning and future workflow nodes."""

    model_config = ConfigDict(frozen=True)

    city: str
    start_date: date
    end_date: date
    travel_days: int = Field(ge=1, le=30)
    transportation: TransportationMode
    accommodation: AccommodationType
    preferences: tuple[str, ...] = ()
    free_text_input: str = ""
    travelers: int = Field(default=1, ge=1, le=20)
    budget_limit: Decimal | None = Field(default=None, gt=0)
    currency: str = Field(default="CNY", pattern="^CNY$")
    must_visit: tuple[str, ...] = ()
    avoid_places: tuple[str, ...] = ()
    max_daily_walking_km: float | None = Field(default=None, gt=0, le=100)
    max_single_transport_minutes: int | None = Field(default=None, ge=1, le=720)

    @field_validator("preferences", "must_visit", "avoid_places", mode="before")
    @classmethod
    def normalize_name_lists(cls, value) -> tuple[str, ...]:
        return _normalize_names(value)

    @model_validator(mode="after")
    def reject_place_conflicts(self) -> "TravelConstraints":
        avoided = {name.casefold() for name in self.avoid_places}
        conflicts = [name for name in self.must_visit if name.casefold() in avoided]
        if conflicts:
            raise ValueError("a place cannot be both required and avoided")
        return self

    @property
    def requires_semantic_extraction(self) -> bool:
        return bool(self.free_text_input.strip())


ConstraintValue = TypeVar("ConstraintValue")


def _prefer_explicit(
    explicit: ConstraintValue | None,
    extracted: ConstraintValue | None,
    default: ConstraintValue | None = None,
) -> ConstraintValue | None:
    if explicit is not None:
        return explicit
    if extracted is not None:
        return extracted
    return default


def build_travel_constraints(
    request: TripRequest,
    extracted: ExtractedConstraints | None = None,
) -> TravelConstraints:
    """Merge validated values with explicit request fields taking precedence."""

    semantic = extracted or ExtractedConstraints()
    return TravelConstraints(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        travel_days=request.travel_days,
        transportation=request.transportation,
        accommodation=request.accommodation,
        preferences=request.preferences,
        free_text_input=request.free_text_input,
        travelers=_prefer_explicit(request.travelers, semantic.travelers, 1),
        budget_limit=_prefer_explicit(request.budget_limit, semantic.budget_limit),
        currency=_prefer_explicit(request.currency, semantic.currency, "CNY"),
        must_visit=_prefer_explicit(request.must_visit, semantic.must_visit, ()),
        avoid_places=_prefer_explicit(request.avoid_places, semantic.avoid_places, ()),
        max_daily_walking_km=_prefer_explicit(
            request.max_daily_walking_km,
            semantic.max_daily_walking_km,
        ),
        max_single_transport_minutes=_prefer_explicit(
            request.max_single_transport_minutes,
            semantic.max_single_transport_minutes,
        ),
    )
