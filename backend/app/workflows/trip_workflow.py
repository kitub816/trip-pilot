"""Request-scoped LangGraph adapter for the legacy trip planner."""

from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from ..agents.trip_planner_agent import MultiAgentTripPlanner, get_trip_planner_agent
from ..errors import AppError, upstream_failure
from ..models.schemas import TripPlan
from ..services.constraint_service import TravelConstraints
from ..services.budget_service import BudgetEngine, get_budget_engine
from ..services.retrieval_service import TripRetrievalResult, retrieve_trip_context


class TripWorkflowState(TypedDict):
    """All state for one planning request; it is never retained between runs."""

    constraints: TravelConstraints
    status: Literal["planning", "budgeting", "completed", "failed"]
    plan: TripPlan | None
    error: AppError | None
    retrieval: TripRetrievalResult | None


PlannerFactory = Callable[[], MultiAgentTripPlanner]


class TripPlanningWorkflow:
    """Minimal graph that isolates orchestration from transport and agents."""

    def __init__(self, planner_factory: PlannerFactory = get_trip_planner_agent,
                 budget_engine: BudgetEngine | None = None) -> None:
        self._planner_factory = planner_factory
        self._budget_engine = budget_engine or get_budget_engine()
        graph = StateGraph(TripWorkflowState)
        graph.add_node("plan", self._plan)
        graph.add_node("budget", self._budget)
        graph.add_node("failure", self._record_failure)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan", self._next_node, {"budget": "budget", "failed": "failure"}
        )
        graph.add_edge("budget", END)
        graph.add_edge("failure", END)
        self._graph = graph.compile()

    def plan(self, constraints: TravelConstraints) -> TripPlan:
        state = self._graph.invoke({
            "constraints": constraints, "status": "planning", "plan": None, "error": None, "retrieval": None,
        })
        error = state["error"]
        if error is not None:
            raise error
        plan = state["plan"]
        if plan is None:
            raise upstream_failure(RuntimeError("workflow finished without a plan"))
        return plan

    def _plan(self, state: TripWorkflowState) -> dict[str, object]:
        try:
            retrieval = retrieve_trip_context(state["constraints"])
            planner = self._planner_factory()
            if hasattr(planner, "plan_from_retrieval"):
                plan = planner.plan_from_retrieval(
                    state["constraints"], retrieval.attractions, retrieval.weather, retrieval.hotels
                )
            else:
                # Keeps isolated test doubles and older integrations compatible.
                plan = planner.plan_trip(state["constraints"])
            return {"plan": plan, "status": "budgeting", "error": None, "retrieval": retrieval}
        except AppError as error:
            return {"plan": None, "status": "failed", "error": error, "retrieval": None}

    @staticmethod
    def _next_node(state: TripWorkflowState) -> Literal["budget", "failed"]:
        return "budget" if state["status"] == "budgeting" else "failed"

    def _budget(self, state: TripWorkflowState) -> dict[str, object]:
        plan = state["plan"]
        if plan is None:
            return {"status": "failed", "error": upstream_failure(RuntimeError("missing plan"))}
        return {
            "plan": self._budget_engine.apply(plan, state["constraints"]),
            "status": "completed",
            "error": None,
        }

    @staticmethod
    def _record_failure(state: TripWorkflowState) -> dict[str, object]:
        """Explicit terminal node reserved for future observability and replan branches."""
        return {}


_trip_workflow: TripPlanningWorkflow | None = None


def get_trip_workflow() -> TripPlanningWorkflow:
    global _trip_workflow
    if _trip_workflow is None:
        _trip_workflow = TripPlanningWorkflow()
    return _trip_workflow


def reset_trip_workflow() -> None:
    """Release the compiled graph reference during application shutdown."""
    global _trip_workflow
    _trip_workflow = None
