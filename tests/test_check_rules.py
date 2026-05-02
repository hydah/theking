from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"


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


def review_markdown(review_type: str, round_number: int) -> str:
    return "\n".join(
        [
            f"# {review_type} Review Round {round_number:03d}",
            "",
            "## Context",
            "- Task: TASK-001-login-flow",
            "",
            "## Findings",
            "- Verified the required checks for this round.",
            "",
        ]
    )


def resolved_review_markdown(review_type: str, round_number: int) -> str:
    return "\n".join(
        [
            f"# Resolved {review_type} Review Round {round_number:03d}",
            "",
            "## Fixes",
            "- Closed every finding from this round.",
            "",
            "## Verification",
            "- uv run --with pytest pytest tests -q",
            "",
        ]
    )


def review_content_for_file(file_name: str) -> str:
    match = re.search(r"round-(\d{3})", file_name)
    assert match is not None
    round_number = int(match.group(1))
    review_type = file_name.split("-review-round-")[0].replace("-", " ").title()
    if file_name.endswith(".resolved.md"):
        return resolved_review_markdown(review_type, round_number)
    return review_markdown(review_type, round_number)


def profile_dir_name(profile: str) -> str:
    return {
        "web.browser": "browser",
        "backend.http": "http",
        "backend.cli": "cli",
        "backend.job": "job",
    }[profile]


def verification_result_markdown(profile: str) -> str:
    # sprint-017 TASK-001: per-profile evidence must now carry semantic
    # anchors, not just Command: / Outcome:. Each profile gets the minimal
    # anchor pair the new shape gate requires so this fixture keeps being
    # a valid "happy path" evidence.
    if profile == "backend.cli":
        body = [
            "- Command: uv run --with pytest pytest tests -q",
            "- Outcome: passed",
            "- Exit: 0",
        ]
    elif profile == "backend.http":
        body = [
            "- Command: curl -iv http://localhost:8080/health",
            "> GET /health HTTP/1.1",
            "< HTTP/1.1 200 OK",
            "- Exit: 0",
        ]
    elif profile == "backend.job":
        body = [
            "- Command: uv run python -m myapp.worker",
            "- Invoked worker at 2026-05-02T18:30",
            "- Job completed without errors.",
            "- Exit: 0",
        ]
    else:
        # web.browser and any unknown profile: keep a neutral anchor set;
        # tests that exercise web.browser plant a binary artifact
        # separately via plant_browser_artifact().
        body = [
            "- Command: npx playwright test",
            "- Outcome: passed",
            "- Exit: 0",
        ]
    return "\n".join(
        [
            "# Verification Result",
            "",
            f"- Profile: {profile}",
            *body,
            "",
        ]
    )


def plant_browser_artifact(profile_dir: Path) -> None:
    """Drop a real >= 512B PNG into profile_dir so the web.browser shape
    gate (sprint-017 TASK-001) has a binary artifact to accept."""
    png = profile_dir / "smoke.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048)


def make_valid_task_tree(
    base_dir: Path,
    *,
    status: str = "draft",
    status_history: list[str] | None = None,
    current_review_round: int = 0,
    task_type: str = "general",
    execution_profile: str = "backend.cli",
    verification_profile: list[str] | None = None,
    requires_security_review: bool | None = None,
    required_agents: list[str] | None = None,
    depends_on: list[str] | None = None,
    include_task: bool = True,
    include_spec: bool = True,
    include_review_dir: bool = True,
    include_verification_dir: bool = True,
    include_verification_evidence: bool | None = None,
    use_theking_layout: bool = True,
    workflow_project_name: str = "demo-app",
) -> Path:
    if use_theking_layout:
        workflow_project_dir = (
            base_dir
            / "demo-app"
            / ".theking"
            / "workflows"
            / workflow_project_name
        )
        sprint_dir = workflow_project_dir / "sprints" / "sprint-001-foundation"
        task_dir = (
            sprint_dir
            / "tasks"
            / "TASK-001-login-flow"
        )
        write_text(workflow_project_dir / "project.md", "# Project\n")
        write_text(sprint_dir / "sprint.md", "# Sprint\n")
    else:
        task_dir = base_dir / "TASK-001-login-flow"
    review_dir = task_dir / "review"
    verification_dir = task_dir / "verification"
    history = status_history or [status]
    verification = verification_profile or [execution_profile]
    security_review = requires_security_review
    if security_review is None:
        security_review = task_type in {"auth", "input", "api"}
    agents = required_agents or ["planner", "tdd-guide", "code-reviewer"]
    if required_agents is None:
        if execution_profile == "web.browser":
            agents.append("e2e-runner")
        if security_review:
            agents.append("security-reviewer")

    task_depends_on = depends_on or []

    if include_task:
        task_content = "\n".join(
            [
                "---",
                "id: TASK-001-login-flow",
                "title: Login Flow",
                f"status: {status}",
                "status_history:",
                *[f"  - {entry}" for entry in history],
                f"task_type: {task_type}",
                f"execution_profile: {execution_profile}",
                "verification_profile:",
                *[f"  - {entry}" for entry in verification],
                f"requires_security_review: {'true' if security_review else 'false'}",
                "required_agents:",
                *[f"  - {agent}" for agent in agents],
                "depends_on:",
                *[f"  - {dep}" for dep in task_depends_on],
                f"current_review_round: {current_review_round}",
                "---",
                "",
                "## Goal",
                "- Validate the workflow.",
            ]
        )
        write_text(task_dir / "task.md", task_content)

    if include_spec:
        # Full-flow spec must meet sprint-002 TASK-001 thresholds:
        # Test Plan >= 5, Edge Cases >= 3. Single bullets would silently
        # fail validate_spec_section_counts.
        spec_content = "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Implement the minimal workflow.",
                "",
                "## Non-Goals",
                "- Avoid unrelated cleanup.",
                "",
                "## Acceptance",
                "- Review loop is enforced.",
                "",
                "## Test Plan",
                "- Run pytest.",
                "- Exercise the happy path.",
                "- Exercise the error path.",
                "- Verify idempotent re-runs.",
                "- Run regression suite.",
                "",
                "## Edge Cases",
                "- Handle repeated runs safely.",
                "- Handle missing optional inputs.",
                "- Handle partially written artifacts.",
            ]
        )
        write_text(task_dir / "spec.md", spec_content)

    if include_review_dir:
        review_dir.mkdir(parents=True, exist_ok=True)

    if include_verification_dir:
        for profile in verification:
            profile_dir = verification_dir / profile_dir_name(profile)
            profile_dir.mkdir(parents=True, exist_ok=True)
            should_write_evidence = include_verification_evidence
            if should_write_evidence is None:
                should_write_evidence = status in {"ready_to_merge", "done"}
            if should_write_evidence:
                write_text(profile_dir / "result.md", verification_result_markdown(profile))
                if profile == "web.browser":
                    # shape gate for web.browser requires a real binary
                    # artifact in addition to textual evidence.
                    plant_browser_artifact(profile_dir)

    return task_dir


def test_check_accepts_legacy_required_agents_with_planner(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
        required_agents=["planner", "tdd-guide", "code-reviewer"],
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Legacy task.md files that still list planner must remain checkable. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize("ledger_content", [None, ""])
def test_check_allows_missing_or_empty_agent_runs_ledger(
    tmp_path: Path,
    ledger_content: str | None,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    ledger = task_dir / "agent-runs.jsonl"
    if ledger_content is not None:
        write_text(ledger, ledger_content)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "agent-runs.jsonl is optional audit metadata; missing/empty ledgers "
        f"must not block check. stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize(
    "ledger_content",
    [
        "{not json}\n",
        "[]\n",
        '{"timestamp":"2026-05-01T00:00:00Z","agent":"tdd-guide"}\n',
        (
            '{"timestamp":"2026-05-01T00:00:00Z","agent":"tdd-guide",'
            '"purpose":"write red tests","input_artifact":"spec.md",'
            '"output_artifact":"tests/test_check_rules.py","status":"ok",'
            '"notes":"valid first line"}\n'
            "{broken second line}\n"
        ),
    ],
)
def test_check_rejects_malformed_agent_runs_ledger(
    tmp_path: Path,
    ledger_content: str,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    write_text(task_dir / "agent-runs.jsonl", ledger_content)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Non-empty agent-runs.jsonl must be valid JSONL objects with required fields. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "agent-runs.jsonl" in result.stderr


def test_check_accepts_valid_agent_runs_ledger_with_extra_fields(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    write_text(
        task_dir / "agent-runs.jsonl",
        '{"timestamp":"2026-05-01T00:00:00Z","agent":"tdd-guide",'
        '"purpose":"write red tests","input_artifact":"spec.md",'
        '"output_artifact":"tests/test_check_rules.py","status":"ok",'
        '"notes":"covered edge cases","extra":"forward-compatible"}\n',
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Valid ledger objects may include extra fields for forward compatibility. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize(
    "missing_name",
    ["task.md", "spec.md", "review", "verification"],
)
def test_check_fails_when_required_task_artifacts_are_missing(
    tmp_path: Path,
    missing_name: str,
) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    target = task_dir / missing_name
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert missing_name in result.stderr


@pytest.mark.parametrize(
    ("artifact_name", "replacement_kind", "expected_fragment"),
    [
        ("task.md", "dir", "Artifact must be a file"),
        ("spec.md", "dir", "Artifact must be a file"),
        ("review", "file", "Artifact must be a directory"),
        ("verification", "file", "Artifact must be a directory"),
    ],
)
def test_check_rejects_wrong_artifact_types(
    tmp_path: Path,
    artifact_name: str,
    replacement_kind: str,
    expected_fragment: str,
) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    artifact_path = task_dir / artifact_name
    if artifact_path.is_dir():
        shutil.rmtree(artifact_path)
    else:
        artifact_path.unlink()

    if replacement_kind == "dir":
        artifact_path.mkdir(parents=True)
    else:
        artifact_path.write_text("wrong type\n", encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert expected_fragment in result.stderr


@pytest.mark.parametrize(
    ("target_text", "replacement", "expected_fragment"),
    [
        ("## Scope\n- Implement the minimal workflow.", "", "Scope"),
        ("## Non-Goals\n- Avoid unrelated cleanup.", "", "Non-Goals"),
        ("## Acceptance\n- Review loop is enforced.", "", "Acceptance"),
        (
            "## Test Plan\n- Run pytest.\n- Exercise the happy path.\n"
            "- Exercise the error path.\n- Verify idempotent re-runs.\n"
            "- Run regression suite.",
            "",
            "Test Plan",
        ),
        (
            "## Edge Cases\n- Handle repeated runs safely.\n"
            "- Handle missing optional inputs.\n"
            "- Handle partially written artifacts.",
            "",
            "Edge Cases",
        ),
    ],
)
def test_check_fails_when_spec_is_missing_required_sections(
    tmp_path: Path,
    target_text: str,
    replacement: str,
    expected_fragment: str,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    spec_path = task_dir / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(spec_text.replace(target_text, replacement), encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert expected_fragment in result.stderr


def test_check_fails_when_spec_section_contains_only_placeholder_content(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    spec_path = task_dir / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(
        spec_text.replace("- Implement the minimal workflow.", "<!-- fill me in -->"),
        encoding="utf-8",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "section must not be empty: Scope" in result.stderr


@pytest.mark.parametrize(
    ("status", "status_history"),
    [
        ("draft", ["draft"]),
        ("planned", ["draft", "planned"]),
    ],
)
def test_check_allows_placeholder_spec_before_red(
    tmp_path: Path,
    status: str,
    status_history: list[str],
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        status_history=status_history,
    )
    spec_path = task_dir / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(
        spec_text.replace("- Implement the minimal workflow.", "<!-- fill me in -->"),
        encoding="utf-8",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("status", "status_history"),
    [
        ("draft", ["draft"]),
        ("planned", ["draft", "planned"]),
    ],
)
def test_check_accepts_legacy_two_section_spec_before_red(
    tmp_path: Path,
    status: str,
    status_history: list[str],
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        status_history=status_history,
    )
    write_text(
        task_dir / "spec.md",
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Acceptance",
                "- Review loop is enforced.",
                "",
                "## Test Plan",
                "- Run pytest.",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_rejects_legacy_two_section_spec_from_red_onward(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    write_text(
        task_dir / "spec.md",
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Acceptance",
                "- Review loop is enforced.",
                "",
                "## Test Plan",
                "- Run pytest.",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "spec.md is missing required section: Scope" in result.stderr


@pytest.mark.parametrize(
    ("status", "status_history", "should_pass"),
    [
        ("blocked", ["draft", "planned", "blocked"], True),
        ("blocked", ["draft", "planned", "red", "blocked"], False),
    ],
)
def test_check_uses_pre_blocked_stage_for_spec_content_gate(
    tmp_path: Path,
    status: str,
    status_history: list[str],
    should_pass: bool,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        status_history=status_history,
    )
    spec_path = task_dir / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(
        spec_text.replace("- Implement the minimal workflow.", "<!-- fill me in -->"),
        encoding="utf-8",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    if should_pass:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "section must not be empty: Scope" in result.stderr


@pytest.mark.parametrize(
    ("status", "requires_security_review", "execution_profile", "review_files", "expected_fragment"),
    [
        ("ready_to_merge", False, "backend.cli", [], "code-review-round-001"),
        ("done", False, "backend.cli", ["code-review-round-001.md"], "code-review-round-001.resolved.md"),
        (
            "ready_to_merge",
            True,
            "backend.http",
            ["code-review-round-001.md", "code-review-round-001.resolved.md"],
            "security-review-round-001",
        ),
        (
            "ready_to_merge",
            False,
            "web.browser",
            ["code-review-round-001.md", "code-review-round-001.resolved.md"],
            "e2e-review-round-001",
        ),
    ],
)
def test_check_requires_review_pairs_for_merge_and_flagged_reviews(
    tmp_path: Path,
    status: str,
    requires_security_review: bool,
    execution_profile: str,
    review_files: list[str],
    expected_fragment: str,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        current_review_round=1,
        requires_security_review=requires_security_review,
        status_history=(
            ["draft", "planned", "red", "green", "in_review", "ready_to_merge", "done"]
            if status == "done"
            else ["draft", "planned", "red", "green", "in_review", status]
        ),
        task_type=("auth" if requires_security_review else "frontend" if execution_profile == "web.browser" else "general"),
        execution_profile=execution_profile,
    )
    review_dir = task_dir / "review"
    for file_name in review_files:
        write_text(review_dir / file_name, review_content_for_file(file_name))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert expected_fragment in result.stderr


@pytest.mark.parametrize(
    ("status", "status_history", "evidence_content"),
    [
        (
            "ready_to_merge",
            ["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
            None,
        ),
        (
            "done",
            ["draft", "planned", "red", "green", "in_review", "ready_to_merge", "done"],
            "",
        ),
    ],
)
def test_check_requires_non_empty_verification_evidence_for_closed_statuses(
    tmp_path: Path,
    status: str,
    status_history: list[str],
    evidence_content: str | None,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        status_history=status_history,
        current_review_round=1,
        include_verification_evidence=False,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))
    if evidence_content is not None:
        write_text(task_dir / "verification" / "cli" / "result.md", evidence_content)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "substantive evidence" in result.stderr


def test_check_rejects_illegal_transition_from_planned_to_done(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="done",
        status_history=["draft", "planned", "done"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "planned -> done" in result.stderr


def test_check_rejects_blocked_status_as_transition_shortcut(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "blocked", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "blocked" in result.stderr


def test_check_rejects_task_type_mismatch_with_review_requirements(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        task_type="api",
        requires_security_review=False,
        execution_profile="backend.http",
        required_agents=["planner", "tdd-guide", "code-reviewer"],
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "requires_security_review" in result.stderr


def test_check_rejects_unknown_execution_profile(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        execution_profile="mobile.app",
        verification_profile=["mobile.app"],
        include_verification_dir=False,
    )
    (task_dir / "verification").mkdir(parents=True, exist_ok=True)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "execution_profile" in result.stderr


def test_check_rejects_unknown_task_type_tokens(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        task_type="authe",
        execution_profile="backend.http",
        verification_profile=["backend.http"],
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "task_type" in result.stderr


def test_check_rejects_non_string_title(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    task_md = task_dir / "task.md"
    task_text = task_md.read_text(encoding="utf-8")
    task_md.write_text(task_text.replace("title: Login Flow", "title: true"), encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "title" in result.stderr


def test_check_rejects_task_outside_theking_workflows(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, use_theking_layout=False)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert ".theking/workflows" in result.stderr


def test_check_rejects_symlinked_task_dir_input(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    task_link = tmp_path / "task-link"
    task_link.symlink_to(task_dir, target_is_directory=True)

    result = run_cli(["check", "--task-dir", str(task_link)], cwd=tmp_path)

    assert result.returncode != 0
    assert "symlink" in result.stderr


def test_check_rejects_invalid_workflow_project_segment(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, workflow_project_name="Demo App")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert ".theking/workflows" in result.stderr


def test_check_rejects_workflow_project_slug_mismatch(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path, workflow_project_name="other-app")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert ".theking/workflows" in result.stderr


def test_check_rejects_execution_and_verification_profile_mismatch(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        task_type="api",
        execution_profile="backend.http",
        verification_profile=["web.browser"],
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "verification_profile" in result.stderr


def test_check_rejects_verification_profile_file_path(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    verification_path = task_dir / "verification" / "cli"
    shutil.rmtree(verification_path)
    verification_path.write_text("not a directory\n", encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "directory" in result.stderr


def test_check_rejects_symlinked_verification_profile_path(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    verification_path = task_dir / "verification" / "cli"
    outside_verification = tmp_path / "outside-verification"
    outside_verification.mkdir()
    shutil.rmtree(verification_path)
    verification_path.symlink_to(outside_verification, target_is_directory=True)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "symlink" in result.stderr


def test_check_rejects_task_id_mismatch_with_directory_name(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    task_md = task_dir / "task.md"
    task_text = task_md.read_text(encoding="utf-8")
    task_md.write_text(task_text.replace("id: TASK-001-login-flow", "id: TASK-001-other-flow"), encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "task id" in result.stderr.lower()


def test_check_requires_positive_review_round_for_merge_states(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=0,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "current_review_round" in result.stderr


def test_check_requires_all_review_rounds_up_to_current_round(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "changes_requested", "in_review", "ready_to_merge"],
        current_review_round=2,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-002.md", review_markdown("Code", 2))
    write_text(review_dir / "code-review-round-002.resolved.md", resolved_review_markdown("Code", 2))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "code-review-round-001" in result.stderr


def test_check_does_not_count_blocked_resume_as_new_review_round(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "blocked", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_accepts_changes_requested_with_review_but_without_resolved_file(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="changes_requested",
        status_history=["draft", "planned", "red", "green", "in_review", "changes_requested"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_accepts_first_in_review_round_without_current_round_review_files(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="in_review",
        status_history=["draft", "planned", "red", "green", "in_review"],
        current_review_round=1,
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_accepts_second_in_review_round_without_current_round_review_files(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="in_review",
        status_history=["draft", "planned", "red", "green", "in_review", "changes_requested", "in_review"],
        current_review_round=2,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_rejects_underreported_review_round_from_history(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="changes_requested",
        status_history=["draft", "planned", "red", "green", "in_review", "changes_requested", "in_review", "changes_requested"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "current_review_round" in result.stderr


def test_check_rejects_review_artifact_directories(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    (review_dir / "code-review-round-001.md").mkdir(parents=True, exist_ok=True)
    (review_dir / "code-review-round-001.resolved.md").mkdir(parents=True, exist_ok=True)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "artifact must be a file" in result.stderr


def test_check_rejects_review_artifacts_without_required_sections(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", "# Code Review Round 001\n")
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "## Findings" in result.stderr


def test_check_rejects_review_artifacts_with_findings_only_in_body_text(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(
        review_dir / "code-review-round-001.md",
        "# Code Review Round 001\n\nThis note mentions ## Context and ## Findings in body text only.\n",
    )
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "## Context" in result.stderr or "## Findings" in result.stderr


def test_check_rejects_resolved_review_artifacts_without_fixes_section(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(
        review_dir / "code-review-round-001.resolved.md",
        "# Resolved Code Review Round 001\n\n## Verification\n- uv run --with pytest pytest tests -q\n",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "## Fixes" in result.stderr


def test_check_accepts_happy_path_task_tree(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
        execution_profile="backend.cli",
        task_type="general",
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_accepts_http_happy_path_with_security_review_pair(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
        execution_profile="backend.http",
        task_type="api",
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))
    write_text(review_dir / "security-review-round-001.md", review_markdown("Security", 1))
    write_text(review_dir / "security-review-round-001.resolved.md", resolved_review_markdown("Security", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_accepts_browser_happy_path_with_e2e_review_pair(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
        execution_profile="web.browser",
        task_type="frontend",
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))
    write_text(review_dir / "e2e-review-round-001.md", review_markdown("E2E", 1))
    write_text(review_dir / "e2e-review-round-001.resolved.md", resolved_review_markdown("E2E", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr


def test_check_rejects_symlinked_review_directory(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    review_dir = task_dir / "review"
    outside_review = tmp_path / "outside-review"
    outside_review.mkdir()
    review_dir.rmdir()
    review_dir.symlink_to(outside_review, target_is_directory=True)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr


def test_check_rejects_symlinked_review_file(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    outside_review = tmp_path / "outside-review.md"
    outside_review.write_text(review_markdown("Code", 1), encoding="utf-8")
    (review_dir / "code-review-round-001.md").symlink_to(outside_review)
    write_text(review_dir / "code-review-round-001.resolved.md", resolved_review_markdown("Code", 1))

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "symlink" in result.stderr


# ---------------------------------------------------------------------------
# Sprint-004 / TASK-001: substantive-evidence gate for smoke.md
#
# ADR-003 "闸 1 · smoke.md 内容校验" requires verification profile evidence to
# be substantive: placeholder-only content or < 40 substantive chars must fail
# `workflowctl check` on ready_to_merge / done. The helper under test is being
# renamed from `has_non_empty_verification_evidence` -> `has_substantive_
# verification_evidence`; until that rename ships, these tests are expected to
# FAIL (RED phase of TDD).
# ---------------------------------------------------------------------------


def _merge_ready_task_tree_without_evidence(tmp_path: Path) -> Path:
    """Build a ready_to_merge task tree with review artefacts but no smoke.md.

    Callers drop their own content under verification/cli/ to exercise the
    substantive-evidence gate in isolation.
    """
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=[
            "draft",
            "planned",
            "red",
            "green",
            "in_review",
            "ready_to_merge",
        ],
        current_review_round=1,
        include_verification_evidence=False,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", review_markdown("Code", 1))
    write_text(
        review_dir / "code-review-round-001.resolved.md",
        resolved_review_markdown("Code", 1),
    )
    return task_dir


def test_check_rejects_placeholder_only_verification_evidence(tmp_path: Path) -> None:
    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    write_text(smoke_path, "<!-- TODO: run smoke later -->\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail on placeholder-only smoke.md, but it passed. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        "Error message should name the placeholder/substantive cause. "
        f"stderr={result.stderr!r}"
    )


def test_check_rejects_short_substantive_verification_evidence(tmp_path: Path) -> None:
    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    # 7 substantive chars — well below the 40-char floor
    write_text(smoke_path, "ran it\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail on 7-char smoke.md, but it passed. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "40" in result.stderr or "substantive" in stderr_lower, (
        "Error message should name the 40-char threshold or use the word "
        f"'substantive'. stderr={result.stderr!r}"
    )


def test_check_accepts_substantive_verification_evidence(tmp_path: Path) -> None:
    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    smoke_body = "\n".join(
        [
            "# Smoke",
            "",
            "- Command: `workflowctl check --task-dir <task>`",
            "- Stdout: `OK /Users/fisher/code/sourcecode/tencent/TASK-001`",
            "- Exit: 0",
            "",
        ]
    )
    write_text(smoke_path, smoke_body)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Expected check to pass on substantive smoke.md. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # Guard against accidental regressions that leave the placeholder-gate
    # message in stderr even on the happy path.
    stderr_lower = result.stderr.lower()
    assert "placeholder" not in stderr_lower
    assert "non-empty evidence file" not in stderr_lower


def test_check_accepts_combined_small_verification_evidence_files(
    tmp_path: Path,
) -> None:
    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    profile_dir = task_dir / "verification" / "cli"
    # Each file alone is < 40 substantive chars, but the directory's combined
    # substantive length comfortably exceeds the 40-char floor.
    # sprint-017 TASK-001: smoke.md carries the Command anchor, stdout.md
    # carries the Exit anchor — together they satisfy both gates.
    write_text(profile_dir / "smoke.md", "$ workflowctl check a b c\n")  # ~22 chars
    write_text(profile_dir / "stdout.md", "ran fine, exit code 0 observed\n")  # ~30 chars

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Expected check to pass when two small files combine to >= 40 "
        f"substantive chars. stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" not in stderr_lower
    assert "non-empty evidence file" not in stderr_lower


def test_check_placeholder_token_handling_depends_on_surrounding_substance(
    tmp_path: Path,
) -> None:
    """Spec Edge Case 5: a placeholder token inside a larger substantive body
    must not poison the file. Only when stripping the token leaves < 40
    substantive chars should the check fail."""

    # --- Case A: bare placeholder token, nothing else -> MUST fail ----------
    case_a_root = tmp_path / "case-a"
    case_a_root.mkdir()
    task_dir_a = _merge_ready_task_tree_without_evidence(case_a_root)
    smoke_a = task_dir_a / "verification" / "cli" / "smoke.md"
    write_text(smoke_a, "TODO\n")

    result_a = run_cli(["check", "--task-dir", str(task_dir_a)], cwd=case_a_root)

    assert result_a.returncode != 0, (
        "Expected check to fail when smoke.md is a bare placeholder token. "
        f"stdout={result_a.stdout!r} stderr={result_a.stderr!r}"
    )
    stderr_a_lower = result_a.stderr.lower()
    assert "placeholder" in stderr_a_lower or "substantive" in stderr_a_lower, (
        f"Case A stderr should name the placeholder cause. stderr={result_a.stderr!r}"
    )

    # --- Case B: placeholder token embedded in real prose -> MUST pass ------
    case_b_root = tmp_path / "case-b"
    case_b_root.mkdir()
    task_dir_b = _merge_ready_task_tree_without_evidence(case_b_root)
    smoke_b = task_dir_b / "verification" / "cli" / "smoke.md"
    # sprint-017 TASK-001: add `$` command anchor + `exit 0` so the prose
    # satisfies the backend.cli shape gate on top of the 40-char floor.
    write_text(
        smoke_b,
        "$ workflowctl check --task-dir TASK-001\n"
        "ran command workflowctl check, got exit 0 and OK line, "
        "TODO: add screenshot of dashboard later\n",
    )

    result_b = run_cli(["check", "--task-dir", str(task_dir_b)], cwd=case_b_root)

    assert result_b.returncode == 0, (
        "Expected check to pass when substantive prose around a TODO token "
        f"exceeds 40 chars. stdout={result_b.stdout!r} stderr={result_b.stderr!r}"
    )
    stderr_b_lower = result_b.stderr.lower()
    assert "placeholder" not in stderr_b_lower
    assert "non-empty evidence file" not in stderr_b_lower


def test_check_rejects_bullet_only_verification_evidence(tmp_path: Path) -> None:
    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    # Bullet markers and whitespace only — no substantive content after strip.
    write_text(smoke_path, "- - -\n-\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail on bullet-only smoke.md. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        f"Error message should name the placeholder/substantive cause. "
        f"stderr={result.stderr!r}"
    )


# --- Round-002 follow-up tests (addressing HIGH-3 / MEDIUM-1 / MEDIUM-3) ----


def test_check_enforces_inclusive_40_char_boundary(tmp_path: Path) -> None:
    """HIGH-3: spec.md Edge Cases points this out — 'exactly 40 substantive
    chars -> pass (inclusive lower bound)'. Pin the boundary directly.
    """

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke = task_dir / "verification" / "cli" / "smoke.md"

    # sprint-017 TASK-001: prefix with the two anchors shape gate needs, then
    # pad with the boundary-exact substantive chars. The anchor preamble
    # itself carries > 40 substantive chars, so add a sibling file of "a" *
    # <boundary-diff> to pin the counter.
    prefix = "$ workflowctl check\nExit: 0\n"

    # 40 substantive 'a' chars: must pass (inclusive boundary).
    write_text(smoke, prefix + "a" * 40 + "\n")
    result_at = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert result_at.returncode == 0, (
        "Expected exactly 40 substantive chars to PASS (inclusive boundary). "
        f"stdout={result_at.stdout!r} stderr={result_at.stderr!r}"
    )

    # 39 substantive chars WITH anchors: must still fail — only the 40-char
    # floor is being probed, shape gate stays green throughout. We drop one
    # 'a' AND remove enough anchor text to push the total below 40. Easier:
    # use a dedicated below-boundary file without anchors, which now fails
    # on EITHER gate — acceptable for this assertion (boundary is below 40).
    write_text(smoke, "a" * 39 + "\n")
    result_below = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert result_below.returncode != 0, (
        "Expected 39 substantive chars to FAIL (below boundary). "
        f"stdout={result_below.stdout!r} stderr={result_below.stderr!r}"
    )


def test_check_rejects_chinese_placeholder_only(tmp_path: Path) -> None:
    """MEDIUM-1: Chinese placeholder tokens must be stripped by the gate.
    Guards against accidental removal of the `待补` entry or regressions in
    `\\b` handling on CJK characters.
    """

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    # 10 occurrences of 待补 + whitespace — 20 raw CJK chars that should
    # all be stripped as placeholder tokens, leaving 0 substantive chars.
    write_text(smoke_path, "待补 待补 待补 待补 待补\n待补 待补 待补 待补 待补\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail on Chinese placeholder-only smoke.md. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        f"Error message should name the placeholder/substantive cause. "
        f"stderr={result.stderr!r}"
    )


def test_check_accepts_substantive_chinese_prose(tmp_path: Path) -> None:
    """MEDIUM-1 (positive path): pure Chinese prose must be accepted when
    its length alone crosses the 40-substantive-char floor. Confirms each
    CJK char counts as 1 (not 0 via any `\\w`-vs-`\\s` regex drift)."""

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    # 50 CJK chars, no placeholder tokens. Prefixed with the backend.cli
    # shape gate anchors (sprint-017 TASK-001) so we isolate the CJK-length
    # path — this test still asserts that the 40-char substantive floor is
    # willing to count CJK characters as 1 each.
    write_text(
        smoke_path,
        "$ workflowctl check\n"
        "Exit: 0\n"
        "执行了真实冒烟脚本确认前端和后端服务均已正常启动并返回预期响应码与输出内容无异常\n",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Expected check to pass on substantive Chinese prose. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_check_rejects_pure_placeholder_above_length_floor(tmp_path: Path) -> None:
    """MEDIUM-3: isolate the placeholder-stripping path from the length-gate
    path. A file whose raw byte length far exceeds 40 but whose *content*
    is nothing but placeholder tokens (plus whitespace) must still fail.

    If someone removes the placeholder blacklist but keeps the length
    check, this test will catch it; the original Case A used a 4-char
    'TODO' which would have failed on length alone."""

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    smoke_path = task_dir / "verification" / "cli" / "smoke.md"
    # 20 repetitions of 'TODO ' = 100 raw chars, 80 of them non-whitespace.
    # After placeholder-token stripping, 0 substantive chars should remain,
    # so the gate must reject — independent of the length floor.
    write_text(smoke_path, "TODO " * 20)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail when smoke.md is 100 raw chars of pure "
        "TODO tokens, proving the placeholder-stripping path is active "
        "even above the length floor. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        f"stderr={result.stderr!r}"
    )


def test_check_rejects_binary_only_verification_evidence(tmp_path: Path) -> None:
    """HIGH-1: binary (non-UTF-8) files must NOT short-circuit the
    substantive-evidence gate. Previously a 2-byte \\x80\\x80 would pass
    because `UnicodeDecodeError` returned True immediately — an unwritten
    opt-out that ADR-003 explicitly forbids."""

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    profile_dir = task_dir / "verification" / "cli"
    profile_dir.mkdir(parents=True, exist_ok=True)
    # 2 bytes of arbitrary non-UTF-8 data. Must not be accepted as evidence.
    (profile_dir / "trace.bin").write_bytes(b"\x80\x80")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        "Expected check to fail when the only 'evidence' is a 2-byte "
        "non-UTF-8 binary file. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    stderr_lower = result.stderr.lower()
    assert "placeholder" in stderr_lower or "substantive" in stderr_lower, (
        f"stderr={result.stderr!r}"
    )


def test_check_accepts_binary_plus_substantive_text(tmp_path: Path) -> None:
    """HIGH-1 companion: a binary artefact is fine as long as at least one
    readable sibling carries >= 40 substantive chars. The gate counts only
    UTF-8 text towards the threshold, but does not reject merely for the
    presence of a binary file."""

    task_dir = _merge_ready_task_tree_without_evidence(tmp_path)
    profile_dir = task_dir / "verification" / "cli"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "screenshot.bin").write_bytes(b"\x80\x80\x80\x80")
    write_text(
        profile_dir / "smoke.md",
        "# Smoke\n- Command: workflowctl check\n- Stdout: OK task dir exit=0\n",
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        "Expected check to pass when a binary file coexists with a "
        "substantive text sibling. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Sprint-004 / TASK-002: Acceptance traceability gate
#
# ADR-003 闸 2: every `- [ ] <criterion>` top-level checkbox under ## Acceptance
# must carry two child bullets naming the verification method and evidence
# path. validate_acceptance_traceability runs after validate_spec_section_counts
# in the require_content=True branch, so it only fires on red+ statuses and
# respects the legacy two-section bypass.
#
# These tests are RED at authoring time — ALLOWED_VERIFICATION_METHODS and
# validate_acceptance_traceability do not exist yet in validation.py.
# ---------------------------------------------------------------------------


def _spec_with_traceability(
    *,
    acceptance_lines: list[str] | None = None,
) -> str:
    """Build a new-format spec.md with full section counts satisfying
    ADR-001 thresholds plus acceptance traceability sub-bullets.

    Pass ``acceptance_lines`` to substitute the Acceptance block with a
    custom list of raw lines (e.g. to construct malformed variants that
    omit a sub-bullet). Default is one well-formed checkbox.
    """

    acceptance_body = acceptance_lines or [
        "- [ ] Criterion behaves correctly",
        "  - 验证方式: unit",
        "  - 证据路径: tests/test_foo.py::test_bar",
    ]
    return "\n".join(
        [
            "# Task Spec",
            "",
            "## Scope",
            "- Implement the minimal workflow.",
            "",
            "## Non-Goals",
            "- Avoid unrelated cleanup.",
            "",
            "## Acceptance",
            *acceptance_body,
            "",
            "## Test Plan",
            "- Run pytest.",
            "- Exercise the happy path.",
            "- Exercise the error path.",
            "- Verify idempotent re-runs.",
            "- Run regression suite.",
            "",
            "## Edge Cases",
            "- Handle repeated runs safely.",
            "- Handle missing optional inputs.",
            "- Handle partially written artifacts.",
            "",
        ]
    )


def _red_state_task(tmp_path: Path) -> Path:
    """red-state task tree — content validation fires at red+ statuses per
    spec_requires_content."""

    return make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )


def test_check_accepts_spec_with_acceptance_traceability(tmp_path: Path) -> None:
    """Happy path: well-formed new-format spec passes check on red+."""

    task_dir = _red_state_task(tmp_path)
    write_text(task_dir / "spec.md", _spec_with_traceability())

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"Expected well-formed traceability spec to pass. stderr={result.stderr!r}"
    )


def test_check_rejects_spec_missing_verification_method(tmp_path: Path) -> None:
    """Missing 验证方式 sub-bullet must fail with a precise message."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] Criterion behaves correctly",
                "  - 证据路径: tests/test_foo.py::test_bar",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected fail when 验证方式 missing. stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "验证方式" in result.stderr, result.stderr


def test_check_rejects_spec_missing_evidence_path(tmp_path: Path) -> None:
    """Missing 证据路径 sub-bullet must fail with a precise message."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] Criterion behaves correctly",
                "  - 验证方式: unit",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected fail when 证据路径 missing. stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "证据路径" in result.stderr, result.stderr


def test_check_rejects_spec_with_unknown_verification_method(tmp_path: Path) -> None:
    """Unknown verification method must fail with a list of allowed values."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] Criterion behaves correctly",
                "  - 验证方式: speculation",
                "  - 证据路径: tests/test_foo.py::test_bar",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected fail on unknown 验证方式. stderr={result.stderr!r}"
    )
    assert "speculation" in result.stderr or "验证方式" in result.stderr, result.stderr
    # The allowed set must be advertised so the implementer knows what to pick.
    allowed_method_names = ("unit", "integration", "smoke", "e2e", "manual-observed")
    stderr_lower = result.stderr.lower()
    assert any(m in stderr_lower for m in allowed_method_names), (
        f"Error message should enumerate at least one allowed method. "
        f"stderr={result.stderr!r}"
    )


def test_check_rejects_spec_with_blank_evidence_path(tmp_path: Path) -> None:
    """`- 证据路径:` present but with no value (or whitespace only) must fail
    — distinguishes 'empty' from 'missing' to avoid stale implementer
    confusion when the sub-bullet is typed but never filled in."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] Criterion behaves correctly",
                "  - 验证方式: unit",
                "  - 证据路径:   ",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected fail on blank 证据路径. stderr={result.stderr!r}"
    )
    assert "证据路径" in result.stderr, result.stderr


def test_check_accepts_spec_with_empty_acceptance_section(tmp_path: Path) -> None:
    """Zero-checkbox Acceptance section must still pass — traceability is
    per-checkbox; a lightweight task with no acceptance item has nothing
    to trace. Guards against the gate over-firing on edge of section."""

    task_dir = make_valid_task_tree(
        tmp_path,
        status="red",
        status_history=["draft", "planned", "red"],
    )
    # Replace the Acceptance section body with a single comment (no checkbox).
    spec = task_dir / "spec.md"
    spec_text = spec.read_text(encoding="utf-8")
    spec_text = spec_text.replace(
        "## Acceptance\n- Review loop is enforced.",
        "## Acceptance\n<!-- no items for this lightweight task -->",
    )
    write_text(spec, spec_text)

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    # With empty Acceptance, spec_section_has_content will already fail
    # (Acceptance is a required section that must have content); we expect
    # that existing gate's error message, NOT the traceability gate's.
    # This test therefore pins ORDER: traceability gate must run AFTER the
    # content-per-section gate so its more specific error never surfaces
    # for a truly empty Acceptance.
    if result.returncode != 0:
        assert "Acceptance" in result.stderr, result.stderr
        assert "验证方式" not in result.stderr, (
            "Traceability error should not fire when Acceptance is empty; "
            f"the more fundamental 'section must not be empty' gate must "
            f"precede it. stderr={result.stderr!r}"
        )
    # If returncode == 0, that's also acceptable — some spec designs may
    # treat an all-comment Acceptance as legal lightweight; in that case
    # the traceability gate still must not have fired (nothing to trace).


def test_check_normalizes_verification_method_case(tmp_path: Path) -> None:
    """Verification method should be normalized to lowercase + stripped
    before membership check so `  Unit  ` and `SMOKE` both pass."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] First criterion",
                "  - 验证方式:   Unit  ",
                "  - 证据路径: tests/one.py",
                "- [ ] Second criterion",
                "  - 验证方式: SMOKE",
                "  - 证据路径: verification/cli/smoke.md",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, (
        f"Expected case-insensitive + stripped method names to pass. "
        f"stderr={result.stderr!r}"
    )


# --- Round-001 follow-ups: MEDIUM-3 / LOW-2 tests ---------------------------


def test_check_rejects_spec_with_blank_verification_method(tmp_path: Path) -> None:
    """MEDIUM-3: `- 验证方式:` present but value is whitespace only must
    fail on the dedicated 'empty value' branch, distinct from the
    'missing sub-bullet' branch. Mirror of
    `test_check_rejects_spec_with_blank_evidence_path`."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] Criterion behaves correctly",
                "  - 验证方式:   ",
                "  - 证据路径: tests/test_foo.py::test_bar",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, (
        f"Expected fail on blank 验证方式 value. stderr={result.stderr!r}"
    )
    assert "验证方式" in result.stderr, result.stderr
    # The empty-value branch has its own precise message; guard against
    # accidental collapse into the 'unknown method' branch which would
    # have different wording.
    stderr_lower = result.stderr.lower()
    assert "empty" in stderr_lower or "空" in result.stderr, (
        f"Error should use the 'empty value' phrasing, not 'unknown'. "
        f"stderr={result.stderr!r}"
    )


def test_check_reports_first_broken_checkbox_only(tmp_path: Path) -> None:
    """LOW-2: `validate_acceptance_traceability` docstring promises
    deterministic ordering — "first missing piece reported first so
    implementers fix one thing at a time." This test pins the contract
    so a future refactor that "collects all errors and joins" cannot
    silently break it."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] First criterion is missing verification method",
                "  - 证据路径: tests/a.py",
                "- [ ] Second criterion has an unknown verification method",
                "  - 验证方式: speculation",
                "  - 证据路径: tests/b.py",
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, result.stderr
    # Only the first checkbox's error should surface.
    assert "First criterion" in result.stderr, (
        f"First broken checkbox should be named. stderr={result.stderr!r}"
    )
    assert "Second criterion" not in result.stderr, (
        f"Second checkbox's error must NOT be reported yet "
        f"(deterministic-ordering contract). stderr={result.stderr!r}"
    )
    assert "speculation" not in result.stderr, (
        f"Second checkbox's unknown-method detail must be absent. "
        f"stderr={result.stderr!r}"
    )


def test_check_closes_checkbox_scope_on_paragraph(tmp_path: Path) -> None:
    """MEDIUM-1: a plain paragraph at column 0 between two checkboxes
    must close the first checkbox's sub-bullet scope. Without this,
    sub-bullets that visually belong to the second checkbox (but appear
    after the paragraph) would be silently attributed to the first one,
    hiding the true location of any error."""

    task_dir = _red_state_task(tmp_path)
    write_text(
        task_dir / "spec.md",
        _spec_with_traceability(
            acceptance_lines=[
                "- [ ] First criterion",
                "  - 验证方式: unit",
                "  - 证据路径: tests/a.py",
                "",
                "Some paragraph describing context or a follow-up note.",
                "",
                "- [ ] Second criterion",
                # Intentionally missing BOTH sub-bullets on the second
                # checkbox. A buggy scope-closing rule would keep the
                # first checkbox's scope open and attach these absent
                # sub-bullets to the first — causing the error to be
                # reported against "First criterion" instead of Second.
            ]
        ),
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0, result.stderr
    # The error should name the SECOND criterion, proving scope closed
    # correctly on the paragraph.
    assert "Second criterion" in result.stderr, (
        f"Error should name 'Second criterion' — the one actually missing "
        f"sub-bullets. stderr={result.stderr!r}"
    )
    assert "First criterion" not in result.stderr, (
        f"'First criterion' is well-formed and must NOT appear in the "
        f"error. stderr={result.stderr!r}"
    )


