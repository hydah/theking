from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validation import parse_frontmatter  # noqa: E402


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
    assert init_project.returncode == 0, init_project.stderr
    assert init_sprint.returncode == 0, init_sprint.stderr


def write_plan(tmp_path: Path, plan: dict) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    return plan_file


def test_init_sprint_plan_creates_all_tasks_with_dependencies(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "auth-setup",
                "title": "Auth Setup",
                "task_type": "auth",
                "execution_profile": "backend.http",
                "depends_on": [],
            },
            {
                "slug": "oauth-provider",
                "title": "OAuth Provider",
                "task_type": "auth",
                "execution_profile": "backend.http",
                "depends_on": ["auth-setup"],
            },
            {
                "slug": "login-ui",
                "title": "Login UI",
                "task_type": "frontend",
                "execution_profile": "web.browser",
                "depends_on": ["auth-setup"],
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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

    assert result.returncode == 0, result.stderr
    tasks_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
    )
    assert (tasks_dir / "TASK-001-auth-setup" / "task.md").is_file()
    assert (tasks_dir / "TASK-002-oauth-provider" / "task.md").is_file()
    assert (tasks_dir / "TASK-003-login-ui" / "task.md").is_file()

    oauth_task = (tasks_dir / "TASK-002-oauth-provider" / "task.md").read_text(encoding="utf-8")
    assert "TASK-001-auth-setup" in oauth_task

    login_task = (tasks_dir / "TASK-003-login-ui" / "task.md").read_text(encoding="utf-8")
    assert "TASK-001-auth-setup" in login_task

    auth_task = (tasks_dir / "TASK-001-auth-setup" / "task.md").read_text(encoding="utf-8")
    assert "depends_on:" in auth_task


def test_init_sprint_plan_omits_planner_from_required_agents(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {"tasks": [{"slug": "cli-task", "title": "CLI Task", "task_type": "general"}]},
    )

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

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-cli-task"
        / "task.md"
    )
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    assert frontmatter["required_agents"] == ["tdd-guide", "code-reviewer"]


def test_init_sprint_plan_creates_handoff_artifacts(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
            {"slug": "task-b", "title": "Task B", "task_type": "frontend"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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

    assert result.returncode == 0, result.stderr
    tasks_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks"
    for task_name in ("TASK-001-task-a", "TASK-002-task-b"):
        handoff_md = tasks_dir / task_name / "handoff.md"
        assert handoff_md.is_file(), f"{task_name} should include handoff.md"
        handoff_text = handoff_md.read_text(encoding="utf-8")
        assert "Phase 1" in handoff_text or "handoff" in handoff_text.lower()


def test_init_sprint_plan_creates_agent_run_ledger_artifacts(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
            {"slug": "task-b", "title": "Task B", "task_type": "auth"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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

    assert result.returncode == 0, result.stderr
    tasks_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks"
    for task_name in ("TASK-001-task-a", "TASK-002-task-b"):
        ledger = tasks_dir / task_name / "agent-runs.jsonl"
        assert ledger.is_file(), f"{task_name} should include agent-runs.jsonl"
        assert ledger.read_text(encoding="utf-8") == ""


def test_init_sprint_plan_accepts_project_root_as_project_dir(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    project_dir = tmp_path / "demo-app"
    plan = {
        "tasks": [
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

    result = run_cli(
        [
            "init-sprint-plan",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert (
        project_dir
        / ".theking"
        / "workflows"
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-task-a"
        / "task.md"
    ).is_file()


def test_init_sprint_plan_rejects_circular_dependencies(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "task-a",
                "title": "Task A",
                "task_type": "general",
                "depends_on": ["task-b"],
            },
            {
                "slug": "task-b",
                "title": "Task B",
                "task_type": "general",
                "depends_on": ["task-a"],
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    assert "circular" in result.stderr.lower() or "cycle" in result.stderr.lower()


def test_init_sprint_plan_rejects_unknown_dependency(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "task-a",
                "title": "Task A",
                "task_type": "general",
                "depends_on": ["nonexistent"],
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    assert "unknown" in result.stderr.lower()


def test_init_sprint_plan_rejects_duplicate_slugs(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "same-slug", "title": "First", "task_type": "general"},
            {"slug": "same-slug", "title": "Second", "task_type": "general"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    assert "duplicate" in result.stderr.lower()


def test_init_sprint_plan_rejects_invalid_json_plan_file(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = tmp_path / "broken-plan.json"
    plan_file.write_text("{invalid json}\n", encoding="utf-8")

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
    assert "valid json" in result.stderr.lower()


def test_init_sprint_plan_rejects_non_string_task_fields(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {
                "slug": "task-a",
                "title": 123,
                "task_type": "general",
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    assert "must be a string" in result.stderr


def test_init_sprint_plan_rejects_symlinked_sprint_directory(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    sprints_dir = workflow_root(tmp_path) / "sprints"
    sprint_dir = sprints_dir / "sprint-001-foundation"
    redirected_dir = sprints_dir / "redirected-sprint"
    sprint_dir.rename(redirected_dir)
    sprint_dir.symlink_to("redirected-sprint", target_is_directory=True)

    plan = {
        "tasks": [
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    assert "symlink" in result.stderr or "stay under" in result.stderr



def test_init_sprint_plan_updates_sprint_overview(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "task-a", "title": "Task A", "task_type": "general"},
            {
                "slug": "task-b",
                "title": "Task B",
                "task_type": "auth",
                "execution_profile": "backend.http",
                "depends_on": ["task-a"],
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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

    assert result.returncode == 0, result.stderr
    sprint_md = (
        workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "sprint.md"
    )
    sprint_text = sprint_md.read_text(encoding="utf-8")
    assert "## Task Overview" in sprint_text
    assert "TASK-001-task-a" in sprint_text
    assert "TASK-002-task-b" in sprint_text


def test_init_sprint_plan_infers_execution_profile(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "web-task", "title": "Web Task", "task_type": "frontend"},
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-web-task"
        / "task.md"
    )
    task_text = task_md.read_text(encoding="utf-8")
    assert "execution_profile: web.browser" in task_text
    assert "e2e-runner" in task_text


def test_init_sprint_plan_does_not_leave_partial_tasks_on_validation_error(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan = {
        "tasks": [
            {"slug": "good-task", "title": "Good Task", "task_type": "general"},
            {
                "slug": "bad-task",
                "title": "Bad Task",
                "task_type": "general",
                "execution_profile": "backend.http",
            },
        ],
    }
    plan_file = write_plan(tmp_path, plan)

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
    tasks_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
    )
    assert sorted(child.name for child in tasks_dir.iterdir()) == []


def test_init_sprint_plan_preserves_existing_task_overview_rows(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    first_plan_file = write_plan(
        tmp_path,
        {"tasks": [{"slug": "task-a", "title": "Task A", "task_type": "general"}]},
    )

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
            str(first_plan_file),
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    second_plan_file = tmp_path / "plan-second.json"
    second_plan_file.write_text(
        json.dumps({"tasks": [{"slug": "task-b", "title": "Task B", "task_type": "general"}]}),
        encoding="utf-8",
    )
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
            str(second_plan_file),
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    sprint_text = (
        workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "sprint.md"
    ).read_text(encoding="utf-8")
    assert "TASK-001-task-a" in sprint_text
    assert "TASK-002-task-b" in sprint_text


def test_init_sprint_plan_prints_next_step_prompt(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {"slug": "task-a", "title": "Task A", "task_type": "general"},
                {"slug": "task-b", "title": "Task B", "task_type": "general"},
            ]
        },
    )

    result = run_cli(
        [
            "init-sprint-plan",
            "--project-dir",
            str(tmp_path / "demo-app"),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "Created 2 task(s) in 'draft'" in result.stdout
    assert "workflowctl activate --task-dir" in result.stdout
    assert "TASK-001-task-a" in result.stdout
    assert "--to-status planned" in result.stdout


def test_init_sprint_plan_writes_decree_checkpoint(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {"tasks": [{"slug": "task-a", "title": "Task A", "task_type": "general"}]},
    )

    result = run_cli(
        [
            "init-sprint-plan",
            "--project-dir",
            str(tmp_path / "demo-app"),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    checkpoint = tmp_path / "demo-app" / ".theking" / "state" / "session" / "decree-session.md"
    assert checkpoint.is_file(), "decree-session.md should be auto-written"
    content = checkpoint.read_text(encoding="utf-8")
    assert 'phase: "phase-3-planning"' in content
    assert 'sprint: "sprint-001-foundation"' in content
    assert 'task: "TASK-001-task-a"' in content


def test_init_sprint_plan_seeds_spec_from_hint_fields(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "task-a",
                    "title": "Task A",
                    "task_type": "general",
                    "scope": ["Do thing X in file Y"],
                    "non_goals": ["Do not refactor Z"],
                    "acceptance": ["`go build ./...` passes", "No AKID strings remain"],
                    "edge_cases": ["Empty env var should stay empty"],
                    "spec_hints": {
                        "code_patterns": ["Follow scripts/workflowctl.py handle_init_task"],
                        "test_helpers": ["Reuse run_cli helper"],
                        "related_tasks": ["TASK-000-docs"],
                    },
                }
            ]
        },
    )

    result = run_cli(
        [
            "init-sprint-plan",
            "--project-dir",
            str(tmp_path / "demo-app"),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    spec_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-task-a"
        / "spec.md"
    )
    content = spec_md.read_text(encoding="utf-8")
    assert "- Do thing X in file Y" in content
    assert "- Do not refactor Z" in content
    assert "- [ ] `go build ./...` passes" in content
    assert "- [ ] No AKID strings remain" in content
    assert "- Empty env var should stay empty" in content
    assert "## Implementation Hints" in content
    assert "Follow scripts/workflowctl.py handle_init_task" in content
    assert "Reuse run_cli helper" in content
    assert "TASK-000-docs" in content


def test_init_sprint_plan_infers_and_normalizes_review_mode(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {"slug": "general-task", "title": "General Task", "task_type": "general"},
                {"slug": "auth-task", "title": "Auth Task", "task_type": "auth"},
                {"slug": "api-task", "title": "API Task", "task_type": "api"},
                {"slug": "e2e-task", "title": "E2E Task", "task_type": "e2e"},
                {
                    "slug": "forced-full",
                    "title": "Forced Full",
                    "task_type": "general",
                    "review_mode": "FULL",
                },
                {
                    "slug": "forced-light",
                    "title": "Forced Light",
                    "task_type": "general",
                    "review_mode": "LiGhT",
                },
            ]
        },
    )

    result = run_cli(
        [
            "init-sprint-plan",
            "--project-dir",
            str(tmp_path / "demo-app"),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    tasks_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks"
    expected = {
        "TASK-001-general-task": "review_mode: light",
        "TASK-002-auth-task": "review_mode: full",
        "TASK-003-api-task": "review_mode: full",
        "TASK-004-e2e-task": "review_mode: full",
        "TASK-005-forced-full": "review_mode: full",
        "TASK-006-forced-light": "review_mode: light",
    }

    for task_name, expected_line in expected.items():
        task_text = (tasks_dir / task_name / "task.md").read_text(encoding="utf-8")
        assert expected_line in task_text


def test_init_sprint_plan_rejects_non_list_spec_hint(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "task-a",
                    "title": "Task A",
                    "task_type": "general",
                    "scope": "not a list",
                }
            ]
        },
    )

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
    assert "must be a list of strings" in result.stderr


def test_init_sprint_plan_rejects_non_string_nested_spec_hint_item(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "task-a",
                    "title": "Task A",
                    "task_type": "general",
                    "spec_hints": {"code_patterns": [123]},
                }
            ]
        },
    )

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
    assert "spec_hints.code_patterns" in result.stderr
    assert "must be a string" in result.stderr


def test_init_sprint_plan_rejects_carriage_return_spec_hint_item(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "task-a",
                    "title": "Task A",
                    "task_type": "general",
                    "scope": ["Safe text\r## Injected"],
                }
            ]
        },
    )

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
    assert "single line" in result.stderr


def test_init_sprint_writes_decree_checkpoint(tmp_path: Path) -> None:
    run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    result = run_cli(
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

    assert result.returncode == 0, result.stderr
    checkpoint = tmp_path / "demo-app" / ".theking" / "state" / "session" / "decree-session.md"
    assert checkpoint.is_file(), "init-sprint should auto-write decree checkpoint"
    content = checkpoint.read_text(encoding="utf-8")
    assert 'phase: "phase-3-planning"' in content
    assert 'sprint: "sprint-001-foundation"' in content

