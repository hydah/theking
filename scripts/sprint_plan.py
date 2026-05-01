"""Sprint planning helpers: plan-file parsing, task file rendering, and
sprint overview maintenance.

Separated from :mod:`workflowctl` so the plan parser can be unit tested
without the full CLI wiring.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .constants import MAX_BUNDLE_SIZE, TASK_ID_PATTERN, WorkflowError
    from .validation import (
        check_dag,
        default_test_plan,
        next_index,
        parse_frontmatter,
        render_template,
        serialize_frontmatter_string,
        slugify,
        stringify,
    )
except ImportError:
    from constants import MAX_BUNDLE_SIZE, TASK_ID_PATTERN, WorkflowError
    from validation import (
        check_dag,
        default_test_plan,
        next_index,
        parse_frontmatter,
        render_template,
        serialize_frontmatter_string,
        slugify,
        stringify,
    )


# --- Sprint-level frontmatter (ADR-002 sealed sprints) -------------------
#
# sprint.md gains an OPTIONAL leading YAML frontmatter block whose only
# recognised keys are ``status`` and ``sealed_at``. Anything else raises so
# we never silently drop drift. When the block is absent (sprint-001 /
# sprint-002 fixtures and every freshly minted sprint), helpers below still
# work — they simply return an empty dict and treat the whole file as body.

ALLOWED_SPRINT_FRONTMATTER_KEYS = frozenset({"status", "sealed_at"})
ALLOWED_SPRINT_STATUSES = frozenset({"sealed"})


def split_sprint_md(text: str) -> tuple[dict[str, str], str]:
    """Split sprint.md into (frontmatter_dict, body).

    Returns ({}, text) when the file does not start with a ``---`` block.
    Raises ``WorkflowError`` when the leading block is malformed (unclosed,
    unknown key, or invalid status value).
    """

    if not text.startswith("---\n"):
        return {}, text

    end_marker = text.find("\n---\n", 4)
    if end_marker == -1:
        raise WorkflowError("sprint.md frontmatter is not closed")

    header_text = text[4:end_marker]
    body = text[end_marker + len("\n---\n") :]

    frontmatter: dict[str, str] = {}
    for raw_line in header_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+)$", line)
        if not match:
            raise WorkflowError(f"Invalid sprint.md frontmatter line: {raw_line!r}")
        key, raw_value = match.groups()
        if key not in ALLOWED_SPRINT_FRONTMATTER_KEYS:
            raise WorkflowError(
                f"Unknown sprint.md frontmatter key: {key!r}. "
                f"Allowed keys: {sorted(ALLOWED_SPRINT_FRONTMATTER_KEYS)}"
            )
        value = raw_value.strip()
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            value = value[1:-1]
        frontmatter[key] = value

    status = frontmatter.get("status")
    if status is not None and status not in ALLOWED_SPRINT_STATUSES:
        raise WorkflowError(
            f"Unknown sprint.md status: {status!r}. "
            f"Allowed values: {sorted(ALLOWED_SPRINT_STATUSES)}"
        )

    return frontmatter, body


def render_sprint_md(frontmatter: dict[str, str], body: str) -> str:
    """Render sprint.md from a frontmatter dict + raw body.

    Skips the frontmatter block entirely when the dict is empty so legacy
    sprint.md files (no header) round-trip byte-for-byte.
    """

    if not frontmatter:
        return body

    lines = ["---"]
    # Stable ordering: status first, then sealed_at, then any remaining
    # allowed keys alphabetically. Today the allow-list has only those two
    # keys, but defensive ordering future-proofs the format.
    for key in ("status", "sealed_at"):
        if key in frontmatter:
            lines.append(f"{key}: {frontmatter[key]}")
    for key in sorted(frontmatter):
        if key in ("status", "sealed_at"):
            continue
        lines.append(f"{key}: {frontmatter[key]}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def read_sprint_frontmatter(sprint_md_path: Path) -> dict[str, str]:
    return split_sprint_md(sprint_md_path.read_text(encoding="utf-8"))[0]


def sprint_is_sealed(sprint_md_path: Path) -> bool:
    if not sprint_md_path.is_file():
        return False
    return read_sprint_frontmatter(sprint_md_path).get("status") == "sealed"


def reject_sealed_sprint_for_writes(sprint_dir: Path) -> None:
    """Raise WorkflowError if ``sprint_dir/sprint.md`` is sealed.

    Called from init-task / init-sprint-plan BEFORE any filesystem mutation
    so a sealed sprint is truly immutable.
    """

    sprint_md = sprint_dir / "sprint.md"
    if not sprint_is_sealed(sprint_md):
        return
    raise WorkflowError(
        f"sprint {sprint_dir.name} is sealed; "
        f"use workflowctl followup-sprint --source-sprint {sprint_dir} "
        "--new-theme <slug> instead of writing into it."
    )


def utc_iso8601_z() -> str:
    """Return the current UTC time in ``YYYY-MM-DDTHH:MM:SSZ`` form.

    The CI-friendly seam: tests stub this via monkeypatch when they need a
    deterministic timestamp.
    """

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise WorkflowError(f"{label} must be a string")
    return value


def extract_spec_hints(entry: dict[str, Any], task_id: str) -> dict[str, list[str]]:
    """Extract optional spec seed fields from a plan entry.

    Recognised top-level keys: scope, non_goals, acceptance, edge_cases.
    Recognised nested spec_hints keys: code_patterns, test_helpers, related_tasks.
    Each must be a list of strings. Returns an empty dict if no hints are supplied.
    """

    def extract_list(raw: Any, key: str) -> list[str]:
        if not isinstance(raw, list):
            raise WorkflowError(
                f"Task {task_id} field '{key}' must be a list of strings when provided"
            )
        items: list[str] = []
        for index, item in enumerate(raw):
            if not isinstance(item, str):
                raise WorkflowError(
                    f"Task {task_id} field '{key}' item {index} must be a string"
                )
            text = item.strip()
            if not text:
                continue
            if "\n" in text or "\r" in text:
                raise WorkflowError(
                    f"Task {task_id} field '{key}' item {index} must be a single line"
                )
            items.append(text)
        return items

    hints: dict[str, list[str]] = {}
    for key in ("scope", "non_goals", "acceptance", "edge_cases"):
        if key not in entry:
            continue
        items = extract_list(entry[key], key)
        if items:
            hints[key] = items

    if "spec_hints" in entry:
        nested = entry["spec_hints"]
        if not isinstance(nested, dict):
            raise WorkflowError(
                f"Task {task_id} field 'spec_hints' must be an object when provided"
            )
        for key in ("code_patterns", "test_helpers", "related_tasks"):
            if key not in nested:
                continue
            items = extract_list(nested[key], f"spec_hints.{key}")
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


def parse_bundles(
    bundle_entries: list[Any],
    slug_to_task_id: dict[str, str],
    deps_by_slug: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """Parse and validate bundle entries from plan.json.

    Returns ``{bundle_slug: {"slug": ..., "task_slugs": [...], "task_ids": [...], "justification": ...}}``.
    Aggregates all errors and raises a single ``WorkflowError`` listing them all.
    """

    errors: list[str] = []
    seen_slugs: set[str] = set()
    task_to_bundle: dict[str, str] = {}  # task_slug -> bundle_slug (overlap check)
    result: dict[str, dict[str, Any]] = {}

    for index, entry in enumerate(bundle_entries):
        label = f"Bundle entry {index}"

        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue

        # --- Required fields ---
        for field in ("slug", "tasks", "justification"):
            if field not in entry:
                errors.append(f"{label} is missing required field: {field}")
        if any(f not in entry for f in ("slug", "tasks", "justification")):
            continue  # skip further validation if structure is broken

        # --- slug ---
        raw_slug = entry["slug"]
        if not isinstance(raw_slug, str) or not raw_slug.strip():
            errors.append(f"{label} slug must be a non-empty string")
            continue
        bundle_slug = slugify(raw_slug)
        if bundle_slug in seen_slugs:
            errors.append(f"[{bundle_slug}] duplicate bundle slug")
            continue
        seen_slugs.add(bundle_slug)
        label = f"[{bundle_slug}]"

        # --- justification ---
        justification = entry["justification"]
        if not isinstance(justification, str) or not justification.strip():
            errors.append(f"{label} justification must be a non-empty string")

        # --- tasks list ---
        task_refs = entry["tasks"]
        if not isinstance(task_refs, list):
            errors.append(f"{label} tasks must be a list")
            continue
        if len(task_refs) < 2:
            errors.append(
                f"{label} bundle must contain at least 2 tasks (got {len(task_refs)})"
            )
            continue
        if len(task_refs) > MAX_BUNDLE_SIZE:
            errors.append(
                f"{label} bundle must contain at most {MAX_BUNDLE_SIZE} tasks "
                f"(got {len(task_refs)})"
            )
            continue

        # --- resolve task refs ---
        resolved_slugs: list[str] = []
        resolved_ids: list[str] = []
        for ref in task_refs:
            if not isinstance(ref, str):
                errors.append(f"{label} task reference must be a string")
                continue
            ref_slug = slugify(ref)
            if ref_slug not in slug_to_task_id:
                errors.append(f"{label} bundle task {ref_slug!r} not found in plan tasks")
                continue
            if ref_slug in task_to_bundle:
                errors.append(
                    f"{label} task {ref_slug!r} is already in bundle "
                    f"{task_to_bundle[ref_slug]!r}"
                )
                continue
            task_to_bundle[ref_slug] = bundle_slug
            resolved_slugs.append(ref_slug)
            resolved_ids.append(slug_to_task_id[ref_slug])

        if len(resolved_slugs) < 2:
            continue  # already reported individual errors

        # --- depends_on relationship check ---
        has_dependency = False
        for slug_a in resolved_slugs:
            task_id_a = slug_to_task_id[slug_a]
            for slug_b in resolved_slugs:
                if slug_a == slug_b:
                    continue
                # Check if slug_b depends on slug_a (i.e. task_id_a in deps of slug_b)
                if task_id_a in deps_by_slug.get(slug_b, []):
                    has_dependency = True
                    break
            if has_dependency:
                break
        if not has_dependency:
            errors.append(
                f"{label} bundle tasks must have at least one depends_on "
                "relationship between them (proves coupling)"
            )
            continue

        result[bundle_slug] = {
            "slug": bundle_slug,
            "task_slugs": resolved_slugs,
            "task_ids": resolved_ids,
            "justification": stringify(justification).strip(),
        }

    if errors:
        header = f"Plan file has {len(errors)} invalid bundle(s):"
        bullets = "\n  - ".join(errors)
        raise WorkflowError(f"{header}\n  - {bullets}")

    return result


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
    bundle: str | None = None,
    review_mode: str = "light",
) -> None:
    """Write task.md, spec.md, and optional audit/context artifacts."""
    depends_on_block = (
        "\n".join(f"  - {dep}" for dep in depends_on)
        if depends_on
        else ""
    )
    bundle_block = f"bundle: {bundle}\n" if bundle else ""
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
            bundle_block=bundle_block,
            review_mode=review_mode,
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

    handoff_md = task_dir / "handoff.md"
    handoff_md.write_text(render_template("handoff.md.tmpl"), encoding="utf-8")

    agent_runs = task_dir / "agent-runs.jsonl"
    agent_runs.write_text("", encoding="utf-8")


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
        """Render the Acceptance checklist with mandatory traceability
        sub-bullets (ADR-003 闸 2). Each hint item becomes a checkbox +
        two child bullets (验证方式 / 证据路径) filled with placeholder
        comments that `workflowctl check` will later require the author
        to replace with real values before advancing past `red`."""

        items = [item.strip() for item in hints.get(key, []) if str(item).strip()]
        subbullet_vm = (
            "  - 验证方式: "
            "<!-- unit | integration | smoke | e2e | manual-observed -->"
        )
        subbullet_ep = (
            "  - 证据路径: "
            "<!-- verification/<profile>/smoke.md or tests/test_x.py::test_y -->"
        )
        if not items:
            return "\n".join(
                [
                    f"- [ ] <!-- {fallback_comment} -->",
                    subbullet_vm,
                    subbullet_ep,
                ]
            )
        rendered: list[str] = []
        for item in items:
            rendered.append(f"- [ ] {item}")
            rendered.append(subbullet_vm)
            rendered.append(subbullet_ep)
        return "\n".join(rendered)

    def implementation_hints() -> str:
        sections: list[str] = []
        labels = {
            "code_patterns": "Code Patterns",
            "test_helpers": "Test Helpers",
            "related_tasks": "Related Tasks",
        }
        for key, label in labels.items():
            items = [item.strip() for item in hints.get(key, []) if str(item).strip()]
            if not items:
                continue
            sections.append(f"### {label}\n" + "\n".join(f"- {item}" for item in items))
        if not sections:
            return ""
        return "\n\n## Implementation Hints\n" + "\n\n".join(sections) + "\n"

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
        f"{implementation_hints()}"
    )


def update_sprint_overview(sprint_md_path: Path) -> None:
    rows: list[str] = []
    rows.append("| Task | Type | Profile | Depends On | Bundle | Status |")
    rows.append("|------|------|---------|-----------|--------|--------|")
    tasks_dir = sprint_md_path.parent / "tasks"
    for entry in collect_task_overview_entries(tasks_dir):
        rows.append(
            f"| {entry['task_id']} | {entry['task_type']} | {entry['execution_profile']} "
            f"| {entry['depends_on']} | {entry['bundle']} | {entry['status']} |"
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
                "bundle": stringify(task_data.get("bundle", "")) or "\u2014",
                "status": stringify(task_data["status"]),
            }
        )
    return entries
