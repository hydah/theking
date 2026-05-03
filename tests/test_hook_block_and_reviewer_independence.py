"""sprint-019 TASK-004: PreToolUse hook blocks edits without an active
task (for production code paths), and review-round artifacts declare
their reviewer with an independence level that triggers a self-audit
checklist requirement when reviewer is the main agent itself.

This closes sprint-017 followup偏差 C: "code-reviewer / doc-updater
全自审，无独立 subagent" — the failure mode where the agent writing
the code also "reviews" it, producing review.md files that rubber-stamp
their own work because there's no adversarial pressure.

Part A (hook): the existing .theking/hooks/check-spec-exists.js hook
already warns when there's no active-task, but then **passes the tool
call through**. An LLM under time pressure reads the warning and
proceeds. This task upgrades the warn-pass branch to a hard exit(1)
when the edited file is production code, keeping the pass-through for
tests/ and .theking/ edits.

Part B (review schema): add Reviewer and Reviewer independence fields
to code_review_round.md template; enforce self-audit checklist >= 10
when reviewer is `self` or `main-agent-fallback`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import validate_reviewer_declaration  # noqa: E402

HOOK_JS = REPO_ROOT / ".theking" / "hooks" / "check-spec-exists.js"
HOOK_TMPL = REPO_ROOT / "templates" / "hooks" / "hook_check_spec.js.tmpl"
REVIEW_TMPL = REPO_ROOT / "templates" / "workflow" / "code_review_round.md.tmpl"


def run_hook(cwd: Path, input_json: dict) -> subprocess.CompletedProcess[str]:
    """Invoke the real hook script via node, mirroring how Claude Code
    runs it as a PreToolUse hook."""
    return subprocess.run(
        ["node", str(HOOK_JS)],
        cwd=cwd,
        input=json.dumps(input_json),
        capture_output=True,
        text=True,
    )


def _mk_theking_no_active(tmp_path: Path) -> None:
    """Create .theking/ dir without an active-task file."""
    (tmp_path / ".theking").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Part A: hook block behavior
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node not in PATH")
def test_hook_blocks_no_active_task_source_code(tmp_path: Path) -> None:
    _mk_theking_no_active(tmp_path)
    r = run_hook(tmp_path, {"tool_input": {"file_path": "scripts/validation.py"}})
    assert r.returncode == 1, (
        f"Hook must BLOCK (exit 1) when no active-task and editing production code; "
        f"got exit={r.returncode}, stderr={r.stderr!r}"
    )
    assert "active task" in r.stderr.lower() or "no active" in r.stderr.lower(), r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not in PATH")
def test_hook_passes_no_active_task_tests_path(tmp_path: Path) -> None:
    _mk_theking_no_active(tmp_path)
    r = run_hook(tmp_path, {"tool_input": {"file_path": "tests/test_x.py"}})
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not in PATH")
def test_hook_passes_no_active_task_theking_path(tmp_path: Path) -> None:
    _mk_theking_no_active(tmp_path)
    r = run_hook(
        tmp_path,
        {"tool_input": {"file_path": ".theking/workflows/demo/sprints/s/tasks/TASK-001-x/spec.md"}},
    )
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not in PATH")
def test_hook_passes_empty_file_path(tmp_path: Path) -> None:
    _mk_theking_no_active(tmp_path)
    r = run_hook(tmp_path, {"tool_input": {}})
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node not in PATH")
def test_hook_still_blocks_missing_spec_with_active_task(tmp_path: Path) -> None:
    """Existing behavior preserved: with active-task + spec.md missing,
    hook blocks. This is the sprint-010+ behavior — don't regress."""
    theking = tmp_path / ".theking"
    theking.mkdir()
    task_dir = tmp_path / "task-dir-a"
    task_dir.mkdir()
    (task_dir / "task.md").write_text("---\nstatus: red\n---\n", encoding="utf-8")
    # NO spec.md
    (theking / "active-task").write_text(str(task_dir), encoding="utf-8")

    r = run_hook(tmp_path, {"tool_input": {"file_path": "scripts/validation.py"}})
    assert r.returncode == 1, r.stderr
    assert "spec.md" in r.stderr.lower(), r.stderr


def test_hook_template_matches_runtime() -> None:
    """The runtime .theking/hooks/check-spec-exists.js must be kept in
    sync with templates/hooks/hook_check_spec.js.tmpl because `ensure`
    re-projects the template on upgrade. Drift here = the next
    `workflowctl upgrade` silently reverts the TASK-004 block logic."""
    runtime = HOOK_JS.read_text(encoding="utf-8")
    template = HOOK_TMPL.read_text(encoding="utf-8")
    # Strip the shell substitution wrapper the template may add; compare
    # the core block-on-no-active-task logic.
    for marker in ("No active task", "process.exit(1)"):
        assert marker in runtime, f"runtime hook missing marker: {marker}"
        assert marker in template, f"template hook missing marker: {marker}"


# ---------------------------------------------------------------------------
# Part B: review template schema
# ---------------------------------------------------------------------------


def test_review_template_has_reviewer_fields() -> None:
    text = REVIEW_TMPL.read_text(encoding="utf-8")
    assert "Reviewer:" in text, "code_review_round.md template must include 'Reviewer:' field"
    assert "Reviewer independence:" in text, (
        "code_review_round.md template must include 'Reviewer independence:' field"
    )


def test_review_template_distinguishes_legacy_fallback_from_new_task_strictness() -> None:
    text = REVIEW_TMPL.read_text(encoding="utf-8")
    lower = text.lower()

    assert "agent-runs.jsonl" in text
    assert "new terminal" in lower or "new tasks" in lower
    assert "self" in lower
    assert "main-agent-fallback" in lower
    assert "reviewer-agent" in lower
    assert "not satisfy" in lower or "does not satisfy" in lower


# ---------------------------------------------------------------------------
# Part B: validate_reviewer_declaration
# ---------------------------------------------------------------------------


def _write_review(
    tmp_path: Path,
    *,
    reviewer: str | None = "self",
    independence: str | None = "self",
    checklist_items: int | None = 0,
) -> Path:
    """Assemble a review round markdown file with configurable shape."""
    lines = ["# Code Review Round 001", "", "## Context"]
    if reviewer is not None:
        lines.append(f"- Reviewer: {reviewer}")
    if independence is not None:
        lines.append(f"- Reviewer independence: {independence}")
    lines.extend(["", "## Findings", "- (no findings this round)"])
    if checklist_items is not None and checklist_items >= 0:
        lines.extend(["", "## Self-audit checklist (>= 10 points)"])
        for i in range(1, checklist_items + 1):
            lines.append(f"- Point {i}: verified")
    review = tmp_path / "code-review-round-001.md"
    review.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return review


def test_legacy_review_without_reviewer_field_passes(tmp_path: Path) -> None:
    """Legacy review files have no Reviewer: line — validator silent-passes."""
    review = _write_review(tmp_path, reviewer=None, independence=None, checklist_items=None)
    validate_reviewer_declaration(review)


def test_self_review_with_full_checklist_passes(tmp_path: Path) -> None:
    review = _write_review(tmp_path, reviewer="self", independence="self", checklist_items=12)
    validate_reviewer_declaration(review)


def test_self_review_insufficient_checklist_rejected(tmp_path: Path) -> None:
    review = _write_review(tmp_path, reviewer="self", independence="self", checklist_items=5)
    with pytest.raises(WorkflowError, match=r"(?is)(checklist|10)"):
        validate_reviewer_declaration(review)


def test_main_agent_fallback_review_requires_checklist(tmp_path: Path) -> None:
    review = _write_review(
        tmp_path, reviewer="self", independence="main-agent-fallback", checklist_items=3
    )
    with pytest.raises(WorkflowError, match=r"(?is)(checklist|10)"):
        validate_reviewer_declaration(review)


def test_parenthetical_legacy_independence_value_is_normalized(tmp_path: Path) -> None:
    review = _write_review(
        tmp_path,
        reviewer="self",
        independence="main-agent-fallback (sprint-017 followup-B flagged)",
        checklist_items=12,
    )

    validate_reviewer_declaration(review)


def test_subagent_review_without_checklist_passes(tmp_path: Path) -> None:
    """When independence is subagent-via-task-tool, no checklist required."""
    review = _write_review(
        tmp_path,
        reviewer="code-reviewer",
        independence="subagent-via-task-tool",
        checklist_items=0,
    )
    validate_reviewer_declaration(review)


def test_subagent_via_cli_passes(tmp_path: Path) -> None:
    review = _write_review(
        tmp_path, reviewer="code-reviewer", independence="subagent-via-cli", checklist_items=0
    )
    validate_reviewer_declaration(review)


def test_invalid_independence_value_rejected(tmp_path: Path) -> None:
    review = _write_review(
        tmp_path, reviewer="self", independence="random-value", checklist_items=12
    )
    with pytest.raises(WorkflowError, match=r"(?is)(independence|random)"):
        validate_reviewer_declaration(review)


def test_reviewer_field_case_insensitive(tmp_path: Path) -> None:
    """Accept 'reviewer:' / 'REVIEWER:' / 'Reviewer:' alike."""
    (tmp_path / "review.md").write_text(
        "# Code Review Round 001\n\n"
        "## Context\n"
        "- REVIEWER: self\n"
        "- REVIEWER INDEPENDENCE: subagent-via-task-tool\n"
        "\n## Findings\n- (no findings)\n",
        encoding="utf-8",
    )
    validate_reviewer_declaration(tmp_path / "review.md")


def test_nested_bullets_not_counted_in_checklist(tmp_path: Path) -> None:
    """Only top-level bullets count toward the 10-item floor."""
    body = [
        "# Code Review Round 001",
        "",
        "## Context",
        "- Reviewer: self",
        "- Reviewer independence: self",
        "",
        "## Findings",
        "- (no findings)",
        "",
        "## Self-audit checklist (>= 10 points)",
    ]
    # 5 top-level items, each with 2 nested bullets = 15 total bullets but
    # only 5 top-level. Must be rejected.
    for i in range(1, 6):
        body.append(f"- Top-level {i}")
        body.append(f"  - nested {i}a")
        body.append(f"  - nested {i}b")
    review = tmp_path / "review.md"
    review.write_text("\n".join(body) + "\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match=r"(?is)(checklist|10)"):
        validate_reviewer_declaration(review)
