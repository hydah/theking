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


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_complete_spec(task_dir: Path) -> None:
    write_text(
        task_dir / "spec.md",
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Complete the requested workflow change for this task.",
                "",
                "## Non-Goals",
                "- No unrelated cleanup.",
                "",
                "## Acceptance",
                "- The task can move through review with valid artifacts.",
                "",
                "## Test Plan",
                "- Run the relevant verification for this task.",
                "- Exercise the happy path.",
                "- Exercise the error path.",
                "- Verify idempotency.",
                "- Run the regression suite.",
                "",
                "## Edge Cases",
                "- Repeated transitions keep task state consistent.",
                "- Missing optional inputs do not crash.",
                "- Partial artifacts do not block recovery.",
            ]
        ),
    )


def parse_frontmatter(text: str) -> dict[str, object]:
    lines = text.splitlines()
    assert lines[0].strip() == "---"
    data: dict[str, object] = {}
    current_key: str | None = None

    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if not line.strip():
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*$", line.strip()):
            current_key = line.strip()[:-1]
            data[current_key] = []
            continue
        if line.startswith("  - "):
            assert current_key is not None
            list_value = data.setdefault(current_key, [])
            assert isinstance(list_value, list)
            list_value.append(line.strip()[2:].strip())
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.+)$", line.strip())
        assert match is not None
        key, raw_value = match.groups()
        lowered = raw_value.lower()
        if lowered == "true":
            data[key] = True
        elif lowered == "false":
            data[key] = False
        elif raw_value.isdigit():
            data[key] = int(raw_value)
        else:
            data[key] = raw_value
        current_key = None

    raise AssertionError("frontmatter must be closed")


def set_task_status(task_md: Path, *, status: str, history: list[str], current_review_round: int) -> None:
    content = task_md.read_text(encoding="utf-8")
    history_block = "\n".join(f"  - {entry}" for entry in history)
    content = re.sub(
        r"status: \S+\nstatus_history:\n(?:  - .*\n)+",
        f"status: {status}\nstatus_history:\n{history_block}\n",
        content,
        count=1,
    )
    content = re.sub(r"current_review_round: \d+", f"current_review_round: {current_review_round}", content, count=1)
    task_md.write_text(content, encoding="utf-8")


def advance_task_to_done(task_dir: Path, cwd: Path) -> None:
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


def verification_result_markdown() -> str:
    return "\n".join(
        [
            "# Verification Result",
            "",
            "- Command: uv run --with pytest pytest tests -q",
            "- Outcome: passed",
            "",
        ]
    )


def bootstrap_sprint_with_tasks(tmp_path: Path) -> Path:
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
            {
                "slug": "task-b",
                "title": "Task B",
                "task_type": "general",
                "depends_on": ["task-a"],
            },
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
    sprint_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"
    # sprint-015 TASK-001: draft-exit Goal gate. Populate Goal on every
    # fixture task so tests that advance status past draft do not trip the
    # gate. Tests that specifically want the placeholder (e.g. Goal-gate
    # tests themselves) overwrite this with `_overwrite_goal_section`.
    from conftest import populate_task_goal

    for task_dir in sorted((sprint_dir / "tasks").iterdir()):
        if task_dir.is_dir():
            populate_task_goal(task_dir / "task.md")
    return sprint_dir


def test_sprint_check_passes_valid_sprint(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_sprint_check_detects_missing_dependency_references(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_b_md = sprint_dir / "tasks" / "TASK-002-task-b" / "task.md"
    content = task_b_md.read_text(encoding="utf-8")
    task_b_md.write_text(
        content.replace("TASK-001-task-a", "TASK-099-nonexistent"),
        encoding="utf-8",
    )

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "TASK-099-nonexistent" in result.stderr


def test_sprint_check_detects_cycle(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_a_md = sprint_dir / "tasks" / "TASK-001-task-a" / "task.md"
    content = task_a_md.read_text(encoding="utf-8")
    content = content.replace("depends_on:\n", "depends_on:\n  - TASK-002-task-b\n")
    task_a_md.write_text(content, encoding="utf-8")

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "circular" in result.stderr.lower() or "cycle" in result.stderr.lower()


def test_check_rejects_invalid_review_mode(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    task_md.write_text(
        task_md.read_text(encoding="utf-8").replace(
            "review_mode: light",
            "review_mode: turbo",
        ),
        encoding="utf-8",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "review_mode" in result.stderr
    assert "turbo" in result.stderr


def test_sprint_check_rejects_invalid_review_mode(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_md = sprint_dir / "tasks" / "TASK-001-task-a" / "task.md"
    task_md.write_text(
        task_md.read_text(encoding="utf-8").replace(
            "review_mode: light",
            "review_mode: turbo",
        ),
        encoding="utf-8",
    )

    result = run_cli(["sprint-check", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "review_mode" in result.stderr
    assert "turbo" in result.stderr


def test_sprint_check_fails_when_task_spec_is_missing(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    spec_path = sprint_dir / "tasks" / "TASK-001-task-a" / "spec.md"
    spec_path.unlink()

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "spec.md" in result.stderr


def test_sprint_check_fails_when_ready_to_merge_task_has_no_review_pair(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = sprint_dir / "tasks" / "TASK-001-task-a" / "task.md"
    write_complete_spec(task_dir)
    task_md.write_text(
        task_md.read_text(encoding="utf-8").replace(
            "status: draft\nstatus_history:\n  - draft",
            "status: ready_to_merge\nstatus_history:\n  - draft\n  - planned\n  - red\n  - green\n  - in_review\n  - ready_to_merge",
        ).replace(
            "current_review_round: 0",
            "current_review_round: 1",
        ),
        encoding="utf-8",
    )
    write_text(task_dir / "verification" / "cli" / "result.md", verification_result_markdown())

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "code-review-round-001" in result.stderr


def test_sprint_check_fails_when_ready_to_merge_task_has_no_verification_evidence(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    task_md.write_text(
        task_md.read_text(encoding="utf-8").replace(
            "status: draft\nstatus_history:\n  - draft",
            "status: ready_to_merge\nstatus_history:\n  - draft\n  - planned\n  - red\n  - green\n  - in_review\n  - ready_to_merge",
        ).replace(
            "current_review_round: 0",
            "current_review_round: 1",
        ),
        encoding="utf-8",
    )
    write_text(
        task_dir / "review" / "code-review-round-001.md",
        "# Code Review Round 001\n\n## Context\n- Task: TASK-001-task-a\n\n## Findings\n- Ready to merge.\n",
    )
    write_text(
        task_dir / "review" / "code-review-round-001.resolved.md",
        "# Resolved Code Review Round 001\n\n## Fixes\n- Closed findings.\n\n## Verification\n- uv run --with pytest pytest tests -q\n",
    )

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "substantive evidence" in result.stderr


def test_sprint_check_rejects_non_theking_layout(tmp_path: Path) -> None:
    sprint_dir = tmp_path / "fake-sprint"
    (sprint_dir / "tasks").mkdir(parents=True)
    (sprint_dir / "sprint.md").write_text("# Fake Sprint\n", encoding="utf-8")

    result = run_cli(
        ["sprint-check", "--sprint-dir", str(sprint_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "sprint_dir must live under .theking/workflows" in result.stderr


def test_activate_writes_active_task_file(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    result = run_cli(
        ["activate", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    active_file = project_dir / ".theking" / "active-task"
    assert active_file.is_file()
    assert task_dir.name in active_file.read_text(encoding="utf-8")


def test_activate_rejects_non_task_directory(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    project_dir = tmp_path / "demo-app"
    invalid_dir = sprint_dir / "not-a-task"
    invalid_dir.mkdir()

    result = run_cli(
        ["activate", "--task-dir", str(invalid_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "task_dir must live under .theking/workflows" in result.stderr
    assert not (project_dir / ".theking" / "active-task").exists()


def test_activate_writes_to_project_theking_even_if_task_contains_nested_theking(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    nested_theking = task_dir / ".theking"
    nested_theking.mkdir()

    result = run_cli(
        ["activate", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_active = tmp_path / "demo-app" / ".theking" / "active-task"
    nested_active = nested_theking / "active-task"
    assert project_active.is_file()
    assert task_dir.name in project_active.read_text(encoding="utf-8")
    assert not nested_active.exists()


def test_activate_rejects_symlinked_active_task_file_outside_project(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"
    external_file = tmp_path / "outside-active-task"
    external_file.write_text("untouched\n", encoding="utf-8")
    (project_dir / ".theking" / "active-task").symlink_to(external_file)

    result = run_cli(
        ["activate", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr
    assert external_file.read_text(encoding="utf-8") == "untouched\n"


def test_deactivate_removes_active_task_file(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert (project_dir / ".theking" / "active-task").is_file()
    advance_task_to_done(task_dir, tmp_path)

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert not (project_dir / ".theking" / "active-task").exists()


def test_deactivate_accepts_theking_dir_as_project_dir(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert (project_dir / ".theking" / "active-task").is_file()
    advance_task_to_done(task_dir, tmp_path)

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir / ".theking")],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert not (project_dir / ".theking" / "active-task").exists()


def test_deactivate_rejects_symlinked_theking_dir_passed_to_project_dir(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    external_theking = tmp_path / "external-theking"
    external_theking.mkdir(parents=True)
    (external_theking / "active-task").write_text("/tmp/task\n", encoding="utf-8")
    (project_dir / ".theking").symlink_to(external_theking, target_is_directory=True)

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir / ".theking")],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr
    assert (external_theking / "active-task").read_text(encoding="utf-8") == "/tmp/task\n"


def test_deactivate_is_idempotent(tmp_path: Path) -> None:
    bootstrap_sprint_with_tasks(tmp_path)
    project_dir = tmp_path / "demo-app"

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr


def test_deactivate_refuses_when_active_task_is_not_terminal(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert (project_dir / ".theking" / "active-task").is_file()

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "Refusing to deactivate" in result.stderr
    assert "draft" in result.stderr
    assert "--force" in result.stderr
    assert (project_dir / ".theking" / "active-task").is_file()


def test_deactivate_allows_force_override_for_non_terminal_task(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir), "--force"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert not (project_dir / ".theking" / "active-task").exists()


def test_deactivate_allows_blocked_task_without_force(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    project_dir = tmp_path / "demo-app"

    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    set_task_status(
        task_dir / "task.md",
        status="blocked",
        history=["draft", "planned", "blocked"],
        current_review_round=0,
    )

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert not (project_dir / ".theking" / "active-task").exists()


def test_deactivate_rejects_symlinked_theking_directory_outside_project(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir(parents=True)
    external_theking = tmp_path / "external-theking"
    external_theking.mkdir(parents=True)
    (external_theking / "active-task").write_text("/tmp/task\n", encoding="utf-8")
    (project_dir / ".theking").symlink_to(external_theking, target_is_directory=True)

    result = run_cli(
        ["deactivate", "--project-dir", str(project_dir)],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "stay under" in result.stderr or "symlink" in result.stderr
    assert (external_theking / "active-task").read_text(encoding="utf-8") == "/tmp/task\n"


def test_status_reports_checkpoint_before_task_activation(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    init_result = run_cli(
        ["init-project", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    checkpoint_result = run_cli(
        [
            "checkpoint",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--phase",
            "phase-3-planning",
            "--flow",
            "full",
            "--summary",
            "Fix upload auth flow",
            "--next-step",
            "Create sprint and tasks from planner output",
        ],
        cwd=project_dir,
    )

    result = run_cli(
        ["status", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )

    assert init_result.returncode == 0, init_result.stderr
    assert checkpoint_result.returncode == 0, checkpoint_result.stderr
    assert result.returncode == 0, result.stderr
    assert "Recovery source: decree checkpoint" in result.stdout
    assert "Summary: Fix upload auth flow" in result.stdout
    assert "Phase: phase-3-planning" in result.stdout
    assert "Next step: Create sprint and tasks from planner output" in result.stdout
    assert "No active task found." in result.stdout


def test_status_suggests_latest_unfinished_task_when_no_active_task(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert sprint_dir.is_dir()
    assert result.returncode == 0, result.stderr
    assert "Recovery source: latest unfinished task" in result.stdout
    assert "Latest unfinished task: TASK-001-task-a (draft)" in result.stdout
    assert "Activate this task" in result.stdout
    assert "workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-task-a --to-status planned" in result.stdout


def test_status_prefers_latest_unfinished_task_over_stale_checkpoint(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    checkpoint_result = run_cli(
        [
            "checkpoint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--phase",
            "phase-2-triage",
            "--flow",
            "full",
            "--summary",
            "Old decree summary",
            "--next-step",
            "Create sprint and tasks",
        ],
        cwd=tmp_path,
    )

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert sprint_dir.is_dir()
    assert checkpoint_result.returncode == 0, checkpoint_result.stderr
    assert result.returncode == 0, result.stderr
    assert "Recovery source: latest unfinished task" in result.stdout
    assert "Saved decree checkpoint:" in result.stdout
    assert "Next step: Create sprint and tasks" in result.stdout
    assert result.stdout.index("Latest unfinished task: TASK-001-task-a (draft)") < result.stdout.index("Saved decree checkpoint:")


def test_status_reports_active_task_green_next_step(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="green",
        history=["draft", "planned", "red", "green"],
        current_review_round=0,
    )
    activate_result = run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert activate_result.returncode == 0, activate_result.stderr
    assert result.returncode == 0, result.stderr
    assert "Recovery source: active-task" in result.stdout
    assert "ID: TASK-001-task-a" in result.stdout
    assert "Status: green" in result.stdout
    assert "Current review round: 0" in result.stdout
    assert "workflowctl init-review-round --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-task-a" in result.stdout


def test_status_errors_when_active_task_points_to_missing_directory(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    project_dir = tmp_path / "demo-app"
    (project_dir / ".theking" / "active-task").write_text(str(sprint_dir / "tasks" / "TASK-404-missing") + "\n", encoding="utf-8")

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "run workflowctl activate again" in result.stderr.lower()


def test_status_uses_pre_blocked_stage_for_next_step(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="blocked",
        history=["draft", "planned", "red", "blocked"],
        current_review_round=0,
    )
    activate_result = run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert activate_result.returncode == 0, activate_result.stderr
    assert result.returncode == 0, result.stderr
    assert "Status: blocked" in result.stdout
    assert "workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-task-a --to-status red" in result.stdout


def test_blocked_in_review_can_resume_via_advance_status(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="blocked",
        history=["draft", "planned", "red", "green", "in_review", "blocked"],
        current_review_round=1,
    )

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "in_review"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    assert frontmatter["status"] == "in_review"
    assert frontmatter["current_review_round"] == 1
    assert frontmatter["status_history"] == ["draft", "planned", "red", "green", "in_review", "blocked", "in_review"]


def test_status_blocked_review_task_shows_resume_in_review_command(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="blocked",
        history=["draft", "planned", "red", "green", "in_review", "blocked"],
        current_review_round=1,
    )
    activate_result = run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)

    result = run_cli(
        ["status", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert activate_result.returncode == 0, activate_result.stderr
    assert result.returncode == 0, result.stderr
    assert "Status: blocked" in result.stdout
    assert "workflowctl advance-status --task-dir .theking/workflows/demo-app/sprints/sprint-001-foundation/tasks/TASK-001-task-a --to-status in_review" in result.stdout


def test_advance_status_updates_status_and_history_for_non_review_transition(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter((task_dir / "task.md").read_text(encoding="utf-8"))
    assert frontmatter["status"] == "planned"
    assert frontmatter["status_history"] == ["draft", "planned"]
    assert frontmatter["current_review_round"] == 0
    sprint_text = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert "| TASK-001-task-a | general | backend.cli | \u2014 | \u2014 | planned |" in sprint_text


def test_advance_status_rejects_illegal_transition_without_mutation(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    original_content = task_md.read_text(encoding="utf-8")

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "done"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "illegal status transition" in result.stderr.lower()
    assert task_md.read_text(encoding="utf-8") == original_content


def test_advance_status_rejects_in_review_target_and_keeps_task_unchanged(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="green",
        history=["draft", "planned", "red", "green"],
        current_review_round=0,
    )
    original_content = task_md.read_text(encoding="utf-8")

    result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "in_review"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "init-review-round" in result.stderr
    assert task_md.read_text(encoding="utf-8") == original_content
    assert not (task_dir / "review" / "code-review-round-001.md").exists()


def test_init_review_round_from_green_sets_first_round_and_scaffolds_code_review_file(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="green",
        history=["draft", "planned", "red", "green"],
        current_review_round=0,
    )

    result = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    assert frontmatter["status"] == "in_review"
    assert frontmatter["status_history"] == ["draft", "planned", "red", "green", "in_review"]
    assert frontmatter["current_review_round"] == 1
    review_file = task_dir / "review" / "code-review-round-001.md"
    assert review_file.is_file()
    assert "## Context" in review_file.read_text(encoding="utf-8")
    assert "## Findings" in review_file.read_text(encoding="utf-8")
    sprint_text = (sprint_dir / "sprint.md").read_text(encoding="utf-8")
    assert "| TASK-001-task-a | general | backend.cli | \u2014 | \u2014 | in_review |" in sprint_text


def test_init_review_round_from_green_scaffolds_security_review_when_required(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("task_type: general", "task_type: auth")
    content = content.replace("execution_profile: backend.cli", "execution_profile: backend.http")
    content = content.replace("  - backend.cli", "  - backend.http")
    content = content.replace("requires_security_review: false", "requires_security_review: true")
    content = content.replace("  - code-reviewer", "  - code-reviewer\n  - security-reviewer")
    content = content.replace("review_mode: light", "review_mode: full")
    task_md.write_text(content, encoding="utf-8")
    (task_dir / "verification" / "http").mkdir(parents=True, exist_ok=True)
    set_task_status(
        task_md,
        status="green",
        history=["draft", "planned", "red", "green"],
        current_review_round=0,
    )

    result = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (task_dir / "review" / "code-review-round-001.md").is_file()
    assert (task_dir / "review" / "security-review-round-001.md").is_file()


def test_init_review_round_from_green_scaffolds_e2e_review_when_required(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("task_type: general", "task_type: frontend")
    content = content.replace("execution_profile: backend.cli", "execution_profile: web.browser")
    content = content.replace("  - backend.cli", "  - web.browser")
    content = content.replace("  - code-reviewer", "  - code-reviewer\n  - e2e-runner")
    task_md.write_text(content, encoding="utf-8")
    (task_dir / "verification" / "browser").mkdir(parents=True, exist_ok=True)
    set_task_status(
        task_md,
        status="green",
        history=["draft", "planned", "red", "green"],
        current_review_round=0,
    )

    result = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (task_dir / "review" / "code-review-round-001.md").is_file()
    assert (task_dir / "review" / "e2e-review-round-001.md").is_file()


def test_init_review_round_from_changes_requested_increments_round(tmp_path: Path) -> None:
    sprint_dir = bootstrap_sprint_with_tasks(tmp_path)
    task_dir = sprint_dir / "tasks" / "TASK-001-task-a"
    task_md = task_dir / "task.md"
    write_complete_spec(task_dir)
    set_task_status(
        task_md,
        status="changes_requested",
        history=["draft", "planned", "red", "green", "in_review", "changes_requested"],
        current_review_round=1,
    )
    write_text(
        task_dir / "review" / "code-review-round-001.md",
        "# Code Review Round 001\n\n## Context\n- Task: TASK-001-task-a\n\n## Findings\n- Needs changes.\n",
    )
    write_text(
        task_dir / "review" / "code-review-round-001.resolved.md",
        "# Resolved Code Review Round 001\n\n## Fixes\n- Closed round 001 findings.\n\n## Verification\n- uv run --with pytest pytest tests -q\n",
    )

    result = run_cli(
        ["init-review-round", "--task-dir", str(task_dir)],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    assert frontmatter["status"] == "in_review"
    assert frontmatter["current_review_round"] == 2
    assert frontmatter["status_history"] == [
        "draft",
        "planned",
        "red",
        "green",
        "in_review",
        "changes_requested",
        "in_review",
    ]
    assert (task_dir / "review" / "code-review-round-002.md").is_file()
