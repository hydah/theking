"""Sprint planning helpers: plan-file parsing, task file rendering, and
sprint overview maintenance.

Separated from :mod:`workflowctl` so the plan parser can be unit tested
without the full CLI wiring.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from .constants import TASK_ID_PATTERN, WorkflowError
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
    from constants import TASK_ID_PATTERN, WorkflowError
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


def require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise WorkflowError(f"{label} must be a string")
    return value


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


def update_sprint_overview(sprint_md_path: Path) -> None:
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
