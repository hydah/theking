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
  capability dict to future validators. Missing file returns a *copy*
  of the ``unknown`` matrix entry so callers cannot accidentally
  mutate the canonical table.

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
except ImportError:  # pragma: no cover — dual-import shim, mirrors scaffold.py
    from constants import (
        DEFAULT_RUNTIME_KEY,
        RUNTIME_CAPABILITY_MATRIX,
        RUNTIME_STATE_SCHEMA_VERSION,
        WorkflowError,
    )


RUNTIME_STATE_ENV_VAR = "THEKING_RUNTIME"
RUNTIME_STATE_RELATIVE = Path(".theking") / "state" / "runtime.json"
_CAPABILITY_FIELDS = ("subagent_runtime_capture", "lifecycle_hooks", "tool_names")


def _runtime_state_path(project_dir: Path) -> Path:
    return project_dir / RUNTIME_STATE_RELATIVE


def _iso_now() -> str:
    """UTC timestamp with trailing ``Z`` (project-wide convention)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _canonical_state_payload(runtime_key: str, locked_at: str) -> dict[str, Any]:
    entry = RUNTIME_CAPABILITY_MATRIX[runtime_key]
    # ``tool_names`` is stored as list in JSON (JSON has no tuple); keep
    # iteration order stable so the on-disk file is deterministic.
    return {
        "runtime": runtime_key,
        "subagent_runtime_capture": bool(entry["subagent_runtime_capture"]),
        "lifecycle_hooks": bool(entry["lifecycle_hooks"]),
        "tool_names": list(cast("tuple[str, ...]", entry["tool_names"])),
        "locked_at": locked_at,
        "theking_schema_version": RUNTIME_STATE_SCHEMA_VERSION,
    }


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
    return None


def write_runtime_state(project_dir: Path, runtime_key: str) -> Path:
    """Persist the capability snapshot to ``.theking/state/runtime.json``.

    Semantics:

    - ``runtime_key`` must be a key of :data:`RUNTIME_CAPABILITY_MATRIX`;
      otherwise a :class:`WorkflowError` is raised so bugs in the caller
      surface immediately.
    - If the file does not exist, create it with a fresh ``locked_at``.
    - If the file exists and its fields align with the matrix entry for
      ``runtime_key``, do **not** rewrite it — we want the first
      ``ensure`` to pin the timestamp, and a drift-free second run to
      be a no-op (so repeated ``ensure`` does not dirty the git tree).
    - If the file exists but any ``subagent_runtime_capture`` /
      ``lifecycle_hooks`` / ``tool_names`` field disagrees with the
      matrix, raise ``WorkflowError``. The operator either hand-edited
      the file, or the matrix changed — either way a human should look
      at it before ``ensure`` silently "fixes" it.

    Returns the absolute path written (or validated).
    """
    if runtime_key not in RUNTIME_CAPABILITY_MATRIX:
        raise WorkflowError(
            f"runtime {runtime_key!r} is not listed in RUNTIME_CAPABILITY_MATRIX; "
            f"allowed keys: {sorted(RUNTIME_CAPABILITY_MATRIX)}"
        )

    state_path = _runtime_state_path(project_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    if state_path.exists():
        try:
            existing_raw = state_path.read_text(encoding="utf-8")
            existing = json.loads(existing_raw)
        except json.JSONDecodeError as error:
            raise WorkflowError(
                f"{state_path}: runtime.json is not valid JSON ({error.msg}). "
                "Delete the file and re-run `workflowctl ensure` after verifying "
                "no local customization is worth preserving."
            ) from error
        if not isinstance(existing, dict):
            raise WorkflowError(
                f"{state_path}: runtime.json must contain a JSON object at the top level."
            )
        drift = _compare_capability_fields(existing, runtime_key)
        if drift is not None:
            raise WorkflowError(
                f"{state_path}: {drift}. "
                "runtime capability is a static table — hand-editing runtime.json "
                "is not supported. If the matrix was updated intentionally, "
                "delete runtime.json and re-run `workflowctl ensure`."
            )
        # Matches on every field we care about; leave the file alone so
        # locked_at stays pinned to the first ensure.
        return state_path

    payload = _canonical_state_payload(runtime_key, _iso_now())
    state_path.write_text(_render_state_json(payload), encoding="utf-8")
    return state_path


def load_runtime_capability(project_dir: Path) -> dict[str, Any]:
    """Read the capability snapshot back as a dict.

    - If ``runtime.json`` is missing, return a *copy* of the ``unknown``
      matrix entry plus ``runtime="unknown"`` and no ``locked_at``.
      Callers must not mutate their result expecting changes to
      propagate — the returned dict is freshly constructed.
    - If the file exists but names an unknown runtime key, raise
      ``WorkflowError``. Silent fallback to ``unknown`` would mask a
      real problem (someone shipped an unsupported runtime name and
      expects behaviour that isn't there).
    - If the file is malformed JSON, raise so the operator notices.

    The result always contains ``runtime`` / ``subagent_runtime_capture``
    / ``lifecycle_hooks`` / ``tool_names``; ``locked_at`` and
    ``theking_schema_version`` are present only when the file exists.
    """
    state_path = _runtime_state_path(project_dir)
    if not state_path.exists():
        entry = RUNTIME_CAPABILITY_MATRIX[DEFAULT_RUNTIME_KEY]
        return {
            "runtime": DEFAULT_RUNTIME_KEY,
            "subagent_runtime_capture": bool(entry["subagent_runtime_capture"]),
            "lifecycle_hooks": bool(entry["lifecycle_hooks"]),
            "tool_names": list(cast("tuple[str, ...]", entry["tool_names"])),
        }

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise WorkflowError(
            f"{state_path}: runtime.json is not valid JSON ({error.msg}). "
            "Repair the file or delete it and re-run `workflowctl ensure`."
        ) from error
    if not isinstance(data, dict):
        raise WorkflowError(
            f"{state_path}: runtime.json must contain a JSON object at the top level."
        )
    runtime_key = data.get("runtime")
    if runtime_key not in RUNTIME_CAPABILITY_MATRIX:
        raise WorkflowError(
            f"{state_path}: runtime={runtime_key!r} is not listed in "
            f"RUNTIME_CAPABILITY_MATRIX (allowed: {sorted(RUNTIME_CAPABILITY_MATRIX)}). "
            "Either update the matrix via an ADR or delete runtime.json and "
            "re-run `workflowctl ensure`."
        )
    # Return a fresh copy so callers that mutate do not corrupt the file
    # image and do not alias the JSON-parsed dict.
    return {
        "runtime": runtime_key,
        "subagent_runtime_capture": bool(data.get("subagent_runtime_capture")),
        "lifecycle_hooks": bool(data.get("lifecycle_hooks")),
        "tool_names": list(data.get("tool_names") or []),
        "locked_at": data.get("locked_at"),
        "theking_schema_version": data.get("theking_schema_version"),
    }


def detect_and_write_runtime_state(project_dir: Path, env: Mapping[str, str] | None = None) -> Path:
    """Convenience wrapper used by ``workflowctl ensure``.

    Separate from :func:`write_runtime_state` so unit tests can target
    the pure writer without going through ``os.environ``.
    """
    runtime_key = detect_runtime_key(env if env is not None else os.environ)
    return write_runtime_state(project_dir, runtime_key)
