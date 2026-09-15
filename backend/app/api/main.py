"""FastAPI app, safe error contract and application lifecycle."""
import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.concurrency import run_in_threadpool

from ..config import get_settings, validate_config
from ..errors import AppError
from ..logging_config import configure_logging, request_id
from ..models.schemas import ErrorResponse
from ..agents.trip_planner_agent import reset_trip_planner
from ..services.amap_service import reset_amap_service
from ..services.llm_service import reset_llm
from ..services.tool_runtime import reset_tool_runtime
from ..services.persistence_service import reset_plan_store
from .routes import trip, poi, map as map_routes

logger = logging.getLogger("trippilot.api")


def close_resources() -> None:
    # Attempt every cleanup even if one dependency's close fails.
    for cleanup in (reset_trip_planner, reset_amap_service, reset_tool_runtime, reset_plan_store, reset_llm):
        try:
            cleanup()
        except Exception:
            logger.error("lifecycle.cleanup_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        validate_config(settings)
    except AppError:
        logger.error("configuration.invalid")
        raise
    logger.info("application.started")
    try:
        yield
    finally:
        await run_in_threadpool(close_resources)
        logger.info("application.stopped")


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content=ErrorResponse(
        message=message, detail=message, error_code=code, request_id=request_id.get()
    ).model_dump())


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  responses={code: {"model": ErrorResponse} for code in (422, 500, 502, 503, 504)})

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        # Generate rather than trust an arbitrary user-controlled correlation header.
        token = request_id.set(uuid4().hex)
        started = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.error("request.unhandled_error")
                response = error_response(500, "INTERNAL_ERROR", "服务内部错误，请稍后重试")
            response.headers["X-Request-ID"] = request_id.get()
            logger.info("request.completed", extra={
                "status_code": response.status_code,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            })
            return response
        finally:
            request_id.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.warning("request.failed", extra={"error_code": exc.code})
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Do not serialize input values or exception ctx (may contain user secrets).
        return error_response(422, "VALIDATION_ERROR", "请求参数格式错误，请检查输入")

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return error_response(exc.status_code, "HTTP_ERROR", "请求无法处理")

    # CORS is outermost so error responses also carry the allowed origin header.
    app.add_middleware(CORSMiddleware, allow_origins=settings.get_cors_origins_list(),
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
    app.include_router(trip.router, prefix="/api")
    app.include_router(poi.router, prefix="/api")
    app.include_router(map_routes.router, prefix="/api")

    @app.get("/")
    async def root():
        return {"name": settings.app_name, "version": settings.app_version, "status": "running", "docs": "/docs", "redoc": "/redoc"}

    @app.get("/health")
    async def health():
        return {"status": "healthy", "check": "liveness", "service": settings.app_name, "version": settings.app_version}

    return app


app = create_app()
