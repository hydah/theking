from __future__ import annotations

import re

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
    "planned": {"red", "green"},  # mechanical flow: planned -> green (skip red)
    "red": {"green"},
    "green": {"in_review"},
    "in_review": {"changes_requested", "ready_to_merge"},
    "changes_requested": {"red", "in_review"},
    "ready_to_merge": {"done"},
    "blocked": set(),
    "done": set(),
}

TERMINAL_STATUSES = {"done", "blocked"}

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


# --- Scaffold manifest (ensure_theking_scaffold source data) ---
# Each tuple is (output filename, template name). Keeping these as data lets
# callers add / remove scaffold artifacts without editing the scaffold function.

RUNTIME_ENTRY_FILES: tuple[tuple[str, str], ...] = (
    ("CLAUDE.md", "claude_md.tmpl"),
    ("CODEBUDDY.md", "codebuddy_md.tmpl"),
    ("AGENTS.md", "agents_md.tmpl"),
)

AGENT_DEFINITIONS: tuple[tuple[str, str], ...] = (
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
)

HOOK_FILES: tuple[tuple[str, str], ...] = (
    ("check-spec-exists.js", "hook_check_spec.js.tmpl"),
    ("check-task-status.js", "hook_check_status.js.tmpl"),
    ("remind-review.js", "hook_remind_review.js.tmpl"),
)

SKILL_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("workflow-governance", "skill_workflow_governance.md.tmpl"),
    ("knowledge-base", "skill_knowledge_base.md.tmpl"),
)

COMMAND_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("decree.md", "cmd_decree.md.tmpl"),
    ("analyze-project.md", "cmd_analyze_project.md.tmpl"),
)


# --- Kimi CLI projection configuration ------------------------------------
# Kimi Code CLI (moonshotai) consumes:
#   * .kimi/skills/ — project-level skills (same SKILL.md format as Claude),
#     discovered automatically.
#   * .kimi/AGENTS.md — auto-merged into ${KIMI_AGENTS_MD} alongside the
#     project-root AGENTS.md.
#   * .kimi/agent.yaml + .kimi/agents/*.yaml — native YAML agent definitions;
#     load with `kimi --agent-file .kimi/agent.yaml`.
#
# We do NOT project hooks (Kimi has no equivalent lifecycle hooks) or commands
# (Kimi has no project-level slash command directory; the `workflow-governance`
# skill carries the equivalent guidance).

KIMI_DIRNAME = ".kimi"
KIMI_MAIN_AGENT_FILENAME = "agent.yaml"
KIMI_AGENTS_SUBDIR = "agents"

# Subset of Kimi's built-in tool list we care about when mirroring Claude agents.
# Keys are the short names used in Claude's `tools:` frontmatter; values are the
# `module:ClassName` identifiers Kimi expects. Unknown tool names are silently
# dropped from the generated YAML — subagents fall back to `extend:`-inherited
# tool policy, so the resulting agent stays usable even if Claude introduces a
# new tool we haven't mapped yet.
CLAUDE_TO_KIMI_TOOL_MAP: dict[str, str] = {
    "Read": "kimi_cli.tools.file:ReadFile",
    "ReadFile": "kimi_cli.tools.file:ReadFile",
    "Write": "kimi_cli.tools.file:WriteFile",
    "WriteFile": "kimi_cli.tools.file:WriteFile",
    "Edit": "kimi_cli.tools.file:StrReplaceFile",
    "StrReplace": "kimi_cli.tools.file:StrReplaceFile",
    "StrReplaceFile": "kimi_cli.tools.file:StrReplaceFile",
    "MultiEdit": "kimi_cli.tools.file:StrReplaceFile",
    "Glob": "kimi_cli.tools.file:Glob",
    "Grep": "kimi_cli.tools.file:Grep",
    "Bash": "kimi_cli.tools.shell:Shell",
    "Shell": "kimi_cli.tools.shell:Shell",
    "WebFetch": "kimi_cli.tools.web:FetchURL",
    "FetchURL": "kimi_cli.tools.web:FetchURL",
    "WebSearch": "kimi_cli.tools.web:SearchWeb",
    "SearchWeb": "kimi_cli.tools.web:SearchWeb",
}

# Roles that map 1:1 from .theking/agents/*.md to .kimi/agents/<role>.yaml.
# Order follows theking's canonical agent catalog (planner first, workhorse
# reviewers next, supporting specialists last) so the generated main agent
# lists subagents in a predictable sequence.
KIMI_SUBAGENT_ROLES: tuple[str, ...] = (
    "planner",
    "tdd-guide",
    "code-reviewer",
    "security-reviewer",
    "e2e-runner",
    "architect",
    "build-error-resolver",
    "doc-updater",
    "refactor-cleaner",
    "perf-optimizer",
)
