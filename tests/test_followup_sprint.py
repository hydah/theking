"""End-to-end tests for `workflowctl followup-sprint`.

Per ADR-002 (sprint-003): a followup sprint is a normal new sprint with
two extra audit traces — a `## Follow-up Source` section in its sprint.md
pointing back at the originating sprint, and an append-only entry in
`<source-sprint>/followups.md`. Works whether or not the source is sealed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def set_task_status(task_md: Path, *, status: str, history: list[str], current_review_round: int) -> None:
    content = task_md.read_text(encoding="utf-8")
    history_block = "\n".join(f"  - {entry}" for entry in history)
    content = re.sub(
        r"status: \S+\nstatus_history:\n(?:  - .*\n)+",
        f"status: {status}\nstatus_history:\n{history_block}\n",
        content,
        count=1,
    )
    content = re.sub(
        r"current_review_round: \d+",
        f"current_review_round: {current_review_round}",
        content,
        count=1,
    )
    task_md.write_text(content, encoding="utf-8")


def force_task_to_done(task_dir: Path) -> None:
    set_task_status(
        task_dir / "task.md",
        status="done",
        history=["draft", "planned", "red", "green", "in_review", "ready_to_merge", "done"],
        current_review_round=1,
    )
    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Task Spec",
                "", "## Scope", "- forged", "",
                "## Non-Goals", "- forged", "",
                "## Acceptance", "- forged", "",
                "## Test Plan",
                "- one", "- two", "- three", "- four", "- five", "",
                "## Edge Cases", "- a", "- b", "- c",
            ]
        ),
        encoding="utf-8",
    )
    review_dir = task_dir / "review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "code-review-round-001.md").write_text(
        "# Code Review Round 001\n\n## Context\n- forged\n\n## Findings\n- none\n",
        encoding="utf-8",
    )
    (review_dir / "code-review-round-001.resolved.md").write_text(
        "# Resolved Code Review Round 001\n\n## Fixes\n- forged\n\n## Verification\n- forged\n",
        encoding="utf-8",
    )
    verification_dir = task_dir / "verification" / "cli"
    verification_dir.mkdir(parents=True, exist_ok=True)
    # Must carry >= 40 substantive chars to pass ADR-003 闸 1 gate.
    (verification_dir / "result.md").write_text(
        "# Verification\n"
        "- Command: forged pytest run for followup sprint tests\n"
        "- Stdout: OK all transitions accounted for, exit=0\n",
        encoding="utf-8",
    )
    # Sprint-level smoke evidence (ADR-003 闸 3): without this,
    # seal-sprint's sprint-smoke pre-check would refuse sealing.
    sprint_dir = task_dir.parent.parent
    sprint_verification = sprint_dir / "verification" / "cli" / "smoke.md"
    sprint_verification.parent.mkdir(parents=True, exist_ok=True)
    sprint_verification.write_text(
        "# Sprint-level smoke (forged for followup-sprint tests)\n"
        "- Command: workflowctl sprint-smoke --sprint-dir <X>\n"
        "- Stdout: OK followup source sprint\n",
        encoding="utf-8",
    )


def bootstrap_source_sprint(tmp_path: Path) -> Path:
    run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    plan = {"tasks": [{"slug": "task-a", "title": "Task A", "task_type": "general"}]}
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    run_cli(
        [
            "init-sprint-plan",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--plan-file", str(plan_file),
        ],
        cwd=tmp_path,
    )
    return workflow_root(tmp_path) / "sprints" / "sprint-001-foundation"


def test_followup_sprint_creates_new_sprint_with_back_link(tmp_path: Path) -> None:
    source_sprint = bootstrap_source_sprint(tmp_path)

    result = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(source_sprint),
            "--new-theme", "edge-case-fixes",
            "--reason", "Caught a missed edge case in the validation gate.",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    new_sprint = workflow_root(tmp_path) / "sprints" / "sprint-002-edge-case-fixes"
    assert new_sprint.is_dir(), "followup-sprint must mint sprint-002-edge-case-fixes"

    new_sprint_md = (new_sprint / "sprint.md").read_text(encoding="utf-8")
    assert "## Follow-up Source" in new_sprint_md
    assert "sprint-001-foundation" in new_sprint_md
    assert "Caught a missed edge case" in new_sprint_md

    followups_md = source_sprint / "followups.md"
    assert followups_md.is_file(), "source sprint must gain followups.md"
    followups_text = followups_md.read_text(encoding="utf-8")
    assert followups_text.startswith("# "), "followups.md must lead with a markdown title"
    assert "sprint-002-edge-case-fixes" in followups_text
    assert "Caught a missed edge case" in followups_text


def test_followup_sprint_works_against_sealed_source(tmp_path: Path) -> None:
    source_sprint = bootstrap_source_sprint(tmp_path)
    force_task_to_done(source_sprint / "tasks" / "TASK-001-task-a")
    seal = run_cli(["seal-sprint", "--sprint-dir", str(source_sprint)], cwd=tmp_path)
    assert seal.returncode == 0, seal.stderr

    sprint_md_before_followup = (source_sprint / "sprint.md").read_text(encoding="utf-8")

    result = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(source_sprint),
            "--new-theme", "post-seal-fix",
            "--reason", "Found a leftover after sealing.",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    # Sealed sprint.md must NOT be modified by followup-sprint.
    sprint_md_after_followup = (source_sprint / "sprint.md").read_text(encoding="utf-8")
    assert sprint_md_before_followup == sprint_md_after_followup, (
        "followup-sprint must not modify a sealed source sprint.md"
    )
    # followups.md is metadata; appending to it on a sealed sprint is allowed.
    assert (source_sprint / "followups.md").is_file()


def test_followup_sprint_appends_multiple_entries_without_overwrite(tmp_path: Path) -> None:
    source_sprint = bootstrap_source_sprint(tmp_path)

    first = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(source_sprint),
            "--new-theme", "first-followup",
            "--reason", "First followup reason.",
        ],
        cwd=tmp_path,
    )
    second = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(source_sprint),
            "--new-theme", "second-followup",
            "--reason", "Second followup reason.",
        ],
        cwd=tmp_path,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    followups_text = (source_sprint / "followups.md").read_text(encoding="utf-8")
    assert "sprint-002-first-followup" in followups_text
    assert "sprint-003-second-followup" in followups_text
    assert "First followup reason." in followups_text
    assert "Second followup reason." in followups_text
    # Order check: first entry must appear before second (append-only).
    assert followups_text.index("first-followup") < followups_text.index("second-followup")


def test_followup_sprint_normalizes_multiline_reason(tmp_path: Path) -> None:
    source_sprint = bootstrap_source_sprint(tmp_path)

    result = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(source_sprint),
            "--new-theme", "multiline-reason",
            "--reason", "Line one.\nLine two.\nLine three.",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    followups_text = (source_sprint / "followups.md").read_text(encoding="utf-8")
    # Each followups.md entry occupies a single line — the reason must be
    # collapsed to one line so the bullet list stays flat.
    bullet_lines = [
        line for line in followups_text.splitlines()
        if line.startswith("- ") and "multiline-reason" in line
    ]
    assert len(bullet_lines) == 1
    assert "\n" not in bullet_lines[0]
    # The multi-line reason must be folded but content preserved (with spaces
    # joining the original line breaks).
    assert "Line one." in bullet_lines[0]
    assert "Line two." in bullet_lines[0]
    assert "Line three." in bullet_lines[0]


def test_followup_sprint_rejects_nonexistent_source(tmp_path: Path) -> None:
    bootstrap_source_sprint(tmp_path)
    fake_source = workflow_root(tmp_path) / "sprints" / "sprint-099-does-not-exist"

    result = run_cli(
        [
            "followup-sprint",
            "--project-dir", str(tmp_path / "demo-app"),
            "--project-slug", "demo-app",
            "--source-sprint", str(fake_source),
            "--new-theme", "phantom",
            "--reason", "Should fail.",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "sprint" in result.stderr.lower()
