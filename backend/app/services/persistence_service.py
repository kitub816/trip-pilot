"""Durable request and plan records; separate from LangGraph checkpoints."""

import logging
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import DateTime, Integer, String, Text, create_engine, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from ..config import get_settings
from ..errors import PersistenceUnavailable, PlanNotFound, PlanVersionConflict
from ..models.schemas import TripPlan, TripRequest

logger = logging.getLogger("trippilot.persistence")


def _utc_now() -> datetime:
    # MySQL DATETIME stores whole seconds unless fractional precision is declared.
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


class TripPlanRow(Base):
    __tablename__ = "trip_plans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StoredTripPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str
    status: Literal["planning", "completed", "failed"]
    version: int
    request: TripRequest
    plan: TripPlan | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class PlanStore:
    """Transactional plan records with optimistic version checks."""

    def __init__(self, database_url: str):
        if not database_url.strip():
            raise ValueError("database_url is required")
        options = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        self._engine = create_engine(database_url, **options)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def initialize(self) -> None:
        try:
            Base.metadata.create_all(self._engine)
        except SQLAlchemyError as exc:
            logger.error("persistence.initialize_failed")
            raise PersistenceUnavailable() from exc

    def start(self, request: TripRequest) -> StoredTripPlan:
        now = _utc_now()
        row = TripPlanRow(
            id=uuid4().hex,
            status="planning",
            version=1,
            request_json=request.model_dump_json(),
            plan_json=None,
            error_code=None,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._sessions.begin() as session:
                session.add(row)
            return self._to_model(row)
        except SQLAlchemyError as exc:
            logger.error("persistence.start_failed")
            raise PersistenceUnavailable() from exc

    def complete(self, plan_id: str, plan: TripPlan, expected_version: int) -> StoredTripPlan:
        return self._transition(
            plan_id,
            expected_version,
            status="completed",
            plan_json=plan.model_dump_json(),
            error_code=None,
        )

    def fail(self, plan_id: str, error_code: str, expected_version: int) -> StoredTripPlan:
        return self._transition(
            plan_id,
            expected_version,
            status="failed",
            plan_json=None,
            error_code=error_code,
        )

    def replace(self, plan_id: str, plan: TripPlan, expected_version: int) -> StoredTripPlan:
        return self._transition(
            plan_id,
            expected_version,
            status="completed",
            plan_json=plan.model_dump_json(),
            error_code=None,
        )

    def get(self, plan_id: str) -> StoredTripPlan:
        try:
            with self._sessions() as session:
                row = session.get(TripPlanRow, plan_id)
                if row is None:
                    raise PlanNotFound()
                return self._to_model(row)
        except (PlanNotFound, PersistenceUnavailable):
            raise
        except (SQLAlchemyError, ValidationError, ValueError) as exc:
            logger.error("persistence.read_failed")
            raise PersistenceUnavailable() from exc

    def _transition(
        self,
        plan_id: str,
        expected_version: int,
        *,
        status: Literal["completed", "failed"],
        plan_json: str | None,
        error_code: str | None,
    ) -> StoredTripPlan:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(TripPlanRow)
                    .where(
                        TripPlanRow.id == plan_id,
                        TripPlanRow.version == expected_version,
                    )
                    .values(
                        status=status,
                        version=expected_version + 1,
                        plan_json=plan_json,
                        error_code=error_code,
                        updated_at=_utc_now(),
                    )
                )
                if result.rowcount == 0:
                    exists = session.scalar(
                        select(TripPlanRow.id).where(TripPlanRow.id == plan_id)
                    )
                    if exists is None:
                        raise PlanNotFound()
                    raise PlanVersionConflict()
            return self.get(plan_id)
        except (PlanNotFound, PlanVersionConflict):
            raise
        except SQLAlchemyError as exc:
            logger.error("persistence.write_failed")
            raise PersistenceUnavailable() from exc

    @staticmethod
    def _to_model(row: TripPlanRow) -> StoredTripPlan:
        return StoredTripPlan(
            plan_id=row.id,
            status=row.status,
            version=row.version,
            request=TripRequest.model_validate_json(row.request_json),
            plan=TripPlan.model_validate_json(row.plan_json) if row.plan_json else None,
            error_code=row.error_code,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def close(self) -> None:
        self._engine.dispose()


_store: PlanStore | None = None
_store_lock = Lock()


def get_plan_store() -> PlanStore | None:
    global _store
    with _store_lock:
        if _store is None:
            url = get_settings().database_url.get_secret_value().strip()
            if not url:
                return None
            _store = PlanStore(url)
            _store.initialize()
        return _store


def reset_plan_store() -> None:
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
            _store = None
