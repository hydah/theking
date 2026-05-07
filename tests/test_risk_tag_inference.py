from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.constants import WorkflowError
from scripts.validation import (
    infer_required_agents,
    parse_frontmatter,
    task_requires_security_review,
    validate_task_metadata,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "workflowctl.py"
PLANNER_TEMPLATE = REPO_ROOT / "templates" / "agents" / "agent_planner.md.tmpl"


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
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


def write_plan(tmp_path: Path, plan: dict[str, Any]) -> Path:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    return plan_file


def minimal_task_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "TASK-001-risk-tags",
        "title": "Risk Tags",
        "status": "draft",
        "status_history": ["draft"],
        "task_type": "general",
        "execution_profile": "backend.cli",
        "verification_profile": ["backend.cli"],
        "requires_security_review": False,
        "required_agents": ["tdd-guide", "code-reviewer"],
        "depends_on": [],
        "current_review_round": 0,
        "created_at": "2026-05-07T00:00:00Z",
        "theking_schema_version": 1,
    }
    data.update(overrides)
    return data


def generated_task_md(tmp_path: Path, task_id: str) -> Path:
    return workflow_root(tmp_path) / "sprints" / "sprint-001-foundation" / "tasks" / task_id / "task.md"


def test_new_task_requires_explicit_risk_tags() -> None:
    task_data = minimal_task_data()

    with pytest.raises(WorkflowError, match="risk_tags"):
        validate_task_metadata(task_data)


def test_legacy_task_may_omit_risk_tags() -> None:
    task_data = minimal_task_data()
    del task_data["theking_schema_version"]
    del task_data["created_at"]

    validated = validate_task_metadata(task_data)

    assert validated["task_type"] == "general"


def test_existing_schema_versioned_tasks_declare_risk_tags() -> None:
    offenders: list[str] = []
    workflows_dir = REPO_ROOT / ".theking" / "workflows"
    for task_md in sorted(workflows_dir.rglob("tasks/*/task.md")):
        text = task_md.read_text(encoding="utf-8")
        frontmatter = parse_frontmatter(text)
        if "theking_schema_version" not in frontmatter:
            continue
        if "risk_tags" not in frontmatter:
            offenders.append(str(task_md.relative_to(REPO_ROOT)))

    assert not offenders, "schema-versioned task.md files missing risk_tags:\n" + "\n".join(offenders)


@pytest.mark.parametrize(
    "risk_tags",
    ["external-api", {"tag": True}, [None], ["   "]],
)
def test_risk_tags_must_be_list_of_non_empty_strings(risk_tags: Any) -> None:
    task_data = minimal_task_data(risk_tags=risk_tags)

    with pytest.raises(WorkflowError, match="risk_tags"):
        validate_task_metadata(task_data)


def test_unknown_risk_tag_is_rejected() -> None:
    task_data = minimal_task_data(risk_tags=["external-api", "not-real"])

    with pytest.raises(WorkflowError) as excinfo:
        validate_task_metadata(task_data)

    message = str(excinfo.value)
    assert "risk_tags" in message
    assert "not-real" in message


def test_empty_risk_tags_preserve_default_inference() -> None:
    task_data = minimal_task_data(risk_tags=[])

    validated = validate_task_metadata(task_data)

    assert validated["risk_tags"] == []
    assert validated["required_agents"] == ["tdd-guide", "code-reviewer"]
    assert validated["requires_security_review"] is False
    assert infer_required_agents("general", "backend.cli", []) == ["tdd-guide", "code-reviewer"]


@pytest.mark.parametrize(
    ("risk_tags", "expected_agents"),
    [
        (["external-api"], ["security-reviewer"]),
        (["browser"], ["e2e-runner"]),
        (["streaming-media"], ["security-reviewer", "perf-optimizer"]),
        (["realtime"], ["perf-optimizer"]),
        (["data-migration"], ["architect"]),
        (["webrtc"], ["security-reviewer"]),
        (["websocket"], ["security-reviewer"]),
    ],
)
def test_risk_tags_infer_additional_required_agents(
    risk_tags: list[str],
    expected_agents: list[str],
) -> None:
    agents = infer_required_agents("general", "backend.cli", risk_tags)

    assert agents[:2] == ["tdd-guide", "code-reviewer"]
    for agent in expected_agents:
        assert agent in agents
    assert len(agents) == len(set(agents))


def test_risk_tag_agent_inference_deduplicates_overlapping_agents() -> None:
    agents = infer_required_agents(
        "auth",
        "web.browser",
        ["external-api", "browser", "external-api", "webrtc"],
    )

    assert agents.count("security-reviewer") == 1
    assert agents.count("e2e-runner") == 1
    assert agents[:2] == ["tdd-guide", "code-reviewer"]


def test_requires_security_review_ignores_risk_tags() -> None:
    risk_tags = ["external-api", "webrtc", "websocket"]
    required_agents = infer_required_agents("general", "backend.cli", risk_tags)
    task_data = minimal_task_data(
        risk_tags=risk_tags,
        required_agents=required_agents,
    )

    assert task_requires_security_review("general", "backend.cli", risk_tags) is False
    assert "security-reviewer" in required_agents
    validated = validate_task_metadata(task_data)
    assert validated["requires_security_review"] is False


def test_init_task_without_risk_tags_writes_explicit_empty_list(tmp_path: Path) -> None:
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
            "plain-task",
            "--title",
            "Plain Task",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.cli",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(generated_task_md(tmp_path, "TASK-001-plain-task").read_text(encoding="utf-8"))
    assert frontmatter["risk_tags"] == []
    assert frontmatter["required_agents"] == ["tdd-guide", "code-reviewer"]


def test_init_task_writes_risk_tags_and_inferred_agents(tmp_path: Path) -> None:
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
            "risk-task",
            "--title",
            "Risk Task",
            "--task-type",
            "general",
            "--execution-profile",
            "backend.cli",
            "--risk-tags",
            " external-api, browser , external-api ",
        ],
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(generated_task_md(tmp_path, "TASK-001-risk-task").read_text(encoding="utf-8"))
    assert frontmatter["risk_tags"] == ["external-api", "browser"]
    assert frontmatter["requires_security_review"] is False
    assert "security-reviewer" in frontmatter["required_agents"]
    assert "e2e-runner" in frontmatter["required_agents"]
    assert len(frontmatter["required_agents"]) == len(set(frontmatter["required_agents"]))


def test_init_sprint_plan_defaults_missing_risk_tags_to_empty_list(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "plan-task",
                    "title": "Plan Task",
                    "task_type": "general",
                    "execution_profile": "backend.cli",
                    "depends_on": [],
                }
            ]
        },
    )

    result = run_cli(
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

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(generated_task_md(tmp_path, "TASK-001-plan-task").read_text(encoding="utf-8"))
    assert frontmatter["risk_tags"] == []


def test_init_sprint_plan_propagates_risk_tags(tmp_path: Path) -> None:
    bootstrap_sprint(tmp_path)
    plan_file = write_plan(
        tmp_path,
        {
            "tasks": [
                {
                    "slug": "media-migration",
                    "title": "Media Migration",
                    "task_type": "general",
                    "execution_profile": "backend.cli",
                    "depends_on": [],
                    "risk_tags": ["streaming-media", "data-migration", "streaming-media"],
                }
            ]
        },
    )

    result = run_cli(
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

    assert result.returncode == 0, result.stderr
    frontmatter = parse_frontmatter(generated_task_md(tmp_path, "TASK-001-media-migration").read_text(encoding="utf-8"))
    assert frontmatter["risk_tags"] == ["streaming-media", "data-migration"]
    assert frontmatter["requires_security_review"] is False
    for agent in ("security-reviewer", "perf-optimizer", "architect"):
        assert agent in frontmatter["required_agents"]
    assert len(frontmatter["required_agents"]) == len(set(frontmatter["required_agents"]))


def test_planner_template_requires_risk_tags() -> None:
    text = PLANNER_TEMPLATE.read_text(encoding="utf-8")

    assert "risk_tags" in text
    match = re.search(r"```json\n(.*?)\n```", text, flags=re.DOTALL)
    assert match is not None, "planner JSON example not found"
    plan = json.loads(match.group(1).replace("{{", "{").replace("}}", "}"))

    for task in plan["tasks"]:
        assert "risk_tags" in task
        assert isinstance(task["risk_tags"], list)