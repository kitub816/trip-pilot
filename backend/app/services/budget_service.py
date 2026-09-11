"""Deterministic budget calculation from typed plan line items."""

from decimal import Decimal
from math import ceil

from ..models.schemas import Budget, BudgetUnknownItem, TripPlan
from .constraint_service import TravelConstraints


class BudgetEngine:
    """Calculate known CNY costs and preserve every missing unit price."""

    room_capacity = 2

    def apply(self, plan: TripPlan, constraints: TravelConstraints) -> TripPlan:
        return plan.model_copy(update={"budget": self.calculate(plan, constraints)})

    def calculate(self, plan: TripPlan, constraints: TravelConstraints) -> Budget:
        travelers = constraints.travelers
        rooms = ceil(travelers / self.room_capacity)
        nights = max(constraints.travel_days - 1, 0)
        attractions = meals = transportation = hotels = 0
        unknown: list[BudgetUnknownItem] = []

        for position, day in enumerate(plan.days):
            day_index = day.day_index if day.day_index >= 0 else position
            for attraction in day.attractions:
                if attraction.ticket_price is None:
                    unknown.append(BudgetUnknownItem(
                        category="attraction", day_index=day_index, item_name=attraction.name,
                    ))
                else:
                    attractions += attraction.ticket_price * travelers
            for meal in day.meals:
                if meal.estimated_cost is None:
                    unknown.append(BudgetUnknownItem(
                        category="meal", day_index=day_index, item_name=meal.name,
                    ))
                else:
                    meals += meal.estimated_cost * travelers
            if day.transportation_cost is None:
                unknown.append(BudgetUnknownItem(
                    category="transportation", day_index=day_index, item_name="当日交通",
                ))
            else:
                transportation += day.transportation_cost * travelers

        for night in range(nights):
            day = plan.days[night] if night < len(plan.days) else None
            hotel = day.hotel if day is not None else None
            day_index = day.day_index if day is not None else night
            if hotel is None or hotel.estimated_cost is None:
                unknown.append(BudgetUnknownItem(
                    category="hotel", day_index=day_index,
                    item_name=hotel.name if hotel is not None else "住宿",
                ))
            else:
                hotels += hotel.estimated_cost * rooms

        total = attractions + hotels + meals + transportation
        complete = not unknown
        within_limit = self._within_limit(total, complete, constraints.budget_limit)
        return Budget(
            total_attractions=attractions,
            total_hotels=hotels,
            total_meals=meals,
            total_transportation=transportation,
            total=total,
            travelers=travelers,
            rooms=rooms,
            accommodation_nights=nights,
            is_complete=complete,
            within_limit=within_limit,
            unknown_items=unknown,
        )

    @staticmethod
    def _within_limit(total: int, complete: bool, limit: Decimal | None) -> bool | None:
        if limit is None:
            return None
        if Decimal(total) > limit:
            return False
        return True if complete else None


_budget_engine = BudgetEngine()


def get_budget_engine() -> BudgetEngine:
    return _budget_engine
