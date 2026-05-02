"""Review resolution coverage gate tests (sprint-010 TASK-001).

Goal: harden review pair validation from "file exists + section present" to
"every finding id declared in <type>-review-round-NNN.md must be closed in the
paired .resolved.md with Status: resolved|waived; waived must carry a
Waiver-Reason".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.constants import WorkflowError  # type: ignore[import-not-found]
from scripts.validation import (  # type: ignore[attr-defined,import-not-found]
    validate_review_resolution_coverage,
)

# ---------- Helpers ----------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _review_with_findings(round_number: int, finding_ids: list[str]) -> str:
    lines = [
        f"# Code Review Round {round_number:03d}",
        "",
        "## Context",
        "- Task: TASK-001-demo",
        "",
        "## Findings",
    ]
    if not finding_ids:
        lines.append("- (no findings this round)")
    else:
        for fid in finding_ids:
            lines += [
                "",
                f"### {fid} · major · Example issue",
                "- Location: path/to/file.py:42",
                "- Severity: major",
                "- Finding: something is wrong",
            ]
    lines.append("")
    return "\n".join(lines)


def _resolved_with(round_number: int, entries: list[dict]) -> str:
    """entries: list of {id, status, reason?}."""
    lines = [
        f"# Resolved Code Review Round {round_number:03d}",
        "",
        "## Fixes",
    ]
    for e in entries:
        lines += [
            "",
            f"### {e['id']}",
            f"- Status: {e['status']}",
            "- Fix: did the thing",
            "- Evidence: tests/test_x.py::test_y",
        ]
        if "reason" in e:
            lines.append(f"- Waiver-Reason: {e['reason']}")
    lines += [
        "",
        "## Verification",
        "- uv run --with pytest pytest tests -q",
        "",
    ]
    return "\n".join(lines)


def _legacy_review(round_number: int) -> str:
    """Old-format review with no finding ids (for backward-compat)."""
    return "\n".join(
        [
            f"# Code Review Round {round_number:03d}",
            "",
            "## Context",
            "- Task: TASK-001-demo",
            "",
            "## Findings",
            "- Freeform prose finding, no id.",
            "",
        ]
    )


def _legacy_resolved(round_number: int) -> str:
    return "\n".join(
        [
            f"# Resolved Code Review Round {round_number:03d}",
            "",
            "## Fixes",
            "- Closed all findings.",
            "",
            "## Verification",
            "- uv run --with pytest pytest tests -q",
            "",
        ]
    )


# ---------- Tests ----------

def test_missing_finding_id_raises(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001", "finding-002"]),
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(1, [{"id": "finding-001", "status": "resolved"}]),
    )

    with pytest.raises(WorkflowError) as excinfo:
        validate_review_resolution_coverage(review_dir, "code", 1)
    assert "finding-002" in str(excinfo.value)


def test_invalid_status_raises(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001"]),
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(1, [{"id": "finding-001", "status": "partial"}]),
    )

    with pytest.raises(WorkflowError) as excinfo:
        validate_review_resolution_coverage(review_dir, "code", 1)
    message = str(excinfo.value)
    assert "finding-001" in message
    assert "partial" in message


def test_waived_without_reason_raises(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001"]),
    )
    # Waived but no Waiver-Reason line.
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(1, [{"id": "finding-001", "status": "waived"}]),
    )

    with pytest.raises(WorkflowError) as excinfo:
        validate_review_resolution_coverage(review_dir, "code", 1)
    assert "finding-001" in str(excinfo.value)
    assert "waiver" in str(excinfo.value).lower() or "reason" in str(excinfo.value).lower()


def test_waived_with_reason_passes(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001"]),
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(
            1,
            [{"id": "finding-001", "status": "waived", "reason": "out of scope, tracked in FOLLOWUPS"}],
        ),
    )

    # Should NOT raise.
    validate_review_resolution_coverage(review_dir, "code", 1)


def test_all_resolved_passes(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001", "finding-002"]),
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(
            1,
            [
                {"id": "finding-001", "status": "resolved"},
                {"id": "finding-002", "status": "resolved"},
            ],
        ),
    )

    validate_review_resolution_coverage(review_dir, "code", 1)


def test_legacy_review_files_backward_compatible(tmp_path: Path) -> None:
    """Old-format review without any ### finding- headers must keep passing."""
    review_dir = tmp_path / "review"
    _write(review_dir / "code-review-round-001.md", _legacy_review(1))
    _write(review_dir / "code-review-round-001.resolved.md", _legacy_resolved(1))

    # No finding ids => nothing to close. Should NOT raise.
    validate_review_resolution_coverage(review_dir, "code", 1)


def test_non_consecutive_finding_ids_ok_when_all_closed(tmp_path: Path) -> None:
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001", "finding-003"]),  # skip 002
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(
            1,
            [
                {"id": "finding-001", "status": "resolved"},
                {"id": "finding-003", "status": "resolved"},
            ],
        ),
    )

    validate_review_resolution_coverage(review_dir, "code", 1)


def test_init_review_round_emits_finding_schema(tmp_path: Path) -> None:
    """The freshly generated code-review-round-001.md must include
    the new `### finding-001` placeholder and its child lines.

    This locks the template change without requiring end-to-end CLI wiring.
    """
    from scripts.validation import render_template  # type: ignore[attr-defined]

    rendered = render_template(
        "code_review_round.md.tmpl",
        review_label="Code",
        round_number="001",
        task_id="TASK-001-demo",
    )

    assert "### finding-001" in rendered, rendered
    assert "- Location:" in rendered
    assert "- Severity:" in rendered
    assert "- Finding:" in rendered
    # Keep existing required sections for backward compat with existing validator.
    assert "## Context" in rendered
    assert "## Findings" in rendered


def test_resolved_template_documents_new_schema() -> None:
    """The resolved template (reference doc for human authors) must describe
    per-finding Status / Fix / Evidence so reviewers see the contract.
    """
    template_path = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "workflow"
        / "resolved_code_review_round.md.tmpl"
    )
    body = template_path.read_text(encoding="utf-8")
    assert "### finding-" in body
    assert "- Status:" in body
    assert "- Fix:" in body
    assert "- Evidence:" in body
    assert "Waiver-Reason" in body  # documents the waived path


def test_status_value_is_case_insensitive(tmp_path: Path) -> None:
    """`- Status: Resolved` (capitalised) must be accepted: the gate normalizes
    to lower-case to match the rest of the module's enum handling
    (normalize_task_flow, normalize_review_mode, etc.).
    """
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001"]),
    )
    _write(
        review_dir / "code-review-round-001.resolved.md",
        "\n".join(
            [
                "# Resolved Code Review Round 001",
                "",
                "## Fixes",
                "",
                "### finding-001",
                "- Status: Resolved",  # capitalised
                "- Fix: done",
                "- Evidence: pytest",
                "",
                "## Verification",
                "- pytest",
                "",
            ]
        ),
    )

    validate_review_resolution_coverage(review_dir, "code", 1)


def test_asymmetric_finding_id_garbage_rejected_on_both_sides(tmp_path: Path) -> None:
    """Inputs like `### finding-001garbage` must be ignored symmetrically on
    both review and resolved sides — previously the resolved parser had a
    looser regex than the review parser, which produced inconsistent verdicts.
    """
    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        "\n".join(
            [
                "# Code Review Round 001",
                "",
                "## Context",
                "- Task: TASK-001-demo",
                "",
                "## Findings",
                "",
                "### finding-001garbage · major · looks like finding-001 but isn't",
                "- Location: bogus",
                "- Severity: major",
                "- Finding: malformed header should be ignored",
                "",
            ]
        ),
    )
    # Resolved file is empty of finding blocks; if review parser (rightly) sees
    # no declared ids, gate is a no-op and this must not raise.
    _write(
        review_dir / "code-review-round-001.resolved.md",
        "# Resolved Code Review Round 001\n\n## Fixes\n\n## Verification\n- ok\n",
    )

    validate_review_resolution_coverage(review_dir, "code", 1)


def test_integration_gate_bites_at_ensure_review_pair(tmp_path: Path) -> None:
    """Lock the WIRING, not just the helper. Constructs a real review dir
    with mismatched finding ids and calls `ensure_review_pair` — the same
    function `validate_review_requirements` drives at `workflowctl check`
    time. If a future refactor decouples `validate_review_resolution_coverage`
    from `ensure_review_pair`, this test fails before any legacy test does.
    """
    from scripts.validation import ensure_review_pair  # type: ignore[attr-defined,import-not-found]

    review_dir = tmp_path / "review"
    _write(
        review_dir / "code-review-round-001.md",
        _review_with_findings(1, ["finding-001", "finding-002"]),
    )
    # Close only finding-001, leave finding-002 dangling.
    _write(
        review_dir / "code-review-round-001.resolved.md",
        _resolved_with(1, [{"id": "finding-001", "status": "resolved"}]),
    )

    with pytest.raises(WorkflowError) as excinfo:
        ensure_review_pair(review_dir, "code", 1)
    message = str(excinfo.value)
    assert "finding-002" in message
    assert "missing finding id" in message or "missing" in message
