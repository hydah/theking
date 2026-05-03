from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_PATH = REPO_ROOT / ".theking" / "context" / "adr" / "ADR-007-governance-provenance-contract.md"


def read_adr_007() -> str:
    assert ADR_PATH.is_file(), (
        "ADR-007 governance provenance contract must exist at "
        ".theking/context/adr/ADR-007-governance-provenance-contract.md"
    )
    return ADR_PATH.read_text(encoding="utf-8")


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def test_adr_007_exists_and_classifies_hard_rules() -> None:
    text = read_adr_007()
    normalized = normalize(text)

    for section in (
        "## Context",
        "## Decision",
        "## Consequences",
        "## Alternatives Considered",
        "## Status",
    ):
        assert section in text

    assert "accepted" in normalized
    assert "hard rule" in normalized
    assert "machine-gated" in normalized or "machine gate" in normalized
    assert "audit-trailed" in normalized or "audit trail" in normalized
    assert "advisory" in normalized
    assert "hard rules must be machine-gated, audit-trailed, or advisory" in normalized


def test_adr_007_documents_legacy_sealed_sprint_policy() -> None:
    normalized = normalize(read_adr_007())

    assert "legacy" in normalized
    assert "sealed" in normalized
    assert "historical sealed sprints" in normalized or "historical sprints" in normalized
    assert "must not be edited" in normalized or "without editing historical sprint artifacts" in normalized
    assert "not retroactively reinterpreted as unsealed" in normalized
    assert "remain readable" in normalized or "legacy compatibility" in normalized


def test_adr_007_defines_new_task_provenance_contract() -> None:
    normalized = normalize(read_adr_007())

    assert "new tasks" in normalized
    assert "theking_schema_version" in normalized
    assert "agent-runs.jsonl" in normalized
    assert "audit facts" in normalized
    assert "not cryptographic proof" in normalized
    assert "without true subagent support" in normalized
    assert "degraded" in normalized
    assert "review independence" in normalized
    assert "source identity" in normalized
    assert "static gate" in normalized
    assert "workflowctl check" in normalized or "red-check" in normalized


def test_adr_007_is_not_ignored_by_gitignore() -> None:
    read_adr_007()
    relative_path = ADR_PATH.relative_to(REPO_ROOT)

    result = subprocess.run(
        ["git", "check-ignore", "--quiet", str(relative_path)],
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 1, f"{relative_path} must be deliverable, not gitignored"
