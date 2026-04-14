from __future__ import annotations

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


def test_init_project_creates_project_root_and_project_md(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    project_md = project_dir / "project.md"

    assert project_dir.is_dir()
    assert project_md.is_file()
    assert "demo-app" in project_md.read_text(encoding="utf-8")


def test_init_sprint_creates_sequential_sprint_directories_under_project(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr

    first = run_cli(
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
    second = run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "auth-hardening",
        ],
        cwd=tmp_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "demo-app" / "sprints" / "sprint-001-foundation" / "sprint.md").is_file()
    assert (tmp_path / "demo-app" / "sprints" / "sprint-002-auth-hardening" / "sprint.md").is_file()
