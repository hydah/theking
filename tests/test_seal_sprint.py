"""End-to-end tests for `workflowctl seal-sprint`.

These tests cover ADR-002: a sealed sprint becomes an immutable audit unit.
init-task and init-sprint-plan must refuse to write into a sealed sprint;
seal-sprint itself must require every task to be terminal (done or blocked)
and must be idempotent on a re-seal.
"""

from __future__ import annotations

import json
import re
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


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def set_task_status(task_md: Path, *, status: str, history: list[str], current_review_round: int) -> None:
    content = task_md.read_text(encoding="utf-8")
    history_block = "\n".join(f"  - {entry}" for entry in history)
    content = re.sub(
        r"status: \S+\nstatus_history:\n(?:  - .*\n)+",
        f"status: {status}\nstatus_history:\n{history_block}\n",
        content,
        count=1,
    )
    content = re.sub(
        r"current_review_round: \d+",
        f"current_review_round: {current_review_round}",
        content,
        count=1,
    )
    task_md.write_text(content, encoding="utf-8")


def force_task_to_done(task_dir: Path) -> None:
    set_task_status(
        task_dir / "task.md",
        status="done",
        history=[
            "draft",
            "planned",
            "red",
            "green",
            "in_review",
            "ready_to_merge",
            "done",
        ],
        current_review_round=1,
    )
    # Spec must be a complete, content-bearing structure to pass full-flow
    # validation at done-state check time.
    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Forged scope for sealing tests.",
                "",
                "## Non-Goals",
                "- No real implementation.",
                "",
                "## Acceptance",
                "- Task can reach done for sealing tests.",
                "",
                "## Test Plan",
                "- Run the relevant verification.",
                "- Exercise happy path.",
                "- Exercise error path.",
                "- Verify idempotency.",
                "- Run regression.",
                "",
                "## Edge Cases",
                "- Repeated transitions stay consistent.",
                "- Missing optional inputs do not crash.",
                "- Partial artifacts do not block recovery.",
            ]
        ),
        encoding="utf-8",
    )
    # Reviews + verification must exist for sprint-check / check to pass.
    review_dir = task_dir / "review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "code-review-round-001.md").write_text(
        "# Code Review Round 001\n\n## Context\n- forged for test\n\n## Findings\n- none\n",
        encoding="utf-8",
    )
    (review_dir / "code-review-round-001.resolved.md").write_text(
        "# Resolved Code Review Round 001\n\n## Fixes\n- forged\n\n## Verification\n- forged\n",
        encoding="utf-8",
    )
    verification_dir = task_dir / "verification" / "cli"
    verification_dir.mkdir(parents=True, exist_ok=True)
    (verification_dir / "result.md").write_text(
        # Must carry >= 40 substantive chars to satisfy the substantive-
        # evidence gate (ADR-003 / sprint-004 TASK-001). 'forged' alone is
        # only 6 substantive chars and would now be rejected.
        "# Verification\n"
        "- Command: forged pytest run for sealing tests\n"
        "- Stdout: OK all transitions accounted for, exit=0\n",
        encoding="utf-8",
    )

    # Sprint-level smoke evidence (ADR-003 / sprint-004 TASK-003). Without
    # this, `seal-sprint`'s new `validate_sprint_smoke_evidence` pre-check
    # would refuse to seal. Writing it here keeps every existing
    # `force_task_to_done` caller working unchanged.
    sprint_dir = task_dir.parent.parent
    sprint_verification = sprint_dir / "verification" / "cli" / "smoke.md"
    sprint_verification.parent.mkdir(parents=True, exist_ok=True)
    sprint_verification.write_text(
        "# Sprint-level smoke (forged for sealing tests)\n"
        "- Command: workflowctl sprint-smoke --sprint-dir <X>\n"
        "- Stdout: OK sprint-001-foundation\n"
        "- Exit: 0\n",
        encoding="utf-8",
    )


def force_task_to_blocked(task_dir: Path) -> None:
    """A task that was ever live (red/green) and got blocked counts as terminal
    for sealing purposes."""
    set_task_status(
        task_dir / "task.md",
        status="blocked",
        history=["draft", "planned", "blocked"],
        current_review_round=0,
    )


def bootstrap_sprint_with_one_task(tmp_path: Path) -> Path:
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
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
        ],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    run_cli(
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
    return workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"


def bootstrap_sprint_with_two_tasks(tmp_path: Path) -> Path:
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
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
            {"slug": "task-b", "title": "Task B", "task_type": "general"},
        ],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    run_cli(
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
    return workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"


def test_seal_sprint_succeeds_when_all_tasks_done(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_done(sprint_dir / "tasks" / "TASK-001-task-a")

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    sprint_md_text = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert sprint_md_text.startswith("---\n"), "sealed sprint.md must lead with frontmatter"
    assert "status: sealed" in sprint_md_text
    assert re.search(
        r"sealed_at: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", sprint_md_text
    ), "sealed_at must be UTC ISO8601 with Z suffix"
    # Body below frontmatter must keep the original H1.
    body_start = sprint_md_text.index("\n---\n", 4) + len("\n---\n")
    assert sprint_md_text[body_start:].startswith("# sprint-001-foundation")


def test_seal_sprint_is_idempotent_and_preserves_sealed_at(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_done(sprint_dir / "tasks" / "TASK-001-task-a")

    first = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    sprint_md_after_first = (sprint_dir / "sprint.md").read_text(encoding="utf-8")

    second = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert second.returncode == 0, second.stderr
    sprint_md_after_second = (sprint_dir / "sprint.md").read_text(encoding="utf-8")

    assert sprint_md_after_first == sprint_md_after_second, (
        "re-seal must be a no-op; sealed_at must not be regenerated"
    )


def test_seal_sprint_rejects_non_terminal_task(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    set_task_status(
        sprint_dir / "tasks" / "TASK-001-task-a" / "task.md",
        status="red",
        history=["draft", "planned", "red"],
        current_review_round=0,
    )

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "TASK-001-task-a" in result.stderr
    assert "red" in result.stderr or "terminal" in result.stderr
    sprint_md_text = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert "status: sealed" not in sprint_md_text


def test_seal_sprint_accepts_blocked_task_as_terminal(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_blocked(sprint_dir / "tasks" / "TASK-001-task-a")

    # Blocked tasks still demand sprint-level evidence per ADR-003 闸 3
    # (the task's execution_profile is still in scope). Seed substantive
    # evidence so seal-sprint's sprint-smoke pre-check passes.
    sprint_evidence = sprint_dir / "verification" / "cli" / "smoke.md"
    sprint_evidence.parent.mkdir(parents=True, exist_ok=True)
    sprint_evidence.write_text(
        "# Sprint-level smoke\n"
        "- Blocked task: TASK-001-task-a\n"
        "- Evidence: sealing with blocked-as-terminal is allowed per ADR-002\n",
        encoding="utf-8",
    )

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "status: sealed" in (sprint_dir / "sprint.md").read_text(encoding="utf-8")


def test_seal_sprint_rejects_empty_sprint(tmp_path: Path) -> None:
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
    sprint_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "no tasks" in result.stderr.lower() or "empty" in result.stderr.lower()


def test_init_task_rejects_sealed_sprint(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_done(sprint_dir / "tasks" / "TASK-001-task-a")
    seal = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert seal.returncode == 0, seal.stderr

    result = run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "late-task",
            "--title",
            "Late Task",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "sealed" in result.stderr
    assert "followup-sprint" in result.stderr
    assert not (sprint_dir / "tasks" / "TASK-002-late-task").exists()


def test_init_sprint_plan_rejects_sealed_sprint(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_done(sprint_dir / "tasks" / "TASK-001-task-a")
    seal = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert seal.returncode == 0, seal.stderr

    plan = {
        "tasks": [
            {"slug": "another", "title": "Another", "task_type": "general"},
        ],
    }
    plan_file = tmp_path / "another-plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")

    result = run_cli(
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

    assert result.returncode != 0
    assert "sealed" in result.stderr
    assert "followup-sprint" in result.stderr


def test_legacy_sprint_md_without_frontmatter_still_validates(tmp_path: Path) -> None:
    """sprint-001 / sprint-002 already exist with no frontmatter. Sealing must
    not be required for them to keep working with init-task / sprint-check.
    """
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)

    # Confirm sprint.md has NO frontmatter (the init-sprint template stays as-is).
    sprint_md_text = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert not sprint_md_text.startswith("---\n"), (
        "init-sprint must not retroactively add frontmatter"
    )

    result = run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "second-task",
            "--title",
            "Second Task",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (sprint_dir / "tasks" / "TASK-002-second-task" / "task.md").is_file()


def test_seal_sprint_rejects_unknown_frontmatter_keys(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    force_task_to_done(sprint_dir / "tasks" / "TASK-001-task-a")
    sprint_md = sprint_dir / "sprint.md"
    original = sprint_md.read_text(encoding="utf-8")
    sprint_md.write_text(
        "---\nbogus_key: yes\n---\n" + original,
        encoding="utf-8",
    )

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "bogus_key" in result.stderr or "unknown" in result.stderr.lower()


def test_advance_status_still_works_on_sealed_sprint_task(tmp_path: Path) -> None:
    """Sealing only locks sprint.md and write surfaces. Existing tasks remain
    legal targets for read/check operations; advance-status against a done
    task is naturally rejected for being terminal, but check should still pass.
    """
    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    force_task_to_done(task_dir)
    seal = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert seal.returncode == 0, seal.stderr

    check = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert check.returncode == 0, check.stderr

    sprint_check = run_cli(["sprint-check", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert sprint_check.returncode == 0, sprint_check.stderr


# --- Sprint-004 TASK-003: sprint-smoke pre-check for seal-sprint ------------


def test_seal_sprint_refuses_without_sprint_smoke_evidence(tmp_path: Path) -> None:
    """TASK-003 闸 3: `seal-sprint` must fail before writing frontmatter
    when `sprint_dir/verification/<profile>/` has no substantive evidence.

    Uses a multi-task sprint because single-task sprints now fall back
    to task-level evidence (sprint-007 TASK-002 optimization). The
    sprint-level gate is only strict for 2+ task sprints.
    """

    sprint_dir = bootstrap_sprint_with_two_tasks(tmp_path)
    for task_dir in sorted((sprint_dir / "tasks").iterdir()):
        if task_dir.name.startswith("TASK-"):
            force_task_to_done(task_dir)

    # Ensure no sprint-level evidence exists.
    sprint_verification = sprint_dir / "verification"
    if sprint_verification.exists():
        import shutil as _shutil

        _shutil.rmtree(sprint_verification)

    sprint_md_before = (sprint_dir / "sprint.md").read_text(encoding="utf-8")

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected seal-sprint to refuse without sprint-level evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

    # sprint.md must be unchanged — no partial write.
    sprint_md_after = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert sprint_md_after == sprint_md_before, (
        "seal-sprint failed but sprint.md was modified — no partial writes allowed"
    )

    # Error should name either the missing profile or the smoke gate.
    stderr_lower = result.stderr.lower()
    assert (
        "cli" in stderr_lower
        or "substantive" in stderr_lower
        or "sprint-smoke" in stderr_lower
        or "smoke" in stderr_lower
    ), f"Error should mention the sprint-smoke cause. stderr={result.stderr!r}"


def test_seal_sprint_succeeds_with_sprint_smoke_evidence(tmp_path: Path) -> None:
    """Positive path for the sprint-smoke pre-check: when sprint-level
    evidence is substantive, `seal-sprint` proceeds and stamps the
    sealed frontmatter as usual."""

    sprint_dir = bootstrap_sprint_with_one_task(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    force_task_to_done(task_dir)

    # Place sprint-level substantive evidence. The file path under
    # verification/cli matches backend.cli's execution_profile_dir.
    sprint_evidence = sprint_dir / "verification" / "cli" / "smoke.md"
    sprint_evidence.parent.mkdir(parents=True, exist_ok=True)
    sprint_evidence.write_text(
        "# Sprint-level smoke\n"
        "- Command: workflowctl sprint-smoke --sprint-dir <X>\n"
        "- Stdout: OK sprint-001-foundation\n"
        "- Exit: 0\n",
        encoding="utf-8",
    )

    result = run_cli(["seal-sprint", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"Expected seal-sprint to pass with sprint-level evidence. "
        f"stderr={result.stderr!r}"
    )
    sprint_md = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert sprint_md.startswith("---\n"), "sealed sprint.md should have frontmatter"
    assert "status: sealed" in sprint_md
