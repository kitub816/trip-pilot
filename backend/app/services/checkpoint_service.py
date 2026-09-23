"""Local durable LangGraph state. No credentials, pickle or arbitrary imports."""
from contextlib import contextmanager
from dataclasses import is_dataclass
from pathlib import Path
import sqlite3

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel

from .. import errors
from ..config import get_settings
from ..models import knowledge, schemas, validation
from . import constraint_service, retrieval_service


def get_checkpoint_path() -> Path | None:
    raw = get_settings().checkpoint_path.strip()
    return Path(raw).expanduser().resolve() if raw else None


class CheckpointSerializer:
    def __init__(self):
        modules = (schemas, knowledge, validation, constraint_service, retrieval_service)
        allowed = []
        for module in modules:
            for value in vars(module).values():
                if isinstance(value, type) and value.__module__ == module.__name__:
                    if issubclass(value, BaseModel) or is_dataclass(value) or value in (
                        schemas.TransportationMode,
                        schemas.AccommodationType,
                    ):
                        allowed.append((value.__module__, value.__name__))
        self.inner = JsonPlusSerializer(
            pickle_fallback=False,
            allowed_msgpack_modules=allowed,
            allowed_json_modules=[],
        )
        self.error_types = {
            value.code: value
            for value in vars(errors).values()
            if isinstance(value, type) and issubclass(value, errors.AppError)
        }

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
    connection = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield SqliteSaver(connection, serde=CheckpointSerializer())
    finally:
        connection.close()


def delete_checkpoint_thread(path: Path, thread_id: str) -> None:
    with sqlite_checkpointer(path) as saver:
        saver.delete_thread(thread_id)
