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
        ALLOWED_REVIEW_MODES,
        ALLOWED_STATUSES,
        ALLOWED_TASK_TYPE_TOKENS,
        ALLOWED_TRANSITIONS,
        DEFAULT_REVIEW_MODE,
        EXECUTION_PROFILE_ALIASES,
        EXECUTION_PROFILE_DIRS,
        MAX_BUNDLE_SIZE,
        SPRINT_NAME_PATTERN,
        TASK_ID_PATTERN,
        THEKING_DIRNAME,
        WorkflowError,
    )
except ImportError:
    from constants import (
        ALLOWED_EXECUTION_PROFILES,
        ALLOWED_REVIEW_MODES,
        ALLOWED_STATUSES,
        ALLOWED_TASK_TYPE_TOKENS,
        ALLOWED_TRANSITIONS,
        DEFAULT_REVIEW_MODE,
        EXECUTION_PROFILE_ALIASES,
        EXECUTION_PROFILE_DIRS,
        MAX_BUNDLE_SIZE,
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


# --- task.md Goal gate (sprint-015 TASK-001) --------------------------------
#
# Why a gate here rather than only in doctor: doctor's zombie-task detection
# (D1) catches empty Goal only *after* a task has already advanced. sprint-014
# demonstrated the hole — two tasks reached `done` with placeholder Goals
# because nothing rejected them at draft exit. The canonical check lives here
# in validation.py so both `workflowctl check` and `advance-status` enforce
# it. doctor.py imports the helpers to avoid drift between the two gates.

_GOAL_PLACEHOLDER_MARKER = "Describe the expected OUTCOME"


def goal_body_is_placeholder(body: str) -> bool:
    """Return True if the Goal body is structurally empty — only HTML comments,
    blank lines, or whitespace. A human has written nothing."""
    stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip()
    return not stripped


def goal_is_placeholder_or_empty(task_md_text: str) -> bool:
    """Return True if the `## Goal` section is missing, empty, or still the
    template placeholder. Structural test is primary; phrase-match is a
    belt-and-braces fallback against template drift."""
    lines = task_md_text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Goal")
    except StopIteration:
        return True
    body_lines: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        body_lines.append(line)
    body = "\n".join(body_lines)
    if goal_body_is_placeholder(body):
        return True
    return _GOAL_PLACEHOLDER_MARKER in body


def validate_task_goal(task_md: Path) -> None:
    """Fail if task.md `## Goal` is missing, empty, or still a template
    placeholder. Called on every `check` / `advance-status` so tasks cannot
    leave draft with a no-op Goal."""
    text = task_md.read_text(encoding="utf-8")
    if goal_is_placeholder_or_empty(text):
        raise WorkflowError(
            f"task.md `## Goal` section must describe the expected outcome. "
            f"Fill it in before running check/advance-status. File: {task_md}"
        )


def validate_task_dir(task_dir: Path, *, check_goal: bool = False) -> None:
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

    if check_goal:
        # Opt-in. `advance-status` turns this on when leaving draft so the
        # Goal gate fires exactly where it should (at promotion time, not
        # during inspection-only `check`/`activate` calls on fresh drafts).
        validate_task_goal(task_paths.task_md)

    task_data = parse_frontmatter(task_paths.task_md.read_text(encoding="utf-8"))
    validated = validate_task_metadata(task_data)
    if stringify(validated["id"]) != task_paths.task_dir.name:
        raise WorkflowError("task id must match the task directory name")
    validate_verification_layout(task_paths.verification_dir, validated)
    validate_spec(
        task_paths.spec_md,
        require_content=spec_requires_content(validated["status_history"]),
        flow=normalize_task_flow(task_data.get("flow")),
    )
    validate_review_requirements(task_paths.review_dir, validated)
    validate_agent_runs_ledger(task_paths.task_dir / "agent-runs.jsonl")


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
    legacy_expected_agents = ["planner", *expected_agents]

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
    actual_agents = tuple(stringify(agent) for agent in task_data["required_agents"])
    if actual_agents not in {tuple(expected_agents), tuple(legacy_expected_agents)}:
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

    # Optional bundle field — validate slug format if present
    bundle_value = task_data.get("bundle")
    if bundle_value is not None:
        bundle_str = stringify(bundle_value).strip()
        if bundle_str and slugify(bundle_str) != bundle_str:
            raise WorkflowError(
                f"bundle must be a valid slug (got {bundle_str!r}); "
                "use lowercase alphanumeric with hyphens"
            )
    review_mode = resolve_review_mode(
        task_data.get("review_mode"),
        task_type,
        execution_profile,
    )

    return {
        **task_data,
        "id": task_id,
        "task_type": task_type,
        "execution_profile": execution_profile,
        "review_mode": review_mode,
    }


SPEC_SECTION_COUNT_THRESHOLDS_FULL: dict[str, int] = {
    "Test Plan": 5,
    "Edge Cases": 3,
}
SPEC_SECTION_COUNT_THRESHOLDS_LIGHT: dict[str, int] = {
    "Test Plan": 3,
    "Edge Cases": 1,
}
SPEC_SECTION_COUNT_THRESHOLDS_MECHANICAL: dict[str, int] = {
    # mechanical flow: no Test Plan / Edge Cases minimum required
}
ALLOWED_TASK_FLOWS = {"full", "lightweight", "mechanical"}


def normalize_task_flow(value: Any) -> str:
    """Normalize the task.md 'flow' frontmatter field. Missing -> 'full'."""
    if value is None:
        return "full"
    text = stringify(value).strip().lower()
    if text == "":
        return "full"
    if text not in ALLOWED_TASK_FLOWS:
        raise WorkflowError(
            f"Unknown task flow: {text!r}. Allowed values: "
            f"{sorted(ALLOWED_TASK_FLOWS)}"
        )
    return text


def count_spec_section_items(section_body: str) -> int:
    """Count top-level list items under a spec section.

    Rules:
    - Strip HTML comments first (they are placeholders, not content).
    - Only lines with zero leading whitespace count.
    - Unordered bullets: lines starting with `-`, `*`, or `+` followed by space.
    - Ordered items: lines starting with `<digits>.` or `<digits>)` followed by
      space.  AI runtimes (Cursor, Codex, CodeBuddy) commonly generate numbered
      lists; these are valid Markdown list items and must be accepted.
    - Checkbox bullets (`- [ ]` or `- [x]`) count as one item.
    - Indented (nested) bullets are not new items.
    """
    stripped = re.sub(r"<!--.*?-->", "", section_body, flags=re.DOTALL)
    count = 0
    for raw_line in stripped.splitlines():
        # Unordered: - item / * item / + item
        # Ordered:   1. item / 2) item
        if re.match(r"^(?:[-*+]|\d+[.)]) \s*\S", raw_line):
            count += 1
    return count


def validate_spec_section_counts(spec_md: Path, *, flow: str) -> None:
    """Enforce per-flow minimum item counts on content-carrying spec sections.

    Legacy spec structure (only Acceptance + Test Plan) is preserved as a
    bypass to match `validate_spec`'s backward-compat contract.
    """
    flow = normalize_task_flow(flow)
    spec_text = spec_md.read_text(encoding="utf-8")
    sections = collect_spec_sections(spec_text)
    if is_legacy_spec_structure(sections):
        return

    thresholds = (
        SPEC_SECTION_COUNT_THRESHOLDS_FULL
        if flow == "full"
        else SPEC_SECTION_COUNT_THRESHOLDS_MECHANICAL
        if flow == "mechanical"
        else SPEC_SECTION_COUNT_THRESHOLDS_LIGHT
    )
    for heading, minimum in thresholds.items():
        section_body = sections.get(heading, "")
        observed = count_spec_section_items(section_body)
        if observed < minimum:
            raise WorkflowError(
                f"spec.md '{heading}' has {observed} item(s); "
                f"{flow} flow requires >= {minimum}. "
                "Either add more items, or switch this task to lightweight "
                "flow by setting `flow: lightweight` in task.md frontmatter."
            )


def validate_spec(
    spec_md: Path,
    *,
    require_content: bool,
    flow: str | None = None,
) -> None:
    spec_text = spec_md.read_text(encoding="utf-8")
    sections = collect_spec_sections(spec_text)
    if not require_content and is_legacy_spec_structure(sections):
        return

    effective_flow = normalize_task_flow(flow) if flow else "full"

    # mechanical flow: only Scope + Acceptance required; others optional
    required_sections: tuple[str, ...]
    if effective_flow == "mechanical":
        required_sections = ("Scope", "Acceptance")
    else:
        required_sections = ("Scope", "Non-Goals", "Acceptance", "Test Plan", "Edge Cases")

    for heading in required_sections:
        section_body = sections.get(heading)
        if section_body is None:
            raise WorkflowError(f"spec.md is missing required section: {heading}")
        if require_content and not spec_section_has_content(section_body):
            raise WorkflowError(f"spec.md section must not be empty: {heading}")

    if require_content:
        validate_spec_section_counts(spec_md, flow=flow or "full")
        validate_acceptance_traceability(spec_md)


# --- Acceptance traceability gate (ADR-003 / sprint-004 TASK-002) -----------
#
# Every `- [ ] <criterion>` under ## Acceptance must declare, via two
# indented child bullets, which verification method proves it and where
# the evidence lives. This closes the "unit tests fake the acceptance"
# 偷懒路径 exposed by voiceagent4 — spec authors can no longer hide the
# fact that their "end-to-end acceptance" is actually satisfied by a
# mocked unit test.

ALLOWED_VERIFICATION_METHODS: frozenset[str] = frozenset(
    {"unit", "integration", "smoke", "e2e", "manual-observed"}
)

# Regex pieces kept at module scope so tests can introspect / future
# extensions can reuse them.
#
# Intentionally narrow: spec.md.tmpl and render_spec_markdown both emit
# `-` bullets exclusively. Accepting `*` / `+` would create drift vectors
# (user hand-edits a spec with `*` and silently bypasses the gate) with
# no upside. Extend here only when parsing external specs becomes a goal.
_ACCEPTANCE_CHECKBOX_RE = re.compile(r"^-\s+\[[ xX]\]\s+(?P<text>.+?)\s*$")
_VERIFICATION_METHOD_SUBBULLET_RE = re.compile(
    r"^\s+-\s+验证方式\s*[:：]\s*(?P<value>.*?)\s*$"
)
_EVIDENCE_PATH_SUBBULLET_RE = re.compile(
    r"^\s+-\s+证据路径\s*[:：]\s*(?P<value>.*?)\s*$"
)
# Matches any top-level (column-0) bullet — used to close the current
# checkbox's sub-bullet scope when a sibling bullet appears without
# a checkbox marker.
_TOP_LEVEL_BULLET_RE = re.compile(r"^-\s+")


def _iter_acceptance_checkboxes(acceptance_body: str) -> list[dict[str, Any]]:
    """Walk the Acceptance section body and return one dict per top-level
    `- [ ]` checkbox, collecting the verification-method and evidence-path
    sub-bullets that appear between it and the next scope-closing event.

    Scope closes on any of:

    - a new top-level checkbox (the match captures the next one)
    - a new top-level `- ` bullet without a checkbox marker
    - a non-indented, non-empty line that is NOT a sub-bullet —
      paragraphs, headings, blockquotes, etc. Matches the visual Markdown
      semantics: a paragraph at column 0 breaks the list.

    This is stricter than "only close on top-level bullets" — MEDIUM-1 in
    round-001 review pointed out that the looser rule would silently
    attach a subsequent checkbox's sub-bullets to the previous one
    whenever a paragraph was inserted between them.
    """

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in acceptance_body.splitlines():
        checkbox = _ACCEPTANCE_CHECKBOX_RE.match(raw_line)
        if checkbox is not None:
            if current is not None:
                entries.append(current)
            current = {
                "text": checkbox.group("text").strip(),
                "verification_method": None,
                "verification_method_raw": None,
                "evidence_path": None,
                "line": raw_line,
            }
            continue

        if current is None:
            # Content before the first checkbox — ignored (could be a
            # leading comment or plain bullet).
            continue

        # Sub-bullet matches take precedence (they are indented, so they
        # can never collide with the top-level-close branch below).
        vm = _VERIFICATION_METHOD_SUBBULLET_RE.match(raw_line)
        if vm is not None:
            raw_value = vm.group("value")
            normalized = raw_value.strip().lower()
            current["verification_method_raw"] = raw_value
            current["verification_method"] = normalized
            continue

        ep = _EVIDENCE_PATH_SUBBULLET_RE.match(raw_line)
        if ep is not None:
            current["evidence_path"] = ep.group("value").strip()
            continue

        # A top-level `- ` bullet (not a checkbox — the checkbox regex
        # would have claimed it). Close current scope without starting
        # a new one.
        if _TOP_LEVEL_BULLET_RE.match(raw_line) is not None:
            entries.append(current)
            current = None
            continue

        # Any other non-indented, non-empty line (paragraph text,
        # heading, blockquote, etc.) also closes the scope so
        # subsequent indented sub-bullets do not get misattributed.
        if raw_line and not raw_line.startswith((" ", "\t")):
            entries.append(current)
            current = None
            continue

        # Blank line or indented-but-not-a-sub-bullet line: keep scope
        # open. (This preserves the Edge Case "nested content between
        # checkbox and its sub-bullets is tolerated" for things like
        # intentional indented blockquotes.)

    if current is not None:
        entries.append(current)
    return entries


def validate_acceptance_traceability(spec_md: Path) -> None:
    """Require every ``- [ ] <criterion>`` in ## Acceptance to be followed
    by:

    - ``  - 验证方式: <method>`` — method must be in
      :data:`ALLOWED_VERIFICATION_METHODS` (case-insensitive, trimmed).
    - ``  - 证据路径: <path or test id>`` — must be non-empty after strip;
      file existence is NOT checked (evidence may arrive post-red).

    The gate runs only on new-format specs (five-section); legacy
    two-section specs bypass via ``is_legacy_spec_structure`` just like
    ``validate_spec_section_counts``. An empty Acceptance section (zero
    checkboxes) also passes — per-checkbox contract, nothing to enforce.

    Error messages are deterministic (first missing piece reported first)
    so implementers always fix one thing at a time.
    """

    spec_text = spec_md.read_text(encoding="utf-8")
    sections = collect_spec_sections(spec_text)
    if is_legacy_spec_structure(sections):
        return
    acceptance_body = sections.get("Acceptance")
    if acceptance_body is None:
        # `validate_spec` already enforces Acceptance presence; this is
        # defensive — if called standalone, silently pass (nothing to
        # trace) rather than raise a second redundant error.
        return

    for entry in _iter_acceptance_checkboxes(acceptance_body):
        text = entry["text"]
        label = text if len(text) <= 60 else text[:57] + "..."

        if entry["verification_method_raw"] is None:
            raise WorkflowError(
                f"spec.md Acceptance checkbox missing 验证方式 sub-bullet: {label!r}. "
                "Add `  - 验证方式: <unit | integration | smoke | e2e | manual-observed>` "
                "on the line below the checkbox."
            )

        if entry["verification_method"] == "":
            raise WorkflowError(
                f"spec.md Acceptance checkbox has empty 验证方式 value: {label!r}. "
                "Provide one of: "
                f"{', '.join(sorted(ALLOWED_VERIFICATION_METHODS))}."
            )

        if entry["verification_method"] not in ALLOWED_VERIFICATION_METHODS:
            raise WorkflowError(
                "spec.md Acceptance checkbox has unknown 验证方式 "
                f"{entry['verification_method_raw']!r} on: {label!r}. "
                "Allowed values: "
                f"{', '.join(sorted(ALLOWED_VERIFICATION_METHODS))}."
            )

        if entry["evidence_path"] is None:
            raise WorkflowError(
                f"spec.md Acceptance checkbox missing 证据路径 sub-bullet: {label!r}. "
                "Add `  - 证据路径: <path or test id>` on the line below the checkbox."
            )

        if entry["evidence_path"] == "":
            raise WorkflowError(
                f"spec.md Acceptance checkbox has empty 证据路径 value: {label!r}. "
                "Provide a path under verification/ or a test identifier "
                "(e.g. tests/test_x.py::test_y)."
            )


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


# --- Substantive-evidence gate (ADR-003 / sprint-004 TASK-001) --------------
#
# Prior gate only checked size > 0, so "待补" / "TODO" / "<!-- pending -->"
# all passed as "evidence". This gate strips HTML comments, bullet markers,
# and a small blacklist of placeholder tokens, then requires the remaining
# substantive character count to meet a minimum across the whole profile dir.

# Matched case-insensitively as whole words. Keep the list small and boring:
# anything an honest engineer would also want to retype before shipping.
PLACEHOLDER_TOKENS: frozenset[str] = frozenset(
    {
        "todo",
        "tbd",
        "pending",
        "placeholder",
        "fill me in",
        "待补",
    }
)

# Minimum substantive character count across a profile's evidence files.
# 40 ≈ one meaningful line ("ran X, observed Y, exit 0"). Below that,
# reviewers cannot tell what was actually checked.
SUBSTANTIVE_EVIDENCE_MIN_CHARS = 40


_PLACEHOLDER_TOKEN_PATTERN = re.compile(
    # Sort for deterministic regex construction (frozenset iteration order
    # is unspecified in CPython, which would make `.pattern` debug output
    # flap between processes).
    r"(?i)\b("
    + "|".join(re.escape(token) for token in sorted(PLACEHOLDER_TOKENS))
    + r")\b"
)


def substantive_text_length(text: str) -> int:
    """Return the non-whitespace char count after stripping HTML comments,
    bullet/checkbox markers, and placeholder tokens.

    Mirrors the comment-stripping pattern from ``spec_section_has_content``
    so both gates agree on what "real content" looks like.
    """

    # 1. Drop HTML comments first — they are scaffolding, not evidence.
    stripped = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # 2. Drop placeholder tokens anywhere they appear. Whole-word match so
    #    "todolist" is not accidentally gutted.
    stripped = _PLACEHOLDER_TOKEN_PATTERN.sub("", stripped)
    # 3. Drop leading bullet / checkbox markers on each line, matching the
    #    exact pattern used by spec_section_has_content.
    cleaned_lines: list[str] = []
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*+]\s*", "", line)
        line = re.sub(r"^\[[ xX]\]\s*", "", line)
        cleaned_lines.append(line)
    # 4. Count non-whitespace characters in the remainder. Unicode chars
    #    (CJK, punctuation, etc.) each count as 1 — we're measuring signal,
    #    not bytes.
    remainder = "".join(cleaned_lines)
    return sum(1 for ch in remainder if not ch.isspace())


def has_substantive_verification_evidence(profile_dir: Path) -> bool:
    """Return True iff the combined substantive text across every readable
    UTF-8 file under ``profile_dir`` meets ``SUBSTANTIVE_EVIDENCE_MIN_CHARS``.

    Directory-level aggregation is intentional: a task may split evidence
    across smoke.md + stdout.txt + screenshot.md, each individually short.

    Non-UTF-8 / binary artefacts (PNG, PDF, trace dumps) are ALLOWED to
    live under the profile dir — they often are real evidence — but they
    do NOT count towards the substantive threshold and do NOT short-circuit
    the check. At least one UTF-8 sibling must still carry substantive
    text. This is a deliberate refusal to add an opt-out via "just drop
    a random binary file here" (ADR-003 / HIGH-1 review finding).
    Symlinks are skipped entirely.
    """

    total = 0
    for artifact in sorted(profile_dir.rglob("*"), key=lambda path: path.as_posix()):
        if artifact.is_symlink():
            # Reject eagerly: rglob will happily enumerate children of a
            # symlinked directory, which could let an attacker "borrow"
            # substantive text from outside the sprint (e.g. a symlink
            # to /usr/share/doc) to clear the 40-char floor. HIGH-2 in
            # sprint-004 TASK-003 code-review-round-001.
            raise WorkflowError(
                f"verification evidence must not contain symlinks: "
                f"{artifact.name} in {profile_dir.name}"
            )
        if not artifact.is_file():
            continue
        if artifact.stat().st_size == 0:
            continue
        try:
            content = artifact.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Binary artefacts are real but unscorable; do not count, do
            # not short-circuit. See docstring above.
            continue
        total += substantive_text_length(content)
        if total >= SUBSTANTIVE_EVIDENCE_MIN_CHARS:
            return True
    return False


# --- Per-profile evidence schema gate (sprint-017 TASK-001) -----------------
#
# ``has_substantive_verification_evidence`` only measures substantive
# character count. It keeps out pure placeholders but accepts "40 characters
# of prose with no actual command or HTTP status line". This sibling gate
# demands that the evidence carry profile-specific semantic anchors so a
# reviewer (human or LLM) can tell what was actually exercised.
#
# Same stance as ADR-001 / ADR-003: no opt-out, clear error messages.

PROFILE_SCHEMA_MIN_BINARY_BYTES = 512

# Magic-byte prefixes for binary artifacts accepted by web.browser shape
# gate. Extension fallback is NOT used — a ".png" with wrong magic bytes
# would let anyone "trick" the gate by renaming a text file.
_WEB_BROWSER_MAGIC_BYTES: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",                # PNG
    b"\xff\xd8\xff",                      # JPEG (any variant starts with FFD8FF)
    b"\x1a\x45\xdf\xa3",                  # WebM / Matroska (EBML header)
    b"%PDF-",                             # PDF
    b"PK\x03\x04",                        # ZIP (playwright trace)
    b"\x00\x00\x00\x18ftypmp4",           # MP4 (partial; enough for smoke)
    b"\x00\x00\x00\x20ftypmp4",           # MP4 variant
    b"\x00\x00\x00\x1cftyp",              # MP4 isobmff generic
    b"GIF87a",                            # GIF87
    b"GIF89a",                            # GIF89
    # "RIFF????WEBP" — WebP is RIFF/WAVE-style: first 4 bytes RIFF, then
    # 4 size bytes, then WEBP. We only match the RIFF header + WEBP marker
    # at offset 8 via a custom check in _is_accepted_browser_binary.
)


def _is_accepted_browser_binary(path: Path) -> bool:
    """True iff ``path`` is a real binary artifact above the size floor.

    Extension alone is insufficient (attacker could rename a text file).
    We read the first 16 bytes and match against known magic-byte prefixes.
    WebP (RIFF/WEBP) needs a two-window check because size bytes sit
    between the RIFF header and the WEBP marker.
    """
    try:
        if path.stat().st_size < PROFILE_SCHEMA_MIN_BINARY_BYTES:
            return False
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return False
    if any(head.startswith(sig) for sig in _WEB_BROWSER_MAGIC_BYTES):
        return True
    # WebP: "RIFF" + 4-byte size + "WEBP"
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def _strip_html_comments(text: str) -> str:
    """Drop HTML comments so anchors inside comments do not count.

    Mirrors ``substantive_text_length``'s stripping. Without this an agent
    could paste `<!-- Command: fake --><!-- Exit: 0 -->` and pass the
    gate trivially.
    """
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def _collect_profile_text(profile_dir: Path) -> str:
    """Concatenate UTF-8 readable evidence text across the profile dir,
    with HTML comments stripped. Binary files are ignored.
    """
    chunks: list[str] = []
    for artifact in sorted(profile_dir.rglob("*"), key=lambda p: p.as_posix()):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        try:
            text = artifact.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        chunks.append(_strip_html_comments(text))
    return "\n".join(chunks)


# Anchor regexes — deliberately boring. Case-insensitive where a human
# might vary casing. Line-anchored where placement matters. Leading
# bullet / checkbox markers (``-`` / ``*`` / ``1.``) are tolerated so
# agents can write evidence as a normal markdown list.
_LINE_PREFIX = r"(?:[-*+]\s+|\d+[.)]\s+|\[[ xX]\]\s+)?"

_CLI_COMMAND_ANCHOR = re.compile(
    r"(?im)^\s*" + _LINE_PREFIX + r"(?:\$\s+\S|>\s+\S|Command\s*:)",
    re.MULTILINE,
)
_CLI_EXIT_ANCHOR = re.compile(
    r"(?i)\b(?:exit(?:\s+code)?\s*[:=]?\s*\d+|exit\s*:\s*\d+|returncode\s*[:=]?\s*\d+|status\s*:\s*\d+)\b"
)

_HTTP_METHOD_ANCHOR = re.compile(
    r"(?m)^\s*" + _LINE_PREFIX + r"(?:[<>]\s*)?(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+\S"
)
_HTTP_STATUS_ANCHOR = re.compile(
    r"(?mi)(?:HTTP/\d(?:\.\d)?\s+(?P<s1>\d{3})\b|^\s*" + _LINE_PREFIX + r"(?:[<>]\s*)?(?:status(?:\s+code)?|HTTP\s+status)\s*[:=]?\s*(?P<s2>\d{3})\b)"
)

_JOB_START_ANCHOR = re.compile(
    r"(?i)\b(?:ran|started|starting|invoked|invoking|launched|began)\b"
)
_JOB_DONE_ANCHOR = re.compile(
    r"(?i)\b(?:completed|finished|done|succeeded)\b"
)

_MD_IMAGE_REF = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _profile_shape_error(profile: str, missing: str) -> WorkflowError:
    return WorkflowError(
        f"Evidence shape gate failed for profile {profile!r}: {missing}. "
        "Evidence must carry the semantic anchors the profile expects. "
        "See validate_profile_evidence_shape docstring for the full "
        "anchor catalogue. No --skip flag is available; paste the missing "
        "anchor(s) into the evidence file."
    )


def validate_profile_evidence_shape(profile_dir: Path, profile_name: str) -> None:
    """Enforce per-profile semantic anchors on evidence files.

    Anchor catalogue:

    - **backend.cli**: a command anchor (``$ cmd``, ``> cmd``, or
      ``Command:`` prefix) AND an exit anchor (``Exit:``, ``exit code``,
      ``returncode``, or ``Status:`` with a number).
    - **backend.http**: an HTTP method verb line (``GET``/``POST``/``PUT``/
      ``DELETE``/``PATCH``/``HEAD``/``OPTIONS`` at line start, optionally
      after ``<``/``>`` for curl-verbose output) AND a 3-digit status code
      (either ``HTTP/1.1 200 OK`` or ``status: 200``).
    - **backend.job**: a start anchor (``ran``/``started``/``invoked``/
      ``launched``) AND a completion anchor (``completed``/``finished``/
      ``done``/``succeeded``).
    - **web.browser**: at least one binary artifact of a recognised media
      type (PNG/JPEG/WebM/MP4/PDF/ZIP/GIF) at least
      ``PROFILE_SCHEMA_MIN_BINARY_BYTES`` in size, OR a markdown image
      reference ``![alt](path)`` whose target resolves relative to the
      markdown file and meets the same magic-byte + size bar.

    HTML comments are stripped before matching so anchors inside comments
    do not count. Unknown profiles are a no-op (forward compat).
    """
    profile_key = profile_name.strip()
    if profile_key not in {"backend.cli", "backend.http", "backend.job", "web.browser"}:
        return  # unknown profile — forward compat, no-op

    if profile_key == "web.browser":
        _validate_web_browser_shape(profile_dir)
        return

    text = _collect_profile_text(profile_dir)

    if profile_key == "backend.cli":
        if not _CLI_COMMAND_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing command anchor "
                "('$ <cmd>', '> <cmd>', or 'Command:' at line start)",
            )
        if not _CLI_EXIT_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing exit/status anchor "
                "('Exit: 0' / 'exit code 0' / 'returncode: 0' / 'Status: 0')",
            )
        return

    if profile_key == "backend.http":
        if not _HTTP_METHOD_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing HTTP method anchor "
                "(GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS at line start)",
            )
        if not _HTTP_STATUS_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing HTTP status anchor "
                "('HTTP/1.1 200 OK' or 'status: 200')",
            )
        return

    if profile_key == "backend.job":
        if not _JOB_START_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing job start anchor "
                "(ran/started/invoked/launched/began)",
            )
        if not _JOB_DONE_ANCHOR.search(text):
            raise _profile_shape_error(
                profile_key,
                "missing job completion anchor "
                "(completed/finished/done/succeeded)",
            )
        return


def _validate_web_browser_shape(profile_dir: Path) -> None:
    """Require a real binary artifact OR a markdown reference that
    resolves to one, above the size + magic-byte bar."""

    # 1) Any direct binary artifact of the right size + magic bytes?
    for artifact in sorted(profile_dir.rglob("*"), key=lambda p: p.as_posix()):
        if artifact.is_symlink() or not artifact.is_file():
            continue
        if _is_accepted_browser_binary(artifact):
            return

    # 2) Fall back to markdown references that point at real files.
    for md_file in sorted(profile_dir.rglob("*.md"), key=lambda p: p.as_posix()):
        if md_file.is_symlink() or not md_file.is_file():
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for ref in _MD_IMAGE_REF.findall(_strip_html_comments(text)):
            ref_path = (md_file.parent / ref).resolve()
            # Confine to profile_dir to prevent ../../system-file tricks.
            try:
                ref_path.relative_to(profile_dir.resolve())
            except ValueError:
                continue
            if _is_accepted_browser_binary(ref_path):
                return

    raise _profile_shape_error(
        "web.browser",
        "missing binary artifact (>= "
        f"{PROFILE_SCHEMA_MIN_BINARY_BYTES}B, recognised media type: "
        "png/jpeg/webm/mp4/pdf/zip/gif) and no markdown image reference "
        "resolves to such a file under the profile dir",
    )


# --- Test-runner pass-marker gate (sprint-017 TASK-002) ---------------------
#
# The shape gate (TASK-001) runs at ready_to_merge/done and demands real
# profile-specific anchors. But red->green and green->in_review had no
# evidence check at all — an agent could toggle state without ever
# pasting a test runner's stdout. This gate plugs that hole by scanning
# the profile dir for a recognisable runner PASS marker and rejecting
# when either (a) no PASS anchor is present, or (b) PASS is present but
# so is FAIL/Error (mixed = overall failure).

# PASS anchors per runner family. Each pattern is boring on purpose.
_PYTEST_PASS = re.compile(r"\b(\d+)\s+passed\b", re.IGNORECASE)
_GO_PASS_LINE = re.compile(r"(?m)^\s*(?:---\s+)?PASS(?::\s|\s*$)")
_GO_OK_PACKAGE = re.compile(r"(?m)^ok\s+\S+\s+\d+\.\d+s")
_JEST_PASS = re.compile(r"(?im)^\s*Tests:\s+.*\b(\d+)\s+passed\b")
_VITEST_PASS = re.compile(
    r"(?im)^\s*(?:Test Files|\s+Tests)\s+(\d+)\s+passed\b"
)
_CARGO_PASS = re.compile(
    r"test result:\s*ok\.\s*(\d+)\s+passed", re.IGNORECASE
)
_JUNIT_PASS = re.compile(
    r"Tests run:\s*(\d+),\s*Failures:\s*0,\s*Errors:\s*0",
    re.IGNORECASE,
)

# FAIL anchors. Must be specific enough to avoid false positives on
# unrelated words like "FAILOVER" or "failed login (spec wording)".
_PYTEST_FAIL = re.compile(r"\b(\d+)\s+failed\b", re.IGNORECASE)
_GO_FAIL_LINE = re.compile(r"(?m)^\s*(?:---\s+)?FAIL(?::\s|\s*$)")
_GO_FAIL_PACKAGE = re.compile(r"(?m)^FAIL\s+\S+\s+\d+\.\d+s")
_PYTEST_ERROR = re.compile(
    r"(?m)^ERROR\s+\S|(?:\b\d+\s+error)", re.IGNORECASE
)
_JEST_FAIL = re.compile(
    r"(?im)^\s*Tests:\s+.*\b([1-9]\d*)\s+failed\b"
)
_JUNIT_FAIL = re.compile(
    r"Tests run:\s*\d+,\s*Failures:\s*([1-9]\d*)",
    re.IGNORECASE,
)
_CARGO_FAIL = re.compile(
    r"test result:\s*FAILED\.|(\d+)\s+failed;", re.IGNORECASE
)

# "No tests collected / ran" markers — count as rejection even if a
# zero-count 'passed' literal appears.
_NO_TESTS_RAN = re.compile(
    r"(?i)\b(?:no\s+tests?\s+ran|collected\s+0\s+items?|running\s+0\s+tests|ran\s+0\s+tests)\b"
)
_ZERO_PASSED = re.compile(
    r"\b0\s+passed\b(?:\s*,\s*0\s+failed\b)?", re.IGNORECASE
)


def _pass_matches(text: str) -> list[tuple[str, str]]:
    """Return (runner_name, matched_substr) for every PASS anchor found.

    Ordering is stable so tests can introspect the list.
    """
    hits: list[tuple[str, str]] = []
    for runner, pattern in (
        ("pytest", _PYTEST_PASS),
        ("go-test (--- PASS)", _GO_PASS_LINE),
        ("go-test (ok pkg)", _GO_OK_PACKAGE),
        ("jest", _JEST_PASS),
        ("vitest", _VITEST_PASS),
        ("cargo test", _CARGO_PASS),
        ("junit", _JUNIT_PASS),
    ):
        for m in pattern.finditer(text):
            hits.append((runner, m.group(0)))
    return hits


def _fail_matches(text: str) -> list[tuple[str, str]]:
    hits: list[tuple[str, str]] = []
    for runner, pattern in (
        ("pytest", _PYTEST_FAIL),
        ("pytest error", _PYTEST_ERROR),
        ("go-test line", _GO_FAIL_LINE),
        ("go-test package", _GO_FAIL_PACKAGE),
        ("jest", _JEST_FAIL),
        ("junit", _JUNIT_FAIL),
        ("cargo test", _CARGO_FAIL),
    ):
        for m in pattern.finditer(text):
            hits.append((runner, m.group(0)))
    return hits


_PASS_MARKER_ERROR = (
    "Evidence must contain a recognised test-runner PASS marker before "
    "advancing to this status. Supported runner outputs: pytest "
    "('N passed'), go test ('--- PASS:' / 'ok  pkg  0.012s' / 'PASS'), "
    "jest ('Tests: N passed'), vitest ('Tests  N passed'), cargo test "
    "('test result: ok. N passed'), junit ('Tests run: N, Failures: 0, "
    "Errors: 0'). Paste one of the above into "
    "verification/<profile>/. No --skip flag is available."
)


def validate_test_pass_marker(profile_dir: Path) -> None:
    """Scan ``profile_dir`` for a recognised test-runner PASS marker.

    Raises ``WorkflowError`` when:
      - the profile dir is empty or only contains binaries with no text
      - none of the supported PASS patterns match
      - the matching PASS anchor co-exists with a FAIL/Error anchor
        anywhere in the aggregated text
      - a 'no tests ran' / 'collected 0 items' signal is present
        (explicit refusal to accept the zero-tests degenerate case)

    HTML comments are stripped before matching so commented-out PASS
    text does not count (mirrors ``substantive_text_length``).
    """
    text = _collect_profile_text(profile_dir)
    if not text.strip():
        raise WorkflowError(
            _PASS_MARKER_ERROR + " (profile directory has no readable text)"
        )

    # Degenerate "no tests ran" cases must be rejected even if a literal
    # "0 passed" appears — that's not a valid PASS anchor.
    if _NO_TESTS_RAN.search(text) or _ZERO_PASSED.search(text):
        raise WorkflowError(
            _PASS_MARKER_ERROR
            + " (found 'no tests ran' / '0 passed' — needs >= 1 actual test PASS)"
        )

    pass_hits = _pass_matches(text)
    if not pass_hits:
        raise WorkflowError(_PASS_MARKER_ERROR)

    fail_hits = _fail_matches(text)
    if fail_hits:
        # Some PASS-shaped lines also accidentally match fail patterns
        # (e.g. cargo's "0 failed;" inside a green summary). Discard
        # FAIL hits that refer to explicit zero-count "0 failed".
        meaningful_fails = [
            (runner, text_)
            for runner, text_ in fail_hits
            if not re.match(r"^\s*0\s+failed", text_, re.IGNORECASE)
        ]
        if meaningful_fails:
            runners = ", ".join(sorted({r for r, _ in meaningful_fails}))
            raise WorkflowError(
                "Evidence contains a PASS marker but also a FAIL / Error "
                f"anchor ({runners}). Mixed-outcome evidence does not clear "
                "the gate; paste only a green run's output."
            )


AGENT_RUN_LEDGER_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "timestamp",
        "agent",
        "purpose",
        "input_artifact",
        "output_artifact",
        "status",
        "notes",
    }
)


def validate_agent_runs_ledger(ledger_path: Path) -> None:
    """Validate optional task-level agent run audit metadata.

    The ledger is intentionally optional and non-authoritative: it helps humans
    see which subagents were invoked, but it is not proof that an external
    runtime actually executed those agents.
    """

    if not ledger_path.exists():
        return
    if ledger_path.is_symlink():
        raise WorkflowError("agent-runs.jsonl must not be a symlink")
    if not ledger_path.is_file():
        raise WorkflowError("agent-runs.jsonl must be a file")
    try:
        content = ledger_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise WorkflowError("agent-runs.jsonl must be readable UTF-8 JSONL") from error
    if not content.strip():
        return

    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise WorkflowError(
                f"agent-runs.jsonl line {line_number} must be a valid JSON object"
            ) from error
        if not isinstance(payload, dict):
            raise WorkflowError(
                f"agent-runs.jsonl line {line_number} must be a JSON object"
            )
        missing = sorted(AGENT_RUN_LEDGER_REQUIRED_FIELDS - set(payload))
        if missing:
            raise WorkflowError(
                f"agent-runs.jsonl line {line_number} is missing required fields: "
                f"{', '.join(missing)}"
            )


HANDOFF_TARGET_SECTIONS: tuple[str, ...] = (
    "Viewed code/tests/docs",
    "Impact surface",
)
HANDOFF_FILE_LINE_PATTERN = re.compile(r"\S+:\d+")
HANDOFF_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)


def validate_handoff_evidence_anchors(handoff_path: Path) -> None:
    """Validate that handoff.md has at least one `file:line` anchor under
    either 'Viewed code/tests/docs' or 'Impact surface'.

    File-existence-first: if the handoff file is absent, the gate silently
    passes. This protects legacy tasks created before sprint-011 (which do
    not own a handoff.md) from being punished by a new gate.

    Scope: only scans the two target sections listed in
    HANDOFF_TARGET_SECTIONS. References buried in unrelated sections
    (e.g. 'Known Pitfalls') do NOT count as valid anchors — Phase-1
    scouting evidence belongs in one of the two designated surfaces.

    Raises WorkflowError with an actionable hint naming both section
    names and the expected `\\S+:\\d+` format.
    """

    if not handoff_path.exists():
        return
    if handoff_path.is_symlink():
        raise WorkflowError("handoff.md must not be a symlink")
    if not handoff_path.is_file():
        raise WorkflowError("handoff.md must be a file")
    try:
        content = handoff_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise WorkflowError("handoff.md must be readable UTF-8 text") from error

    # Strip HTML comments before scanning: the default template ships example
    # `file:line` refs inside `<!-- ... -->` blocks so authors see the expected
    # shape. Those examples must NOT count as real Phase-1 anchors.
    stripped_content = HANDOFF_HTML_COMMENT_PATTERN.sub("", content)

    if _handoff_has_anchor_under_target_section(stripped_content):
        return

    # Treat an unpopulated scaffold (both target sections present but empty
    # after stripping comments) as "not filled yet" — silent pass, same as
    # a fully absent handoff.md. This lets test fixtures and fresh scaffolds
    # move planned->red without being punished before the author has had a
    # chance to fill Phase-1 notes. The gate only bites once the author has
    # written *some* content under one of the target sections without a
    # file:line anchor — that is the actual "partially filled, not evidenced"
    # state we want to catch.
    if not _handoff_target_sections_have_any_content(stripped_content):
        return

    section_list = " or ".join(f"'{name}'" for name in HANDOFF_TARGET_SECTIONS)
    raise WorkflowError(
        "handoff.md is missing a file:line evidence anchor. Add at least one "
        f"bullet under {section_list} that matches the pattern "
        r"\S+:\d+"
        " (for example: '- scripts/validation.py:747 substantive evidence helper'). "
        "This gate fires only on the planned->red transition; edit handoff.md "
        "and re-run `workflowctl advance-status --to-status red`."
    )


def _handoff_has_anchor_under_target_section(content: str) -> bool:
    """Return True iff at least one line under a target section has `\\S+:\\d+`.

    Parsing model:
      - A bullet line starting with `- <section-name>:` (possibly indented)
        opens a section scope; any following bullets that are MORE indented
        are considered 'within' that section until a sibling/parent bullet
        closes it.
      - A markdown header (`#`, `##`, ...) also closes any open section scope.

    This mirrors the two-level bullet structure emitted by
    templates/workflow/handoff.md.tmpl.
    """

    def leading_ws(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    in_target = False
    target_indent = -1
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        # A markdown heading always closes the current target scope.
        if stripped.startswith("#"):
            in_target = False
            target_indent = -1
            continue
        if not stripped:
            continue
        indent = leading_ws(raw_line)
        # Detect start of a target section: bullet of the form
        #   `- <TARGET_SECTION>:` (trailing content tolerated).
        if stripped.startswith("- "):
            bullet_body = stripped[2:].rstrip()
            matched_target = None
            for name in HANDOFF_TARGET_SECTIONS:
                # Section header bullets look like "- Viewed code/tests/docs:"
                # (possibly with trailing colon only). Trailing refs on the
                # same line would already count and are accepted.
                if bullet_body == f"{name}:" or bullet_body.startswith(f"{name}:"):
                    matched_target = name
                    break
            if matched_target is not None:
                # Same-line ref on the header counts.
                if HANDOFF_FILE_LINE_PATTERN.search(bullet_body[len(matched_target) + 1 :]):
                    return True
                in_target = True
                target_indent = indent
                continue
            # Non-target bullet at the same or outer indent closes the scope.
            if in_target and indent <= target_indent:
                in_target = False
                target_indent = -1
        if in_target and indent > target_indent:
            if HANDOFF_FILE_LINE_PATTERN.search(raw_line):
                return True
    return False


def _handoff_target_sections_have_any_content(content: str) -> bool:
    """Return True iff at least one target section has a non-empty child bullet.

    Used to distinguish "unpopulated scaffold" (both sections present but no
    child content yet — silent pass) from "partially filled but no file:line
    anchor" (at least one child bullet exists, but none match \\S+:\\d+ — must
    be rejected).

    Mirrors the parsing in _handoff_has_anchor_under_target_section but only
    tracks whether any child bullet text survives under a target section.
    """

    def leading_ws(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    in_target = False
    target_indent = -1
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            in_target = False
            target_indent = -1
            continue
        if not stripped:
            continue
        indent = leading_ws(raw_line)
        if stripped.startswith("- "):
            bullet_body = stripped[2:].rstrip()
            matched_target = None
            for name in HANDOFF_TARGET_SECTIONS:
                if bullet_body == f"{name}:" or bullet_body.startswith(f"{name}:"):
                    matched_target = name
                    break
            if matched_target is not None:
                trailing_after_colon = bullet_body[len(matched_target) + 1 :].strip()
                if trailing_after_colon:
                    return True
                in_target = True
                target_indent = indent
                continue
            if in_target and indent <= target_indent:
                in_target = False
                target_indent = -1
                # Fall through: this bullet belongs to a non-target sibling,
                # not to a target section.
                continue
        if in_target and indent > target_indent:
            # Any non-empty child line (bullet or prose) counts as "content".
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
        if status in {"ready_to_merge", "done"} and not has_substantive_verification_evidence(profile_dir):
            raise WorkflowError(
                "Verification profile directory must contain substantive evidence "
                f"(>= {SUBSTANTIVE_EVIDENCE_MIN_CHARS} substantive chars across its files, "
                "not just placeholder tokens like 'TODO' / '待补' or empty HTML comments) "
                f"before {status}: {profile_dir.name}"
            )
        if status in {"ready_to_merge", "done"}:
            # Shape gate runs AFTER substantive-chars gate: if the dir is
            # structurally empty, the above error already fires. Only when
            # there's actual evidence do we then demand the right anchors
            # for the profile. Unknown profiles (forward compat) no-op.
            validate_profile_evidence_shape(profile_dir, normalized)


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

    # --- Bundle consistency check (I-012) ---
    # Verify that tasks claiming the same bundle slug form valid bundles
    # (2-3 members). Source of truth is the bundle: field in each task.md.
    bundle_groups: dict[str, list[str]] = {}
    for task_dir in task_dirs:
        task_md = task_dir / "task.md"
        task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
        bundle_value = task_data.get("bundle")
        if bundle_value is not None:
            bundle_str = stringify(bundle_value).strip()
            if bundle_str:
                bundle_groups.setdefault(bundle_str, []).append(task_dir.name)

    for bundle_slug, members in bundle_groups.items():
        if len(members) < 2:
            raise WorkflowError(
                f"Bundle {bundle_slug!r} has only {len(members)} task(s); "
                "bundles require 2-3 tasks"
            )
        if len(members) > MAX_BUNDLE_SIZE:
            raise WorkflowError(
                f"Bundle {bundle_slug!r} has {len(members)} tasks; "
                f"maximum is {MAX_BUNDLE_SIZE}"
            )


# --- Sprint-level smoke gate (ADR-003 / sprint-004 TASK-003) ----------------


def validate_sprint_smoke_evidence(sprint_dir: Path) -> None:
    """Ensure that every ``execution_profile`` used by the sprint's tasks
    has substantive evidence under ``sprint_dir/verification/<profile-dir>/``.

    This is the sprint-level complement to the task-level substantive-
    evidence gate from ADR-003 闸 1. Task-level smoke covers each task
    in isolation; sprint-smoke guarantees that **cross-task integration
    evidence** exists at the sprint boundary — catching the voiceagent4
    failure mode where every individual task had unit tests but the
    wiring between them (Pipeline, WebRTC audio track, etc.) was never
    run end-to-end.

    Rules:

    - An empty sprint (no TASK-* directories) is rejected with "nothing
      to smoke" — sealing a placeholder carries no audit signal.
    - The set of required profiles is the union of every task's
      ``execution_profile`` frontmatter field. Blocked tasks still count
      (the profile was planned even if the work stalled).
    - For each required profile, ``sprint_dir/verification/<profile-dir>/``
      must pass :func:`has_substantive_verification_evidence`. Missing
      dirs and placeholder-only content both fail.
    - Errors collect ALL missing/placeholder profiles before raising so
      the operator can fix in one pass rather than drip-feeding.
    """

    tasks_dir = sprint_dir / "tasks"
    if not tasks_dir.is_dir():
        raise WorkflowError(
            f"sprint has no tasks directory; nothing to smoke: {sprint_dir.name}"
        )

    task_dirs: list[Path] = []
    for child in sorted(tasks_dir.iterdir(), key=lambda path: path.name):
        if child.is_symlink():
            # Reject eagerly — a symlinked TASK dir could point at a
            # task whose execution_profile differs from the sibling real
            # tasks, letting the corresponding profile evidence slip
            # through the gate. `seal-sprint` uses the same discipline
            # (see handle_seal_sprint).
            raise WorkflowError(
                f"task entry must not be a symlink: {child.name} "
                "(sprint-smoke cannot trust profiles of symlinked task dirs)"
            )
        if not child.is_dir():
            continue
        if TASK_ID_PATTERN.fullmatch(child.name):
            task_dirs.append(child)

    if not task_dirs:
        raise WorkflowError(
            f"sprint has no tasks; nothing to smoke: {sprint_dir.name}. "
            "sprint-smoke guards cross-task integration evidence; "
            "an empty sprint has no such surface."
        )

    required_profiles: set[str] = set()
    unreadable_tasks: list[str] = []
    for task_dir in task_dirs:
        task_md = task_dir / "task.md"
        if not task_md.is_file():
            unreadable_tasks.append(f"{task_dir.name} (missing task.md)")
            continue
        try:
            task_data = parse_frontmatter(task_md.read_text(encoding="utf-8"))
        except WorkflowError as error:
            unreadable_tasks.append(f"{task_dir.name} (invalid task.md: {error})")
            continue
        profile_raw = stringify(task_data.get("execution_profile", ""))
        try:
            profile = normalize_execution_profile(profile_raw)
        except WorkflowError:
            unreadable_tasks.append(
                f"{task_dir.name} (unknown execution_profile: {profile_raw!r})"
            )
            continue
        required_profiles.add(profile)

    if unreadable_tasks:
        bullets = "\n  - ".join(unreadable_tasks)
        raise WorkflowError(
            f"sprint-smoke cannot determine profiles for {len(unreadable_tasks)} "
            f"task(s) in {sprint_dir.name}:\n  - {bullets}"
        )

    # Single-task sprint optimization: when there is exactly one task,
    # task-level verification evidence is equivalent to sprint-level
    # evidence (there is no cross-task integration surface to test).
    # Fall back to the task's own verification/<profile>/ directory
    # when the sprint-level directory is missing.
    single_task_fallback = len(task_dirs) == 1

    verification_dir = sprint_dir / "verification"
    missing: list[str] = []
    insufficient: list[str] = []
    for profile in sorted(required_profiles):
        profile_dir = verification_dir / execution_profile_dir(profile)
        if not profile_dir.is_dir():
            # Try task-level fallback for single-task sprints
            if single_task_fallback:
                task_profile_dir = task_dirs[0] / "verification" / execution_profile_dir(profile)
                if (
                    not task_profile_dir.is_symlink()
                    and task_profile_dir.is_dir()
                    and has_substantive_verification_evidence(task_profile_dir)
                ):
                    continue
            missing.append(profile)
            continue
        if not has_substantive_verification_evidence(profile_dir):
            insufficient.append(profile)

    problems: list[str] = []
    if missing:
        problems.append(
            f"missing evidence dir(s): {', '.join(missing)} "
            f"(expected under {verification_dir.name}/<profile>/)"
        )
    if insufficient:
        problems.append(
            f"insufficient evidence in: {', '.join(insufficient)} "
            f"(need >= {SUBSTANTIVE_EVIDENCE_MIN_CHARS} substantive chars, "
            "not just placeholder tokens)"
        )
    if problems:
        raise WorkflowError(
            f"sprint-smoke failed for {sprint_dir.name}: " + "; ".join(problems)
        )


def ensure_review_pair(review_dir: Path, review_type: str, round_number: int) -> None:
    base_name = f"{review_type}-review-round-{round_number:03d}"
    review_file = review_dir / f"{base_name}.md"
    resolved_file = review_dir / f"{base_name}.resolved.md"

    ensure_review_artifact(review_file, "review")
    ensure_review_artifact(resolved_file, "resolved review")
    # Sprint-010 TASK-001: harden resolved coverage once the round is paired.
    # Runs only when review + resolved both exist; legacy (no `### finding-`
    # header) files skip the gate transparently.
    validate_review_resolution_coverage(review_dir, review_type, round_number)


_FINDING_ID_RE = r"(finding-\d+)(?:\s|·|$)"
_FINDING_HEADER = re.compile(r"^###\s+" + _FINDING_ID_RE, re.MULTILINE)
_RESOLVED_HEADER = re.compile(r"^###\s+" + _FINDING_ID_RE)


def _parse_finding_ids_from_review(review_md: str) -> list[str]:
    """Return the ordered unique list of `finding-NNN` ids declared in a
    review round markdown. Deduplicates while preserving first-seen order.
    """
    seen: dict[str, None] = {}
    for match in _FINDING_HEADER.finditer(review_md):
        fid = match.group(1)
        seen.setdefault(fid, None)
    return list(seen.keys())


def _parse_resolved_entries(resolved_md: str) -> dict[str, dict[str, str]]:
    """Parse resolved markdown into a map of finding-id -> {status, waiver_reason}.

    Each `### finding-NNN` subsection is walked until the next `###` or `##`
    header; we collect `- Status:` and `- Waiver-Reason:` lines verbatim (value
    stripped and lower-cased for Status to match the rest of the module's enum
    normalization style). Missing Status leaves the key absent so the caller
    can raise a precise error. The id header uses the same trailing guard as
    the review-side parser (via shared _RESOLVED_HEADER) so inputs like
    `### finding-001garbage` are ignored on both sides symmetrically.

    Tie-breaks: first block wins for a repeated id (setdefault); within a
    block, first `- Status:` / `- Waiver-Reason:` line wins (we assign only
    when the key is still absent).
    """
    entries: dict[str, dict[str, str]] = {}
    lines = resolved_md.splitlines()
    index = 0
    while index < len(lines):
        header = _RESOLVED_HEADER.match(lines[index])
        if not header:
            index += 1
            continue
        fid = header.group(1)
        block: dict[str, str] = {}
        index += 1
        while index < len(lines) and not lines[index].startswith("##"):
            status_match = re.match(r"^-\s*Status\s*:\s*(.+?)\s*$", lines[index])
            if status_match and "status" not in block:
                # Lower-case to match normalize_* helpers elsewhere in this
                # module; authors writing `Resolved` / `WAIVED` get a friendly
                # match instead of a confusing rejection.
                block["status"] = status_match.group(1).strip().lower()
            waiver_match = re.match(r"^-\s*Waiver-Reason\s*:\s*(.+?)\s*$", lines[index])
            if waiver_match and "waiver_reason" not in block:
                block["waiver_reason"] = waiver_match.group(1).strip()
            index += 1
        entries.setdefault(fid, block)
    return entries


def validate_review_resolution_coverage(
    review_dir: Path,
    review_type: str,
    round_number: int,
) -> None:
    """Gate: every `### finding-NNN` declared in the review round must be
    closed in the paired .resolved.md with Status ∈ {resolved, waived}; a
    waived finding must carry a non-empty `- Waiver-Reason:` line.

    Backward compatibility: if the review round markdown declares zero
    `### finding-` headers (legacy prose format), this function is a no-op —
    the existing `validate_review_artifact_content` gate still fires for
    section presence. This keeps sprints 001-009 green without forcing a
    migration.
    """
    base_name = f"{review_type}-review-round-{round_number:03d}"
    review_file = review_dir / f"{base_name}.md"
    resolved_file = review_dir / f"{base_name}.resolved.md"

    if not review_file.is_file() or not resolved_file.is_file():
        # Existence is the prior gate's job. Coverage gate is additive.
        return

    review_md = review_file.read_text(encoding="utf-8")
    resolved_md = resolved_file.read_text(encoding="utf-8")

    declared = _parse_finding_ids_from_review(review_md)
    if not declared:
        # Legacy prose format — nothing to close. No-op.
        return

    entries = _parse_resolved_entries(resolved_md)

    missing = [fid for fid in declared if fid not in entries]
    if missing:
        raise WorkflowError(
            f"Resolved review {resolved_file.name} is missing finding id "
            f"section(s): {', '.join(missing)}. Every `### finding-NNN` "
            "declared in the review round must have a matching resolution "
            "block with `- Status:` (resolved|waived)."
        )

    allowed_statuses = {"resolved", "waived"}
    problems: list[str] = []
    for fid in declared:
        block = entries[fid]
        status = block.get("status")
        if status is None:
            problems.append(
                f"{fid}: missing `- Status:` line (expected resolved|waived)"
            )
            continue
        if status not in allowed_statuses:
            problems.append(
                f"{fid}: invalid Status `{status}` "
                f"(expected one of: {', '.join(sorted(allowed_statuses))})"
            )
            continue
        if status == "waived":
            reason = block.get("waiver_reason", "").strip()
            if not reason:
                problems.append(
                    f"{fid}: Status is `waived` but `- Waiver-Reason:` line "
                    "is missing or empty"
                )

    if problems:
        raise WorkflowError(
            f"Resolved review {resolved_file.name} has coverage issues:\n  - "
            + "\n  - ".join(problems)
        )


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
    agents = ["tdd-guide", "code-reviewer"]
    if execution_profile == "web.browser":
        agents.append("e2e-runner")
    if task_requires_security_review(task_type, execution_profile):
        agents.append("security-reviewer")
    return agents


def task_requires_security_review(task_type: str, execution_profile: str) -> bool:
    tokens = set(task_type.split(","))
    return execution_profile == "backend.http" or bool(tokens & {"auth", "input", "api"})


def normalize_review_mode(value: Any) -> str:
    """Normalize the task.md 'review_mode' frontmatter field. Missing -> DEFAULT_REVIEW_MODE."""
    if value is None:
        return DEFAULT_REVIEW_MODE
    text = stringify(value).strip().lower()
    if text == "":
        return DEFAULT_REVIEW_MODE
    if text not in ALLOWED_REVIEW_MODES:
        raise WorkflowError(
            f"Unknown review_mode: {text!r}. Allowed values: {sorted(ALLOWED_REVIEW_MODES)}"
        )
    return text


def infer_default_review_mode(task_type: str, execution_profile: str) -> str:
    """Infer a sensible default review_mode from task_type and execution_profile.

    Tasks touching security surfaces or cross-module concerns should default
    to 'full'; everything else defaults to 'light'.
    """
    if execution_profile == "backend.http":
        return "full"
    tokens = set(task_type.split(","))
    if tokens & {"auth", "input", "api", "e2e"}:
        return "full"
    return "light"


def resolve_review_mode(value: Any, task_type: str, execution_profile: str) -> str:
    """Resolve review_mode with task-contract-aware defaults and safeguards."""
    inferred = infer_default_review_mode(task_type, execution_profile)
    if value is None or stringify(value).strip() == "":
        return inferred
    review_mode = normalize_review_mode(value)
    if inferred == "full" and review_mode != "full":
        raise WorkflowError(
            "review_mode must be 'full' for auth/input/api/backend.http/e2e tasks"
        )
    return review_mode


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
    ]
    # Preserve optional `flow` field if present. Without this, every call to
    # `apply_status_transition` -> `write_task_document` silently strips the
    # field a user added by hand to switch a task to lightweight thresholds.
    # Rendered last so it never disturbs the position of required fields.
    if task_data.get("flow") is not None:
        flow_value = normalize_task_flow(task_data["flow"])
        lines.append(f"flow: {flow_value}")
    # Preserve optional `review_mode` field if present.
    if task_data.get("review_mode") is not None:
        review_value = normalize_review_mode(task_data["review_mode"])
        lines.append(f"review_mode: {review_value}")
    # Preserve optional `bundle` field if present (I-012 task bundle).
    if task_data.get("bundle") is not None:
        bundle_str = stringify(task_data["bundle"]).strip()
        if bundle_str:
            lines.append(f"bundle: {bundle_str}")
    lines.append("---")
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
