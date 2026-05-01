from __future__ import annotations

import re
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


def parse_frontmatter(text: str) -> dict[str, object]:
    lines = text.splitlines()
    assert lines[0].strip() == "---"
    data: dict[str, object] = {}
    current_key: str | None = None

    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if not line.strip():
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*$", line.strip()):
            current_key = line.strip()[:-1]
            data[current_key] = []
            continue
        if line.startswith("  - "):
            assert current_key is not None
            list_value = data.setdefault(current_key, [])
            assert isinstance(list_value, list)
            list_value.append(line.strip()[2:].strip())
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.+)$", line.strip())
        assert match is not None
        key, raw_value = match.groups()
        lowered = raw_value.lower()
        if lowered == "true":
            data[key] = True
        elif lowered == "false":
            data[key] = False
        elif raw_value.isdigit():
            data[key] = int(raw_value)
        else:
            data[key] = raw_value
        current_key = None

    raise AssertionError("frontmatter must be closed")


def write_complete_spec(task_dir: Path) -> None:
    # Full-flow spec must meet sprint-002 TASK-001 thresholds (>=5/>=3).
    (task_dir / "spec.md").write_text(
        "\n".join(
            [
                "# Task Spec",
                "",
                "## Scope",
                "- Align the request payload with the backend contract.",
                "",
                "## Non-Goals",
                "- No unrelated refactors.",
                "",
                "## Acceptance",
                "- The affected workflow reaches the expected task state.",
                "",
                "## Test Plan",
                "- Run the relevant automated checks for this task.",
                "- Exercise the happy path end-to-end.",
                "- Cover the primary error path.",
                "- Verify idempotency of the workflow.",
                "- Run the regression suite.",
                "",
                "## Edge Cases",
                "- Re-running the flow keeps the task tree consistent.",
                "- Missing optional inputs do not crash.",
                "- Partial artifacts do not block recovery.",
            ]
        ),
        encoding="utf-8",
    )


def workflow_root(tmp_path: Path) -> Path:
    return tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"


def bootstrap_sprint(tmp_path: Path) -> None:
    init_project = run_cli(
        ["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"],
        cwd=tmp_path,
    )
    init_sprint = run_cli(
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
    assert init_project.returncode == 0, init_project.stderr
    assert init_sprint.returncode == 0, init_sprint.stderr


def test_init_task_creates_minimal_task_tree_and_required_fields(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "auth",
            "--execution-profile",
            "backend.http",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-login-flow"
    )
    task_md = task_dir / "task.md"
    spec_md = task_dir / "spec.md"

    assert task_md.is_file()
    assert spec_md.is_file()
    assert (task_dir / "review").is_dir()
    assert (task_dir / "verification" / "http").is_dir()

    task_text = task_md.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(task_text)
    for field in (
        "id:",
        "title:",
        "status:",
        "task_type:",
        "execution_profile:",
        "verification_profile:",
        "requires_security_review:",
        "required_agents:",
        "depends_on:",
        "current_review_round:",
        "status_history:",
    ):
        assert field in task_text

    assert "status: draft" in task_text
    assert frontmatter["execution_profile"] == "backend.http"
    assert frontmatter["verification_profile"] == ["backend.http"]
    assert frontmatter["requires_security_review"] is True

    spec_text = spec_md.read_text(encoding="utf-8")
    assert "## Scope" in spec_text
    assert "## Non-Goals" in spec_text
    assert "## Acceptance" in spec_text
    assert "## Test Plan" in spec_text
    assert "## Edge Cases" in spec_text


def test_init_task_accepts_project_root_as_project_dir(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    project_dir = tmp_path / "demo-app"

    result = run_cli(
        [
            "init-task",
            "--project-dir",
            str(project_dir),
            "--project-slug",
            "demo-app",
            "--sprint",
            "sprint-001-foundation",
            "--slug",
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "auth",
            "--execution-profile",
            "backend.http",
        ],
        cwd=project_dir,
    )

    assert result.returncode == 0, result.stderr
    assert (
        project_dir
        / ".theking"
        / "workflows"
        / "demo-app"
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-login-flow"
        / "task.md"
    ).is_file()


def test_init_task_generated_spec_requires_author_input_before_red(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "auth",
            "--execution-profile",
            "backend.http",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr

    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-login-flow"
    )
    check_result = run_cli(["check", "--task-dir", str(task_dir)], cwd=tmp_path)
    planned_result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"],
        cwd=tmp_path,
    )
    red_result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "red"],
        cwd=tmp_path,
    )

    assert check_result.returncode == 0, check_result.stderr
    assert planned_result.returncode == 0, planned_result.stderr
    assert red_result.returncode != 0
    assert "section must not be empty: Scope" in red_result.stderr

    write_complete_spec(task_dir)

    retry_red_result = run_cli(
        ["advance-status", "--task-dir", str(task_dir), "--to-status", "red"],
        cwd=tmp_path,
    )

    assert retry_red_result.returncode == 0, retry_red_result.stderr


def test_init_task_creates_handoff_artifact(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "handoff-demo",
            "--title",
            "Handoff Demo",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.cli",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-handoff-demo"
    )
    handoff_md = task_dir / "handoff.md"

    assert handoff_md.is_file(), "init-task should scaffold handoff.md beside task.md and spec.md"
    handoff_text = handoff_md.read_text(encoding="utf-8")
    assert "Phase 1" in handoff_text or "handoff" in handoff_text.lower()
    assert "Planner" in handoff_text or "TDD" in handoff_text or "Reviewer" in handoff_text


def test_init_task_creates_agent_run_ledger_artifact(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "ledger-demo",
            "--title",
            "Ledger Demo",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.cli",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_dir = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-ledger-demo"
    )
    ledger = task_dir / "agent-runs.jsonl"

    assert ledger.is_file(), "init-task should scaffold an optional agent-runs.jsonl ledger"
    assert ledger.read_text(encoding="utf-8") == ""


def test_init_task_rejects_sprint_path_escape(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    escape_dir = workflow_root(tmp_path) / "escape"
    escape_dir.mkdir(parents=True)
    (escape_dir / "sprint.md").write_text("# Escape\n", encoding="utf-8")

    result = run_cli(
        [
            "init-task",
            "--root",
            str(tmp_path),
            "--project-slug",
            "demo-app",
            "--sprint",
            "../escape",
            "--slug",
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "sprint" in result.stderr
    assert not (escape_dir / "tasks").exists()


def test_init_task_rejects_multiline_title(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "login-flow",
            "--title",
            "Login Flow\nstatus: done",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "single line" in result.stderr
    assert not (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-login-flow"
    ).exists()


def test_init_task_rejects_incompatible_task_contract(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "mismatch",
            "--title",
            "Mismatch",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.http",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "incompatible" in result.stderr
    assert not (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-mismatch"
    ).exists()


def test_init_task_generates_profile_specific_test_plan(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "browser-flow",
            "--title",
            "Browser Flow",
            "--task-type",
            "frontend",
            "--execution-profile",
            "web.browser",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    spec_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-browser-flow"
        / "spec.md"
    )
    spec_text = spec_md.read_text(encoding="utf-8")

    assert "Playwright" in spec_text or "browser" in spec_text
    assert "verification/browser/" in spec_text
    assert "workflowctl" not in spec_text


def test_init_task_rejects_symlinked_tasks_directory(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    tasks_dir = workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks"
    outside_tasks = tmp_path / "outside-tasks"
    outside_tasks.mkdir()
    tasks_dir.rmdir()
    tasks_dir.symlink_to(outside_tasks, target_is_directory=True)

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
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not any(outside_tasks.iterdir())


def test_init_task_rejects_symlinked_sprint_directory(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    sprints_dir = workflow_root(tmp_path) / "sprints"
    sprint_dir = sprints_dir / "sprint-001-foundation"
    replacement_sprint = sprints_dir / "sprint-002-other"
    replacement_sprint.mkdir()
    (replacement_sprint / "sprint.md").write_text("# Other Sprint\n", encoding="utf-8")
    (replacement_sprint / "tasks").mkdir()

    original_tasks_dir = sprint_dir / "tasks"
    original_tasks_dir.rmdir()
    (sprint_dir / "sprint.md").unlink()
    sprint_dir.rmdir()
    sprint_dir.symlink_to(replacement_sprint, target_is_directory=True)

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
            "login-flow",
            "--title",
            "Login Flow",
            "--task-type",
            "general",
        ],
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr or "stay under" in result.stderr
    assert not any((replacement_sprint / "tasks").iterdir())


@pytest.mark.parametrize(
    ("task_type", "execution_profile", "expected_agents", "verification_dir"),
    [
        ("frontend", "web.browser", ["tdd-guide", "code-reviewer", "e2e-runner"], "browser"),
        ("auth", "backend.http", ["tdd-guide", "code-reviewer", "security-reviewer"], "http"),
        ("general", "backend.cli", ["tdd-guide", "code-reviewer"], "cli"),
        (
            "auth",
            "web.browser",
            ["tdd-guide", "code-reviewer", "e2e-runner", "security-reviewer"],
            "browser",
        ),
    ],
)
def test_init_task_assigns_required_agents_by_task_type_and_execution_profile(
    tmp_path: Path,
    task_type: str,
    execution_profile: str,
    expected_agents: list[str],
    verification_dir: str,
) -> None:
    bootstrap_sprint(tmp_path)

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
            f"{task_type}-task",
            "--title",
            f"{task_type.title()} Task",
            "--task-type",
            task_type,
            "--execution-profile",
            execution_profile,
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{task_type}-task"
        / "task.md"
    )
    task_text = task_md.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(task_text)

    for agent in expected_agents:
        assert f"- {agent}" in task_text

    required_agents = frontmatter["required_agents"]
    assert isinstance(required_agents, list)
    assert required_agents == expected_agents
    assert len(required_agents) == len(set(required_agents))
    assert frontmatter["verification_profile"] == [execution_profile]
    assert (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{task_type}-task"
        / "verification"
        / verification_dir
    ).is_dir()


def test_init_task_auth_web_preserves_e2e_and_security_agents(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)

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
            "auth-web-task",
            "--title",
            "Auth Web Task",
            "--task-type",
            "auth,web",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / "TASK-001-auth-web-task"
        / "task.md"
    )
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    assert frontmatter["execution_profile"] == "web.browser"
    assert frontmatter["required_agents"] == [
        "tdd-guide",
        "code-reviewer",
        "e2e-runner",
        "security-reviewer",
    ]


@pytest.mark.parametrize(
    ("task_type", "expected_execution_profile"),
    [
        ("frontend", "web.browser"),
        ("api", "backend.http"),
        ("general", "backend.cli"),
        # TASK-004 of kimi-feedback sprint: `backend` alone means "library code",
        # so it must default to backend.cli, not backend.http.
        ("backend", "backend.cli"),
        # `service` still signals an HTTP/RPC server; unchanged.
        ("service", "backend.http"),
    ],
)
def test_init_task_infers_execution_profile_from_task_type(
    tmp_path: Path,
    task_type: str,
    expected_execution_profile: str,
) -> None:
    bootstrap_sprint(tmp_path)

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
            f"{task_type}-inferred",
            "--title",
            f"{task_type.title()} Inferred",
            "--task-type",
            task_type,
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{task_type}-inferred"
        / "task.md"
    )
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))

    assert frontmatter["execution_profile"] == expected_execution_profile
    assert frontmatter["verification_profile"] == [expected_execution_profile]


@pytest.mark.parametrize(
    ("task_type", "expected_execution_profile", "expected_review_mode"),
    [
        ("general", "backend.cli", "light"),
        ("auth", "backend.http", "full"),
        ("api", "backend.http", "full"),
        ("e2e", "web.browser", "full"),
    ],
)
def test_init_task_infers_review_mode_from_task_contract(
    tmp_path: Path,
    task_type: str,
    expected_execution_profile: str,
    expected_review_mode: str,
) -> None:
    bootstrap_sprint(tmp_path)

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
            f"{task_type}-review-mode",
            "--title",
            f"{task_type.title()} Review Mode",
            "--task-type",
            task_type,
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    task_md = (
        workflow_root(tmp_path)
        / "sprints"
        / "sprint-001-foundation"
        / "tasks"
        / f"TASK-001-{task_type}-review-mode"
        / "task.md"
    )
    frontmatter = parse_frontmatter(task_md.read_text(encoding="utf-8"))

    assert frontmatter["execution_profile"] == expected_execution_profile
    assert frontmatter["review_mode"] == expected_review_mode
