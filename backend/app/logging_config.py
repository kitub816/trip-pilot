"""Application JSON logs contain event names and IDs, not request bodies."""
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str] = ContextVar("request_id", default="-")

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Omit exception text/tracebacks and arbitrary extra fields.
        return json.dumps({"time": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                           "event": "mcp.transport_event" if record.name.startswith("mcp.") else record.getMessage(),
                           "request_id": request_id.get()}, ensure_ascii=False)

def configure_logging(level: str) -> None:
    logger = logging.getLogger("trippilot")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers[:] = [handler]
    logger.setLevel(level)
    logger.propagate = False
    # MCP parser exceptions may embed raw protocol contents. Keep only a safe event.
    mcp_logger = logging.getLogger("mcp")
    mcp_logger.handlers[:] = [handler]
    mcp_logger.setLevel(logging.WARNING)
    mcp_logger.propagate = False
