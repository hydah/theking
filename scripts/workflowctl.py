from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

try:
    from .constants import (
        EXECUTION_PROFILE_DIRS,
        TASK_ID_PATTERN,
        TERMINAL_STATUSES,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from .validation import (
        apply_status_transition,
        append_theking_reference,
        check_dag,
        default_test_plan,
        derive_task_paths,
        ensure_absent,
        ensure_file,
        ensure_local_path,
        ensure_tree_has_no_symlinks,
        ensure_within_directory,
        execution_profile_dir,
        get_project_dir,
        get_theking_dir,
        get_workflow_project_dir,
        humanize_slug,
        infer_execution_profile,
        infer_blocked_resume_status,
        infer_required_agents,
        infer_verification_profile,
        load_task_document,
        next_index,
        normalize_execution_profile,
        normalize_sprint_name,
        normalize_task_type,
        normalize_title,
        parse_frontmatter,
        read_template_raw,
        render_template,
        review_type_specs_for_task,
        serialize_frontmatter_string,
        slugify,
        stringify,
        task_requires_security_review,
        validate_spec,
        validate_sprint_dir,
        validate_task_contract,
        validate_task_dir,
        write_task_document,
        write_if_missing,
    )
except ImportError:
    from constants import (
        EXECUTION_PROFILE_DIRS,
        TASK_ID_PATTERN,
        TERMINAL_STATUSES,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from validation import (
        apply_status_transition,
        append_theking_reference,
        check_dag,
        default_test_plan,
        derive_task_paths,
        ensure_absent,
        ensure_file,
        ensure_local_path,
        ensure_tree_has_no_symlinks,
        ensure_within_directory,
        execution_profile_dir,
        get_project_dir,
        get_theking_dir,
        get_workflow_project_dir,
        humanize_slug,
        infer_execution_profile,
        infer_blocked_resume_status,
        infer_required_agents,
        infer_verification_profile,
        load_task_document,
        next_index,
        normalize_execution_profile,
        normalize_sprint_name,
        normalize_task_type,
        normalize_title,
        parse_frontmatter,
        read_template_raw,
        render_template,
        review_type_specs_for_task,
        serialize_frontmatter_string,
        slugify,
        stringify,
        task_requires_security_review,
        validate_spec,
        validate_sprint_dir,
        validate_task_contract,
        validate_task_dir,
        write_task_document,
        write_if_missing,
    )


PROJECT_DIR_ARGUMENT_HELP = (
    "Project root or .theking directory. Preferred: run from the project root with --project-dir . "
    "The project directory basename must exactly match --project-slug."
)
DEACTIVATE_PROJECT_DIR_ARGUMENT_HELP = (
    "Project root or .theking directory for the target project. Pass --project-dir .theking if you only have the workflow path."
)
ROOT_ARGUMENT_HELP = "Project parent directory containing <project-slug>. Backward-compatible option."
PROJECT_SLUG_ARGUMENT_HELP = "Project slug in kebab-case. Usually the project directory name."
CHECKPOINT_FLOW_CHOICES = ("full", "lightweight")
DEGREE_CHECKPOINT_FILENAME = "decree-session.md"


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
    parser = argparse.ArgumentParser(
        prog="workflowctl",
        description="Bootstrap and validate theking project workflows.",
        epilog=(
            "Install:\n"
            "  pipx install /path/to/theking\n"
            "  uv tool install /path/to/theking\n\n"
            "Quickstart from a project root:\n"
            "  workflowctl ensure --project-dir . --project-slug my-app\n"
            "  workflowctl init-sprint --project-dir . --project-slug my-app --theme foundation\n"
            "  workflowctl init-task --project-dir . --project-slug my-app --sprint sprint-001-foundation --slug demo --title \"Demo\" --task-type tooling\n\n"
            "Compatibility:\n"
            "  Legacy scripts can keep using --root <parent-dir> --project-slug my-app.\n"
            "  If you already have a .theking path, pass it via --project-dir .theking."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_project = add_command_parser(
        subparsers,
        "init-project",
        help_text="Initialize a project's .theking scaffold.",
        example="workflowctl init-project --project-dir . --project-slug my-app",
    )
    add_project_locator_arguments(init_project)
    add_project_slug_argument(init_project)
    init_project.set_defaults(handler=handle_init_project)

    init_sprint = add_command_parser(
        subparsers,
        "init-sprint",
        help_text="Create a sprint under an initialized project.",
        example="workflowctl init-sprint --project-dir . --project-slug my-app --theme foundation",
    )
    add_project_locator_arguments(init_sprint)
    add_project_slug_argument(init_sprint)
    init_sprint.add_argument("--theme", required=True)
    init_sprint.set_defaults(handler=handle_init_sprint)

    init_task = add_command_parser(
        subparsers,
        "init-task",
        help_text="Create a task under an initialized sprint.",
        example=(
            "workflowctl init-task --project-dir . --project-slug my-app --sprint sprint-001-foundation "
            "--slug demo --title \"Demo\" --task-type tooling"
        ),
    )
    add_project_locator_arguments(init_task)
    add_project_slug_argument(init_task)
    init_task.add_argument("--sprint", required=True)
    init_task.add_argument("--slug", required=True)
    init_task.add_argument("--title", required=True)
    init_task.add_argument("--task-type", required=True)
    init_task.add_argument("--execution-profile")
    init_task.set_defaults(handler=handle_init_task)

    check = add_command_parser(
        subparsers,
        "check",
        help_text="Validate a task directory.",
        example="workflowctl check --task-dir .theking/workflows/my-app/sprints/sprint-001-foundation/tasks/TASK-001-demo",
    )
    check.add_argument("--task-dir", required=True)
    check.set_defaults(handler=handle_check)

    advance_status = add_command_parser(
        subparsers,
        "advance-status",
        help_text="Advance a task status outside of first-time review entry.",
        example=(
            "workflowctl advance-status --task-dir .theking/workflows/my-app/sprints/"
            "sprint-001-foundation/tasks/TASK-001-demo --to-status green"
        ),
    )
    advance_status.add_argument("--task-dir", required=True)
    advance_status.add_argument("--to-status", required=True)
    advance_status.set_defaults(handler=handle_advance_status)

    init_review_round = add_command_parser(
        subparsers,
        "init-review-round",
        help_text="Enter in_review and scaffold review files for the current round.",
        example=(
            "workflowctl init-review-round --task-dir .theking/workflows/my-app/sprints/"
            "sprint-001-foundation/tasks/TASK-001-demo"
        ),
    )
    init_review_round.add_argument("--task-dir", required=True)
    init_review_round.set_defaults(handler=handle_init_review_round)

    init_sprint_plan = add_command_parser(
        subparsers,
        "init-sprint-plan",
        help_text="Create many tasks from a sprint plan file.",
        example=(
            "workflowctl init-sprint-plan --project-dir . --project-slug my-app --sprint "
            "sprint-001-foundation --plan-file plan.json"
        ),
    )
    add_project_locator_arguments(init_sprint_plan)
    add_project_slug_argument(init_sprint_plan)
    init_sprint_plan.add_argument("--sprint", required=True)
    init_sprint_plan.add_argument("--plan-file", required=True)
    init_sprint_plan.set_defaults(handler=handle_init_sprint_plan)

    sprint_check = add_command_parser(
        subparsers,
        "sprint-check",
        help_text="Validate all tasks in a sprint.",
        example="workflowctl sprint-check --sprint-dir .theking/workflows/my-app/sprints/sprint-001-foundation",
    )
    sprint_check.add_argument("--sprint-dir", required=True)
    sprint_check.set_defaults(handler=handle_sprint_check)

    activate = add_command_parser(
        subparsers,
        "activate",
        help_text="Mark a task as the active task for hooks and workflow guidance.",
        example="workflowctl activate --task-dir .theking/workflows/my-app/sprints/sprint-001-foundation/tasks/TASK-001-demo",
    )
    activate.add_argument("--task-dir", required=True)
    activate.set_defaults(handler=handle_activate)

    deactivate = add_command_parser(
        subparsers,
        "deactivate",
        help_text="Clear the active task marker for a project.",
        example="workflowctl deactivate --project-dir .",
    )
    deactivate.add_argument("--project-dir", required=True, help=DEACTIVATE_PROJECT_DIR_ARGUMENT_HELP)
    deactivate.add_argument(
        "--force",
        action="store_true",
        help="Allow deactivating even if active task has not reached a terminal status (done/blocked).",
    )
    deactivate.set_defaults(handler=handle_deactivate)

    ensure = add_command_parser(
        subparsers,
        "ensure",
        help_text="Idempotently bootstrap a project with .theking scaffolding.",
        example="workflowctl ensure --project-dir . --project-slug my-app",
    )
    add_project_locator_arguments(ensure)
    add_project_slug_argument(ensure)
    ensure.set_defaults(handler=handle_ensure)

    upgrade = add_command_parser(
        subparsers,
        "upgrade",
        help_text="Refresh theking-owned runtime files after a theking skill upgrade.",
        example="workflowctl upgrade --project-dir . --project-slug my-app --dry-run",
    )
    add_project_locator_arguments(upgrade)
    add_project_slug_argument(upgrade)
    upgrade_mode = upgrade.add_mutually_exclusive_group()
    upgrade_mode.add_argument(
        "--force",
        action="store_true",
        help="Overwrite drifted files after backing them up under .theking/.backups/<timestamp>/.",
    )
    upgrade_mode.add_argument(
        "--adopt",
        action="store_true",
        help="Accept current on-disk content as the new baseline without overwriting.",
    )
    upgrade.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the upgrade plan without touching any files.",
    )
    upgrade.set_defaults(handler=handle_upgrade)

    checkpoint = add_command_parser(
        subparsers,
        "checkpoint",
        help_text="Persist the current decree progress so compacted sessions can resume safely.",
        example=(
            "workflowctl checkpoint --project-dir . --project-slug my-app --phase phase-3-planning "
            "--flow full --summary \"Fix upload auth flow\" --next-step \"Create sprint and tasks from planner output\""
        ),
    )
    add_project_locator_arguments(checkpoint)
    add_project_slug_argument(checkpoint)
    checkpoint.add_argument("--phase", required=True)
    checkpoint.add_argument("--summary", required=True)
    checkpoint.add_argument("--next-step", required=True)
    checkpoint.add_argument("--flow", choices=CHECKPOINT_FLOW_CHOICES)
    checkpoint.add_argument("--sprint")
    checkpoint.add_argument("--task-dir")
    checkpoint.set_defaults(handler=handle_checkpoint)

    status = add_command_parser(
        subparsers,
        "status",
        help_text="Show the current decree/task recovery state after compact or session resume.",
        example="workflowctl status --project-dir . --project-slug my-app",
    )
    add_project_locator_arguments(status)
    add_project_slug_argument(status)
    status.set_defaults(handler=handle_status)

    return parser


def add_command_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    *,
    help_text: str,
    example: str,
) -> argparse.ArgumentParser:
    return subparsers.add_parser(
        name,
        help=help_text,
        description=f"{help_text}\n\nExample:\n  {example}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def add_project_locator_arguments(parser: argparse.ArgumentParser) -> None:
    locator = parser.add_mutually_exclusive_group(required=True)
    locator.add_argument("--project-dir", help=PROJECT_DIR_ARGUMENT_HELP)
    locator.add_argument("--root", help=ROOT_ARGUMENT_HELP)


def add_project_slug_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project-slug", required=True, help=PROJECT_SLUG_ARGUMENT_HELP)


def normalize_project_dir_arg(project_dir_value: str) -> Path:
    project_dir_input = Path(project_dir_value).expanduser()
    if project_dir_input.name == THEKING_DIRNAME:
        return project_dir_input.parent.resolve()

    resolved_project_dir = project_dir_input.resolve()
    if resolved_project_dir.name == THEKING_DIRNAME:
        return resolved_project_dir.parent
    return resolved_project_dir


def resolve_project_context(
    project_slug_value: str,
    *,
    project_dir_value: str | None,
    root_value: str | None,
) -> tuple[Path, Path, str]:
    project_slug = slugify(project_slug_value)

    if project_dir_value is not None:
        project_dir = normalize_project_dir_arg(project_dir_value)
        if project_dir.name != project_slug:
            raise WorkflowError(
                "--project-dir must point to a directory whose basename exactly matches --project-slug. "
                f"Got directory {project_dir.name!r} for slug {project_slug!r}; use --root <parent-dir> if the directory name differs."
            )
        workspace_root = project_dir.parent
        return workspace_root, project_dir, project_slug

    if root_value is None:
        raise WorkflowError("Either --project-dir or --root is required")

    root = Path(root_value).expanduser().resolve()
    if root.name == THEKING_DIRNAME:
        raise WorkflowError(
            "--root expects the project parent directory. "
            "Use --project-dir . or --project-dir .theking from a project directory."
        )
    if root.name == project_slug or slugify(root.name) == project_slug:
        raise WorkflowError(
            "--root expects the project parent directory, not the project directory itself. "
            "Use --project-dir . or --project-dir .theking from a project directory."
        )

    workspace_root = root
    project_dir = get_project_dir(workspace_root, project_slug)

    return workspace_root, project_dir, project_slug


# --- Handlers ---


def handle_init_project(args: argparse.Namespace) -> None:
    workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)

    ensure_local_path(project_dir, workspace_root, "project")
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
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    theme_slug = slugify(args.theme)
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

    existing_checkpoint = load_decree_checkpoint(project_dir) or {}
    write_decree_checkpoint(
        project_dir=project_dir,
        project_slug=project_slug,
        summary=stringify(existing_checkpoint.get("summary", "")) or f"Sprint {sprint_name} created",
        phase="phase-3-planning",
        next_step=(
            f"run `workflowctl init-sprint-plan --sprint {sprint_name} --plan-file plan.json` "
            f"or `workflowctl init-task --sprint {sprint_name} ...` to create tasks, "
            "then activate the first task and write spec.md"
        ),
        flow=stringify(existing_checkpoint.get("flow", "")),
        sprint=sprint_name,
    )


def handle_init_task(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
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

    write_task_files(
        task_dir,
        task_id=task_id,
        title=title,
        task_type=task_type,
        execution_profile=execution_profile,
        verification_profile=verification_profile,
        requires_security_review=requires_security_review,
        required_agents=required_agents,
        depends_on=[],
    )
    print(task_dir)


def handle_check(args: argparse.Namespace) -> None:
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()
    validate_task_dir(task_dir)
    print(f"OK {task_dir}")


def handle_advance_status(args: argparse.Namespace) -> None:
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()

    validate_task_dir(task_dir)
    task_paths = derive_task_paths(task_dir)
    task_md = task_paths.task_md
    sprint_md = task_paths.sprint_dir / "sprint.md"
    original_content = task_md.read_text(encoding="utf-8")
    original_sprint_content = sprint_md.read_text(encoding="utf-8")
    task_data, body = load_task_document(task_md)

    requested_status = args.to_status.strip()
    if requested_status == "in_review":
        current_status = stringify(task_data["status"])
        if current_status != "blocked" or infer_blocked_resume_status([stringify(entry) for entry in task_data["status_history"]]) != "in_review":
            raise WorkflowError("Use init-review-round to enter in_review")

    updated_task = apply_status_transition(task_data, requested_status)

    try:
        write_task_document(task_md, updated_task, body)
        validate_task_dir(task_dir)
        update_sprint_overview(sprint_md)
    except Exception:
        task_md.write_text(original_content, encoding="utf-8")
        sprint_md.write_text(original_sprint_content, encoding="utf-8")
        raise

    print(f"Updated {task_dir} -> {updated_task['status']}")


def handle_init_review_round(args: argparse.Namespace) -> None:
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()

    validate_task_dir(task_dir)
    task_paths = derive_task_paths(task_dir)
    task_data, body = load_task_document(task_paths.task_md)
    current_status = stringify(task_data["status"])
    if current_status not in {"green", "changes_requested"}:
        raise WorkflowError("init-review-round requires task status green or changes_requested")

    updated_task = apply_status_transition(task_data, "in_review")
    round_number = int(updated_task["current_review_round"])
    review_specs = review_type_specs_for_task(updated_task)
    review_artifacts: list[tuple[Path, str]] = []
    sprint_md = task_paths.sprint_dir / "sprint.md"

    for review_type, review_label in review_specs:
        review_file = task_paths.review_dir / f"{review_type}-review-round-{round_number:03d}.md"
        ensure_local_path(review_file, task_paths.project_dir, "review")
        ensure_absent(review_file)
        review_artifacts.append((review_file, review_label))

    original_content = task_paths.task_md.read_text(encoding="utf-8")
    original_sprint_content = sprint_md.read_text(encoding="utf-8")
    try:
        write_task_document(task_paths.task_md, updated_task, body)
        for review_file, review_label in review_artifacts:
            review_file.write_text(
                render_template(
                    "code_review_round.md.tmpl",
                    review_label=review_label,
                    round_number=f"{round_number:03d}",
                    task_id=stringify(updated_task["id"]),
                ),
                encoding="utf-8",
            )
        validate_task_dir(task_dir)
        update_sprint_overview(sprint_md)
    except Exception:
        task_paths.task_md.write_text(original_content, encoding="utf-8")
        sprint_md.write_text(original_sprint_content, encoding="utf-8")
        for review_file, _review_label in review_artifacts:
            if review_file.exists():
                review_file.unlink()
        raise

    print(f"Initialized review round {round_number:03d} for {task_dir}")


def handle_init_sprint_plan(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    sprint_name = normalize_sprint_name(args.sprint)
    plan_file = Path(args.plan_file).expanduser().resolve()

    if not plan_file.is_file():
        raise WorkflowError(f"Plan file not found: {plan_file}")
    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Plan file must contain valid JSON: {plan_file}") from error
    if not isinstance(plan_data, dict) or "tasks" not in plan_data:
        raise WorkflowError("Plan file must contain a 'tasks' array")
    task_entries = plan_data["tasks"]
    if not isinstance(task_entries, list) or not task_entries:
        raise WorkflowError("Plan file must contain at least one task")

    sprints_dir = get_workflow_project_dir(project_dir, project_slug) / "sprints"
    ensure_local_path(sprints_dir, project_dir, "sprints")
    requested_sprint_dir = sprints_dir / sprint_name
    ensure_local_path(requested_sprint_dir, project_dir, "sprint")
    sprint_dir = requested_sprint_dir.resolve()
    ensure_within_directory(sprint_dir, sprints_dir.resolve(), "sprint")
    ensure_file(sprint_dir / "sprint.md", "sprint.md")

    tasks_dir = sprint_dir / "tasks"
    ensure_local_path(tasks_dir, project_dir, "tasks")
    tasks_dir.mkdir(exist_ok=True)

    parsed = parse_plan_entries(task_entries, tasks_dir)

    prepared_entries: list[dict[str, Any]] = []
    for entry in parsed["entries"]:
        task_id = entry["_task_id"]
        title = normalize_title(require_string(entry["title"], f"Task {task_id} field 'title'"))
        task_type = normalize_task_type(
            require_string(entry["task_type"], f"Task {task_id} field 'task_type'")
        )
        execution_profile = (
            normalize_execution_profile(
                require_string(entry["execution_profile"], f"Task {task_id} field 'execution_profile'")
            )
            if "execution_profile" in entry
            else infer_execution_profile(task_type)
        )
        validate_task_contract(task_type, execution_profile)
        verification_profile = infer_verification_profile(execution_profile)
        requires_security_review = task_requires_security_review(task_type, execution_profile)
        required_agents = infer_required_agents(task_type, execution_profile)
        resolved_deps = parsed["deps_by_slug"][entry["_slug"]]

        prepared_entries.append(
            {
                **entry,
                "task_id": task_id,
                "title": title,
                "task_type": task_type,
                "execution_profile": execution_profile,
                "verification_profile": verification_profile,
                "requires_security_review": requires_security_review,
                "required_agents": required_agents,
                "depends_on": resolved_deps,
                "spec_hints": entry.get("_spec_hints", {}),
            }
        )

    created_dirs: list[Path] = []
    try:
        for entry in prepared_entries:
            task_id = entry["task_id"]
            task_dir = tasks_dir / task_id
            ensure_local_path(task_dir, project_dir, "task")
            task_dir.mkdir(parents=True, exist_ok=False)
            created_dirs.append(task_dir)

            review_dir = task_dir / "review"
            ensure_local_path(review_dir, project_dir, "review")
            review_dir.mkdir(exist_ok=True)
            verification_subdir = task_dir / "verification" / execution_profile_dir(entry["execution_profile"])
            ensure_local_path(verification_subdir, project_dir, "verification")
            verification_subdir.mkdir(parents=True, exist_ok=True)

            write_task_files(
                task_dir,
                task_id=task_id,
                title=entry["title"],
                task_type=entry["task_type"],
                execution_profile=entry["execution_profile"],
                verification_profile=entry["verification_profile"],
                requires_security_review=entry["requires_security_review"],
                required_agents=entry["required_agents"],
                depends_on=entry["depends_on"],
                spec_hints=entry.get("spec_hints") or None,
            )

        update_sprint_overview(sprint_dir / "sprint.md")
    except Exception:
        for task_dir in reversed(created_dirs):
            shutil.rmtree(task_dir, ignore_errors=True)
        raise

    for task_dir in created_dirs:
        print(task_dir)

    existing_checkpoint = load_decree_checkpoint(project_dir) or {}
    first_task_dir = created_dirs[0]
    first_task_id = prepared_entries[0]["task_id"]
    first_task_rel = first_task_dir.relative_to(project_dir).as_posix()
    write_decree_checkpoint(
        project_dir=project_dir,
        project_slug=project_slug,
        summary=stringify(existing_checkpoint.get("summary", ""))
        or f"Sprint {sprint_name} planned with {len(created_dirs)} task(s)",
        phase="phase-3-planning",
        next_step=(
            f"activate {first_task_rel}, write spec.md, then "
            f"`workflowctl advance-status --task-dir {first_task_rel} --to-status planned`"
        ),
        flow=stringify(existing_checkpoint.get("flow", "")),
        sprint=sprint_name,
        task_id=first_task_id,
        task_dir_relative=first_task_rel,
    )

    print("")
    print(f"Created {len(created_dirs)} task(s) in 'draft'. NEXT STEP:")
    print(f"  workflowctl activate --task-dir {first_task_rel}")
    print("  # Write spec.md (Scope / Non-Goals / Acceptance / Test Plan / Edge Cases), then:")
    print(
        f"  workflowctl advance-status --task-dir {first_task_rel} --to-status planned"
    )
    print("Tasks stay in 'draft' until you explicitly advance them.")
    print("`workflowctl deactivate` refuses to exit while the active task is non-terminal.")


def handle_sprint_check(args: argparse.Namespace) -> None:
    input_sprint_dir = Path(args.sprint_dir).expanduser()
    if input_sprint_dir.is_symlink():
        raise WorkflowError(f"sprint_dir must not be a symlink: {input_sprint_dir}")
    sprint_dir = input_sprint_dir.resolve()
    validate_sprint_dir(sprint_dir)
    print(f"OK {sprint_dir}")


def handle_activate(args: argparse.Namespace) -> None:
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()
    if not task_dir.is_dir():
        raise WorkflowError(f"task_dir does not exist: {task_dir}")

    validate_task_dir(task_dir)
    task_paths = derive_task_paths(task_dir)
    active_task_file = task_paths.theking_dir / "active-task"
    ensure_local_path(active_task_file, task_paths.project_dir, "active-task")
    active_task_file.write_text(str(task_dir) + "\n", encoding="utf-8")
    print(f"Activated {task_dir}")


def handle_deactivate(args: argparse.Namespace) -> None:
    project_dir = normalize_project_dir_arg(args.project_dir)
    theking_dir = project_dir / THEKING_DIRNAME
    active_task_file = theking_dir / "active-task"
    ensure_local_path(active_task_file, project_dir, "active-task")
    force = bool(getattr(args, "force", False))
    if active_task_file.exists():
        if not force:
            task_path_text = active_task_file.read_text(encoding="utf-8").strip()
            if task_path_text:
                task_dir = Path(task_path_text)
                task_md = task_dir / "task.md"
                if task_md.is_file():
                    try:
                        task_data, _body = load_task_document(task_md)
                        current_status = stringify(task_data.get("status", ""))
                    except Exception:
                        current_status = ""
                    if current_status and current_status not in TERMINAL_STATUSES:
                        task_id = stringify(task_data.get("id", task_dir.name))
                        raise WorkflowError(
                            f"Refusing to deactivate: task {task_id} is still in '{current_status}'. "
                            f"Advance it to a terminal status (done/blocked) first, e.g. "
                            f"`workflowctl advance-status --task-dir {task_dir} --to-status <next>`. "
                            f"Pass --force to override."
                        )
        active_task_file.unlink()
    print("Deactivated")


def handle_ensure(args: argparse.Namespace) -> None:
    """Idempotent bootstrap: create .theking scaffold if missing, skip if exists."""
    workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)

    ensure_local_path(project_dir, workspace_root, "project")
    ensure_local_path(workflow_project_dir, project_dir, "workflow project")
    project_dir.mkdir(parents=True, exist_ok=True)
    ensure_theking_scaffold(project_dir, project_slug)
    workflow_project_dir.mkdir(parents=True, exist_ok=True)
    sprints_dir = workflow_project_dir / "sprints"
    ensure_local_path(sprints_dir, project_dir, "sprints")
    sprints_dir.mkdir(exist_ok=True)

    project_md = workflow_project_dir / "project.md"
    ensure_local_path(project_md, project_dir, "project.md")
    write_if_missing(
        project_md,
        render_template(
            "project.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )

    theking_dir = get_theking_dir(project_dir)
    print(f"OK {theking_dir}")


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


def handle_checkpoint(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )

    sprint_name = normalize_sprint_name(args.sprint) if args.sprint else ""
    task_id = ""
    task_dir_relative = ""

    if args.task_dir:
        input_task_dir = Path(args.task_dir).expanduser()
        if input_task_dir.is_symlink():
            raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
        task_dir = input_task_dir.resolve()
        task_paths = derive_task_paths(task_dir)
        ensure_local_path(task_dir, project_dir, "task")
        task_data, _body = load_task_document(task_paths.task_md)
        task_id = stringify(task_data["id"])
        task_dir_relative = task_dir.relative_to(project_dir).as_posix()
        if sprint_name and task_paths.sprint_dir.name != sprint_name:
            raise WorkflowError("--sprint must match the sprint that owns --task-dir")
        sprint_name = task_paths.sprint_dir.name

    checkpoint_path = write_decree_checkpoint(
        project_dir=project_dir,
        project_slug=project_slug,
        summary=args.summary,
        phase=args.phase,
        next_step=args.next_step,
        flow=args.flow or "",
        sprint=sprint_name,
        task_id=task_id,
        task_dir_relative=task_dir_relative,
    )
    print(checkpoint_path)


def handle_status(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    theking_dir = get_theking_dir(project_dir)
    ensure_local_path(theking_dir, project_dir, "theking")
    session_checkpoint = load_decree_checkpoint(project_dir)
    active_task_summary = load_active_task_status(project_dir)
    latest_unfinished_task = None if active_task_summary else find_latest_unfinished_task(project_dir, project_slug)

    lines = [
        f"Project: {project_slug}",
        f"Recovery source: {describe_recovery_source(session_checkpoint, active_task_summary, latest_unfinished_task)}",
    ]

    checkpoint_lines: list[str] = []
    if session_checkpoint is not None:
        checkpoint_lines.extend(
            [
                "Saved decree checkpoint:",
                f"- Summary: {session_checkpoint.get('summary', '')}",
                f"- Phase: {session_checkpoint.get('phase', '')}",
            ]
        )
        flow_value = stringify(session_checkpoint.get("flow", ""))
        if flow_value:
            checkpoint_lines.append(f"- Flow: {flow_value}")
        sprint_value = stringify(session_checkpoint.get("sprint", ""))
        if sprint_value:
            checkpoint_lines.append(f"- Sprint: {sprint_value}")
        task_value = stringify(session_checkpoint.get("task", ""))
        if task_value:
            checkpoint_lines.append(f"- Task: {task_value}")
        checkpoint_lines.append(f"- Next step: {session_checkpoint.get('next_step', '')}")

    if active_task_summary is not None:
        lines.extend(
            [
                "Active task:",
                f"- ID: {active_task_summary['task_id']}",
                f"- Status: {active_task_summary['status']}",
                f"- Task dir: {active_task_summary['task_dir']}",
                f"- Current review round: {active_task_summary['current_review_round']}",
                f"- Next step: {active_task_summary['next_step']}",
            ]
        )
        lines.extend(checkpoint_lines)
    elif latest_unfinished_task is not None:
        lines.extend(
            [
                "Suggested recovery:",
                f"- Latest unfinished task: {latest_unfinished_task['task_id']} ({latest_unfinished_task['status']})",
                f"- Task dir: {latest_unfinished_task['task_dir']}",
                f"- Next step: Activate this task, then {latest_unfinished_task['next_step']}",
            ]
        )
        lines.extend(checkpoint_lines)
    else:
        lines.extend(checkpoint_lines)
        lines.extend(
            [
                "Suggested recovery:",
                "- No active task found.",
                "- If this session was compacted mid-decree, continue from the checkpoint above.",
                "- Otherwise start a new /decree or activate an existing unfinished task.",
            ]
        )

    print("\n".join(lines))


# --- Shared helpers ---


def extract_spec_hints(entry: dict[str, Any], task_id: str) -> dict[str, list[str]]:
    """Extract optional spec seed fields from a plan entry.

    Recognised keys: scope, non_goals, acceptance, edge_cases. Each must be a list of
    strings. Returns an empty dict if no hints are supplied.
    """

    hints: dict[str, list[str]] = {}
    for key in ("scope", "non_goals", "acceptance", "edge_cases"):
        if key not in entry:
            continue
        raw = entry[key]
        if not isinstance(raw, list):
            raise WorkflowError(
                f"Task {task_id} field '{key}' must be a list of strings when provided"
            )
        items: list[str] = []
        for index, item in enumerate(raw):
            text = stringify(item).strip()
            if not text:
                continue
            if "\n" in text:
                raise WorkflowError(
                    f"Task {task_id} field '{key}' item {index} must be a single line"
                )
            items.append(text)
        if items:
            hints[key] = items
    return hints


def parse_plan_entries(
    task_entries: list[Any],
    tasks_dir: Path,
) -> dict[str, Any]:
    """Parse and validate plan entries. Returns slug_to_id, entries, deps_by_slug."""
    base_number = next_index(tasks_dir, "TASK")
    slug_to_task_id: dict[str, str] = {}
    parsed_entries: list[dict[str, Any]] = []

    for index, entry in enumerate(task_entries):
        if not isinstance(entry, dict):
            raise WorkflowError(f"Task entry {index} must be an object")
        for required_field in ("slug", "title", "task_type"):
            if required_field not in entry:
                raise WorkflowError(f"Task entry {index} is missing required field: {required_field}")

        task_slug = slugify(require_string(entry["slug"], f"Task entry {index} field 'slug'"))
        if task_slug in slug_to_task_id:
            raise WorkflowError(f"Duplicate task slug: {task_slug}")

        task_number = base_number + index
        task_id = f"TASK-{task_number:03d}-{task_slug}"
        slug_to_task_id[task_slug] = task_id
        spec_hints = extract_spec_hints(entry, task_id)
        parsed_entries.append(
            {
                **entry,
                "_task_id": task_id,
                "_slug": task_slug,
                "_spec_hints": spec_hints,
            }
        )

    resolved_deps_by_slug: dict[str, list[str]] = {}
    for entry in parsed_entries:
        slug = entry["_slug"]
        raw_deps = entry.get("depends_on", [])
        if not isinstance(raw_deps, list):
            raise WorkflowError(f"depends_on must be a list for task {slug}")
        resolved: list[str] = []
        for dep_slug in raw_deps:
            dep_slug_normalized = slugify(require_string(dep_slug, f"Task {slug} dependency entry"))
            if dep_slug_normalized not in slug_to_task_id:
                raise WorkflowError(
                    f"Task {slug} depends on unknown task: {dep_slug}"
                )
            resolved.append(slug_to_task_id[dep_slug_normalized])
        resolved_deps_by_slug[slug] = resolved

    task_id_to_slug = {v: k for k, v in slug_to_task_id.items()}
    dag_adjacency = {
        slug: [task_id_to_slug[dep_id] for dep_id in deps]
        for slug, deps in resolved_deps_by_slug.items()
    }
    check_dag(dag_adjacency)

    return {
        "slug_to_id": slug_to_task_id,
        "entries": parsed_entries,
        "deps_by_slug": resolved_deps_by_slug,
    }


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
        return f"run build/lint/type/unit plus profile verification, capture evidence, then workflowctl init-review-round --task-dir {task_dir_relative}"
    if status == "in_review":
        review_labels = ", ".join(label for _review_type, label in review_type_specs_for_task(task_data))
        return f"continue review round {int(task_data['current_review_round']):03d} and close the {review_labels} findings"
    if status == "changes_requested":
        next_round = int(task_data["current_review_round"]) + 1
        return f"fix the current review findings, add resolved review evidence, then re-enter in_review for round {next_round:03d}"
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


def write_task_files(
    task_dir: Path,
    *,
    task_id: str,
    title: str,
    task_type: str,
    execution_profile: str,
    verification_profile: list[str],
    requires_security_review: bool,
    required_agents: list[str],
    depends_on: list[str],
    spec_hints: dict[str, list[str]] | None = None,
) -> None:
    """Write task.md and spec.md into a task directory."""
    depends_on_block = (
        "\n".join(f"  - {dep}" for dep in depends_on)
        if depends_on
        else ""
    )
    task_md = task_dir / "task.md"
    task_md.write_text(
        render_template(
            "task.md.tmpl",
            task_id=task_id,
            task_title=serialize_frontmatter_string(title),
            task_type=task_type,
            execution_profile=execution_profile,
            verification_profile_block="\n".join(f"  - {p}" for p in verification_profile),
            requires_security_review=str(requires_security_review).lower(),
            required_agents_block="\n".join(f"  - {a}" for a in required_agents),
            depends_on_block=depends_on_block,
        ),
        encoding="utf-8",
    )

    spec_md = task_dir / "spec.md"
    spec_md.write_text(
        render_spec_markdown(
            title=title,
            test_plan=default_test_plan(execution_profile),
            hints=spec_hints,
        ),
        encoding="utf-8",
    )


def render_spec_markdown(
    *,
    title: str,
    test_plan: str,
    hints: dict[str, list[str]] | None,
) -> str:
    """Render spec.md. If no hints provided, fall back to the legacy placeholder template."""

    if not hints:
        return render_template(
            "spec.md.tmpl",
            task_title=title,
            test_plan=test_plan,
        )

    def bullets(key: str, fallback_comment: str) -> str:
        items = [item.strip() for item in hints.get(key, []) if str(item).strip()]
        if not items:
            return f"<!-- {fallback_comment} -->"
        return "\n".join(f"- {item}" for item in items)

    def checklist(key: str, fallback_comment: str) -> str:
        items = [item.strip() for item in hints.get(key, []) if str(item).strip()]
        if not items:
            return f"- [ ] <!-- {fallback_comment} -->"
        return "\n".join(f"- [ ] {item}" for item in items)

    return (
        f"# {title} Spec\n\n"
        "<!-- All sections below are required, even for lightweight tasks.\n"
        "     Brevity is allowed; omission is not. -->\n\n"
        "## Scope\n"
        f"{bullets('scope', 'Define the smallest deliverable that can pass review.')}\n\n"
        "## Non-Goals\n"
        f"{bullets('non_goals', 'Explicitly state what this task does NOT cover.')}\n\n"
        "## Acceptance\n"
        f"{checklist('acceptance', 'Specific, testable criterion. Each should be independently verifiable.')}\n\n"
        "## Test Plan\n"
        f"{test_plan}\n\n"
        "## Edge Cases\n"
        f"{bullets('edge_cases', 'List boundary conditions, error scenarios, and unusual inputs to handle.')}\n"
    )



def update_sprint_overview(
    sprint_md_path: Path,
) -> None:
    rows: list[str] = []
    rows.append("| Task | Type | Profile | Depends On | Status |")
    rows.append("|------|------|---------|-----------|--------|")
    tasks_dir = sprint_md_path.parent / "tasks"
    for entry in collect_task_overview_entries(tasks_dir):
        rows.append(
            f"| {entry['task_id']} | {entry['task_type']} | {entry['execution_profile']} | {entry['depends_on']} | {entry['status']} |"
        )

    overview_table = "\n".join(rows)
    existing_content = sprint_md_path.read_text(encoding="utf-8")
    if "## Task Overview" not in existing_content:
        existing_content += f"\n\n## Task Overview\n\n{overview_table}\n"
    else:
        existing_content = re.sub(
            r"## Task Overview\n.*?(?=\n## |\Z)",
            f"## Task Overview\n\n{overview_table}\n",
            existing_content,
            flags=re.DOTALL,
        )
    sprint_md_path.write_text(existing_content, encoding="utf-8")


RUNTIME_MANIFEST_RELATIVE = PurePosixPath(THEKING_DIRNAME) / ".manifests" / "runtime.json"
RUNTIME_BACKUP_ROOT_RELATIVE = PurePosixPath(THEKING_DIRNAME) / ".backups"

# CodeBuddy agent frontmatter defaults. Tool list mirrors the CodeBuddy extension's
# standard set; we intentionally drop `model` (environment-specific) and `mcpTools`
# (user must choose which MCP servers to trust in their workspace).
CODEBUDDY_AGENT_TOOLS = (
    "list_dir, search_file, search_content, read_file, read_lints, replace_in_file, "
    "write_to_file, execute_command, mcp_get_tool_description, mcp_call_tool, "
    "delete_file, preview_url, web_fetch, use_skill, web_search, codebase_search, "
    "automation_update"
)
CODEBUDDY_FRONTMATTER_DROP_KEYS = frozenset(
    {"model", "tools", "agentMode", "enabled", "enabledAutoRun", "mcpTools"}
)
CODEBUDDY_FRONTMATTER_APPEND = (
    f"tools: {CODEBUDDY_AGENT_TOOLS}",
    "agentMode: agentic",
    "enabled: true",
    "enabledAutoRun: true",
)


def rewrite_agent_frontmatter_for_codebuddy(relative_path: str, text: str) -> str:
    """Rewrite a Claude-flavored agent file into CodeBuddy-flavored frontmatter.

    Only runs on files directly under the projection target (no nested dirs)
    ending in .md with a leading YAML frontmatter block. Preserves `name` and
    `description` (including multi-line block scalars). Drops Claude-specific
    `tools`/`model` and appends CodeBuddy-specific keys. Body is untouched.
    """
    if "/" in relative_path or not relative_path.endswith(".md"):
        return text
    if not text.startswith("---\n"):
        return text
    end_marker = text.find("\n---\n", 4)
    if end_marker == -1:
        return text
    header = text[4:end_marker]
    body = text[end_marker + 5 :]

    kept_lines: list[str] = []
    skipping_block = False
    for line in header.splitlines():
        if skipping_block:
            # Indented continuation of a block scalar / flow sequence.
            if line.startswith((" ", "\t")) or line == "":
                continue
            skipping_block = False
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if match and match.group(1) in CODEBUDDY_FRONTMATTER_DROP_KEYS:
            # Detect block scalar (| or >) or empty value that implies nested block.
            value_match = re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s*:\s*(.*)$", line)
            value = value_match.group(1) if value_match else ""
            if value.startswith("|") or value.startswith(">") or value == "":
                skipping_block = True
            continue
        kept_lines.append(line)

    kept_lines.extend(CODEBUDDY_FRONTMATTER_APPEND)
    new_header = "\n".join(kept_lines)
    return f"---\n{new_header}\n---\n{body}"


def build_runtime_template_vars(project_slug: str) -> dict[str, str]:
    theking_cmd = "workflowctl"
    workflow_root = "."
    workflow_root_quoted = shlex.quote(workflow_root)
    project_dir_hint = "."
    project_dir_quoted = shlex.quote(project_dir_hint)
    demo_task_dir_quoted = shlex.quote(
        (
            PurePosixPath(THEKING_DIRNAME)
            / "workflows"
            / project_slug
            / "sprints"
            / "sprint-001-foundation"
            / "tasks"
            / "TASK-001-demo"
        ).as_posix()
    )
    return dict(
        project_slug=project_slug,
        project_title=humanize_slug(project_slug),
        theking_cmd=theking_cmd,
        workflow_root=workflow_root,
        workflow_root_quoted=workflow_root_quoted,
        project_dir=project_dir_hint,
        project_dir_quoted=project_dir_quoted,
        demo_task_dir_quoted=demo_task_dir_quoted,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def runtime_manifest_path(project_dir: Path) -> Path:
    return project_dir / RUNTIME_MANIFEST_RELATIVE


def load_runtime_manifest(project_dir: Path) -> dict[str, str]:
    path = runtime_manifest_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    files = data.get("files")
    if not isinstance(files, dict):
        return {}
    return {str(k): str(v) for k, v in files.items() if isinstance(k, str) and isinstance(v, str)}


def save_runtime_manifest(project_dir: Path, files: dict[str, str]) -> None:
    path = runtime_manifest_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": dict(sorted(files.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def collect_managed_runtime_artifacts(
    project_dir: Path, project_slug: str
) -> list[tuple[Path, str]]:
    """Return (absolute_path, rendered_content) for every file whose canonical
    content is fully owned by theking templates. Intentionally excludes user
    content (project-overview.md, MEMORY.md) and entry files (CLAUDE.md,
    CODEBUDDY.md, AGENTS.md), which have bespoke update semantics.
    """
    theking_dir = get_theking_dir(project_dir)
    tmpl_vars = build_runtime_template_vars(project_slug)
    artifacts: list[tuple[Path, str]] = []

    def add(relative: str, content: str) -> None:
        artifacts.append((theking_dir / relative, content))

    add(
        "README.md",
        render_template(
            "theking_readme.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    add(
        "bootstrap.md",
        render_template(
            "theking_bootstrap.md.tmpl",
            project_slug=project_slug,
            project_title=humanize_slug(project_slug),
        ),
    )
    add(
        "context/architecture.md",
        render_template("theking_architecture.md.tmpl", project_slug=project_slug),
    )
    add(
        "context/dev-workflow.md",
        render_template("theking_dev_workflow.md.tmpl", **tmpl_vars),
    )
    add(
        "agents/README.md",
        render_template("theking_agents_readme.md.tmpl", project_slug=project_slug),
    )
    add(
        "agents/catalog.md",
        render_template("theking_agents_catalog.md.tmpl", project_slug=project_slug),
    )
    add(
        "verification/README.md",
        render_template("theking_verification_readme.md.tmpl", project_slug=project_slug),
    )

    agent_definitions = [
        ("planner.md", "agent_planner.md.tmpl"),
        ("tdd-guide.md", "agent_tdd_guide.md.tmpl"),
        ("code-reviewer.md", "agent_code_reviewer.md.tmpl"),
        ("security-reviewer.md", "agent_security_reviewer.md.tmpl"),
        ("e2e-runner.md", "agent_e2e_runner.md.tmpl"),
        ("architect.md", "agent_architect.md.tmpl"),
        ("build-error-resolver.md", "agent_build_error_resolver.md.tmpl"),
        ("doc-updater.md", "agent_doc_updater.md.tmpl"),
        ("refactor-cleaner.md", "agent_refactor_cleaner.md.tmpl"),
        ("perf-optimizer.md", "agent_perf_optimizer.md.tmpl"),
    ]
    for filename, template_name in agent_definitions:
        add(f"agents/{filename}", render_template(template_name, project_slug=project_slug))

    hook_files = [
        ("check-spec-exists.js", "hook_check_spec.js.tmpl"),
        ("check-task-status.js", "hook_check_status.js.tmpl"),
        ("remind-review.js", "hook_remind_review.js.tmpl"),
    ]
    for filename, template_name in hook_files:
        add(f"hooks/{filename}", read_template_raw(template_name))

    skill_definitions = [
        ("workflow-governance", "skill_workflow_governance.md.tmpl"),
        ("knowledge-base", "skill_knowledge_base.md.tmpl"),
    ]
    for skill_name, template_name in skill_definitions:
        add(
            f"skills/{skill_name}/SKILL.md",
            render_template(template_name, **tmpl_vars),
        )

    command_definitions = [
        ("decree.md", "cmd_decree.md.tmpl"),
        ("analyze-project.md", "cmd_analyze_project.md.tmpl"),
    ]
    for cmd_filename, template_name in command_definitions:
        rendered = render_template(template_name, **tmpl_vars)
        add(f"commands/{cmd_filename}", rendered)
        prompt_name = cmd_filename.replace(".md", ".prompt.md")
        add(f"prompts/{prompt_name}", rendered)

    return artifacts


def _manifest_key(project_dir: Path, absolute_path: Path) -> str:
    return absolute_path.relative_to(project_dir).as_posix()


def sync_runtime_manifest_baseline(project_dir: Path, project_slug: str) -> None:
    """Populate manifest entries for files whose on-disk content equals the
    current template output. Leaves drifted files untouched (they will be
    reported during upgrade)."""
    artifacts = collect_managed_runtime_artifacts(project_dir, project_slug)
    manifest = load_runtime_manifest(project_dir)
    changed = False
    for absolute_path, rendered in artifacts:
        key = _manifest_key(project_dir, absolute_path)
        if not absolute_path.exists():
            if key in manifest:
                del manifest[key]
                changed = True
            continue
        try:
            on_disk = absolute_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        on_disk_hash = _sha256_text(on_disk)
        template_hash = _sha256_text(rendered)
        expected = manifest.get(key)
        if on_disk_hash == template_hash and expected != template_hash:
            manifest[key] = template_hash
            changed = True
    if changed:
        save_runtime_manifest(project_dir, manifest)


def ensure_theking_scaffold(project_dir: Path, project_slug: str) -> None:
    theking_dir = get_theking_dir(project_dir)
    context_dir = theking_dir / "context"
    memory_dir = theking_dir / "memory"
    verification_dir = theking_dir / "verification"
    state_dir = theking_dir / "state"
    session_state_dir = state_dir / "session"
    workflows_dir = theking_dir / "workflows"
    runs_dir = theking_dir / "runs"
    manifest_dir = theking_dir / ".manifests"
    agents_dir = theking_dir / "agents"
    commands_dir = theking_dir / "commands"
    skills_dir = theking_dir / "skills"
    hooks_dir = theking_dir / "hooks"
    prompts_dir = theking_dir / "prompts"
    legacy_runtime_dir = theking_dir / "runtime"
    legacy_runtime_manifest_dir = legacy_runtime_dir / ".manifests"
    legacy_runtime_agents_dir = legacy_runtime_dir / "agents"
    legacy_runtime_commands_dir = legacy_runtime_dir / "commands"
    legacy_runtime_skills_dir = legacy_runtime_dir / "skills"
    legacy_runtime_hooks_dir = legacy_runtime_dir / "hooks"
    legacy_runtime_prompts_dir = legacy_runtime_dir / "prompts"

    if legacy_runtime_dir.exists():
        ensure_tree_has_no_symlinks(
            legacy_runtime_dir,
            project_dir,
            legacy_runtime_dir.relative_to(project_dir).as_posix(),
        )

    for directory in (
        context_dir,
        memory_dir,
        verification_dir,
        state_dir,
        session_state_dir,
        workflows_dir,
        runs_dir,
        manifest_dir,
        agents_dir,
        commands_dir,
        skills_dir,
        hooks_dir,
        prompts_dir,
    ):
        ensure_local_path(directory, project_dir, directory.name)
        directory.mkdir(parents=True, exist_ok=True)

    for profile_name in EXECUTION_PROFILE_DIRS.values():
        (verification_dir / profile_name).mkdir(parents=True, exist_ok=True)

    # --- Shared template variables ---
    tmpl_vars = build_runtime_template_vars(project_slug)

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
        render_template("theking_dev_workflow.md.tmpl", **tmpl_vars),
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
        legacy_path=legacy_runtime_agents_dir / "README.md",
    )
    write_if_missing(
        agents_dir / "catalog.md",
        render_template(
            "theking_agents_catalog.md.tmpl",
            project_slug=project_slug,
        ),
        legacy_path=legacy_runtime_agents_dir / "catalog.md",
    )
    write_if_missing(
        verification_dir / "README.md",
        render_template(
            "theking_verification_readme.md.tmpl",
            project_slug=project_slug,
        ),
    )

    runtime_entry_files = [
        ("CLAUDE.md", "claude_md.tmpl"),
        ("CODEBUDDY.md", "codebuddy_md.tmpl"),
        ("AGENTS.md", "agents_md.tmpl"),
    ]
    theking_anchor = ".theking/bootstrap.md"
    for entry_filename, template_name in runtime_entry_files:
        entry_path = project_dir / entry_filename
        if entry_path.is_symlink() and not entry_path.exists():
            # Dangling symlink — skip rather than overwrite
            continue
        if entry_path.is_symlink():
            ensure_local_path(entry_path.resolve(), project_dir, entry_filename)
        if not entry_path.exists() and not entry_path.is_symlink():
            entry_path.write_text(
                render_template(
                    template_name,
                    project_slug=project_slug,
                    project_title=humanize_slug(project_slug),
                ),
                encoding="utf-8",
            )
        elif theking_anchor not in entry_path.read_text(encoding="utf-8"):
            append_theking_reference(entry_path)

    agent_definitions = [
        ("planner.md", "agent_planner.md.tmpl"),
        ("tdd-guide.md", "agent_tdd_guide.md.tmpl"),
        ("code-reviewer.md", "agent_code_reviewer.md.tmpl"),
        ("security-reviewer.md", "agent_security_reviewer.md.tmpl"),
        ("e2e-runner.md", "agent_e2e_runner.md.tmpl"),
        ("architect.md", "agent_architect.md.tmpl"),
        ("build-error-resolver.md", "agent_build_error_resolver.md.tmpl"),
        ("doc-updater.md", "agent_doc_updater.md.tmpl"),
        ("refactor-cleaner.md", "agent_refactor_cleaner.md.tmpl"),
        ("perf-optimizer.md", "agent_perf_optimizer.md.tmpl"),
    ]

    for agent_filename, template_name in agent_definitions:
        agent_content = render_template(template_name, project_slug=project_slug)
        write_if_missing(
            agents_dir / agent_filename,
            agent_content,
            legacy_path=legacy_runtime_agents_dir / agent_filename,
        )

    hook_files = [
        ("check-spec-exists.js", "hook_check_spec.js.tmpl"),
        ("check-task-status.js", "hook_check_status.js.tmpl"),
        ("remind-review.js", "hook_remind_review.js.tmpl"),
    ]
    for hook_filename, template_name in hook_files:
        hook_content = read_template_raw(template_name)
        write_if_missing(
            hooks_dir / hook_filename,
            hook_content,
            legacy_path=legacy_runtime_hooks_dir / hook_filename,
        )

    # --- Skill definitions ---
    skill_definitions = [
        ("workflow-governance", "skill_workflow_governance.md.tmpl"),
        ("knowledge-base", "skill_knowledge_base.md.tmpl"),
    ]
    for skill_name, template_name in skill_definitions:
        skill_content = render_template(template_name, **tmpl_vars)
        canonical_skill_dir = skills_dir / skill_name
        canonical_skill_dir.mkdir(parents=True, exist_ok=True)
        write_if_missing(
            canonical_skill_dir / "SKILL.md",
            skill_content,
            legacy_path=legacy_runtime_skills_dir / skill_name / "SKILL.md",
        )

    # --- Command definitions ---
    command_definitions = [
        ("decree.md", "cmd_decree.md.tmpl"),
        ("analyze-project.md", "cmd_analyze_project.md.tmpl"),
    ]
    for cmd_filename, template_name in command_definitions:
        cmd_content = render_template(template_name, **tmpl_vars)
        write_if_missing(
            commands_dir / cmd_filename,
            cmd_content,
            legacy_path=legacy_runtime_commands_dir / cmd_filename,
        )

    for cmd_filename, template_name in command_definitions:
        prompt_name = cmd_filename.replace(".md", ".prompt.md")
        prompt_content = render_template(template_name, **tmpl_vars)
        write_if_missing(
            prompts_dir / prompt_name,
            prompt_content,
            legacy_path=legacy_runtime_prompts_dir / prompt_name,
        )

    runtime_projection_dirs = [
        (project_dir / ".claude" / "agents", agents_dir, legacy_runtime_agents_dir, True, True, None, None),
        (project_dir / ".claude" / "commands", commands_dir, legacy_runtime_commands_dir, True, True, None, None),
        (project_dir / ".claude" / "skills", skills_dir, legacy_runtime_skills_dir, True, True, None, None),
        (
            project_dir / ".codebuddy" / "agents",
            agents_dir,
            legacy_runtime_agents_dir,
            False,  # transform forces materialized copy
            True,
            None,
            rewrite_agent_frontmatter_for_codebuddy,
        ),
        (project_dir / ".codebuddy" / "commands", commands_dir, legacy_runtime_commands_dir, True, True, None, None),
        (project_dir / ".codebuddy" / "skills", skills_dir, legacy_runtime_skills_dir, True, True, None, None),
        (
            project_dir / ".github" / "skills",
            skills_dir,
            legacy_runtime_skills_dir,
            False,
            True,
            manifest_dir / "github-skills.json",
            None,
        ),
        (
            project_dir / ".github" / "prompts",
            prompts_dir,
            legacy_runtime_prompts_dir,
            False,
            True,
            manifest_dir / "github-prompts.json",
            None,
        ),
    ]
    for (
        exposure_dir,
        source_dir,
        legacy_source_dir,
        prefer_symlink,
        overwrite_existing,
        manifest_path,
        content_transform,
    ) in runtime_projection_dirs:
        materialize_runtime_projection(
            source_dir=source_dir,
            exposure_dir=exposure_dir,
            project_dir=project_dir,
            legacy_source_dir=legacy_source_dir,
            prefer_symlink=prefer_symlink,
            overwrite_existing=overwrite_existing,
            manifest_path=manifest_path,
            content_transform=content_transform,
        )

    prune_legacy_copilot_exports(
        project_dir=project_dir,
        runtime_agents_dir=agents_dir,
        runtime_commands_dir=commands_dir,
    )

    runtime_settings_paths = [
        project_dir / ".claude" / "settings.json",
        project_dir / ".codebuddy" / "settings.json",
    ]
    settings_content = read_template_raw("claude_settings.json.tmpl")
    for settings_path in runtime_settings_paths:
        ensure_local_path(settings_path, project_dir, settings_path.relative_to(project_dir).as_posix())
        merge_runtime_settings(settings_path, settings_content)

    prune_legacy_runtime_sources(
        project_dir=project_dir,
        legacy_runtime_dir=legacy_runtime_dir,
        legacy_runtime_manifest_dir=legacy_runtime_manifest_dir,
        canonical_dirs={
            "agents": agents_dir,
            "commands": commands_dir,
            "skills": skills_dir,
            "hooks": hooks_dir,
            "prompts": prompts_dir,
        },
    )

    sync_runtime_manifest_baseline(project_dir, project_slug)


def handle_upgrade(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )

    ensure_theking_scaffold(project_dir, project_slug)

    artifacts = collect_managed_runtime_artifacts(project_dir, project_slug)
    manifest = load_runtime_manifest(project_dir)

    dry_run = bool(getattr(args, "dry_run", False))
    force = bool(getattr(args, "force", False))
    adopt = bool(getattr(args, "adopt", False))

    if adopt and force:
        raise WorkflowError("--adopt and --force are mutually exclusive.")

    backup_dir: Path | None = None
    statuses: dict[str, list[str]] = {
        "created": [],
        "current": [],
        "upgraded": [],
        "adopted": [],
        "drift": [],
        "forced": [],
    }

    def _backup(relative_key: str, absolute_path: Path) -> None:
        nonlocal backup_dir
        if backup_dir is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = project_dir / RUNTIME_BACKUP_ROOT_RELATIVE / timestamp
        target = backup_dir / relative_key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(absolute_path, target)

    manifest_updates: dict[str, str] = dict(manifest)
    manifest_removals: set[str] = set()

    for absolute_path, rendered in artifacts:
        key = _manifest_key(project_dir, absolute_path)
        template_hash = _sha256_text(rendered)
        tracked_hash = manifest.get(key)

        if not absolute_path.exists():
            if dry_run:
                statuses["created"].append(key)
                continue
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            absolute_path.write_text(rendered, encoding="utf-8")
            manifest_updates[key] = template_hash
            statuses["created"].append(key)
            continue

        try:
            on_disk = absolute_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            statuses["drift"].append(key)
            continue
        on_disk_hash = _sha256_text(on_disk)

        if on_disk_hash == template_hash:
            if tracked_hash != template_hash:
                manifest_updates[key] = template_hash
            statuses["current"].append(key)
            continue

        if adopt:
            if dry_run:
                statuses["adopted"].append(key)
                continue
            manifest_updates[key] = on_disk_hash
            statuses["adopted"].append(key)
            continue

        if tracked_hash is not None and tracked_hash == on_disk_hash:
            # Safe upgrade: last-known theking-owned content, user did not touch it.
            if dry_run:
                statuses["upgraded"].append(key)
                continue
            absolute_path.write_text(rendered, encoding="utf-8")
            manifest_updates[key] = template_hash
            statuses["upgraded"].append(key)
            continue

        # Drift: on-disk content differs from both template and manifest.
        if force:
            if dry_run:
                statuses["forced"].append(key)
                continue
            _backup(key, absolute_path)
            absolute_path.write_text(rendered, encoding="utf-8")
            manifest_updates[key] = template_hash
            statuses["forced"].append(key)
            continue

        statuses["drift"].append(key)

    if not dry_run and manifest_updates != manifest:
        # Prune entries we removed explicitly (none yet in this flow) and save.
        for stale in manifest_removals:
            manifest_updates.pop(stale, None)
        save_runtime_manifest(project_dir, manifest_updates)

    def _emit(label: str, entries: list[str]) -> None:
        if not entries:
            return
        print(f"{label} ({len(entries)}):")
        for entry in entries:
            print(f"  - {entry}")

    order = ["created", "upgraded", "adopted", "forced", "drift", "current"]
    labels = {
        "created": "Created",
        "upgraded": "Upgraded",
        "adopted": "Adopted (manifest baselined to on-disk)",
        "forced": "Force-upgraded (backups saved)",
        "drift": "Drift — left untouched (use --force to overwrite with backup, or --adopt to keep)",
        "current": "Current",
    }

    header = "Upgrade plan (dry run)" if dry_run else "Upgrade result"
    print(header)
    for key in order:
        _emit(labels[key], statuses[key])

    if backup_dir is not None:
        print(f"Backups: {backup_dir.relative_to(project_dir).as_posix()}")

    if statuses["drift"] and not force and not adopt:
        print(
            "Some files drifted from their tracked template content. "
            "Review the diff, then re-run with --force to overwrite "
            "(the old version is backed up) or --adopt to keep your edits.",
            file=sys.stderr,
        )


def merge_runtime_settings(settings_path: Path, template_content: str) -> None:
    template_data = json.loads(template_content)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    if not settings_path.exists():
        write_if_missing(settings_path, template_content)
        return

    try:
        existing_data = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError(
            f"settings.json must contain valid JSON before merging theking hooks: {settings_path}"
        ) from error
    if not isinstance(existing_data, dict):
        raise WorkflowError(f"settings.json must contain a JSON object before merging: {settings_path}")
    existing_data = replace_legacy_hook_paths(existing_data)
    validate_runtime_settings_shape(existing_data, settings_path)
    merged_data = dict(existing_data)
    merged_hooks = dict(existing_data.get("hooks", {}))
    template_hooks = template_data.get("hooks", {})

    for hook_stage, hook_entries in template_hooks.items():
        existing_entries = list(merged_hooks.get(hook_stage, []))
        for hook_entry in hook_entries:
            if hook_entry not in existing_entries:
                existing_entries.append(hook_entry)
        merged_hooks[hook_stage] = existing_entries

    merged_data["hooks"] = merged_hooks
    if merged_data != existing_data:
        settings_path.write_text(json.dumps(merged_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def materialize_runtime_projection(
    *,
    source_dir: Path,
    exposure_dir: Path,
    project_dir: Path,
    legacy_source_dir: Path | None,
    prefer_symlink: bool,
    overwrite_existing: bool,
    manifest_path: Path | None,
    content_transform: Callable[[str, str], str] | None = None,
) -> None:
    label = exposure_dir.relative_to(project_dir).as_posix()
    ensure_local_path(source_dir, project_dir, f"runtime source for {label}")
    ensure_projection_tree_has_no_symlinks(source_dir, project_dir, f"runtime source for {label}")
    if manifest_path is not None:
        ensure_local_path(manifest_path, project_dir, manifest_path.relative_to(project_dir).as_posix())

    # Content transforms require materialized files, so symlinks would expose
    # the wrong flavor to the target runtime.
    if content_transform is not None:
        prefer_symlink = False

    if exposure_dir.is_symlink():
        resolved = exposure_dir.resolve(strict=False)
        ensure_within_directory(resolved, project_dir.resolve(), label)
        if content_transform is not None:
            # A previously-installed symlink predates the transform; replace it
            # with a real directory so we can write flavored content.
            exposure_dir.unlink()
        elif legacy_source_dir is not None and resolved == legacy_source_dir.resolve(strict=False):
            legacy_issue = describe_legacy_runtime_tree_drift(source_dir, legacy_source_dir)
            if legacy_issue is not None:
                raise WorkflowError(legacy_issue)
            exposure_dir.unlink()
            try:
                relative_target = os.path.relpath(source_dir, exposure_dir.parent)
                exposure_dir.symlink_to(relative_target, target_is_directory=True)
                return
            except OSError:
                exposure_dir.mkdir(parents=True, exist_ok=True)
                copy_directory_if_missing(
                    source_dir,
                    exposure_dir,
                    legacy_source_dir=legacy_source_dir,
                    overwrite_existing=overwrite_existing,
                    content_transform=content_transform,
                )
                if manifest_path is not None:
                    update_export_manifest(source_dir, manifest_path)
                return
        else:
            if resolved != source_dir.resolve():
                raise WorkflowError(f"{label} symlink must point to {source_dir}")
            return

    if exposure_dir.exists():
        if not exposure_dir.is_dir():
            raise WorkflowError(f"{label} must be a directory")
        ensure_projection_tree_has_no_symlinks(exposure_dir, project_dir, label)
        if overwrite_existing and manifest_path is not None:
            prune_managed_export_targets(source_dir, exposure_dir, manifest_path)
        copy_directory_if_missing(
            source_dir,
            exposure_dir,
            legacy_source_dir=legacy_source_dir,
            overwrite_existing=overwrite_existing,
            content_transform=content_transform,
        )
        if manifest_path is not None:
            update_export_manifest(source_dir, manifest_path)
        return

    ensure_local_path(exposure_dir.parent, project_dir, exposure_dir.parent.relative_to(project_dir).as_posix())
    exposure_dir.parent.mkdir(parents=True, exist_ok=True)
    if prefer_symlink:
        try:
            relative_target = os.path.relpath(source_dir, exposure_dir.parent)
            exposure_dir.symlink_to(relative_target, target_is_directory=True)
            return
        except OSError:
            pass

    exposure_dir.mkdir(parents=True, exist_ok=True)
    copy_directory_if_missing(
        source_dir,
        exposure_dir,
        legacy_source_dir=legacy_source_dir,
        overwrite_existing=overwrite_existing,
        content_transform=content_transform,
    )
    if manifest_path is not None:
        update_export_manifest(source_dir, manifest_path)


def copy_directory_if_missing(
    source_dir: Path,
    target_dir: Path,
    *,
    legacy_source_dir: Path | None,
    overwrite_existing: bool,
    content_transform: Callable[[str, str], str] | None = None,
) -> None:
    for source_path in sorted(source_dir.rglob("*"), key=lambda path: path.as_posix()):
        relative_path = source_path.relative_to(source_dir)
        target_path = target_dir / relative_path
        if target_path.is_symlink():
            raise WorkflowError(f"runtime projection must not traverse symlinks: {target_path}")
        if source_path.is_dir():
            if target_path.exists() and not target_path.is_dir():
                raise WorkflowError(f"runtime projection path must be a directory: {target_path}")
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        if target_path.exists() and target_path.is_dir():
            raise WorkflowError(f"runtime projection path must be a file: {target_path}")
        source_content = source_path.read_text(encoding="utf-8")
        if content_transform is not None:
            source_content = content_transform(relative_path.as_posix(), source_content)
        legacy_path = legacy_source_dir / relative_path if legacy_source_dir is not None else None
        if overwrite_existing and target_path.exists():
            if target_path.is_symlink():
                raise WorkflowError(f"runtime projection must not traverse symlinks: {target_path}")
            if target_path.read_text(encoding="utf-8") != source_content:
                target_path.write_text(source_content, encoding="utf-8")
            continue
        if target_path.exists() and legacy_path is not None and legacy_path.is_file():
            target_content = target_path.read_text(encoding="utf-8")
            legacy_content = legacy_path.read_text(encoding="utf-8")
            if target_content == legacy_content and target_content != source_content:
                target_path.write_text(source_content, encoding="utf-8")
                continue
        write_if_missing(target_path, source_content)


def prune_legacy_copilot_exports(
    *,
    project_dir: Path,
    runtime_agents_dir: Path,
    runtime_commands_dir: Path,
) -> None:
    legacy_exports = [
        (project_dir / ".github" / "agents", runtime_agents_dir),
        (project_dir / ".github" / "commands", runtime_commands_dir),
    ]

    for legacy_dir, source_dir in legacy_exports:
        label = legacy_dir.relative_to(project_dir).as_posix()
        if not legacy_dir.exists():
            continue
        ensure_local_path(legacy_dir, project_dir, label)
        if legacy_dir.is_symlink():
            raise WorkflowError(f"{label} must not be a symlink")
        if not legacy_dir.is_dir():
            raise WorkflowError(f"{label} must be a directory")
        ensure_projection_tree_has_no_symlinks(legacy_dir, project_dir, label)
        if not is_exact_runtime_mirror(source_dir, legacy_dir):
            continue
        remove_directory_tree(legacy_dir)


def is_exact_runtime_mirror(source_dir: Path, target_dir: Path) -> bool:
    source_files, source_dirs = collect_directory_tree_manifest(source_dir)
    target_files, target_dirs = collect_directory_tree_manifest(target_dir)
    if target_files != source_files:
        return False
    if target_dirs != source_dirs:
        return False

    for relative_path in target_files:
        if (source_dir / relative_path).read_text(encoding="utf-8") != (target_dir / relative_path).read_text(
            encoding="utf-8"
        ):
            return False
    return True


def prune_legacy_runtime_sources(
    *,
    project_dir: Path,
    legacy_runtime_dir: Path,
    legacy_runtime_manifest_dir: Path,
    canonical_dirs: dict[str, Path],
) -> None:
    if not legacy_runtime_dir.exists():
        return
    ensure_local_path(legacy_runtime_dir, project_dir, legacy_runtime_dir.relative_to(project_dir).as_posix())
    if legacy_runtime_dir.is_symlink():
        raise WorkflowError(f"legacy runtime directory must not be a symlink: {legacy_runtime_dir}")
    if not legacy_runtime_dir.is_dir():
        raise WorkflowError(f"legacy runtime path must be a directory: {legacy_runtime_dir}")
    ensure_projection_tree_has_no_symlinks(
        legacy_runtime_dir,
        project_dir,
        legacy_runtime_dir.relative_to(project_dir).as_posix(),
    )
    validate_legacy_runtime_manifest_dir(legacy_runtime_manifest_dir)

    removable_children: list[Path] = []
    allowed_names: set[str] = set()
    for name, canonical_dir in canonical_dirs.items():
        legacy_dir = legacy_runtime_dir / name
        if not legacy_dir.exists():
            continue
        if not legacy_dir.is_dir():
            raise WorkflowError(f"legacy runtime path must be a directory: {legacy_dir}")
        legacy_issue = describe_legacy_runtime_tree_drift(canonical_dir, legacy_dir)
        if legacy_issue is not None:
            raise WorkflowError(legacy_issue)
        removable_children.append(legacy_dir)
        allowed_names.add(name)

    if legacy_runtime_manifest_dir.exists():
        allowed_names.add(legacy_runtime_manifest_dir.name)

    current_names = {child.name for child in legacy_runtime_dir.iterdir()}
    if current_names - allowed_names:
        unexpected_name = sorted(current_names - allowed_names)[0]
        raise WorkflowError(
            f"legacy runtime artifact has no canonical destination: {legacy_runtime_dir / unexpected_name}"
        )

    for child in removable_children:
        remove_directory_tree(child)
    if legacy_runtime_manifest_dir.exists():
        remove_directory_tree(legacy_runtime_manifest_dir)
    if legacy_runtime_dir.exists() and not any(legacy_runtime_dir.iterdir()):
        legacy_runtime_dir.rmdir()


def collect_directory_tree_manifest(directory: Path) -> tuple[set[str], set[str]]:
    file_paths: set[str] = set()
    dir_paths: set[str] = set()
    for path in directory.rglob("*"):
        if path.name in {".DS_Store", "Thumbs.db"}:
            continue
        relative_path = path.relative_to(directory).as_posix()
        if path.is_file():
            file_paths.add(relative_path)
        elif path.is_dir():
            dir_paths.add(relative_path)
    return file_paths, dir_paths


def describe_legacy_runtime_tree_drift(canonical_dir: Path, legacy_dir: Path) -> str | None:
    canonical_files, canonical_dirs = collect_directory_tree_manifest(canonical_dir)
    legacy_files, legacy_dirs = collect_directory_tree_manifest(legacy_dir)

    extra_legacy_dirs = sorted(legacy_dirs - canonical_dirs)
    if extra_legacy_dirs:
        return f"legacy runtime artifact has no canonical destination: {legacy_dir / extra_legacy_dirs[0]}"

    extra_legacy_files = sorted(legacy_files - canonical_files)
    if extra_legacy_files:
        return f"legacy runtime artifact has no canonical destination: {legacy_dir / extra_legacy_files[0]}"

    for relative_path in sorted(legacy_files):
        canonical_path = canonical_dir / relative_path
        legacy_path = legacy_dir / relative_path
        if canonical_path.read_text(encoding="utf-8") != legacy_path.read_text(encoding="utf-8"):
            return f"Canonical artifact conflicts with legacy artifact: {canonical_path} vs {legacy_path}"

    return None


def validate_legacy_runtime_manifest_dir(legacy_runtime_manifest_dir: Path) -> None:
    if not legacy_runtime_manifest_dir.exists():
        return
    if legacy_runtime_manifest_dir.is_symlink():
        raise WorkflowError(
            f"legacy runtime manifest directory must not be a symlink: {legacy_runtime_manifest_dir}"
        )
    if not legacy_runtime_manifest_dir.is_dir():
        raise WorkflowError(f"legacy runtime manifest path must be a directory: {legacy_runtime_manifest_dir}")

    allowed_manifest_files = {"github-skills.json", "github-prompts.json"}
    for path in sorted(legacy_runtime_manifest_dir.rglob("*"), key=lambda child: child.as_posix()):
        if path.name in {".DS_Store", "Thumbs.db"}:
            continue
        if path.is_symlink():
            raise WorkflowError(f"legacy runtime manifest directory must not contain symlinks: {path}")
        if path.is_dir():
            raise WorkflowError(f"legacy runtime manifest path must be a file: {path}")
        relative_path = path.relative_to(legacy_runtime_manifest_dir).as_posix()
        if relative_path not in allowed_manifest_files:
            raise WorkflowError(f"legacy runtime manifest artifact has no canonical destination: {path}")


def remove_directory_tree(directory: Path) -> None:
    for child in sorted(directory.rglob("*"), key=lambda path: path.as_posix(), reverse=True):
        if child.is_symlink():
            raise WorkflowError(f"legacy export cleanup must not traverse symlinks: {child}")
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    directory.rmdir()


def ensure_projection_tree_has_no_symlinks(directory: Path, project_dir: Path, label: str) -> None:
    ensure_local_path(directory, project_dir, label)
    for child in directory.rglob("*"):
        if child.is_symlink():
            raise WorkflowError(f"{label} must not contain symlinks: {child}")


def prune_managed_export_targets(source_dir: Path, target_dir: Path, manifest_path: Path) -> None:
    managed_paths = load_export_manifest(manifest_path)
    current_paths = collect_source_file_manifest(source_dir)
    stale_paths = sorted(managed_paths - current_paths, reverse=True)

    for relative_path in stale_paths:
        target_path = target_dir / relative_path
        ensure_within_directory(target_path.resolve(strict=False), target_dir.resolve(), "managed export target")
        if target_path.is_symlink():
            raise WorkflowError(f"runtime projection must not traverse symlinks: {target_path}")
        if not target_path.exists():
            continue
        if target_path.is_dir():
            raise WorkflowError(f"managed export target must be a file: {target_path}")
        target_path.unlink()
        parent = target_path.parent
        while parent != target_dir and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def load_export_manifest(manifest_path: Path) -> set[str]:
    if not manifest_path.exists():
        return set()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError(f"Export manifest must contain valid JSON: {manifest_path}") from error
    if not isinstance(data, list):
        raise WorkflowError(f"Export manifest must be a JSON array: {manifest_path}")
    managed_paths: set[str] = set()
    for index, value in enumerate(data):
        managed_paths.add(normalize_manifest_entry(value, manifest_path, index))
    return managed_paths


def collect_source_file_manifest(source_dir: Path) -> set[str]:
    return {
        source_path.relative_to(source_dir).as_posix()
        for source_path in source_dir.rglob("*")
        if source_path.is_file()
    }


def update_export_manifest(source_dir: Path, manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(sorted(collect_source_file_manifest(source_dir)), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def normalize_manifest_entry(value: Any, manifest_path: Path, index: int) -> str:
    if not isinstance(value, str):
        raise WorkflowError(f"Export manifest entry {index} must be a string: {manifest_path}")
    normalized = PurePosixPath(value)
    if not value or normalized.is_absolute() or any(part == ".." for part in normalized.parts):
        raise WorkflowError(f"Export manifest entry {index} must stay within the export directory: {manifest_path}")
    if normalized.as_posix() in {"", "."}:
        raise WorkflowError(f"Export manifest entry {index} must not be empty: {manifest_path}")
    return normalized.as_posix()


def replace_legacy_hook_paths(settings_data: dict[str, Any]) -> dict[str, Any]:
    old_prefix = ".theking/runtime/hooks/"
    new_prefix = ".theking/hooks/"
    migrated = json.loads(json.dumps(settings_data))
    hooks = migrated.get("hooks")
    if not isinstance(hooks, dict):
        return migrated

    for hook_stage, hook_entries in hooks.items():
        if not isinstance(hook_entries, list):
            continue
        normalized_entries: list[dict[str, Any]] = []
        for hook_entry in hook_entries:
            if not isinstance(hook_entry, dict):
                normalized_entries.append(hook_entry)
                continue
            normalized_entry = json.loads(json.dumps(hook_entry))
            hook_list = normalized_entry.get("hooks")
            if isinstance(hook_list, list):
                for hook in hook_list:
                    if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                        hook["command"] = hook["command"].replace(old_prefix, new_prefix)
            normalized_entries.append(normalized_entry)
        hooks[hook_stage] = normalized_entries

    return migrated


def validate_runtime_settings_shape(settings_data: dict[str, Any], settings_path: Path) -> None:
    hooks = settings_data.get("hooks")
    if hooks is None:
        return
    if not isinstance(hooks, dict):
        raise WorkflowError(f"settings.json hooks must be an object before merging: {settings_path}")
    for hook_stage, hook_entries in hooks.items():
        if not isinstance(hook_entries, list):
            raise WorkflowError(
                f"settings.json hooks.{hook_stage} must be a list before merging: {settings_path}"
            )
        for index, hook_entry in enumerate(hook_entries):
            if not isinstance(hook_entry, dict):
                raise WorkflowError(
                    f"settings.json hooks.{hook_stage}[{index}] must be an object before merging: {settings_path}"
                )
            nested_hooks = hook_entry.get("hooks")
            if nested_hooks is None:
                continue
            if not isinstance(nested_hooks, list):
                raise WorkflowError(
                    f"settings.json hooks.{hook_stage}[{index}].hooks must be a list before merging: {settings_path}"
                )
            for nested_index, nested_hook in enumerate(nested_hooks):
                if not isinstance(nested_hook, dict):
                    raise WorkflowError(
                        f"settings.json hooks.{hook_stage}[{index}].hooks[{nested_index}] must be an object before merging: {settings_path}"
                    )
                if "type" in nested_hook and not isinstance(nested_hook["type"], str):
                    raise WorkflowError(
                        f"settings.json hooks.{hook_stage}[{index}].hooks[{nested_index}].type must be a string before merging: {settings_path}"
                    )
                if "command" in nested_hook and not isinstance(nested_hook["command"], str):
                    raise WorkflowError(
                        f"settings.json hooks.{hook_stage}[{index}].hooks[{nested_index}].command must be a string before merging: {settings_path}"
                    )


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise WorkflowError(f"{label} must be a string")
    return value


def collect_task_overview_entries(tasks_dir: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for task_dir in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
        if task_dir.is_symlink() or not task_dir.is_dir():
            continue
        if TASK_ID_PATTERN.fullmatch(task_dir.name) is None:
            continue
        task_md = task_dir / "task.md"
        if not task_md.is_file():
            continue
        task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
        depends_on = task_data.get("depends_on", [])
        entries.append(
            {
                "task_id": stringify(task_data["id"]),
                "task_type": stringify(task_data["task_type"]),
                "execution_profile": stringify(task_data["execution_profile"]),
                "depends_on": ", ".join(stringify(dep) for dep in depends_on)
                if isinstance(depends_on, list) and depends_on
                else "\u2014",
                "status": stringify(task_data["status"]),
            }
        )
    return entries


if __name__ == "__main__":
    raise SystemExit(main())
