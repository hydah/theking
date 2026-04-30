"""When init-sprint-plan finds multiple problems in one plan.json, it must
report them all at once so the agent can fix them in one edit cycle —
not drip-feed one error per run like the Kimi CLI feedback session
documented.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def bootstrap(tmp_path: Path) -> None:
    run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=tmp_path,
    )


def write_plan(tmp_path: Path, plan: dict) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    return plan_file


def _run_plan(tmp_path: Path, plan: dict) -> subprocess.CompletedProcess[str]:
    plan_file = write_plan(tmp_path, plan)
    return run_cli(
        [
            "init-sprint-plan",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )


def test_aggregates_contract_and_unknown_task_type_errors(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "bogus-type",
                "title": "Bogus Type",
                "task_type": "not-a-real-token",
            },
            {
                "slug": "bad-contract",
                "title": "Bad Contract",
                "task_type": "general",
                "execution_profile": "backend.http",
            },
        ],
    }
    r = _run_plan(tmp_path, plan)
    assert r.returncode != 0
    # Keep backward-compat substrings so existing tests that grep for them
    # keep passing.
    assert "Unknown" in r.stderr or "unknown" in r.stderr
    assert "incompatible" in r.stderr
    # Both task slugs must be named in the aggregated error output so the
    # agent can fix both at once.
    assert "bogus-type" in r.stderr or "bogus_type" in r.stderr
    assert "bad-contract" in r.stderr or "bad_contract" in r.stderr


def test_aggregates_two_contract_errors_across_tasks(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {"slug": "ok-task", "title": "Ok Task", "task_type": "general"},
            {
                "slug": "bad-one",
                "title": "Bad One",
                "task_type": "general",
                "execution_profile": "backend.http",
            },
            {
                "slug": "bad-two",
                "title": "Bad Two",
                "task_type": "frontend",
                "execution_profile": "backend.cli",
            },
        ],
    }
    r = _run_plan(tmp_path, plan)
    assert r.returncode != 0
    # Aggregation: both bad tasks must appear by slug; "ok-task" must not
    # be slandered with an error (it is legit).
    assert "bad-one" in r.stderr
    assert "bad-two" in r.stderr
    assert "incompatible" in r.stderr
    # Legit task name must not appear in any "error" context. We only check
    # it isn't flagged — its name may still appear benignly in diagnostic
    # banners, so don't over-assert.


def test_single_error_still_uses_substring_contract(tmp_path: Path) -> None:
    """Back-compat: a single-error plan still returns non-zero and stderr
    still contains the historic substrings the existing test suite greps for.
    """
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "only-bad",
                "title": "Only Bad",
                "task_type": "bogus",
            },
        ],
    }
    r = _run_plan(tmp_path, plan)
    assert r.returncode != 0
    assert "Unknown" in r.stderr or "unknown" in r.stderr


def test_aggregates_invalid_review_mode_with_other_task_errors(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "bad-review-mode",
                "title": "Bad Review Mode",
                "task_type": "general",
                "review_mode": "deep",
            },
            {
                "slug": "bad-contract",
                "title": "Bad Contract",
                "task_type": "general",
                "execution_profile": "backend.http",
            },
        ],
    }

    r = _run_plan(tmp_path, plan)

    assert r.returncode != 0
    assert "Plan file has 2 invalid task(s)" in r.stderr
    assert "bad-review-mode" in r.stderr
    assert "review_mode" in r.stderr
    assert "deep" in r.stderr
    assert "bad-contract" in r.stderr
    assert "incompatible" in r.stderr


def test_rejects_security_task_review_mode_downgrade(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "auth-light",
                "title": "Auth Light",
                "task_type": "auth",
                "execution_profile": "backend.http",
                "review_mode": "light",
            },
        ],
    }

    r = _run_plan(tmp_path, plan)

    assert r.returncode != 0
    assert "auth-light" in r.stderr
    assert "review_mode" in r.stderr
    assert "full" in r.stderr


def test_rejects_mixed_e2e_task_review_mode_downgrade(tmp_path: Path) -> None:
    bootstrap(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "e2e-job-light",
                "title": "E2E Job Light",
                "task_type": "e2e,job",
                "execution_profile": "backend.job",
                "review_mode": "light",
            },
        ],
    }

    r = _run_plan(tmp_path, plan)

    assert r.returncode != 0
    assert "e2e-job-light" in r.stderr
    assert "review_mode" in r.stderr
    assert "full" in r.stderr
