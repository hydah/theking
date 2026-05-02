from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .constants import (
        ALLOWED_EXECUTION_PROFILES,
        ALLOWED_TASK_TYPE_TOKENS,
        EXECUTION_PROFILE_DIRS,
        TERMINAL_STATUSES,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from .scaffold import (
        RUNTIME_BACKUP_ROOT_RELATIVE,
        collect_managed_runtime_artifacts,
        ensure_theking_scaffold,
        load_runtime_manifest,
        manifest_key,
        save_runtime_manifest,
        sha256_text,
    )
    from .sessions import (
        describe_recovery_source,
        find_latest_unfinished_task,
        load_active_task_status,
        load_decree_checkpoint,
        write_decree_checkpoint,
    )
    from .doctor import (
        format_report_json,
        format_report_summary,
        format_report_text,
        run_diagnostics,
    )
    from .sprint_plan import (
        parse_bundles,
        parse_plan_entries,
        reject_sealed_sprint_for_writes,
        render_sprint_md,
        require_string,
        split_sprint_md,
        update_sprint_overview,
        utc_iso8601_z,
        write_task_files,
    )
    from .validation import (
        STATUS_NEXT_STEP_HINTS,
        apply_status_transition,
        derive_task_paths,
        ensure_absent,
        ensure_file,
        ensure_local_path,
        ensure_within_directory,
        execution_profile_dir,
        get_project_dir,
        get_theking_dir,
        get_workflow_project_dir,
        humanize_slug,
        infer_blocked_resume_status,
        infer_default_review_mode,
        infer_execution_profile,
        infer_required_agents,
        infer_verification_profile,
        load_task_document,
        next_index,
        normalize_execution_profile,
        normalize_sprint_name,
        normalize_task_type,
        normalize_title,
        render_template,
        resolve_review_mode,
        review_type_specs_for_task,
        slugify,
        stringify,
        task_requires_security_review,
        validate_sprint_dir,
        validate_sprint_location,
        validate_sprint_smoke_evidence,
        validate_task_contract,
        validate_task_dir,
        validate_handoff_evidence_anchors,
        write_if_missing,
        write_task_document,
    )
except ImportError:
    from constants import (
        ALLOWED_EXECUTION_PROFILES,
        ALLOWED_TASK_TYPE_TOKENS,
        EXECUTION_PROFILE_DIRS,
        TERMINAL_STATUSES,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from scaffold import (
        RUNTIME_BACKUP_ROOT_RELATIVE,
        collect_managed_runtime_artifacts,
        ensure_theking_scaffold,
        load_runtime_manifest,
        manifest_key,
        save_runtime_manifest,
        sha256_text,
    )
    from sessions import (
        describe_recovery_source,
        find_latest_unfinished_task,
        load_active_task_status,
        load_decree_checkpoint,
        write_decree_checkpoint,
    )
    from doctor import (
        format_report_json,
        format_report_summary,
        format_report_text,
        run_diagnostics,
    )
    from sprint_plan import (
        parse_bundles,
        parse_plan_entries,
        reject_sealed_sprint_for_writes,
        render_sprint_md,
        require_string,
        split_sprint_md,
        update_sprint_overview,
        utc_iso8601_z,
        write_task_files,
    )
    from validation import (
        STATUS_NEXT_STEP_HINTS,
        apply_status_transition,
        derive_task_paths,
        ensure_absent,
        ensure_file,
        ensure_local_path,
        ensure_within_directory,
        execution_profile_dir,
        get_project_dir,
        get_theking_dir,
        get_workflow_project_dir,
        humanize_slug,
        infer_blocked_resume_status,
        infer_default_review_mode,
        infer_execution_profile,
        infer_required_agents,
        infer_verification_profile,
        load_task_document,
        next_index,
        normalize_execution_profile,
        normalize_sprint_name,
        normalize_task_type,
        normalize_title,
        render_template,
        resolve_review_mode,
        review_type_specs_for_task,
        slugify,
        stringify,
        task_requires_security_review,
        validate_sprint_dir,
        validate_sprint_location,
        validate_sprint_smoke_evidence,
        validate_task_contract,
        validate_task_dir,
        validate_handoff_evidence_anchors,
        write_if_missing,
        write_task_document,
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


def _task_type_help() -> str:
    tokens = ", ".join(sorted(ALLOWED_TASK_TYPE_TOKENS))
    return (
        "Task type token. Use a single token or comma-separated combination "
        f"(e.g. 'auth,api'). Allowed tokens: {tokens}."
    )


def _execution_profile_help() -> str:
    profiles = ", ".join(sorted(ALLOWED_EXECUTION_PROFILES))
    return (
        "Optional execution profile. If omitted, inferred from --task-type. "
        f"Allowed values: {profiles}."
    )


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
    init_task.add_argument(
        "--task-type",
        required=True,
        help=_task_type_help(),
    )
    init_task.add_argument(
        "--execution-profile",
        help=_execution_profile_help(),
    )
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

    sprint_smoke = add_command_parser(
        subparsers,
        "sprint-smoke",
        help_text=(
            "Verify that every execution_profile used by a sprint's tasks has "
            "substantive evidence under sprint_dir/verification/<profile>/ "
            "(ADR-003 hard rule #9). No --skip-smoke flag by design."
        ),
        example="workflowctl sprint-smoke --sprint-dir .theking/workflows/my-app/sprints/sprint-001-foundation",
    )
    sprint_smoke.add_argument("--sprint-dir", required=True)
    sprint_smoke.set_defaults(handler=handle_sprint_smoke)

    seal_sprint = add_command_parser(
        subparsers,
        "seal-sprint",
        help_text="Mark a sprint immutable after every task reaches done/blocked.",
        example="workflowctl seal-sprint --sprint-dir .theking/workflows/my-app/sprints/sprint-001-foundation",
    )
    seal_sprint.add_argument("--sprint-dir", required=True)
    seal_sprint.set_defaults(handler=handle_seal_sprint)

    followup_sprint = add_command_parser(
        subparsers,
        "followup-sprint",
        help_text="Create a new sprint that back-links to a prior sprint as its source.",
        example=(
            "workflowctl followup-sprint --project-dir . --project-slug my-app "
            "--source-sprint .theking/workflows/my-app/sprints/sprint-001-foundation "
            "--new-theme edge-case-fix --reason \"Caught a missed branch.\""
        ),
    )
    add_project_locator_arguments(followup_sprint)
    add_project_slug_argument(followup_sprint)
    followup_sprint.add_argument("--source-sprint", required=True)
    followup_sprint.add_argument("--new-theme", required=True)
    followup_sprint.add_argument("--reason", required=True)
    followup_sprint.set_defaults(handler=handle_followup_sprint)

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

    doctor = add_command_parser(
        subparsers,
        "doctor",
        help_text=(
            "Read-only repo-level health check (zombie tasks, stale checkpoints, "
            "stale active-task markers, missing projections, broken review pairs)."
        ),
        example="workflowctl doctor --project-dir . --project-slug my-app",
    )
    add_project_locator_arguments(doctor)
    add_project_slug_argument(doctor)
    doctor.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit findings as JSON (errors/warnings/info/summary).",
    )
    doctor.add_argument(
        "--summary",
        action="store_true",
        dest="summary_output",
        help="Emit a concise aggregated summary (TL;DR + per-category counts + open tasks).",
    )
    doctor.set_defaults(handler=handle_doctor)

    finalize = add_command_parser(
        subparsers,
        "finalize",
        help_text="Run check + advance to ready_to_merge + advance to done in one call.",
        example="workflowctl finalize --task-dir .theking/workflows/my-app/sprints/sprint-001-foundation/tasks/TASK-001-demo",
    )
    finalize.add_argument("--task-dir", required=True)
    finalize.set_defaults(handler=handle_finalize)

    verify = add_command_parser(
        subparsers,
        "verify",
        help_text=(
            "Run a command and append its output to verification/<profile>/evidence.md; "
            "auto-append one line to agent-runs.jsonl. Wrapped command failure does NOT "
            "propagate into verify's own exit code (only verify_error does)."
        ),
        example=(
            "workflowctl verify --task-dir <TASK_DIR> --profile backend.cli "
            "--command 'pytest tests/' --evidence-section unit-suite"
        ),
    )
    verify.add_argument("--task-dir", required=True)
    verify.add_argument(
        "--profile",
        required=True,
        help="Execution profile name (web.browser / backend.http / backend.cli / backend.job).",
    )
    verify.add_argument(
        "--command",
        required=True,
        help="Shell command string. Executed as `<shell> -c <command>`.",
    )
    verify.add_argument(
        "--evidence-section",
        required=True,
        help="Evidence section name (anchor for '## <section>' in evidence.md).",
    )
    verify.add_argument("--cwd", default=None, help="Working directory for the command (default: task_dir).")
    verify.add_argument("--timeout", type=int, default=300, help="Timeout in seconds (default: 300).")
    verify.add_argument("--shell", default="/bin/bash", help="Shell binary (default: /bin/bash).")
    verify.set_defaults(handler=handle_verify)

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
    reject_sealed_sprint_for_writes(sprint_dir)

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
    review_mode = infer_default_review_mode(task_type, execution_profile)

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
        review_mode=review_mode,
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

    # Handoff evidence anchor gate: only fires on planned->red.
    # File-existence-first — legacy tasks without handoff.md are not punished.
    if requested_status == "red" and stringify(task_data["status"]) == "planned":
        validate_handoff_evidence_anchors(task_paths.task_dir / "handoff.md")

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
        if current_status == "in_review":
            raise WorkflowError(
                "init-review-round requires task status green or changes_requested. "
                f"Task is already in_review (round {int(task_data['current_review_round'])}). "
                "Hint: if the current round is resolved, run "
                "`workflowctl advance-status --to-status ready_to_merge`. "
                "Only run init-review-round again AFTER you advance to changes_requested "
                "and fix code — running it now will force an empty extra round."
            )
        raise WorkflowError(
            "init-review-round requires task status green or changes_requested. "
            f"Current status: {current_status}. "
            f"Hint: {STATUS_NEXT_STEP_HINTS.get(current_status, 'advance status first')}"
        )

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
    reject_sealed_sprint_for_writes(sprint_dir)

    tasks_dir = sprint_dir / "tasks"
    ensure_local_path(tasks_dir, project_dir, "tasks")
    tasks_dir.mkdir(exist_ok=True)

    parsed = parse_plan_entries(task_entries, tasks_dir)

    # --- Parse bundles (optional; backward-compatible) ---
    bundle_entries = plan_data.get("bundles", [])
    if not isinstance(bundle_entries, list):
        raise WorkflowError("'bundles' must be an array when provided")
    bundle_map: dict[str, str] = {}  # task_slug -> bundle_slug
    if bundle_entries:
        bundles = parse_bundles(
            bundle_entries,
            parsed["slug_to_id"],
            parsed["deps_by_slug"],
        )
        for bundle_slug, info in bundles.items():
            for task_slug in info["task_slugs"]:
                bundle_map[task_slug] = bundle_slug

    # Two-pass validation: first collect every per-task problem, then report
    # them all at once. This lets the agent fix multiple broken rows in a
    # single edit cycle instead of being drip-fed one error per run
    # (which was the Kimi CLI feedback pain point).
    prepared_entries: list[dict[str, Any]] = []
    plan_errors: list[str] = []
    for entry in parsed["entries"]:
        task_id = entry["_task_id"]
        slug = entry["_slug"]
        try:
            title = normalize_title(
                require_string(entry["title"], f"Task {task_id} field 'title'")
            )
            task_type = normalize_task_type(
                require_string(entry["task_type"], f"Task {task_id} field 'task_type'")
            )
            execution_profile = (
                normalize_execution_profile(
                    require_string(
                        entry["execution_profile"],
                        f"Task {task_id} field 'execution_profile'",
                    )
                )
                if "execution_profile" in entry
                else infer_execution_profile(task_type)
            )
            validate_task_contract(task_type, execution_profile)
            review_mode = (
                resolve_review_mode(entry["review_mode"], task_type, execution_profile)
                if "review_mode" in entry
                else infer_default_review_mode(task_type, execution_profile)
            )
        except WorkflowError as error:
            plan_errors.append(f"[{slug}] {error}")
            continue
        verification_profile = infer_verification_profile(execution_profile)
        requires_security_review = task_requires_security_review(task_type, execution_profile)
        required_agents = infer_required_agents(task_type, execution_profile)
        resolved_deps = parsed["deps_by_slug"][slug]

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
                "review_mode": review_mode,
            }
        )

    if plan_errors:
        header = f"Plan file has {len(plan_errors)} invalid task(s):"
        bullets = "\n  - ".join(plan_errors)
        raise WorkflowError(f"{header}\n  - {bullets}")

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
                bundle=bundle_map.get(entry["_slug"]) if bundle_map else None,
                review_mode=entry.get("review_mode", "light"),
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


def handle_sprint_smoke(args: argparse.Namespace) -> None:
    """Verify the sprint has substantive cross-task evidence for every
    execution_profile its tasks declare (ADR-003 hard rule #9).

    Callable standalone (audit trail) or as a pre-check inside
    ``handle_seal_sprint``. No ``--skip`` flag by design — I-003 forbids
    hard-rule opt-outs.
    """

    input_sprint_dir = Path(args.sprint_dir).expanduser()
    if input_sprint_dir.is_symlink():
        raise WorkflowError(f"sprint_dir must not be a symlink: {input_sprint_dir}")
    sprint_dir = input_sprint_dir.resolve()
    # Enforce theking layout parity with sprint-check so users cannot
    # accidentally run sprint-smoke on a non-theking dir and get a
    # misleading OK / wrong-profile error. MEDIUM finding in
    # code-review-round-001.
    validate_sprint_location(sprint_dir)
    ensure_file(sprint_dir / "sprint.md", "sprint.md")
    validate_sprint_smoke_evidence(sprint_dir)
    print(f"OK {sprint_dir}")


def handle_seal_sprint(args: argparse.Namespace) -> None:
    """Mark a sprint sealed by writing leading frontmatter on sprint.md.

    Pre-conditions:
    - Every TASK-* directory under tasks/ must have task.md whose status is
      in ``TERMINAL_STATUSES`` (done / blocked).
    - The sprint must contain at least one task (sealing an empty sprint
      destroys audit signal — there is nothing to lock down).

    Idempotent: re-running on an already-sealed sprint is a no-op and
    preserves the original ``sealed_at`` timestamp.
    """

    input_sprint_dir = Path(args.sprint_dir).expanduser()
    if input_sprint_dir.is_symlink():
        raise WorkflowError(f"sprint_dir must not be a symlink: {input_sprint_dir}")
    sprint_dir = input_sprint_dir.resolve()

    sprint_md = sprint_dir / "sprint.md"
    ensure_file(sprint_md, "sprint.md")

    # Parse frontmatter first so a malformed / unknown-key block fails BEFORE
    # we walk the task tree.
    frontmatter, body = split_sprint_md(sprint_md.read_text(encoding="utf-8"))

    if frontmatter.get("status") == "sealed":
        print(f"Sprint already sealed: {sprint_dir}")
        return

    tasks_dir = sprint_dir / "tasks"
    if not tasks_dir.is_dir():
        raise WorkflowError(f"sprint has no tasks directory; nothing to seal: {sprint_dir}")

    task_dirs: list[Path] = []
    for child in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
        if child.is_symlink():
            raise WorkflowError(f"task entry must not be a symlink: {child.name}")
        if child.is_dir() and child.name.startswith("TASK-"):
            task_dirs.append(child)

    if not task_dirs:
        raise WorkflowError(
            f"sprint has no tasks; nothing to seal: {sprint_dir}. "
            "Sealing is meant to lock a delivered sprint, not a placeholder."
        )

    non_terminal: list[tuple[str, str]] = []
    for task_dir in task_dirs:
        task_md = task_dir / "task.md"
        if not task_md.is_file():
            non_terminal.append((task_dir.name, "missing task.md"))
            continue
        try:
            task_data, _body = load_task_document(task_md)
        except WorkflowError as error:
            non_terminal.append((task_dir.name, f"invalid task.md ({error})"))
            continue
        status = stringify(task_data.get("status", ""))
        if status not in TERMINAL_STATUSES:
            non_terminal.append((task_dir.name, f"status={status}"))

    if non_terminal:
        bullets = "\n  - ".join(f"{name}: {reason}" for name, reason in non_terminal)
        raise WorkflowError(
            f"Refusing to seal {sprint_dir.name}: "
            f"{len(non_terminal)} task(s) are not terminal (done/blocked):\n  - {bullets}\n"
            "Advance each to a terminal status first."
        )

    # ADR-003 hard rule #9 / sprint-004 TASK-003: every execution_profile
    # used by the sprint's tasks must have substantive evidence at the
    # SPRINT level (not just per-task). Run this AFTER the terminal-status
    # guard so a non-terminal sprint still surfaces its clearer error
    # first. Any failure here short-circuits before we touch sprint.md.
    validate_sprint_smoke_evidence(sprint_dir)

    frontmatter["status"] = "sealed"
    frontmatter["sealed_at"] = utc_iso8601_z()
    sprint_md.write_text(render_sprint_md(frontmatter, body), encoding="utf-8")
    print(f"Sealed {sprint_dir}")


def handle_followup_sprint(args: argparse.Namespace) -> None:
    """Create a new sprint that back-links to a source sprint.

    Wraps the same flow as ``handle_init_sprint`` (next_index, template
    render) plus two audit additions:

    1. Inject a ``## Follow-up Source`` section into the new sprint.md
       between ``## Theme`` and ``## Exit Criteria``.
    2. Append a single bullet line to ``<source-sprint>/followups.md``
       (creating the file from template on first followup).

    Works whether or not the source sprint is sealed. The append to
    ``followups.md`` is metadata about the source sprint, not a write to
    its sealed body, so the seal guard does not fire.
    """

    workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )

    source_input = Path(args.source_sprint).expanduser()
    if source_input.is_symlink():
        raise WorkflowError(f"source-sprint must not be a symlink: {source_input}")
    source_sprint_dir = source_input.resolve()
    if not source_sprint_dir.is_dir():
        raise WorkflowError(f"source-sprint does not exist: {source_sprint_dir}")
    try:
        normalize_sprint_name(source_sprint_dir.name)
    except WorkflowError as error:
        raise WorkflowError(
            f"source-sprint must be a sprint directory (sprint-NNN-<slug>): {source_sprint_dir.name}"
        ) from error
    source_sprint_md = source_sprint_dir / "sprint.md"
    ensure_file(source_sprint_md, "source sprint.md")

    new_theme_slug = slugify(args.new_theme)
    workflow_project_dir = get_workflow_project_dir(project_dir, project_slug)
    sprints_dir = workflow_project_dir / "sprints"
    ensure_local_path(sprints_dir, project_dir, "sprints")
    ensure_within_directory(
        source_sprint_dir, sprints_dir.resolve(), "source-sprint"
    )

    sprint_number = next_index(sprints_dir, "sprint")
    new_sprint_name = f"sprint-{sprint_number:03d}-{new_theme_slug}"
    new_sprint_dir = sprints_dir / new_sprint_name
    ensure_local_path(new_sprint_dir, project_dir, "sprint")
    new_sprint_dir.mkdir(parents=True, exist_ok=False)
    (new_sprint_dir / "tasks").mkdir(exist_ok=True)

    new_sprint_md = new_sprint_dir / "sprint.md"
    new_sprint_md.write_text(
        render_template(
            "sprint.md.tmpl",
            sprint_name=new_sprint_name,
            sprint_theme=humanize_slug(new_theme_slug),
            exit_criteria="All scoped tasks reach ready_to_merge or done.",
        ),
        encoding="utf-8",
    )

    one_line_reason = " ".join(args.reason.splitlines()).strip()
    if not one_line_reason:
        raise WorkflowError("--reason must contain at least one non-blank character")

    # Inject `## Follow-up Source` between `## Theme` and `## Exit Criteria`.
    sprint_md_text = new_sprint_md.read_text(encoding="utf-8")
    source_sprint_relative = source_sprint_dir.relative_to(project_dir).as_posix()
    followup_block = (
        "\n## Follow-up Source\n"
        f"- Source sprint: [`{source_sprint_dir.name}`]({source_sprint_relative})\n"
        f"- Reason: {one_line_reason}\n"
    )
    sprint_md_text = sprint_md_text.replace(
        "\n## Exit Criteria\n",
        f"{followup_block}\n## Exit Criteria\n",
        1,
    )
    new_sprint_md.write_text(sprint_md_text, encoding="utf-8")

    # Append (or create) followups.md on the source sprint.
    followups_md = source_sprint_dir / "followups.md"
    if not followups_md.exists():
        followups_md.write_text(
            render_template(
                "followups.md.tmpl",
                sprint_name=source_sprint_dir.name,
            ),
            encoding="utf-8",
        )
    timestamp = utc_iso8601_z()
    bullet = f"- {new_sprint_name} \u2014 {one_line_reason} ({timestamp})\n"
    with followups_md.open("a", encoding="utf-8") as handle:
        handle.write(bullet)

    print(new_sprint_md)
    print(f"Wrote follow-up entry to {followups_md}")

    # Update the decree checkpoint so a follow-up sprint is observable from
    # `workflowctl status`. We do not infer flow here — the user will reset
    # it via the next decree (Phase 2).
    existing_checkpoint = load_decree_checkpoint(project_dir) or {}
    write_decree_checkpoint(
        project_dir=project_dir,
        project_slug=project_slug,
        summary=stringify(existing_checkpoint.get("summary", ""))
        or f"Followup sprint {new_sprint_name} created from {source_sprint_dir.name}",
        phase="phase-3-planning",
        next_step=(
            f"plan tasks for {new_sprint_name} via `workflowctl init-sprint-plan` "
            f"or `workflowctl init-task --sprint {new_sprint_name} ...`"
        ),
        flow=stringify(existing_checkpoint.get("flow", "")),
        sprint=new_sprint_name,
    )


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


def handle_doctor(args: argparse.Namespace) -> None:
    _workspace_root, project_dir, project_slug = resolve_project_context(
        args.project_slug,
        project_dir_value=args.project_dir,
        root_value=args.root,
    )
    report = run_diagnostics(project_dir, project_slug)
    if getattr(args, "json_output", False):
        print(format_report_json(report))
    elif getattr(args, "summary_output", False):
        print(format_report_summary(report))
    else:
        print(format_report_text(report))
    sys.exit(report.exit_code())


def handle_finalize(args: argparse.Namespace) -> None:
    """Convenience wrapper: check + advance to ready_to_merge + advance to done.

    Each step runs full validation. If any step fails, the command stops
    with the task unchanged (or at the last successful status).
    """

    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        raise WorkflowError(f"task_dir must not be a symlink: {input_task_dir}")
    task_dir = input_task_dir.resolve()

    validate_task_dir(task_dir)
    task_paths = derive_task_paths(task_dir)
    task_data, _body = load_task_document(task_paths.task_md)
    current_status = stringify(task_data["status"])

    # Already done — idempotent exit.
    if current_status == "done":
        print(f"Task already done: {task_dir}")
        return

    sprint_md = task_paths.sprint_dir / "sprint.md"

    # Determine which transitions to apply.
    transitions = []
    if current_status != "ready_to_merge":
        transitions.append("ready_to_merge")
    transitions.append("done")

    for target_status in transitions:
        task_data_now, body_now = load_task_document(task_paths.task_md)
        original_content = task_paths.task_md.read_text(encoding="utf-8")
        original_sprint_content = sprint_md.read_text(encoding="utf-8")
        updated_task = apply_status_transition(task_data_now, target_status)
        try:
            write_task_document(task_paths.task_md, updated_task, body_now)
            validate_task_dir(task_dir)
            update_sprint_overview(sprint_md)
        except Exception:
            task_paths.task_md.write_text(original_content, encoding="utf-8")
            sprint_md.write_text(original_sprint_content, encoding="utf-8")
            raise

    print(f"Finalized {task_dir} -> done")


def handle_verify(args: argparse.Namespace) -> None:
    """Run a wrapped command, append structured evidence, auto-log ledger.

    MVP (sprint-013 TASK-002). See ADR-004. Scope excludes .raw/ size tiering,
    head/tail flags, and same-second disambiguation — those are sprint-014.

    Exit semantics:
      - 0 when evidence was appended (including when the wrapped command failed).
      - non-zero only for verify_error paths (bad task_dir, invalid profile,
        write failure). verify_error is atomic: no evidence, no ledger line.
    """

    import shutil
    import subprocess as _subprocess
    import time

    # --- Argument validation (verify_error path; must be atomic) ---
    input_task_dir = Path(args.task_dir).expanduser()
    if input_task_dir.is_symlink():
        _verify_fail("task_dir must not be a symlink", args, task_dir=input_task_dir)
        return
    task_dir = input_task_dir.resolve()
    try:
        validate_task_dir(task_dir)
    except WorkflowError as error:
        _verify_fail(f"invalid task_dir: {error}", args, task_dir=task_dir)
        return

    profile = args.profile.strip()
    if profile not in EXECUTION_PROFILE_DIRS:
        allowed = ", ".join(sorted(EXECUTION_PROFILE_DIRS))
        _verify_fail(
            f"invalid --profile {profile!r}; expected one of: {allowed}",
            args,
            task_dir=task_dir,
        )
        return

    section = args.evidence_section.strip()
    if not section:
        _verify_fail("--evidence-section must not be empty", args, task_dir=task_dir)
        return

    shell = args.shell
    if shutil.which(shell) is None and not Path(shell).is_file():
        _verify_fail(f"shell not found: {shell}", args, task_dir=task_dir)
        return

    cwd = Path(args.cwd).expanduser().resolve() if args.cwd else task_dir
    if not cwd.is_dir():
        _verify_fail(f"--cwd is not a directory: {cwd}", args, task_dir=task_dir)
        return

    profile_dir_name = EXECUTION_PROFILE_DIRS[profile]
    profile_dir = task_dir / "verification" / profile_dir_name
    # From here on we perform real writes. Any exception must propagate as
    # verify_error BUT after evidence write begins there is no atomicity
    # guarantee; the argument-validation block above is where atomicity matters.
    profile_dir.mkdir(parents=True, exist_ok=True)
    evidence_md = profile_dir / "evidence.md"
    ledger_path = task_dir / "agent-runs.jsonl"

    # --- Run the command ---
    started_at_iso = _verify_iso8601_now()
    t0 = time.monotonic()
    try:
        completed = _subprocess.run(
            [shell, "-c", args.command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=args.timeout,
        )
        timed_out = False
        command_exit = completed.returncode
        output_text = (completed.stdout or "") + (completed.stderr or "")
    except _subprocess.TimeoutExpired as error:
        timed_out = True
        command_exit = 124
        output_text = (
            (error.stdout.decode("utf-8", errors="replace") if isinstance(error.stdout, bytes) else (error.stdout or ""))
            + (error.stderr.decode("utf-8", errors="replace") if isinstance(error.stderr, bytes) else (error.stderr or ""))
            + f"\n[workflowctl verify] command exceeded --timeout {args.timeout}s"
        )
    duration_ms = int((time.monotonic() - t0) * 1000)

    # --- Build the evidence block ---
    run_iso = started_at_iso
    status_trailer = (
        f"exit: {command_exit}\n"
        f"run: {run_iso}\n"
        f"duration_ms: {duration_ms}\n"
    )
    fenced_block = (
        "```shell\n"
        f"$ {args.command}\n"
        f"{output_text.rstrip()}\n"
        "```\n"
        f"{status_trailer}"
    )

    pre_evidence_text = evidence_md.read_text(encoding="utf-8") if evidence_md.is_file() else ""
    pre_evidence_len = len(pre_evidence_text)

    section_header = f"## {section}"
    if section_header in pre_evidence_text.splitlines():
        # Append as a `### run` sub-heading at EOF under the existing section.
        appendage = (
            ("" if pre_evidence_text.endswith("\n") else "\n")
            + f"\n### run {run_iso}\n\n"
            + fenced_block
        )
        new_evidence_text = pre_evidence_text + appendage
    else:
        # Fresh section. If evidence.md already exists with free-form content,
        # append the new section at EOF; preserve prior content verbatim.
        appendage = (
            ("" if pre_evidence_text.endswith("\n") or pre_evidence_text == "" else "\n")
            + (f"\n{section_header}\n\n" if pre_evidence_text else f"{section_header}\n\n")
            + fenced_block
        )
        new_evidence_text = pre_evidence_text + appendage

    evidence_md.write_text(new_evidence_text, encoding="utf-8")
    substantive_chars_appended = len(new_evidence_text) - pre_evidence_len

    # --- Decide summary status ---
    if timed_out:
        summary_status = "command_failed"
        ledger_status = "command_failed"
    elif command_exit != 0:
        summary_status = "command_failed"
        ledger_status = "command_failed"
    else:
        # ok vs ok_under_threshold (substantive char preview; non-blocking).
        summary_status = "ok" if substantive_chars_appended >= 40 else "ok_under_threshold"
        ledger_status = "command_ok"

    # --- Append ledger line ---
    ledger_line = {
        "timestamp": run_iso,
        "agent": "workflowctl-verify",
        "purpose": f"evidence capture: {section}",
        "input_artifact": args.command,
        "output_artifact": f"verification/{profile_dir_name}/evidence.md#{section}",
        "status": ledger_status,
        "notes": (
            f"exit={command_exit} duration_ms={duration_ms} "
            f"substantive_delta={substantive_chars_appended}"
        ),
    }
    pre_ledger_text = ledger_path.read_text(encoding="utf-8") if ledger_path.is_file() else ""
    if pre_ledger_text and not pre_ledger_text.endswith("\n"):
        pre_ledger_text += "\n"
    new_ledger_text = pre_ledger_text + json.dumps(ledger_line, ensure_ascii=False) + "\n"
    ledger_path.write_text(new_ledger_text, encoding="utf-8")

    # --- Emit JSON summary ---
    summary = {
        "status": summary_status,
        "exit": command_exit,
        "duration_ms": duration_ms,
        "substantive_chars_appended": substantive_chars_appended,
        "section": section,
        "evidence_path": str(evidence_md),
    }
    print(json.dumps(summary, ensure_ascii=False))


def _verify_iso8601_now() -> str:
    """Return UTC ISO8601 with Z suffix (second precision)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _verify_fail(message: str, args: argparse.Namespace, *, task_dir: Path) -> None:
    """Emit a verify_error JSON summary and exit non-zero WITHOUT side-effects."""
    summary = {
        "status": "verify_error",
        "exit": None,
        "duration_ms": 0,
        "substantive_chars_appended": 0,
        "section": getattr(args, "evidence_section", "") or "",
        "evidence_path": None,
        "error": message,
    }
    print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
    raise WorkflowError(f"verify_error: {message}")


# --- Shared helpers ---


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
        key = manifest_key(project_dir, absolute_path)
        template_hash = sha256_text(rendered)
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
        on_disk_hash = sha256_text(on_disk)

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


if __name__ == "__main__":
    raise SystemExit(main())
