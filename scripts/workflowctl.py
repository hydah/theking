from __future__ import annotations

import argparse
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
    init_task.set_defaults(handler=handle_init_task)

    check = subparsers.add_parser("check")
    check.add_argument("--task-dir", required=True)
    check.set_defaults(handler=handle_check)

    return parser


def handle_init_project(args: argparse.Namespace) -> None:
    root = Path(args.root).expanduser().resolve()
    project_slug = slugify(args.project_slug)
    project_dir = root / project_slug
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "sprints").mkdir(exist_ok=True)

    project_md = project_dir / "project.md"
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
    project_dir = root / project_slug
    ensure_exists(project_dir / "project.md", "project.md")

    sprints_dir = project_dir / "sprints"
    sprint_number = next_index(sprints_dir, "sprint")
    sprint_name = f"sprint-{sprint_number:03d}-{theme_slug}"
    sprint_dir = sprints_dir / sprint_name
    sprint_dir.mkdir(parents=True, exist_ok=False)
    (sprint_dir / "tasks").mkdir(exist_ok=True)

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
    sprint_name = args.sprint.strip()
    task_slug = slugify(args.slug)
    title = args.title.strip()
    task_type = normalize_task_type(args.task_type)

    sprint_dir = root / project_slug / "sprints" / sprint_name
    ensure_exists(sprint_dir / "sprint.md", "sprint.md")

    tasks_dir = sprint_dir / "tasks"
    task_number = next_index(tasks_dir, "TASK")
    task_id = f"TASK-{task_number:03d}-{task_slug}"
    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    (task_dir / "review").mkdir(exist_ok=True)

    requires_e2e = task_requires_e2e(task_type)
    requires_security_review = task_requires_security_review(task_type)
    required_agents = infer_required_agents(task_type)

    task_md = task_dir / "task.md"
    task_md.write_text(
        render_template(
            "task.md.tmpl",
            task_id=task_id,
            task_title=title,
            task_type=task_type,
            requires_e2e=str(requires_e2e).lower(),
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
            test_plan="- Run unit tests for workflowctl.\n- Validate the generated task tree with workflowctl check.",
        ),
        encoding="utf-8",
    )

    print(task_dir)


def handle_check(args: argparse.Namespace) -> None:
    task_dir = Path(args.task_dir).expanduser().resolve()
    validate_task_dir(task_dir)
    print(f"OK {task_dir}")


def validate_task_dir(task_dir: Path) -> None:
    ensure_exists(task_dir, task_dir.name)
    task_md = task_dir / "task.md"
    spec_md = task_dir / "spec.md"
    review_dir = task_dir / "review"

    ensure_exists(task_md, "task.md")
    ensure_exists(spec_md, "spec.md")
    ensure_exists(review_dir, "review")

    task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
    validate_task_metadata(task_data)
    validate_spec(spec_md)
    validate_review_requirements(review_dir, task_data)


def validate_task_metadata(task_data: dict[str, Any]) -> None:
    required_fields = {
        "id",
        "title",
        "status",
        "status_history",
        "task_type",
        "requires_e2e",
        "requires_security_review",
        "required_agents",
        "current_review_round",
    }
    missing = sorted(required_fields - set(task_data))
    if missing:
        raise WorkflowError(f"task.md is missing required fields: {', '.join(missing)}")

    status = stringify(task_data["status"])
    history = task_data["status_history"]
    task_type = stringify(task_data["task_type"])
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

    if not isinstance(task_data["requires_e2e"], bool):
        raise WorkflowError("requires_e2e must be a boolean")
    if not isinstance(task_data["requires_security_review"], bool):
        raise WorkflowError("requires_security_review must be a boolean")
    if not isinstance(task_data["required_agents"], list) or not task_data["required_agents"]:
        raise WorkflowError("required_agents must be a non-empty list")

    if not isinstance(task_data["current_review_round"], int) or task_data["current_review_round"] < 0:
        raise WorkflowError("current_review_round must be a non-negative integer")

    expected_requires_e2e = task_requires_e2e(task_type)
    expected_requires_security_review = task_requires_security_review(task_type)
    expected_agents = infer_required_agents(task_type)

    if task_data["requires_e2e"] != expected_requires_e2e:
        raise WorkflowError(
            f"requires_e2e does not match task_type {task_type}: expected {str(expected_requires_e2e).lower()}"
        )
    if task_data["requires_security_review"] != expected_requires_security_review:
        raise WorkflowError(
            "requires_security_review does not match task_type "
            f"{task_type}: expected {str(expected_requires_security_review).lower()}"
        )
    if task_data["required_agents"] != expected_agents:
        raise WorkflowError(
            "required_agents does not match task_type "
            f"{task_type}: expected {', '.join(expected_agents)}"
        )


def validate_spec(spec_md: Path) -> None:
    spec_text = spec_md.read_text(encoding="utf-8")
    for heading in ("Acceptance", "Test Plan"):
        if not re.search(rf"^##\s+{re.escape(heading)}\s*$", spec_text, flags=re.MULTILINE):
            raise WorkflowError(f"spec.md is missing required section: {heading}")


def validate_review_requirements(review_dir: Path, task_data: dict[str, Any]) -> None:
    status = stringify(task_data["status"])
    round_number = int(task_data["current_review_round"])
    requires_security_review = bool(task_data["requires_security_review"])
    requires_e2e = bool(task_data["requires_e2e"])

    if status in {"ready_to_merge", "done"}:
        if round_number < 1:
            raise WorkflowError("current_review_round must be >= 1 before ready_to_merge or done")
        ensure_review_pair(review_dir, "code", round_number)
        if requires_security_review:
            ensure_review_pair(review_dir, "security", round_number)
        if requires_e2e:
            ensure_review_pair(review_dir, "e2e", round_number)


def ensure_review_pair(review_dir: Path, review_type: str, round_number: int) -> None:
    base_name = f"{review_type}-review-round-{round_number:03d}"
    review_file = review_dir / f"{base_name}.md"
    resolved_file = review_dir / f"{base_name}.resolved.md"

    if not review_file.exists():
        raise WorkflowError(f"Missing review file: {review_file.name}")
    if not resolved_file.exists():
        raise WorkflowError(f"Missing resolved review file: {resolved_file.name}")


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
    return ",".join(tokens)


def task_requires_e2e(task_type: str) -> bool:
    tokens = set(task_type.split(","))
    return bool(tokens & {"frontend", "e2e", "ui"})


def task_requires_security_review(task_type: str) -> bool:
    tokens = set(task_type.split(","))
    return bool(tokens & {"auth", "input", "api"})


def infer_required_agents(task_type: str) -> list[str]:
    agents = ["planner", "tdd-guide", "code-reviewer"]
    if task_requires_e2e(task_type):
        agents.append("e2e-runner")
    if task_requires_security_review(task_type):
        agents.append("security-reviewer")
    return agents


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


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise WorkflowError(f"Missing required artifact: {label}")


def ensure_absent(path: Path) -> None:
    if path.exists():
        raise WorkflowError(f"Refusing to overwrite existing file: {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
