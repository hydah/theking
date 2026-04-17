"""Runtime scaffold, projection, and upgrade-manifest helpers.

Extracted from ``workflowctl`` so that the CLI entry module stays focused on
argument parsing + handlers. Nothing here is CLI-aware; ``handle_upgrade`` and
``handle_ensure`` import from this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .constants import (
        AGENT_DEFINITIONS,
        CLAUDE_TO_KIMI_TOOL_MAP,
        COMMAND_DEFINITIONS,
        EXECUTION_PROFILE_DIRS,
        HOOK_FILES,
        KIMI_AGENTS_SUBDIR,
        KIMI_DIRNAME,
        KIMI_MAIN_AGENT_FILENAME,
        KIMI_SUBAGENT_ROLES,
        RUNTIME_ENTRY_FILES,
        SKILL_DEFINITIONS,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from .validation import (
        append_theking_reference,
        ensure_local_path,
        ensure_tree_has_no_symlinks,
        ensure_within_directory,
        get_theking_dir,
        humanize_slug,
        read_template_raw,
        render_template,
        write_if_missing,
    )
except ImportError:
    from constants import (
        AGENT_DEFINITIONS,
        CLAUDE_TO_KIMI_TOOL_MAP,
        COMMAND_DEFINITIONS,
        EXECUTION_PROFILE_DIRS,
        HOOK_FILES,
        KIMI_AGENTS_SUBDIR,
        KIMI_DIRNAME,
        KIMI_MAIN_AGENT_FILENAME,
        KIMI_SUBAGENT_ROLES,
        RUNTIME_ENTRY_FILES,
        SKILL_DEFINITIONS,
        THEKING_DIRNAME,
        WorkflowError,
    )
    from validation import (
        append_theking_reference,
        ensure_local_path,
        ensure_tree_has_no_symlinks,
        ensure_within_directory,
        get_theking_dir,
        humanize_slug,
        read_template_raw,
        render_template,
        write_if_missing,
    )


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


@dataclass(frozen=True)
class RuntimeProjection:
    """One target directory under .claude/.codebuddy/.github to mirror from .theking."""

    exposure_dir: Path
    source_dir: Path
    legacy_source_dir: Path
    prefer_symlink: bool = True
    overwrite_existing: bool = True
    manifest_path: Path | None = None
    content_transform: Callable[[str, str], str] | None = None


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


# --- Kimi CLI agent generation ------------------------------------------
#
# Kimi uses YAML agent files (``kimi --agent-file``), not Claude's md-with-
# frontmatter format. Rather than maintain a parallel set of YAML templates
# per role, we derive each ``.kimi/agents/<role>.yaml`` from the canonical
# ``.theking/agents/<role>.md`` at projection time — so there is exactly one
# source of truth for each role's system prompt.
#
# The main agent ``.kimi/agent.yaml`` simply ``extend:``-s Kimi's built-in
# ``default`` agent (inheriting its tool policy) and lists every subagent. Each
# subagent extends the main agent and points ``system_prompt_path`` back at the
# canonical md file.

_FRONTMATTER_TOOLS_PATTERN = re.compile(r"^tools\s*:\s*(.*)$")
_FRONTMATTER_DESCRIPTION_PATTERN = re.compile(r"^description\s*:\s*(.*)$")


def extract_claude_tools_from_md(md_text: str) -> list[str]:
    """Extract Claude-style comma-separated tool list from an agent md file.

    Returns an empty list if no ``tools:`` field is present or the frontmatter
    is malformed. Only handles the simple inline-list form (``tools: Read, Grep``)
    that theking's canonical templates use; block-scalar forms are ignored.
    """
    if not md_text.startswith("---\n"):
        return []
    end_marker = md_text.find("\n---\n", 4)
    if end_marker == -1:
        return []
    header = md_text[4:end_marker]
    for line in header.splitlines():
        match = _FRONTMATTER_TOOLS_PATTERN.match(line)
        if not match:
            continue
        raw_value = match.group(1).strip()
        if not raw_value or raw_value.startswith(("|", ">", "[")):
            # Skip block scalars and flow sequences — canonical templates do
            # not use them, and trying to parse them without a real YAML
            # parser risks silently mapping the wrong tools.
            return []
        return [token.strip() for token in raw_value.split(",") if token.strip()]
    return []


def extract_claude_description_from_md(md_text: str) -> str:
    """Extract the ``description`` field from an agent md frontmatter.

    Handles inline strings (optionally surrounded by matching single or double
    quotes). Returns an empty string when the field is absent, when it uses a
    block scalar (``|``, ``>``), or when the frontmatter is malformed — we
    prefer dropping the description to emitting a YAML that might corrupt
    Kimi's parser downstream.
    """
    if not md_text.startswith("---\n"):
        return ""
    end_marker = md_text.find("\n---\n", 4)
    if end_marker == -1:
        return ""
    header = md_text[4:end_marker]
    for line in header.splitlines():
        match = _FRONTMATTER_DESCRIPTION_PATTERN.match(line)
        if not match:
            continue
        raw_value = match.group(1).strip()
        if raw_value.startswith(("|", ">")):
            return ""
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in ('"', "'"):
            raw_value = raw_value[1:-1]
        return raw_value
    return ""


def _escape_yaml_double_quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def map_claude_tools_to_kimi(claude_tools: list[str]) -> list[str]:
    """Translate Claude tool names to Kimi ``module:ClassName`` identifiers.

    Unknown tool names are dropped silently so that a subagent keeps working
    even if Claude introduces a new tool we have not mapped yet — the subagent
    falls back to the tool policy inherited via ``extend:``.
    """
    mapped: list[str] = []
    seen: set[str] = set()
    for token in claude_tools:
        kimi_tool = CLAUDE_TO_KIMI_TOOL_MAP.get(token)
        if kimi_tool is None or kimi_tool in seen:
            continue
        seen.add(kimi_tool)
        mapped.append(kimi_tool)
    return mapped


def build_kimi_subagent_yaml(*, role: str, canonical_md_text: str) -> str:
    """Render a single Kimi subagent YAML for a canonical ``.theking/agents``
    md file.

    ``system_prompt_path`` is expressed relative to the subagent YAML's own
    location (``.kimi/agents/<role>.yaml``), so it resolves to
    ``<project>/.theking/agents/<role>.md`` without hard-coded absolute paths.
    """
    description = extract_claude_description_from_md(canonical_md_text)
    claude_tools = extract_claude_tools_from_md(canonical_md_text)
    kimi_tools = map_claude_tools_to_kimi(claude_tools)

    lines: list[str] = [
        f"# Kimi subagent for role `{role}` — generated from .theking/agents/{role}.md",
        "#",
        "# Edit the canonical md instead of this file; `workflowctl ensure` only",
        "# creates this file when it does not already exist.",
        "",
        "version: 1",
        "agent:",
        "  extend: ../agent.yaml",
        f"  name: {role}",
        f"  system_prompt_path: ../../.theking/agents/{role}.md",
    ]
    if description:
        lines.append(f'  description: "{_escape_yaml_double_quoted(description)}"')
    if kimi_tools:
        lines.append("  tools:")
        lines.extend(f"    - {tool}" for tool in kimi_tools)
    return "\n".join(lines) + "\n"


def build_kimi_main_agent_yaml(*, project_slug: str, roles: tuple[str, ...]) -> str:
    """Render the Kimi main agent YAML that ties subagents together.

    The returned text is filled through the ``main_agent.yaml.tmpl`` template
    so doc/comment edits can stay in the template without code changes.
    """
    main_agent_name = f"{project_slug}-main"
    subagents_block_lines: list[str] = []
    for role in roles:
        subagents_block_lines.append(f"    {role}:")
        subagents_block_lines.append(f"      path: ./agents/{role}.yaml")
        subagents_block_lines.append(
            f'      description: "theking {role} subagent for {project_slug}"'
        )
    subagents_block = "\n".join(subagents_block_lines)
    return render_template(
        "main_agent.yaml.tmpl",
        project_slug=project_slug,
        main_agent_name=main_agent_name,
        subagents_block=subagents_block,
    )


def ensure_kimi_runtime(project_dir: Path, project_slug: str, agents_dir: Path) -> None:
    """Materialize the Kimi CLI runtime surface under ``.kimi/``.

    This is additive: an existing ``.kimi/agent.yaml`` or ``.kimi/agents/*.yaml``
    is left alone so user customizations survive re-runs. Skills and AGENTS.md
    are exposed as symlinks so they always track the canonical sources.
    """
    kimi_dir = project_dir / KIMI_DIRNAME
    ensure_local_path(kimi_dir, project_dir, KIMI_DIRNAME)
    kimi_dir.mkdir(parents=True, exist_ok=True)

    kimi_agents_dir = kimi_dir / KIMI_AGENTS_SUBDIR
    ensure_local_path(kimi_agents_dir, project_dir, f"{KIMI_DIRNAME}/{KIMI_AGENTS_SUBDIR}")
    if kimi_agents_dir.is_symlink():
        raise WorkflowError(
            f"{kimi_agents_dir.relative_to(project_dir).as_posix()} must not be a symlink"
        )
    kimi_agents_dir.mkdir(parents=True, exist_ok=True)

    main_agent_path = kimi_dir / KIMI_MAIN_AGENT_FILENAME
    ensure_local_path(
        main_agent_path, project_dir, f"{KIMI_DIRNAME}/{KIMI_MAIN_AGENT_FILENAME}"
    )
    write_if_missing(
        main_agent_path,
        build_kimi_main_agent_yaml(project_slug=project_slug, roles=KIMI_SUBAGENT_ROLES),
    )

    for role in KIMI_SUBAGENT_ROLES:
        canonical_md = agents_dir / f"{role}.md"
        if not canonical_md.is_file():
            # Canonical agent wasn't generated (should never happen in normal
            # flow, but be defensive instead of producing a YAML that points
            # at a missing prompt file).
            continue
        subagent_path = kimi_agents_dir / f"{role}.yaml"
        ensure_local_path(
            subagent_path,
            project_dir,
            f"{KIMI_DIRNAME}/{KIMI_AGENTS_SUBDIR}/{role}.yaml",
        )
        write_if_missing(
            subagent_path,
            build_kimi_subagent_yaml(
                role=role,
                canonical_md_text=canonical_md.read_text(encoding="utf-8"),
            ),
        )

    # .kimi/AGENTS.md → symlink to project-root AGENTS.md so both locations
    # Kimi merges resolve to the same file. We can't use ``ensure_local_path``
    # here because it rejects the symlink we are intentionally installing;
    # instead we validate the *target* stays inside the project via
    # ``ensure_within_directory``.
    root_agents_md = project_dir / "AGENTS.md"
    kimi_agents_md = kimi_dir / "AGENTS.md"

    if kimi_agents_md.is_symlink():
        existing_target = kimi_agents_md.resolve(strict=False)
        ensure_within_directory(
            existing_target, project_dir.resolve(), f"{KIMI_DIRNAME}/AGENTS.md"
        )
    elif kimi_agents_md.exists():
        if not kimi_agents_md.is_file():
            raise WorkflowError(
                f"{KIMI_DIRNAME}/AGENTS.md must be a file or symlink, got {kimi_agents_md}"
            )
    elif root_agents_md.is_file():
        try:
            relative_target = os.path.relpath(root_agents_md, kimi_agents_md.parent)
            kimi_agents_md.symlink_to(relative_target)
        except OSError:
            # Filesystems without symlink support fall back to a materialized
            # copy. Kimi will still consume it; only the "both paths resolve
            # to the same inode" invariant is relaxed.
            kimi_agents_md.write_text(
                root_agents_md.read_text(encoding="utf-8"), encoding="utf-8"
            )


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


def sha256_text(text: str) -> str:
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


def manifest_key(project_dir: Path, absolute_path: Path) -> str:
    return absolute_path.relative_to(project_dir).as_posix()


def sync_runtime_manifest_baseline(project_dir: Path, project_slug: str) -> None:
    """Populate manifest entries for files whose on-disk content equals the
    current template output. Leaves drifted files untouched (they will be
    reported during upgrade)."""
    artifacts = collect_managed_runtime_artifacts(project_dir, project_slug)
    manifest = load_runtime_manifest(project_dir)
    changed = False
    for absolute_path, rendered in artifacts:
        key = manifest_key(project_dir, absolute_path)
        if not absolute_path.exists():
            if key in manifest:
                del manifest[key]
                changed = True
            continue
        try:
            on_disk = absolute_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        on_disk_hash = sha256_text(on_disk)
        template_hash = sha256_text(rendered)
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

    theking_anchor = ".theking/bootstrap.md"
    for entry_filename, template_name in RUNTIME_ENTRY_FILES:
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

    for agent_filename, template_name in AGENT_DEFINITIONS:
        agent_content = render_template(template_name, project_slug=project_slug)
        write_if_missing(
            agents_dir / agent_filename,
            agent_content,
            legacy_path=legacy_runtime_agents_dir / agent_filename,
        )

    for hook_filename, template_name in HOOK_FILES:
        hook_content = read_template_raw(template_name)
        write_if_missing(
            hooks_dir / hook_filename,
            hook_content,
            legacy_path=legacy_runtime_hooks_dir / hook_filename,
        )

    # --- Skill definitions ---
    for skill_name, template_name in SKILL_DEFINITIONS:
        skill_content = render_template(template_name, **tmpl_vars)
        canonical_skill_dir = skills_dir / skill_name
        canonical_skill_dir.mkdir(parents=True, exist_ok=True)
        write_if_missing(
            canonical_skill_dir / "SKILL.md",
            skill_content,
            legacy_path=legacy_runtime_skills_dir / skill_name / "SKILL.md",
        )

    # --- Command definitions ---
    for cmd_filename, template_name in COMMAND_DEFINITIONS:
        cmd_content = render_template(template_name, **tmpl_vars)
        write_if_missing(
            commands_dir / cmd_filename,
            cmd_content,
            legacy_path=legacy_runtime_commands_dir / cmd_filename,
        )

    for cmd_filename, template_name in COMMAND_DEFINITIONS:
        prompt_name = cmd_filename.replace(".md", ".prompt.md")
        prompt_content = render_template(template_name, **tmpl_vars)
        write_if_missing(
            prompts_dir / prompt_name,
            prompt_content,
            legacy_path=legacy_runtime_prompts_dir / prompt_name,
        )

    runtime_projections = [
        RuntimeProjection(
            exposure_dir=project_dir / ".claude" / "agents",
            source_dir=agents_dir,
            legacy_source_dir=legacy_runtime_agents_dir,
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".claude" / "commands",
            source_dir=commands_dir,
            legacy_source_dir=legacy_runtime_commands_dir,
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".claude" / "skills",
            source_dir=skills_dir,
            legacy_source_dir=legacy_runtime_skills_dir,
        ),
        # .codebuddy/agents forces a materialized copy so the transform can run.
        RuntimeProjection(
            exposure_dir=project_dir / ".codebuddy" / "agents",
            source_dir=agents_dir,
            legacy_source_dir=legacy_runtime_agents_dir,
            prefer_symlink=False,
            content_transform=rewrite_agent_frontmatter_for_codebuddy,
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".codebuddy" / "commands",
            source_dir=commands_dir,
            legacy_source_dir=legacy_runtime_commands_dir,
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".codebuddy" / "skills",
            source_dir=skills_dir,
            legacy_source_dir=legacy_runtime_skills_dir,
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".github" / "skills",
            source_dir=skills_dir,
            legacy_source_dir=legacy_runtime_skills_dir,
            prefer_symlink=False,
            manifest_path=manifest_dir / "github-skills.json",
        ),
        RuntimeProjection(
            exposure_dir=project_dir / ".github" / "prompts",
            source_dir=prompts_dir,
            legacy_source_dir=legacy_runtime_prompts_dir,
            prefer_symlink=False,
            manifest_path=manifest_dir / "github-prompts.json",
        ),
        # Kimi CLI reads project-level skills from `.kimi/skills/` (same
        # SKILL.md format as Claude / CodeBuddy). Keep it as a symlink so
        # skill edits flow through `.theking/skills/` only.
        RuntimeProjection(
            exposure_dir=project_dir / KIMI_DIRNAME / "skills",
            source_dir=skills_dir,
            legacy_source_dir=legacy_runtime_skills_dir,
        ),
    ]
    for projection in runtime_projections:
        materialize_runtime_projection(
            source_dir=projection.source_dir,
            exposure_dir=projection.exposure_dir,
            project_dir=project_dir,
            legacy_source_dir=projection.legacy_source_dir,
            prefer_symlink=projection.prefer_symlink,
            overwrite_existing=projection.overwrite_existing,
            manifest_path=projection.manifest_path,
            content_transform=projection.content_transform,
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

    # Kimi CLI runtime (agent.yaml + subagents + AGENTS.md). Must run *after*
    # the canonical agents are written and the root AGENTS.md entry file has
    # been created, so subagent YAMLs point at real md files and the
    # `.kimi/AGENTS.md` symlink has a valid target.
    ensure_kimi_runtime(project_dir, project_slug, agents_dir)

    sync_runtime_manifest_baseline(project_dir, project_slug)


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
