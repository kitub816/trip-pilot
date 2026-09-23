"""Durable request and plan records; separate from LangGraph checkpoints."""

from contextlib import contextmanager
import logging
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    or_,
    select,
    update,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from ..config import get_settings
from ..errors import (
    PersistenceUnavailable,
    PlanNotFound,
    PlanVersionConflict,
    ServiceBusy,
)
from ..models.schemas import TripPlan, TripRequest

logger = logging.getLogger("trippilot.persistence")
CURRENT_WORKFLOW_VERSION = 1


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
    owner_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workflow_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CURRENT_WORKFLOW_VERSION,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class StoredTripPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_id: str
    status: Literal["planning", "completed", "failed"]
    version: int
    request: TripRequest
    plan: TripPlan | None
    error_code: str | None
    owner_token_hash: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    workflow_version: int
    created_at: datetime
    updated_at: datetime


class LeaseGuard:
    def __init__(
        self,
        store: "PlanStore",
        plan_id: str,
        holder_id: str,
        ttl_seconds: int,
    ) -> None:
        self._store = store
        self._plan_id = plan_id
        self._holder_id = holder_id
        self._ttl_seconds = ttl_seconds
        self._stopped = Event()
        self._lost = Event()
        self._thread = Thread(target=self._renew_loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _renew_loop(self) -> None:
        interval = max(5, self._ttl_seconds // 3)
        while not self._stopped.wait(interval):
            try:
                if not self._store.renew_lease(
                    self._plan_id,
                    self._holder_id,
                    self._ttl_seconds,
                ):
                    self._lost.set()
                    return
            except PersistenceUnavailable:
                self._lost.set()
                return

    def ensure_owned(self) -> None:
        if self._lost.is_set():
            raise ServiceBusy()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=2)


class PlanStore:
    """Transactional plan records, optimistic versions and execution leases."""

    def __init__(self, database_url: str):
        if not database_url.strip():
            raise ValueError("database_url is required")
        self._database_url = database_url
        options = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        self._engine = create_engine(database_url, **options)
        self._sessions = sessionmaker(self._engine, expire_on_commit=False)

    def initialize(self) -> None:
        try:
            from .migration_service import upgrade_database

            upgrade_database(self._database_url)
        except Exception as exc:
            logger.error("persistence.initialize_failed")
            raise PersistenceUnavailable() from exc

    def start(
        self,
        request: TripRequest,
        plan_id: str | None = None,
        owner_token_hash: str | None = None,
    ) -> StoredTripPlan:
        now = _utc_now()
        row = TripPlanRow(
            id=plan_id or uuid4().hex,
            status="planning",
            version=1,
            request_json=request.model_dump_json(),
            plan_json=None,
            error_code=None,
            owner_token_hash=owner_token_hash,
            lease_owner=None,
            lease_expires_at=None,
            workflow_version=CURRENT_WORKFLOW_VERSION,
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

    def acquire_lease(self, plan_id: str, holder_id: str, ttl_seconds: int) -> bool:
        now = _utc_now()
        expires_at = now + timedelta(seconds=ttl_seconds)
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(TripPlanRow)
                    .where(
                        TripPlanRow.id == plan_id,
                        TripPlanRow.status == "planning",
                        or_(
                            TripPlanRow.lease_owner.is_(None),
                            TripPlanRow.lease_expires_at.is_(None),
                            TripPlanRow.lease_expires_at <= now,
                            TripPlanRow.lease_owner == holder_id,
                        ),
                    )
                    .values(lease_owner=holder_id, lease_expires_at=expires_at)
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            logger.error("persistence.lease_acquire_failed")
            raise PersistenceUnavailable() from exc

    def renew_lease(self, plan_id: str, holder_id: str, ttl_seconds: int) -> bool:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    update(TripPlanRow)
                    .where(
                        TripPlanRow.id == plan_id,
                        TripPlanRow.status == "planning",
                        TripPlanRow.lease_owner == holder_id,
                    )
                    .values(
                        lease_expires_at=_utc_now() + timedelta(seconds=ttl_seconds)
                    )
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            logger.error("persistence.lease_renew_failed")
            raise PersistenceUnavailable() from exc

    def release_lease(self, plan_id: str, holder_id: str) -> None:
        try:
            with self._sessions.begin() as session:
                session.execute(
                    update(TripPlanRow)
                    .where(
                        TripPlanRow.id == plan_id,
                        TripPlanRow.lease_owner == holder_id,
                    )
                    .values(lease_owner=None, lease_expires_at=None)
                )
        except SQLAlchemyError as exc:
            logger.error("persistence.lease_release_failed")
            raise PersistenceUnavailable() from exc

    @contextmanager
    def execution_lease(self, plan_id: str, ttl_seconds: int):
        holder_id = uuid4().hex
        if not self.acquire_lease(plan_id, holder_id, ttl_seconds):
            raise ServiceBusy()
        guard = LeaseGuard(self, plan_id, holder_id, ttl_seconds)
        guard.start()
        try:
            yield guard
        finally:
            guard.stop()
            self.release_lease(plan_id, holder_id)

    def terminal_before(self, cutoff: datetime, limit: int = 1000) -> list[str]:
        now = _utc_now()
        try:
            with self._sessions() as session:
                return list(session.scalars(
                    select(TripPlanRow.id)
                    .where(
                        TripPlanRow.status.in_(("completed", "failed")),
                        TripPlanRow.updated_at < cutoff,
                        or_(
                            TripPlanRow.lease_owner.is_(None),
                            TripPlanRow.lease_expires_at <= now,
                        ),
                    )
                    .order_by(TripPlanRow.updated_at)
                    .limit(limit)
                ))
        except SQLAlchemyError as exc:
            logger.error("persistence.cleanup_list_failed")
            raise PersistenceUnavailable() from exc

    def delete_terminal(self, plan_id: str, cutoff: datetime) -> bool:
        try:
            with self._sessions.begin() as session:
                result = session.execute(
                    delete(TripPlanRow).where(
                        TripPlanRow.id == plan_id,
                        TripPlanRow.status.in_(("completed", "failed")),
                        TripPlanRow.updated_at < cutoff,
                    )
                )
                return result.rowcount == 1
        except SQLAlchemyError as exc:
            logger.error("persistence.cleanup_delete_failed")
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
            owner_token_hash=row.owner_token_hash,
            lease_owner=row.lease_owner,
            lease_expires_at=row.lease_expires_at,
            workflow_version=row.workflow_version,
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
