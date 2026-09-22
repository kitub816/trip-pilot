"""Trip API; synchronous SDK calls run in FastAPI's worker pool."""
from fastapi import APIRouter
from ...errors import AppError, PersistenceUnavailable, PlanValidationError
from ...services.rag_service import retrieve_plan_evidence
from ...models.schemas import (
    StoredTripPlanResponse,
    TripPlanResponse,
    TripPlanUpdateRequest,
    TripRequest,
)
from ...agents.trip_planner_agent import get_trip_planner_agent
from ...config import validate_config
from ...services.constraint_service import build_travel_constraints
from ...services.budget_service import get_budget_engine
from ...services.persistence_service import PlanStore, StoredTripPlan, get_plan_store
from ...services.route_service import get_route_optimizer
from ...services.validation_service import get_plan_validator
from ...workflows.trip_workflow import TripPlanningWorkflow

from ...services.extraction_service import ConstraintExtractor, ExtractionPreview, ExtractionRequest

router = APIRouter(prefix="/trip", tags=["旅行规划"])


def get_trip_workflow() -> TripPlanningWorkflow:
    """Create a graph for one request, with the legacy planner as an adapter node."""
    return TripPlanningWorkflow(planner_factory=get_trip_planner_agent)

@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
def plan_trip(request: TripRequest):
    constraints = build_travel_constraints(request)
    store = get_plan_store()
    record = store.start(request) if store is not None else None
    try:
        plan = get_trip_workflow().plan(constraints)
    except AppError as error:
        if store is not None and record is not None:
            store.fail(record.plan_id, error.code, record.version)
        raise
    except Exception:
        if store is not None and record is not None:
            store.fail(record.plan_id, "INTERNAL_ERROR", record.version)
        raise
    if store is not None and record is not None:
        record = store.complete(record.plan_id, plan, record.version)
    return TripPlanResponse(
        success=True,
        message="旅行计划生成成功",
        data=plan,
        plan_id=record.plan_id if record else None,
        version=record.version if record else None,
    )


def _response(record: StoredTripPlan, message: str) -> StoredTripPlanResponse:
    return StoredTripPlanResponse(
        message=message,
        plan_id=record.plan_id,
        status=record.status,
        version=record.version,
        request=record.request,
        data=record.plan,
        error_code=record.error_code,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _required_store() -> PlanStore:
    store = get_plan_store()
    if store is None:
        raise PersistenceUnavailable()
    return store


@router.get("/plans/{plan_id}", response_model=StoredTripPlanResponse, summary="读取旅行计划")
def get_plan(plan_id: str):
    return _response(_required_store().get(plan_id), "旅行计划读取成功")


@router.put("/plans/{plan_id}", response_model=StoredTripPlanResponse, summary="更新旅行计划")
def update_plan(plan_id: str, request: TripPlanUpdateRequest):
    store = _required_store()
    current = store.get(plan_id)
    constraints = build_travel_constraints(current.request)
    plan = get_route_optimizer().apply(request.data, constraints)
    plan = get_budget_engine().apply(plan, constraints)
    evidence = retrieve_plan_evidence(plan)
    result = get_plan_validator().validate(plan, constraints, evidence)
    if not result.is_valid:
        raise PlanValidationError()
    plan = plan.model_copy(update={"evidence": list(evidence),
                                  "validation_warnings": list(result.violations)})
    record = store.replace(plan_id, plan, request.expected_version)
    return _response(record, "旅行计划更新成功")

@router.get("/health", summary="规划配置检查（不调用外部服务）")
def health_check():
    validate_config()
    return {"status": "configured", "service": "trip-planner", "external_dependencies": "not_checked"}


@router.post("/extract", response_model=ExtractionPreview, summary="预览自由文本中的硬约束")
def extract_constraints(request: ExtractionRequest):
    return ConstraintExtractor().extract(request.text)
