"""Decree checkpoint + active task recovery helpers.

These live outside :mod:`workflowctl` because they only depend on
``constants`` and ``validation`` and are reused by several CLI handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .constants import WorkflowError
    from .validation import (
        derive_task_paths,
        ensure_file,
        ensure_local_path,
        get_theking_dir,
        get_workflow_project_dir,
        infer_blocked_resume_status,
        load_task_document,
        parse_frontmatter,
        review_type_specs_for_task,
        serialize_frontmatter_string,
        stringify,
        validate_spec,
    )
except ImportError:
    from constants import WorkflowError
    from validation import (
        derive_task_paths,
        ensure_file,
        ensure_local_path,
        get_theking_dir,
        get_workflow_project_dir,
        infer_blocked_resume_status,
        load_task_document,
        parse_frontmatter,
        review_type_specs_for_task,
        serialize_frontmatter_string,
        stringify,
        validate_spec,
    )


DEGREE_CHECKPOINT_FILENAME = "decree-session.md"


def get_state_dir(project_dir: Path) -> Path:
    return get_theking_dir(project_dir) / "state"


def get_session_dir(project_dir: Path) -> Path:
    return get_state_dir(project_dir) / "session"


def get_decree_checkpoint_path(project_dir: Path) -> Path:
    return get_session_dir(project_dir) / DEGREE_CHECKPOINT_FILENAME


def load_decree_checkpoint(project_dir: Path) -> dict[str, Any] | None:
    checkpoint_path = get_decree_checkpoint_path(project_dir)
    ensure_local_path(checkpoint_path, project_dir, "decree checkpoint")
    if not checkpoint_path.exists():
        return None
    ensure_file(checkpoint_path, DEGREE_CHECKPOINT_FILENAME)
    return parse_frontmatter(checkpoint_path.read_text(encoding="utf-8"))


def load_active_task_status(project_dir: Path) -> dict[str, str] | None:
    active_task_file = get_theking_dir(project_dir) / "active-task"
    ensure_local_path(active_task_file, project_dir, "active-task")
    if not active_task_file.exists():
        return None
    ensure_file(active_task_file, "active-task")
    active_task_text = active_task_file.read_text(encoding="utf-8").strip()
    if not active_task_text:
        raise WorkflowError("active-task is empty; run workflowctl activate again")
    task_dir = Path(active_task_text).expanduser()
    if task_dir.is_symlink():
        raise WorkflowError(f"active-task must not point to a symlinked task directory: {task_dir}")
    resolved_task_dir = task_dir.resolve()
    ensure_local_path(resolved_task_dir, project_dir, "active task")
    try:
        task_paths = derive_task_paths(resolved_task_dir)
        ensure_file(task_paths.task_md, "task.md")
        task_data, _body = load_task_document(task_paths.task_md)
    except WorkflowError as error:
        raise WorkflowError(
            f"active-task does not point to a valid task directory; run workflowctl activate again. ({error})"
        ) from error
    return summarize_task_status(task_paths, task_data)


def find_latest_unfinished_task(project_dir: Path, project_slug: str) -> dict[str, str] | None:
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)
    ensure_local_path(workflow_project_dir, project_dir, "workflow project")
    if not workflow_project_dir.exists():
        return None
    sprints_dir = workflow_project_dir / "sprints"
    if not sprints_dir.exists():
        return None

    task_summaries: list[dict[str, str]] = []
    for sprint_dir in sorted(sprints_dir.iterdir(), key=lambda path: path.name, reverse=True):
        if sprint_dir.is_symlink() or not sprint_dir.is_dir():
            continue
        tasks_dir = sprint_dir / "tasks"
        if tasks_dir.is_symlink() or not tasks_dir.is_dir():
            continue
        for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
            if task_dir.is_symlink() or not task_dir.is_dir():
                continue
            try:
                task_paths = derive_task_paths(task_dir)
                task_data, _body = load_task_document(task_paths.task_md)
            except WorkflowError:
                continue
            if stringify(task_data["status"]) == "done":
                continue
            task_summaries.append(summarize_task_status(task_paths, task_data))

    return task_summaries[0] if task_summaries else None


def summarize_task_status(task_paths: Any, task_data: dict[str, Any]) -> dict[str, str]:
    return {
        "task_id": stringify(task_data["id"]),
        "status": stringify(task_data["status"]),
        "task_dir": task_paths.task_dir.relative_to(task_paths.project_dir).as_posix(),
        "current_review_round": str(int(task_data["current_review_round"])),
        "next_step": infer_task_next_step(task_paths, task_data),
    }


def infer_task_next_step(task_paths: Any, task_data: dict[str, Any]) -> str:
    status = stringify(task_data["status"])
    task_dir_relative = task_paths.task_dir.relative_to(task_paths.project_dir).as_posix()
    if status == "blocked":
        resume_status = infer_blocked_resume_status([stringify(entry) for entry in task_data["status_history"]])
        if resume_status == "in_review":
            return (
                "resolve the blocker, then run "
                f"workflowctl advance-status --task-dir {task_dir_relative} --to-status in_review "
                f"to resume review round {int(task_data['current_review_round']):03d}"
            )
        return (
            "resolve the blocker, then run "
            f"workflowctl advance-status --task-dir {task_dir_relative} --to-status {resume_status}"
        )
    if status == "draft":
        return (
            "review the task scope and run "
            f"workflowctl advance-status --task-dir {task_dir_relative} --to-status planned when the task is ready"
        )
    if status == "planned":
        try:
            validate_spec(task_paths.spec_md, require_content=True)
        except WorkflowError:
            return "finish the five spec sections, then write failing tests and advance to red"
        return f"write failing tests, then run workflowctl advance-status --task-dir {task_dir_relative} --to-status red"
    if status == "red":
        return "finish the red-phase tests and minimal implementation needed to reach green"
    if status == "green":
        return (
            f"run build/lint/type/unit plus profile verification, capture evidence, "
            f"then workflowctl init-review-round --task-dir {task_dir_relative}"
        )
    if status == "in_review":
        review_labels = ", ".join(label for _review_type, label in review_type_specs_for_task(task_data))
        return f"continue review round {int(task_data['current_review_round']):03d} and close the {review_labels} findings"
    if status == "changes_requested":
        next_round = int(task_data["current_review_round"]) + 1
        return (
            f"fix the current review findings, add resolved review evidence, "
            f"then re-enter in_review for round {next_round:03d}"
        )
    if status == "ready_to_merge":
        return f"run workflowctl check --task-dir {task_dir_relative} and only then advance the task to done"
    if status == "done":
        return "deactivate this task or activate the next unfinished task"
    return "review the task artifacts and continue from the recorded status"


def describe_recovery_source(
    session_checkpoint: dict[str, Any] | None,
    active_task_summary: dict[str, str] | None,
    latest_unfinished_task: dict[str, str] | None,
) -> str:
    if active_task_summary is not None:
        return "active-task"
    if latest_unfinished_task is not None:
        return "latest unfinished task"
    if session_checkpoint is not None:
        return "decree checkpoint"
    return "none"


def write_decree_checkpoint(
    *,
    project_dir: Path,
    project_slug: str,
    summary: str,
    phase: str,
    next_step: str,
    flow: str = "",
    sprint: str = "",
    task_id: str = "",
    task_dir_relative: str = "",
) -> Path:
    """Persist a decree checkpoint. Returns the checkpoint file path."""

    checkpoint_path = get_decree_checkpoint_path(project_dir)
    ensure_local_path(checkpoint_path, project_dir, "decree checkpoint")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint_lines = [
        "---",
        f"project_slug: {serialize_frontmatter_string(project_slug)}",
        f"summary: {serialize_frontmatter_string(summary.strip())}",
        f"phase: {serialize_frontmatter_string(phase.strip())}",
        f"next_step: {serialize_frontmatter_string(next_step.strip())}",
        f"updated_at: {serialize_frontmatter_string(datetime.now(timezone.utc).isoformat())}",
    ]
    if flow:
        checkpoint_lines.append(f"flow: {serialize_frontmatter_string(flow)}")
    if sprint:
        checkpoint_lines.append(f"sprint: {serialize_frontmatter_string(sprint)}")
    if task_id:
        checkpoint_lines.append(f"task: {serialize_frontmatter_string(task_id)}")
    if task_dir_relative:
        checkpoint_lines.append(f"task_dir: {serialize_frontmatter_string(task_dir_relative)}")
    checkpoint_lines.extend(["---", ""])

    checkpoint_path.write_text("\n".join(checkpoint_lines), encoding="utf-8")
    return checkpoint_path
