"""Unit tests for the spec section count gate (sprint-002 TASK-001, ADR-001).

When require_content is True (i.e. the task has advanced past `planned`), the
spec.md must carry at least a minimum number of items under 'Test Plan' and
'Edge Cases', driven by the task's flow (default `full`, opt into
`lightweight` via task.md frontmatter).

- Full flow: Test Plan >= 5, Edge Cases >= 3
- Lightweight flow: Test Plan >= 3, Edge Cases >= 1
- Legacy spec structure (only Acceptance + Test Plan sections) keeps bypassing.
- Comment-only content still counts as 0.
- Nested bullets under a top-level bullet count as 1 top-level item.

The error message must name the deficient section and both remediation paths
(switch to lightweight flow, or add more items).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    SPEC_SECTION_COUNT_THRESHOLDS_FULL,
    SPEC_SECTION_COUNT_THRESHOLDS_LIGHT,
    count_spec_section_items,
    normalize_task_flow,
    validate_spec_section_counts,
)

FULL_FLOW_SPEC = """# Task Spec

## Scope
- Implement feature X.

## Non-Goals
- Avoid unrelated cleanup.

## Acceptance
- [ ] Behavior Y is testable.

## Test Plan
- Unit test a.
- Unit test b.
- Unit test c.
- Integration test d.
- Regression e.

## Edge Cases
- Empty input.
- Boundary value.
- Concurrent access.
"""

# Variant: AI-generated spec with ordered (numbered) lists — must also pass.
FULL_FLOW_SPEC_ORDERED = """# Task Spec

## Scope
- Implement feature X.

## Non-Goals
- Avoid unrelated cleanup.

## Acceptance
- [ ] Behavior Y is testable.

## Test Plan
1. Unit test a.
2. Unit test b.
3. Unit test c.
4. Integration test d.
5. Regression e.

## Edge Cases
1. Empty input.
2. Boundary value.
3. Concurrent access.
"""

# Variant: mixed ordered + unordered lists — must also pass.
FULL_FLOW_SPEC_MIXED = """# Task Spec

## Scope
- Implement feature X.

## Non-Goals
- Avoid unrelated cleanup.

## Acceptance
- [ ] Behavior Y is testable.

## Test Plan
- Unit test a.
2. Unit test b.
- Unit test c.
4. Integration test d.
- Regression e.

## Edge Cases
- Empty input.
2. Boundary value.
- Concurrent access.
"""

LIGHTWEIGHT_FLOW_SPEC = """# Task Spec

## Scope
- Implement feature X.

## Non-Goals
- Avoid unrelated cleanup.

## Acceptance
- [ ] Behavior Y is testable.

## Test Plan
- Unit test a.
- Unit test b.
- Regression c.

## Edge Cases
- Empty input.
"""

LEGACY_SPEC = """# Task Spec

## Acceptance
- [ ] Something is tested.

## Test Plan
- One thing.
"""


# --- count_spec_section_items ----------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("- a\n- b\n- c\n", 3),
        ("- a\n  - nested under a\n- b\n", 2),  # nested is not a new top-level
        ("- [ ] checkbox\n- [x] done\n", 2),
        ("- a\n\n- b\n\n- c\n", 3),
        ("", 0),
        ("<!-- fill me in -->\n", 0),
        ("- a\n<!-- still placeholder -->\n", 1),
        ("*Not a bullet in our counting*\n", 0),  # only leading -/*/+ top-level
        ("  - indented only\n", 0),
        # --- Ordered (numbered) lists — AI runtimes commonly generate these ---
        ("1. first\n2. second\n3. third\n", 3),
        ("1. first\n   - nested detail\n2. second\n", 2),  # nested not top-level
        ("1. first\n\n2. second\n\n3. third\n", 3),  # blank lines between
        ("1) first\n2) second\n3) third\n", 3),  # paren style
        ("  1. indented ordered\n", 0),  # indented — not top-level
        # --- Mixed ordered + unordered ---
        ("- bullet a\n1. ordered b\n- bullet c\n", 3),
        ("1. ordered\n- unordered\n2. ordered again\n", 3),
    ],
)
def test_count_spec_section_items_counts_top_level_bullets(
    body: str, expected: int
) -> None:
    assert count_spec_section_items(body) == expected


# --- normalize_task_flow ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "full"), ("full", "full"), ("lightweight", "lightweight")],
)
def test_normalize_task_flow_accepts_known_values(raw, expected) -> None:
    assert normalize_task_flow(raw) == expected


def test_normalize_task_flow_rejects_unknown_value() -> None:
    with pytest.raises(WorkflowError, match="flow"):
        normalize_task_flow("heavy")


# --- validate_spec_section_counts: acceptance cases ------------------------


def test_full_flow_accepts_exactly_meeting_thresholds(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(FULL_FLOW_SPEC, encoding="utf-8")
    # Should not raise.
    validate_spec_section_counts(spec, flow="full")


def test_full_flow_accepts_ordered_list_spec(tmp_path: Path) -> None:
    """AI runtimes (Cursor/Codex/CodeBuddy) commonly generate numbered lists."""
    spec = tmp_path / "spec.md"
    spec.write_text(FULL_FLOW_SPEC_ORDERED, encoding="utf-8")
    # Should not raise — ordered lists are valid markdown lists.
    validate_spec_section_counts(spec, flow="full")


def test_full_flow_accepts_mixed_list_spec(tmp_path: Path) -> None:
    """Specs may mix ordered and unordered lists within the same section."""
    spec = tmp_path / "spec.md"
    spec.write_text(FULL_FLOW_SPEC_MIXED, encoding="utf-8")
    validate_spec_section_counts(spec, flow="full")


def test_lightweight_flow_accepts_lighter_thresholds(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(LIGHTWEIGHT_FLOW_SPEC, encoding="utf-8")
    validate_spec_section_counts(spec, flow="lightweight")


def test_legacy_spec_bypass_is_honored(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text(LEGACY_SPEC, encoding="utf-8")
    # Legacy structure (only Acceptance + Test Plan) bypasses the count gate.
    validate_spec_section_counts(spec, flow="full")


# --- validate_spec_section_counts: rejection cases -------------------------


def test_full_flow_rejects_test_plan_below_threshold(tmp_path: Path) -> None:
    sparse = FULL_FLOW_SPEC.replace(
        "## Test Plan\n- Unit test a.\n- Unit test b.\n- Unit test c.\n"
        "- Integration test d.\n- Regression e.\n",
        "## Test Plan\n- Unit test a.\n- Unit test b.\n",
    )
    spec = tmp_path / "spec.md"
    spec.write_text(sparse, encoding="utf-8")
    with pytest.raises(WorkflowError) as excinfo:
        validate_spec_section_counts(spec, flow="full")
    msg = str(excinfo.value)
    assert "Test Plan" in msg
    assert "5" in msg  # the threshold
    assert "2" in msg  # the observed count
    # Both remediation paths must be named.
    assert "lightweight" in msg.lower()


def test_full_flow_rejects_edge_cases_below_threshold(tmp_path: Path) -> None:
    sparse = FULL_FLOW_SPEC.replace(
        "## Edge Cases\n- Empty input.\n- Boundary value.\n- Concurrent access.\n",
        "## Edge Cases\n- Empty input.\n",
    )
    spec = tmp_path / "spec.md"
    spec.write_text(sparse, encoding="utf-8")
    with pytest.raises(WorkflowError, match="Edge Cases"):
        validate_spec_section_counts(spec, flow="full")


def test_lightweight_flow_rejects_when_even_lighter_thresholds_fail(
    tmp_path: Path,
) -> None:
    very_sparse = LIGHTWEIGHT_FLOW_SPEC.replace(
        "## Test Plan\n- Unit test a.\n- Unit test b.\n- Regression c.\n",
        "## Test Plan\n- Unit test a.\n",
    )
    spec = tmp_path / "spec.md"
    spec.write_text(very_sparse, encoding="utf-8")
    with pytest.raises(WorkflowError, match="Test Plan"):
        validate_spec_section_counts(spec, flow="lightweight")


# --- Thresholds ------------------------------------------------------------


def test_full_thresholds_are_strict_and_documented() -> None:
    assert SPEC_SECTION_COUNT_THRESHOLDS_FULL == {"Test Plan": 5, "Edge Cases": 3}
    assert SPEC_SECTION_COUNT_THRESHOLDS_LIGHT == {"Test Plan": 3, "Edge Cases": 1}
    # Lightweight must be strictly lighter than full for every tracked section.
    for key, full_threshold in SPEC_SECTION_COUNT_THRESHOLDS_FULL.items():
        assert SPEC_SECTION_COUNT_THRESHOLDS_LIGHT[key] < full_threshold
