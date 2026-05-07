"""sprint-021 TASK-001: static RUNTIME_CAPABILITY_MATRIX + runtime.json state file.

Tests the new ground-floor primitives required by
`.theking/context/design-main-agent-boundary.md` §4 P0-1. Only matrix
definition, runtime-state I/O, and `workflowctl ensure` integration are
covered — validator gates that *consume* the capability (`degraded` /
`main-agent-fallback` branching) belong to sprint-021 段 B and are
out of scope here.

The tests are written *first* (TDD red) before the implementation lands;
the target module `scripts/runtime_state.py` does not exist yet. This
file will fail collection with `ModuleNotFoundError` until TASK-001
green implementation lands.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "workflowctl.py"

# The matrix values below MUST match design §4 P0-1. Tests own the
# contract; drift on either side is a design decision that needs an ADR.
EXPECTED_RUNTIMES = {"claude-code", "codebuddy", "kimi-cli", "copilot", "unknown"}
EXPECTED_CAPTURE_TRUE = {"claude-code", "codebuddy"}
EXPECTED_CAPTURE_FALSE = {"kimi-cli", "copilot", "unknown"}


def _run_cli(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env is not None:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
    )


# --- Matrix shape -----------------------------------------------------


def test_matrix_keys_and_shape() -> None:
    """Acceptance #1: matrix covers 5 runtimes, fields are typed correctly."""
    from scripts.constants import RUNTIME_CAPABILITY_MATRIX

    assert set(RUNTIME_CAPABILITY_MATRIX) == EXPECTED_RUNTIMES

    for key, entry in RUNTIME_CAPABILITY_MATRIX.items():
        assert isinstance(entry, dict), f"{key} entry must be a dict"
        assert "subagent_runtime_capture" in entry, f"{key} missing subagent_runtime_capture"
        assert "lifecycle_hooks" in entry, f"{key} missing lifecycle_hooks"
        assert "tool_names" in entry, f"{key} missing tool_names"
        assert isinstance(entry["subagent_runtime_capture"], bool), (
            f"{key}.subagent_runtime_capture must be bool"
        )
        assert isinstance(entry["lifecycle_hooks"], bool), f"{key}.lifecycle_hooks must be bool"
        assert isinstance(entry["tool_names"], tuple), (
            f"{key}.tool_names must be tuple (immutable, design §4 P0-1)"
        )

    for key in EXPECTED_CAPTURE_TRUE:
        assert RUNTIME_CAPABILITY_MATRIX[key]["subagent_runtime_capture"] is True
    for key in EXPECTED_CAPTURE_FALSE:
        assert RUNTIME_CAPABILITY_MATRIX[key]["subagent_runtime_capture"] is False


def test_matrix_has_default_unknown_key() -> None:
    """`unknown` must be the canonical fallback; explicit default constant required."""
    from scripts.constants import DEFAULT_RUNTIME_KEY, RUNTIME_CAPABILITY_MATRIX

    assert DEFAULT_RUNTIME_KEY == "unknown"
    assert DEFAULT_RUNTIME_KEY in RUNTIME_CAPABILITY_MATRIX
    # unknown must be the most-restricted flavor: no capture, no hooks.
    unknown = RUNTIME_CAPABILITY_MATRIX[DEFAULT_RUNTIME_KEY]
    assert unknown["subagent_runtime_capture"] is False
    assert unknown["lifecycle_hooks"] is False


# --- detect_runtime_key -----------------------------------------------


def test_detect_runtime_key_missing_env() -> None:
    """Acceptance #2: missing env var -> 'unknown'."""
    from scripts.runtime_state import detect_runtime_key

    assert detect_runtime_key({}) == "unknown"


def test_detect_runtime_key_empty_env() -> None:
    """Acceptance #2: empty / whitespace env var -> 'unknown' (strict)."""
    from scripts.runtime_state import detect_runtime_key

    assert detect_runtime_key({"THEKING_RUNTIME": ""}) == "unknown"
    assert detect_runtime_key({"THEKING_RUNTIME": "   "}) == "unknown"


def test_detect_runtime_key_unknown_value_falls_back() -> None:
    """Unknown runtime name falls back rather than raising — user may set a
    name theking does not know yet, and we still want `ensure` to succeed."""
    from scripts.runtime_state import detect_runtime_key

    assert detect_runtime_key({"THEKING_RUNTIME": "some-new-ide"}) == "unknown"


def test_detect_runtime_key_case_sensitive() -> None:
    """Matrix keys are lowercase; we do NOT canonicalize casing to avoid
    accidental matching on `CodeBuddy` vs `codebuddy`. Match strictly."""
    from scripts.runtime_state import detect_runtime_key

    # Design §4 P0-1 uses lowercase canonical keys; uppercase is not matched.
    assert detect_runtime_key({"THEKING_RUNTIME": "CodeBuddy"}) == "unknown"
    assert detect_runtime_key({"THEKING_RUNTIME": "codebuddy"}) == "codebuddy"


def test_detect_runtime_key_known_values() -> None:
    """All documented runtimes round-trip through detect."""
    from scripts.runtime_state import detect_runtime_key

    for runtime in EXPECTED_RUNTIMES:
        assert detect_runtime_key({"THEKING_RUNTIME": runtime}) == runtime


# --- write_runtime_state ---------------------------------------------


def test_write_runtime_state_initial_write(tmp_path: Path) -> None:
    """Acceptance #3 (first write): state file contains matrix fields + locked_at."""
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    (project_dir / ".theking" / "state").mkdir(parents=True)
    state_path = write_runtime_state(project_dir, "codebuddy")

    assert state_path == project_dir / ".theking" / "state" / "runtime.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["runtime"] == "codebuddy"
    assert data["subagent_runtime_capture"] is True
    assert data["lifecycle_hooks"] is True
    assert isinstance(data["tool_names"], list)
    assert data["theking_schema_version"] == 1
    assert data["locked_at"].endswith("Z")


def test_write_runtime_state_idempotent(tmp_path: Path) -> None:
    """Acceptance #3 (second write): matches matrix -> no-op (preserve locked_at)."""
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    (project_dir / ".theking" / "state").mkdir(parents=True)
    state_path = write_runtime_state(project_dir, "unknown")
    first_content = state_path.read_text(encoding="utf-8")

    # Second call must not touch the file (especially not refresh locked_at).
    state_path_again = write_runtime_state(project_dir, "unknown")
    assert state_path_again == state_path
    assert state_path.read_text(encoding="utf-8") == first_content


def test_write_runtime_state_rejects_tampered_file(tmp_path: Path) -> None:
    """Acceptance #3 (tamper): hand-edited subagent_runtime_capture -> WorkflowError."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    (project_dir / ".theking" / "state").mkdir(parents=True)
    write_runtime_state(project_dir, "kimi-cli")  # False in matrix
    state_path = project_dir / ".theking" / "state" / "runtime.json"

    tampered = json.loads(state_path.read_text(encoding="utf-8"))
    tampered["subagent_runtime_capture"] = True  # forgery
    state_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(WorkflowError, match="runtime.json"):
        write_runtime_state(project_dir, "kimi-cli")


def test_write_runtime_state_rejects_unknown_matrix_key(tmp_path: Path) -> None:
    """Matrix is closed; writing an undeclared runtime key is a bug in the caller."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    (project_dir / ".theking" / "state").mkdir(parents=True)
    with pytest.raises(WorkflowError, match="RUNTIME_CAPABILITY_MATRIX"):
        write_runtime_state(project_dir, "totally-invented-runtime")


# --- load_runtime_capability -----------------------------------------


def test_load_runtime_capability_missing_file(tmp_path: Path) -> None:
    """Acceptance #4: missing runtime.json -> matrix['unknown'] copy (not mutable alias)."""
    from scripts.constants import RUNTIME_CAPABILITY_MATRIX
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    (project_dir / ".theking").mkdir(parents=True)
    cap = load_runtime_capability(project_dir)

    assert cap["runtime"] == "unknown"
    assert cap["subagent_runtime_capture"] is False
    # Mutation must not leak into the canonical matrix.
    cap["subagent_runtime_capture"] = True
    assert RUNTIME_CAPABILITY_MATRIX["unknown"]["subagent_runtime_capture"] is False


def test_load_runtime_capability_legit_file(tmp_path: Path) -> None:
    """load reads the fields written by write_runtime_state."""
    from scripts.runtime_state import load_runtime_capability, write_runtime_state

    project_dir = tmp_path / "proj"
    (project_dir / ".theking" / "state").mkdir(parents=True)
    write_runtime_state(project_dir, "claude-code")

    cap = load_runtime_capability(project_dir)
    assert cap["runtime"] == "claude-code"
    assert cap["subagent_runtime_capture"] is True
    assert "locked_at" in cap


def test_load_runtime_capability_unknown_key_in_file_rejects(tmp_path: Path) -> None:
    """File was hand-edited to an undocumented runtime key -> WorkflowError."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text(
        json.dumps(
            {
                "runtime": "super-new-ide",
                "subagent_runtime_capture": True,
                "lifecycle_hooks": True,
                "tool_names": [],
                "locked_at": "2026-05-07T00:00:00Z",
                "theking_schema_version": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowError, match="RUNTIME_CAPABILITY_MATRIX"):
        load_runtime_capability(project_dir)


def test_load_runtime_capability_malformed_json_rejects(tmp_path: Path) -> None:
    """Damaged JSON must fail loudly (no silent fallback to unknown)."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkflowError, match="runtime.json"):
        load_runtime_capability(project_dir)


def test_load_runtime_capability_ignores_tampered_capability_values(tmp_path: Path) -> None:
    """finding-001 regression: capability values come from the matrix,
    not from disk. A hand-edit that flips ``subagent_runtime_capture``
    from False to True must be ignored at read-time (the runtime key is
    the only disk-supplied field that decides behaviour)."""
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    tampered = {
        "runtime": "kimi-cli",  # matrix says subagent_runtime_capture=False
        "subagent_runtime_capture": True,  # attacker flip
        "lifecycle_hooks": True,  # attacker flip
        "tool_names": ["Evil"],  # attacker flip
        "locked_at": "2026-05-07T00:00:00Z",
        "theking_schema_version": 1,
    }
    (state_dir / "runtime.json").write_text(
        json.dumps(tampered, indent=2) + "\n", encoding="utf-8"
    )
    cap = load_runtime_capability(project_dir)
    # Matrix wins; file was ignored on all capability fields.
    assert cap["subagent_runtime_capture"] is False
    assert cap["lifecycle_hooks"] is False
    assert cap["tool_names"] == []


def test_load_runtime_capability_rejects_schema_version_mismatch(tmp_path: Path) -> None:
    """finding-005 regression: the RUNTIME_STATE_SCHEMA_VERSION constant
    is enforced, not decorative. Files produced by a future theking
    schema must not be silently consumed by today's loader."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text(
        json.dumps(
            {
                "runtime": "unknown",
                "subagent_runtime_capture": False,
                "lifecycle_hooks": False,
                "tool_names": [],
                "locked_at": "2026-05-07T00:00:00Z",
                "theking_schema_version": 99,  # future version
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowError, match="theking_schema_version"):
        load_runtime_capability(project_dir)


def test_write_runtime_state_rejects_malformed_existing(tmp_path: Path) -> None:
    """finding-004 regression: malformed JSON on the second write path
    must raise, not silently overwrite. (The first-write path has no
    file to parse, so only the second call exercises this.)"""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text("{garbage", encoding="utf-8")
    with pytest.raises(WorkflowError, match="runtime.json"):
        write_runtime_state(project_dir, "unknown")


def test_write_runtime_state_rejects_non_object_top_level(tmp_path: Path) -> None:
    """finding-004 regression: a JSON list (or scalar) at the top level
    must fail rather than be coerced into a dict."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text(
        json.dumps([1, 2, 3]) + "\n", encoding="utf-8"
    )
    with pytest.raises(WorkflowError, match="JSON object"):
        write_runtime_state(project_dir, "unknown")


def test_load_runtime_capability_rejects_non_object_top_level(tmp_path: Path) -> None:
    """finding-004 regression: the load-side also rejects non-dict top-level."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import load_runtime_capability

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime.json").write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="JSON object"):
        load_runtime_capability(project_dir)


def test_write_runtime_state_rejects_symlink(tmp_path: Path) -> None:
    """finding-003 regression: ensure_local_path blocks a pre-planted
    symlink at .theking/state/runtime.json."""
    from scripts.constants import WorkflowError
    from scripts.runtime_state import write_runtime_state

    project_dir = tmp_path / "proj"
    state_dir = project_dir / ".theking" / "state"
    state_dir.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    (state_dir / "runtime.json").symlink_to(target)

    with pytest.raises(WorkflowError):
        write_runtime_state(project_dir, "unknown")


# --- ensure integration ----------------------------------------------


def test_ensure_writes_runtime_state(tmp_path: Path) -> None:
    """Acceptance #5: `workflowctl ensure` produces runtime.json with unknown by default."""
    result = _run_cli(
        [
            "ensure",
            "--project-dir",
            str(tmp_path / "app"),
            "--project-slug",
            "app",
        ],
        cwd=tmp_path,
        env={"THEKING_RUNTIME": ""},  # force unknown
    )
    assert result.returncode == 0, result.stderr

    state_path = tmp_path / "app" / ".theking" / "state" / "runtime.json"
    assert state_path.is_file()
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["runtime"] == "unknown"
    assert data["subagent_runtime_capture"] is False


def test_ensure_honours_theking_runtime_env(tmp_path: Path) -> None:
    """ENV-driven runtime identification propagates to runtime.json."""
    result = _run_cli(
        [
            "ensure",
            "--project-dir",
            str(tmp_path / "app"),
            "--project-slug",
            "app",
        ],
        cwd=tmp_path,
        env={"THEKING_RUNTIME": "codebuddy"},
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(
        (tmp_path / "app" / ".theking" / "state" / "runtime.json").read_text(encoding="utf-8")
    )
    assert data["runtime"] == "codebuddy"
    assert data["subagent_runtime_capture"] is True


def test_ensure_is_idempotent_for_runtime_state(tmp_path: Path) -> None:
    """Second ensure must not rewrite runtime.json when matrix still matches."""
    for _ in range(2):
        result = _run_cli(
            [
                "ensure",
                "--project-dir",
                str(tmp_path / "app"),
                "--project-slug",
                "app",
            ],
            cwd=tmp_path,
            env={"THEKING_RUNTIME": "unknown"},
        )
        assert result.returncode == 0, result.stderr

    state_path = tmp_path / "app" / ".theking" / "state" / "runtime.json"
    first_contents = state_path.read_text(encoding="utf-8")

    # Third call after on-disk content is already aligned: still no diff.
    result = _run_cli(
        [
            "ensure",
            "--project-dir",
            str(tmp_path / "app"),
            "--project-slug",
            "app",
        ],
        cwd=tmp_path,
        env={"THEKING_RUNTIME": "unknown"},
    )
    assert result.returncode == 0, result.stderr
    assert state_path.read_text(encoding="utf-8") == first_contents
