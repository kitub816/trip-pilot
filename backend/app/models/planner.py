"""Private LLM output schema; trusted domain models are built after validation."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlannerAttractionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_id: str = Field(min_length=1, max_length=20)
    visit_duration: int = Field(ge=15, le=720)
    description: str = Field(min_length=1, max_length=1000)
    ticket_price: int | None = Field(default=None, ge=0)


class PlannerHotelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_id: str = Field(min_length=1, max_length=20)
    price_range: str = Field(default="", max_length=100)
    rating: str = Field(default="", max_length=30)
    distance: str = Field(default="", max_length=100)
    estimated_cost: int | None = Field(default=None, ge=0)


class PlannerMeal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["breakfast", "lunch", "dinner", "snack"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    estimated_cost: int | None = Field(default=None, ge=0)


class PlannerDay(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    date: date
    day_index: int = Field(ge=0, le=29)
    description: str = Field(min_length=1, max_length=1000)
    transportation: str = Field(min_length=1, max_length=100)
    transportation_cost: int | None = Field(default=None, ge=0)
    accommodation: str = Field(min_length=1, max_length=100)
    hotel: PlannerHotelSelection | None = None
    attractions: list[PlannerAttractionSelection] = Field(min_length=1, max_length=3)
    meals: list[PlannerMeal] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def require_main_meals(self) -> "PlannerDay":
        meal_types = [meal.type for meal in self.meals]
        for required in ("breakfast", "lunch", "dinner"):
            if meal_types.count(required) != 1:
                raise ValueError("each day must contain breakfast, lunch and dinner exactly once")
        return self


class PlannerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    days: list[PlannerDay] = Field(min_length=1, max_length=30)
    overall_suggestions: str = Field(min_length=1, max_length=2000)
