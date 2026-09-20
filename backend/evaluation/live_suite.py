"""Small fixed live case set; descriptive only, not a performance benchmark."""
import json
import sys

from .live_smoke import CASE, run_case

travel_date = CASE["start_date"]
CASES = [
    CASE,
    {
        "city": "北京", "start_date": travel_date, "end_date": travel_date,
        "transportation": "公共交通", "accommodation": "经济型酒店",
        "preferences": ["故宫"], "travelers": 1,
    },
    {
        "city": "杭州", "start_date": travel_date, "end_date": travel_date,
        "transportation": "自驾", "accommodation": "经济型酒店",
        "preferences": ["西湖"], "travelers": 1,
    },
]


def main() -> int:
    results = []
    for case in CASES:
        result = run_case(case)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = {
        "scope": "three predefined live cases; no latency percentile inference",
        "cases": len(results),
        "successful": sum(bool(item["success"]) for item in results),
        "tool_calls_completed": sum(int(item["tool_calls_completed"]) for item in results),
        "tool_calls_failed": sum(int(item["tool_calls_failed"]) for item in results),
        "provider_token_usage": None,
        "provider_cost": None,
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    return 0 if summary["successful"] == summary["cases"] else 1


if __name__ == "__main__":
    sys.exit(main())
