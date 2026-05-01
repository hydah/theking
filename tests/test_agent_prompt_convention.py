"""Drift + presence tests for the Task Context Entry Convention preamble
injected into every subagent prompt (sprint-013 TASK-003).

The convention tells downstream subagents to read `<TASK_DIR>/handoff.md`
before anything else. The invariant is:

  * every file in `templates/agents/agent_*.md.tmpl` contains the canonical
    preamble marker;
  * every file in `.theking/agents/*.md` (except non-agent files like
    README.md / catalog.md) contains the same marker;
  * the two trees must not drift out of sync.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = REPO_ROOT / "templates" / "agents"
CANONICAL_DIR = REPO_ROOT / ".theking" / "agents"

MARKER = "Task Context Entry Convention"
REQUIRED_PHRASES = (
    "handoff.md",
    "spec.md",
)

NON_AGENT_CANONICAL = {"README.md", "catalog.md"}


def iter_templates() -> list[Path]:
    return sorted(
        p for p in TEMPLATES_DIR.glob("agent_*.md.tmpl")
        if p.is_file()
    )


def iter_canonical_agents() -> list[Path]:
    if not CANONICAL_DIR.is_dir():
        return []
    return sorted(
        p for p in CANONICAL_DIR.glob("*.md")
        if p.is_file() and p.name not in NON_AGENT_CANONICAL
    )


def test_all_agent_templates_contain_entry_convention_marker() -> None:
    templates = iter_templates()
    assert templates, f"No agent templates found under {TEMPLATES_DIR}"
    missing = [p.name for p in templates if MARKER not in p.read_text(encoding="utf-8")]
    assert not missing, (
        f"These agent templates are missing the '{MARKER}' preamble: {missing}. "
        f"Every subagent prompt must instruct the agent to read handoff.md first."
    )


def test_all_agent_templates_reference_handoff_and_spec() -> None:
    templates = iter_templates()
    for path in templates:
        text = path.read_text(encoding="utf-8")
        for phrase in REQUIRED_PHRASES:
            assert phrase in text, (
                f"{path.name} missing required phrase '{phrase}' in the "
                f"Task Context Entry Convention preamble"
            )


def test_all_canonical_agents_contain_entry_convention_marker() -> None:
    canonical = iter_canonical_agents()
    if not canonical:
        # Canonical tree may not be projected in every workspace; skip then.
        return
    missing = [p.name for p in canonical if MARKER not in p.read_text(encoding="utf-8")]
    assert not missing, (
        f"These canonical agent prompts are missing the '{MARKER}' preamble: "
        f"{missing}. The .theking/agents/ tree must stay in sync with "
        f"templates/agents/ after install.sh projection."
    )


def test_template_and_canonical_tree_count_matches() -> None:
    """Sanity check that both trees project the same set of agents by name."""
    templates = iter_templates()
    canonical = iter_canonical_agents()
    if not canonical:
        return
    template_agent_names = {
        p.name.replace("agent_", "").replace(".md.tmpl", "").replace("_", "-")
        for p in templates
    }
    canonical_agent_names = {p.stem for p in canonical}
    # templates have strict subset relationship with canonical (canonical may
    # legitimately include extras like 'catalog', already filtered out).
    missing_from_canonical = template_agent_names - canonical_agent_names
    assert not missing_from_canonical, (
        f"Templates exist but are not projected into .theking/agents/: "
        f"{missing_from_canonical}"
    )
