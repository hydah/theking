"""Per-Phase Rationalizations tests (sprint-010 TASK-003).

Scope: the workflow-governance skill template must carry a Rationalizations
subsection per Phase (not only a single global table), because LLM
self-rationalization at each Phase boundary uses phase-specific excuses that
the global table does not enumerate.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "templates" / "skills" / "skill_workflow_governance.md.tmpl"
WORKFLOWCTL = REPO_ROOT / "scripts" / "workflowctl.py"

PHASES = (1, 2, 3, 4, 5)


def _template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _section_body(text: str, heading: str) -> str:
    """Return the text between `heading` and the next `### ` or `## ` heading."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        return ""
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("### ") or line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def test_five_phase_rationalization_subsections_exist() -> None:
    text = _template_text()
    for n in PHASES:
        heading = f"### Phase {n} 合理化借口"
        assert heading in text, f"missing subsection: `{heading}`"


def test_each_phase_rationalization_has_at_least_three_entries() -> None:
    text = _template_text()
    for n in PHASES:
        heading = f"### Phase {n} 合理化借口"
        body = _section_body(text, heading)
        assert body, f"section `{heading}` is empty"
        pipe_lines = [line for line in body.splitlines() if line.lstrip().startswith("|")]
        # Markdown table: 1 header + 1 divider + >=3 content rows -> >=5 lines.
        assert len(pipe_lines) >= 5, (
            f"section `{heading}` has {len(pipe_lines)} pipe-lines, expected >= 5 "
            f"(header + divider + >=3 entries)"
        )


def test_red_flags_usage_guidance_present() -> None:
    """Round-001 finding-002 fix: anchor on the actual paragraph, not scattered
    keywords. The guidance must exist as a single paragraph that (a) names the
    three-step action in order (stop → look up → return to gate) AND (b) cross-
    references the Rationalizations table by name. Deleting the paragraph or
    silently paraphrasing away the cross-reference must fail this test.
    """
    text = _template_text()
    m = re.search(
        r"使用方法.{0,20}三步.*?停.*?(查|对照|翻).*?(回到?|返回).*?(门禁|Phase|阶段)",
        text,
        re.DOTALL,
    )
    assert m is not None, "three-step usage paragraph missing or broken"
    # Must be wired to Rationalizations so the two tables are explicitly paired.
    assert "合理化借口" in m.group(0) or "Rationalizations" in m.group(0), (
        "three-step paragraph does not cross-reference the Rationalizations table"
    )


def test_global_rationalizations_table_remains_intact() -> None:
    """Safety-net: per-Phase additions must not accidentally delete or
    fragment the global `## 🛡️ 常见借口与反驳` table.
    """
    text = _template_text()
    assert "## 🛡️ 常见借口与反驳" in text
    # The original 12-row table should still be present (check for a few of
    # the canonical entries that shipped in sprint-009).
    for canonical_line in (
        "这只是个小改动，不需要 spec",
        "我只是改个 bug，不用 review",
        "reviewer 的意见我大概懂了",
    ):
        assert canonical_line in text, f"canonical rationalization missing: {canonical_line!r}"


def test_ensure_writes_phase_rationalizations_to_fresh_project(tmp_path: Path) -> None:
    """`workflowctl ensure` must project the new per-Phase subsections into
    the generated `.theking/skills/workflow-governance/SKILL.md`.
    """
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    slug = "demo-app"

    r = subprocess.run(
        [
            sys.executable,
            str(WORKFLOWCTL),
            "ensure",
            "--project-dir",
            ".",
            "--project-slug",
            slug,
        ],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    generated = (
        project_dir
        / ".theking"
        / "skills"
        / "workflow-governance"
        / "SKILL.md"
    )
    # `ensure` may symlink or materialize — follow through either way.
    assert generated.exists(), f"{generated} missing after ensure"
    body = generated.read_text(encoding="utf-8")

    for n in PHASES:
        assert f"### Phase {n} 合理化借口" in body, (
            f"generated SKILL.md is missing `### Phase {n} 合理化借口`"
        )


def test_phase_rationalizations_are_adjacent_to_their_red_flags() -> None:
    """Structural sanity: each per-Phase rationalization subsection should
    sit within 60 lines of the corresponding `### Phase N 危险信号` so the
    two tables read together, not at opposite ends of the document.
    """
    text = _template_text()
    lines = text.splitlines()
    for n in PHASES:
        red_heading = f"### Phase {n} 危险信号"
        rat_heading = f"### Phase {n} 合理化借口"
        try:
            red_idx = next(i for i, line in enumerate(lines) if line.strip() == red_heading)
            rat_idx = next(i for i, line in enumerate(lines) if line.strip() == rat_heading)
        except StopIteration:
            raise AssertionError(f"Phase {n} headings not both found")
        distance = abs(red_idx - rat_idx)
        assert distance <= 60, (
            f"Phase {n}: distance between `{red_heading}` and "
            f"`{rat_heading}` is {distance} lines (limit 60)"
        )


# Round-001 finding-003 resolved: removed `test_task_md_template_and_scaffold_untouched`.
# The test claimed to enforce scope discipline ("TASK-003 is pure-doc, no scripts
# touched") but only asserted that TASK-001/002 symbols were still present — a
# tautology unrelated to TASK-003's scope. The real scope gate is code review.
#
# Round-001 finding-004 resolved: removed `test_cleanup_tmp_artifacts`. pytest
# already manages tmp_path cleanup; the test was self-proving scaffolding with
# no product-behaviour coverage.
