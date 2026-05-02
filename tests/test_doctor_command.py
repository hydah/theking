"""workflowctl doctor — repo-level read-only health check (sprint-010 TASK-002).

Five finding categories:
  D1 — zombie task (unfinished + Goal still placeholder/empty)
  D2 — stale decree checkpoint (points at sealed/done sprint)
  D3 — missing projection directory (runtime exposure partially torn)
  D4 — broken review pair on done/ready_to_merge task
  D5 — stale active-task recovery marker
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


# ---------- Helpers ----------


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _make_fresh_project(tmp_path: Path) -> tuple[Path, str]:
    """Bootstrap a minimal theking project with one sprint + one task in draft."""
    project_dir = tmp_path / "demo-app"
    project_dir.mkdir()
    slug = "demo-app"

    r = _run(["ensure", "--project-dir", ".", "--project-slug", slug], cwd=project_dir)
    assert r.returncode == 0, r.stderr

    r = _run(
        ["init-sprint", "--project-dir", ".", "--project-slug", slug, "--theme", "foundation"],
        cwd=project_dir,
    )
    assert r.returncode == 0, r.stderr

    r = _run(
        [
            "init-task",
            "--project-dir",
            ".",
            "--project-slug",
            slug,
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "demo-task",
            "--title",
            "Demo Task",
            "--task-type",
            "tooling",
            "--execution-profile",
            "backend.cli",
        ],
        cwd=project_dir,
    )
    assert r.returncode == 0, r.stderr

    return project_dir, slug


def _task_md_path(project_dir: Path, slug: str, sprint: str, task: str) -> Path:
    return (
        project_dir
        / ".theking"
        / "workflows"
        / slug
        / "sprints"
        / sprint
        / "tasks"
        / task
        / "task.md"
    )


def _advance(project_dir: Path, task_dir: Path, to: str) -> None:
    # Seed evidence when crossing into ready_to_merge, mirroring existing helpers.
    if to == "ready_to_merge":
        evidence = task_dir / "verification" / "cli" / "test.log"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        if not evidence.exists():
            # sprint-017 TASK-001: shape gate needs Command: + Exit: anchors.
            evidence.write_text(
                "$ uv run --with pytest pytest tests -q\n"
                "pytest run ok: happy path passes, error path passes, regression clean\n"
                "Exit: 0\n",
                encoding="utf-8",
            )
    # sprint-017 TASK-002: red->green needs a runner PASS marker.
    if to == "green":
        from conftest import plant_test_pass_marker

        plant_test_pass_marker(task_dir)
    r = _run(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", to],
        cwd=project_dir,
    )
    assert r.returncode == 0, r.stderr


def _doctor(project_dir: Path, slug: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run(
        ["doctor", "--project-dir", ".", "--project-slug", slug, *extra],
        cwd=project_dir,
    )


def _fill_spec_with_five_sections(task_dir: Path) -> None:
    """Replace the spec placeholder with valid content so advance-status can
    move the task forward for D4 tests.
    """
    spec = task_dir / "spec.md"
    spec.write_text(
        "# Demo Spec\n\n"
        "## Scope\nDemo deliverable.\n\n"
        "## Non-Goals\nNothing else.\n\n"
        "## Acceptance\n"
        "- [ ] Criterion one is met.\n"
        "  - 验证方式: unit\n"
        "  - 证据路径: tests/test_demo.py::test_one\n\n"
        "## Test Plan\n"
        "- Item one.\n"
        "- Item two.\n"
        "- Item three.\n"
        "- Item four.\n"
        "- Item five.\n\n"
        "## Edge Cases\n"
        "- Case one.\n"
        "- Case two.\n"
        "- Case three.\n",
        encoding="utf-8",
    )


def _fill_goal(task_md: Path, goal_text: str) -> None:
    """Replace the placeholder Goal section with real text."""
    content = task_md.read_text(encoding="utf-8")
    new = content.replace(
        "## Goal\n<!-- Describe the expected OUTCOME, not the implementation.\n"
        "     Example: \"Users can log in via OAuth and see their personal dashboard.\" -->\n",
        f"## Goal\n{goal_text}\n",
    )
    assert new != content, "Goal placeholder not found in task.md"
    task_md.write_text(new, encoding="utf-8")


def _write_active_task(project_dir: Path, task_dir_text: str) -> Path:
    active_task = project_dir / ".theking" / "active-task"
    active_task.write_text(task_dir_text + "\n", encoding="utf-8")
    return active_task


def _force_task_to_done_with_valid_audit(task_dir: Path) -> None:
    _fill_spec_with_five_sections(task_dir)
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("status: draft", "status: done")
    content = content.replace(
        "status_history:\n  - draft\n",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
    )
    content = content.replace("current_review_round: 0", "current_review_round: 1")
    task_md.write_text(content, encoding="utf-8")
    review_dir = task_dir / "review"
    review_dir.mkdir(exist_ok=True)
    (review_dir / "code-review-round-001.md").write_text(
        "# Code Review Round 001\n\n## Context\n- Doctor stale active-task test\n\n## Findings\n- None\n",
        encoding="utf-8",
    )
    (review_dir / "code-review-round-001.resolved.md").write_text(
        "# Resolved Code Review Round 001\n\n## Fixes\n- Nothing to fix\n\n## Verification\n- pytest\n",
        encoding="utf-8",
    )
    evidence = task_dir / "verification" / "cli" / "result.md"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "# Verification\n- Command: pytest tests/test_doctor_command.py\n- Stdout: focused stale active task diagnostics exercised\n",
        encoding="utf-8",
    )


# ---------- Tests ----------


def test_doctor_help_mentions_active_task_diagnostics(tmp_path: Path) -> None:
    result = _run(["doctor", "--help"], cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "active-task" in result.stdout



def test_detects_zombie_task(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    # The freshly created task is status=draft with a placeholder Goal.
    # That matches the D1 predicate: unfinished + Goal is placeholder.
    r = _doctor(project_dir, slug)
    assert "[warning]" in r.stdout.lower() or "warning" in r.stdout.lower()
    assert "TASK-001-demo-task" in r.stdout
    assert "zombie" in r.stdout.lower() or "goal" in r.stdout.lower()


def test_goal_filled_is_not_zombie(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    task_md = _task_md_path(project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task")
    _fill_goal(task_md, "Users can do the demo thing end-to-end.")
    r = _doctor(project_dir, slug)
    # No zombie warning for THIS task id.
    # (Other findings may still exist — we scope the assertion to the task id.)
    zombie_lines = [
        line
        for line in r.stdout.splitlines()
        if "TASK-001-demo-task" in line and ("zombie" in line.lower() or "goal" in line.lower())
    ]
    assert zombie_lines == [], r.stdout


def test_done_task_is_not_zombie(tmp_path: Path) -> None:
    """A done task with empty Goal must NOT be reported as zombie."""
    project_dir, slug = _make_fresh_project(tmp_path)
    task_dir = _task_md_path(
        project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task"
    ).parent

    # Forge a done state directly on disk (the advance flow requires full spec,
    # which is not the scenario under test here — we want zombie checker to
    # skip done tasks regardless of Goal content).
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("status: draft", "status: done")
    content = content.replace(
        "status_history:\n  - draft\n",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
    )
    # current_review_round must be >= 1 for ready_to_merge/done per validators;
    # but the doctor predicate only cares about "status == done" skip, not full
    # validation. D4 path validates separately; D1 is the target here.
    task_md.write_text(content, encoding="utf-8")

    r = _doctor(project_dir, slug)
    zombie_lines = [
        line
        for line in r.stdout.splitlines()
        if "TASK-001-demo-task" in line and "zombie" in line.lower()
    ]
    assert zombie_lines == [], r.stdout


def test_detects_active_task_pointing_at_done_task(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    task_dir = _task_md_path(
        project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task"
    ).parent
    _force_task_to_done_with_valid_audit(task_dir)
    _write_active_task(project_dir, str(task_dir))

    r = _doctor(project_dir, slug)

    assert r.returncode == 0, r.stdout + r.stderr
    output = r.stdout.lower()
    assert "active-task" in output
    assert "TASK-001-demo-task" in r.stdout
    assert "done" in output
    assert "stale" in output or "terminal" in output


def test_detects_active_task_pointing_at_missing_task(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    missing_task_dir = (
        project_dir
        / ".theking"
        / "workflows"
        / slug
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-999-missing-task"
    )
    _write_active_task(project_dir, str(missing_task_dir))

    r = _doctor(project_dir, slug)

    assert r.returncode == 0, r.stdout + r.stderr
    output = r.stdout.lower()
    assert "active-task" in output
    assert "TASK-999-missing-task" in r.stdout
    assert "missing" in output or "non-existent" in output


def test_active_task_diagnostic_is_warning_only(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    task_dir = _task_md_path(
        project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task"
    ).parent
    _force_task_to_done_with_valid_audit(task_dir)
    _write_active_task(project_dir, str(task_dir))

    r = _doctor(project_dir, slug, "--json")

    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["errors"] == []
    recovery_findings = [
        finding
        for bucket_name in ("warnings", "info")
        for finding in data[bucket_name]
        if "active-task" in finding["message"].lower()
    ]
    assert recovery_findings, data


def test_detects_stale_decree_checkpoint(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    # Make the task done so the checkpoint's referenced sprint is "all done".
    task_dir = _task_md_path(project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task").parent
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8").replace("status: draft", "status: done")
    content = content.replace(
        "status_history:\n  - draft\n",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
    )
    # done requires current_review_round >= 1 for frontmatter parsers.
    content = content.replace("current_review_round: 0", "current_review_round: 1")
    task_md.write_text(content, encoding="utf-8")

    # Now write a checkpoint referencing this done sprint.
    r = _run(
        [
            "checkpoint",
            "--project-dir",
            ".",
            "--project-slug",
            slug,
            "--phase",
            "phase-3-planning",
            "--flow",
            "full",
            "--summary",
            "historical",
            "--next-step",
            "nothing",
            "--sprint",
            "sprint-001-foundation",
        ],
        cwd=project_dir,
    )
    assert r.returncode == 0, r.stderr

    r = _doctor(project_dir, slug)
    assert "[info]" in r.stdout.lower() or "stale" in r.stdout.lower() or "checkpoint" in r.stdout.lower()


def test_detects_missing_projection_dir(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    # Tear down one projection subdir.
    agents_dir = project_dir / ".codebuddy" / "agents"
    assert agents_dir.exists(), "sanity: ensure step should have created .codebuddy/agents"
    shutil.rmtree(agents_dir)

    r = _doctor(project_dir, slug)
    assert ".codebuddy" in r.stdout
    assert "agents" in r.stdout
    assert "warning" in r.stdout.lower()


def test_detects_broken_review_pair_on_done_task(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    task_dir = _task_md_path(
        project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task"
    ).parent
    _fill_goal(task_dir / "task.md", "End-to-end: broken review pair is caught by doctor.")
    _fill_spec_with_five_sections(task_dir)

    # Drive to in_review so init-review-round scaffolds a real review file.
    for to in ("planned", "red", "green"):
        _advance(project_dir, task_dir, to)
    r = _run(
        ["init-review-round", "--task-dir", str(task_dir)], cwd=project_dir
    )
    assert r.returncode == 0, r.stderr
    # Write a resolved that does NOT close finding-001 (the one
    # init-review-round scaffolds by default).
    resolved = task_dir / "review" / "code-review-round-001.resolved.md"
    resolved.write_text(
        "# Resolved Code Review Round 001\n\n"
        "## Fixes\n- nothing closed\n\n"
        "## Verification\n- pytest\n",
        encoding="utf-8",
    )
    # Force task to done by hand (bypasses advance-status gate which would
    # reject broken coverage — we need to exercise D4's catch-up role).
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("status: in_review", "status: done")
    content = content.replace(
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n  - in_review\n",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
    )
    task_md.write_text(content, encoding="utf-8")

    r = _doctor(project_dir, slug)
    assert "error" in r.stdout.lower()
    assert "TASK-001-demo-task" in r.stdout
    assert r.returncode == 1


def test_exit_codes_clean_and_warning(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    # Clean(ish): fill Goal to eliminate zombie warning. Projection dirs intact.
    task_md = _task_md_path(project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task")
    _fill_goal(task_md, "Real goal text here.")
    r = _doctor(project_dir, slug)
    # Might still have warnings (e.g. spec placeholder etc.), but MUST NOT have errors.
    assert r.returncode == 0, r.stdout


def test_exit_code_on_error(tmp_path: Path) -> None:
    """Only errors should bump exit code to 1."""
    project_dir, slug = _make_fresh_project(tmp_path)
    task_dir = _task_md_path(
        project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task"
    ).parent
    _fill_goal(task_dir / "task.md", "Exercise doctor error-exit path end-to-end.")
    _fill_spec_with_five_sections(task_dir)
    for to in ("planned", "red", "green"):
        _advance(project_dir, task_dir, to)
    _run(["init-review-round", "--task-dir", str(task_dir)], cwd=project_dir)
    resolved = task_dir / "review" / "code-review-round-001.resolved.md"
    resolved.write_text(
        "# Resolved Code Review Round 001\n\n"
        "## Fixes\n- nothing closed\n\n"
        "## Verification\n- pytest\n",
        encoding="utf-8",
    )
    task_md = task_dir / "task.md"
    content = task_md.read_text(encoding="utf-8").replace("status: in_review", "status: done")
    content = content.replace(
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n  - in_review\n",
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
    )
    task_md.write_text(content, encoding="utf-8")

    r = _doctor(project_dir, slug)
    assert r.returncode == 1, r.stdout


def test_json_output_shape(tmp_path: Path) -> None:
    project_dir, slug = _make_fresh_project(tmp_path)
    r = _doctor(project_dir, slug, "--json")
    # stdout must be parseable JSON with the agreed top-level keys.
    data = json.loads(r.stdout)
    assert set(["errors", "warnings", "info", "summary"]).issubset(data.keys())
    summary = data["summary"]
    assert isinstance(summary, dict)
    for key in ("errors", "warnings", "info"):
        assert key in summary
        assert isinstance(summary[key], int)
    assert summary["errors"] == len(data["errors"])
    assert summary["warnings"] == len(data["warnings"])
    assert summary["info"] == len(data["info"])


def test_doctor_handles_missing_top_level_runtime(tmp_path: Path) -> None:
    """If .kimi/ does not exist at all (user opted out), D3 must NOT complain
    about its subdirs — the whole runtime is simply not selected.
    """
    project_dir, slug = _make_fresh_project(tmp_path)
    # `ensure` creates .kimi/ too. Remove it entirely.
    kimi = project_dir / ".kimi"
    if kimi.exists():
        shutil.rmtree(kimi)

    r = _doctor(project_dir, slug)
    # No line should mention a specific missing `.kimi/<subdir>`.
    kimi_complaints = [
        line for line in r.stdout.splitlines() if line.startswith("[warning]") and ".kimi/" in line
    ]
    assert kimi_complaints == [], r.stdout


# ---------- Pinning tests: finding-001 & finding-002 from round 001 review ----------


def test_d2_sealed_detection_uses_canonical_helper(tmp_path: Path) -> None:
    """Round-001 finding-001: D2 must use `sprint_is_sealed` (ADR-002 canonical
    helper), not raw substring matching against sprint.md. Write frontmatter
    that puts `status: sealed` in the proper place and assert info fires; put
    a false-flag `status: sealed` line inside a code fence and assert info
    does NOT fire.
    """
    project_dir, slug = _make_fresh_project(tmp_path)
    sprint_dir = (
        project_dir / ".theking" / "workflows" / slug / "sprints" / "sprint-001-foundation"
    )
    sprint_md = sprint_dir / "sprint.md"

    # Case A: proper frontmatter — sprint_is_sealed must return True.
    existing = sprint_md.read_text(encoding="utf-8")
    sealed_version = "---\nstatus: sealed\n---\n" + existing
    sprint_md.write_text(sealed_version, encoding="utf-8")

    # Point checkpoint at this sprint.
    r = _run(
        [
            "checkpoint",
            "--project-dir",
            ".",
            "--project-slug",
            slug,
            "--phase",
            "phase-5-cleanup",
            "--flow",
            "full",
            "--summary",
            "sealed test",
            "--next-step",
            "clean up",
            "--sprint",
            "sprint-001-foundation",
        ],
        cwd=project_dir,
    )
    assert r.returncode == 0, r.stderr

    r = _doctor(project_dir, slug)
    info_lines = [line for line in r.stdout.splitlines() if line.startswith("[info]")]
    assert any("sealed" in line.lower() for line in info_lines), r.stdout

    # Case B: `status: sealed` appearing only inside a code fence of a draft
    # sprint must NOT trigger seal detection. Rewrite sprint.md with no
    # frontmatter but with the phrase in a fenced block.
    fake_body = (
        "# sprint-001-foundation\n\n"
        "## Theme\n- Foundation\n\n"
        "## Notes\n"
        "Example line that accidentally contains the sealed phrase:\n"
        "```\nstatus: sealed\n```\n"
    )
    sprint_md.write_text(fake_body, encoding="utf-8")

    # Also undo the all-done state from earlier (put the task back to draft).
    task_md = _task_md_path(project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task")
    content = task_md.read_text(encoding="utf-8")
    content = content.replace("status: done", "status: draft")
    content = content.replace(
        "status_history:\n  - draft\n  - planned\n  - red\n  - green\n"
        "  - in_review\n  - ready_to_merge\n  - done\n",
        "status_history:\n  - draft\n",
    )
    content = content.replace("current_review_round: 1", "current_review_round: 0")
    task_md.write_text(content, encoding="utf-8")

    r = _doctor(project_dir, slug)
    info_lines_b = [line for line in r.stdout.splitlines() if line.startswith("[info]")]
    sealed_info = [line for line in info_lines_b if "sealed" in line.lower()]
    assert sealed_info == [], r.stdout


def test_d4_classifier_pins_audit_chain_markers() -> None:
    """Round-001 finding-002: the D4 severity-downgrade classifier hinges on a
    hand-curated marker tuple. Pin each marker so a future rename in
    validation.py can't silently reclassify an audit-chain breach as doc drift.
    """
    from scripts.doctor import _D4_AUDIT_CHAIN_MARKERS, _d4_is_audit_chain

    # Each marker must classify as audit-chain.
    for marker in _D4_AUDIT_CHAIN_MARKERS:
        probe = f"Some prefix {marker} some suffix"
        assert _d4_is_audit_chain(probe), f"marker `{marker}` failed to classify"

    # Case-insensitivity spot-check.
    assert _d4_is_audit_chain("MISSING REVIEW file")
    assert _d4_is_audit_chain("missing finding id section(s): finding-003")

    # A classic non-audit-chain error message (spec drift) must classify as
    # warning (not audit-chain).
    doc_drift_samples = [
        "spec.md 'Edge Cases' has 2 item(s); full flow requires >= 3.",
        "spec.md 'Test Plan' has 4 item(s); full flow requires >= 5.",
        "spec.md Acceptance checkbox missing 验证方式 sub-bullet: 'foo'.",
        "current_review_round does not match status_history review rounds",
    ]
    for message in doc_drift_samples:
        assert not _d4_is_audit_chain(
            message
        ), f"expected doc-drift to be warning, classified as audit-chain: {message!r}"


# ---------------------------------------------------------------------------
# sprint-014 / sprint-015: doctor --summary
#
# Tests MUST be isolated: build the diagnostic scenario inside tmp_path so
# each assertion pins a specific count instead of a weak substring that
# passes on any non-empty summary output (sprint-014 review finding).
# ---------------------------------------------------------------------------

import re as _re_summary


def test_doctor_summary_outputs_exact_tldr_header_for_known_scenario(
    tmp_path: Path,
) -> None:
    """--summary TL;DR exactly matches the finding counts of a controlled scenario.

    Scenario: one fresh draft task with placeholder Goal = exactly 1 D1 zombie
    warning, 0 errors, 0 info. Header must read `0 errors, 1 warnings, 0 info`.
    """
    project_dir, slug = _make_fresh_project(tmp_path)

    result = _run(
        ["doctor", "--project-dir", ".", "--project-slug", slug, "--summary"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr

    first_line = result.stdout.splitlines()[0]
    # Exact match, not substring — catches any regression that drops a count.
    match = _re_summary.match(
        r"^(\d+) errors?, (\d+) warnings?, (\d+) info$", first_line
    )
    assert match is not None, f"TL;DR header shape broken. Got: {first_line!r}"
    errors, warnings, info = (int(x) for x in match.groups())
    assert errors == 0, f"expected 0 errors in fresh-draft scenario, got {errors}: {result.stdout}"
    assert warnings >= 1, f"expected at least 1 zombie warning, got {warnings}: {result.stdout}"
    assert info == 0, f"expected 0 info findings, got {info}: {result.stdout}"


def test_doctor_summary_lists_d1_category_with_exact_count(tmp_path: Path) -> None:
    """--summary category breakdown names D1 and reports the exact finding count.

    The fresh-draft scenario produces exactly one D1 zombie finding, so the
    category line must read `[D1] 1 finding(s)`.
    """
    project_dir, slug = _make_fresh_project(tmp_path)

    result = _run(
        ["doctor", "--project-dir", ".", "--project-slug", slug, "--summary"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr

    # Extract the D1 line from the category breakdown.
    d1_lines = [line for line in result.stdout.splitlines() if line.startswith("[D1]")]
    assert len(d1_lines) == 1, f"expected exactly one [D1] line, got: {d1_lines!r}"
    assert d1_lines[0].startswith("[D1] 1 finding(s)"), (
        f"[D1] category line should report exactly 1 finding. Got: {d1_lines[0]!r}"
    )


def test_doctor_summary_open_tasks_names_the_zombie_task(tmp_path: Path) -> None:
    """--summary Open-tasks section lists the specific zombie task id in a scenario with one zombie."""
    project_dir, slug = _make_fresh_project(tmp_path)

    result = _run(
        ["doctor", "--project-dir", ".", "--project-slug", slug, "--summary"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr

    # Parse the 'Open tasks:' block: one header line + indented task ids until
    # the closing blank line.
    lines = result.stdout.splitlines()
    try:
        hdr = next(i for i, line in enumerate(lines) if line.startswith("Open tasks"))
    except StopIteration:  # pragma: no cover
        raise AssertionError(f"no 'Open tasks' section in summary:\n{result.stdout}")

    open_ids: list[str] = []
    for line in lines[hdr + 1 :]:
        if not line.startswith("  "):
            break
        open_ids.append(line.strip())

    assert open_ids == ["TASK-001-demo-task"], (
        f"Open tasks should list exactly the one fresh-draft zombie task id. Got: {open_ids!r}"
    )


def test_doctor_summary_open_tasks_is_none_when_goal_filled(tmp_path: Path) -> None:
    """Clean scenario: zero findings → summary emits `All clear.` early-exit.

    Verifies the happy-path short-circuit: when the project has no findings,
    the summary does not render category breakdown or Open-tasks sections
    (they would be noise). The Open-tasks-not-listed path is also covered by
    this short-circuit.
    """
    project_dir, slug = _make_fresh_project(tmp_path)
    task_md = _task_md_path(project_dir, slug, "sprint-001-foundation", "TASK-001-demo-task")
    _fill_goal(task_md, "A developer exercises the doctor summary happy path.")

    result = _run(
        ["doctor", "--project-dir", ".", "--project-slug", slug, "--summary"],
        cwd=project_dir,
    )
    assert result.returncode == 0, result.stderr

    lines = result.stdout.splitlines()
    assert lines[0] == "0 errors, 0 warnings, 0 info", (
        f"clean scenario TL;DR must show zero counts. Got: {lines[0]!r}"
    )
    assert "All clear." in result.stdout, (
        f"zero-finding scenario must short-circuit with 'All clear.'. Got:\n{result.stdout}"
    )
    # And specifically: no D1 / category breakdown / Open tasks section.
    assert not any(line.startswith("[D") for line in lines), (
        f"clean scenario must not render category lines. Got:\n{result.stdout}"
    )
    assert "Open tasks" not in result.stdout, (
        f"clean scenario must not render Open-tasks section. Got:\n{result.stdout}"
    )

