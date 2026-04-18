"""End-to-end tests for `workflowctl sprint-smoke`.

These tests cover ADR-003 闸 3: a sprint cannot be sealed unless every
execution_profile used by its tasks has substantive evidence under
`sprint_dir/verification/<profile-dir>/`. This is the sprint-level
counterpart to the task-level smoke gate from sprint-004 TASK-001.

Implementation lives in:

- ``scripts/validation.py::validate_sprint_smoke_evidence``
- ``scripts/workflowctl.py::handle_sprint_smoke`` (subcommand)
- ``scripts/workflowctl.py::handle_seal_sprint`` (pre-check wire-up)

The tests here are RED at authoring time — none of the above symbols
exist yet in the repo. They will go green with the TASK-003 implementation.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"
SKILL_MD = (
    Path(__file__).resolve().parents[1]
    / ".theking"
    / "skills"
    / "workflow-governance"
    / "SKILL.md"
)


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _bootstrap_sprint(
    tmp_path: Path,
    *,
    task_types: list[tuple[str, str]] | None = None,
) -> Path:
    """Create a demo project + sprint-001-foundation populated with one
    or more tasks. ``task_types`` is a list of (slug, task_type) tuples
    defaulting to one backend.cli task.

    Returns the sprint directory under the project's workflow tree.
    """

    specs = task_types or [("task-a", "general")]
    run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    run_cli(
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
    plan = {
        "tasks": [
            {"slug": slug, "title": f"Task {slug}", "task_type": task_type}
            for slug, task_type in specs
        ],
    }
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    run_cli(
        [
            "init-sprint-plan",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--plan-file",
            str(plan_file),
        ],
        cwd=tmp_path,
    )
    return (
        tmp_path
        / "demo-app"
        / ".theking"
        / "workflows"
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
    )


def _substantive_evidence() -> str:
    """Return a block of text that passes ``has_substantive_verification_
    evidence``'s 40-substantive-char floor with room to spare."""

    return (
        "# Smoke\n"
        "- Command: workflowctl sprint-smoke --sprint-dir <X>\n"
        "- Stdout: OK sprint-level smoke for sprint-001-foundation\n"
        "- Exit: 0\n"
    )


# --- sprint-smoke command ---------------------------------------------------


def test_sprint_smoke_passes_when_all_profiles_have_substantive_evidence(
    tmp_path: Path,
) -> None:
    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general"), ("task-b", "general")],
    )
    write_text(sprint_dir / "verification" / "cli" / "smoke.md", _substantive_evidence())

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"Expected sprint-smoke to pass when evidence exists. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_sprint_smoke_fails_when_profile_evidence_missing(tmp_path: Path) -> None:
    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    # No sprint-level evidence dir at all — must fail.

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to fail on missing evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "cli" in result.stderr or "backend.cli" in result.stderr, (
        f"Error should name the missing profile. stderr={result.stderr!r}"
    )


def test_sprint_smoke_fails_when_profile_evidence_is_placeholder(
    tmp_path: Path,
) -> None:
    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    # Only placeholder content — must fail via substantive-evidence gate.
    write_text(
        sprint_dir / "verification" / "cli" / "smoke.md",
        "<!-- TODO: run smoke later -->\n",
    )

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to fail on placeholder evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        f"Error should name the placeholder/substantive cause. "
        f"stderr={result.stderr!r}"
    )


def test_sprint_smoke_fails_when_sprint_has_no_tasks(tmp_path: Path) -> None:
    """Edge case: sprint with no TASK-* directories — nothing to smoke.

    Absence of tasks means absence of evidence scope; sprint-smoke
    should reject rather than silently pass on a placeholder sprint.
    """

    run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    run_cli(
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
    sprint_dir = (
        tmp_path
        / "demo-app"
        / ".theking"
        / "workflows"
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
    )
    # tasks/ dir exists but empty (no TASK-* children).
    (sprint_dir / "tasks").mkdir(exist_ok=True)

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to fail on empty sprint. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "no tasks" in stderr_lower or "nothing" in stderr_lower, (
        f"Error should indicate empty sprint. stderr={result.stderr!r}"
    )


# --- SKILL.md content guards -----------------------------------------------


def test_skill_md_contains_hard_rule_9() -> None:
    """SKILL.md 硬规则 list must contain a 9th numbered rule about
    runnable evidence, falling under ⛔ 硬规则 section."""

    content = SKILL_MD.read_text(encoding="utf-8")
    # Locate the 硬规则 block.
    assert "## ⛔ 硬规则" in content, (
        "SKILL.md must have the ⛔ 硬规则 section header"
    )
    # Rule #9 should exist.
    rule_9 = re.search(r"^9\.\s+\*\*.+?\*\*", content, flags=re.MULTILINE)
    assert rule_9 is not None, (
        "SKILL.md 硬规则 list must include a 9th bullet starting with "
        "`9. **...**`. Actual content near the section:\n"
        + content[content.find("## ⛔ 硬规则"):content.find("## ⛔ 硬规则") + 2000]
    )
    # The rule should be about runnable / smoke / 启动 evidence.
    rule_line = rule_9.group(0)
    # Read a broader slice to include the body until the next rule/section.
    rule_block_match = re.search(
        r"^9\.\s+.*?(?=^(?:\d+\.\s|\#\#\s)|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert rule_block_match is not None
    rule_block = rule_block_match.group(0)
    assert any(
        keyword in rule_block
        for keyword in ("启动", "runnable", "冷启动", "smoke", "sprint-smoke")
    ), f"Rule #9 should mention runnable/smoke evidence. Got:\n{rule_block}"
    # And must point at落地 phase.
    assert "Phase 4" in rule_block or "Phase 5" in rule_block, (
        f"Rule #9 must name a Phase landing point. Got:\n{rule_block}"
    )


def test_skill_md_phase_references_updated() -> None:
    """Phase 4 步骤 5 should reference the substantive-evidence gate
    (or `workflowctl check`); Phase 5 步骤 2-3 should reference
    `sprint-smoke`."""

    content = SKILL_MD.read_text(encoding="utf-8")

    # Phase 4 step 5: the "亲勘实证" header is bolded as `**5. 亲勘实证 ...**`.
    phase4_step5_marker = re.search(
        r"\*\*5\.\s*亲勘实证",
        content,
    )
    assert phase4_step5_marker is not None, (
        "Phase 4 step 5 '亲勘实证' header must still exist"
    )
    # Slice a reasonable window around step 5 to check its body.
    p4_idx = phase4_step5_marker.start()
    phase4_step5_body = content[p4_idx : p4_idx + 1500]
    assert (
        "substantive" in phase4_step5_body.lower()
        or "workflowctl check" in phase4_step5_body
        or "has_substantive_verification_evidence" in phase4_step5_body
    ), (
        "Phase 4 step 5 must reference the substantive-evidence gate "
        "enforced by `workflowctl check`. Got:\n" + phase4_step5_body
    )

    # Phase 5 step 2 or 3 should reference sprint-smoke.
    phase5_marker = content.find("Phase 5:")
    assert phase5_marker >= 0, "Phase 5 header must still exist"
    phase5_body = content[phase5_marker:]
    assert "sprint-smoke" in phase5_body, (
        "Phase 5 body must reference `sprint-smoke` (step 2 or 3). "
        f"Phase 5 slice (first 2000 chars):\n{phase5_body[:2000]}"
    )


def test_skill_md_command_index_includes_sprint_smoke() -> None:
    """The workflowctl command index table in SKILL.md must list
    `sprint-smoke`."""

    content = SKILL_MD.read_text(encoding="utf-8")
    # The index header is "📋 workflowctl 命令索引".
    idx = content.find("workflowctl 命令索引")
    assert idx >= 0, "Command index section must exist"
    index_slice = content[idx : idx + 2000]
    assert "sprint-smoke" in index_slice, (
        "Command index must include a `sprint-smoke` row. Got:\n"
        + index_slice
    )


# --- Round-001 follow-up: HIGH-1 / HIGH-2 / MEDIUM / LOW guards --------------


def test_sprint_smoke_rejects_symlinked_task_dir(tmp_path: Path) -> None:
    """HIGH-1: symlinked TASK-* dirs must be rejected by sprint-smoke, not
    silently skipped. Otherwise a symlinked task whose execution_profile
    differs from its real counterpart would let the corresponding profile
    evidence requirement slip through.
    """

    import os

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    write_text(sprint_dir / "verification" / "cli" / "smoke.md", _substantive_evidence())

    # Create an out-of-tree target task dir and symlink it into the sprint.
    outside_task = tmp_path / "outside-task"
    outside_task.mkdir(parents=True)
    (outside_task / "task.md").write_text(
        "---\n"
        "id: TASK-002-evil\n"
        "title: Evil\n"
        "status: draft\n"
        "status_history:\n  - draft\n"
        "task_type: api\n"
        "execution_profile: backend.http\n"
        "verification_profile:\n  - backend.http\n"
        "requires_security_review: true\n"
        "required_agents:\n  - planner\n  - tdd-guide\n  - code-reviewer\n"
        "  - security-reviewer\n"
        "depends_on:\n"
        "current_review_round: 0\n"
        "---\n",
        encoding="utf-8",
    )
    os.symlink(outside_task, sprint_dir / "tasks" / "TASK-002-evil")

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to reject symlinked TASK dir. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "symlink" in result.stderr.lower(), (
        f"Error should mention symlink. stderr={result.stderr!r}"
    )


def test_sprint_smoke_rejects_symlinked_evidence_tree(tmp_path: Path) -> None:
    """HIGH-2: a symlink under `verification/<profile>/` that points at
    a directory full of long text must NOT count as substantive evidence.
    Previously `rglob` would traverse the symlink and count every file
    under it, letting an attacker borrow e.g. /usr/share/doc to satisfy
    the 40-char floor.
    """

    import os

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    # Build a directory tree outside sprint_dir that is chock full of
    # substantive text.
    outside_docs = tmp_path / "bootleg-docs"
    outside_docs.mkdir(parents=True)
    (outside_docs / "long.md").write_text(
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Integer nec odio. Praesent libero. Sed cursus ante dapibus diam.\n",
        encoding="utf-8",
    )
    # Symlink it into the sprint evidence dir, with NO real UTF-8 file
    # adjacent — the only content comes via the symlink.
    profile_dir = sprint_dir / "verification" / "cli"
    profile_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(outside_docs, profile_dir / "linked-evidence")

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to reject symlink-borrowed evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "symlink" in stderr_lower or "substantive" in stderr_lower, (
        f"Error should name symlink or substantive cause. "
        f"stderr={result.stderr!r}"
    )


def test_sprint_smoke_rejects_sprint_without_tasks_dir(tmp_path: Path) -> None:
    """MEDIUM: the `tasks/` dir-missing branch must also fail cleanly.
    Use a real theking-layout sprint (so `validate_sprint_location`
    passes) but delete its `tasks/` subdir to exercise the
    `validate_sprint_smoke_evidence` branch specifically.
    """

    import shutil as _shutil

    # Start with a well-formed sprint via _bootstrap_sprint so path
    # location validation passes, then blow away the tasks/ dir.
    sprint_dir = _bootstrap_sprint(tmp_path, task_types=[("task-a", "general")])
    _shutil.rmtree(sprint_dir / "tasks")

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to fail when tasks/ dir missing. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "no tasks" in stderr_lower or "nothing" in stderr_lower, (
        f"Error should indicate the missing tasks/ dir. "
        f"stderr={result.stderr!r}"
    )


def test_sprint_smoke_rejects_non_theking_layout(tmp_path: Path) -> None:
    """MEDIUM: `sprint-smoke` should validate the sprint path is within
    `.theking/workflows/<project>/sprints/` — same discipline as
    `sprint-check`. Otherwise users can run it on a non-theking layout
    and get misleading OK / error wording.
    """

    fake_sprint = tmp_path / "fake-sprint"
    fake_sprint.mkdir(parents=True)
    (fake_sprint / "sprint.md").write_text("# Fake\n", encoding="utf-8")
    (fake_sprint / "tasks").mkdir()

    result = run_cli(["sprint-smoke", "--sprint-dir", str(fake_sprint)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected sprint-smoke to reject non-theking sprint layout. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (
        ".theking/workflows" in result.stderr
        or "sprint_dir must live under" in result.stderr
    ), f"Error should name the layout rule. stderr={result.stderr!r}"


def test_skill_md_phase_5_slice_contains_sprint_smoke() -> None:
    """MEDIUM drift guard: the original `test_skill_md_phase_references_
    updated` used `content[phase5_marker:]` which stretches to the end
    of the file; `sprint-smoke` might only appear in the command-index
    table (far below Phase 5). This test binds sprint-smoke to the
    Phase 5 body specifically, not the whole tail.
    """

    content = SKILL_MD.read_text(encoding="utf-8")

    # Phase 5 header is `### 🏛️ Phase 5:`
    phase5_start = content.find("Phase 5:")
    assert phase5_start >= 0
    # Bound: next major section is either `---\n` separator or the
    # `## 🔁 Sprint 收尾后的回补` heading.
    search_from = phase5_start + 1
    candidates = [
        content.find("\n---\n", search_from),
        content.find("## 🔁", search_from),
        content.find("\n## ", search_from),
    ]
    phase5_end = min(c for c in candidates if c >= 0)
    phase5_body = content[phase5_start:phase5_end]

    assert "sprint-smoke" in phase5_body, (
        "Phase 5 body (bounded, not tail-of-file) must mention `sprint-smoke`. "
        f"Phase 5 slice:\n{phase5_body[:3000]}"
    )


def test_skill_md_hard_rule_9_names_load_bearing_keywords() -> None:
    """LOW drift guard: narrow the hard-rule-9 content assertion from
    "any of {启动, runnable, 冷启动, smoke, sprint-smoke}" to the
    load-bearing subset that guarantees the rule is still about the
    evidence gate, not drift to some unrelated "启动流程" topic.
    """

    content = SKILL_MD.read_text(encoding="utf-8")
    rule_block_match = re.search(
        r"^9\.\s+.*?(?=^(?:\d+\.\s|\#\#\s)|\Z)",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert rule_block_match is not None
    rule_block = rule_block_match.group(0)

    # Must be load-bearing: at least one of the following strings that
    # pins the rule to the actual enforcement surface.
    load_bearing_keywords = (
        "sprint-smoke",
        "has_substantive_verification_evidence",
        "冷启动真实跑通",
    )
    hits = [kw for kw in load_bearing_keywords if kw in rule_block]
    assert hits, (
        "Rule #9 must anchor on one of the load-bearing keywords "
        f"{load_bearing_keywords}. Got:\n{rule_block}"
    )


# --- Single-task sprint verification merge (sprint-007 TASK-002) ----------


def test_single_task_sprint_passes_with_task_level_evidence(
    tmp_path: Path,
) -> None:
    """Single-task sprint should pass sprint-smoke when only task-level
    verification/<profile>/ has substantive evidence — no sprint-level
    evidence dir required."""

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    # Write evidence only at task level, NOT at sprint level
    task_dir = sorted((sprint_dir / "tasks").iterdir())[0]
    write_text(
        task_dir / "verification" / "cli" / "smoke.md",
        _substantive_evidence(),
    )

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"Single-task sprint should pass with task-level evidence only. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_single_task_sprint_fails_without_any_evidence(
    tmp_path: Path,
) -> None:
    """Single-task sprint should fail when neither task-level nor
    sprint-level evidence exists."""

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    # No evidence anywhere

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Single-task sprint should fail without any evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_single_task_sprint_fails_with_placeholder_task_evidence(
    tmp_path: Path,
) -> None:
    """Single-task sprint should fail when task-level evidence is
    placeholder-only (< 40 substantive chars)."""

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general")],
    )
    task_dir = sorted((sprint_dir / "tasks").iterdir())[0]
    write_text(
        task_dir / "verification" / "cli" / "smoke.md",
        "<!-- TODO: fill later -->\n",
    )

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Single-task sprint should fail with placeholder evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_multi_task_sprint_does_not_use_single_task_fallback(
    tmp_path: Path,
) -> None:
    """2-task sprint should NOT fall back to task-level evidence.
    Even if all tasks have task-level evidence, sprint-level is required."""

    sprint_dir = _bootstrap_sprint(
        tmp_path,
        task_types=[("task-a", "general"), ("task-b", "general")],
    )
    # Write evidence at task level for both tasks
    for task_dir in sorted((sprint_dir / "tasks").iterdir()):
        write_text(
            task_dir / "verification" / "cli" / "smoke.md",
            _substantive_evidence(),
        )
    # No sprint-level evidence

    result = run_cli(["sprint-smoke", "--sprint-dir", str(sprint_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Multi-task sprint should fail without sprint-level evidence. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

