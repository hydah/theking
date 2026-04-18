"""TASK-004 sprint-002: tdd-guide adversarial inputs discipline.

agent_tdd_guide.md.tmpl must carry a 'Step 1.5 Adversarial Inputs' block
between Step 1 (Read spec.md) and Step 2 (Write Failing Tests) that mandates
enumerating 10 failure categories and covering >= 5 in Red-phase tests.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = REPO_ROOT / "templates" / "agents" / "agent_tdd_guide.md.tmpl"


def read_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_step_1_5_header_present() -> None:
    text = read_template()
    # The block must have a stable discoverable header.
    assert "Step 1.5" in text
    assert "Adversarial" in text


def test_step_1_5_states_10_categories_5_covered() -> None:
    text = read_template()
    # Find the Step 1.5 region.
    start = text.index("Step 1.5")
    # End at the next "### Step" header.
    rest = text[start:]
    end = rest.index("### Step 2")
    block = rest[:end]
    # Assert both magic numbers exist in the block.
    assert "10" in block, "Step 1.5 must state the 10-category enumeration"
    assert "5" in block, "Step 1.5 must state the >= 5 coverage requirement"


def test_step_1_5_seeds_at_least_five_example_categories() -> None:
    text = read_template()
    start = text.index("Step 1.5")
    end = text.index("### Step 2", start)
    block = text[start:end]
    # Loose contains-checks for seed categories. Exact wording allowed to
    # vary, but the five concepts must appear.
    seeds = ("type", "size", "concurrency", "ordering", "encoding")
    missing = [s for s in seeds if s not in block.lower()]
    assert not missing, f"Step 1.5 seed categories missing: {missing}"


def test_step_1_5_positioned_between_step_1_and_step_2() -> None:
    text = read_template()
    step1 = text.index("### Step 1:")
    step1_5 = text.index("### Step 1.5")
    step2 = text.index("### Step 2:")
    assert step1 < step1_5 < step2, (
        "Step 1.5 must be positioned between Step 1 (Read spec.md) and Step 2 "
        "(Write Failing Tests)"
    )


def test_original_tdd_workflow_steps_are_preserved() -> None:
    text = read_template()
    # Previous skill contract: Steps 1-6 (Read, Write Red, Verify Fail,
    # Minimal Green, Verify Pass, Refactor). They must survive.
    for header in (
        "### Step 1: Read spec.md",
        "### Step 2: Write Failing Tests",
        "### Step 3: Verify Tests Fail",
        "### Step 4: Write Minimal Implementation",
        "### Step 5: Verify Tests Pass",
        "### Step 6: Refactor",
    ):
        assert header in text, f"missing: {header}"
