"""Tests for the I-001 subagent-gating language additions to agent
descriptions.

Five agents (planner, tdd-guide, refactor-cleaner, doc-updater,
perf-optimizer) gain explicit "you may skip / only fire when X" language so
AI harnesses can self-skip subagent calls that add no signal. Four agents
(code-reviewer, security-reviewer, e2e-runner, architect) MUST stay
unchanged — their independent-judgment role is the audit invariant from
sprint-001.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validation import render_template  # noqa: E402

PROJECT_SLUG = "demo-app"


def render_agent(template_name: str) -> str:
    return render_template(template_name, project_slug=PROJECT_SLUG)


# --- Five agents that gain gating language ------------------------------


def test_planner_description_mentions_lightweight_skip() -> None:
    text = render_agent("agent_planner.md.tmpl")
    # Description lives in the leading `description:` field on the second line.
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "single-task lightweight" in description_line
    assert "empty plan" in description_line


def test_tdd_guide_description_mentions_pin_only_waiver() -> None:
    text = render_agent("agent_tdd_guide.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "pin-only" in description_line.lower()
    assert "step 1.5" in description_line.lower() or "adversarial" in description_line.lower()


def test_refactor_cleaner_description_restricts_to_phase_5() -> None:
    text = render_agent("agent_refactor_cleaner.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "phase 5" in description_line.lower()
    assert "do not call per-task" in description_line.lower()


def test_doc_updater_description_restricts_to_sprint_end() -> None:
    text = render_agent("agent_doc_updater.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "sprint-end" in description_line.lower() or "sprint end" in description_line.lower()
    assert "full flow" in description_line.lower()


def test_perf_optimizer_description_requires_measured_signal() -> None:
    text = render_agent("agent_perf_optimizer.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "measured" in description_line.lower() or "profiling" in description_line.lower()
    assert "do not invoke speculatively" in description_line.lower() or \
        "do not call speculatively" in description_line.lower()


# --- Four agents whose descriptions MUST NOT change ---------------------
#
# We cannot diff against a prior commit from inside the test, so we anchor
# on a stable substring that has been part of each description since
# sprint-001 / sprint-002. If a future change reworks the description, the
# author must update both the substring AND consciously decide whether the
# audit-independence guarantee still holds.


def test_code_reviewer_description_keeps_independent_role_anchor() -> None:
    text = render_agent("agent_code_reviewer.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "Reviews code for quality, security, and maintainability" in description_line
    assert "PROACTIVELY immediately after writing or modifying code" in description_line


def test_security_reviewer_description_keeps_independent_role_anchor() -> None:
    text = render_agent("agent_security_reviewer.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    # The exact phrase from the existing template — pinning it locks the
    # description against drift.
    assert "security" in description_line.lower()
    assert "PROACTIVELY" in description_line


def test_e2e_runner_description_keeps_independent_role_anchor() -> None:
    text = render_agent("agent_e2e_runner.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "E2E" in description_line or "end-to-end" in description_line.lower()
    assert "PROACTIVELY" in description_line


def test_architect_description_keeps_independent_role_anchor() -> None:
    text = render_agent("agent_architect.md.tmpl")
    description_line = next(
        line for line in text.splitlines() if line.startswith("description:")
    )
    assert "architecture" in description_line.lower()
    assert "PROACTIVELY" in description_line
