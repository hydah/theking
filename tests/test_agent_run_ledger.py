from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from scaffold import build_runtime_template_vars  # noqa: E402
from validation import render_template  # noqa: E402


def render_workflow_skill() -> str:
    return render_template(
        "skill_workflow_governance.md.tmpl",
        **build_runtime_template_vars("demo-app"),
    )


def test_workflow_skill_documents_agent_run_ledger_as_audit_aid() -> None:
    text = render_workflow_skill()
    assert "agent-runs.jsonl" in text, "Workflow skill must document the task-level agent run ledger"

    ledger_idx = text.find("agent-runs.jsonl")
    ledger_slice = text[max(0, ledger_idx - 800) : ledger_idx + 1600]
    lower_slice = ledger_slice.lower()

    for field in (
        "timestamp",
        "agent",
        "purpose",
        "input_artifact",
        "output_artifact",
        "status",
        "notes",
    ):
        assert field in ledger_slice, f"Ledger docs must name required field `{field}`. Slice:\n{ledger_slice}"

    assert "audit" in lower_slice or "审计" in ledger_slice, (
        "Ledger docs should describe agent-runs.jsonl as audit metadata/aid. "
        f"Slice:\n{ledger_slice}"
    )
    assert (
        "not proof" in lower_slice
        or "not a proof" in lower_slice
        or "不是证明" in ledger_slice
        or "不能证明" in ledger_slice
        or "非证明" in ledger_slice
    ), (
        "Ledger docs must explicitly say the ledger is not proof of agent execution. "
        f"Slice:\n{ledger_slice}"
    )
