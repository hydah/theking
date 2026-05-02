from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")


pytestmark = pytest.mark.skipif(UV is None, reason="uv is required for console script tests")


def run_console_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [UV, "run", "workflowctl", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def write_complete_spec(task_dir: Path) -> None:
    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Complete the minimal console workflow successfully.",
                "",
                "## Non-Goals",
                "- No unrelated cleanup.",
                "",
                "## Acceptance",
                "- The task can advance into review with the expected artifacts.",
                "",
                "## Test Plan",
                "- Run the console workflow commands in sequence.",
                "- Exercise the happy path.",
                "- Exercise the error path.",
                "- Verify idempotency.",
                "- Run the regression suite.",
                "",
                "## Edge Cases",
                "- Re-running the status transitions keeps task history valid.",
                "- Missing optional inputs do not crash.",
                "- Partial artifacts do not block recovery.",
            ]
        ),
        encoding="utf-8",
    )


def test_workflowctl_console_script_help_runs() -> None:
    result = run_console_cli(["--help"])

    assert result.returncode == 0, result.stderr
    assert "init-project" in result.stdout
    assert "ensure" in result.stdout
    assert "checkpoint" in result.stdout
    assert "status" in result.stdout
    assert "advance-status" in result.stdout
    assert "init-review-round" in result.stdout
    assert "pipx install /path/to/theking" in result.stdout
    assert "project-dir" in result.stdout


@pytest.mark.parametrize(
    "command",
    ["ensure", "init-project", "init-sprint", "init-task", "init-sprint-plan", "deactivate", "checkpoint", "status"],
)
def test_workflowctl_root_command_help_mentions_project_root_and_theking_compatibility(command: str) -> None:
    result = run_console_cli([command, "--help"])

    assert result.returncode == 0, result.stderr
    assert "project-dir" in result.stdout
    assert ".theking" in result.stdout
    if command != "deactivate":
        assert "--root" in result.stdout
    else:
        assert "--project-slug" not in result.stdout


def test_workflowctl_console_script_can_ensure_project(tmp_path: Path) -> None:
    result = run_console_cli([
        "ensure",
        "--root",
        str(tmp_path),
        "--project-slug",
        "console-demo",
    ])

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "console-demo" / ".theking" / "workflows" / "console-demo" / "project.md").is_file()


def test_workflowctl_console_script_runs_minimal_task_workflow(tmp_path: Path) -> None:
    ensure_result = run_console_cli([
        "ensure",
        "--root",
        str(tmp_path),
        "--project-slug",
        "console-demo",
    ])
    sprint_result = run_console_cli([
        "init-sprint",
        "--root",
        str(tmp_path),
        "--project-slug",
        "console-demo",
        "--theme",
        "foundation",
    ])
    task_result = run_console_cli([
        "init-task",
        "--root",
        str(tmp_path),
        "--project-slug",
        "console-demo",
        "--sprint",
        "sprint-001-foundation",
        "--slug",
        "demo",
        "--title",
        "Demo",
        "--task-type",
        "tooling",
        "--execution-profile",
        "backend.cli",
    ])

    task_dir = (
        tmp_path
        / "console-demo"
        / ".theking"
        / "workflows"
        / "console-demo"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-demo"
    )
    check_result = run_console_cli([
        "check",
        "--task-dir",
        str(task_dir),
    ])
    # sprint-015 TASK-001: draft-exit Goal gate.
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    planned_result = run_console_cli([
        "advance-status",
        "--task-dir",
        str(task_dir),
        "--to-status",
        "planned",
    ])
    red_result = run_console_cli([
        "advance-status",
        "--task-dir",
        str(task_dir),
        "--to-status",
        "red",
    ])

    write_complete_spec(task_dir)

    retry_red_result = run_console_cli([
        "advance-status",
        "--task-dir",
        str(task_dir),
        "--to-status",
        "red",
    ])
    green_result = run_console_cli([
        "advance-status",
        "--task-dir",
        str(task_dir),
        "--to-status",
        "green",
    ])
    review_round_result = run_console_cli([
        "init-review-round",
        "--task-dir",
        str(task_dir),
    ])

    assert ensure_result.returncode == 0, ensure_result.stderr
    assert sprint_result.returncode == 0, sprint_result.stderr
    assert task_result.returncode == 0, task_result.stderr
    assert check_result.returncode == 0, check_result.stderr
    assert planned_result.returncode == 0, planned_result.stderr
    assert red_result.returncode != 0
    assert "section must not be empty: Scope" in red_result.stderr
    assert retry_red_result.returncode == 0, retry_red_result.stderr
    assert green_result.returncode == 0, green_result.stderr
    assert review_round_result.returncode == 0, review_round_result.stderr
    assert task_dir.is_dir()
    assert check_result.stdout.strip().startswith("OK ")
    task_text = (task_dir / "task.md").read_text(encoding="utf-8")
    assert "status: in_review" in task_text
    assert "current_review_round: 1" in task_text
    assert (task_dir / "review" / "code-review-round-001.md").is_file()


def test_workflowctl_built_wheel_exports_entrypoint_and_runs_help(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    site_dir = tmp_path / "site"
    build_result = subprocess.run(
        [UV, "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert build_result.returncode == 0, build_result.stderr
    wheel_path = next(dist_dir.glob("*.whl"))

    with zipfile.ZipFile(wheel_path) as wheel_archive:
        wheel_archive.extractall(site_dir)

    entry_points = next(site_dir.glob("*.dist-info/entry_points.txt")).read_text(encoding="utf-8")
    assert "workflowctl = theking.workflowctl:main" in entry_points

    help_result = subprocess.run(
        [sys.executable, "-c", "from theking.workflowctl import main; main(['--help'])"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(site_dir)},
        capture_output=True,
        text=True,
    )

    assert help_result.returncode == 0, help_result.stderr
    assert "init-project" in help_result.stdout
    assert "ensure" in help_result.stdout
    assert "project-dir" in help_result.stdout