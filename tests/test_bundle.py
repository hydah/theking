"""I-012 Task Bundle: end-to-end tests for bundle declaration, validation,
frontmatter round-trip, and sprint-level consistency checking.

Follows the same CLI-based e2e pattern as test_init_sprint_plan.py and
test_task_flow_e2e.py.
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


def bootstrap_sprint(tmp_path: Path) -> None:
    r1 = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    r2 = run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr


def write_plan(tmp_path: Path, plan: dict) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    return plan_file


def run_init_sprint_plan(tmp_path: Path, plan: dict) -> subprocess.CompletedProcess[str]:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(tmp_path, plan)
    return run_cli(
        [
            "init-sprint-plan",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--plan-file", str(plan_file),
        ],
        cwd=tmp_path,
    )


def tasks_dir(tmp_path: Path) -> Path:
    return workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks"


# --- Helper: two-task plan with bundle ---

TWO_TASK_BUNDLE_PLAN = {
    "tasks": [
        {"slug": "core-layer", "title": "Core Layer", "task_type": "general"},
        {
            "slug": "streaming",
            "title": "Streaming Session",
            "task_type": "general",
            "depends_on": ["core-layer"],
        },
        {"slug": "independent", "title": "Independent Task", "task_type": "general"},
    ],
    "bundles": [
        {
            "slug": "core-streaming",
            "tasks": ["core-layer", "streaming"],
            "justification": "streaming is core's only caller; split validation meaningless",
        }
    ],
}


# ============================================================
# Happy path
# ============================================================


def test_init_sprint_plan_creates_bundled_tasks_with_bundle_field(tmp_path: Path) -> None:
    result = run_init_sprint_plan(tmp_path, TWO_TASK_BUNDLE_PLAN)
    assert result.returncode == 0, result.stderr

    td = tasks_dir(tmp_path)
    core_text = (td / "TASK-001-core-layer" / "task.md").read_text(encoding="utf-8")
    stream_text = (td / "TASK-002-streaming" / "task.md").read_text(encoding="utf-8")
    indep_text = (td / "TASK-003-independent" / "task.md").read_text(encoding="utf-8")

    assert "bundle: core-streaming" in core_text
    assert "bundle: core-streaming" in stream_text
    assert "bundle" not in indep_text.lower().replace("bundle_block", "")


def test_init_sprint_plan_bundle_three_tasks(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
            {"slug": "c", "title": "C", "task_type": "general", "depends_on": ["b"]},
        ],
        "bundles": [
            {"slug": "abc", "tasks": ["a", "b", "c"], "justification": "tight coupling"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode == 0, result.stderr

    td = tasks_dir(tmp_path)
    for slug in ("TASK-001-a", "TASK-002-b", "TASK-003-c"):
        text = (td / slug / "task.md").read_text(encoding="utf-8")
        assert "bundle: abc" in text


def test_bundles_array_is_optional(tmp_path: Path) -> None:
    plan = {"tasks": [{"slug": "task-a", "title": "A", "task_type": "general"}]}
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode == 0, result.stderr


def test_empty_bundles_array_is_valid(tmp_path: Path) -> None:
    plan = {
        "tasks": [{"slug": "task-a", "title": "A", "task_type": "general"}],
        "bundles": [],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode == 0, result.stderr


def test_bundled_task_passes_check(tmp_path: Path) -> None:
    result = run_init_sprint_plan(tmp_path, TWO_TASK_BUNDLE_PLAN)
    assert result.returncode == 0, result.stderr

    task_dir = tasks_dir(tmp_path) / "TASK-001-core-layer"
    # Activate + write minimal spec + advance to planned
    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    spec = task_dir / "spec.md"
    spec.write_text(
        "# Core Layer Spec\n\n"
        "## Scope\n- Core recognizer factory\n\n"
        "## Non-Goals\n- No handler changes\n\n"
        "## Acceptance\n"
        "- [ ] NewRecognizer returns valid recognizer\n"
        "  - 验证方式: unit\n"
        "  - 证据路径: tests/test_recognizer.go::TestNew\n\n"
        "## Test Plan\n- Unit a\n- Unit b\n- Unit c\n- Unit d\n- Unit e\n\n"
        "## Edge Cases\n- Empty provider\n- Unknown suffix\n- Nil context\n",
        encoding="utf-8",
    )
    adv = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"], cwd=tmp_path)
    assert adv.returncode == 0, adv.stderr

    check = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert check.returncode == 0, check.stderr


def test_bundled_task_advance_status_preserves_bundle_field(tmp_path: Path) -> None:
    """Bundle field must survive every status transition (serialize round-trip)."""
    result = run_init_sprint_plan(tmp_path, TWO_TASK_BUNDLE_PLAN)
    assert result.returncode == 0, result.stderr

    task_dir = tasks_dir(tmp_path) / "TASK-001-core-layer"
    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    # Write full spec to pass content gate
    spec = task_dir / "spec.md"
    spec.write_text(
        "# Core Layer Spec\n\n"
        "## Scope\n- Core recognizer factory\n\n"
        "## Non-Goals\n- No handler changes\n\n"
        "## Acceptance\n"
        "- [ ] NewRecognizer works\n"
        "  - 验证方式: unit\n"
        "  - 证据路径: tests/test.go::TestNew\n\n"
        "## Test Plan\n- a\n- b\n- c\n- d\n- e\n\n"
        "## Edge Cases\n- x\n- y\n- z\n",
        encoding="utf-8",
    )

    # advance draft → planned
    run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"], cwd=tmp_path)
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "bundle: core-streaming" in text, "bundle lost after planned"

    # advance planned → red
    run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "red"], cwd=tmp_path)
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "bundle: core-streaming" in text, "bundle lost after red"

    # advance red → green
    run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "green"], cwd=tmp_path)
    text = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "bundle: core-streaming" in text, "bundle lost after green"


def test_sprint_overview_includes_bundle_column(tmp_path: Path) -> None:
    result = run_init_sprint_plan(tmp_path, TWO_TASK_BUNDLE_PLAN)
    assert result.returncode == 0, result.stderr

    sprint_md = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "sprint.md"
    sprint_text = sprint_md.read_text(encoding="utf-8")
    assert "| Bundle |" in sprint_text or "Bundle" in sprint_text
    assert "core-streaming" in sprint_text


# ============================================================
# Validation / error tests
# ============================================================


def test_bundle_rejects_four_tasks(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
            {"slug": "c", "title": "C", "task_type": "general", "depends_on": ["b"]},
            {"slug": "d", "title": "D", "task_type": "general", "depends_on": ["c"]},
        ],
        "bundles": [
            {"slug": "too-big", "tasks": ["a", "b", "c", "d"], "justification": "nope"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "3" in result.stderr or "maximum" in result.stderr.lower() or "at most" in result.stderr.lower()


def test_bundle_rejects_single_task(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "lonely", "title": "Lonely", "task_type": "general"},
        ],
        "bundles": [
            {"slug": "too-small", "tasks": ["lonely"], "justification": "nope"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "2" in result.stderr or "at least" in result.stderr.lower()


def test_bundle_rejects_unknown_task_slug(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
        ],
        "bundles": [
            {"slug": "bad-ref", "tasks": ["a", "nonexistent"], "justification": "test"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "not found" in result.stderr.lower()


def test_bundle_rejects_missing_justification(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
        ],
        "bundles": [
            {"slug": "no-why", "tasks": ["a", "b"], "justification": ""},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "justification" in result.stderr.lower()


def test_bundle_rejects_missing_depends_on(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general"},
        ],
        "bundles": [
            {"slug": "no-dep", "tasks": ["a", "b"], "justification": "coupling"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "depends_on" in result.stderr.lower() or "relationship" in result.stderr.lower()


def test_bundle_rejects_overlapping_tasks(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
            {"slug": "c", "title": "C", "task_type": "general", "depends_on": ["a"]},
        ],
        "bundles": [
            {"slug": "bundle1", "tasks": ["a", "b"], "justification": "test"},
            {"slug": "bundle2", "tasks": ["a", "c"], "justification": "test"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "already" in result.stderr.lower()


def test_bundle_rejects_duplicate_bundle_slugs(tmp_path: Path) -> None:
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general", "depends_on": ["a"]},
            {"slug": "c", "title": "C", "task_type": "general"},
            {"slug": "d", "title": "D", "task_type": "general", "depends_on": ["c"]},
        ],
        "bundles": [
            {"slug": "same-name", "tasks": ["a", "b"], "justification": "test"},
            {"slug": "same-name", "tasks": ["c", "d"], "justification": "test"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower()


def test_bundle_rejects_non_list_bundles(tmp_path: Path) -> None:
    plan = {
        "tasks": [{"slug": "a", "title": "A", "task_type": "general"}],
        "bundles": "not-a-list",
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert "array" in result.stderr.lower() or "list" in result.stderr.lower()


def test_bundle_error_does_not_leave_partial_tasks(tmp_path: Path) -> None:
    """When bundle validation fails, no task directories should be created."""
    plan = {
        "tasks": [
            {"slug": "a", "title": "A", "task_type": "general"},
            {"slug": "b", "title": "B", "task_type": "general"},
        ],
        "bundles": [
            # No depends_on between a and b → fails
            {"slug": "bad", "tasks": ["a", "b"], "justification": "test"},
        ],
    }
    result = run_init_sprint_plan(tmp_path, plan)
    assert result.returncode != 0

    td = tasks_dir(tmp_path)
    if td.exists():
        task_dirs = [d for d in td.iterdir() if d.is_dir() and d.name.startswith("TASK-")]
        assert len(task_dirs) == 0, f"Found leftover task dirs: {task_dirs}"


# ============================================================
# Sprint-level validation
# ============================================================


def _create_tasks_manually(sprint_dir: Path, task_specs: list[dict]) -> None:
    """Manually create task directories with specific frontmatter for sprint-check tests."""
    tasks_dir = sprint_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for spec in task_specs:
        task_dir = tasks_dir / spec["id"]
        task_dir.mkdir(exist_ok=True)
        (task_dir / "review").mkdir(exist_ok=True)
        profile_dir = "cli"  # default
        (task_dir / "verification" / profile_dir).mkdir(parents=True, exist_ok=True)

        bundle_line = f"bundle: {spec['bundle']}\n" if spec.get("bundle") else ""
        (task_dir / "task.md").write_text(
            f"---\n"
            f"id: {spec['id']}\n"
            f"title: Test Task\n"
            f"status: draft\n"
            f"status_history:\n  - draft\n"
            f"task_type: general\n"
            f"execution_profile: backend.cli\n"
            f"verification_profile:\n  - backend.cli\n"
            f"requires_security_review: false\n"
            f"required_agents:\n  - planner\n  - tdd-guide\n  - code-reviewer\n"
            f"depends_on:\n\n"
            f"{bundle_line}"
            f"current_review_round: 0\n"
            f"---\n",
            encoding="utf-8",
        )
        (task_dir / "spec.md").write_text(
            "# Spec\n## Scope\n- x\n## Non-Goals\n- y\n## Acceptance\n- [ ] z\n"
            "## Test Plan\n- t\n## Edge Cases\n- e\n",
            encoding="utf-8",
        )


def test_sprint_check_rejects_single_task_bundle(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    sprint_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"
    _create_tasks_manually(sprint_dir, [
        {"id": "TASK-001-lonely", "bundle": "orphan-bundle"},
    ])
    result = run_cli(["sprint-check", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert result.returncode != 0
    assert "orphan-bundle" in result.stderr or "1 task" in result.stderr.lower()


def test_sprint_check_rejects_oversized_bundle(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    sprint_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"
    _create_tasks_manually(sprint_dir, [
        {"id": "TASK-001-a", "bundle": "too-big"},
        {"id": "TASK-002-b", "bundle": "too-big"},
        {"id": "TASK-003-c", "bundle": "too-big"},
        {"id": "TASK-004-d", "bundle": "too-big"},
    ])
    result = run_cli(["sprint-check", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)
    assert result.returncode != 0
    assert "too-big" in result.stderr or "4 task" in result.stderr.lower()
