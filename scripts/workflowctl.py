from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {
    "draft",
    "planned",
    "red",
    "green",
    "in_review",
    "changes_requested",
    "ready_to_merge",
    "done",
    "blocked",
}

ALLOWED_TRANSITIONS = {
    "draft": {"planned"},
    "planned": {"red"},
    "red": {"green"},
    "green": {"in_review"},
    "in_review": {"changes_requested", "ready_to_merge"},
    "changes_requested": {"red", "in_review"},
    "ready_to_merge": {"done"},
    "blocked": set(),
    "done": set(),
}

THEKING_DIRNAME = ".theking"
SPRINT_NAME_PATTERN = re.compile(r"^sprint-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*$")
TASK_ID_PATTERN = re.compile(r"^TASK-\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_TASK_TYPE_TOKENS = {
    "general",
    "frontend",
    "e2e",
    "ui",
    "web",
    "auth",
    "input",
    "api",
    "backend",
    "service",
    "cli",
    "tooling",
    "script",
    "automation",
    "job",
}
ALLOWED_EXECUTION_PROFILES = {
    "web.browser",
    "backend.http",
    "backend.cli",
    "backend.job",
}
EXECUTION_PROFILE_ALIASES = {
    "browser": "web.browser",
    "web": "web.browser",
    "web-browser": "web.browser",
    "http": "backend.http",
    "backend-http": "backend.http",
    "cli": "backend.cli",
    "backend-cli": "backend.cli",
    "job": "backend.job",
    "backend-job": "backend.job",
}
EXECUTION_PROFILE_DIRS = {
    "web.browser": "browser",
    "backend.http": "http",
    "backend.cli": "cli",
    "backend.job": "job",
}


class WorkflowError(Exception):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        args.handler(args)
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="workflowctl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = subparsers.add_parser("init-project")
    init_project.add_argument("--root", required=True)
    init_project.add_argument("--project-slug", required=True)
    init_project.set_defaults(handler=handle_init_project)

    init_sprint = subparsers.add_parser("init-sprint")
    init_sprint.add_argument("--root", required=True)
    init_sprint.add_argument("--project-slug", required=True)
    init_sprint.add_argument("--theme", required=True)
    init_sprint.set_defaults(handler=handle_init_sprint)

    init_task = subparsers.add_parser("init-task")
    init_task.add_argument("--root", required=True)
    init_task.add_argument("--project-slug", required=True)
    init_task.add_argument("--sprint", required=True)
    init_task.add_argument("--slug", required=True)
    init_task.add_argument("--title", required=True)
    init_task.add_argument("--task-type", required=True)
    init_task.add_argument("--execution-profile")
    init_task.set_defaults(handler=handle_init_task)

    check = subparsers.add_parser("check")
    check.add_argument("--task-dir", required=True)
    check.set_defaults(handler=handle_check)

    return parser


def handle_init_project(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    project_slug = slugify(args.project_slug)
    project_dir = get_project_dir(root, project_slug)
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)

    ensure_local_path(project_dir, root, "project")
    ensure_local_path(workflow_project_dir, project_dir, "workflow project")
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_theking_scaffold(project_dir, project_slug)
    workflow_project_dir.mkdir(parents=True, exist_ok=True)
    (workflow_project_dir / "sprints").mkdir(exist_ok=True)

    project_md = workflow_project_dir / "project.md"
    ensure_absent(project_md)
    project_md.write_text(
        render_template(
            "project.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
        encoding="utf-8",
    )
    print(project_md)


def handle_init_sprint(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    project_slug = slugify(args.project_slug)
    theme_slug = slugify(args.theme)
    project_dir = get_project_dir(root, project_slug)
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)
    ensure_local_path(workflow_project_dir, project_dir, "workflow project")
    ensure_file(workflow_project_dir / "project.md", "project.md")

    sprints_dir = workflow_project_dir / "sprints"
    ensure_local_path(sprints_dir, project_dir, "sprints")
    sprint_number = next_index(sprints_dir, "sprint")
    sprint_name = f"sprint-{sprint_number:03d}-{theme_slug}"
    sprint_dir = sprints_dir / sprint_name
    ensure_local_path(sprint_dir, project_dir, "sprint")
    sprint_dir.mkdir(parents=True, exist_ok=False)
    tasks_dir = sprint_dir / "tasks"
    ensure_local_path(tasks_dir, project_dir, "tasks")
    tasks_dir.mkdir(exist_ok=True)

    sprint_md = sprint_dir / "sprint.md"
    sprint_md.write_text(
        render_template(
            "sprint.md.tmpl",
            sprint_name=sprint_name,
            sprint_theme=humanize_slug(theme_slug),
            exit_criteria="All scoped tasks reach ready_to_merge or done.",
        ),
        encoding="utf-8",
    )
    print(sprint_md)


def handle_init_task(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    project_slug = slugify(args.project_slug)
    sprint_name = normalize_sprint_name(args.sprint)
    task_slug = slugify(args.slug)
    title = normalize_title(args.title)
    task_type = normalize_task_type(args.task_type)
    execution_profile = (
        normalize_execution_profile(args.execution_profile)
        if args.execution_profile
        else infer_execution_profile(task_type)
    )
    validate_task_contract(task_type, execution_profile)
    verification_profile = infer_verification_profile(execution_profile)

    project_dir = get_project_dir(root, project_slug)
    sprints_dir = get_workflow_project_dir(project_dir, project_slug) / "sprints"
    ensure_local_path(sprints_dir, project_dir, "sprints")
    requested_sprint_dir = sprints_dir / sprint_name
    ensure_local_path(requested_sprint_dir, project_dir, "sprint")
    sprint_dir = requested_sprint_dir.resolve()
    ensure_within_directory(sprint_dir, sprints_dir.resolve(), "sprint")
    ensure_file(sprint_dir / "sprint.md", "sprint.md")

    tasks_dir = sprint_dir / "tasks"
    ensure_local_path(tasks_dir, project_dir, "tasks")
    task_number = next_index(tasks_dir, "TASK")
    task_id = f"TASK-{task_number:03d}-{task_slug}"
    task_dir = tasks_dir / task_id
    ensure_local_path(task_dir, project_dir, "task")
    task_dir.mkdir(parents=True, exist_ok=False)
    review_dir = task_dir / "review"
    ensure_local_path(review_dir, project_dir, "review")
    review_dir.mkdir(exist_ok=True)
    verification_dir = task_dir / "verification" / execution_profile_dir(execution_profile)
    ensure_local_path(verification_dir, project_dir, "verification")
    verification_dir.mkdir(parents=True, exist_ok=True)

    requires_security_review = task_requires_security_review(task_type, execution_profile)
    required_agents = infer_required_agents(task_type, execution_profile)

    task_md = task_dir / "task.md"
    task_md.write_text(
        render_template(
            "task.md.tmpl",
            task_id=task_id,
            task_title=serialize_frontmatter_string(title),
            task_type=task_type,
            execution_profile=execution_profile,
            verification_profile_block="\n".join(f"  - {profile}" for profile in verification_profile),
            requires_security_review=str(requires_security_review).lower(),
            required_agents_block="\n".join(f"  - {agent}" for agent in required_agents),
        ),
        encoding="utf-8",
    )

    spec_md = task_dir / "spec.md"
    spec_md.write_text(
        render_template(
            "spec.md.tmpl",
            task_title=title,
            test_plan=default_test_plan(execution_profile),
        ),
        encoding="utf-8",
    )

    print(task_dir)


def handle_check(args: argparse.Namespace) -> None:
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()
    validate_task_dir(task_dir)
    print(f"OK {task_dir}")


def validate_task_dir(task_dir: Path) -> None:
    validate_task_location(task_dir)
    project_dir = task_dir.parents[5]
    ensure_local_path(task_dir, project_dir, "task")
    ensure_dir(task_dir, task_dir.name)
    sprint_dir = task_dir.parent.parent
    workflow_project_dir = sprint_dir.parent.parent
    task_md = task_dir / "task.md"
    spec_md = task_dir / "spec.md"
    review_dir = task_dir / "review"
    verification_dir = task_dir / "verification"

    ensure_local_path(task_md, project_dir, "task.md")
    ensure_local_path(spec_md, project_dir, "spec.md")
    ensure_local_path(review_dir, project_dir, "review")
    ensure_local_path(verification_dir, project_dir, "verification")
    ensure_file(workflow_project_dir / "project.md", "project.md")
    ensure_file(sprint_dir / "sprint.md", "sprint.md")
    ensure_file(task_md, "task.md")
    ensure_file(spec_md, "spec.md")
    ensure_dir(review_dir, "review")
    ensure_dir(verification_dir, "verification")

    task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    validate_task_metadata(task_data)
    if stringify(task_data["id"]) != task_dir.name:
        raise WorkflowError("task id must match the task directory name")
    validate_verification_layout(verification_dir, task_data)
    validate_spec(spec_md)
    validate_review_requirements(review_dir, task_data)


def validate_task_location(task_dir: Path) -> None:
    expected_layout = (
        "task_dir must live under .theking/workflows/<project>/sprints/"
        "<sprint>/tasks/TASK-*"
    )
    if TASK_ID_PATTERN.fullmatch(task_dir.name) is None:
        raise WorkflowError(expected_layout)

    tasks_dir = task_dir.parent
    sprint_dir = tasks_dir.parent
    sprints_dir = sprint_dir.parent
    workflow_project_dir = sprints_dir.parent
    workflows_dir = workflow_project_dir.parent
    theking_dir = workflows_dir.parent
    project_dir = theking_dir.parent

    if slugify(workflow_project_dir.name) != workflow_project_dir.name:
        raise WorkflowError(expected_layout)
    if workflow_project_dir.name != slugify(project_dir.name):
        raise WorkflowError(expected_layout)
    if tasks_dir.name != "tasks":
        raise WorkflowError(expected_layout)
    try:
        normalize_sprint_name(sprint_dir.name)
    except WorkflowError as error:
        raise WorkflowError(expected_layout) from error
    if sprints_dir.name != "sprints":
        raise WorkflowError(expected_layout)
    if workflows_dir.name != "workflows":
        raise WorkflowError(expected_layout)
    if theking_dir.name != THEKING_DIRNAME:
        raise WorkflowError(expected_layout)


def validate_task_metadata(task_data: dict[str, Any]) -> None:
    required_fields = {
        "id",
        "title",
        "status",
        "status_history",
        "task_type",
        "execution_profile",
        "verification_profile",
        "requires_security_review",
        "required_agents",
        "current_review_round",
    }
    missing = sorted(required_fields - set(task_data))
    if missing:
        raise WorkflowError(f"task.md is missing required fields: {', '.join(missing)}")

    task_id = normalize_task_id(stringify(task_data["id"]))
    status = stringify(task_data["status"])
    history = task_data["status_history"]
    title = task_data["title"]
    task_type = normalize_task_type(stringify(task_data["task_type"]))
    execution_profile = normalize_execution_profile(stringify(task_data["execution_profile"]))
    validate_task_contract(task_type, execution_profile)
    if not isinstance(title, str):
        raise WorkflowError("title must be a string")
    normalize_title(title)
    if not isinstance(history, list) or not history:
        raise WorkflowError("status_history must contain at least one status")
    if history[0] != "draft":
        raise WorkflowError("status_history must start with draft")
    if history[-1] != status:
        raise WorkflowError("status must match the last entry in status_history")

    for value in history:
        if value not in ALLOWED_STATUSES:
            raise WorkflowError(f"Unknown status in status_history: {value}")

    if status not in ALLOWED_STATUSES:
        raise WorkflowError(f"Unknown status: {status}")

    for index, (current, nxt) in enumerate(zip(history, history[1:])):
        if nxt == "blocked":
            if current == "done":
                raise WorkflowError("done cannot transition to blocked")
            continue
        if current == "blocked":
            previous = history[index - 1] if index > 0 else None
            if previous is None or previous == "blocked" or nxt != previous:
                raise WorkflowError("blocked tasks must resume to the prior non-blocked status")
            continue
        if nxt not in ALLOWED_TRANSITIONS.get(current, set()):
            raise WorkflowError(f"Illegal status transition: {current} -> {nxt}")

    if not isinstance(task_data["requires_security_review"], bool):
        raise WorkflowError("requires_security_review must be a boolean")
    if not isinstance(task_data["verification_profile"], list) or not task_data["verification_profile"]:
        raise WorkflowError("verification_profile must be a non-empty list")
    if not isinstance(task_data["required_agents"], list) or not task_data["required_agents"]:
        raise WorkflowError("required_agents must be a non-empty list")

    if type(task_data["current_review_round"]) is not int or task_data["current_review_round"] < 0:
        raise WorkflowError("current_review_round must be a non-negative integer")

    expected_review_round = infer_expected_review_round(history)
    if task_data["current_review_round"] != expected_review_round:
        raise WorkflowError(
            "current_review_round does not match status_history "
            f"review rounds: expected {expected_review_round}"
        )

    expected_requires_security_review = task_requires_security_review(task_type, execution_profile)
    expected_verification_profile = infer_verification_profile(execution_profile)
    expected_agents = infer_required_agents(task_type, execution_profile)

    if task_data["requires_security_review"] != expected_requires_security_review:
        raise WorkflowError(
            "requires_security_review does not match task_type "
            f"{task_type}: expected {str(expected_requires_security_review).lower()}"
        )
    if task_data["verification_profile"] != expected_verification_profile:
        raise WorkflowError(
            "verification_profile does not match execution_profile "
            f"{execution_profile}: expected {', '.join(expected_verification_profile)}"
        )
    if task_data["required_agents"] != expected_agents:
        raise WorkflowError(
            "required_agents does not match task_type "
            f"{task_type}: expected {', '.join(expected_agents)}"
        )
    task_data["id"] = task_id
    task_data["task_type"] = task_type
    task_data["execution_profile"] = execution_profile


def validate_spec(spec_md: Path) -> None:
    spec_text = spec_md.read_text(encoding="utf-8")
    for heading in ("Acceptance", "Test Plan"):
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", spec_text, flags=re.MULTILINE):
            raise WorkflowError(f"spec.md is missing required section: {heading}")


def validate_verification_layout(verification_dir: Path, task_data: dict[str, Any]) -> None:
    verification_profile = task_data["verification_profile"]
    if not isinstance(verification_profile, list):
        raise WorkflowError("verification_profile must be a list")

    for profile in verification_profile:
        normalized = normalize_execution_profile(stringify(profile))
        profile_dir = verification_dir / execution_profile_dir(normalized)
        if profile_dir.is_symlink():
            raise WorkflowError(f"Verification profile path must not be a symlink: {profile_dir.name}")
        if not profile_dir.exists():
            raise WorkflowError(f"Missing verification profile directory: {profile_dir.name}")
        if not profile_dir.is_dir():
            raise WorkflowError(f"Verification profile path must be a directory: {profile_dir.name}")


def validate_review_requirements(review_dir: Path, task_data: dict[str, Any]) -> None:
    status = stringify(task_data["status"])
    round_number = int(task_data["current_review_round"])
    requires_security_review = bool(task_data["requires_security_review"])
    verification_profile = task_data["verification_profile"]
    requires_browser_e2e = isinstance(verification_profile, list) and "web.browser" in verification_profile

    if status in {"ready_to_merge", "done"}:
        if round_number < 1:
            raise WorkflowError("current_review_round must be >= 1 before ready_to_merge or done")

    required_review_rounds = 0
    if status == "in_review":
        required_review_rounds = max(round_number - 1, 0)
    elif status in {"ready_to_merge", "done"}:
        required_review_rounds = round_number

    if required_review_rounds:
        for review_round in range(1, required_review_rounds + 1):
            ensure_review_pair(review_dir, "code", review_round)
            if requires_security_review:
                ensure_review_pair(review_dir, "security", review_round)
            if requires_browser_e2e:
                ensure_review_pair(review_dir, "e2e", review_round)

    if status == "changes_requested":
        if round_number < 1:
            raise WorkflowError("current_review_round must be >= 1 in changes_requested")
        for review_round in range(1, round_number):
            ensure_review_pair(review_dir, "code", review_round)
            if requires_security_review:
                ensure_review_pair(review_dir, "security", review_round)
            if requires_browser_e2e:
                ensure_review_pair(review_dir, "e2e", review_round)
        ensure_review_file(review_dir, "code", round_number)
        if requires_security_review:
            ensure_review_file(review_dir, "security", round_number)
        if requires_browser_e2e:
            ensure_review_file(review_dir, "e2e", round_number)


def ensure_review_pair(review_dir: Path, review_type: str, round_number: int) -> None:
    base_name = f"{review_type}-review-round-{round_number:03d}"
    review_file = review_dir / f"{base_name}.md"
    resolved_file = review_dir / f"{base_name}.resolved.md"

    ensure_review_artifact(review_file, "review")
    ensure_review_artifact(resolved_file, "resolved review")


def ensure_review_file(review_dir: Path, review_type: str, round_number: int) -> None:
    review_file = review_dir / f"{review_type}-review-round-{round_number:03d}.md"
    ensure_review_artifact(review_file, "review")


def ensure_review_artifact(path: Path, label: str) -> None:
    if path.is_symlink():
        raise WorkflowError(f"{label.capitalize()} artifact must not be a symlink: {path.name}")
    if not path.exists():
        raise WorkflowError(f"Missing {label} file: {path.name}")
    if not path.is_file():
        raise WorkflowError(f"{label.capitalize()} artifact must be a file: {path.name}")
    if path.stat().st_size == 0:
        raise WorkflowError(f"{label.capitalize()} artifact must not be empty: {path.name}")
    validate_review_artifact_content(path, label)


def validate_review_artifact_content(path: Path, label: str) -> None:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("# "):
        raise WorkflowError(f"{label.capitalize()} artifact must start with a markdown title: {path.name}")

    required_sections = (
        [(r"^##\s+Fixes\s*$", "## Fixes"), (r"^##\s+Verification\s*$", "## Verification")]
        if label == "resolved review"
        else [(r"^##\s+Context\s*$", "## Context"), (r"^##\s+Findings\s*$", "## Findings")]
    )
    missing_sections = [display for pattern, display in required_sections if not re.search(pattern, content, flags=re.MULTILINE)]
    if missing_sections:
        raise WorkflowError(
            f"{label.capitalize()} artifact is missing required sections: {', '.join(missing_sections)}"
        )


def parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        raise WorkflowError("task.md must start with frontmatter delimited by ---")

    data: dict[str, Any] = {}
    current_key: str | None = None
    index = 1

    while index < len(lines):
        raw_line = lines[index]
        line = raw_line.rstrip()
        if line.strip() == "---":
            return data
        if not line.strip():
            index += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*$", line.strip()):
            current_key = line.strip()[:-1]
            data[current_key] = []
            index += 1
            continue
        if line.startswith("  - "):
            if current_key is None or not isinstance(data.get(current_key), list):
                raise WorkflowError(f"Invalid list item in task.md: {line.strip()}")
            data[current_key].append(line.strip()[2:].strip())
            index += 1
            continue

        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.+)$", line.strip())
        if not match:
            raise WorkflowError(f"Invalid task.md frontmatter line: {line.strip()}")

        key, raw_value = match.groups()
        data[key] = parse_scalar(raw_value)
        current_key = None
        index += 1

    raise WorkflowError("task.md frontmatter is not closed")


def parse_scalar(raw_value: str) -> Any:
    value = raw_value.strip()
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.match(r"^-?\d+$", value):
        return int(value)
    return value


def render_template(template_name: str, **context: str) -> str:
    template_path = Path(__file__).resolve().parents[1] / "templates" / template_name
    return template_path.read_text(encoding="utf-8").format(**context)


def next_index(parent_dir: Path, prefix: str) -> int:
    if not parent_dir.exists():
        return 1

    pattern = re.compile(rf"^{re.escape(prefix)}-(\d{{3}})(?:-|$)")
    seen = []
    for child in parent_dir.iterdir():
        if not child.is_dir():
            continue
        match = pattern.match(child.name)
        if match:
            seen.append(int(match.group(1)))
    return max(seen, default=0) + 1


def normalize_task_type(task_type: str) -> str:
    tokens = [slugify(token) for token in task_type.split(",") if token.strip()]
    if not tokens:
        raise WorkflowError("task_type must not be empty")
    unknown_tokens = [token for token in tokens if token not in ALLOWED_TASK_TYPE_TOKENS]
    if unknown_tokens:
        raise WorkflowError(f"Unknown task_type token(s): {', '.join(unknown_tokens)}")
    return ",".join(tokens)


def normalize_execution_profile(value: str) -> str:
    profile = value.strip().lower()
    if profile in ALLOWED_EXECUTION_PROFILES:
        return profile
    canonical = EXECUTION_PROFILE_ALIASES.get(profile)
    if canonical:
        return canonical
    raise WorkflowError(f"Unknown execution_profile: {value}")


def infer_execution_profile(task_type: str) -> str:
    tokens = set(task_type.split(","))
    if tokens & {"frontend", "e2e", "ui", "web"}:
        return "web.browser"
    if "job" in tokens:
        return "backend.job"
    if tokens & {"auth", "api", "input", "backend", "service"}:
        return "backend.http"
    return "backend.cli"


def infer_expected_review_round(history: list[str]) -> int:
    round_count = 0
    for index, status in enumerate(history):
        if status != "in_review":
            continue
        previous_non_blocked = None
        for previous_status in reversed(history[:index]):
            if previous_status != "blocked":
                previous_non_blocked = previous_status
                break
        if previous_non_blocked != "in_review":
            round_count += 1
    return round_count


def normalize_task_id(task_id: str) -> str:
    normalized = task_id.strip()
    if TASK_ID_PATTERN.fullmatch(normalized) is None:
        raise WorkflowError(f"Invalid task id: {task_id}")
    return normalized


def normalize_sprint_name(sprint_name: str) -> str:
    normalized = sprint_name.strip()
    if not SPRINT_NAME_PATTERN.fullmatch(normalized):
        raise WorkflowError("sprint must use sprint-<nnn>-<slug> format")
    return normalized


def normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise WorkflowError("title must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise WorkflowError("title must be a single line")
    return normalized


def serialize_frontmatter_string(value: str) -> str:
    return json.dumps(value)


def infer_verification_profile(execution_profile: str) -> list[str]:
    return [execution_profile]


def default_test_plan(execution_profile: str) -> str:
    profile_dir = execution_profile_dir(execution_profile)
    profile_steps = {
        "web.browser": "- Run the browser or Playwright checks that cover the affected user flow.",
        "backend.http": "- Run the HTTP-level checks that cover the affected endpoint or service flow.",
        "backend.cli": "- Run the CLI or script entrypoint and verify its exit code and outputs.",
        "backend.job": "- Trigger the job or worker path and verify the expected side effects.",
    }
    return "\n".join(
        [
            profile_steps[execution_profile],
            f"- Capture evidence under verification/{profile_dir}/.",
            "- Run the project checks that are relevant to this task.",
        ]
    )


def task_requires_security_review(task_type: str, execution_profile: str) -> bool:
    tokens = set(task_type.split(","))
    return execution_profile == "backend.http" or bool(tokens & {"auth", "input", "api"})


def infer_required_agents(task_type: str, execution_profile: str) -> list[str]:
    agents = ["planner", "tdd-guide", "code-reviewer"]
    if execution_profile == "web.browser":
        agents.append("e2e-runner")
    if task_requires_security_review(task_type, execution_profile):
        agents.append("security-reviewer")
    return agents


def validate_task_contract(task_type: str, execution_profile: str) -> None:
    tokens = set(task_type.split(","))
    browser_tokens = {"frontend", "e2e", "ui", "web", "auth"}
    http_tokens = {"auth", "api", "input", "backend", "service"}
    job_tokens = {"job", "automation"}

    if execution_profile == "web.browser" and not (tokens & browser_tokens):
        raise WorkflowError("task_type is incompatible with execution_profile web.browser")
    if execution_profile == "backend.http" and not (tokens & http_tokens):
        raise WorkflowError("task_type is incompatible with execution_profile backend.http")
    if execution_profile == "backend.job" and not (tokens & job_tokens):
        raise WorkflowError("task_type is incompatible with execution_profile backend.job")
    if execution_profile == "backend.cli" and (tokens & (browser_tokens | http_tokens | {"job"})):
        raise WorkflowError("task_type is incompatible with execution_profile backend.cli")


def get_project_dir(root: Path, project_slug: str) -> Path:
    return root / project_slug


def get_theking_dir(project_dir: Path) -> Path:
    return project_dir / THEKING_DIRNAME


def get_workflow_project_dir(project_dir: Path, project_slug: str) -> Path:
    return get_theking_dir(project_dir) / "workflows" / project_slug


def execution_profile_dir(execution_profile: str) -> str:
    return EXECUTION_PROFILE_DIRS[execution_profile]


def ensure_theking_scaffold(project_dir: Path, project_slug: str) -> None:
    theking_dir = get_theking_dir(project_dir)
    context_dir = theking_dir / "context"
    memory_dir = theking_dir / "memory"
    commands_dir = theking_dir / "commands"
    skills_dir = theking_dir / "skills"
    agents_dir = theking_dir / "agents"
    verification_dir = theking_dir / "verification"
    workflows_dir = theking_dir / "workflows"
    runs_dir = theking_dir / "runs"

    for directory in (
        context_dir,
        memory_dir,
        commands_dir,
        skills_dir,
        agents_dir,
        verification_dir,
        workflows_dir,
        runs_dir,
    ):
        ensure_local_path(directory, project_dir, directory.name)
        directory.mkdir(parents=True, exist_ok=True)

    for profile_name in EXECUTION_PROFILE_DIRS.values():
        (verification_dir / profile_name).mkdir(parents=True, exist_ok=True)

    write_if_missing(
        theking_dir / "README.md",
        render_template(
            "theking_readme.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    write_if_missing(
        theking_dir / "bootstrap.md",
        render_template(
            "theking_bootstrap.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    write_if_missing(
        context_dir / "project-overview.md",
        render_template(
            "theking_project_overview.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    write_if_missing(
        context_dir / "architecture.md",
        render_template(
            "theking_architecture.md.tmpl",
            project_slug=project_slug,
        ),
    )
    write_if_missing(
        context_dir / "dev-workflow.md",
        render_template(
            "theking_dev_workflow.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    write_if_missing(
        memory_dir / "MEMORY.md",
        render_template(
            "theking_memory.md.tmpl",
            project_slug=project_slug,
        ),
    )
    write_if_missing(
        agents_dir / "README.md",
        render_template(
            "theking_agents_readme.md.tmpl",
            project_slug=project_slug,
        ),
    )
    write_if_missing(
        agents_dir / "catalog.md",
        render_template(
            "theking_agents_catalog.md.tmpl",
            project_slug=project_slug,
        ),
    )
    write_if_missing(
        verification_dir / "README.md",
        render_template(
            "theking_verification_readme.md.tmpl",
            project_slug=project_slug,
        ),
    )


def write_if_missing(path: Path, content: str) -> None:
    if path.is_symlink():
        raise WorkflowError(f"Refusing to write through symlink: {path}")
    if path.exists():
        return
    path.write_text(content, encoding="utf-8")


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise WorkflowError(f"Unable to derive a slug from: {value!r}")
    return slug


def humanize_slug(value: str) -> str:
    return value.replace("-", " ").title()


def stringify(value: Any) -> str:
    return str(value).strip()


def ensure_within_directory(path: Path, root: Path, label: str) -> None:
    try:
        path.relative_to(root)
    except ValueError as error:
        raise WorkflowError(f"{label} must stay under {root}") from error


def ensure_local_path(path: Path, root: Path, label: str) -> None:
    resolved = path.resolve(strict=False)
    ensure_within_directory(resolved, root.resolve(), label)
    current = root.resolve()
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError as error:
        raise WorkflowError(f"{label} must stay under {root}") from error
    for part in relative_parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise WorkflowError(f"{label} must not traverse symlinks: {current}")


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise WorkflowError(f"Missing required artifact: {label}")


def ensure_file(path: Path, label: str) -> None:
    ensure_exists(path, label)
    if path.is_symlink():
        raise WorkflowError(f"Artifact must not be a symlink: {label}")
    if not path.is_file():
        raise WorkflowError(f"Artifact must be a file: {label}")


def ensure_dir(path: Path, label: str) -> None:
    ensure_exists(path, label)
    if path.is_symlink():
        raise WorkflowError(f"Artifact must not be a symlink: {label}")
    if not path.is_dir():
        raise WorkflowError(f"Artifact must be a directory: {label}")


def ensure_absent(path: Path) -> None:
    if path.is_symlink() or path.exists():
        raise WorkflowError(f"Refusing to overwrite existing file: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
