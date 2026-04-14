from __future__ import annotations

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


def make_valid_task_tree(
    base_dir: Path,
    *,
    status: str = "draft",
    status_history: list[str] | None = None,
    current_review_round: int = 0,
    task_type: str = "general",
    requires_security_review: bool = False,
    requires_e2e: bool = False,
    required_agents: list[str] | None = None,
    include_task: bool = True,
    include_spec: bool = True,
    include_review_dir: bool = True,
) -> Path:
    task_dir = base_dir / "TASK-001-login-flow"
    review_dir = task_dir / "review"
    history = status_history or [status]
    agents = required_agents or ["planner", "tdd-guide", "code-reviewer"]
    if required_agents is None:
        if task_type in {"frontend", "e2e"}:
            agents.append("e2e-runner")
        if task_type in {"auth", "input", "api"}:
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
                f"requires_e2e: {'true' if requires_e2e else 'false'}",
                f"requires_security_review: {'true' if requires_security_review else 'false'}",
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

    return task_dir


@pytest.mark.parametrize(
    "missing_name",
    ["task.md", "spec.md", "review"],
)
def test_check_fails_when_required_task_artifacts_are_missing(
    tmp_path: Path,
    missing_name: str,
) -> None:
    task_dir = make_valid_task_tree(tmp_path)
    target = task_dir / missing_name
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert missing_name in result.stderr


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
    ("status", "requires_security_review", "requires_e2e", "review_files", "expected_fragment"),
    [
        ("ready_to_merge", False, False, [], "code-review-round-001"),
            ("done", False, False, ["code-review-round-001.md"], "code-review-round-001.resolved.md"),
        (
            "ready_to_merge",
            True,
            False,
            ["code-review-round-001.md", "code-review-round-001.resolved.md"],
            "security-review-round-001",
        ),
        (
            "ready_to_merge",
            False,
            True,
            ["code-review-round-001.md", "code-review-round-001.resolved.md"],
            "e2e-review-round-001",
        ),
    ],
)
def test_check_requires_review_pairs_for_merge_and_flagged_reviews(
    tmp_path: Path,
    status: str,
    requires_security_review: bool,
    requires_e2e: bool,
    review_files: list[str],
    expected_fragment: str,
) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status=status,
        current_review_round=1,
        requires_security_review=requires_security_review,
        requires_e2e=requires_e2e,
        status_history=(
            ["draft", "planned", "red", "green", "in_review", "ready_to_merge", "done"]
            if status == "done"
            else ["draft", "planned", "red", "green", "in_review", status]
        ),
        task_type=("auth" if requires_security_review else "frontend" if requires_e2e else "general"),
    )
    review_dir = task_dir / "review"
    for file_name in review_files:
        write_text(review_dir / file_name, "# Review\n")

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
    write_text(review_dir / "code-review-round-001.md", "# Review\n")
    write_text(review_dir / "code-review-round-001.resolved.md", "# Resolved Review\n")

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
    write_text(review_dir / "code-review-round-001.md", "# Review\n")
    write_text(review_dir / "code-review-round-001.resolved.md", "# Resolved Review\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "blocked" in result.stderr


def test_check_rejects_task_type_mismatch_with_review_requirements(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        task_type="auth",
        requires_security_review=False,
        required_agents=["planner", "tdd-guide", "code-reviewer"],
    )

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "requires_security_review" in result.stderr


def test_check_requires_positive_review_round_for_merge_states(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=0,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", "# Review\n")
    write_text(review_dir / "code-review-round-001.resolved.md", "# Resolved Review\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode != 0
    assert "current_review_round" in result.stderr


def test_check_accepts_happy_path_task_tree(tmp_path: Path) -> None:
    task_dir = make_valid_task_tree(
        tmp_path,
        status="ready_to_merge",
        status_history=["draft", "planned", "red", "green", "in_review", "ready_to_merge"],
        current_review_round=1,
    )
    review_dir = task_dir / "review"
    write_text(review_dir / "code-review-round-001.md", "# Review\n")
    write_text(review_dir / "code-review-round-001.resolved.md", "# Resolved Review\n")

    result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)

    assert result.returncode == 0, result.stderr