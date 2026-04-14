from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def extract_required_agents(task_text: str) -> list[str]:
    marker = "required_agents:\n"
    start = task_text.index(marker) + len(marker)
    end = task_text.index("current_review_round:")
    block = task_text[start:end]
    return [line.strip()[2:].strip() for line in block.splitlines() if line.strip().startswith("-")]


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


def test_init_task_creates_minimal_task_tree_and_required_fields(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "auth",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_dir = (
        tmp_path
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-login-flow"
    )
    task_md = task_dir / "task.md"
    spec_md = task_dir / "spec.md"

    assert task_md.is_file()
    assert spec_md.is_file()
    assert (task_dir / "review").is_dir()

    task_text = task_md.read_text(encoding="utf-8")
    for field in (
        "id:",
        "title:",
        "status:",
        "task_type:",
        "requires_e2e:",
        "requires_security_review:",
        "required_agents:",
        "current_review_round:",
        "status_history:",
    ):
        assert field in task_text

    assert "status: draft" in task_text

    spec_text = spec_md.read_text(encoding="utf-8")
    assert "## Acceptance" in spec_text
    assert "## Test Plan" in spec_text


@pytest.mark.parametrize(
    ("task_type", "expected_agents"),
    [
        ("frontend", ["planner", "tdd-guide", "code-reviewer", "e2e-runner"]),
        ("e2e", ["planner", "tdd-guide", "code-reviewer", "e2e-runner"]),
        ("auth", ["planner", "tdd-guide", "code-reviewer", "security-reviewer"]),
        ("input", ["planner", "tdd-guide", "code-reviewer", "security-reviewer"]),
        ("api", ["planner", "tdd-guide", "code-reviewer", "security-reviewer"]),
    ],
)
def test_init_task_assigns_required_agents_by_task_type(
    tmp_path: Path,
    task_type: str,
    expected_agents: list[str],
) -> None:
    bootstrap_sprint(tmp_path)

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
            f"{task_type}-task",
            "--title",
            f"{task_type.title()} Task",
            "--task-type",
            task_type,
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_md = (
        tmp_path
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{task_type}-task"
        / "task.md"
    )
    task_text = task_md.read_text(encoding="utf-8")

    for agent in expected_agents:
        assert f"- {agent}" in task_text

    required_agents = extract_required_agents(task_text)
    assert required_agents == expected_agents
    assert len(required_agents) == len(set(required_agents))
