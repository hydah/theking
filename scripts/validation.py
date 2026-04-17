from __future__ import annotations

import contextlib
import json
import re
import sys
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

try:
    from .constants import (
        ALLOWED_EXECUTION_PROFILES,
        ALLOWED_STATUSES,
        ALLOWED_TASK_TYPE_TOKENS,
        ALLOWED_TRANSITIONS,
        EXECUTION_PROFILE_ALIASES,
        EXECUTION_PROFILE_DIRS,
        SPRINT_NAME_PATTERN,
        TASK_ID_PATTERN,
        THEKING_DIRNAME,
        WorkflowError,
    )
except ImportError:
    from constants import (
        ALLOWED_EXECUTION_PROFILES,
        ALLOWED_STATUSES,
        ALLOWED_TASK_TYPE_TOKENS,
        ALLOWED_TRANSITIONS,
        EXECUTION_PROFILE_ALIASES,
        EXECUTION_PROFILE_DIRS,
        SPRINT_NAME_PATTERN,
        TASK_ID_PATTERN,
        THEKING_DIRNAME,
        WorkflowError,
    )


def check_dag(adjacency: dict[str, list[str]]) -> None:
    """Detect cycles in a directed graph. Raises WorkflowError if a cycle is found."""
    visited: set[str] = set()
    in_stack: set[str] = set()

    def dfs(node: str) -> None:
        if node in in_stack:
            raise WorkflowError(f"Circular dependency detected involving: {node}")
        if node in visited:
            return
        in_stack.add(node)
        for neighbor in adjacency.get(node, []):
            dfs(neighbor)
        in_stack.discard(node)
        visited.add(node)

    for node in adjacency:
        dfs(node)


@dataclass(frozen=True)
class TaskPaths:
    project_dir: Path
    theking_dir: Path
    workflow_project_dir: Path
    sprint_dir: Path
    task_dir: Path
    task_md: Path
    spec_md: Path
    review_dir: Path
    verification_dir: Path


def derive_task_paths(task_dir: Path) -> TaskPaths:
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

    return TaskPaths(
        project_dir=project_dir,
        theking_dir=theking_dir,
        workflow_project_dir=workflow_project_dir,
        sprint_dir=sprint_dir,
        task_dir=task_dir,
        task_md=task_dir / "task.md",
        spec_md=task_dir / "spec.md",
        review_dir=task_dir / "review",
        verification_dir=task_dir / "verification",
    )


def validate_task_dir(task_dir: Path) -> None:
    task_paths = derive_task_paths(task_dir)
    ensure_local_path(task_paths.task_dir, task_paths.project_dir, "task")
    ensure_dir(task_paths.task_dir, task_paths.task_dir.name)

    ensure_local_path(task_paths.task_md, task_paths.project_dir, "task.md")
    ensure_local_path(task_paths.spec_md, task_paths.project_dir, "spec.md")
    ensure_local_path(task_paths.review_dir, task_paths.project_dir, "review")
    ensure_local_path(task_paths.verification_dir, task_paths.project_dir, "verification")
    ensure_file(task_paths.workflow_project_dir / "project.md", "project.md")
    ensure_file(task_paths.sprint_dir / "sprint.md", "sprint.md")
    ensure_file(task_paths.task_md, "task.md")
    ensure_file(task_paths.spec_md, "spec.md")
    ensure_dir(task_paths.review_dir, "review")
    ensure_dir(task_paths.verification_dir, "verification")

    task_data = parse_frontmatter(task_paths.task_md.read_text(encoding="utf-8"))
    validated = validate_task_metadata(task_data)
    if stringify(validated["id"]) != task_paths.task_dir.name:
        raise WorkflowError("task id must match the task directory name")
    validate_verification_layout(task_paths.verification_dir, validated)
    validate_spec(
        task_paths.spec_md,
        require_content=spec_requires_content(validated["status_history"]),
    )
    validate_review_requirements(task_paths.review_dir, validated)


def validate_task_location(task_dir: Path) -> None:
    derive_task_paths(task_dir)


def validate_task_metadata(task_data: dict[str, Any]) -> dict[str, Any]:
    """Validate task metadata. Returns a new dict with normalized fields."""
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
        "depends_on",
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

    for index, (current, nxt) in enumerate(zip(history, history[1:], strict=False)):
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

    depends_on = task_data["depends_on"]
    if not isinstance(depends_on, list):
        raise WorkflowError("depends_on must be a list")
    for dep in depends_on:
        dep_str = stringify(dep)
        if TASK_ID_PATTERN.fullmatch(dep_str) is None:
            raise WorkflowError(f"Invalid depends_on entry: {dep_str}")

    return {
        **task_data,
        "id": task_id,
        "task_type": task_type,
        "execution_profile": execution_profile,
    }


def validate_spec(spec_md: Path, *, require_content: bool) -> None:
    spec_text = spec_md.read_text(encoding="utf-8")
    sections = collect_spec_sections(spec_text)
    if not require_content and is_legacy_spec_structure(sections):
        return

    for heading in ("Scope", "Non-Goals", "Acceptance", "Test Plan", "Edge Cases"):
        section_body = sections.get(heading)
        if section_body is None:
            raise WorkflowError(f"spec.md is missing required section: {heading}")
        if require_content and not spec_section_has_content(section_body):
            raise WorkflowError(f"spec.md section must not be empty: {heading}")


def collect_spec_sections(spec_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for heading in ("Scope", "Non-Goals", "Acceptance", "Test Plan", "Edge Cases"):
        match = re.search(
            rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
            spec_text,
            flags=re.MULTILINE | re.DOTALL,
        )
        if match is not None:
            sections[heading] = match.group("body")
    return sections


def is_legacy_spec_structure(sections: dict[str, str]) -> bool:
    return set(sections) == {"Acceptance", "Test Plan"}


def spec_requires_content(status_history: list[str]) -> bool:
    effective_status = spec_validation_status(status_history)
    return effective_status not in {"draft", "planned"}


def spec_validation_status(status_history: list[str]) -> str:
    current_status = stringify(status_history[-1])
    if current_status == "blocked":
        normalized_history = [stringify(status) for status in status_history]
        return infer_blocked_resume_status(normalized_history)
    return current_status


def spec_section_has_content(section_body: str) -> bool:
    stripped_comments = re.sub(r"<!--.*?-->", "", section_body, flags=re.DOTALL)
    for raw_line in stripped_comments.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*+]\s*", "", line)
        line = re.sub(r"^\[[ xX]\]\s*", "", line)
        if line:
            return True
    return False


def has_non_empty_verification_evidence(profile_dir: Path) -> bool:
    for artifact in sorted(profile_dir.rglob("*"), key=lambda path: path.as_posix()):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        if artifact.stat().st_size > 0:
            return True
    return False


def validate_verification_layout(verification_dir: Path, task_data: dict[str, Any]) -> None:
    verification_profile = task_data["verification_profile"]
    if not isinstance(verification_profile, list):
        raise WorkflowError("verification_profile must be a list")

    status = stringify(task_data["status"])

    for profile in verification_profile:
        normalized = normalize_execution_profile(stringify(profile))
        profile_dir = verification_dir / execution_profile_dir(normalized)
        if profile_dir.is_symlink():
            raise WorkflowError(f"Verification profile path must not be a symlink: {profile_dir.name}")
        if not profile_dir.exists():
            raise WorkflowError(f"Missing verification profile directory: {profile_dir.name}")
        if not profile_dir.is_dir():
            raise WorkflowError(f"Verification profile path must be a directory: {profile_dir.name}")
        if status in {"ready_to_merge", "done"} and not has_non_empty_verification_evidence(profile_dir):
            raise WorkflowError(
                "Verification profile directory must contain at least one non-empty evidence file "
                f"before {status}: {profile_dir.name}"
            )


def validate_review_requirements(review_dir: Path, task_data: dict[str, Any]) -> None:
    status = stringify(task_data["status"])
    round_number = int(task_data["current_review_round"])
    requires_security_review = bool(task_data["requires_security_review"])
    verification_profile = task_data["verification_profile"]
    requires_browser_e2e = isinstance(verification_profile, list) and "web.browser" in verification_profile

    if status in {"ready_to_merge", "done"} and round_number < 1:
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


def validate_sprint_location(sprint_dir: Path) -> None:
    expected_layout = (
        "sprint_dir must live under .theking/workflows/<project>/sprints/"
        "sprint-<nnn>-<slug>"
    )
    try:
        normalize_sprint_name(sprint_dir.name)
    except WorkflowError as error:
        raise WorkflowError(expected_layout) from error

    sprints_dir = sprint_dir.parent
    workflow_project_dir = sprints_dir.parent
    workflows_dir = workflow_project_dir.parent
    theking_dir = workflows_dir.parent
    project_dir = theking_dir.parent

    if sprints_dir.name != "sprints":
        raise WorkflowError(expected_layout)
    if workflows_dir.name != "workflows":
        raise WorkflowError(expected_layout)
    if theking_dir.name != THEKING_DIRNAME:
        raise WorkflowError(expected_layout)
    if slugify(workflow_project_dir.name) != workflow_project_dir.name:
        raise WorkflowError(expected_layout)
    if workflow_project_dir.name != slugify(project_dir.name):
        raise WorkflowError(expected_layout)


def validate_sprint_dir(sprint_dir: Path) -> None:
    validate_sprint_location(sprint_dir)
    ensure_file(sprint_dir / "sprint.md", "sprint.md")
    tasks_dir = sprint_dir / "tasks"
    ensure_dir(tasks_dir, "tasks")

    task_dirs: list[Path] = []
    for child in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
        if child.is_symlink():
            raise WorkflowError(f"Task artifact must not be a symlink: {child.name}")
        if child.is_dir() and TASK_ID_PATTERN.fullmatch(child.name):
            task_dirs.append(child)

    if not task_dirs:
        print(f"No tasks found in {sprint_dir}", file=sys.stderr)
        return

    all_task_ids: set[str] = {d.name for d in task_dirs}
    all_depends_on: dict[str, list[str]] = {}

    for task_dir in task_dirs:
        validate_task_dir(task_dir)
        task_md = task_dir / "task.md"
        task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
        depends_on = task_data.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise WorkflowError(f"depends_on must be a list in {task_dir.name}")

        for dep in depends_on:
            dep_str = stringify(dep)
            if dep_str not in all_task_ids:
                raise WorkflowError(
                    f"Task {task_dir.name} depends on {dep_str} which does not exist in this sprint"
                )
        all_depends_on[task_dir.name] = [stringify(d) for d in depends_on]

    check_dag(all_depends_on)


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


# --- Parsing ---

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


def split_frontmatter_document(text: str) -> tuple[dict[str, Any], str]:
    data = parse_frontmatter(text)
    lines = text.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return data, "\n".join(lines[index + 1:])
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


# --- Normalizers ---

def normalize_task_type(task_type: str) -> str:
    tokens = [slugify(token) for token in task_type.split(",") if token.strip()]
    if not tokens:
        raise WorkflowError("task_type must not be empty")
    unknown_tokens = [token for token in tokens if token not in ALLOWED_TASK_TYPE_TOKENS]
    if unknown_tokens:
        allowed = ", ".join(sorted(ALLOWED_TASK_TYPE_TOKENS))
        raise WorkflowError(
            f"Unknown task_type token(s): {', '.join(unknown_tokens)}. "
            f"Allowed tokens: {allowed}."
        )
    return ",".join(tokens)


def normalize_execution_profile(value: str) -> str:
    profile = value.strip().lower()
    if profile in ALLOWED_EXECUTION_PROFILES:
        return profile
    canonical = EXECUTION_PROFILE_ALIASES.get(profile)
    if canonical:
        return canonical
    raise WorkflowError(
        f"Unknown execution_profile: {value}. "
        f"Allowed values: {', '.join(sorted(ALLOWED_EXECUTION_PROFILES))}."
    )


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


def normalize_status(status: str) -> str:
    normalized = status.strip()
    if normalized not in ALLOWED_STATUSES:
        raise WorkflowError(f"Unknown status: {status}")
    return normalized


# --- Inference ---

def infer_execution_profile(task_type: str) -> str:
    tokens = set(task_type.split(","))
    if tokens & {"frontend", "e2e", "ui", "web"}:
        return "web.browser"
    if tokens & {"job", "automation"}:
        return "backend.job"
    # Note: plain `backend` is intentionally excluded from the HTTP set.
    # `backend` is ambiguous between "backend library" and "backend server";
    # we default it to backend.cli (library) and require users to combine
    # `backend` with `api` / `service` — or set execution_profile explicitly —
    # when they actually want an HTTP surface. This avoids dragging a
    # rubber-stamp security-reviewer onto every library task.
    if tokens & {"auth", "api", "input", "service"}:
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


def infer_blocked_resume_status(history: list[str]) -> str:
    for previous_status in reversed(history[:-1]):
        if previous_status != "blocked":
            return previous_status
    raise WorkflowError("blocked tasks must resume to the prior non-blocked status")


def infer_verification_profile(execution_profile: str) -> list[str]:
    return [execution_profile]


def infer_required_agents(task_type: str, execution_profile: str) -> list[str]:
    agents = ["planner", "tdd-guide", "code-reviewer"]
    if execution_profile == "web.browser":
        agents.append("e2e-runner")
    if task_requires_security_review(task_type, execution_profile):
        agents.append("security-reviewer")
    return agents


def task_requires_security_review(task_type: str, execution_profile: str) -> bool:
    tokens = set(task_type.split(","))
    return execution_profile == "backend.http" or bool(tokens & {"auth", "input", "api"})


def validate_task_contract(task_type: str, execution_profile: str) -> None:
    tokens = set(task_type.split(","))
    browser_tokens = {"frontend", "e2e", "ui", "web", "auth"}
    # `backend` is kept here for backward compat (pre-existing tasks that use
    # backend + backend.http stay valid), but `infer_execution_profile` no
    # longer maps plain `backend` to backend.http.
    http_tokens = {"auth", "api", "input", "backend", "service"}
    job_tokens = {"job", "automation"}
    # Tokens that are strictly illegal on backend.cli. `backend` is NOT in this
    # set — it is ambiguous and the CLI (library) interpretation is valid.
    cli_forbidden_tokens = (
        browser_tokens | {"api", "input", "service", "job"}
    )

    def _hint(profile: str, allowed: set[str]) -> str:
        tokens_list = ", ".join(sorted(allowed))
        return (
            f"task_type is incompatible with execution_profile {profile}. "
            f"For {profile}, task_type must include at least one of: {tokens_list}. "
            f"Got task_type={task_type!r}. "
            "Hint: see `.theking/agents/planner.md` for the task_type × execution_profile matrix."
        )

    if execution_profile == "web.browser" and not (tokens & browser_tokens):
        raise WorkflowError(_hint("web.browser", browser_tokens))
    if execution_profile == "backend.http" and not (tokens & http_tokens):
        raise WorkflowError(_hint("backend.http", http_tokens))
    if execution_profile == "backend.job" and not (tokens & job_tokens):
        raise WorkflowError(_hint("backend.job", job_tokens))
    if execution_profile == "backend.cli" and (tokens & cli_forbidden_tokens):
        forbidden = tokens & cli_forbidden_tokens
        raise WorkflowError(
            "task_type is incompatible with execution_profile backend.cli. "
            f"backend.cli forbids task_type tokens: {', '.join(sorted(forbidden))}. "
            "Use general / backend / cli / tooling / script / automation for CLI tasks, "
            "or switch execution_profile to the matching profile "
            "(web.browser / backend.http / backend.job). "
            "Hint: see `.theking/agents/planner.md` for the task_type × execution_profile matrix."
        )


# --- Path helpers ---

def execution_profile_dir(execution_profile: str) -> str:
    return EXECUTION_PROFILE_DIRS[execution_profile]


def default_test_plan(execution_profile: str) -> str:
    profile_dir = execution_profile_dir(execution_profile)
    profile_steps = {
        "web.browser": "- Run a real browser smoke or lightweight E2E flow that covers the affected user path.",
        "backend.http": "- Run a real request or integration-style check that covers the affected endpoint or service flow.",
        "backend.cli": "- Run the CLI or script entrypoint and verify its exit code, outputs, and failure path.",
        "backend.job": "- Trigger the job or worker path and verify the expected side effects end to end.",
    }
    return "\n".join(
        [
            profile_steps[execution_profile],
            "- Run the relevant build/lint/type/unit checks for the changed code path before asking for review.",
            f"- Capture evidence under verification/{profile_dir}/.",
            "- If automation is missing, record the gap and the minimum manual verification that was performed.",
        ]
    )


def serialize_frontmatter_string(value: str) -> str:
    return json.dumps(value)


def serialize_task_frontmatter(task_data: dict[str, Any]) -> str:
    lines = [
        "---",
        f"id: {stringify(task_data['id'])}",
        f"title: {serialize_frontmatter_string(stringify(task_data['title']))}",
        f"status: {normalize_status(stringify(task_data['status']))}",
        "status_history:",
        *[f"  - {stringify(entry)}" for entry in task_data["status_history"]],
        f"task_type: {stringify(task_data['task_type'])}",
        f"execution_profile: {stringify(task_data['execution_profile'])}",
        "verification_profile:",
        *[f"  - {stringify(entry)}" for entry in task_data["verification_profile"]],
        f"requires_security_review: {'true' if bool(task_data['requires_security_review']) else 'false'}",
        "required_agents:",
        *[f"  - {stringify(agent)}" for agent in task_data["required_agents"]],
        "depends_on:",
        *[f"  - {stringify(dep)}" for dep in task_data["depends_on"]],
        f"current_review_round: {int(task_data['current_review_round'])}",
        "---",
    ]
    return "\n".join(lines)


def write_task_document(task_md: Path, task_data: dict[str, Any], body: str) -> None:
    frontmatter_text = serialize_task_frontmatter(task_data)
    rendered = frontmatter_text + (f"\n{body}" if body else "\n")
    task_md.write_text(rendered, encoding="utf-8")


def load_task_document(task_md: Path) -> tuple[dict[str, Any], str]:
    task_data, body = split_frontmatter_document(task_md.read_text(encoding="utf-8"))
    return validate_task_metadata(task_data), body


STATUS_NEXT_STEP_HINTS: dict[str, str] = {
    "draft": "run `workflowctl advance-status --to-status planned` after writing spec.md",
    "planned": "write the failing test(s) and run `workflowctl advance-status --to-status red`",
    "red": "make the tests pass, then `workflowctl advance-status --to-status green`",
    "green": (
        "run `workflowctl init-review-round --task-dir <TASK_DIR>` to enter in_review "
        "(do NOT advance-status directly; init-review-round scaffolds the review files)"
    ),
    "in_review": (
        "after reviewer produces findings: if none, `workflowctl advance-status --to-status "
        "ready_to_merge`; if there are findings, `advance-status --to-status changes_requested`"
    ),
    "changes_requested": (
        "go back to `red` to add/strengthen tests, then through `green` and re-run "
        "`workflowctl init-review-round` to open the next round"
    ),
    "ready_to_merge": "run `workflowctl advance-status --to-status done`",
    "done": "this task is terminal; start a new task or close the sprint",
    "blocked": "resume with `workflowctl advance-status --to-status <previous status>` once unblocked",
}


def _next_step_hint(current_status: str, allowed_moves: list[str]) -> str:
    primary = STATUS_NEXT_STEP_HINTS.get(current_status)
    if primary:
        return primary
    if allowed_moves:
        return f"try `workflowctl advance-status --to-status {allowed_moves[0]}`"
    return "this state has no outgoing transitions"


def apply_status_transition(task_data: dict[str, Any], to_status: str) -> dict[str, Any]:
    validated_task = validate_task_metadata(task_data)
    current_status = normalize_status(stringify(validated_task["status"]))
    target_status = normalize_status(to_status)

    if current_status == target_status:
        raise WorkflowError(f"Task is already in status: {target_status}")
    if current_status == "blocked":
        resume_status = infer_blocked_resume_status(validated_task["status_history"])
        if target_status != resume_status:
            raise WorkflowError(
                "blocked tasks must resume to the prior non-blocked status. "
                f"Expected next status: {resume_status}. "
                f"Hint: workflowctl advance-status --to-status {resume_status}"
            )
    elif target_status == "blocked":
        if current_status == "done":
            raise WorkflowError("done cannot transition to blocked")
    elif target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        allowed_moves = sorted(ALLOWED_TRANSITIONS.get(current_status, set()))
        moves_text = ", ".join(allowed_moves) if allowed_moves else "(terminal state)"
        hint = _next_step_hint(current_status, allowed_moves)
        raise WorkflowError(
            f"Illegal status transition: {current_status} -> {target_status}. "
            f"From '{current_status}' you can only go to: {moves_text}. "
            f"Hint: {hint}"
        )

    status_history = [*validated_task["status_history"], target_status]
    updated_task = {
        **validated_task,
        "status": target_status,
        "status_history": status_history,
        "current_review_round": infer_expected_review_round(status_history),
    }
    return validate_task_metadata(updated_task)


def review_type_specs_for_task(task_data: dict[str, Any]) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = [("code", "Code")]
    if bool(task_data["requires_security_review"]):
        specs.append(("security", "Security"))
    if "web.browser" in task_data["verification_profile"]:
        specs.append(("e2e", "E2E"))
    return specs


def get_project_dir(root: Path, project_slug: str) -> Path:
    return root / project_slug


def get_theking_dir(project_dir: Path) -> Path:
    return project_dir / THEKING_DIRNAME


def get_workflow_project_dir(project_dir: Path, project_slug: str) -> Path:
    return get_theking_dir(project_dir) / "workflows" / project_slug


def find_theking_dir(path: Path) -> Path | None:
    current = path
    for _ in range(10):
        candidate = current / THEKING_DIRNAME
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


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


# --- Template rendering ---

SOURCE_TEMPLATES_ROOT = Path(__file__).resolve().parents[1] / "templates"


def template_roots() -> list[Any]:
    roots: list[Any] = []
    with contextlib.suppress(ModuleNotFoundError):
        roots.append(resources.files("theking.templates"))
    roots.append(SOURCE_TEMPLATES_ROOT)
    return roots


def resolve_template_path(template_name: str) -> Any:
    """Resolve a template name to a file-like resource, searching subdirectories."""
    for template_root in template_roots():
        direct = template_root.joinpath(template_name)
        if direct.is_file():
            return direct
        for subdir in template_root.iterdir():
            if subdir.is_dir():
                candidate = subdir.joinpath(template_name)
                if candidate.is_file():
                    return candidate
    raise WorkflowError(f"Template not found: {template_name}")


def render_template(template_name: str, **context: str) -> str:
    template_path = resolve_template_path(template_name)
    return template_path.read_text(encoding="utf-8").format(**context)


def read_template_raw(template_name: str) -> str:
    template_path = resolve_template_path(template_name)
    return template_path.read_text(encoding="utf-8")


# --- Filesystem guards ---

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


def ensure_tree_has_no_symlinks(directory: Path, root: Path, label: str) -> None:
    ensure_local_path(directory, root, label)
    if directory.is_symlink():
        raise WorkflowError(f"{label} must not be a symlink: {directory}")
    if not directory.exists():
        return
    if not directory.is_dir():
        raise WorkflowError(f"{label} must be a directory: {directory}")
    for child in directory.rglob("*"):
        if child.is_symlink():
            raise WorkflowError(f"{label} must not contain symlinks: {child}")


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


def write_if_missing(path: Path, content: str, legacy_path: Path | None = None) -> None:
    if path.is_symlink():
        raise WorkflowError(f"Refusing to write through symlink: {path}")
    if path.exists():
        if not path.is_file():
            raise WorkflowError(f"Refusing to overwrite non-file path: {path}")
        if legacy_path is not None:
            if legacy_path.is_symlink():
                raise WorkflowError(f"Refusing to migrate through symlink: {legacy_path}")
            if legacy_path.exists():
                if not legacy_path.is_file():
                    raise WorkflowError(f"Legacy artifact must be a file before migrating: {legacy_path}")
                if path.read_text(encoding="utf-8") != legacy_path.read_text(encoding="utf-8"):
                    raise WorkflowError(
                        f"Canonical artifact conflicts with legacy artifact: {path} vs {legacy_path}"
                    )
        return
    if legacy_path is not None:
        if legacy_path.is_symlink():
            raise WorkflowError(f"Refusing to migrate through symlink: {legacy_path}")
        if legacy_path.exists():
            if not legacy_path.is_file():
                raise WorkflowError(f"Legacy artifact must be a file before migrating: {legacy_path}")
            path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
            return
    path.write_text(content, encoding="utf-8")


THEKING_REFERENCE_BLOCK = """
---

## Project Knowledge Base

> This project uses [theking](.theking/bootstrap.md) for project knowledge and workflow governance.
> Read [`.theking/bootstrap.md`](.theking/bootstrap.md) for the full context index.
"""


def append_theking_reference(path: Path) -> None:
    """Append a theking reference block to an existing runtime entry file.

    If *path* is a symlink, resolve it to the real target and append there.
    This preserves the symlink itself while modifying the underlying file.
    """
    real_path = path.resolve() if path.is_symlink() else path
    existing = real_path.read_text(encoding="utf-8")
    real_path.write_text(existing.rstrip() + "\n" + THEKING_REFERENCE_BLOCK, encoding="utf-8")
