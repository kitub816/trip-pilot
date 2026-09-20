"""Opt-in live API case. Requires configured Amap and LLM providers.

Run from backend: python -m evaluation.live_smoke
The JSON summary contains no keys, prompts, raw provider responses or plan contents.
"""
import json
import logging
import sys
import time

from fastapi.testclient import TestClient

from app.api.main import create_app

CASE = {
    "city": "上海",
    "start_date": "2026-10-20",
    "end_date": "2026-10-20",
    "transportation": "步行",
    "accommodation": "经济型酒店",
    "preferences": ["外滩"],
    "travelers": 1,
}


class ToolEventCounter(logging.Handler):
    """Count observed MCP results without retaining input or provider output."""

    def __init__(self) -> None:
        super().__init__()
        self.completed = 0
        self.failed = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.msg.startswith("tool.completed."):
            self.completed += 1
        elif record.msg.startswith("tool.failed."):
            self.failed += 1


def run_case(case: dict[str, object]) -> dict[str, object]:
    counter = ToolEventCounter()
    tool_logger = logging.getLogger("trippilot.tools")
    tool_logger.addHandler(counter)
    started = time.perf_counter()
    try:
        with TestClient(create_app()) as client:
            response = client.post("/api/trip/plan", json=case)
    finally:
        tool_logger.removeHandler(counter)
    payload = response.json()
    success = response.status_code == 200 and payload.get("success") is True
    data = payload.get("data") if success else None
    days = data.get("days", []) if data else []
    return {
        "scope": "one live FastAPI TestClient request through configured MCP and LLM",
        "city": case["city"],
        "start_date": case["start_date"],
        "transportation": case["transportation"],
        "http_status": response.status_code,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "success": success,
        "error_code": payload.get("error_code") if not success else None,
        "tool_calls_completed": counter.completed,
        "tool_calls_failed": counter.failed,
        "days": len(days) if success else None,
        "attractions": sum(len(day.get("attractions", [])) for day in days) if success else None,
        "timed_attractions": sum(sum(item.get("visit_start") is not None
            and item.get("visit_end") is not None for item in day.get("attractions", []))
            for day in days) if success else None,
        "routes_complete": all((day.get("route") or {}).get("is_complete")
            for day in days) if success else None,
        "hard_constraints_validated": success,
        "provider_token_usage": None,
        "provider_cost": None,
    }


def main() -> int:
    summary = run_case(CASE)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
