"""TASK-006 sprint-002: code-reviewer 'Untested Paths' dimension.

The code-reviewer agent template must add an explicit 'Test Coverage' category
to its Review Checklist, an optional '## Untested Paths' block in the Findings
format, and the approval criteria must name 'missing Untested Paths on
non-trivial changes' as a HIGH-level concern.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = (
    REPO_ROOT / "templates" / "agents" / "agent_code_reviewer.md.tmpl"
)


def read_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


# --- Review Checklist ------------------------------------------------------


def test_review_checklist_has_test_coverage_category() -> None:
    text = read_template()
    assert "### Test Coverage" in text, (
        "code-reviewer template must add a named 'Test Coverage' category"
    )


def test_test_coverage_category_lists_at_least_three_bullets() -> None:
    text = read_template()
    start = text.index("### Test Coverage")
    # End at the next '### ' header.
    rest = text[start + len("### Test Coverage") :]
    end = rest.find("### ")
    block = rest if end < 0 else rest[:end]
    bullets = [
        line for line in block.splitlines() if line.strip().startswith("- ")
    ]
    assert len(bullets) >= 3, (
        f"'Test Coverage' category must list >=3 concrete bullets; "
        f"got {len(bullets)}"
    )


def test_test_coverage_category_names_uncovered_branches() -> None:
    text = read_template()
    start = text.index("### Test Coverage")
    block = text[start : text.find("### ", start + 1)]
    lowered = block.lower()
    # At minimum these three concerns must be named.
    assert "uncovered" in lowered or "untested" in lowered
    assert "branch" in lowered or "path" in lowered
    assert "boundary" in lowered or "edge" in lowered


# --- Findings format: optional Untested Paths block ----------------------


def test_findings_format_has_optional_untested_paths_section() -> None:
    text = read_template()
    # Require both the header and explanatory wording.
    assert "## Untested Paths" in text
    # Must describe when to fill it in (non-trivial) and when it's optional.
    lowered = text.lower()
    assert "optional" in lowered or "when applicable" in lowered


# --- Approval criteria ----------------------------------------------------


def test_approval_criteria_mention_missing_untested_paths_as_high() -> None:
    text = read_template()
    # Locate the Approval Criteria block.
    start = text.index("## Approval Criteria")
    end = text.find("## ", start + 1)
    block = text[start:end] if end > 0 else text[start:]
    assert "Untested Paths" in block
    assert "HIGH" in block


# --- Backward compat: existing review format still documented -------------


def test_review_artifact_format_still_documented() -> None:
    text = read_template()
    assert "# Code Review Round NNN" in text
    assert "## Findings" in text
    assert "## Fixes" in text
    assert "## Verification" in text
