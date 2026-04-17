"""Direct unit tests for execution-profile inference + contract validation.

TASK-004 of the kimi-feedback sprint reshapes the default for plain `backend`:
- `backend` alone now infers `backend.cli` (library / in-process code)
- `backend + api` / `backend + service` still infer `backend.http`
- Existing task files with `execution_profile: backend.http` + `task_type: backend`
  must stay valid (backward compat).

These tests talk directly to the validation helpers so they run fast and cover
branches that the full-CLI integration tests would miss.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    infer_execution_profile,
    normalize_task_type,
    task_requires_security_review,
    validate_task_contract,
)

# --- infer_execution_profile: new default for plain `backend` ---


@pytest.mark.parametrize(
    ("raw_task_type", "expected_profile"),
    [
        ("backend", "backend.cli"),  # NEW default: library/in-process
        ("backend,api", "backend.http"),  # api token overrides
        ("backend,service", "backend.http"),  # service token overrides
        ("api", "backend.http"),
        ("service", "backend.http"),
        ("auth", "backend.http"),
        ("input", "backend.http"),
        ("general", "backend.cli"),
        ("tooling", "backend.cli"),
        ("cli", "backend.cli"),
        ("script", "backend.cli"),
        ("job", "backend.job"),
        ("automation", "backend.job"),
        ("frontend", "web.browser"),
        ("ui", "web.browser"),
        ("web", "web.browser"),
        ("e2e", "web.browser"),
    ],
)
def test_infer_execution_profile(raw_task_type: str, expected_profile: str) -> None:
    task_type = normalize_task_type(raw_task_type)
    assert infer_execution_profile(task_type) == expected_profile


# --- validate_task_contract: backward compat ---


@pytest.mark.parametrize(
    ("task_type", "execution_profile"),
    [
        # Brand-new default combination.
        ("backend", "backend.cli"),
        # Backward-compatible: already-written tasks with backend+http stay valid.
        ("backend", "backend.http"),
        ("backend,api", "backend.http"),
        ("service", "backend.http"),
        ("api", "backend.http"),
        ("auth", "web.browser"),
        ("auth", "backend.http"),
        ("frontend", "web.browser"),
        ("job", "backend.job"),
        ("automation", "backend.job"),
        ("general", "backend.cli"),
        ("tooling", "backend.cli"),
    ],
)
def test_validate_task_contract_accepts(task_type: str, execution_profile: str) -> None:
    # Should not raise.
    validate_task_contract(normalize_task_type(task_type), execution_profile)


@pytest.mark.parametrize(
    ("task_type", "execution_profile"),
    [
        ("general", "backend.http"),  # general is a CLI/library token
        ("tooling", "backend.http"),
        ("frontend", "backend.http"),  # frontend wants the browser profile
        ("api", "backend.cli"),  # api implies a server
        ("job", "backend.cli"),
    ],
)
def test_validate_task_contract_rejects(task_type: str, execution_profile: str) -> None:
    with pytest.raises(WorkflowError) as exc:
        validate_task_contract(normalize_task_type(task_type), execution_profile)
    # Contract error should always name the incompatible pair (keyword preserved
    # for any external tooling that greps for it).
    assert "incompatible" in str(exc.value)


# --- requires_security_review derivation stays stable ---


def test_backend_cli_library_task_does_not_require_security_review() -> None:
    """TASK-004 guarantee: a plain `backend` library task (new default) must NOT
    be force-tagged requires_security_review=true. The whole point of switching
    the default away from backend.http is to drop the rubber-stamp security
    review for library code."""
    assert task_requires_security_review("backend", "backend.cli") is False


def test_backend_http_server_task_still_requires_security_review() -> None:
    """But the moment you opt into backend.http, security review comes back on."""
    assert task_requires_security_review("backend", "backend.http") is True
    assert task_requires_security_review("api", "backend.http") is True
    assert task_requires_security_review("service", "backend.http") is True
