"""Deterministic cost aggregation and unknown-price semantics."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    TripPlan,
    TripRequest,
)
from app.services.budget_service import BudgetEngine
from app.services.constraint_service import build_travel_constraints
from app.workflows.trip_workflow import TripPlanningWorkflow


def request(**updates) -> TripRequest:
    values = {
        "city": "上海",
        "start_date": "2026-10-01",
        "end_date": "2026-10-03",
        "transportation": "公共交通",
        "accommodation": "舒适型酒店",
        "travelers": 3,
        "budget_limit": "1750",
        "currency": "CNY",
    }
    values.update(updates)
    return TripRequest(**values)


def attraction(name: str, price: int | None) -> Attraction:
    return Attraction(
        name=name,
        address="测试地址",
        location=Location(longitude=121.4, latitude=31.2),
        visit_duration=120,
        description="fixture",
        ticket_price=price,
    )


def day(index: int, *, hotel_cost: int | None, ticket: int | None,
        meal_cost: int | None, transport_cost: int | None) -> DayPlan:
    return DayPlan(
        date=f"2026-10-0{index + 1}",
        day_index=index,
        description="fixture",
        transportation="公共交通",
        transportation_cost=transport_cost,
        accommodation="舒适型酒店",
        hotel=Hotel(name=f"酒店{index}", estimated_cost=hotel_cost),
        attractions=[attraction(f"景点{index}", ticket)],
        meals=[Meal(type="lunch", name=f"午餐{index}", estimated_cost=meal_cost)],
    )


def plan(days, budget: Budget | None = None) -> TripPlan:
    return TripPlan(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-03",
        days=days,
        overall_suggestions="fixture",
        budget=budget,
    )


def test_budget_multiplies_people_rooms_and_actual_nights():
    source = plan([
        day(0, hotel_cost=200, ticket=50, meal_cost=30, transport_cost=10),
        day(1, hotel_cost=300, ticket=0, meal_cost=40, transport_cost=20),
        day(2, hotel_cost=999, ticket=100, meal_cost=0, transport_cost=0),
    ], budget=Budget(total=999999))
    result = BudgetEngine().apply(source, build_travel_constraints(request()))
    assert result.budget.total_attractions == 450
    assert result.budget.total_hotels == 1000
    assert result.budget.total_meals == 210
    assert result.budget.total_transportation == 90
    assert result.budget.total == 1750
    assert result.budget.travelers == 3
    assert result.budget.rooms == 2
    assert result.budget.accommodation_nights == 2
    assert result.budget.is_complete is True
    assert result.budget.within_limit is True
    assert result.budget.unknown_items == []
    assert source.budget.total == 999999


def test_unknown_prices_are_not_treated_as_free_and_limit_is_tri_state():
    source = plan([
        day(0, hotel_cost=None, ticket=None, meal_cost=None, transport_cost=None),
        day(1, hotel_cost=300, ticket=100, meal_cost=30, transport_cost=10),
        day(2, hotel_cost=999, ticket=0, meal_cost=0, transport_cost=0),
    ])
    constraints = build_travel_constraints(request(budget_limit="2000"))
    budget = BudgetEngine().calculate(source, constraints)
    assert budget.total == 1020
    assert budget.is_complete is False
    assert budget.within_limit is None
    assert {(item.category, item.day_index) for item in budget.unknown_items} == {
        ("attraction", 0), ("meal", 0), ("transportation", 0), ("hotel", 0),
    }

    low_limit = build_travel_constraints(request(budget_limit="1000"))
    assert BudgetEngine().calculate(source, low_limit).within_limit is False


def test_one_day_trip_has_no_hotel_night_and_explicit_zero_is_complete():
    one_day_request = request(end_date="2026-10-01", budget_limit=None)
    source = TripPlan(
        city="上海",
        start_date="2026-10-01",
        end_date="2026-10-01",
        days=[day(0, hotel_cost=None, ticket=0, meal_cost=0, transport_cost=0)],
        overall_suggestions="fixture",
    )
    budget = BudgetEngine().calculate(source, build_travel_constraints(one_day_request))
    assert budget.total == 0
    assert budget.accommodation_nights == 0
    assert budget.is_complete is True
    assert budget.within_limit is None


@pytest.mark.parametrize(
    "constructor,kwargs",
    [
        (attraction, {"name": "x", "price": -1}),
        (Hotel, {"name": "x", "estimated_cost": -1}),
        (Meal, {"type": "lunch", "name": "x", "estimated_cost": -1}),
        (day, {"index": 0, "hotel_cost": 0, "ticket": 0, "meal_cost": 0, "transport_cost": -1}),
    ],
)
def test_negative_line_item_costs_are_rejected(constructor, kwargs):
    with pytest.raises(ValidationError):
        constructor(**kwargs)


def test_workflow_replaces_llm_budget_before_completion():
    constraints = build_travel_constraints(request())
    llm_plan = plan([
        day(0, hotel_cost=200, ticket=50, meal_cost=30, transport_cost=10),
        day(1, hotel_cost=300, ticket=0, meal_cost=40, transport_cost=20),
        day(2, hotel_cost=999, ticket=100, meal_cost=0, transport_cost=0),
    ], budget=Budget(total=999999))
    workflow = TripPlanningWorkflow(
        planner_factory=lambda: SimpleNamespace(plan_trip=lambda _: llm_plan),
    )
    result = workflow.plan(constraints)
    assert result.budget.total == 1750
    assert result.budget.within_limit is True
    assert result is not llm_plan
