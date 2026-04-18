from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = REPO_ROOT / "install.sh"


def isolated_home_env(tmp_home: Path) -> dict[str, str]:
    bin_dir = tmp_home / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(tmp_home),
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }


def run_install(tmp_home: Path, *, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(INSTALL_SCRIPT)],
        cwd=REPO_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        env=isolated_home_env(tmp_home),
    )


def run_documented_install_entrypoint(
    tmp_home: Path, *args: str, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(INSTALL_SCRIPT), *args],
        cwd=REPO_ROOT,
        input=stdin,
        capture_output=True,
        text=True,
        env=isolated_home_env(tmp_home),
    )


def run_installed_command(
    tmp_home: Path, command: str, *args: str, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    run_cwd = cwd or (tmp_home.parent / "outside")
    run_cwd.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [command, *args],
        cwd=run_cwd,
        capture_output=True,
        text=True,
        env=isolated_home_env(tmp_home),
    )


def run_installed_workflowctl(tmp_home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_installed_command(tmp_home, "workflowctl", *args)


def test_documented_install_entrypoint_is_executable(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_documented_install_entrypoint(home, "--help")

    assert result.returncode == 0, result.stderr
    assert "install.sh - End-user installer" in result.stdout


def test_install_sh_default_install_exposes_workflowctl_in_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_install(home)

    assert result.returncode == 0, result.stderr
    assert (home / ".agents" / "skills" / "theking").is_dir()
    workflowctl_help = run_installed_workflowctl(home, "--help")
    assert workflowctl_help.returncode == 0, workflowctl_help.stderr
    assert "ensure" in workflowctl_help.stdout


def test_install_sh_installs_helper_wrappers(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    result = run_install(home)

    assert result.returncode == 0, result.stderr
    assert (home / ".local" / "bin" / "theking-install").is_file()
    assert not (home / ".local" / "bin" / "theking-dogfood").exists()


def test_install_sh_can_opt_in_claude_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)

    result = run_install(home, stdin="y\n")

    assert result.returncode == 0, result.stderr
    assert (home / ".agents" / "skills" / "theking").is_dir()
    assert (home / ".claude" / "skills" / "theking").exists()
    assert not (home / ".codebuddy" / "skills" / "theking").exists()


def test_install_sh_can_opt_in_codebuddy_runtime(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".codebuddy").mkdir(parents=True)

    result = run_install(home, stdin="y\n")

    assert result.returncode == 0, result.stderr
    assert (home / ".agents" / "skills" / "theking").is_dir()
    assert (home / ".codebuddy" / "skills" / "theking").exists()
    assert not (home / ".claude" / "skills" / "theking").exists()


def test_install_sh_is_idempotent_on_repeat_run(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    first = run_install(home)
    second = run_install(home)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    workflowctl_help = run_installed_workflowctl(home, "--help")
    assert workflowctl_help.returncode == 0, workflowctl_help.stderr
    assert (home / ".agents" / "skills" / "theking").is_dir()


def test_theking_install_wrapper_can_reinstall_safely(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    first = run_install(home)
    second = run_installed_command(home, "theking-install", "--yes")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (home / ".agents" / "skills" / "theking" / "scripts" / "workflowctl.py").is_file()
    workflowctl_help = run_installed_workflowctl(home, "--help")
    assert workflowctl_help.returncode == 0, workflowctl_help.stderr


def test_installed_wrappers_work_outside_repo_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    outside = tmp_path / "outside"
    home.mkdir()
    outside.mkdir()

    first = run_install(home)
    reinstall = run_installed_command(home, "theking-install", "--yes", cwd=outside)
    workflowctl_help = run_installed_command(home, "workflowctl", "--help", cwd=outside)

    assert first.returncode == 0, first.stderr
    assert reinstall.returncode == 0, reinstall.stderr
    assert workflowctl_help.returncode == 0, workflowctl_help.stderr
    assert "ensure" in workflowctl_help.stdout


def test_reinstall_replaces_managed_tree_instead_of_merging(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()

    first = run_install(home)
    stale_file = home / ".agents" / "skills" / "theking" / "EXTRA_STALE_FILE"
    stale_file.write_text("old", encoding="utf-8")

    second = run_installed_command(home, "theking-install", "--yes")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert not stale_file.exists()


def test_readme_documents_home_installer_flow() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "./install.sh" in readme
    assert "~/.agents/skills/theking" in readme
    assert ".claude" in readme
    assert ".codebuddy" in readme
    assert "theking-install" in readme
