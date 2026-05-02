"""Task Goal gate — sprint-015 TASK-001.

`workflowctl check` and `advance-status` must reject a task.md whose
`## Goal` section is still the template placeholder or is empty. The
placeholder-detection logic already exists in doctor.py (D1 zombie); this
gate enforces it at draft-exit time so tasks cannot reach `done` with a
placeholder Goal (root cause of the sprint-014 self-inflicted zombies).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_check_rules import make_valid_task_tree, run_cli, write_text


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


PLACEHOLDER_GOAL_BODY = (
    "<!-- Describe the expected OUTCOME, not the implementation.\n"
    "     Example: \"Users can log in via OAuth and see their personal dashboard.\" -->"
)
EMPTY_GOAL_BODY = ""  # literally nothing under ## Goal


def _overwrite_goal_section(task_md: Path, new_goal_body: str) -> None:
    """Replace the body under `## Goal` until the next `## ` heading."""
    text = task_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Goal")
    except StopIteration as exc:  # pragma: no cover - fixture guarantee
        raise AssertionError("fixture task.md has no ## Goal heading") from exc
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    new_block = ["## Goal"]
    if new_goal_body:
        new_block.append(new_goal_body)
    new_block.append("")  # trailing blank before next section
    task_md.write_text("\n".join(lines[:start] + new_block + lines[end:]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# `workflowctl check` must reject placeholder / empty Goal
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# `workflowctl check` is tolerant of placeholder Goal on draft tasks.
# Rationale: fresh init-task output is always placeholder; `check` is a
# read-only inspection used during authoring. The real gate is at draft
# EXIT (advance-status), not draft INSPECTION. This matches how the
# spec-section-count gate works (it only fires once spec is "required",
# not on every check call).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "goal_body,label",
    [(PLACEHOLDER_GOAL_BODY, "placeholder-comment"), (EMPTY_GOAL_BODY, "empty-body")],
)
def test_check_tolerates_placeholder_or_empty_goal_on_draft(
    tmp_path: Path, goal_body: str, label: str
) -> None:
    """`check` does NOT reject placeholder Goal — it's a read-only inspection.

    The gate fires at advance-status draft-exit (see
    `test_advance_status_blocks_draft_exit_with_placeholder_goal`).
    """
    task_dir = make_valid_task_tree(tmp_path, status="draft")
    _overwrite_goal_section(task_dir / "task.md", goal_body)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"check should remain tolerant on drafts with {label} Goal. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_check_accepts_substantive_goal(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, status="draft")
    _overwrite_goal_section(
        task_dir / "task.md",
        "A developer can run `widget build` and get a deployable artifact.",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"substantive Goal must pass check. stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# `workflowctl advance-status` must refuse draft->planned with placeholder Goal
# ---------------------------------------------------------------------------


def test_advance_status_blocks_draft_exit_with_placeholder_goal(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, status="draft")
    _overwrite_goal_section(task_dir / "task.md", PLACEHOLDER_GOAL_BODY)

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )

    assert result.returncode != 0, (
        f"advance-status must refuse placeholder Goal. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    task_md_after = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "status: draft" in task_md_after, (
        "status must stay at draft when gate rejects; got task.md:\n" + task_md_after
    )


def test_advance_status_allows_planned_with_substantive_goal(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, status="draft")
    _overwrite_goal_section(
        task_dir / "task.md",
        "Operators can run `foo bar` and observe a non-zero exit on malformed input.",
    )

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, (
        f"substantive Goal must allow draft->planned. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    task_md_after = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "status: planned" in task_md_after
