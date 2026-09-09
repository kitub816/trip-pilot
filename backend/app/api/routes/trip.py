"""Trip API; synchronous SDK calls run in FastAPI's worker pool."""
from fastapi import APIRouter
from ...models.schemas import TripRequest, TripPlanResponse
from ...agents.trip_planner_agent import get_trip_planner_agent
from ...config import validate_config
from ...services.constraint_service import build_travel_constraints
from ...workflows.trip_workflow import TripPlanningWorkflow

router = APIRouter(prefix="/trip", tags=["旅行规划"])


def get_trip_workflow() -> TripPlanningWorkflow:
    """Create a graph for one request, with the legacy planner as an adapter node."""
    return TripPlanningWorkflow(planner_factory=get_trip_planner_agent)

@router.post("/plan", response_model=TripPlanResponse, summary="生成旅行计划")
def plan_trip(request: TripRequest):
    constraints = build_travel_constraints(request)
    plan = get_trip_workflow().plan(constraints)
    return TripPlanResponse(success=True, message="旅行计划生成成功", data=plan)

@router.get("/health", summary="规划配置检查（不调用外部服务）")
def health_check():
    validate_config()
    return {"status": "configured", "service": "trip-planner", "external_dependencies": "not_checked"}
