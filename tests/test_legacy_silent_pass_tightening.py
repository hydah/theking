"""sprint-019 TASK-002: tighten silent-pass for new tasks.

`validate_handoff_evidence_anchors` and `validate_spec` /
`validate_spec_section_counts` each have a silent-pass path that was
designed for backward compatibility with legacy tasks (pre-sprint-011,
pre-sprint-002). For **new** tasks (those carrying the
`theking_schema_version` frontmatter field introduced in sprint-019
TASK-001), those silent-pass paths are disabled: missing handoff =
reject; legacy 2-section spec = reject.

Legacy behavior remains byte-identical.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    validate_handoff_evidence_anchors,
    validate_spec,
    validate_spec_section_counts,
)


SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# unit: validate_handoff_evidence_anchors with task_is_new flag
# ---------------------------------------------------------------------------


def test_new_task_missing_handoff_rejected(tmp_path: Path) -> None:
    """New task + absent handoff.md must raise."""
    handoff = tmp_path / "handoff.md"  # does not exist
    with pytest.raises(WorkflowError, match=r"(?is)handoff"):
        validate_handoff_evidence_anchors(handoff, task_is_new=True)


def test_new_task_empty_handoff_sections_rejected(tmp_path: Path) -> None:
    """New task with target sections containing only HTML comments must raise."""
    handoff = tmp_path / "handoff.md"
    write(
        handoff,
        "# Task Handoff\n\n## Phase 1 Evidence Anchors\n\n"
        "- Viewed code/tests/docs:\n"
        "  <!-- - scripts/example.py:42 -->\n"
        "- Impact surface:\n"
        "  <!-- - scripts/example.py:80 -->\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)handoff"):
        validate_handoff_evidence_anchors(handoff, task_is_new=True)


def test_new_task_with_handoff_anchor_passes(tmp_path: Path) -> None:
    """New task + handoff with real file:line anchor must pass."""
    handoff = tmp_path / "handoff.md"
    write(
        handoff,
        "# Task Handoff\n\n## Phase 1 Evidence Anchors\n\n"
        "- Viewed code/tests/docs:\n"
        "  - scripts/validation.py:1355 handoff gate\n"
        "- Impact surface:\n",
    )
    # Should not raise
    validate_handoff_evidence_anchors(handoff, task_is_new=True)


def test_legacy_task_missing_handoff_still_passes(tmp_path: Path) -> None:
    """Legacy task (task_is_new=False) with absent handoff must pass —
    backward compatibility with pre-sprint-011 tasks."""
    handoff = tmp_path / "handoff.md"  # does not exist
    # Must not raise
    validate_handoff_evidence_anchors(handoff, task_is_new=False)


def test_legacy_task_empty_handoff_still_passes(tmp_path: Path) -> None:
    """Legacy task with empty handoff.md must pass."""
    handoff = tmp_path / "handoff.md"
    write(
        handoff,
        "# Task Handoff\n\n## Phase 1 Evidence Anchors\n\n"
        "- Viewed code/tests/docs:\n"
        "- Impact surface:\n",
    )
    # Must not raise (legacy silent-pass preserved)
    validate_handoff_evidence_anchors(handoff, task_is_new=False)


def test_default_task_is_new_is_false(tmp_path: Path) -> None:
    """The default value of task_is_new must be False so existing
    callers without the kwarg retain legacy behavior."""
    handoff = tmp_path / "handoff.md"  # missing
    # Must not raise — default is legacy
    validate_handoff_evidence_anchors(handoff)


# ---------------------------------------------------------------------------
# unit: validate_spec with task_is_new flag
# ---------------------------------------------------------------------------


LEGACY_SPEC = """# Task Spec

## Acceptance
- [ ] Criterion one
  - 验证方式: unit
  - 证据路径: tests/test_x.py::test_y

## Test Plan
- Unit test a
- Unit test b
- Unit test c
"""


FULL_SPEC = """# Task Spec

## Scope
- Implement feature X.

## Non-Goals
- Nothing else.

## Acceptance
- [ ] Behaviour Y is testable.
  - 验证方式: unit
  - 证据路径: tests/test_x.py::test_y

## Test Plan
- Unit test a.
- Unit test b.
- Unit test c.
- Integration test d.
- Regression e.

## Edge Cases
- Empty input.
- Boundary value.
- Concurrent access.
"""


def test_new_task_with_legacy_spec_rejected(tmp_path: Path) -> None:
    """New task using legacy 2-section spec must be rejected."""
    spec = tmp_path / "spec.md"
    write(spec, LEGACY_SPEC)
    with pytest.raises(WorkflowError, match=r"(?is)(section|spec)"):
        validate_spec(spec, require_content=True, flow="full", task_is_new=True)


def test_legacy_task_with_legacy_spec_still_passes(tmp_path: Path) -> None:
    """Legacy task with legacy 2-section spec must pass — backward compat."""
    spec = tmp_path / "spec.md"
    write(spec, LEGACY_SPEC)
    # Must not raise (legacy silent-pass preserved)
    validate_spec(spec, require_content=True, flow="full", task_is_new=False)


def test_new_task_with_full_spec_passes(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    write(spec, FULL_SPEC)
    validate_spec(spec, require_content=True, flow="full", task_is_new=True)


def test_validate_spec_default_task_is_new_false(tmp_path: Path) -> None:
    """Default task_is_new=False preserves existing behavior."""
    spec = tmp_path / "spec.md"
    write(spec, LEGACY_SPEC)
    # Must not raise — default legacy path
    validate_spec(spec, require_content=True, flow="full")


def test_validate_spec_section_counts_new_task_legacy_spec_rejected(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    write(spec, LEGACY_SPEC)
    with pytest.raises(WorkflowError, match=r"(?is)(section|Scope|Non-Goals|Edge)"):
        validate_spec_section_counts(spec, flow="full", task_is_new=True)


def test_validate_spec_section_counts_legacy_task_legacy_spec_passes(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.md"
    write(spec, LEGACY_SPEC)
    # Must not raise
    validate_spec_section_counts(spec, flow="full", task_is_new=False)


# ---------------------------------------------------------------------------
# error message: identifies task as new
# ---------------------------------------------------------------------------


def test_error_message_names_new_task_context(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff.md"
    with pytest.raises(WorkflowError) as exc:
        validate_handoff_evidence_anchors(handoff, task_is_new=True)
    msg = str(exc.value).lower()
    # Error must explain WHY the rejection fires, naming the new-task context.
    assert "new" in msg or "schema" in msg, (
        f"error must name the new-task context; got: {exc.value}"
    )


# ---------------------------------------------------------------------------
# integration: CLI end-to-end
# ---------------------------------------------------------------------------


def _bootstrap(tmp_path: Path) -> Path:
    run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    r = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", "demo-task",
            "--title", "Demo Task",
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    return (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation"
        / "tasks" / "TASK-001-demo-task"
    )


def _fill_goal_and_full_spec(task_dir: Path) -> None:
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    (task_dir / "spec.md").write_text(FULL_SPEC, encoding="utf-8")


def _strip_schema_version(task_dir: Path) -> None:
    """Simulate a legacy task by removing the sprint-019 frontmatter fields."""
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8")
    content = re.sub(r"^created_at:.*\n", "", content, flags=re.MULTILINE)
    content = re.sub(r"^theking_schema_version:.*\n", "", content, flags=re.MULTILINE)
    task_md.write_text(content, encoding="utf-8")


def test_advance_status_rejects_new_task_with_empty_handoff(tmp_path: Path) -> None:
    """End-to-end: init-task creates a new task (with schema_version);
    leave handoff.md empty but populate Goal + spec; advance-status
    planned->red must be rejected by the tightened gate."""
    task_dir = _bootstrap(tmp_path)
    _fill_goal_and_full_spec(task_dir)

    # Write handoff.md with only HTML comments in target sections — this is
    # exactly what init-sprint-plan's default template produces.
    # (init-task writes it already via render_template, but we overwrite
    # to pin the empty-sections state regardless of template drift.)
    (task_dir / "handoff.md").write_text(
        "# Task Handoff\n\n## Phase 1 Evidence Anchors\n\n"
        "- Viewed code/tests/docs:\n"
        "  <!-- - scripts/example.py:42 -->\n"
        "- Impact surface:\n"
        "  <!-- - scripts/example.py:80 -->\n",
        encoding="utf-8",
    )

    r_planned = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    assert r_planned.returncode == 0, r_planned.stderr
    r_red = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "red"],
        cwd=tmp_path,
    )
    assert r_red.returncode != 0, (
        f"New task with empty handoff should be rejected at planned->red; "
        f"got stdout={r_red.stdout!r} stderr={r_red.stderr!r}"
    )
    assert "handoff" in r_red.stderr.lower(), r_red.stderr


def test_advance_status_accepts_legacy_task_with_empty_handoff(tmp_path: Path) -> None:
    """Mirror of the above with schema_version stripped (simulating
    a legacy task) — must pass planned->red even with empty handoff."""
    task_dir = _bootstrap(tmp_path)
    _fill_goal_and_full_spec(task_dir)
    _strip_schema_version(task_dir)

    # Empty handoff target sections (comment-only)
    (task_dir / "handoff.md").write_text(
        "# Task Handoff\n\n## Phase 1 Evidence Anchors\n\n"
        "- Viewed code/tests/docs:\n"
        "  <!-- example -->\n"
        "- Impact surface:\n"
        "  <!-- example -->\n",
        encoding="utf-8",
    )

    r_planned = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    assert r_planned.returncode == 0, r_planned.stderr
    r_red = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "red"],
        cwd=tmp_path,
    )
    assert r_red.returncode == 0, (
        f"Legacy task with empty handoff must still pass planned->red "
        f"(backward compat); got stdout={r_red.stdout!r} "
        f"stderr={r_red.stderr!r}"
    )
