from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from conftest import populate_task_goal
from scripts.sessions import read_ledger
from scripts.validation import parse_frontmatter


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def bootstrap_sprint(tmp_path: Path) -> None:
    project = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    sprint = run_cli(
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
    assert project.returncode == 0, project.stderr
    assert sprint.returncode == 0, sprint.stderr


def init_task(tmp_path: Path, *, slug: str) -> Path:
    result = run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            slug,
            "--title",
            slug.title(),
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    task_dir = (
        tmp_path
        / "demo-app"
        / ".theking"
        / "workflows"
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{slug}"
    )
    populate_task_goal(task_dir / "task.md")
    return task_dir


def set_flow(task_md: Path, flow_value: str | None) -> None:
    text = task_md.read_text(encoding="utf-8")
    text = re.sub(r"^flow:\s*\S+\s*\n", "", text, flags=re.MULTILINE)
    if flow_value is None:
        task_md.write_text(text, encoding="utf-8")
        return
    text = re.sub(
        r"^(task_type:)",
        f"flow: {flow_value}\n\\1",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    task_md.write_text(text, encoding="utf-8")


def advance_to_planned(tmp_path: Path, task_dir: Path) -> subprocess.CompletedProcess[str]:
    return run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"], cwd=tmp_path)


def test_planned_transition_records_locked_flow(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="mixed-flow")
    set_flow(task_dir / "task.md", "LightWeight")

    result = advance_to_planned(tmp_path, task_dir)

    assert result.returncode == 0, result.stderr
    transitions = [entry for entry in read_ledger(task_dir) if entry.get("type") == "transition"]
    assert transitions
    assert transitions[-1]["to_status"] == "planned"
    assert transitions[-1]["flow"] == "lightweight"


def test_planned_task_flow_change_without_retriage_is_rejected(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="silent-flow-edit")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr

    set_flow(task_dir / "task.md", "lightweight")
    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "flow" in result.stderr.lower()
    assert "full" in result.stderr
    assert "lightweight" in result.stderr
    assert "workflowctl retriage" in result.stderr


def test_retriage_resets_to_draft_and_records_ledger(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="retriage-task")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr

    result = run_cli(
        [
            "retriage",
            "--task-dir",
            str(task_dir),
            "--to-flow",
            "lightweight",
            "--reason",
            "wrong initial triage",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_data = parse_frontmatter((task_dir / "task.md").read_text(encoding="utf-8"))
    assert task_data["status"] == "draft"
    assert task_data["status_history"] == ["draft"]
    assert task_data["flow"] == "lightweight"

    ledger = read_ledger(task_dir)
    retriage_entries = [entry for entry in ledger if entry.get("type") == "retriage"]
    assert retriage_entries
    assert retriage_entries[-1]["from_flow"] == "full"
    assert retriage_entries[-1]["to_flow"] == "lightweight"
    assert retriage_entries[-1]["reason"] == "wrong initial triage"

    check = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert check.returncode == 0, check.stderr

    planned_again = advance_to_planned(tmp_path, task_dir)
    assert planned_again.returncode == 0, planned_again.stderr
    transition_entries = [entry for entry in read_ledger(task_dir) if entry.get("type") == "transition"]
    assert transition_entries[-1]["flow"] == "lightweight"


def test_retriage_invalidates_previous_planned_flow_lock(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="retriage-invalidates-lock")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr
    retriage = run_cli(
        [
            "retriage",
            "--task-dir",
            str(task_dir),
            "--to-flow",
            "lightweight",
            "--reason",
            "wrong initial triage",
        ],
        cwd=tmp_path,
    )
    assert retriage.returncode == 0, retriage.stderr

    task_md = task_dir / "task.md"
    text = task_md.read_text(encoding="utf-8")
    text = text.replace("status: draft", "status: planned")
    text = text.replace("status_history:\n  - draft", "status_history:\n  - draft\n  - planned")
    task_md.write_text(text, encoding="utf-8")
    set_flow(task_md, None)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "retriage" in result.stderr.lower()
    assert "advance-status" in result.stderr


def test_retriage_rejects_empty_reason_without_mutating_task(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="empty-reason")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr
    before_task = (task_dir / "task.md").read_text(encoding="utf-8")
    before_ledger = (task_dir / "ledger.jsonl").read_text(encoding="utf-8")

    result = run_cli(
        ["retriage", "--task-dir", str(task_dir), "--to-flow", "lightweight", "--reason", "   "],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "reason" in result.stderr.lower()
    assert (task_dir / "task.md").read_text(encoding="utf-8") == before_task
    assert (task_dir / "ledger.jsonl").read_text(encoding="utf-8") == before_ledger


def test_retriage_rejects_same_flow_without_mutating_task(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="same-flow")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr
    before_task = (task_dir / "task.md").read_text(encoding="utf-8")
    before_ledger = (task_dir / "ledger.jsonl").read_text(encoding="utf-8")

    result = run_cli(
        [
            "retriage",
            "--task-dir",
            str(task_dir),
            "--to-flow",
            "full",
            "--reason",
            "same flow should not reset status",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "differ" in result.stderr.lower()
    assert (task_dir / "task.md").read_text(encoding="utf-8") == before_task
    assert (task_dir / "ledger.jsonl").read_text(encoding="utf-8") == before_ledger


def test_retriage_rejects_draft_task(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="draft-retriage")

    result = run_cli(
        [
            "retriage",
            "--task-dir",
            str(task_dir),
            "--to-flow",
            "lightweight",
            "--reason",
            "not planned yet",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "planned" in result.stderr.lower()


def test_retriage_rejects_task_with_review_round(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="reviewed-retriage")
    planned = advance_to_planned(tmp_path, task_dir)
    assert planned.returncode == 0, planned.stderr
    task_md = task_dir / "task.md"
    text = task_md.read_text(encoding="utf-8")
    text = text.replace("status: planned", "status: in_review")
    text = text.replace(
        "status_history:\n  - draft\n  - planned",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n  - in_review",
    )
    text = text.replace("current_review_round: 0", "current_review_round: 1")
    task_md.write_text(text, encoding="utf-8")

    result = run_cli(
        [
            "retriage",
            "--task-dir",
            str(task_dir),
            "--to-flow",
            "lightweight",
            "--reason",
            "too late",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "review" in result.stderr.lower()


def test_legacy_planned_default_flow_without_lock_still_passes(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="legacy-default")
    task_md = task_dir / "task.md"
    text = task_md.read_text(encoding="utf-8")
    text = text.replace("status: draft", "status: planned")
    text = text.replace("status_history:\n  - draft", "status_history:\n  - draft\n  - planned")
    task_md.write_text(text, encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_planned_non_default_flow_without_lock_is_rejected(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    task_dir = init_task(tmp_path, slug="legacy-non-default")
    task_md = task_dir / "task.md"
    text = task_md.read_text(encoding="utf-8")
    text = text.replace("status: draft", "status: planned")
    text = text.replace("status_history:\n  - draft", "status_history:\n  - draft\n  - planned")
    task_md.write_text(text, encoding="utf-8")
    set_flow(task_md, "lightweight")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "flow" in result.stderr.lower()
    assert "retriage" in result.stderr.lower()
