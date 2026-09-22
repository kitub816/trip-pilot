"""Request-scoped LangGraph adapter for the legacy trip planner."""

import logging
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from ..agents.trip_planner_agent import MultiAgentTripPlanner, get_trip_planner_agent
from ..errors import AppError, PlanValidationError, upstream_failure
from ..models.schemas import TripPlan
from ..models.validation import PlanViolation
from ..models.knowledge import TravelEvidence
from ..services.constraint_service import TravelConstraints
from ..config import get_settings
from ..services.budget_service import BudgetEngine, get_budget_engine
from ..services.retrieval_service import TripRetrievalResult, retrieve_trip_context
from ..services.rag_service import retrieve_trip_evidence
from ..services.route_service import RouteOptimizer, get_route_optimizer
from ..services.validation_service import PlanValidator, get_plan_validator


class TripWorkflowState(TypedDict):
    """All state for one planning request; it is never retained between runs."""

    constraints: TravelConstraints
    status: Literal[
        "planning", "routing", "budgeting", "validating", "replanning", "completed", "failed",
    ]
    plan: TripPlan | None
    error: AppError | None
    retrieval: TripRetrievalResult | None
    evidence: tuple[TravelEvidence, ...]
    violations: tuple[PlanViolation, ...]
    replan_attempts: int


PlannerFactory = Callable[[], MultiAgentTripPlanner]


class TripPlanningWorkflow:
    """Minimal graph that isolates orchestration from transport and agents."""

    def __init__(self, planner_factory: PlannerFactory = get_trip_planner_agent,
                 budget_engine: BudgetEngine | None = None,
                 route_optimizer: RouteOptimizer | None = None,
                 validator: PlanValidator | None = None,
                 max_replan_attempts: int | None = None) -> None:
        self._planner_factory = planner_factory
        self._budget_engine = budget_engine or get_budget_engine()
        self._route_optimizer = route_optimizer or get_route_optimizer()
        self._validator = validator or get_plan_validator()
        self._max_replan_attempts = (
            get_settings().max_replan_attempts
            if max_replan_attempts is None else max_replan_attempts
        )
        if self._max_replan_attempts < 0:
            raise ValueError("max_replan_attempts must not be negative")
        graph = StateGraph(TripWorkflowState)
        graph.add_node("plan", self._plan)
        graph.add_node("route", self._route)
        graph.add_node("budget", self._budget)
        graph.add_node("validate", self._validate)
        graph.add_node("replan", self._replan)
        graph.add_node("failure", self._record_failure)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan", self._next_node, {"route": "route", "failed": "failure"}
        )
        graph.add_conditional_edges(
            "route", self._route_next, {"budget": "budget", "failed": "failure"},
        )
        graph.add_conditional_edges(
            "budget", self._budget_next, {"validate": "validate", "failed": "failure"},
        )
        graph.add_conditional_edges(
            "validate", self._validation_next,
            {"completed": END, "replan": "replan", "failed": "failure"},
        )
        graph.add_edge("replan", "route")
        graph.add_edge("failure", END)
        self._graph = graph.compile()

    def plan(self, constraints: TravelConstraints) -> TripPlan:
        state = self._graph.invoke({
            "constraints": constraints, "status": "planning", "plan": None, "error": None,
            "retrieval": None, "violations": (), "replan_attempts": 0, "evidence": (),
        })
        error = state["error"]
        if error is not None:
            raise error
        plan = state["plan"]
        if plan is None:
            raise upstream_failure(RuntimeError("workflow finished without a plan"))
        return plan

    def _plan(self, state: TripWorkflowState) -> dict[str, object]:
        self._log_node("plan")
        try:
            retrieval = retrieve_trip_context(state["constraints"])
            evidence_result = retrieve_trip_evidence(
                retrieval.attractions, state["constraints"].start_date,
                state["constraints"].end_date,
            )
            planner = self._planner_factory()
            if hasattr(planner, "plan_from_retrieval"):
                arguments = (
                    state["constraints"], retrieval.attractions, retrieval.weather, retrieval.hotels,
                )
                if evidence_result.evidence:
                    plan = planner.plan_from_retrieval(*arguments, evidence=evidence_result.evidence)
                else:
                    plan = planner.plan_from_retrieval(*arguments)
            else:
                # Keeps isolated test doubles and older integrations compatible.
                plan = planner.plan_trip(state["constraints"])
            return {
                "plan": plan, "status": "routing", "error": None, "retrieval": retrieval,
                "violations": (), "replan_attempts": 0, "evidence": evidence_result.evidence,
            }
        except AppError as error:
            return {"plan": None, "status": "failed", "error": error, "retrieval": None,
                    "evidence": ()}

    @staticmethod
    def _next_node(state: TripWorkflowState) -> Literal["route", "failed"]:
        return "route" if state["status"] == "routing" else "failed"

    def _route(self, state: TripWorkflowState) -> dict[str, object]:
        self._log_node("route")
        plan = state["plan"]
        if plan is None:
            return {"status": "failed", "error": upstream_failure(RuntimeError("missing plan"))}
        return {
            "plan": self._route_optimizer.apply(plan, state["constraints"]),
            "status": "budgeting",
            "error": None,
        }

    def _budget(self, state: TripWorkflowState) -> dict[str, object]:
        self._log_node("budget")
        plan = state["plan"]
        if plan is None:
            return {"status": "failed", "error": upstream_failure(RuntimeError("missing plan"))}
        return {
            "plan": self._budget_engine.apply(plan, state["constraints"]),
            "status": "validating",
            "error": None,
        }

    @staticmethod
    def _route_next(state: TripWorkflowState) -> Literal["budget", "failed"]:
        return "budget" if state["status"] == "budgeting" else "failed"

    @staticmethod
    def _budget_next(state: TripWorkflowState) -> Literal["validate", "failed"]:
        return "validate" if state["status"] == "validating" else "failed"

    def _validate(self, state: TripWorkflowState) -> dict[str, object]:
        self._log_node("validate")
        plan = state["plan"]
        if plan is None:
            return {"status": "failed", "error": upstream_failure(RuntimeError("missing plan"))}
        if state["evidence"]:
            result = self._validator.validate(plan, state["constraints"], state["evidence"])
        else:
            result = self._validator.validate(plan, state["constraints"])
        for violation in result.violations:
            logger.info("validation.finding.%s.%s", violation.severity, violation.code)
        if result.is_valid:
            return {"status": "completed", "violations": tuple(result.violations), "error": None}
        if state["replan_attempts"] >= self._max_replan_attempts or state["retrieval"] is None:
            return {
                "status": "failed", "violations": tuple(result.violations),
                "error": PlanValidationError(),
            }
        return {"status": "replanning", "violations": tuple(result.violations), "error": None}

    @staticmethod
    def _validation_next(state: TripWorkflowState) -> Literal["completed", "replan", "failed"]:
        if state["status"] == "completed":
            return "completed"
        if state["status"] == "replanning":
            return "replan"
        return "failed"

    def _replan(self, state: TripWorkflowState) -> dict[str, object]:
        self._log_node("replan")
        retrieval = state["retrieval"]
        if retrieval is None:
            return {"status": "failed", "error": PlanValidationError()}
        try:
            planner = self._planner_factory()
            if not hasattr(planner, "replan_from_retrieval"):
                raise PlanValidationError()
            arguments = (
                state["constraints"], retrieval.attractions, retrieval.weather,
                retrieval.hotels, state["violations"],
            )
            if state["evidence"]:
                plan = planner.replan_from_retrieval(*arguments, evidence=state["evidence"])
            else:
                plan = planner.replan_from_retrieval(*arguments)
            return {
                "plan": plan, "status": "routing", "error": None,
                "replan_attempts": state["replan_attempts"] + 1,
            }
        except AppError as error:
            return {"status": "failed", "error": error}

    @staticmethod
    def _record_failure(state: TripWorkflowState) -> dict[str, object]:
        """Explicit terminal node reserved for future observability and replan branches."""
        return {}

    @staticmethod
    def _log_node(node: str) -> None:
        logger.info("workflow.node.started", extra={"workflow_node": node})


_trip_workflow: TripPlanningWorkflow | None = None
logger = logging.getLogger("trippilot.workflow")


def get_trip_workflow() -> TripPlanningWorkflow:
    global _trip_workflow
    if _trip_workflow is None:
        _trip_workflow = TripPlanningWorkflow()
    return _trip_workflow


def reset_trip_workflow() -> None:
    """Release the compiled graph reference during application shutdown."""
    global _trip_workflow
    _trip_workflow = None
