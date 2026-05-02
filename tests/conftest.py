"""pytest config — make repo root importable so tests can do `from scripts.x import y`.

Rationale: existing tests historically shell out to `workflowctl.py` via
subprocess, so sys.path never mattered. Sprint-010 introduces unit tests that
import `scripts.validation` helpers directly (finer-grained gates, faster
loops). Injecting the repo root here keeps that import path uniform.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# sprint-015 TASK-001: shared helper for populating task.md Goal section so
# tests that advance a freshly-created draft can clear the Goal gate without
# each test re-implementing the search-and-replace.
# ---------------------------------------------------------------------------


def populate_task_goal(task_md: Path, goal_text: str | None = None) -> None:
    """Replace a placeholder/empty `## Goal` body in task.md with prose.

    Idempotent: if the Goal section is already substantive, it's left alone.
    Use in tests that need to drive a draft task past the Goal gate
    (draft-exit) via `workflowctl advance-status`.
    """
    goal_text = goal_text or "Test fixture Goal: exercise the workflow end-to-end."
    text = task_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Goal")
    except StopIteration:
        return
    end = start + 1
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    # If body already has a non-comment, non-blank line, leave it alone.
    import re

    current_body = "\n".join(lines[start + 1 : end])
    stripped = re.sub(r"<!--.*?-->", "", current_body, flags=re.DOTALL).strip()
    if stripped and "Describe the expected OUTCOME" not in stripped:
        return
    new_block = ["## Goal", goal_text, ""]
    task_md.write_text("\n".join(lines[:start] + new_block + lines[end:]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# sprint-017 TASK-002: shared helper to plant a test-runner PASS marker
# into a task's verification/<profile>/ dir. Tests that fast-forward a
# task to green (bypassing the red->green CLI transition via frontmatter
# edit) still need to satisfy the pass-marker gate when init-review-round
# runs green->in_review. Centralising this here prevents fixture drift.
# ---------------------------------------------------------------------------


def plant_test_pass_marker(
    task_dir: Path,
    *,
    profile: str = "cli",
    runner: str = "pytest",
    filename: str = "pass-marker.log",
) -> None:
    """Drop a minimal file with a recognised PASS marker for ``runner``.

    ``profile`` is the verification/<dirname> short name (cli / http /
    job / browser). Callers with a specific profile can pick it;
    default is cli which covers ~90% of tests.
    """
    pass_lines = {
        "pytest": "569 passed, 2 skipped in 59.23s\n",
        "go-test": "--- PASS: TestOne (0.01s)\nok  \tpkg\t0.012s\nPASS\n",
        "jest": "Tests: 42 passed, 42 total\n",
        "vitest": "Test Files  3 passed (3)\n     Tests  12 passed (12)\n",
        "cargo": "test result: ok. 12 passed; 0 failed; 0 ignored\n",
        "junit": "Tests run: 42, Failures: 0, Errors: 0, Skipped: 0\n",
    }
    marker = pass_lines.get(runner, pass_lines["pytest"])
    profile_dir = task_dir / "verification" / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / filename).write_text(marker, encoding="utf-8")

