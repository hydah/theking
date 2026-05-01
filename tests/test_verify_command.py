"""Red-phase tests for `workflowctl verify` MVP (sprint-013 TASK-002).

Covers the 5 acceptance scenarios in
.theking/workflows/theking/sprints/sprint-013-main-agent-offloading-p0/
tasks/TASK-002-workflowctl-verify-command/spec.md :

    1. Fresh evidence section written
    2. Repeated same-section call appends under ## heading (not a new ##)
    3. Wrapped command failure -> status=command_failed, verify exit 0
    4. agent-runs.jsonl gains one valid line per call
    5. verify_error is atomic (bad profile -> no writes)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def bootstrap_task(tmp_path: Path, slug: str = "verify-target") -> Path:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    assert init_project.returncode == 0, init_project.stderr
    init_sprint = run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    assert init_sprint.returncode == 0, init_sprint.stderr
    init_task = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", slug,
            "--title", slug.title(),
            "--task-type", "general",
            "--execution-profile", "backend.cli",
        ],
        cwd=tmp_path,
    )
    assert init_task.returncode == 0, init_task.stderr
    return (
        workflow_root(tmp_path)
        / "sprints" / "sprint-001-foundation"
        / "tasks" / f"TASK-001-{slug}"
    )


# ---------------------------------------------------------------------------
# Acceptance 1: fresh evidence section
# ---------------------------------------------------------------------------


def test_verify_writes_fresh_evidence_section(tmp_path: Path) -> None:
    task_dir = bootstrap_task(tmp_path)
    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "backend.cli",
            "--command", "echo hello",
            "--evidence-section", "smoke",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"verify failed: {result.stderr!r}"

    # JSON summary on stdout.
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] in {"ok", "ok_under_threshold"}, summary
    assert summary["exit"] == 0
    assert summary["section"] == "smoke"

    evidence = task_dir / "verification" / "cli" / "evidence.md"
    assert evidence.is_file(), "verify must create verification/cli/evidence.md"
    text = evidence.read_text(encoding="utf-8")
    assert "## smoke" in text, f"Fresh section header missing: {text!r}"
    assert "$ echo hello" in text
    assert "hello" in text
    assert "exit: 0" in text


# ---------------------------------------------------------------------------
# Acceptance 2: repeated call appends under same section
# ---------------------------------------------------------------------------


def test_verify_appends_under_existing_section(tmp_path: Path) -> None:
    task_dir = bootstrap_task(tmp_path)
    for _ in range(2):
        result = run_cli(
            [
                "verify",
                "--task-dir", str(task_dir),
                "--profile", "backend.cli",
                "--command", "echo run",
                "--evidence-section", "smoke",
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr

    text = (task_dir / "verification" / "cli" / "evidence.md").read_text(encoding="utf-8")
    # Exactly one top-level '## smoke' — subsequent runs go under '### run'.
    assert text.count("\n## smoke") + (1 if text.startswith("## smoke") else 0) == 1, (
        f"Second call must not create a new '## smoke' header. Got:\n{text}"
    )
    # At least one '### run ' sub-heading from the repeat call.
    assert "### run " in text, f"Missing '### run <iso8601>' sub-heading. Got:\n{text}"


# ---------------------------------------------------------------------------
# Acceptance 3: wrapped command failure does not propagate
# ---------------------------------------------------------------------------


def test_verify_command_failed_does_not_propagate(tmp_path: Path) -> None:
    task_dir = bootstrap_task(tmp_path)
    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "backend.cli",
            "--command", "sh -c 'echo oops >&2; exit 42'",
            "--evidence-section", "failing-step",
        ],
        cwd=tmp_path,
    )
    # verify itself succeeds (evidence was recorded).
    assert result.returncode == 0, (
        f"verify must exit 0 even when the wrapped command fails. "
        f"stderr={result.stderr!r}"
    )
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] == "command_failed", summary
    assert summary["exit"] == 42, summary

    evidence = (task_dir / "verification" / "cli" / "evidence.md").read_text(encoding="utf-8")
    assert "exit: 42" in evidence
    assert "oops" in evidence


# ---------------------------------------------------------------------------
# Acceptance 4: agent-runs.jsonl gains one valid line per call
# ---------------------------------------------------------------------------


def test_verify_appends_valid_ledger_line(tmp_path: Path) -> None:
    task_dir = bootstrap_task(tmp_path)
    ledger = task_dir / "agent-runs.jsonl"
    assert ledger.exists(), "bootstrap scaffold must include agent-runs.jsonl"
    baseline_lines = ledger.read_text(encoding="utf-8").count("\n")

    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "backend.cli",
            "--command", "echo ledger",
            "--evidence-section", "ledger-check",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    content = ledger.read_text(encoding="utf-8")
    new_lines = content.count("\n")
    assert new_lines == baseline_lines + 1, (
        f"Expected exactly one new ledger line. baseline={baseline_lines} new={new_lines}"
    )
    last = content.strip().splitlines()[-1]
    payload = json.loads(last)

    required_fields = {
        "timestamp", "agent", "purpose",
        "input_artifact", "output_artifact", "status", "notes",
    }
    assert required_fields <= set(payload), f"Ledger line missing fields: {payload}"
    assert payload["agent"] == "workflowctl-verify"
    assert payload["status"] in {"command_ok", "command_failed"}
    assert "ledger-check" in payload["purpose"] or "ledger-check" in payload["output_artifact"]

    # Independently validate via the project's own validator so verify's output is
    # guaranteed forward-compatible with validate_agent_runs_ledger.
    from validation import validate_agent_runs_ledger
    validate_agent_runs_ledger(ledger)


# ---------------------------------------------------------------------------
# Acceptance 5: verify_error is atomic
# ---------------------------------------------------------------------------


def test_verify_error_is_atomic(tmp_path: Path) -> None:
    task_dir = bootstrap_task(tmp_path)
    evidence_dir = task_dir / "verification" / "cli"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence = evidence_dir / "evidence.md"
    evidence.write_text("# pre-existing content\n", encoding="utf-8")
    pre_evidence = evidence.read_text(encoding="utf-8")

    ledger = task_dir / "agent-runs.jsonl"
    pre_ledger = ledger.read_text(encoding="utf-8")

    # Unknown profile -> verify_error.
    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "made-up-profile",
            "--command", "echo should-not-run",
            "--evidence-section", "nope",
        ],
        cwd=tmp_path,
    )
    assert result.returncode != 0, (
        f"verify must exit non-zero on verify_error. stdout={result.stdout!r}"
    )

    # No write on either artifact.
    assert evidence.read_text(encoding="utf-8") == pre_evidence, "evidence.md must not change on verify_error"
    assert ledger.read_text(encoding="utf-8") == pre_ledger, "agent-runs.jsonl must not change on verify_error"

    # Also: the unrelated "nope" profile dir must not have been created.
    assert not (task_dir / "verification" / "made-up-profile").exists()


# ---------------------------------------------------------------------------
# Round-001 finding-001: timeout writes status=command_failed (not command_timeout)
# ---------------------------------------------------------------------------


def test_verify_timeout_writes_command_failed_status(tmp_path: Path) -> None:
    """Per spec §Scope, the ledger `status` field is `{command_ok,
    command_failed}`. A timeout must fold into `command_failed`; timeout
    signal survives via exit=124 in `notes` and the '[workflowctl verify]
    command exceeded --timeout Ns' trailer in evidence.md."""
    task_dir = bootstrap_task(tmp_path)
    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "backend.cli",
            "--command", "sleep 5",
            "--evidence-section", "slow-step",
            "--timeout", "1",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"verify must exit 0 even on timeout: {result.stderr!r}"

    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] == "command_failed", (
        f"Summary status on timeout must be command_failed, got: {summary}"
    )
    assert summary["exit"] == 124, summary

    ledger = task_dir / "agent-runs.jsonl"
    last = ledger.read_text(encoding="utf-8").strip().splitlines()[-1]
    payload = json.loads(last)
    assert payload["status"] == "command_failed", (
        f"Ledger status on timeout must match spec enum (command_failed); "
        f"got {payload['status']!r}"
    )
    assert "exit=124" in payload["notes"]

    evidence = (task_dir / "verification" / "cli" / "evidence.md").read_text(encoding="utf-8")
    assert "exit: 124" in evidence
    assert "exceeded --timeout" in evidence or "timeout" in evidence.lower()


def test_verify_appends_to_legacy_free_form_evidence(tmp_path: Path) -> None:
    """Round-001 untested-paths observation: spec Edge Case §2 requires
    appending at EOF without rewriting when the existing evidence.md has
    free-form fenced blocks but no '## <section>' heading."""
    task_dir = bootstrap_task(tmp_path)
    evidence_dir = task_dir / "verification" / "cli"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    legacy = evidence_dir / "evidence.md"
    legacy_text = (
        "# Some legacy evidence\n\n"
        "```shell\n"
        "$ go test ./...\n"
        "ok pkg/foo\n"
        "```\n"
    )
    legacy.write_text(legacy_text, encoding="utf-8")

    result = run_cli(
        [
            "verify",
            "--task-dir", str(task_dir),
            "--profile", "backend.cli",
            "--command", "echo new",
            "--evidence-section", "added-later",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    text = legacy.read_text(encoding="utf-8")
    # Legacy prelude preserved verbatim.
    assert text.startswith(legacy_text), "Legacy content must be preserved verbatim at the start"
    # New section appended.
    assert "## added-later" in text
    assert "$ echo new" in text
