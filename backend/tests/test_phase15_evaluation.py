from pathlib import Path

from app.services.evaluation_service import run_constraint_cases


def test_fixed_constraint_evaluation_fixture_is_reproducible():
    path = Path(__file__).parents[1] / "evaluation" / "constraint_cases.json"
    assert run_constraint_cases(path) == {"total": 3, "matched": 3}
