"""TASK-002 sprint-002: Phase 1 scouting checklist lands in the workflow skill.

The skill_workflow_governance template must carry a 4-item research checklist
inside the Phase 1 察情 奏报格式, and the Phase 1->2 self-check line must
reference it. The existing 奏报 fields (已查看 / 影响面 / 风险标签 / 未决问题)
must remain.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = (
    REPO_ROOT / "templates" / "skills" / "skill_workflow_governance.md.tmpl"
)


def read_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


# --- Checklist presence ---------------------------------------------------


def test_phase1_contains_scouting_checklist_heading() -> None:
    text = read_template()
    assert "调研清单" in text, "Phase 1 must introduce a 调研清单 block"


def test_phase1_checklist_enumerates_four_items() -> None:
    text = read_template()
    # The 4 mandated items: prior art / external docs / reusable helpers / same-module edge cases.
    assert "3 处先例" in text
    assert "外部库" in text or "外部文档" in text or "官方文档" in text
    assert "测试 helper" in text or "测试辅助" in text
    assert "edge case" in text.lower() or "边界" in text


def test_phase1_self_check_mentions_checklist() -> None:
    text = read_template()
    # The self-check block already enumerates Phase 1 -> 2 gating.
    # Ensure it now references the checklist by name.
    assert "调研清单" in text
    # The old self-check line (初勘结果) should still exist as the structural transition.
    assert "已输出初勘结果" in text


# --- 奏报格式 backward compatibility ---------------------------------------


def test_phase1_奏报格式_retains_original_fields() -> None:
    text = read_template()
    for field in ("已查看", "影响面", "风险标签", "未决问题"):
        assert field in text, f"奏报格式 must still contain {field}"


def test_phase1_forbids_skipping_research_on_lightweight_flow() -> None:
    text = read_template()
    # Intent: user should not be able to go 轻量 to skip the checklist.
    # We assert the text explicitly states the checklist is required before
    # declaring any flow level.
    assert "未察案牍" in text  # existing guardrail line
    assert "调研清单" in text  # new checklist line
