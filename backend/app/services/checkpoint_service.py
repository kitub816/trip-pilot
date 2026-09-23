"""Local durable LangGraph state. No credentials, pickle or arbitrary imports."""
from contextlib import contextmanager
from dataclasses import is_dataclass
import sqlite3
from pathlib import Path
from threading import Lock

from pydantic import BaseModel
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .. import errors
from ..models import schemas, knowledge, validation
from . import constraint_service, retrieval_service
from ..config import get_settings
from ..errors import ServiceBusy


_active_plan_ids: set[str] = set()
_active_plan_lock = Lock()


def get_checkpoint_path() -> Path | None:
    raw = get_settings().checkpoint_path.strip()
    return Path(raw).expanduser().resolve() if raw else None


@contextmanager
def plan_execution(plan_id: str):
    """Prevent two local workers from advancing the same graph thread at once."""
    with _active_plan_lock:
        if plan_id in _active_plan_ids:
            raise ServiceBusy()
        _active_plan_ids.add(plan_id)
    try:
        yield
    finally:
        with _active_plan_lock:
            _active_plan_ids.discard(plan_id)


class CheckpointSerializer:
    def __init__(self):
        modules = (schemas, knowledge, validation, constraint_service, retrieval_service)
        allowed = []
        for module in modules:
            for value in vars(module).values():
                if isinstance(value, type) and value.__module__ == module.__name__:
                    if issubclass(value, BaseModel) or is_dataclass(value) or value in (
                        schemas.TransportationMode, schemas.AccommodationType
                    ):
                        allowed.append((value.__module__, value.__name__))
        self.inner = JsonPlusSerializer(pickle_fallback=False,
                                       allowed_msgpack_modules=allowed,
                                       allowed_json_modules=[])
        self.error_types = {value.code: value for value in vars(errors).values()
                            if isinstance(value, type) and issubclass(value, errors.AppError)}

    def _encode(self, value):
        if isinstance(value, errors.AppError):
            return {"__trippilot_error__": value.code}
        if isinstance(value, dict):
            return {key: self._encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._encode(item) for item in value]
        return value

    def _decode(self, value):
        if isinstance(value, dict):
            if set(value) == {"__trippilot_error__"}:
                error = self.error_types.get(value["__trippilot_error__"])
                if error is None:
                    raise ValueError("unknown checkpoint error")
                return error()
            return {key: self._decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decode(item) for item in value]
        return value

    def dumps_typed(self, value):
        return self.inner.dumps_typed(self._encode(value))

    def loads_typed(self, value):
        return self._decode(self.inner.loads_typed(value))


@contextmanager
def sqlite_checkpointer(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    try:
        yield SqliteSaver(connection, serde=CheckpointSerializer())
    finally:
        connection.close()
