"""workflowctl doctor — repo-level read-only health check.

Four finding categories:
  D1 — zombie task (unfinished + Goal section placeholder/empty)
  D2 — stale decree checkpoint (references a sprint where all tasks are done
       or the sprint is sealed)
  D3 — missing projection directory (runtime exposure partially torn)
  D4 — broken review pair on done/ready_to_merge task (runs validate_task_dir)

Severity levels:
  error   — correctness violation; exit 1
  warning — attention needed; exit 0
  info    — noteworthy but harmless; exit 0

The module is deliberately READ-ONLY. No auto-repair. No side effects beyond
stdout.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from .constants import WorkflowError
    from .sessions import (
        get_decree_checkpoint_path,  # noqa: F401  (re-export for future callers)
        load_decree_checkpoint,
    )
    from .sprint_plan import sprint_is_sealed
    from .validation import (
        get_theking_dir,
        get_workflow_project_dir,
        load_task_document,
        stringify,
        validate_task_dir,
    )
except ImportError:  # pragma: no cover - dual-import fallback
    from constants import WorkflowError  # type: ignore[no-redef]
    from sessions import (  # type: ignore[no-redef]
        get_decree_checkpoint_path,  # noqa: F401
        load_decree_checkpoint,
    )
    from sprint_plan import sprint_is_sealed  # type: ignore[no-redef]
    from validation import (  # type: ignore[no-redef]
        get_theking_dir,
        get_workflow_project_dir,
        load_task_document,
        stringify,
        validate_task_dir,
    )


# Runtime projections we check for presence. Keys are top-level dirs that
# indicate "user opted into this runtime"; values are required subdirs that
# must exist once the top-level is present.
#
# Note: this is a SUPERSET of what spec.md §Scope D3 originally enumerated
# (agents + github/skills + github/prompts). `workflowctl ensure` provisions
# commands and skills under every interactive runtime too, so doctor checks
# them all. If a subdir under here is missing on a repo whose top-level
# runtime dir exists, that's a real projection tear — worth a warning.
PROJECTION_SUBDIRS: dict[str, tuple[str, ...]] = {
    ".claude": ("agents", "commands", "skills"),
    ".codebuddy": ("agents", "commands", "skills"),
    ".kimi": ("agents", "skills"),
    ".github": ("skills", "prompts"),
}


def _goal_body_is_placeholder(body: str) -> bool:
    """Return True if the Goal body consists only of HTML comments / blank
    lines / whitespace — i.e. nothing a human has actually written.

    This is the structural test. The literal template-phrase marker below is
    kept as a belt-and-braces redundancy so that if someone writes real prose
    that happens to contain the phrase verbatim, we still classify correctly.
    """
    stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    return not stripped


# Legacy phrase-match fallback for the Goal placeholder. Template prose drift
# would silently neuter this, which is why `_goal_body_is_placeholder` is the
# primary gate and this marker is only a secondary tripwire.
_GOAL_PLACEHOLDER_MARKER = "Describe the expected OUTCOME"


@dataclass
class Finding:
    level: str  # one of: error, warning, info
    category: str  # D1|D2|D3|D4
    message: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass
class DoctorReport:
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    info: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        if finding.level == "error":
            self.errors.append(finding)
        elif finding.level == "warning":
            self.warnings.append(finding)
        elif finding.level == "info":
            self.info.append(finding)
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown finding level: {finding.level}")

    def summary(self) -> dict[str, int]:
        return {
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "info": len(self.info),
        }

    def exit_code(self) -> int:
        return 1 if self.errors else 0


# ---------- D1: zombie task ----------

UNFINISHED_STATUSES = {
    "draft",
    "planned",
    "red",
    "green",
    "in_review",
    "changes_requested",
    "blocked",
}


def _iter_task_dirs(project_dir: Path, project_slug: str):
    workflow_root = get_workflow_project_dir(project_dir, project_slug)
    sprints_dir = workflow_root / "sprints"
    if not sprints_dir.is_dir():
        return
    for sprint_dir in sorted(sprints_dir.iterdir(), key=lambda p: p.name):
        if sprint_dir.is_symlink() or not sprint_dir.is_dir():
            continue
        tasks_dir = sprint_dir / "tasks"
        if not tasks_dir.is_dir():
            continue
        for task_dir in sorted(tasks_dir.iterdir(), key=lambda p: p.name):
            if task_dir.is_symlink() or not task_dir.is_dir():
                continue
            yield sprint_dir, task_dir


def _goal_is_placeholder_or_empty(task_md_text: str) -> bool:
    """Return True if the Goal section is missing, empty, or still carries the
    template placeholder comment.

    Primary gate: body is structurally empty once HTML comments / whitespace
    are stripped (see `_goal_body_is_placeholder`). Template-phrase matching
    is kept as a redundant tripwire to avoid coupling zombie detection to
    one exact wording of the comment scaffold.
    """
    lines = task_md_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Goal")
    except StopIteration:
        return True
    # Collect body until the next `## ` header.
    body_lines: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body_lines.append(line)
    body = "\n".join(body_lines)
    if _goal_body_is_placeholder(body):
        return True
    # Redundant phrase tripwire — belt-and-braces.
    return _GOAL_PLACEHOLDER_MARKER in body


def check_zombie_tasks(project_dir: Path, project_slug: str, report: DoctorReport) -> None:
    for _sprint_dir, task_dir in _iter_task_dirs(project_dir, project_slug):
        task_md = task_dir / "task.md"
        if not task_md.is_file():
            continue
        try:
            task_data, body = load_task_document(task_md)
        except WorkflowError as error:
            report.add(
                Finding(
                    level="error",
                    category="D1",
                    message=f"{task_dir.name}: task.md failed to parse ({error})",
                    hint="Fix frontmatter and re-run doctor.",
                )
            )
            continue
        status = stringify(task_data.get("status", "")).strip()
        if status not in UNFINISHED_STATUSES:
            continue  # done / sealed / terminal — not a zombie by definition
        if not _goal_is_placeholder_or_empty(body):
            continue
        task_id = stringify(task_data.get("id", task_dir.name))
        report.add(
            Finding(
                level="warning",
                category="D1",
                message=(
                    f"{task_id}: zombie task — status={status}, Goal section "
                    "is still placeholder/empty"
                ),
                hint=(
                    "Fill in the Goal section and advance the task, or "
                    "explicitly mark it blocked with a reason."
                ),
            )
        )


# ---------- D2: stale decree checkpoint ----------


def check_stale_checkpoint(
    project_dir: Path, project_slug: str, report: DoctorReport
) -> None:
    try:
        checkpoint = load_decree_checkpoint(project_dir)
    except WorkflowError:
        return
    if checkpoint is None:
        return
    sprint_value = stringify(checkpoint.get("sprint", "")).strip()
    if not sprint_value:
        return  # checkpoint without a sprint reference is legitimate pre-planning state
    sprint_dir = (
        get_workflow_project_dir(project_dir, project_slug) / "sprints" / sprint_value
    )
    if not sprint_dir.is_dir():
        report.add(
            Finding(
                level="info",
                category="D2",
                message=(
                    f"Stale decree checkpoint references non-existent sprint "
                    f"'{sprint_value}'"
                ),
                hint=(
                    "Delete .theking/state/session/decree-session.md or overwrite "
                    "it via `workflowctl checkpoint` for the current effort."
                ),
            )
        )
        return

    # Check sprint.md for sealed status + all tasks done.
    # Use the canonical `sprint_is_sealed` helper (ADR-002 single source of
    # truth for seal detection) rather than raw substring matching, which
    # would false-positive on docs/code-blocks containing `status: sealed`.
    sprint_md = sprint_dir / "sprint.md"
    sealed = sprint_md.is_file() and sprint_is_sealed(sprint_md)

    tasks_dir = sprint_dir / "tasks"
    # Note: `all_done` initialises True so that an EMPTY sprint (init-sprint
    # ran, no tasks yet) is not classified as stale-but-done. The `has_any_task`
    # guard below is the load-bearing condition — we require at least one task
    # to declare "fully done".
    all_done = True
    has_any_task = False
    if tasks_dir.is_dir():
        for task_dir in tasks_dir.iterdir():
            if task_dir.is_symlink() or not task_dir.is_dir():
                continue
            task_md = task_dir / "task.md"
            if not task_md.is_file():
                continue
            has_any_task = True
            try:
                task_data, _body = load_task_document(task_md)
            except WorkflowError:
                all_done = False
                continue
            status = stringify(task_data.get("status", "")).strip()
            if status != "done":
                all_done = False
                break

    if sealed or (has_any_task and all_done):
        report.add(
            Finding(
                level="info",
                category="D2",
                message=(
                    f"Stale decree checkpoint — sprint '{sprint_value}' is "
                    f"{'sealed' if sealed else 'fully done'}"
                ),
                hint=(
                    "The checkpoint is harmless but misleading on resume; "
                    "overwrite via `workflowctl checkpoint` for the next "
                    "effort or remove decree-session.md."
                ),
            )
        )


# ---------- D3: missing projection directory ----------


def check_projection_dirs(project_dir: Path, report: DoctorReport) -> None:
    for top_name, subdirs in PROJECTION_SUBDIRS.items():
        top = project_dir / top_name
        if not top.is_dir():
            # User hasn't enabled this runtime (or torn it down intentionally).
            # Whole-runtime opt-out is legitimate; skip without noise.
            continue
        for sub in subdirs:
            sub_path = top / sub
            if not sub_path.is_dir():
                report.add(
                    Finding(
                        level="warning",
                        category="D3",
                        message=(
                            f"Projection directory missing: {top_name}/{sub}"
                        ),
                        hint=(
                            "Run `workflowctl upgrade --project-dir . "
                            "--project-slug <slug> --force` to rebuild, or "
                            f"remove the whole {top_name}/ tree if this "
                            "runtime is no longer used."
                        ),
                    )
                )


# ---------- D4: broken review pair on done/ready_to_merge ----------


# Substrings that indicate a D4 finding is about audit-chain integrity
# (review pair / resolution / verification evidence). Everything else (spec
# section counts, acceptance traceability) is historical-doc drift and should
# NOT block exit code for already-done tasks.
_D4_AUDIT_CHAIN_MARKERS: tuple[str, ...] = (
    "Missing review",
    "Missing resolved review",
    "missing finding id",
    "coverage issues",
    "review pair",
    "verification evidence",
    "substantive evidence",
    "sprint-smoke",
)


def _d4_is_audit_chain(error_message: str) -> bool:
    lower = error_message.lower()
    return any(marker.lower() in lower for marker in _D4_AUDIT_CHAIN_MARKERS)


def check_done_task_integrity(
    project_dir: Path, project_slug: str, report: DoctorReport
) -> None:
    for _sprint_dir, task_dir in _iter_task_dirs(project_dir, project_slug):
        task_md = task_dir / "task.md"
        if not task_md.is_file():
            continue
        try:
            task_data, _body = load_task_document(task_md)
        except WorkflowError:
            continue  # D1 already surfaced parse errors
        status = stringify(task_data.get("status", "")).strip()
        if status not in {"done", "ready_to_merge"}:
            continue
        try:
            validate_task_dir(task_dir)
        except WorkflowError as error:
            task_id = stringify(task_data.get("id", task_dir.name))
            message = f"{task_id}: {error}"
            # Audit-chain violations (missing review pair / resolution coverage
            # / verification evidence) stay as error — they break the trail.
            # Spec doc drift (section counts, acceptance traceability) on
            # already-done tasks is warning: the task isn't flowing anymore,
            # so it's a historical housekeeping issue, not a live correctness
            # problem. Bumping every legacy sprint to error would make doctor
            # perpetually red on mature repos, defeating its signal value.
            level = "error" if _d4_is_audit_chain(str(error)) else "warning"
            report.add(
                Finding(
                    level=level,
                    category="D4",
                    message=message,
                    hint=(
                        "Fix review pair / verification evidence or roll the "
                        "task status back to in_review via advance-status."
                        if level == "error"
                        else (
                            "Historical spec drift (doc-level). Safe to leave "
                            "as-is; backfill the missing fields if you want "
                            "`workflowctl check` green on this legacy task."
                        )
                    ),
                )
            )


# ---------- Orchestrator ----------


def run_diagnostics(project_dir: Path, project_slug: str) -> DoctorReport:
    theking_dir = get_theking_dir(project_dir)
    if not theking_dir.is_dir():
        raise WorkflowError(
            f".theking directory not found at {theking_dir}; "
            "run `workflowctl ensure` first"
        )
    report = DoctorReport()
    check_zombie_tasks(project_dir, project_slug, report)
    check_stale_checkpoint(project_dir, project_slug, report)
    check_projection_dirs(project_dir, report)
    check_done_task_integrity(project_dir, project_slug, report)
    return report


def format_report_text(report: DoctorReport) -> str:
    lines: list[str] = []
    for bucket_name, bucket in (
        ("errors", report.errors),
        ("warnings", report.warnings),
        ("info", report.info),
    ):
        if not bucket:
            continue
        lines.append(f"## {bucket_name.upper()} ({len(bucket)})")
        for finding in bucket:
            lines.append(f"[{finding.level}] [{finding.category}] {finding.message}")
            if finding.hint:
                lines.append(f"    -> {finding.hint}")
        lines.append("")
    summary = report.summary()
    lines.append(
        f"Summary: {summary['errors']} errors, {summary['warnings']} warnings, "
        f"{summary['info']} info"
    )
    return "\n".join(lines)


def format_report_json(report: DoctorReport) -> str:
    payload: dict[str, Any] = {
        "errors": [f.to_dict() for f in report.errors],
        "warnings": [f.to_dict() for f in report.warnings],
        "info": [f.to_dict() for f in report.info],
        "summary": report.summary(),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
