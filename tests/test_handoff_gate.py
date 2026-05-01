"""Red-phase tests for validate_handoff_evidence_anchors + planned->red gate.

Covers the 6 scenarios enumerated in
.theking/workflows/theking/sprints/sprint-013-main-agent-offloading-p0/
tasks/TASK-001-handoff-living-doc-gate/spec.md :

    1. handoff.md absent              -> validator passes silently
    2. handoff.md has no file:line    -> WorkflowError naming both sections
                                         + \\S+:\\d+ format hint
    3. ref under "Viewed code/..."    -> passes
    4. ref only under "Impact surface"-> passes
    5. ref only in unrelated section  -> WorkflowError
    6. non planned->red transition    -> gate not invoked (CLI level)

Cases 1-5 exercise validate_handoff_evidence_anchors directly
(acceptance: "exported and covered by unit tests independently of
the workflowctl entry point").

Case 6 spawns workflowctl as a subprocess because only a real
handle_advance_status call can prove the planned->red gate is
properly guarded (mirrors tests/test_finalize.py's CLI style and
tests/test_init_task.py's bootstrap_sprint helper).

These tests are deliberately RED: they import a symbol
(`validate_handoff_evidence_anchors`) that does not yet exist in
scripts/validation.py. Running pytest must surface an ImportError
or AttributeError on the unit tests and a non-rejected CLI path on
case 6 — both are acceptable red signals for this task.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402


def _load_validator():
    """Import validate_handoff_evidence_anchors lazily.

    Done per-test so that case 6 (which only drives the CLI) can still
    be collected and run independently of whether the symbol exists
    yet. This keeps each of the 6 scenarios as a separately-reported
    red signal instead of collapsing them into one collection error.
    """
    from validation import validate_handoff_evidence_anchors  # noqa: WPS433

    return validate_handoff_evidence_anchors


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


FORMAT_HINT_TOKEN = r"\S+:\d+"
SECTION_VIEWED = "Viewed code/tests/docs"
SECTION_IMPACT = "Impact surface"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def write_handoff(task_dir: Path, body: str) -> Path:
    """Write handoff.md with the given body; return its path."""
    task_dir.mkdir(parents=True, exist_ok=True)
    handoff = task_dir / "handoff.md"
    handoff.write_text(body, encoding="utf-8")
    return handoff


def handoff_body(
    *,
    viewed_bullets: list[str] | None = None,
    impact_bullets: list[str] | None = None,
    pitfalls_bullets: list[str] | None = None,
) -> str:
    """Build a handoff.md body mirroring templates/workflow/handoff.md.tmpl."""

    def block(header: str, bullets: list[str] | None) -> list[str]:
        lines = [header]
        for bullet in bullets or []:
            lines.append(f"  - {bullet}")
        return lines

    lines: list[str] = [
        "# Task Handoff",
        "",
        "> Purpose: compact Phase 1 context for downstream agents.",
        "",
        "## Phase 1 Evidence Anchors",
    ]
    lines.extend(block(f"- {SECTION_VIEWED}:", viewed_bullets))
    lines.extend(block(f"- {SECTION_IMPACT}:", impact_bullets))
    lines.extend(
        [
            "- Risk tags:",
            "- Open questions:",
            "",
            "## Known Pitfalls",
        ]
    )
    for bullet in pitfalls_bullets or []:
        lines.append(f"- {bullet}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Case 1: handoff.md absent -> silent pass
# ---------------------------------------------------------------------------


def test_validator_silently_passes_when_handoff_file_absent(tmp_path: Path) -> None:
    """Legacy tasks (pre sprint-011) have no handoff.md; gate must not punish them.

    Mirrors validate_agent_runs_ledger's file-existence guard at
    scripts/validation.py:758-759 .
    """
    validator = _load_validator()
    missing = tmp_path / "TASK-legacy" / "handoff.md"
    assert not missing.exists()
    # Must not raise.
    validator(missing)


# ---------------------------------------------------------------------------
# Case 2: both target sections have zero file:line refs -> fail with hint
# ---------------------------------------------------------------------------


def test_validator_rejects_handoff_with_no_file_line_references(tmp_path: Path) -> None:
    """Empty anchor sections are the most common footgun — must be caught."""
    validator = _load_validator()
    handoff = write_handoff(
        tmp_path,
        handoff_body(
            viewed_bullets=["just a note with no path"],
            impact_bullets=["also nothing concrete here"],
        ),
    )
    with pytest.raises(WorkflowError) as exc_info:
        validator(handoff)

    msg = str(exc_info.value)
    assert SECTION_VIEWED in msg, (
        f"Error must name section {SECTION_VIEWED!r} so the user knows "
        f"where to paste refs. Got: {msg!r}"
    )
    assert SECTION_IMPACT in msg, (
        f"Error must name section {SECTION_IMPACT!r}. Got: {msg!r}"
    )
    assert FORMAT_HINT_TOKEN in msg, (
        f"Error must embed the regex hint {FORMAT_HINT_TOKEN!r} so the user "
        f"knows what shape refs take (e.g. path/to/file.py:123). Got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Case 3: ref under "Viewed code/tests/docs" -> pass
# ---------------------------------------------------------------------------


def test_validator_accepts_ref_under_viewed_section(tmp_path: Path) -> None:
    validator = _load_validator()
    handoff = write_handoff(
        tmp_path,
        handoff_body(
            viewed_bullets=["scripts/validation.py:747 reference helper"],
            impact_bullets=["prose without colon-number"],
        ),
    )
    # Must not raise.
    validator(handoff)


# ---------------------------------------------------------------------------
# Case 4: ref only under "Impact surface" -> pass
# ---------------------------------------------------------------------------


def test_validator_accepts_ref_only_under_impact_section(tmp_path: Path) -> None:
    validator = _load_validator()
    handoff = write_handoff(
        tmp_path,
        handoff_body(
            viewed_bullets=["prose without colon-number"],
            impact_bullets=["scripts/workflowctl.py:720 new gate hook"],
        ),
    )
    # Must not raise.
    validator(handoff)


# ---------------------------------------------------------------------------
# Case 5: ref only in unrelated section -> fail
# ---------------------------------------------------------------------------


def test_validator_rejects_ref_placed_in_unrelated_section(tmp_path: Path) -> None:
    """A file:line buried under 'Known Pitfalls' is not evidence of Phase-1
    scouting. Gate must scan only the two target sections, not the whole file."""
    validator = _load_validator()
    handoff = write_handoff(
        tmp_path,
        handoff_body(
            viewed_bullets=["empty bullet"],
            impact_bullets=["also empty"],
            pitfalls_bullets=["scripts/validation.py:747 misplaced ref"],
        ),
    )
    with pytest.raises(WorkflowError) as exc_info:
        validator(handoff)
    msg = str(exc_info.value)
    assert SECTION_VIEWED in msg
    assert SECTION_IMPACT in msg


# ---------------------------------------------------------------------------
# Case 5b: HTML comment examples must NOT count as anchors
# ---------------------------------------------------------------------------


def test_validator_ignores_file_line_refs_inside_html_comments(tmp_path: Path) -> None:
    """The default template ships example file:line refs inside HTML comments
    (e.g. `<!-- - scripts/example.py:42 ... -->`). A fresh scaffolded task
    whose author has not filled anything substantive should still fail the
    gate; comment examples must not constitute evidence of real Phase-1
    scouting."""
    validator = _load_validator()
    body_lines = [
        "# Task Handoff",
        "",
        "## Phase 1 Evidence Anchors",
        f"- {SECTION_VIEWED}:",
        "  <!-- - scripts/example.py:42 brief note on what you verified there -->",
        f"- {SECTION_IMPACT}:",
        "  <!-- - scripts/example.py:80 new function injected here -->",
        "- Risk tags:",
        "- Open questions:",
        "",
    ]
    handoff = write_handoff(tmp_path, "\n".join(body_lines))
    with pytest.raises(WorkflowError) as exc_info:
        validator(handoff)
    msg = str(exc_info.value)
    assert SECTION_VIEWED in msg
    assert SECTION_IMPACT in msg
    assert FORMAT_HINT_TOKEN in msg


# ---------------------------------------------------------------------------
# Case 6: planned -> green transition is NOT guarded by the gate
# ---------------------------------------------------------------------------

# Spec content that satisfies sprint-002 TASK-001's section-count thresholds
# (Test Plan >= 5, Edge Cases >= 3). Mirrors tests/test_init_task.py's
# write_complete_spec so advance-status does not fail for unrelated reasons.
COMPLETE_SPEC = "\n".join(
    [
        "# Task Spec",
        "",
        "## Scope",
        "- Keep the handoff gate off the planned->green fast-path.",
        "",
        "## Non-Goals",
        "- No unrelated refactors.",
        "",
        "## Acceptance",
        "- planned->green transitions succeed without touching handoff.md.",
        "",
        "## Test Plan",
        "- Run the relevant automated checks.",
        "- Exercise the happy path end-to-end.",
        "- Cover the primary error path.",
        "- Verify idempotency of the workflow.",
        "- Run the regression suite.",
        "",
        "## Edge Cases",
        "- Re-running the flow keeps the task tree consistent.",
        "- Missing optional inputs do not crash.",
        "- Partial artifacts do not block recovery.",
    ]
)


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def bootstrap_sprint(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr
    init_sprint = run_cli(
        [
            "init-sprint",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--theme",
            "foundation",
        ],
        cwd=tmp_path,
    )
    assert init_sprint.returncode == 0, init_sprint.stderr


def test_cli_does_not_invoke_gate_on_non_planned_to_red_transition(
    tmp_path: Path,
) -> None:
    """Fast-path planned -> green must succeed even when handoff.md has
    zero file:line refs. Only planned -> red is gated (spec Non-Goals
    explicitly forbids touching any other transition)."""
    bootstrap_sprint(tmp_path)

    init_task = run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "bypass-gate",
            "--title",
            "Bypass Gate",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.cli",
        ],
        cwd=tmp_path,
    )
    assert init_task.returncode == 0, init_task.stderr

    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-bypass-gate"
    )

    # Fill spec so planned->green does not fail for section-count reasons.
    (task_dir / "spec.md").write_text(COMPLETE_SPEC, encoding="utf-8")

    # Deliberately leave handoff.md empty of file:line refs. If the gate
    # fires on planned->green, this file would cause a rejection.
    write_handoff(
        task_dir,
        handoff_body(
            viewed_bullets=["nothing concrete"],
            impact_bullets=["also nothing"],
        ),
    )

    planned = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    assert planned.returncode == 0, (
        f"draft->planned must not be gated. stderr={planned.stderr!r}"
    )

    green = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "green"],
        cwd=tmp_path,
    )
    assert green.returncode == 0, (
        "planned->green fast-path must not trigger the handoff gate "
        "(spec Non-Goals: 'Does NOT modify any other status transition'). "
        f"stdout={green.stdout!r} stderr={green.stderr!r}"
    )
