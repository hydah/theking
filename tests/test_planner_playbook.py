"""Static assertions on the planner agent + workflow-governance skill templates.

These tests guard the "playbook" content that AI agents read when they invoke
theking via Claude / CodeBuddy / Kimi / Codex. The content is pure markdown,
so we validate it by substring match rather than by rendering — rendering
happens elsewhere (test_init_project.py covers scaffold emission).

The goal is to prevent silent drift: if someone deletes the decision tree or
the compatibility matrix, CI fails before the regression reaches users.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLANNER_TMPL = REPO_ROOT / "templates" / "agents" / "agent_planner.md.tmpl"
PLANNER_PROJECTIONS = (
    PLANNER_TMPL,
    REPO_ROOT / ".theking" / "agents" / "planner.md",
    REPO_ROOT / ".claude" / "agents" / "planner.md",
    REPO_ROOT / ".codebuddy" / "agents" / "planner.md",
)
WORKFLOW_SKILL_TMPL = (
    REPO_ROOT / "templates" / "skills" / "skill_workflow_governance.md.tmpl"
)
WORKFLOW_SKILL_PROJECTIONS = (
    WORKFLOW_SKILL_TMPL,
    REPO_ROOT / ".theking" / "skills" / "workflow-governance" / "SKILL.md",
    REPO_ROOT / ".github" / "skills" / "workflow-governance" / "SKILL.md",
)

from scripts.constants import ALLOWED_TASK_TYPE_TOKENS
from scripts.sprint_plan import parse_bundles, parse_plan_entries


def read_planner() -> str:
    return PLANNER_TMPL.read_text(encoding="utf-8")


def read_planner_projections() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in PLANNER_PROJECTIONS]


def read_workflow_skill() -> str:
    return WORKFLOW_SKILL_TMPL.read_text(encoding="utf-8")


def read_workflow_skill_projections() -> list[tuple[Path, str]]:
    return [(path, path.read_text(encoding="utf-8")) for path in WORKFLOW_SKILL_PROJECTIONS]


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


def test_planner_compatibility_matrix_has_consistent_column_count() -> None:
    text = read_planner()
    matrix = re.search(
        r"\| task_type ↓ / execution_profile → \|.*?(?=\n\nRules of thumb)",
        text,
        flags=re.DOTALL,
    )
    assert matrix is not None, "compatibility matrix not found"
    rows = [line for line in matrix.group(0).splitlines() if line.startswith("|")]
    counts = [len(line.strip().strip("|").split("|")) for line in rows]
    assert len(set(counts)) == 1, f"matrix column counts drifted: {counts}"


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


def test_planner_projections_keep_plan_json_json_only() -> None:
    for path, text in read_planner_projections():
        assert "初勘响应" in text, path
        assert "outside the JSON block" in text, path
        assert "Do not put Markdown headings" in text, path


# --- workflow-governance skill: plan.json convention + review loop hint ---


def test_workflow_skill_documents_plan_json_sprint_local_path() -> None:
    text = read_workflow_skill()
    # Either a direct path mention or a template-variable-based one is fine,
    # but the sprint directory must be called out as the landing spot.
    assert (
        "sprints/" in text and "plan.json" in text
    ), "workflow-governance skill must document that plan.json lives under the sprint directory"


def test_workflow_skill_keeps_plan_json_json_only() -> None:
    for path, text in read_workflow_skill_projections():
        assert "plan.json 的 `##" not in text, path
        assert "Markdown" in text, path
        assert "伴随说明" in text, path


def test_workflow_skill_does_not_reintroduce_process_skip_exceptions() -> None:
    for path, text in read_workflow_skill_projections():
        assert "不需要 sprint / spec / review" not in text, path
        assert "可以跳过 theking 工作流" not in text, path
        assert "流程外快速处理" in text, path


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


def test_planner_plan_json_example_is_valid_json() -> None:
    text = read_planner()
    match = re.search(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    assert match is not None, "planner JSON example not found"
    example = match.group(1).replace("{{", "{").replace("}}", "}")
    assert re.search(r"^\s*\.\.\.\s*$", example, flags=re.MULTILINE) is None

    plan = json.loads(example)

    assert isinstance(plan["tasks"], list)
    for task in plan["tasks"]:
        for field in (
            "slug",
            "title",
            "task_type",
            "execution_profile",
            "depends_on",
            "review_mode",
            "scope",
            "non_goals",
            "acceptance",
            "edge_cases",
        ):
            assert field in task


def test_planner_plan_json_example_matches_plan_parser(tmp_path: Path) -> None:
    text = read_planner()
    match = re.search(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    assert match is not None, "planner JSON example not found"
    example = match.group(1).replace("{{", "{").replace("}}", "}")
    plan = json.loads(example)
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    parsed = parse_plan_entries(plan["tasks"], tasks_dir)
    parse_bundles(plan["bundles"], parsed["slug_to_id"], parsed["deps_by_slug"])
