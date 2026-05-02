"""End-to-end tests for workflowctl error-message hints.

Every error path that AI agents regularly hit during automated sessions must
include a `Hint:` line that names the allowed next commands — otherwise the
agent will loop through trial-and-error until context runs out (this was
observed in the Kimi CLI feedback transcript that motivated this sprint).

These tests call the real `workflowctl` CLI end-to-end so they also cover the
stderr wire format, not just the Python-level error object.
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


def _drive_through_green(tmp_path: Path, task_dir: Path) -> None:
    """Push a task draft -> planned -> red -> green, planting the
    sprint-017 TASK-002 runner PASS marker right before the red->green
    transition so the gate doesn't block CLI-driven test helpers."""
    from conftest import plant_test_pass_marker

    for to_status in ("planned", "red"):
        r = run_cli(
            ["advance-status", "--task-dir", str(task_dir), "--to-status", to_status],
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
    plant_test_pass_marker(task_dir)
    r = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "green"],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


SPEC_CONTENT = "\n".join(
    [
        "# Demo Task Spec",
        "",
        "## Scope",
        "- Minimal spec so task can leave planned.",
        "",
        "## Non-Goals",
        "- Not a real feature.",
        "",
        "## Acceptance",
        "- Test harness passes.",
        "",
        "## Test Plan",
        "- Unit test via pytest.",
        "- Exercise the happy path.",
        "- Exercise the error path.",
        "- Verify idempotency.",
        "- Run the regression suite.",
        "",
        "## Edge Cases",
        "- Empty input.",
        "- Boundary value.",
        "- Concurrent access.",
    ]
)


def bootstrap_sprint_with_task(tmp_path: Path) -> Path:
    """Create demo-app with a single general/backend.cli task.

    Writes a complete spec.md so advance-status can drive past planned.
    Returns the task directory.
    """
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
    run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "demo-task",
            "--title",
            "Demo Task",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )
    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-demo-task"
    )
    (task_dir / "spec.md").write_text(SPEC_CONTENT, encoding="utf-8")
    # sprint-015 TASK-001: draft-exit Goal gate.
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    return task_dir


# --- advance-status: illegal transition must list allowed moves + hint ---


def test_advance_status_illegal_transition_lists_allowed_moves(tmp_path: Path) -> None:
    task_dir = bootstrap_sprint_with_task(tmp_path)

    # Attempt green -> ready_to_merge (illegal; must go through in_review).
    # First push the task to green legally so the test exercises the green
    # outgoing edge, not draft.
    _drive_through_green(tmp_path, task_dir)

    r = run_cli(
        [
            "advance-status",
            "--task-dir",
            str(task_dir),
            "--to-status",
            "ready_to_merge",
        ],
        cwd=tmp_path,
    )
    assert r.returncode != 0
    # Old message substring MUST still be there (keeps backward compat for
    # anyone parsing it), AND the new hint text MUST be present.
    assert "Illegal status transition" in r.stderr
    assert "in_review" in r.stderr, (
        "error should list in_review as the only allowed move from green; "
        f"got stderr: {r.stderr!r}"
    )
    assert "Hint:" in r.stderr, (
        "error must include a 'Hint:' line naming the next workflowctl command"
    )


def test_advance_status_hint_points_at_init_review_round_for_green(tmp_path: Path) -> None:
    task_dir = bootstrap_sprint_with_task(tmp_path)
    _drive_through_green(tmp_path, task_dir)
    r = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "done"],
        cwd=tmp_path,
    )
    assert r.returncode != 0
    assert "init-review-round" in r.stderr, (
        "hint from green->done should steer the user to init-review-round "
        f"(which is the only legal next step); stderr: {r.stderr!r}"
    )


# --- init-review-round: in_review without transition should hint, not re-open ---


def _drive_task_to_in_review(tmp_path: Path, task_dir: Path) -> None:
    _drive_through_green(tmp_path, task_dir)
    r = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr


def test_init_review_round_refuses_when_already_in_review(tmp_path: Path) -> None:
    task_dir = bootstrap_sprint_with_task(tmp_path)
    _drive_task_to_in_review(tmp_path, task_dir)
    r = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )
    assert r.returncode != 0
    # Old message text still present for back-compat with any consumer; hint is the new value.
    assert "green" in r.stderr or "changes_requested" in r.stderr
    assert "Hint:" in r.stderr, "init-review-round rejection must include a Hint"
    assert (
        "ready_to_merge" in r.stderr or "advance-status" in r.stderr
    ), (
        "when task already in_review with round open, hint should steer toward "
        "advance-status ready_to_merge, NOT another init-review-round; "
        f"stderr: {r.stderr!r}"
    )


# --- validate_task_contract: incompatible pair must suggest alternatives ---


def test_init_sprint_plan_incompatible_contract_error_names_allowed_tokens(
    tmp_path: Path,
) -> None:
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
    plan = {
        "tasks": [
            {
                "slug": "bad-task",
                "title": "Bad Task",
                "task_type": "general",
                "execution_profile": "backend.http",
            },
        ],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")

    r = run_cli(
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
    assert r.returncode != 0
    # Backward compat keyword (existing callers grep for "incompatible").
    assert "incompatible" in r.stderr
    # New value: tell the user which task_type tokens ARE legal for this profile.
    # For backend.http at least `api`, `service` and `auth` must be named.
    legal_tokens = ["api", "service"]
    assert any(token in r.stderr for token in legal_tokens), (
        "error must name at least one allowed task_type for backend.http "
        f"(expected one of {legal_tokens}); stderr: {r.stderr!r}"
    )
