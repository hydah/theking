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
    include_task: bool = True,
    include_spec: bool = True,
    include_review_dir: bool = True,
    include_verification_dir: bool = True,
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
                f"current_review_round: {current_review_round}",
                "---",
                "",
                "## Goal",
                "- Validate the workflow.",
            ]
        )
        write_text(task_dir / "task.md", task_content)

    if include_spec:
        spec_content = "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Implement the minimal workflow.",
                "",
                "## Non-Goals",
                "- Extra automation.",
                "",
                "## Acceptance",
                "- Review loop is enforced.",
                "",
                "## Test Plan",
                "- Run pytest.",
            ]
        )
        write_text(task_dir / "spec.md", spec_content)

    if include_review_dir:
        review_dir.mkdir(parents=True, exist_ok=True)

    if include_verification_dir:
        for profile in verification:
            (verification_dir / profile_dir_name(profile)).mkdir(parents=True, exist_ok=True)

    return task_dir


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
        ("## Acceptance\n- Review loop is enforced.", "", "Acceptance"),
        ("## Test Plan\n- Run pytest.", "", "Test Plan"),
    ],
)
def test_check_fails_when_spec_is_missing_required_sections(
    tmp_path: Path,
    target_text: str,
    replacement: str,
    expected_fragment: str,
) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    spec_path = task_dir / "spec.md"
    spec_text = spec_path.read_text(encoding="utf-8")
    spec_path.write_text(spec_text.replace(target_text, replacement), encoding="utf-8")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert expected_fragment in result.stderr


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