"""End-to-end CLI tests for the optional `flow:` task.md frontmatter field.

Sprint-002 TASK-001 introduced the per-task `flow: full | lightweight`
frontmatter that drives `validate_spec_section_counts` thresholds. The unit
tests in `tests/test_check_rules.py` cover the helper functions in isolation.

This file (sprint-003 TASK-003 / I-008) exercises the FULL chain via the
real CLI: a sparse spec (3 Test Plan + 1 Edge Cases) must pass on
lightweight flow and fail on full flow, exercising init-task -> spec write
-> task.md edit -> advance-status planned -> red.
"""

from __future__ import annotations

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


def bootstrap_sprint(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    init_sprint = run_cli(
        [
            "init-sprint", "--root", str(tmp_path),
            "--project-slug", "demo-app", "--theme", "foundation",
        ],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr
    assert init_sprint.returncode == 0, init_sprint.stderr


def init_general_task(tmp_path: Path, *, slug: str) -> Path:
    result = run_cli(
        [
            "init-task", "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", slug,
            "--title", slug.title(),
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    task_dir = (
        workflow_root(tmp_path)
        / "sprints" / "sprint-001-foundation"
        / "tasks" / f"TASK-001-{slug}"
    )
    assert task_dir.is_dir()
    return task_dir


def write_sparse_spec(task_dir: Path) -> None:
    """3 Test Plan items, 1 Edge Cases item — exactly the lightweight floor.

    Lightweight thresholds: Test Plan >= 3, Edge Cases >= 1.
    Full thresholds:        Test Plan >= 5, Edge Cases >= 3.
    """

    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Sparse Spec",
                "",
                "## Scope",
                "- Tiny scope item.",
                "",
                "## Non-Goals",
                "- Nothing else.",
                "",
                "## Acceptance",
                "- The change does the thing.",
                "",
                "## Test Plan",
                "- Plan item 1",
                "- Plan item 2",
                "- Plan item 3",
                "",
                "## Edge Cases",
                "- Edge case 1",
            ]
        ),
        encoding="utf-8",
    )


def set_flow_in_task_md(task_md: Path, flow_value: str | None) -> None:
    """Insert/replace `flow: <value>` in task.md frontmatter, or remove it."""

    text = task_md.read_text(encoding="utf-8")
    # Remove any existing flow line.
    text = re.sub(r"^flow:\s*\S+\s*\n", "", text, flags=re.MULTILINE)
    if flow_value is None:
        task_md.write_text(text, encoding="utf-8")
        return
    # Insert flow: <value> immediately after status_history block (before
    # the next frontmatter key). Anchor on the line that starts task_type.
    text = re.sub(
        r"^(task_type:)",
        f"flow: {flow_value}\n\\1",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    task_md.write_text(text, encoding="utf-8")


def advance_to_red(tmp_path: Path, task_dir: Path) -> subprocess.CompletedProcess[str]:
    """Advance draft -> planned -> red. Returns the LAST CLI invocation that
    actually returned a non-zero exit code (so the caller can assert on the
    error message), or the successful red-transition result.

    Important: validation that depends on `flow:` runs at every transition,
    not just `red`. An invalid flow value or a sparse spec on full flow
    will fail at `planned` already; the helper surfaces that first failure
    rather than blindly asserting `planned.returncode == 0`.
    """

    planned = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    if planned.returncode != 0:
        return planned
    return run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "red"],
        cwd=tmp_path,
    )


def test_lightweight_flow_accepts_sparse_spec_via_cli(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="lightweight-task")

    write_sparse_spec(task_dir)
    set_flow_in_task_md(task_dir / "task.md", "lightweight")

    result = advance_to_red(tmp_path, task_dir)

    assert result.returncode == 0, (
        f"lightweight flow with 3 Test Plan + 1 Edge Cases should pass; "
        f"got: {result.stderr}"
    )


def test_full_flow_rejects_sparse_spec_via_cli(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="full-task")

    write_sparse_spec(task_dir)
    set_flow_in_task_md(task_dir / "task.md", "full")

    result = advance_to_red(tmp_path, task_dir)

    assert result.returncode != 0
    assert "Test Plan" in result.stderr
    assert ">= 5" in result.stderr
    # Error message must point at the lightweight escape hatch.
    assert "lightweight" in result.stderr


def test_missing_flow_field_defaults_to_full_and_rejects_sparse_spec(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="default-task")

    write_sparse_spec(task_dir)
    # Explicitly remove the flow field if anything inserted it. Only the
    # frontmatter section (between the leading `---` markers) is checked —
    # the body documents the `flow:` field so a substring search would
    # match the documentation itself.
    set_flow_in_task_md(task_dir / "task.md", None)
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    frontmatter_end = text.find("\n---\n", 4)
    assert frontmatter_end != -1
    frontmatter_block = text[: frontmatter_end + 5]
    assert "flow:" not in frontmatter_block

    result = advance_to_red(tmp_path, task_dir)

    assert result.returncode != 0, "no flow field must default to full and reject sparse spec"
    assert "Test Plan" in result.stderr or "Edge Cases" in result.stderr


def test_invalid_flow_value_raises_clear_error(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="bogus-flow-task")

    write_sparse_spec(task_dir)
    set_flow_in_task_md(task_dir / "task.md", "supercharged")

    result = advance_to_red(tmp_path, task_dir)

    assert result.returncode != 0
    assert "Unknown task flow" in result.stderr
    assert "supercharged" in result.stderr


def test_lightweight_one_below_floor_fails(tmp_path: Path) -> None:
    """Boundary check: lightweight requires Test Plan >= 3 and Edge Cases >= 1.
    Two Test Plan items must fail even on lightweight."""

    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="below-floor")

    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Below Floor",
                "",
                "## Scope", "- one", "",
                "## Non-Goals", "- one", "",
                "## Acceptance", "- one", "",
                "## Test Plan",
                "- only one plan",
                "- only two plans",
                "",
                "## Edge Cases",
                "- one edge case",
            ]
        ),
        encoding="utf-8",
    )
    set_flow_in_task_md(task_dir / "task.md", "lightweight")

    result = advance_to_red(tmp_path, task_dir)

    assert result.returncode != 0
    assert ">= 3" in result.stderr


def test_task_md_template_documents_flow_field(tmp_path: Path) -> None:
    """The body of task.md must guide authors to the flow field. Without this
    discoverability hint, the only way to find `flow:` is to read validation.py.
    """

    bootstrap_sprint(tmp_path)
    task_dir = init_general_task(tmp_path, slug="discoverability-check")

    task_md_text = (task_dir / "task.md").read_text(encoding="utf-8")
    # Hint must mention BOTH the field name and the lightweight value to be
    # actionable. We anchor on the literal substring rather than a precise
    # phrase so future copy edits do not break the test.
    assert "flow" in task_md_text.lower()
    assert "lightweight" in task_md_text
