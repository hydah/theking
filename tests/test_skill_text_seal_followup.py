"""Tests for sprint-003 TASK-005 — skill text additions covering reviewer
parallelism (I-002A) and the sealed-sprint / followup-sprint conventions
(documentation layer of I-007).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scaffold import build_runtime_template_vars  # noqa: E402
from validation import render_template  # noqa: E402


def render_skill() -> str:
    return render_template(
        "skill_workflow_governance.md.tmpl",
        **build_runtime_template_vars("demo-app"),
    )


# --- I-002A reviewer parallelism ----------------------------------------


def test_phase4_step7_documents_reviewer_parallelism() -> None:
    text = render_skill()
    # The new paragraph must mention parallelism explicitly and call out the
    # "between-rounds is sequential" carve-out so AI does not invent
    # cross-round parallel approval.
    assert "reviewer 并发" in text or "并行召唤" in text or "parallel" in text.lower()
    assert "code-reviewer" in text and "security-reviewer" in text and "e2e-runner" in text
    # Round-N -> round-N+1 must remain serialized.
    assert "round" in text.lower()


# --- I-007 docs layer: sealed sprints + followup-sprint -----------------


def test_phase5_step7_mentions_seal_sprint_command() -> None:
    text = render_skill()
    # `workflowctl deactivate` is already in Phase 5 step 7. The new line
    # must add `seal-sprint` as the immediate next step.
    assert "seal-sprint" in text
    # Rationale anchor: the sealed sprint is immutable.
    assert "封印" in text or "sealed" in text.lower() or "immutable" in text.lower()


def test_skill_has_followup_sprint_section_with_four_scenarios() -> None:
    text = render_skill()
    # New section must enumerate the 4 scenarios from evolution-workflow-ux.md
    # I-007 so AI knows which naming convention to apply.
    assert "followup-sprint" in text
    assert "场景 A" in text
    assert "场景 B" in text
    # The 4 scenario distinguishers from I-007:
    assert "自然延续" in text
    assert "独立议题" in text
    assert "真 bug" in text or "明确遗留" in text
    assert "演进" in text


def test_workflowctl_command_index_includes_seal_and_followup() -> None:
    text = render_skill()
    # The command index table at the bottom of the skill must list both new
    # commands so a quick reference reader sees them.
    assert "seal-sprint" in text
    assert "followup-sprint" in text


def test_skill_text_links_back_to_evolution_workflow_ux() -> None:
    """The sealed-sprint section must point readers at the canonical I-007
    discussion in evolution-workflow-ux.md instead of duplicating the full
    rationale (single source of truth)."""

    text = render_skill()
    assert "evolution-workflow-ux" in text or "I-007" in text
