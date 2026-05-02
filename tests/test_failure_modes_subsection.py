"""sprint-017 TASK-003: Edge Cases subsection split into Failure modes
+ Happy variants.

The previous gate counted Edge Cases as a flat bullet list. This left
the adversarial-inputs discipline from tdd-guide ('enumerate >= 10
failure categories, cover >= 5') as a pure text convention with no
machine enforcement. This task upgrades the gate: when spec.md uses
the new '### Failure modes' / '### Happy variants' subsections under
'## Edge Cases', validate_spec_section_counts counts them separately.

- Full flow:        Failure modes >= 2, Happy variants >= 1
- Lightweight flow: Failure modes >= 1 (Happy variants not required)
- Mechanical flow:  unchanged (skips Edge Cases entirely)

Backward compat: a flat bullet list under Edge Cases keeps the old
aggregated threshold (full >= 3, lightweight >= 1). Mixed forms
(flat bullets AND subsection headings) are rejected with an error
that asks the author to pick one structure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    validate_spec_section_counts,
)

# ---------------------------------------------------------------------------
# spec builders
# ---------------------------------------------------------------------------


HEADER = "# Task Spec\n\n## Scope\n- x\n\n## Non-Goals\n- y\n\n## Acceptance\n- [ ] z\n\n"


def spec_with_test_plan(n: int = 5) -> str:
    plan = "\n".join(f"- Item {i}" for i in range(n))
    return f"## Test Plan\n{plan}\n\n"


def write_spec(tmp_path: Path, edge_cases_body: str, *, test_plan_items: int = 5) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(
        HEADER + spec_with_test_plan(test_plan_items) + "## Edge Cases\n" + edge_cases_body,
        encoding="utf-8",
    )
    return spec


# ---------------------------------------------------------------------------
# backward compat: flat Edge Cases
# ---------------------------------------------------------------------------


def test_full_accepts_legacy_flat_structure(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "- Edge 1\n- Edge 2\n- Edge 3\n")
    # Must not raise.
    validate_spec_section_counts(spec, flow="full")


def test_full_rejects_legacy_flat_under_threshold(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "- Only one\n- Only two\n")
    with pytest.raises(WorkflowError, match=r"(?is)Edge Cases"):
        validate_spec_section_counts(spec, flow="full")


def test_lightweight_accepts_legacy_flat_minimum(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "- One is enough\n", test_plan_items=3)
    validate_spec_section_counts(spec, flow="lightweight")


# ---------------------------------------------------------------------------
# new subsection structure
# ---------------------------------------------------------------------------


def test_full_accepts_new_structure_with_thresholds(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "### Failure modes\n"
        "- boundary null input\n"
        "- concurrency reentry\n"
        "\n"
        "### Happy variants\n"
        "- two callers same payload\n",
    )
    validate_spec_section_counts(spec, flow="full")


def test_full_rejects_insufficient_failure_modes(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "### Failure modes\n"
        "- only one failure\n"
        "\n"
        "### Happy variants\n"
        "- happy 1\n"
        "- happy 2\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)Failure modes"):
        validate_spec_section_counts(spec, flow="full")


def test_full_rejects_insufficient_happy_variants(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "### Failure modes\n"
        "- a\n"
        "- b\n"
        "- c\n"
        "\n"
        "### Happy variants\n"
        "<!-- placeholder -->\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)Happy variants"):
        validate_spec_section_counts(spec, flow="full")


def test_lightweight_accepts_minimum(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "### Failure modes\n- one failure\n\n### Happy variants\n",
        test_plan_items=3,
    )
    validate_spec_section_counts(spec, flow="lightweight")


def test_lightweight_rejects_zero_failure_modes(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "### Failure modes\n"
        "<!-- nothing yet -->\n"
        "\n"
        "### Happy variants\n"
        "- a\n- b\n- c\n- d\n- e\n",
        test_plan_items=3,
    )
    with pytest.raises(WorkflowError, match=r"(?is)Failure modes"):
        validate_spec_section_counts(spec, flow="lightweight")


def test_mechanical_skips_edge_cases_entirely(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "")  # empty Edge Cases body
    # mechanical flow has no Test Plan / Edge Cases threshold.
    validate_spec_section_counts(spec, flow="mechanical")


# ---------------------------------------------------------------------------
# subsection header variations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure_header",
    ["### Failure modes", "### failure modes", "### FAILURE MODES", "### Failure Modes"],
)
def test_subsection_header_case_variants(tmp_path: Path, failure_header: str) -> None:
    spec = write_spec(
        tmp_path,
        f"{failure_header}\n"
        "- a\n- b\n"
        "\n"
        "### Happy variants\n"
        "- happy\n",
    )
    validate_spec_section_counts(spec, flow="full")


def test_nested_bullets_count_as_one_top_level_item(tmp_path: Path) -> None:
    """Mirror count_spec_section_items behaviour: nested bullets do NOT
    each become a top-level item."""
    spec = write_spec(
        tmp_path,
        "### Failure modes\n"
        "- outer 1\n"
        "  - nested 1a\n"
        "  - nested 1b\n"
        "- outer 2\n"
        "\n"
        "### Happy variants\n"
        "- happy 1\n",
    )
    validate_spec_section_counts(spec, flow="full")


def test_only_one_subsection_present_missing_is_zero(tmp_path: Path) -> None:
    """When only Failure modes is present and Happy variants is omitted
    entirely, Happy variants counts as 0."""
    spec = write_spec(
        tmp_path,
        "### Failure modes\n- a\n- b\n- c\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)Happy variants"):
        validate_spec_section_counts(spec, flow="full")


# ---------------------------------------------------------------------------
# mixed-form rejection
# ---------------------------------------------------------------------------


def test_rejects_mixed_flat_and_subsection_structure(tmp_path: Path) -> None:
    """Having top-level bullets AND subsection headers is ambiguous —
    must be rejected with an error that names both forms."""
    spec = write_spec(
        tmp_path,
        "- stray top-level bullet\n"
        "\n"
        "### Failure modes\n"
        "- one\n"
        "- two\n"
        "\n"
        "### Happy variants\n"
        "- happy\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)(mix|both|choose|pick one|one structure)"):
        validate_spec_section_counts(spec, flow="full")


# ---------------------------------------------------------------------------
# template scaffold
# ---------------------------------------------------------------------------


def test_template_contains_subsection_scaffolds() -> None:
    tmpl = (
        REPO_ROOT / "templates" / "workflow" / "spec.md.tmpl"
    ).read_text(encoding="utf-8")
    assert "### Failure modes" in tmpl, (
        "spec.md template must scaffold a '### Failure modes' subsection "
        "so authors discover the new structure without reading validation.py"
    )
    assert "### Happy variants" in tmpl, (
        "spec.md template must scaffold a '### Happy variants' subsection"
    )
