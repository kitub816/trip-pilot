"""One opt-in live API smoke case. Requires configured Amap and LLM providers.

Run from backend: python -m evaluation.live_smoke
The JSON summary contains no keys, prompts, raw provider responses or plan contents.
"""
import json
import time
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.api.main import create_app

CASE = {
    "city": "上海",
    "start_date": (date.today() + timedelta(days=30)).isoformat(),
    "end_date": (date.today() + timedelta(days=30)).isoformat(),
    "transportation": "步行",
    "accommodation": "经济型酒店",
    "preferences": ["外滩"],
    "travelers": 1,
}


def main() -> None:
    started = time.perf_counter()
    with TestClient(create_app()) as client:
        response = client.post("/api/trip/plan", json=CASE)
    payload = response.json()
    summary = {
        "scope": "single live FastAPI TestClient request through configured MCP and LLM",
        "city": CASE["city"],
        "start_date": CASE["start_date"],
        "http_status": response.status_code,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "success": response.status_code == 200 and payload.get("success") is True,
        "error_code": payload.get("error_code") if response.status_code != 200 else None,
        "days": len(payload.get("data", {}).get("days", [])) if response.status_code == 200 else None,
        "attractions": sum(len(day.get("attractions", [])) for day in payload.get("data", {}).get("days", [])) if response.status_code == 200 else None,
        "timed_attractions": sum(sum(item.get("visit_start") is not None and item.get("visit_end") is not None for item in day.get("attractions", [])) for day in payload.get("data", {}).get("days", [])) if response.status_code == 200 else None,
        "provider_token_usage": None,
        "provider_cost": None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
