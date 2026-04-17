"""Static assertions on the planner agent + workflow-governance skill templates.

These tests guard the "playbook" content that AI agents read when they invoke
theking via Claude / CodeBuddy / Kimi / Codex. The content is pure markdown,
so we validate it by substring match rather than by rendering — rendering
happens elsewhere (test_init_project.py covers scaffold emission).

The goal is to prevent silent drift: if someone deletes the decision tree or
the compatibility matrix, CI fails before the regression reaches users.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANNER_TMPL = REPO_ROOT / "templates" / "agents" / "agent_planner.md.tmpl"
WORKFLOW_SKILL_TMPL = (
    REPO_ROOT / "templates" / "skills" / "skill_workflow_governance.md.tmpl"
)

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from constants import ALLOWED_TASK_TYPE_TOKENS  # noqa: E402


def read_planner() -> str:
    return PLANNER_TMPL.read_text(encoding="utf-8")


def read_workflow_skill() -> str:
    return WORKFLOW_SKILL_TMPL.read_text(encoding="utf-8")


# --- planner playbook: three tables ---


def test_planner_template_includes_task_type_decision_tree() -> None:
    text = read_planner()
    assert "task_type 决策树" in text, (
        "planner agent must document how to pick task_type from business context"
    )


def test_planner_template_includes_compatibility_matrix() -> None:
    text = read_planner()
    assert "兼容矩阵" in text, (
        "planner agent must show task_type × execution_profile compatibility "
        "matrix so AI avoids trial-and-error on init-sprint-plan"
    )
    # Matrix must mention each of the four execution_profiles by name.
    for profile in ("web.browser", "backend.http", "backend.cli", "backend.job"):
        assert profile in text, f"compatibility matrix missing profile: {profile}"


def test_planner_template_includes_security_review_rule() -> None:
    text = read_planner()
    assert "requires_security_review" in text
    assert "自动" in text or "auto" in text.lower(), (
        "planner must explain that requires_security_review is derived, not user-set"
    )


def test_planner_template_covers_every_allowed_task_type_token() -> None:
    text = read_planner()
    missing = [token for token in sorted(ALLOWED_TASK_TYPE_TOKENS) if token not in text]
    assert not missing, (
        f"planner template is missing these task_type tokens: {missing}. "
        "Every token in ALLOWED_TASK_TYPE_TOKENS must appear in the decision "
        "tree or the compatibility matrix so AI knows when to use it."
    )


# --- workflow-governance skill: plan.json convention + review loop hint ---


def test_workflow_skill_documents_plan_json_sprint_local_path() -> None:
    text = read_workflow_skill()
    # Either a direct path mention or a template-variable-based one is fine,
    # but the sprint directory must be called out as the landing spot.
    assert (
        "sprints/" in text and "plan.json" in text
    ), "workflow-governance skill must document that plan.json lives under the sprint directory"


def test_workflow_skill_clarifies_resolved_no_new_changes_path() -> None:
    text = read_workflow_skill()
    # When a round is resolved with no new code changes, advancing to
    # ready_to_merge is the right call — NOT opening a new review round.
    assert "ready_to_merge" in text
    assert (
        "无新改动" in text
        or "no new changes" in text.lower()
        or "直接 advance-status" in text
        or "直接推到 ready_to_merge" in text
    ), (
        "workflow-governance skill must warn against opening an empty round 2; "
        "resolved-with-no-code-changes should advance directly to ready_to_merge"
    )
