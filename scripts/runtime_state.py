"""Runtime-state persistence for the main-agent boundary architecture.

sprint-021 TASK-001 (design-main-agent-boundary §4 P0-1).

This module is the *ground floor* of the theking main-agent-boundary
work. It provides three responsibilities, and nothing else:

- ``detect_runtime_key`` — classify the current runtime using the
  ``THEKING_RUNTIME`` environment variable. We never auto-probe
  (sniffing process names, scanning ``$PATH``, reading tool inventory),
  because auto-probing is just another self-report dressed up as
  detection. Callers who want to override tell us explicitly.
- ``write_runtime_state`` — fold the matrix entry for a detected
  runtime into ``.theking/state/runtime.json`` on first run, keep the
  file stable on re-runs, and raise when someone has hand-edited the
  file into disagreement with :data:`RUNTIME_CAPABILITY_MATRIX`.
- ``load_runtime_capability`` — read the file back and expose the
  capability dict to future validators. The capability *values*
  always come from :data:`RUNTIME_CAPABILITY_MATRIX`, never from the
  file — the file only supplies the runtime *key*, ``locked_at``, and
  ``theking_schema_version``. This is how the table stays the
  authoritative source: a hand-edited ``subagent_runtime_capture``
  would be ignored at read-time even if it slipped past the write-time
  tamper check.

The write-boundary hook, the HMAC machinery, and any validator that
actually *consumes* ``subagent_runtime_capture`` live in sprint-021
段 B (design §4 P0-2 / P0-3 / P0-4). Do not reach into those concerns
from here; this module has to stay dead-simple to audit.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

try:
    from .constants import (
        DEFAULT_RUNTIME_KEY,
        RUNTIME_CAPABILITY_MATRIX,
        RUNTIME_STATE_SCHEMA_VERSION,
        WorkflowError,
    )
    from .validation import ensure_local_path
except ImportError:  # pragma: no cover — dual-import shim, mirrors scaffold.py
    from constants import (
        DEFAULT_RUNTIME_KEY,
        RUNTIME_CAPABILITY_MATRIX,
        RUNTIME_STATE_SCHEMA_VERSION,
        WorkflowError,
    )
    from validation import ensure_local_path


RUNTIME_STATE_ENV_VAR = "THEKING_RUNTIME"
RUNTIME_STATE_RELATIVE = Path(".theking") / "state" / "runtime.json"
_CAPABILITY_FIELDS = ("subagent_runtime_capture", "lifecycle_hooks", "tool_names")

# Pointer used in WorkflowError messages. We deliberately do NOT tell the
# operator to "delete the file and re-run ensure" for tamper / unknown-key
# paths — that would be a governance-leaking escape hatch (design §4 P0-8
# and the finding-002 outcome of TASK-001 code-review-round-001). Point
# them at the design doc + ADR-008 instead so the correct response is
# "file an ADR / update the matrix", not "bypass the guard".
_BOUNDARY_DESIGN_REFERENCE = (
    ".theking/context/design-main-agent-boundary.md §4 P0-1 + ADR-008"
)


def _runtime_state_path(project_dir: Path) -> Path:
    return project_dir / RUNTIME_STATE_RELATIVE


def _iso_now() -> str:
    """UTC timestamp with trailing ``Z`` (project-wide convention)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_state_path_safe(project_dir: Path) -> Path:
    """Compute the state file path and reject symlink traversal.

    Mirrors the pattern used across ``scripts/scaffold.py``: every state
    write in the theking tree funnels through ``ensure_local_path`` so a
    pre-planted symlink (e.g. `.theking/state/runtime.json ->
    ~/.ssh/authorized_keys`) cannot be followed by ``write_runtime_state``
    or ``load_runtime_capability``.
    """
    state_path = _runtime_state_path(project_dir)
    ensure_local_path(state_path, project_dir, ".theking/state/runtime.json")
    if state_path.is_symlink():
        raise WorkflowError(
            f"{state_path}: runtime.json must not be a symlink. "
            f"This file is owned by `workflowctl ensure` and must live inside "
            f"the project tree as a regular file. See {_BOUNDARY_DESIGN_REFERENCE}."
        )
    return state_path


def detect_runtime_key(env: Mapping[str, str]) -> str:
    """Classify the runtime from environment variables.

    Matching rules are strict on purpose:

    - Missing / empty / whitespace-only → :data:`DEFAULT_RUNTIME_KEY`.
    - Case-sensitive exact match against :data:`RUNTIME_CAPABILITY_MATRIX`
      keys. ``CodeBuddy`` is rejected — only ``codebuddy`` is a canonical
      key. Callers who are unsure should pick ``unknown`` rather than
      guess casing.
    - Anything else that does not appear in the matrix → fallback.
      We fall back (rather than raise) so an operator who sets
      ``THEKING_RUNTIME=my-new-ide`` still gets a usable ``ensure``.

    Returns a matrix key guaranteed to be present in
    :data:`RUNTIME_CAPABILITY_MATRIX`.
    """
    raw = env.get(RUNTIME_STATE_ENV_VAR)
    if raw is None:
        return DEFAULT_RUNTIME_KEY
    candidate = raw.strip()
    if not candidate:
        return DEFAULT_RUNTIME_KEY
    if candidate in RUNTIME_CAPABILITY_MATRIX:
        return candidate
    return DEFAULT_RUNTIME_KEY


def _matrix_view(runtime_key: str) -> dict[str, Any]:
    """Return a freshly-constructed dict that mirrors the matrix entry
    for ``runtime_key``. Immutable fields are deep-copied so mutation
    by the caller cannot leak back into :data:`RUNTIME_CAPABILITY_MATRIX`."""
    entry = RUNTIME_CAPABILITY_MATRIX[runtime_key]
    return {
        "runtime": runtime_key,
        "subagent_runtime_capture": bool(entry["subagent_runtime_capture"]),
        "lifecycle_hooks": bool(entry["lifecycle_hooks"]),
        "tool_names": list(cast("tuple[str, ...]", entry["tool_names"])),
    }


def _canonical_state_payload(runtime_key: str, locked_at: str) -> dict[str, Any]:
    payload = _matrix_view(runtime_key)
    payload["locked_at"] = locked_at
    payload["theking_schema_version"] = RUNTIME_STATE_SCHEMA_VERSION
    return payload


def _render_state_json(payload: dict[str, Any]) -> str:
    # ``ensure_ascii=False`` keeps the file human-readable; the trailing
    # newline matches theking convention (see scaffold.py).
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _compare_capability_fields(existing: dict[str, Any], runtime_key: str) -> str | None:
    """Return a human-readable reason when ``existing`` disagrees with
    the matrix entry for ``runtime_key``, or ``None`` when they match."""
    entry = RUNTIME_CAPABILITY_MATRIX[runtime_key]
    if existing.get("runtime") != runtime_key:
        return (
            f"runtime.json has runtime={existing.get('runtime')!r} "
            f"but caller requested {runtime_key!r}"
        )
    for field in _CAPABILITY_FIELDS:
        expected = entry[field]
        observed = existing.get(field)
        if field == "tool_names":
            expected_list = list(cast("tuple[str, ...]", expected))
            observed_list = list(observed) if isinstance(observed, (list, tuple)) else None
            if observed_list != expected_list:
                return (
                    f"runtime.json has tool_names={observed!r} "
                    f"but RUNTIME_CAPABILITY_MATRIX[{runtime_key!r}] "
                    f"requires {expected_list!r}"
                )
            continue
        if observed != expected:
            return (
                f"runtime.json has {field}={observed!r} "
                f"but RUNTIME_CAPABILITY_MATRIX[{runtime_key!r}] "
                f"requires {expected!r}"
            )
    schema_version = existing.get("theking_schema_version")
    if schema_version != RUNTIME_STATE_SCHEMA_VERSION:
        return (
            f"runtime.json has theking_schema_version={schema_version!r} "
            f"but this theking installation expects "
            f"{RUNTIME_STATE_SCHEMA_VERSION!r}"
        )
    return None


def write_runtime_state(project_dir: Path, runtime_key: str) -> Path:
    """Persist the capability snapshot to ``.theking/state/runtime.json``.

    Semantics:

    - ``runtime_key`` must be a key of :data:`RUNTIME_CAPABILITY_MATRIX`;
      otherwise a :class:`WorkflowError` is raised so bugs in the caller
      surface immediately.
    - If the file does not exist, create it with a fresh ``locked_at``.
    - If the file exists and its fields align with the matrix entry for
      ``runtime_key`` and the schema version matches, do **not** rewrite
      it — we want the first ``ensure`` to pin the timestamp, and a
      drift-free second run to be a no-op (so repeated ``ensure`` does
      not dirty the git tree).
    - If the file exists but any ``subagent_runtime_capture`` /
      ``lifecycle_hooks`` / ``tool_names`` / ``theking_schema_version``
      field disagrees with the matrix, raise ``WorkflowError``. The
      operator either hand-edited the file or the matrix changed — a
      human must triage before ``ensure`` silently "fixes" it. The error
      message points at the design doc, not at a workaround command,
      because this boundary is what the whole main-agent-boundary
      sprint is built to defend (design §4 P0-8).

    Returns the absolute path written (or validated).
    """
    if runtime_key not in RUNTIME_CAPABILITY_MATRIX:
        raise WorkflowError(
            f"runtime {runtime_key!r} is not listed in RUNTIME_CAPABILITY_MATRIX; "
            f"allowed keys: {sorted(RUNTIME_CAPABILITY_MATRIX)}. "
            f"Extending the matrix requires an ADR — see {_BOUNDARY_DESIGN_REFERENCE}."
        )

    state_path = _ensure_state_path_safe(project_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    if state_path.exists():
        try:
            existing_raw = state_path.read_text(encoding="utf-8")
            existing = json.loads(existing_raw)
        except json.JSONDecodeError as error:
            raise WorkflowError(
                f"{state_path}: runtime.json is not valid JSON ({error.msg}). "
                f"This file is owned by `workflowctl ensure`; if it is corrupted "
                f"from an interrupted write, repair it to match the "
                f"RUNTIME_CAPABILITY_MATRIX entry for the current runtime "
                f"({runtime_key!r}) and commit. See {_BOUNDARY_DESIGN_REFERENCE}."
            ) from error
        if not isinstance(existing, dict):
            raise WorkflowError(
                f"{state_path}: runtime.json must contain a JSON object at the top level. "
                f"See {_BOUNDARY_DESIGN_REFERENCE} for the canonical shape."
            )
        drift = _compare_capability_fields(existing, runtime_key)
        if drift is not None:
            raise WorkflowError(
                f"{state_path}: {drift}. "
                f"runtime.json is authoritative only because `workflowctl ensure` "
                f"writes it from the static RUNTIME_CAPABILITY_MATRIX. "
                f"Hand-editing this file is unsupported; if the matrix needs to "
                f"change, file an ADR that covers the migration path. "
                f"See {_BOUNDARY_DESIGN_REFERENCE}."
            )
        # Matches on every field we care about; leave the file alone so
        # locked_at stays pinned to the first ensure.
        return state_path

    payload = _canonical_state_payload(runtime_key, _iso_now())
    state_path.write_text(_render_state_json(payload), encoding="utf-8")
    return state_path


def load_runtime_capability(project_dir: Path) -> dict[str, Any]:
    """Read the capability snapshot back as a dict.

    Trust model:

    - The ``runtime`` key is the only file-supplied field that decides
      behaviour; every capability value (``subagent_runtime_capture`` /
      ``lifecycle_hooks`` / ``tool_names``) is resolved from
      :data:`RUNTIME_CAPABILITY_MATRIX` against the key at read time.
      A hand-edit that flips ``subagent_runtime_capture`` in the file
      is therefore ignored — read-time still returns the matrix value.
      This closes the finding-001 gap from TASK-001 code-review-round-001:
      we can no longer be fooled by on-disk tampering between ensure
      runs.
    - Schema-version mismatch is rejected so future migrations cannot
      accidentally consume stale snapshots.
    - Missing ``runtime.json`` returns a :func:`_matrix_view` of the
      ``unknown`` runtime. The returned dict is freshly constructed on
      every call so callers mutating their result cannot leak into
      ``RUNTIME_CAPABILITY_MATRIX``.
    - Malformed JSON, non-dict top level, and unknown-runtime key all
      raise :class:`WorkflowError`. Silent fallback would mask the
      kinds of local edits we want flagged.
    """
    state_path = _ensure_state_path_safe(project_dir)
    if not state_path.exists():
        return _matrix_view(DEFAULT_RUNTIME_KEY)

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError(
            f"{state_path}: runtime.json is not valid JSON ({error.msg}). "
            f"Repair the file to match the RUNTIME_CAPABILITY_MATRIX entry "
            f"for the current runtime; see {_BOUNDARY_DESIGN_REFERENCE}."
        ) from error
    if not isinstance(data, dict):
        raise WorkflowError(
            f"{state_path}: runtime.json must contain a JSON object at the top level. "
            f"See {_BOUNDARY_DESIGN_REFERENCE} for the canonical shape."
        )
    runtime_key = data.get("runtime")
    if runtime_key not in RUNTIME_CAPABILITY_MATRIX:
        raise WorkflowError(
            f"{state_path}: runtime={runtime_key!r} is not listed in "
            f"RUNTIME_CAPABILITY_MATRIX (allowed: {sorted(RUNTIME_CAPABILITY_MATRIX)}). "
            f"Extending the matrix requires an ADR; see {_BOUNDARY_DESIGN_REFERENCE}."
        )

    schema_version = data.get("theking_schema_version")
    if schema_version != RUNTIME_STATE_SCHEMA_VERSION:
        raise WorkflowError(
            f"{state_path}: theking_schema_version={schema_version!r} but "
            f"this theking installation expects {RUNTIME_STATE_SCHEMA_VERSION!r}. "
            f"A schema bump must be accompanied by a migration ADR; "
            f"see {_BOUNDARY_DESIGN_REFERENCE}."
        )

    # Capability values come from the matrix, not from disk. Attach the
    # file-supplied metadata (locked_at / schema version) on top.
    view = _matrix_view(runtime_key)
    view["locked_at"] = data.get("locked_at")
    view["theking_schema_version"] = schema_version
    return view


def detect_and_write_runtime_state(project_dir: Path, env: Mapping[str, str] | None = None) -> Path:
    """Convenience wrapper used by ``workflowctl ensure``.

    Separate from :func:`write_runtime_state` so unit tests can target
    the pure writer without going through ``os.environ``.
    """
    runtime_key = detect_runtime_key(env if env is not None else os.environ)
    return write_runtime_state(project_dir, runtime_key)
