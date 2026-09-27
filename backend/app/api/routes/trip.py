"""Trip API; synchronous SDK calls run in FastAPI's worker pool."""
import json
import logging
from time import monotonic
from queue import Empty, Queue
from threading import BoundedSemaphore, Thread
from typing import Annotated

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.base import BaseCheckpointSaver

from ...agents.trip_planner_agent import get_trip_planner_agent
from ...config import get_settings, validate_config
from ...errors import (
    AppError,
    CheckpointUnavailable,
    PersistenceUnavailable,
    PlanNotResumable,
    PlanValidationError,
    ServiceBusy,
    WorkflowVersionUnsupported,
)
from ...models.schemas import (
    StoredTripPlanResponse,
    TripPlanResponse,
    TripPlanUpdateRequest,
    TripRequest,
)
from ...logging_config import request_id
from ...services.budget_service import get_budget_engine
from ...services.checkpoint_service import get_checkpoint_path, sqlite_checkpointer
from ...services.constraint_service import build_travel_constraints
from ...services.ownership_service import authorize_owner, require_owner_hash
from ...services.persistence_service import (
    CURRENT_WORKFLOW_VERSION,
    PlanStore,
    StoredTripPlan,
    get_plan_store,
)
from ...services.rag_service import retrieve_plan_evidence
from ...services.route_service import get_route_optimizer
from ...services.validation_service import get_plan_validator
from ...workflows.trip_workflow import ProgressCallback, TripPlanningWorkflow

from ...services.extraction_service import ConstraintExtractor, ExtractionPreview, ExtractionRequest

router = APIRouter(prefix="/trip", tags=["旅行规划"])
logger = logging.getLogger("trippilot.trip_stream")
_stream_slots = BoundedSemaphore(4)
OwnerHeader = Annotated[
    str | None,
    Header(alias="X-Trip-Owner-Token", pattern=r"^[0-9a-f]{64}$"),
]


def get_trip_workflow() -> TripPlanningWorkflow:
    """Create a graph for one request, with the legacy planner as an adapter node."""
    return TripPlanningWorkflow(planner_factory=get_trip_planner_agent)


def build_durable_workflow(checkpointer: BaseCheckpointSaver) -> TripPlanningWorkflow:
    return TripPlanningWorkflow(
        planner_factory=get_trip_planner_agent,
        checkpointer=checkpointer,
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


def _authorized_record(
    store: PlanStore,
    plan_id: str,
    owner_token: str | None,
) -> StoredTripPlan:
    record = store.get(plan_id)
    authorize_owner(getattr(record, "owner_token_hash", None), owner_token)
    return record


def _run_durable(
    store: PlanStore,
    record: StoredTripPlan,
    *,
    resume: bool,
    on_progress: ProgressCallback | None = None,
) -> StoredTripPlan:
    path = get_checkpoint_path()
    if path is None:
        raise CheckpointUnavailable()
    if record.workflow_version != CURRENT_WORKFLOW_VERSION:
        raise WorkflowVersionUnsupported()
    constraints = build_travel_constraints(record.request)
    settings = get_settings()
    with store.execution_lease(
        record.plan_id,
        settings.execution_lease_seconds,
    ) as lease:
        try:
            with sqlite_checkpointer(path) as saver:
                workflow = (
                    TripPlanningWorkflow(
                        planner_factory=get_trip_planner_agent,
                        checkpointer=saver,
                        on_progress=on_progress,
                    ) if on_progress is not None else build_durable_workflow(saver)
                )
                if resume and workflow.has_checkpoint(record.plan_id):
                    plan = workflow.resume(record.plan_id)
                else:
                    plan = workflow.plan(constraints, record.plan_id)
            lease.ensure_owned()
        except AppError as error:
            store.fail(record.plan_id, error.code, record.version)
            raise
        # Unexpected interruption deliberately leaves the record in "planning".
        # A later resume starts at the last committed graph node.
        return store.complete(record.plan_id, plan, record.version)


def _plan_trip(
    request: TripRequest,
    recovery_id: str | None,
    owner_token: str | None,
    on_progress: ProgressCallback | None = None,
) -> TripPlanResponse:
    constraints = build_travel_constraints(request)
    store = get_plan_store()
    owner_hash = require_owner_hash(owner_token) if store is not None else None
    if store is None:
        record = None
    elif recovery_id is not None:
        record = store.start(request, recovery_id, owner_hash)
    elif owner_hash is not None:
        record = store.start(request, owner_token_hash=owner_hash)
    else:
        record = store.start(request)
    if on_progress is not None:
        on_progress("started")
    if record is not None and get_checkpoint_path() is not None:
        record = _run_durable(store, record, resume=False, on_progress=on_progress)
        plan = record.plan
    else:
        try:
            workflow = (
                TripPlanningWorkflow(planner_factory=get_trip_planner_agent, on_progress=on_progress)
                if on_progress is not None else get_trip_workflow()
            )
            plan = workflow.plan(constraints)
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


RecoveryHeader = Annotated[
    str | None,
    Header(alias="X-Trip-Plan-ID", pattern=r"^[0-9a-f]{32}$"),
]


@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
def plan_trip(
    request: TripRequest,
    recovery_id: RecoveryHeader = None,
    owner_token: OwnerHeader = None,
):
    return _plan_trip(request, recovery_id, owner_token)


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/plan/stream", summary="流式生成旅行计划")
def stream_plan_trip(
    request: TripRequest,
    recovery_id: RecoveryHeader = None,
    owner_token: OwnerHeader = None,
):
    """Progress is observed from real workflow steps; the worker survives disconnects."""
    if not _stream_slots.acquire(blocking=False):
        raise ServiceBusy()
    events: Queue[tuple[str, dict]] = Queue()
    correlation_id = request_id.get()

    def work() -> None:
        context_token = request_id.set(correlation_id)
        started = monotonic()
        try:
            result = _plan_trip(
                request, recovery_id, owner_token,
                lambda stage: events.put(("progress", {"stage": stage})),
            )
            events.put(("result", result.model_dump(mode="json")))
            logger.info("stream.completed", extra={"duration_ms": round((monotonic() - started) * 1000, 3)})
        except AppError as error:
            events.put(("error", {"error_code": error.code, "message": error.message,
                                  "status_code": error.status_code}))
            logger.warning("stream.failed", extra={"error_code": error.code})
        except Exception:
            logger.exception("stream.planning_failed")
            events.put(("error", {"error_code": "INTERNAL_ERROR", "message": "服务内部错误，请稍后重试"}))
        finally:
            request_id.reset(context_token)
            _stream_slots.release()

    try:
        Thread(target=work, daemon=True, name="trip-plan-stream").start()
    except Exception:
        _stream_slots.release()
        raise

    def stream():
        while True:
            try:
                event, payload = events.get(timeout=15)
            except Empty:
                yield ": heartbeat\n\n"
                continue
            yield _sse(event, payload)
            if event in ("result", "error"):
                return

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/plans/{plan_id}", response_model=StoredTripPlanResponse, summary="读取旅行计划")
def get_plan(plan_id: str, owner_token: OwnerHeader = None):
    store = _required_store()
    return _response(
        _authorized_record(store, plan_id, owner_token),
        "旅行计划读取成功",
    )


@router.post(
    "/plans/{plan_id}/resume",
    response_model=StoredTripPlanResponse,
    summary="继续未完成的旅行规划",
)
def resume_plan(plan_id: str, owner_token: OwnerHeader = None):
    store = _required_store()
    record = _authorized_record(store, plan_id, owner_token)
    if record.status == "completed":
        return _response(record, "旅行计划已完成")
    if record.status != "planning":
        raise PlanNotResumable()
    record = _run_durable(store, record, resume=True)
    return _response(record, "旅行计划恢复完成")


@router.put("/plans/{plan_id}", response_model=StoredTripPlanResponse, summary="更新旅行计划")
def update_plan(
    plan_id: str,
    request: TripPlanUpdateRequest,
    owner_token: OwnerHeader = None,
):
    store = _required_store()
    current = _authorized_record(store, plan_id, owner_token)
    constraints = build_travel_constraints(current.request)
    plan = get_route_optimizer().apply(request.data, constraints)
    plan = get_budget_engine().apply(plan, constraints)
    evidence = retrieve_plan_evidence(plan)
    result = get_plan_validator().validate(plan, constraints, evidence)
    if not result.is_valid:
        raise PlanValidationError()
    plan = plan.model_copy(update={
        "evidence": list(evidence),
        "validation_warnings": list(result.violations),
    })
    record = store.replace(plan_id, plan, request.expected_version)
    return _response(record, "旅行计划更新成功")


@router.get("/health", summary="规划配置检查（不调用外部服务）")
def health_check():
    validate_config()
    return {
        "status": "configured",
        "service": "trip-planner",
        "external_dependencies": "not_checked",
    }


@router.post("/extract", response_model=ExtractionPreview, summary="预览自由文本中的硬约束")
def extract_constraints(request: ExtractionRequest):
    return ConstraintExtractor().extract(request.text)
