"""TASK-003 sprint-002: architect trigger signals in planner + skill.

Both the planner agent template and the workflow-governance skill template
must carry the same 4 signals verbatim (single source of truth), and the
skill template's Phase 3 complete flow must mandate calling architect
when any signal fires.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PLANNER_PATH = REPO_ROOT / "templates" / "agents" / "agent_planner.md.tmpl"
SKILL_PATH = REPO_ROOT / "templates" / "skills" / "skill_workflow_governance.md.tmpl"


SIGNALS = (
    "跨 module 接口",
    "引入新依赖",
    "公共接口变更",
    "数据迁移",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_planner_template_lists_all_four_signals() -> None:
    text = read(PLANNER_PATH)
    for signal in SIGNALS:
        assert signal in text, f"planner template missing signal: {signal}"


def test_planner_template_has_named_section_for_architect_trigger() -> None:
    text = read(PLANNER_PATH)
    # Require an explicit heading so readers can navigate to the rule.
    assert "何时召 architect" in text or "召 architect" in text


def test_skill_template_phase3_names_all_four_signals() -> None:
    text = read(SKILL_PATH)
    # Locate Phase 3 complete flow block.
    anchor = "#### 完整流程"
    assert anchor in text
    phase3 = text.split(anchor, 1)[1]
    # Stop at the next top-level Phase heading.
    phase3 = phase3.split("### ", 1)[0]
    for signal in SIGNALS:
        assert signal in phase3, (
            f"skill template Phase 3 complete flow missing signal: {signal}"
        )


def test_skill_template_phase3_mandates_calling_architect_on_signal() -> None:
    text = read(SKILL_PATH)
    anchor = "#### 完整流程"
    phase3 = text.split(anchor, 1)[1].split("### ", 1)[0]
    # The existing single line said "涉及架构决策时，先问太傅（architect）".
    # New contract: must explicitly name signals and say they MUST call architect.
    lowered = phase3.replace(" ", "").lower()
    assert "必须" in phase3 and "architect" in lowered


def test_planner_and_skill_signal_wording_is_identical() -> None:
    planner_text = read(PLANNER_PATH)
    skill_text = read(SKILL_PATH)
    # For each signal, both templates must contain the exact same phrase.
    # (We cannot assert a shared constant file, but we can assert cross-coverage.)
    for signal in SIGNALS:
        assert signal in planner_text
        assert signal in skill_text


def test_skill_template_lightweight_flow_does_not_trigger_architect() -> None:
    text = read(SKILL_PATH)
    # Phase 3 lightweight block must not add an architect call; it already reads
    # "创建单 task sprint（跳过 planner）". We assert the lightweight block is
    # free of new signal language, so the rule stays full-flow only.
    start = text.index("#### 轻量流程")
    lightweight = text[start : text.index("**⛔ 叩阙自检")]
    for signal in SIGNALS:
        assert signal not in lightweight, (
            f"lightweight flow block should not list architect signal: {signal}"
        )
