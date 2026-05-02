"""sprint-019 TASK-003: TDD order gate on red transition.

`advance-status planned→red` previously had no machine check on git
history — an LLM could write tests + implementation in the same
thinking cycle and then stage-stash-commit the red "proof" in a dance
that fools text-based gates. This task adds a diff-inspection gate
that rejects a new task's red transition when production code is
already staged or committed. Escape hatch: `skeleton: true` frontmatter
for compiled-language skeleton phase. Legacy tasks (no schema_version)
are exempt.

Tests here run against real temporary git repositories (not mocks) —
subprocess.run git init / add / commit — so the contract pinned is
exactly what handle_advance_status sees at runtime.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    classify_diff_path,
    validate_red_transition_diff,
)


WORKFLOWCTL = REPO_ROOT / "scripts" / "workflowctl.py"


def _git(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"HOME": str(cwd), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    if check:
        assert r.returncode == 0, f"git {args} failed: stderr={r.stderr}"
    return r


def _init_repo(tmp_path: Path) -> Path:
    """Create a fresh git repo at tmp_path with one initial commit."""
    _git(["init", "--quiet", "-b", "main"], tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    _git(["add", ".gitignore"], tmp_path)
    _git(["commit", "--quiet", "-m", "initial"], tmp_path)
    return tmp_path


@dataclass
class _FakeTaskPaths:
    task_dir: Path
    project_dir: Path


# ---------------------------------------------------------------------------
# classify_diff_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "tests/test_x.py",
        "tests/subdir/test_y.py",
        "tests/conftest.py",
        "conftest.py",
        "foo_test.py",
        "test_bar.py",
        "pkg/foo/foo_test.go",
        "pkg/foo/foo_test.ts",
    ],
)
def test_classify_test_variants(rel_path: str) -> None:
    assert classify_diff_path(rel_path) == "test"


def test_classify_tests_path() -> None:
    assert classify_diff_path("tests/test_evidence_schema_gate.py") == "test"


@pytest.mark.parametrize(
    "rel_path",
    [
        "scripts/validation.py",
        "scripts/workflowctl.py",
        "src/foo.py",
        "lib/bar.ts",
        "app/main.go",
        "mymodule/core.py",
        "index.ts",
    ],
)
def test_classify_production_path(rel_path: str) -> None:
    assert classify_diff_path(rel_path) == "production"


@pytest.mark.parametrize(
    "rel_path",
    [
        ".theking/workflows/x/sprints/s/tasks/TASK-001-foo/spec.md",
        ".theking/workflows/x/sprints/s/tasks/TASK-001-foo/handoff.md",
        ".theking/workflows/x/sprints/s/sprint.md",
        ".theking/context/adr/ADR-007-foo.md",
        ".theking/verification/regression.md",
    ],
)
def test_classify_metadata_path(rel_path: str) -> None:
    assert classify_diff_path(rel_path) == "metadata"


@pytest.mark.parametrize(
    "rel_path",
    [
        "README.md",
        "pyproject.toml",
        "Makefile",
        "some-file-without-category.txt",
    ],
)
def test_classify_other_path(rel_path: str) -> None:
    assert classify_diff_path(rel_path) == "other"


# ---------------------------------------------------------------------------
# validate_red_transition_diff — git integration
# ---------------------------------------------------------------------------


def _mk_task_paths(project_dir: Path) -> _FakeTaskPaths:
    """Minimal stand-in for TaskPaths — validate_red_transition_diff only
    needs project_dir and task_dir for its diff scan."""
    task_dir = project_dir / ".theking" / "workflows" / "demo" / "sprints" / "s" / "tasks" / "TASK-001-x"
    task_dir.mkdir(parents=True, exist_ok=True)
    return _FakeTaskPaths(task_dir=task_dir, project_dir=project_dir)


def _stage(project_dir: Path, rel: str, content: str = "x") -> None:
    p = project_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(["add", rel], project_dir)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_new_task_rejects_production_in_staged(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    _stage(tmp_path, "scripts/new_feature.py", "def foo(): pass\n")

    with pytest.raises(WorkflowError, match=r"(?is)(production|red|stash)"):
        validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_new_task_rejects_production_in_head_commit(tmp_path: Path) -> None:
    """Even if nothing is staged now, the most recent commit containing
    production code (the 'stash to hide, commit red, then stash pop'
    attack from sprint-017 TASK-001) must still be caught."""
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    # simulate: author wrote impl + tests, committed impl, now wants red
    _stage(tmp_path, "scripts/secret_impl.py", "def impl(): return 42\n")
    _git(["commit", "--quiet", "-m", "sneaky impl"], tmp_path)

    with pytest.raises(WorkflowError, match=r"(?is)(production|recent commit|HEAD)"):
        validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_new_task_accepts_tests_only_staged(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    _stage(tmp_path, "tests/test_new.py", "def test_x(): pass\n")
    _stage(tmp_path, ".theking/workflows/demo/sprints/s/tasks/TASK-001-x/spec.md", "# Spec\n")

    # Must not raise — tests + metadata only.
    validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_skeleton_true_bypasses_gate(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    _stage(tmp_path, "scripts/skeleton.py", "class Foo: pass\n")

    # skeleton=True is the compiled-language escape hatch — must pass.
    validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_legacy_task_not_enforced(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    _stage(tmp_path, "scripts/anything.py", "whatever\n")

    # task_is_new=False means legacy — gate must silent-pass.
    validate_red_transition_diff(paths, tmp_path, task_is_new=False, skeleton=False)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_mixed_staged_names_production_path_in_error(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    paths = _mk_task_paths(tmp_path)
    _stage(tmp_path, "tests/test_x.py", "def test_x(): pass\n")
    _stage(tmp_path, "scripts/sneaky.py", "def foo(): return 1\n")

    with pytest.raises(WorkflowError) as exc:
        validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)
    assert "scripts/sneaky.py" in str(exc.value), (
        f"error must name the violating path; got: {exc.value}"
    )


def test_non_git_repo_silent_pass(tmp_path: Path) -> None:
    """tmp_path without .git — must silent-pass, not crash."""
    paths = _mk_task_paths(tmp_path)
    # No _init_repo. Must not raise.
    validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_empty_repo_no_head_silent_pass(tmp_path: Path) -> None:
    """git init but no commits — HEAD does not exist. Must not crash."""
    _git(["init", "--quiet", "-b", "main"], tmp_path)
    paths = _mk_task_paths(tmp_path)
    # No staged changes either.
    validate_red_transition_diff(paths, tmp_path, task_is_new=True, skeleton=False)


# ---------------------------------------------------------------------------
# CLI integration: advance-status planned->red + red-check subcommand
# ---------------------------------------------------------------------------


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKFLOWCTL), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _bootstrap_new_task(tmp_path: Path) -> Path:
    r1 = run_cli(["init-project", "--root", str(tmp_path), "--project-slug", "demo-app"], cwd=tmp_path)
    assert r1.returncode == 0, r1.stderr
    r2 = run_cli(
        ["init-sprint", "--root", str(tmp_path), "--project-slug", "demo-app", "--theme", "foundation"],
        cwd=tmp_path,
    )
    assert r2.returncode == 0, r2.stderr
    r3 = run_cli(
        [
            "init-task",
            "--root", str(tmp_path),
            "--project-slug", "demo-app",
            "--sprint", "sprint-001-foundation",
            "--slug", "demo-task",
            "--title", "Demo",
            "--task-type", "general",
        ],
        cwd=tmp_path,
    )
    assert r3.returncode == 0, r3.stderr
    return (
        tmp_path / "demo-app" / ".theking" / "workflows" / "demo-app"
        / "sprints" / "sprint-001-foundation"
        / "tasks" / "TASK-001-demo-task"
    )


def _fill_spec_and_goal(task_dir: Path) -> None:
    from conftest import populate_handoff_anchor, populate_task_goal

    populate_task_goal(task_dir / "task.md")
    populate_handoff_anchor(task_dir)
    (task_dir / "spec.md").write_text(
        "# Spec\n\n## Scope\n- s\n\n## Non-Goals\n- n\n\n"
        "## Acceptance\n- [ ] a\n  - 验证方式: unit\n  - 证据路径: tests/test.py::test_a\n\n"
        "## Test Plan\n- a\n- b\n- c\n- d\n- e\n\n"
        "## Edge Cases\n- x\n- y\n- z\n",
        encoding="utf-8",
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_cli_advance_status_rejects_mixed_staged(tmp_path: Path) -> None:
    """End-to-end: new task + production code staged → advance-status
    planned→red rejects."""
    _git(["init", "--quiet", "-b", "main"], tmp_path)
    _git(["commit", "--quiet", "--allow-empty", "-m", "root"], tmp_path)
    task_dir = _bootstrap_new_task(tmp_path)
    _fill_spec_and_goal(task_dir)

    project_dir = tmp_path / "demo-app"
    # Stage a production-looking file at the project root.
    _stage(project_dir, "scripts/feature.py", "def feat(): pass\n")

    r_planned = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "planned"], cwd=tmp_path)
    assert r_planned.returncode == 0, r_planned.stderr
    r_red = run_cli(["advance-status", "--task-dir", str(task_dir), "--to-status", "red"], cwd=tmp_path)
    assert r_red.returncode != 0, (
        f"new task with production staged must be rejected; got {r_red.stdout!r} / {r_red.stderr!r}"
    )
    # Error message must name the remediation.
    assert re.search(r"(?i)stash|production|scripts/feature.py", r_red.stderr), r_red.stderr


@pytest.mark.skipif(shutil.which("git") is None, reason="git not in PATH")
def test_red_check_subcommand_exit_codes(tmp_path: Path) -> None:
    """`workflowctl red-check --task-dir <dir>` must be a first-class
    subcommand that exits 0 on clean, != 0 on violation."""
    _git(["init", "--quiet", "-b", "main"], tmp_path)
    _git(["commit", "--quiet", "--allow-empty", "-m", "root"], tmp_path)
    task_dir = _bootstrap_new_task(tmp_path)

    project_dir = tmp_path / "demo-app"

    # Clean: no staged production changes
    r_clean = run_cli(["red-check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r_clean.returncode == 0, r_clean.stderr

    # Violating: stage a production file
    _stage(project_dir, "scripts/bad.py", "def bad(): pass\n")
    r_bad = run_cli(["red-check", "--task-dir", str(task_dir)], cwd=tmp_path)
    assert r_bad.returncode != 0, r_bad.stderr
