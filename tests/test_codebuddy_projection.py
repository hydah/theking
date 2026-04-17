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


def init_project(tmp_path: Path, slug: str = "demo-app") -> Path:
    result = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", slug], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    return tmp_path / slug


def test_codebuddy_agents_projection_has_flavored_frontmatter(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    planner = (project_dir / ".codebuddy" / "agents" / "planner.md").read_text(encoding="utf-8")

    assert planner.startswith("---\n")
    assert "name: planner" in planner
    assert "description:" in planner
    assert "tools: list_dir, search_file" in planner
    assert "agentMode: agentic" in planner
    assert "enabled: true" in planner
    assert "enabledAutoRun: true" in planner
    # Claude-specific values must not leak.
    assert "tools: Read" not in planner
    assert "model: opus" not in planner


def test_claude_agents_projection_preserves_canonical_content(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    canonical = (project_dir / ".theking" / "agents" / "architect.md").read_text(encoding="utf-8")
    projected = (project_dir / ".claude" / "agents" / "architect.md").read_text(encoding="utf-8")
    assert canonical == projected
    # Canonical still has Claude flavor.
    assert "tools: Read, Grep, Glob" in canonical
    assert "model: opus" in canonical


def test_codebuddy_agents_projection_preserves_agent_body(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    for filename in ("planner.md", "architect.md", "code-reviewer.md", "tdd-guide.md"):
        theking = (project_dir / ".theking" / "agents" / filename).read_text(encoding="utf-8")
        codebuddy = (project_dir / ".codebuddy" / "agents" / filename).read_text(encoding="utf-8")
        _, _, theking_body = theking.partition("\n---\n")
        _, _, codebuddy_body = codebuddy.partition("\n---\n")
        assert theking_body == codebuddy_body, f"Body diverged for {filename}"


def test_codebuddy_projection_is_idempotent(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    planner_path = project_dir / ".codebuddy" / "agents" / "planner.md"
    first = planner_path.read_text(encoding="utf-8")

    # Re-run ensure — should produce identical output (no double-rewrite).
    result = run_cli(
        ["ensure", "--project-dir", str(project_dir), "--project-slug", "demo-app"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr
    second = planner_path.read_text(encoding="utf-8")
    assert first == second

    # Count of keys should not have doubled.
    assert second.count("agentMode: agentic") == 1
    assert second.count("enabled: true") == 1
    assert second.count("enabledAutoRun: true") == 1
    assert second.count("tools: list_dir") == 1


def test_codebuddy_commands_remain_symlinked_to_canonical(tmp_path: Path) -> None:
    project_dir = init_project(tmp_path)
    # Commands have no Claude-specific frontmatter, so they stay symlinked
    # (no content divergence needed).
    commands = project_dir / ".codebuddy" / "commands"
    assert commands.is_symlink()
    assert commands.resolve() == (project_dir / ".theking" / "commands").resolve()


def test_rewriter_unit_behavior() -> None:
    import importlib
    import sys as _sys

    scripts_dir = str(SCRIPT_PATH.parent)
    if scripts_dir not in _sys.path:
        _sys.path.insert(0, scripts_dir)
    module = importlib.import_module("scaffold")
    rewrite = module.rewrite_agent_frontmatter_for_codebuddy

    sample = (
        "---\n"
        "name: planner\n"
        'description: "Implementation planning."\n'
        "tools: Read, Grep, Glob\n"
        "model: opus\n"
        "---\n"
        "Body stays the same.\n"
    )
    out = rewrite("planner.md", sample)
    assert "name: planner" in out
    assert 'description: "Implementation planning."' in out
    assert "tools: Read, Grep, Glob" not in out
    assert "model: opus" not in out
    assert "agentMode: agentic" in out
    assert out.endswith("Body stays the same.\n")

    # Nested paths are a no-op (only top-level agent files are rewritten).
    nested = rewrite("subdir/planner.md", sample)
    assert nested == sample

    # Non-.md files are a no-op.
    not_md = rewrite("planner.txt", sample)
    assert not_md == sample

    # Files without frontmatter are a no-op.
    no_fm = rewrite("planner.md", "Just text, no frontmatter.\n")
    assert no_fm == "Just text, no frontmatter.\n"

    # Multi-line description (block scalar) in preserved keys must survive.
    with_block = (
        "---\n"
        "name: skill\n"
        "description: |\n"
        "  Line one.\n"
        "  Line two.\n"
        "tools: Read\n"
        "---\n"
        "body\n"
    )
    out_block = rewrite("skill.md", with_block)
    assert "description: |" in out_block
    assert "  Line one." in out_block
    assert "  Line two." in out_block
    assert "tools: Read\n" not in out_block
    assert "tools: list_dir" in out_block
