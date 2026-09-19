"""Measure only the fixed offline constraint suite; no provider or network calls."""

import hashlib
import json
import platform
import statistics
import time
from pathlib import Path

from app.services.evaluation_service import run_constraint_cases


def main() -> None:
    dataset = Path(__file__).with_name("constraint_cases.json")
    for _ in range(10):
        run_constraint_cases(dataset)
    samples_ms: list[float] = []
    result = None
    for _ in range(100):
        start = time.perf_counter()
        result = run_constraint_cases(dataset)
        samples_ms.append((time.perf_counter() - start) * 1000)
    ordered = sorted(samples_ms)
    report = {
        "scope": "offline constraint validation only",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "cases": result["total"],
        "matched": result["matched"],
        "warmup_runs": 10,
        "measured_runs": 100,
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[94], 3),
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
