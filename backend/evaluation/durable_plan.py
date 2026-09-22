"""Opt-in local planning/resume command; may call configured real providers."""
import argparse
from pathlib import Path

from app.models.schemas import TripRequest
from app.services.constraint_service import build_travel_constraints
from app.services.checkpoint_service import sqlite_checkpointer
from app.workflows.trip_workflow import TripPlanningWorkflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--thread-id", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", type=Path)
    mode.add_argument("--resume", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with sqlite_checkpointer(args.db) as saver:
        workflow = TripPlanningWorkflow(checkpointer=saver)
        if args.resume:
            result = workflow.resume(args.thread_id)
        else:
            request = TripRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
            result = workflow.plan(build_travel_constraints(request), args.thread_id)
    args.output.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    print("Plan saved; no provider usage or cost inferred.")


if __name__ == "__main__":
    main()
