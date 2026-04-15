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


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def test_init_project_creates_theking_scaffold_and_workflow_root(tmp_path: Path) -> None:
    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    project_dir = tmp_path / "demo-app"
    theking_dir = project_dir / ".theking"
    project_md = workflow_root(tmp_path) / "project.md"

    assert project_dir.is_dir()
    assert theking_dir.is_dir()
    assert project_md.is_file()
    assert "demo-app" in project_md.read_text(encoding="utf-8")
    assert (theking_dir / "README.md").is_file()
    assert (theking_dir / "bootstrap.md").is_file()
    assert (theking_dir / "context" / "project-overview.md").is_file()
    assert (theking_dir / "context" / "architecture.md").is_file()
    assert (theking_dir / "context" / "dev-workflow.md").is_file()
    assert (theking_dir / "memory" / "MEMORY.md").is_file()
    assert (theking_dir / "verification" / "README.md").is_file()
    assert (theking_dir / "agents" / "README.md").is_file()
    assert (theking_dir / "agents" / "catalog.md").is_file()
    assert (theking_dir / "commands").is_dir()
    assert (theking_dir / "skills").is_dir()
    assert (theking_dir / "runs").is_dir()
    assert "agents/catalog.md" in (theking_dir / "README.md").read_text(encoding="utf-8")
    assert "*** Add File" not in (theking_dir / "agents" / "README.md").read_text(encoding="utf-8")
    assert not (project_dir / "project.md").exists()
    assert not (project_dir / "sprints").exists()


def test_init_project_preserves_existing_project_files_and_adds_theking(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    readme = project_dir / "README.md"
    readme.write_text("existing project file\n", encoding="utf-8")

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert readme.read_text(encoding="utf-8") == "existing project file\n"
    assert (project_dir / ".theking" / "README.md").is_file()
    assert (project_dir / ".theking" / "agents" / "catalog.md").is_file()
    assert (workflow_root(tmp_path) / "project.md").is_file()
    assert not (project_dir / "project.md").exists()


def test_init_sprint_creates_sequential_sprint_directories_under_theking_workflows(tmp_path: Path) -> None:
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
    assert (workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "sprint.md").is_file()
    assert (workflow_root(tmp_path) / "sprints" / "sprint-002-auth-hardening" / "sprint.md").is_file()


def test_init_sprint_rejects_symlinked_sprints_directory(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr

    sprints_dir = workflow_root(tmp_path) / "sprints"
    outside_sprints = tmp_path / "outside-sprints"
    outside_sprints.mkdir()
    sprints_dir.rmdir()
    sprints_dir.symlink_to(outside_sprints, target_is_directory=True)

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

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr


def test_init_project_rejects_dangling_symlinked_project_file(tmp_path: Path) -> None:
    project_md = workflow_root(tmp_path) / "project.md"
    outside_target = tmp_path / "outside-project.md"
    project_md.parent.mkdir(parents=True, exist_ok=True)
    project_md.symlink_to(outside_target)

    result = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "overwrite" in result.stderr
    assert not outside_target.exists()
