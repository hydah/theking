"""Full coverage of init-review-round's accept / reject paths + hint text.

The Kimi-CLI session that motivated this sprint got stuck in a round-2
"empty rubber-stamp" death loop because init-review-round's reject message
didn't tell the agent what to do next. These tests pin every state that
init-review-round can encounter.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


SPEC_CONTENT = "\n".join(
    [
        "# Demo Task Spec",
        "",
        "## Scope",
        "- Non-empty scope.",
        "",
        "## Non-Goals",
        "- None.",
        "",
        "## Acceptance",
        "- Green.",
        "",
        "## Test Plan",
        "- Run pytest.",
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


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def _setup(tmp_path: Path) -> Path:
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
    return task_dir


def _advance(tmp_path: Path, task_dir: Path, to: str) -> None:
    """Drive a task into ``to`` via ``workflowctl advance-status``.

    Side effect: before advancing to ``ready_to_merge`` this helper auto-seeds
    a fake ``verification/cli/test.log`` so the evidence gate passes without
    us having to run a real test in the test harness. This is explicit and
    limited to the ``ready_to_merge`` transition — all other transitions use
    only the data already seeded by ``init-task``.
    """
    # sprint-015 TASK-001: draft-exit Goal gate. Ensure Goal is populated
    # before advancing past draft. Idempotent on non-draft tasks.
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    evidence = task_dir / "verification" / "cli" / "test.log"
    if to == "ready_to_merge" and not (evidence.exists() and evidence.stat().st_size > 0):
        evidence.parent.mkdir(parents=True, exist_ok=True)
        # Must carry >= 40 substantive chars to satisfy ADR-003 gate; a
        # bare "pytest run ok" (12 chars) is now rejected by the
        # substantive-evidence check in validate_verification_layout.
        evidence.write_text(
            "pytest run ok: happy path passes, error path passes, regression clean\n",
            encoding="utf-8",
        )
    r = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", to],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr


# --- accept paths ---


def test_init_review_round_on_green_creates_round_1(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    for s in ("planned", "red", "green"):
        _advance(tmp_path, task_dir, s)
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (task_dir / "review" / "code-review-round-001.md").is_file()


def test_init_review_round_on_changes_requested_creates_round_2(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    for s in ("planned", "red", "green"):
        _advance(tmp_path, task_dir, s)
    # Enter round 1, then down to changes_requested, then back up.
    assert (
        run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path).returncode
        == 0
    )
    # Simulate resolved round 1 before driving to changes_requested so that
    # the subsequent re-entry into in_review can find its prior pair.
    # init-review-round emits a `### finding-001` scaffold in the review `.md`,
    # so the paired resolved must close that id (sprint-010 coverage gate).
    (task_dir / "review" / "code-review-round-001.resolved.md").write_text(
        "# Resolved\n\n"
        "## Fixes\n\n"
        "### finding-001\n"
        "- Status: resolved\n"
        "- Fix: code fixed\n"
        "- Evidence: pytest\n\n"
        "## Verification\n\n- pytest\n",
        encoding="utf-8",
    )
    _advance(tmp_path, task_dir, "changes_requested")
    # Re-enter red/green cycle (hard-rule: code changes go through red/green).
    _advance(tmp_path, task_dir, "red")
    _advance(tmp_path, task_dir, "green")
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (task_dir / "review" / "code-review-round-002.md").is_file()


# --- reject paths with hints ---


def test_init_review_round_rejected_from_draft_gives_hint(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    # status = draft (initial)
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode != 0
    assert "Hint" in r.stderr
    # Hint should name the immediate next legal move toward green.
    assert "planned" in r.stderr or "advance-status" in r.stderr


def test_init_review_round_rejected_from_planned_hints_at_red(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    _advance(tmp_path, task_dir, "planned")
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode != 0
    assert "Hint" in r.stderr
    assert "red" in r.stderr, f"hint from planned should point at red; stderr: {r.stderr!r}"


def test_init_review_round_rejected_from_red_hints_at_green(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    for s in ("planned", "red"):
        _advance(tmp_path, task_dir, s)
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode != 0
    assert "Hint" in r.stderr
    assert "green" in r.stderr


def test_init_review_round_rejected_when_already_in_review_hints_ready_to_merge(
    tmp_path: Path,
) -> None:
    task_dir = _setup(tmp_path)
    for s in ("planned", "red", "green"):
        _advance(tmp_path, task_dir, s)
    assert (
        run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path).returncode
        == 0
    )
    # Second invocation while already in_review should fail with actionable hint.
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode != 0
    assert "Hint" in r.stderr
    assert "ready_to_merge" in r.stderr or "advance-status" in r.stderr
    # Critical: the hint must steer AWAY from opening another round without
    # a code change (this was the Kimi CLI failure mode). We require the
    # specific "empty extra round" phrase so future refactors can't water
    # down the warning by accident.
    assert "empty extra round" in r.stderr, (
        "hint must name the 'empty extra round' failure mode explicitly; "
        f"stderr: {r.stderr!r}"
    )


def test_init_review_round_rejected_from_ready_to_merge_hints_done(tmp_path: Path) -> None:
    task_dir = _setup(tmp_path)
    for s in ("planned", "red", "green"):
        _advance(tmp_path, task_dir, s)
    run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    # Need a resolved file to cross into ready_to_merge. init-review-round
    # emitted `### finding-001` in the review markdown, so the resolved file
    # must close that id (sprint-010 coverage gate).
    (task_dir / "review" / "code-review-round-001.resolved.md").write_text(
        "# Resolved\n\n"
        "## Fixes\n\n"
        "### finding-001\n"
        "- Status: resolved\n"
        "- Fix: nothing\n"
        "- Evidence: pytest\n\n"
        "## Verification\n\n- pytest\n",
        encoding="utf-8",
    )
    _advance(tmp_path, task_dir, "ready_to_merge")
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode != 0
    assert "Hint" in r.stderr
    assert "done" in r.stderr or "advance-status" in r.stderr
