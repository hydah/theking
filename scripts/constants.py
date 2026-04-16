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
    "planned": {"red"},
    "red": {"green"},
    "green": {"in_review"},
    "in_review": {"changes_requested", "ready_to_merge"},
    "changes_requested": {"red", "in_review"},
    "ready_to_merge": {"done"},
    "blocked": set(),
    "done": set(),
}

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
