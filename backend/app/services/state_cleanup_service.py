"""Retention cleanup for terminal plan records and their LangGraph threads."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .checkpoint_service import delete_checkpoint_thread
from .persistence_service import PlanStore


@dataclass(frozen=True)
class CleanupResult:
    candidates: int
    deleted: int


def cleanup_terminal_state(
    store: PlanStore,
    checkpoint_path: Path,
    cutoff: datetime,
    *,
    dry_run: bool = False,
    limit: int = 1000,
) -> CleanupResult:
    plan_ids = store.terminal_before(cutoff, limit)
    if dry_run:
        return CleanupResult(candidates=len(plan_ids), deleted=0)
    deleted = 0
    for plan_id in plan_ids:
        if checkpoint_path.exists():
            delete_checkpoint_thread(checkpoint_path, plan_id)
        if store.delete_terminal(plan_id, cutoff):
            deleted += 1
    return CleanupResult(candidates=len(plan_ids), deleted=deleted)
