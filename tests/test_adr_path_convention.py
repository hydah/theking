"""TASK-005 sprint-002: ADR path convention + template.

- templates/workflow/adr.md.tmpl must exist with the 5 required sections.
- agent_architect template must point to .theking/context/adr/ADR-NNN-<slug>.md.
- init-project / ensure must create .theking/context/adr/ directory.
- ensure must be idempotent over ADR files (do not wipe existing ADRs).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"

ADR_TEMPLATE = REPO_ROOT / "templates" / "workflow" / "adr.md.tmpl"
ARCHITECT_TEMPLATE = REPO_ROOT / "templates" / "agents" / "agent_architect.md.tmpl"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


# --- template presence ----------------------------------------------------


def test_adr_template_file_exists() -> None:
    assert ADR_TEMPLATE.is_file(), "templates/workflow/adr.md.tmpl must exist"


def test_adr_template_has_required_sections() -> None:
    text = ADR_TEMPLATE.read_text(encoding="utf-8")
    for section in (
        "## Context",
        "## Decision",
        "## Consequences",
        "## Alternatives Considered",
        "## Status",
    ):
        assert section in text, f"adr.md.tmpl missing section: {section}"


# --- architect template points to the concrete path ----------------------


def test_architect_template_references_concrete_adr_path() -> None:
    text = ARCHITECT_TEMPLATE.read_text(encoding="utf-8")
    assert ".theking/context/adr/" in text
    # Filename pattern hint.
    assert "ADR-" in text
    # Must NOT still use the vague "stored in .theking/context/" line.
    assert "stored in .theking/context/\n" not in text
    assert "stored in .theking/context/ " not in text


# --- scaffold creates the adr directory ----------------------------------


def test_init_project_creates_adr_directory(tmp_path: Path) -> None:
    project_slug = "demo-app"
    project_dir = tmp_path / project_slug
    project_dir.mkdir()

    result = run_cli(
        [
            "init-project",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            project_slug,
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    adr_dir = project_dir / ".theking" / "context" / "adr"
    assert adr_dir.is_dir(), f"adr/ dir not created: {adr_dir}"


def test_ensure_is_idempotent_over_existing_adr_files(tmp_path: Path) -> None:
    project_slug = "demo-app"
    project_dir = tmp_path / project_slug
    project_dir.mkdir()

    assert (
        run_cli(
            [
                "init-project",
                "--project-dir",
                str(project_dir),
                "--project-slug",
                project_slug,
            ],
            cwd=tmp_path,
        ).returncode
        == 0
    )

    adr_file = project_dir / ".theking" / "context" / "adr" / "ADR-042-dummy.md"
    adr_file.write_text("# ADR-042 dummy\n", encoding="utf-8")

    assert (
        run_cli(
            [
                "ensure",
                "--project-dir",
                str(project_dir),
                "--project-slug",
                project_slug,
            ],
            cwd=tmp_path,
        ).returncode
        == 0
    )

    assert adr_file.is_file()
    assert adr_file.read_text(encoding="utf-8") == "# ADR-042 dummy\n"
