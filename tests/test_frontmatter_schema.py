"""sprint-019 TASK-001: task.md frontmatter `created_at` + `theking_schema_version`.

Two new optional frontmatter fields let downstream gates distinguish
"tasks created inside this governance regime" (strict rules apply)
from "legacy tasks from before the regime existed" (silent-pass for
backward compatibility). The discriminator is `theking_schema_version`:
its presence means the task was created by a post-sprint-019 workflowctl.

This module pins:
  - init-task / init-sprint-plan inject both fields at creation time
  - `is_new_theking_task(task_data)` returns True iff schema_version is set
  - validate_task_metadata accepts legacy (absent) and new (populated)
    task frontmatter; rejects malformed values
  - `TASK_SCHEMA_VERSION` constant exists and equals 1
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
    is_new_theking_task,
    validate_task_metadata,
)

import constants  # noqa: E402


SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _bootstrap(tmp_path: Path) -> None:
    r1 = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    assert r1.returncode == 0, r1.stderr
    r2 = run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    assert r2.returncode == 0, r2.stderr


def _read_task_md(task_dir: Path) -> str:
    return (task_dir / "task.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# TASK_SCHEMA_VERSION constant
# ---------------------------------------------------------------------------


def test_task_schema_version_constant() -> None:
    """Constant must exist and be a positive integer equal to 1 at sprint-019
    landing. Future bumps require an ADR + migration strategy."""
    assert hasattr(constants, "TASK_SCHEMA_VERSION")
    assert isinstance(constants.TASK_SCHEMA_VERSION, int)
    assert constants.TASK_SCHEMA_VERSION == 1


# ---------------------------------------------------------------------------
# is_new_theking_task discriminator
# ---------------------------------------------------------------------------


def test_is_new_theking_task_returns_true_when_schema_version_set() -> None:
    assert is_new_theking_task({"theking_schema_version": 1}) is True


def test_is_new_theking_task_returns_true_for_future_version() -> None:
    """Forward-compat: a task from a newer theking version is still 'new'."""
    assert is_new_theking_task({"theking_schema_version": 99}) is True


def test_is_new_theking_task_returns_false_when_field_absent() -> None:
    assert is_new_theking_task({}) is False


def test_is_new_theking_task_returns_false_when_field_explicit_none() -> None:
    assert is_new_theking_task({"theking_schema_version": None}) is False


# ---------------------------------------------------------------------------
# validate_task_metadata — accept legacy + accept new + reject malformed
# ---------------------------------------------------------------------------


def _minimal_valid_task_data() -> dict:
    """Frontmatter dict that passes validate_task_metadata without the
    two new optional fields. Mirrors what `init-task` used to write
    before sprint-019."""
    return {
        "id": "TASK-001-demo",
        "title": "Demo",
        "status": "draft",
        "status_history": ["draft"],
        "task_type": "general",
        "execution_profile": "backend.cli",
        "verification_profile": ["backend.cli"],
        "requires_security_review": False,
        "required_agents": ["tdd-guide", "code-reviewer"],
        "depends_on": [],
        "current_review_round": 0,
        "review_mode": "light",
    }


def test_validate_task_metadata_accepts_legacy_task() -> None:
    """Legacy tasks (no new fields) must keep passing — backward compat."""
    data = _minimal_valid_task_data()
    result = validate_task_metadata(data)
    assert "theking_schema_version" not in result or result.get("theking_schema_version") is None


def test_validate_task_metadata_accepts_new_task() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 1
    data["created_at"] = "2026-05-02T22:30:00Z"
    result = validate_task_metadata(data)
    assert result["theking_schema_version"] == 1
    assert result["created_at"] == "2026-05-02T22:30:00Z"


def test_validate_task_metadata_rejects_schema_version_string() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = "v1"
    with pytest.raises(WorkflowError, match=r"(?is)theking_schema_version"):
        validate_task_metadata(data)


def test_validate_task_metadata_rejects_schema_version_zero() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 0
    with pytest.raises(WorkflowError, match=r"(?is)theking_schema_version"):
        validate_task_metadata(data)


def test_validate_task_metadata_rejects_schema_version_negative() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = -1
    with pytest.raises(WorkflowError, match=r"(?is)theking_schema_version"):
        validate_task_metadata(data)


def test_validate_task_metadata_rejects_created_at_without_timezone() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 1
    data["created_at"] = "2026-05-02T22:30:00"  # no Z, no offset
    with pytest.raises(WorkflowError, match=r"(?is)created_at"):
        validate_task_metadata(data)


def test_validate_task_metadata_rejects_created_at_empty() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 1
    data["created_at"] = ""
    with pytest.raises(WorkflowError, match=r"(?is)created_at"):
        validate_task_metadata(data)


def test_validate_task_metadata_rejects_created_at_non_iso() -> None:
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 1
    data["created_at"] = "yesterday at noon"
    with pytest.raises(WorkflowError, match=r"(?is)created_at"):
        validate_task_metadata(data)


def test_validate_task_metadata_accepts_created_at_with_plus_zero() -> None:
    """+00:00 offset is equivalent to Z per ISO8601."""
    data = _minimal_valid_task_data()
    data["theking_schema_version"] = 1
    data["created_at"] = "2026-05-02T22:30:00+00:00"
    result = validate_task_metadata(data)
    assert result["created_at"] == "2026-05-02T22:30:00+00:00"


# ---------------------------------------------------------------------------
# init-task integration — schema fields are injected
# ---------------------------------------------------------------------------


def test_init_task_injects_schema_fields(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    r = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", "schema-check",
            "--title", "Schema Check",
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    task_dir = (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation"
        / "tasks" / "TASK-001-schema-check"
    )
    content = _read_task_md(task_dir)
    assert re.search(r"^theking_schema_version:\s*1\s*$", content, re.MULTILINE), (
        f"task.md must include theking_schema_version: 1\n{content}"
    )
    m = re.search(r"^created_at:\s*(\S+)\s*$", content, re.MULTILINE)
    assert m is not None, f"task.md must include created_at field\n{content}"
    # created_at must be ISO8601Z (UTC)
    created_at = m.group(1)
    assert created_at.endswith("Z") or "+00:00" in created_at, (
        f"created_at must be UTC ISO8601 (Z or +00:00 suffix): {created_at!r}"
    )


# ---------------------------------------------------------------------------
# init-sprint-plan integration — all tasks get schema fields, shared second
# ---------------------------------------------------------------------------


def test_init_sprint_plan_injects_schema_fields_for_all_tasks(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general"},
            {"slug": "c", "title": "C", "task_type": "general"},
        ]
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")

    r = run_cli(
        [
            "init-sprint-plan",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--plan-file", str(plan_file),
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr

    tasks_dir = (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation" / "tasks"
    )
    created_ats: list[str] = []
    for task_name in ("TASK-001-a", "TASK-002-b", "TASK-003-c"):
        content = _read_task_md(tasks_dir / task_name)
        assert re.search(r"^theking_schema_version:\s*1\s*$", content, re.MULTILINE), (
            f"{task_name}/task.md must include theking_schema_version: 1"
        )
        m = re.search(r"^created_at:\s*(\S+)\s*$", content, re.MULTILINE)
        assert m is not None, f"{task_name}/task.md must include created_at"
        created_ats.append(m.group(1))

    # All tasks in one CLI invocation share the same created_at timestamp
    # (second precision) — essential for audit to reconstruct the sprint
    # initialization event as a single atomic unit.
    assert len(set(created_ats)) == 1, (
        f"all tasks in one init-sprint-plan must share created_at; "
        f"got {created_ats}"
    )


# ---------------------------------------------------------------------------
# round-trip: status transitions must preserve schema fields
# ---------------------------------------------------------------------------


def test_schema_fields_survive_advance_status(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    r = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", "round-trip",
            "--title", "Round Trip",
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert r.returncode == 0, r.stderr
    task_dir = (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation"
        / "tasks" / "TASK-001-round-trip"
    )

    # Fill Goal + spec enough to clear planned transition gates.
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    spec_body = (
        "# Round Trip Spec\n\n"
        "## Scope\n- Check fields survive.\n\n"
        "## Non-Goals\n- Nothing else.\n\n"
        "## Acceptance\n"
        "- [ ] Fields survive.\n"
        "  - 验证方式: unit\n"
        "  - 证据路径: tests/test_frontmatter_schema.py::test_schema_fields_survive_advance_status\n\n"
        "## Test Plan\n- a\n- b\n- c\n- d\n- e\n\n"
        "## Edge Cases\n- x\n- y\n- z\n"
    )
    (task_dir / "spec.md").write_text(spec_body, encoding="utf-8")

    r_planned = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    assert r_planned.returncode == 0, r_planned.stderr

    content = _read_task_md(task_dir)
    assert "theking_schema_version: 1" in content, (
        "schema_version must survive planned transition"
    )
    assert re.search(r"^created_at:", content, re.MULTILINE), (
        "created_at must survive planned transition"
    )
