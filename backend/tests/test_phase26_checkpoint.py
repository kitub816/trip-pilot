"""Real SQLite reopen, resume, thread isolation and terminal-error persistence."""
import subprocess
import sys
from types import SimpleNamespace
import pytest

from app.errors import ServiceBusy
from app.models.schemas import TripPlan, TripRequest
from app.models.validation import PlanValidationResult
from app.services.checkpoint_service import sqlite_checkpointer
from app.services.constraint_service import build_travel_constraints
from app.workflows.trip_workflow import TripPlanningWorkflow


def constraints():
    return build_travel_constraints(TripRequest(city="上海", start_date="2026-10-01",
        end_date="2026-10-01", transportation="步行", accommodation="民宿"))


def workflow(saver, calls, crash=False, error=False):
    def plan(c):
        calls.append("plan")
        if error:
            raise ServiceBusy()
        return TripPlan(city=c.city, start_date=str(c.start_date), end_date=str(c.end_date),
                        days=[], overall_suggestions="fixture")
    def route(plan, c):
        calls.append("route")
        if crash:
            raise RuntimeError("simulated interruption")
        return plan
    return TripPlanningWorkflow(checkpointer=saver,
        planner_factory=lambda: SimpleNamespace(plan_trip=plan),
        route_optimizer=SimpleNamespace(apply=route),
        budget_engine=SimpleNamespace(apply=lambda plan, c: plan),
        validator=SimpleNamespace(validate=lambda *args: PlanValidationResult()))


def test_resume_after_reopen_does_not_repeat_completed_planner(tmp_path):
    path=tmp_path/"checkpoint.sqlite"
    calls=[]
    with sqlite_checkpointer(path) as saver:
        with pytest.raises(RuntimeError, match="simulated"):
            workflow(saver,calls,crash=True).plan(constraints(),"case")
    with sqlite_checkpointer(path) as saver:
        assert workflow(saver,calls).resume("case").city=="上海"
        assert workflow(saver,calls).resume("case").city=="上海"
        with pytest.raises(ValueError, match="already exists"):
            workflow(saver,calls).plan(constraints(),"case")
        with pytest.raises(ValueError, match="not found"):
            workflow(saver,calls).resume("missing")
    assert calls==["plan","route","route"]
    script = (
        "from pathlib import Path; from app.services.checkpoint_service import sqlite_checkpointer; "
        "from app.workflows.trip_workflow import TripPlanningWorkflow; import sys; "
        "ctx=sqlite_checkpointer(Path(sys.argv[1])); saver=ctx.__enter__(); "
        "p=TripPlanningWorkflow(checkpointer=saver).resume('case'); "
        "assert len(p.days)==0; ctx.__exit__(None,None,None); print('restored')"
    )
    result=subprocess.run([sys.executable,"-c",script,str(path)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0, result.stderr
    assert "restored" in result.stdout


def test_terminal_safe_error_survives_checkpoint(tmp_path):
    calls=[]
    path=tmp_path/"checkpoint.sqlite"
    with sqlite_checkpointer(path) as saver:
        with pytest.raises(ServiceBusy):
            workflow(saver,calls,error=True).plan(constraints(),"failed")
    with sqlite_checkpointer(path) as saver:
        with pytest.raises(ServiceBusy):
            workflow(saver,calls).resume("failed")
    assert calls==["plan"]


def test_threads_are_isolated(tmp_path):
    calls=[]
    with sqlite_checkpointer(tmp_path/"checkpoint.sqlite") as saver:
        flow=workflow(saver,calls)
        flow.plan(constraints(),"one")
        flow.plan(constraints(),"two")
        assert flow.resume("one").city=="上海"
    assert calls.count("plan")==2
