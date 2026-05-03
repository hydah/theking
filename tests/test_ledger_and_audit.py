"""sprint-019 TASK-005: append-only action ledger + workflowctl audit.

Every state transition writes a JSON line to `<task_dir>/ledger.jsonl`
with a `prev_hash` field that chains to the previous entry. The
`workflowctl audit` subcommand reads the ledger and verifies:
 (a) planned→red transitions have a git_head whose commit diff is
     tests-only (complements sprint-019 TASK-003 runtime gate with a
     retrospective audit);
 (b) timestamps are monotonically non-decreasing;
 (c) chain-hash links are unbroken.

Legacy tasks without ledger.jsonl silent-pass. Audit is advisory by
default and opt-in strict via `--strict`.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from sessions import (  # noqa: E402
    append_ledger_entry,
    compute_entry_hash,
    read_ledger,
)

WORKFLOWCTL = REPO_ROOT / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKFLOWCTL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# unit: append_ledger_entry / read_ledger / compute_entry_hash
# ---------------------------------------------------------------------------


def test_append_ledger_entry_creates_file_with_required_fields(tmp_path: Path) -> None:
    entry = append_ledger_entry(tmp_path, {"type": "activate"})
    ledger = tmp_path / "ledger.jsonl"
    assert ledger.exists()
    assert "timestamp" in entry and entry["timestamp"].endswith("Z")
    assert "prev_hash" in entry
    assert "git_head" in entry
    assert entry["type"] == "activate"


def test_first_entry_prev_hash_is_genesis(tmp_path: Path) -> None:
    entry = append_ledger_entry(tmp_path, {"type": "activate"})
    assert entry["prev_hash"] == "genesis"


def test_chain_hash_links_entries(tmp_path: Path) -> None:
    first = append_ledger_entry(tmp_path, {"type": "activate"})
    second = append_ledger_entry(tmp_path, {"type": "transition", "from_status": "draft", "to_status": "planned"})
    expected_prev = compute_entry_hash(first)
    assert second["prev_hash"] == expected_prev


def test_read_ledger_round_trips(tmp_path: Path) -> None:
    append_ledger_entry(tmp_path, {"type": "activate"})
    append_ledger_entry(tmp_path, {"type": "transition", "from_status": "draft", "to_status": "planned"})
    entries = read_ledger(tmp_path)
    assert len(entries) == 2
    assert entries[0]["type"] == "activate"
    assert entries[1]["type"] == "transition"


def test_compute_entry_hash_deterministic() -> None:
    entry = {
        "timestamp": "2026-05-02T22:00:00Z",
        "type": "activate",
        "git_head": "abc123",
        "prev_hash": "SHOULD_BE_EXCLUDED_FROM_HASH",
    }
    # Mutating prev_hash must not change the computed hash — prev_hash
    # is an output of compute_entry_hash, not an input.
    h1 = compute_entry_hash(entry)
    mutated = {**entry, "prev_hash": "different"}
    h2 = compute_entry_hash(mutated)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


def test_read_ledger_handles_missing_file(tmp_path: Path) -> None:
    """Legacy task without ledger.jsonl must not crash read_ledger."""
    entries = read_ledger(tmp_path)
    assert entries == []


def test_read_ledger_reports_malformed_line(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text('{"type":"activate","timestamp":"2026-05-02T22:00:00Z","prev_hash":"genesis","git_head":"x"}\n'
                     'not-json\n', encoding="utf-8")
    entries = read_ledger(tmp_path)
    assert len(entries) == 2
    assert entries[0]["type"] == "activate"
    assert "_error" in entries[1]


# ---------------------------------------------------------------------------
# integration: transition handlers write ledger entries
# ---------------------------------------------------------------------------


def _bootstrap_new_task(tmp_path: Path) -> Path:
    r1 = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    assert r1.returncode == 0, r1.stderr
    r2 = run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    assert r2.returncode == 0, r2.stderr
    r3 = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", "ledger-demo",
            "--title", "Ledger Demo",
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert r3.returncode == 0, r3.stderr
    return (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation"
        / "tasks" / "TASK-001-ledger-demo"
    )


def test_activate_writes_ledger_entry(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    r = run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    entries = read_ledger(task_dir)
    assert any(e.get("type") == "activate" for e in entries), entries


def test_advance_status_writes_ledger_entry(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    from conftest import populate_task_goal

    populate_task_goal(task_dir / "task.md")
    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    r = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr

    entries = read_ledger(task_dir)
    transitions = [e for e in entries if e.get("type") == "transition"]
    assert transitions, f"no transition entries in ledger; got {entries}"
    planned_entry = [e for e in transitions if e.get("to_status") == "planned"]
    assert planned_entry
    assert planned_entry[0].get("from_status") == "draft"


def test_init_review_round_writes_ledger_entry(tmp_path: Path) -> None:
    """Fast-forward a task to green and trigger init-review-round, then
    check the ledger entry includes round_number."""
    task_dir = _bootstrap_new_task(tmp_path)
    from conftest import (
        plant_test_pass_marker,
        populate_handoff_anchor,
        populate_task_goal,
    )

    populate_task_goal(task_dir / "task.md")
    # Full-flow spec with 5 sections + 5-item test plan + 3 edge cases
    (task_dir / "spec.md").write_text(
        "# Spec\n\n## Scope\n- s\n\n## Non-Goals\n- n\n\n"
        "## Acceptance\n- [ ] a\n  - 验证方式: unit\n  - 证据路径: tests/test.py::test_a\n\n"
        "## Test Plan\n- a\n- b\n- c\n- d\n- e\n\n"
        "## Edge Cases\n- x\n- y\n- z\n",
        encoding="utf-8",
    )
    populate_handoff_anchor(task_dir)
    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    for to in ("planned", "red"):
        r = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", to], cwd=tmp_path)
        assert r.returncode == 0, r.stderr
    plant_test_pass_marker(task_dir)
    r = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "green"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    r = run_cli(["init-review-round", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr

    entries = read_ledger(task_dir)
    review_events = [e for e in entries if e.get("type") == "init_review_round"]
    assert review_events
    assert review_events[0].get("round_number") == 1


# ---------------------------------------------------------------------------
# integration: ledger subcommand
# ---------------------------------------------------------------------------


def test_ledger_subcommand_prints_entries(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    run_cli(["activate", "--task-dir", str(task_dir)], cwd=tmp_path)
    r = run_cli(["ledger", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "activate" in r.stdout


def test_ledger_subcommand_tail(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    for _ in range(3):
        append_ledger_entry(task_dir, {"type": "activate"})
    r = run_cli(["ledger", "--task-dir", str(task_dir), "--tail", "2"], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    # Crude: 3 entries total, --tail 2 → 2 lines of event rendering
    assert r.stdout.count("activate") == 2, r.stdout


def test_ledger_subcommand_legacy_task_prints_empty(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    # Don't write any ledger entries.
    r = run_cli(["ledger", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "no ledger entries" in r.stdout.lower() or r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# integration: audit subcommand
# ---------------------------------------------------------------------------


def test_audit_clean_case(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    for event in (
        {"type": "activate"},
        {"type": "transition", "from_status": "draft", "to_status": "planned"},
        {"type": "transition", "from_status": "planned", "to_status": "red"},
    ):
        append_ledger_entry(task_dir, event)
    r = run_cli(["audit", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert re.search(r"(?i)ledger clean|no findings|0 findings", r.stdout), r.stdout


def test_audit_legacy_task_silent(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)
    # No ledger entries written — legacy task path.
    r = run_cli(["audit", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert re.search(r"(?i)no ledger|nothing to verify|empty", r.stdout), r.stdout


def test_audit_strict_rejects_new_task_without_ledger_entries(tmp_path: Path) -> None:
    task_dir = _bootstrap_new_task(tmp_path)

    result = run_cli(["audit", "--task-dir", str(task_dir), "--strict"], cwd=tmp_path)

    assert result.returncode != 0, result.stdout
    combined_output = result.stdout + result.stderr
    assert re.search(r"(?i)strict", combined_output), combined_output
    assert re.search(r"(?i)no ledger|ledger entries|empty", combined_output), combined_output


def test_audit_strict_detects_chain_break(tmp_path: Path) -> None:
    """Manually corrupt ledger.jsonl by rewriting a prev_hash. Audit
    strict must exit non-zero."""
    task_dir = _bootstrap_new_task(tmp_path)
    append_ledger_entry(task_dir, {"type": "activate"})
    append_ledger_entry(task_dir, {"type": "transition", "from_status": "draft", "to_status": "planned"})

    # Corrupt the second entry's prev_hash
    ledger = task_dir / "ledger.jsonl"
    lines = ledger.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["prev_hash"] = "deadbeef" * 8
    lines[1] = json.dumps(entry)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

    r_advisory = run_cli(["audit", "--task-dir", str(task_dir)], cwd=tmp_path)
    # Default advisory: exit 0, but findings printed
    assert r_advisory.returncode == 0, r_advisory.stderr
    assert re.search(r"(?i)chain|hash", r_advisory.stdout), r_advisory.stdout

    r_strict = run_cli(["audit", "--task-dir", str(task_dir), "--strict"], cwd=tmp_path)
    assert r_strict.returncode != 0, r_strict.stderr


def test_audit_detects_non_monotonic_timestamps(tmp_path: Path) -> None:
    """Write two entries with reversed timestamps by hand; audit must flag."""
    task_dir = _bootstrap_new_task(tmp_path)
    ledger = task_dir / "ledger.jsonl"
    e1 = {"timestamp": "2026-05-02T22:00:00Z", "type": "activate", "prev_hash": "genesis", "git_head": "x"}
    # Chain correctly but timestamp regresses
    h1 = compute_entry_hash(e1)
    e2 = {"timestamp": "2026-05-02T21:59:00Z", "type": "activate", "prev_hash": h1, "git_head": "x"}
    ledger.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")

    r = run_cli(["audit", "--task-dir", str(task_dir), "--strict"], cwd=tmp_path)
    assert r.returncode != 0, r.stderr
    assert re.search(r"(?i)monoton|timestamp", r.stdout + r.stderr), (r.stdout, r.stderr)
