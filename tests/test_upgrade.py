from __future__ import annotations

import json
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


def init_project(tmp_path: Path, slug: str = "demo-app") -> Path:
    result = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", slug], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return tmp_path / slug


def load_manifest(project_dir: Path) -> dict[str, str]:
    path = project_dir / ".theking" / ".manifests" / "runtime.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("files")
    assert isinstance(files, dict)
    return files


def test_init_project_baselines_runtime_manifest(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    manifest = load_manifest(project_dir)

    # Known managed entries should be baselined.
    expected_any = [
        "README.md",
        "bootstrap.md",
        "context/architecture.md",
        "context/dev-workflow.md",
        "agents/planner.md",
        "hooks/check-spec-exists.js",
        "skills/workflow-governance/SKILL.md",
        "commands/decree.md",
        "prompts/decree.prompt.md",
    ]
    for rel in expected_any:
        key = f".theking/{rel}"
        assert key in manifest, f"{key} missing from manifest: {sorted(manifest)[:5]}..."

    # User content must NOT be tracked.
    forbidden = [
        ".theking/context/project-overview.md",
        ".theking/memory/MEMORY.md",
        "CLAUDE.md",
        "CODEBUDDY.md",
        "AGENTS.md",
    ]
    for key in forbidden:
        assert key not in manifest, f"{key} unexpectedly present in manifest"


def test_upgrade_fresh_install_is_all_current(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)

    result = run_cli(
        ["upgrade", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    # No drift, no created (all files exist after init), no upgrades needed.
    assert "Drift" not in result.stdout
    assert "Upgraded" not in result.stdout
    assert "Created" not in result.stdout
    assert "Current" in result.stdout


def test_upgrade_refreshes_tracked_file_after_template_change(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "bootstrap.md"
    original = target.read_text(encoding="utf-8")

    # Simulate a "theking skill upgrade" by mutating the on-disk file's hash
    # to match a hypothetical previous template, with its hash already in the
    # manifest. Here we emulate the inverse: change the file on disk and set
    # the manifest so the tracked hash matches the current (mutated) content.
    mutated = original + "\n<!-- mutated by simulated old template -->\n"
    target.write_text(mutated, encoding="utf-8")

    # Rewrite manifest: track the mutated hash as if that were the previous
    # known-theking content. Upgrade must then treat it as safe and overwrite
    # with the current template output.
    import hashlib

    manifest_path = project_dir / ".theking" / ".manifests" / "runtime.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"][".theking/bootstrap.md"] = hashlib.sha256(
        mutated.encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = run_cli(
        ["upgrade", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert ".theking/bootstrap.md" in result.stdout
    assert "Upgraded" in result.stdout
    assert target.read_text(encoding="utf-8") == original


def test_upgrade_detects_drift_and_leaves_file_alone(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "agents" / "planner.md"
    drifted = target.read_text(encoding="utf-8") + "\n<!-- user edit -->\n"
    target.write_text(drifted, encoding="utf-8")

    result = run_cli(
        ["upgrade", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert "Drift" in result.stdout
    assert "agents/planner.md" in result.stdout
    # File must be untouched.
    assert target.read_text(encoding="utf-8") == drifted


def test_upgrade_force_backs_up_and_overwrites_drift(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "agents" / "planner.md"
    pristine = target.read_text(encoding="utf-8")
    drifted = pristine + "\n<!-- user edit -->\n"
    target.write_text(drifted, encoding="utf-8")

    result = run_cli(
        [
            "upgrade",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--force",
        ],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert "Force-upgraded" in result.stdout

    assert target.read_text(encoding="utf-8") == pristine

    backup_root = project_dir / ".theking" / ".backups"
    assert backup_root.is_dir()
    backups = list(backup_root.iterdir())
    assert len(backups) == 1
    backed_up = backups[0] / ".theking" / "agents" / "planner.md"
    assert backed_up.is_file()
    assert backed_up.read_text(encoding="utf-8") == drifted


def test_upgrade_adopt_keeps_user_edit_but_baselines_manifest(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "agents" / "planner.md"
    drifted = target.read_text(encoding="utf-8") + "\n<!-- user edit -->\n"
    target.write_text(drifted, encoding="utf-8")

    result = run_cli(
        [
            "upgrade",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--adopt",
        ],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert "Adopted" in result.stdout
    assert target.read_text(encoding="utf-8") == drifted

    import hashlib

    manifest = load_manifest(project_dir)
    assert manifest[".theking/agents/planner.md"] == hashlib.sha256(
        drifted.encode("utf-8")
    ).hexdigest()

    # A second upgrade should now see the file as "current" (manifest matches
    # on-disk), NOT as drift.
    second = run_cli(
        ["upgrade", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert second.returncode == 0, second.stderr
    assert "Drift" not in second.stdout


def test_upgrade_dry_run_does_not_modify_files_or_manifest(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "agents" / "planner.md"
    drifted = target.read_text(encoding="utf-8") + "\n<!-- drift -->\n"
    target.write_text(drifted, encoding="utf-8")

    before_manifest = load_manifest(project_dir)

    result = run_cli(
        [
            "upgrade",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--force",
            "--dry-run",
        ],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert "dry run" in result.stdout.lower()
    # File untouched.
    assert target.read_text(encoding="utf-8") == drifted
    # Manifest untouched.
    assert load_manifest(project_dir) == before_manifest
    # No backup directory created.
    assert not (project_dir / ".theking" / ".backups").exists()


def test_upgrade_recreates_deleted_managed_file(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    target = project_dir / ".theking" / "commands" / "decree.md"
    target.unlink()

    result = run_cli(
        ["upgrade", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    assert target.is_file()
    # `ensure_theking_scaffold` runs before the upgrade pass and recreates
    # missing canonical files, so the upgrade sees it as "Current".
    assert "Current" in result.stdout


def test_upgrade_adopt_and_force_are_mutually_exclusive(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    result = run_cli(
        [
            "upgrade",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--adopt",
            "--force",
        ],
        cwd=project_dir,
    )
    # argparse enforces mutual exclusion at parse time.
    assert result.returncode != 0
    assert "not allowed with" in result.stderr or "mutually exclusive" in result.stderr.lower()
