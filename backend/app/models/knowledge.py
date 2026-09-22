"""Typed, source-aware travel evidence used by the local RAG boundary."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, model_validator


class OpeningWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    months: list[int] = Field(min_length=1, max_length=12)
    opens: time
    last_entry: time
    closes: time

    @model_validator(mode="after")
    def valid_window(self):
        if any(month < 1 or month > 12 for month in self.months):
            raise ValueError("invalid month")
        if any(value.tzinfo is not None for value in (self.opens, self.last_entry, self.closes)):
            raise ValueError("local times required")
        if not self.opens <= self.last_entry <= self.closes:
            raise ValueError("invalid opening window")
        return self


class EvidenceFacts(BaseModel):
    """Structured facts extracted from one source chunk; absent means unknown."""

    model_config = ConfigDict(extra="forbid")

    opening_windows: list[OpeningWindow] = Field(default_factory=list)
    regular_closed_weekdays: list[int] = Field(default_factory=list)
    opening_hours: str | None = Field(default=None, max_length=500)
    reservation_required: bool | None = None
    accessible: bool | None = None
    closed_dates: list[date] = Field(default_factory=list)


class TravelEvidence(BaseModel):
    """A retrievable POI fact with provenance and an explicit confidence state."""

    model_config = ConfigDict(extra="forbid")

    poi_id: str = Field(min_length=1, max_length=128)
    topic: Literal["opening_hours", "reservation", "rules", "accessibility"]
    content: str = Field(min_length=1, max_length=4000)
    source_url: AnyUrl
    captured_at: datetime
    applicable_from: date | None = None
    applicable_to: date | None = None
    status: Literal["verified", "uncertain"]
    facts: EvidenceFacts = Field(default_factory=EvidenceFacts)

    @model_validator(mode="after")
    def validate_date_range(self) -> "TravelEvidence":
        if (self.applicable_from is not None and self.applicable_to is not None
                and self.applicable_from > self.applicable_to):
            raise ValueError("applicable_from must not be after applicable_to")
        return self

    def applies_on(self, value: date) -> bool:
        return ((self.applicable_from is None or self.applicable_from <= value)
                and (self.applicable_to is None or value <= self.applicable_to))


class EvidenceWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["EVIDENCE_UNAVAILABLE"]
    poi_id: str = Field(min_length=1, max_length=128)
