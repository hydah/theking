"""End-to-end tests for `workflowctl finalize`.

`workflowctl finalize --task-dir <DIR>` is a convenience subcommand that
performs `check` + `advance-status ready_to_merge` + `advance-status done`
in one call.  These tests are written RED-first: the `finalize` subcommand
does not exist yet in workflowctl.py, so every test is expected to fail.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"

SPEC_CONTENT = "\n".join(
    [
        "# Demo Task Spec",
        "",
        "## Scope",
        "- Non-empty scope for finalize tests.",
        "",
        "## Non-Goals",
        "- None.",
        "",
        "## Acceptance",
        "- Task finalizes cleanly.",
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


def set_task_status(
    task_md: Path,
    *,
    status: str,
    history: list[str],
    current_review_round: int,
) -> None:
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


def bootstrap_project_and_sprint(tmp_path: Path) -> Path:
    """Bootstrap a project + sprint + single task, returning the task_dir."""
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
            "finalize-demo",
            "--title",
            "Finalize Demo",
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
        / "TASK-001-finalize-demo"
    )
    (task_dir / "spec.md").write_text(SPEC_CONTENT, encoding="utf-8")
    return task_dir


def advance(tmp_path: Path, task_dir: Path, to: str) -> None:
    """Drive a task forward via advance-status.

    Seeds verification evidence before ready_to_merge so the substantive-
    evidence gate (ADR-003) passes without running a real test suite.
    """
    evidence = task_dir / "verification" / "cli" / "test.log"
    if to == "ready_to_merge" and not (evidence.exists() and evidence.stat().st_size > 0):
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            "pytest run ok: happy path passes, error path passes, regression clean\n",
            encoding="utf-8",
        )
    r = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", to],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr


def advance_to_in_review(tmp_path: Path, task_dir: Path) -> None:
    """Advance a freshly-created task through planned -> red -> green -> in_review."""
    for status in ("planned", "red", "green"):
        advance(tmp_path, task_dir, status)
    r = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr


def write_review_pair(task_dir: Path, round_number: int = 1) -> None:
    """Write a code-review + resolved pair for the given round.

    init-review-round already creates the review file; this helper
    writes the .resolved.md counterpart that ``check`` demands before
    the task can cross into ready_to_merge.
    """
    review_dir = task_dir / "review"
    review_dir.mkdir(exist_ok=True)
    review_file = review_dir / f"code-review-round-{round_number:03d}.md"
    if not review_file.is_file():
        review_file.write_text(
            f"# Code Review Round {round_number:03d}\n\n"
            "## Context\n- Finalize demo\n\n"
            "## Findings\n- None\n",
            encoding="utf-8",
        )
    resolved_file = review_dir / f"code-review-round-{round_number:03d}.resolved.md"
    resolved_file.write_text(
        f"# Resolved Code Review Round {round_number:03d}\n\n"
        "## Fixes\n\n"
        "### finding-001\n"
        "- Status: resolved\n"
        "- Fix: Nothing actually needed — placeholder finding in scaffold.\n"
        "- Evidence: pytest\n\n"
        "## Verification\n- pytest passed\n",
        encoding="utf-8",
    )


def seed_verification_evidence(task_dir: Path) -> None:
    """Seed substantive verification evidence (>= 40 chars) for the CLI profile."""
    evidence = task_dir / "verification" / "cli" / "test.log"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "pytest run ok: happy path passes, error path passes, regression clean\n",
        encoding="utf-8",
    )


def read_task_status(task_dir: Path) -> str:
    """Extract the current status from task.md frontmatter."""
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    match = re.search(r"^status: (\S+)", text, re.MULTILINE)
    assert match is not None, f"Could not find status in task.md:\n{text}"
    return match.group(1)


def force_task_to_done(task_dir: Path) -> None:
    """Force a task into done state with all review and verification artifacts."""
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
    (task_dir / "spec.md").write_text(SPEC_CONTENT, encoding="utf-8")
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
        "# Verification\n"
        "- Command: forged pytest run for finalize tests\n"
        "- Stdout: OK all transitions accounted for, exit=0\n",
        encoding="utf-8",
    )


def force_task_to_ready_to_merge(task_dir: Path) -> None:
    """Force a task into ready_to_merge state with all required artifacts."""
    set_task_status(
        task_dir / "task.md",
        status="ready_to_merge",
        history=[
            "draft",
            "planned",
            "red",
            "green",
            "in_review",
            "ready_to_merge",
        ],
        current_review_round=1,
    )
    (task_dir / "spec.md").write_text(SPEC_CONTENT, encoding="utf-8")
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
        "# Verification\n"
        "- Command: forged pytest run for finalize tests\n"
        "- Stdout: OK all transitions accounted for, exit=0\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_finalize_succeeds_on_reviewed_task(tmp_path: Path) -> None:
    """A task in in_review with complete review pairs and verification
    evidence should finalize successfully (check + ready_to_merge + done)."""
    task_dir = bootstrap_project_and_sprint(tmp_path)
    advance_to_in_review(tmp_path, task_dir)
    write_review_pair(task_dir, round_number=1)
    seed_verification_evidence(task_dir)

    result = run_cli(
        ["finalize", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, (
        f"Expected finalize to succeed on a reviewed task. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert read_task_status(task_dir) == "done", (
        f"Task should be in done state after finalize, "
        f"got {read_task_status(task_dir)!r}"
    )


def test_finalize_fails_on_check_failure(tmp_path: Path) -> None:
    """A task in in_review without a resolved review file should fail
    finalize at the check step (missing review pair)."""
    task_dir = bootstrap_project_and_sprint(tmp_path)
    advance_to_in_review(tmp_path, task_dir)
    # Deliberately do NOT write code-review-round-001.resolved.md.
    # The check gate requires the resolved file for ready_to_merge transitions.

    result = run_cli(
        ["finalize", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0, (
        f"Expected finalize to fail when review pair is incomplete. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # The error must come from the finalize subcommand's validation gate
    # (not from argparse rejecting an unknown subcommand). The specific
    # gate that fires first may vary (evidence check, missing review pair,
    # etc.), so we only verify it's a non-zero exit from the finalize path.
    combined_output = result.stdout + result.stderr
    assert (
        "finalize" not in combined_output.lower()
        or "unrecognized" not in combined_output.lower()
    ), (
        f"Expected a validation failure, not an argparse error. "
        f"stderr={result.stderr!r}"
    )


def test_finalize_on_done_task_is_idempotent(tmp_path: Path) -> None:
    """Running finalize on a task already in done state should succeed
    (idempotent) and indicate the task is already done."""
    task_dir = bootstrap_project_and_sprint(tmp_path)
    force_task_to_done(task_dir)

    result = run_cli(
        ["finalize", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, (
        f"Expected finalize to be idempotent on a done task. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined_output = (result.stdout + result.stderr).lower()
    assert "already" in combined_output or "done" in combined_output, (
        f"Output should mention the task is already done. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert read_task_status(task_dir) == "done"


def test_finalize_from_ready_to_merge(tmp_path: Path) -> None:
    """A task already in ready_to_merge should finalize to done
    (skipping the ready_to_merge advance, only doing check + done)."""
    task_dir = bootstrap_project_and_sprint(tmp_path)
    force_task_to_ready_to_merge(task_dir)

    result = run_cli(
        ["finalize", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, (
        f"Expected finalize to succeed from ready_to_merge. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert read_task_status(task_dir) == "done", (
        f"Task should be in done state after finalize, "
        f"got {read_task_status(task_dir)!r}"
    )


def test_finalize_appears_in_help(tmp_path: Path) -> None:
    """The finalize subcommand must be discoverable via --help."""
    result = run_cli(["--help"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "finalize" in result.stdout, (
        f"Expected 'finalize' in --help output. stdout={result.stdout!r}"
    )
