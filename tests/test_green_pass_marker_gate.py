"""sprint-017 TASK-002: require a test-runner PASS marker on green transitions.

The existing gates check evidence volume (substantive chars, sprint-004)
and evidence shape (profile anchors, sprint-017 TASK-001). Neither of
them verifies that the agent actually saw a test runner report PASS.
This gate scans ``verification/<profile>/`` at red->green and
green->in_review and requires a recognisable PASS marker from one of
the supported runners — pytest / go test / jest / vitest / cargo test /
junit / generic. Mixed PASS+FAIL is rejected; "no tests ran" outputs
are rejected.

Mirrors ADR-001's no-opt-out stance and TASK-001's HTML-comment
stripping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    validate_test_pass_marker,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# runner-specific happy paths
# ---------------------------------------------------------------------------


def test_accepts_pytest_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "$ pytest tests -q\n"
        "........................................................................ [100%]\n"
        "569 passed, 2 skipped in 59.23s\n",
    )
    validate_test_pass_marker(tmp_path)


def test_accepts_go_test_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.log",
        "=== RUN   TestSomething\n"
        "--- PASS: TestSomething (0.01s)\n"
        "ok  \tgithub.com/fisher/pkg\t0.012s\n"
        "PASS\n",
    )
    validate_test_pass_marker(tmp_path)


def test_accepts_jest_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "jest.log",
        "Test Suites: 12 passed, 12 total\n"
        "Tests:       84 passed, 84 total\n"
        "Snapshots:   0 total\n"
        "Time:        4.2 s\n",
    )
    validate_test_pass_marker(tmp_path)


def test_accepts_vitest_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "vitest.log",
        " ✓ src/foo.test.ts (5 tests) 120ms\n"
        "Test Files  3 passed (3)\n"
        "     Tests  42 passed (42)\n",
    )
    validate_test_pass_marker(tmp_path)


def test_accepts_cargo_test_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "cargo.log",
        "running 12 tests\n"
        "test tests::foo ... ok\n"
        "test tests::bar ... ok\n"
        "\n"
        "test result: ok. 12 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n",
    )
    validate_test_pass_marker(tmp_path)


def test_accepts_junit_pass_output(tmp_path: Path) -> None:
    write(
        tmp_path / "junit.log",
        "[INFO] Running com.example.FooTest\n"
        "[INFO] Tests run: 42, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 1.23 s\n",
    )
    validate_test_pass_marker(tmp_path)


# ---------------------------------------------------------------------------
# rejection cases
# ---------------------------------------------------------------------------


def test_rejects_empty_profile_dir(tmp_path: Path) -> None:
    with pytest.raises(WorkflowError, match=r"(?is)(pass|passed|PASS)"):
        validate_test_pass_marker(tmp_path)


def test_rejects_narrative_without_runner_output(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# Evidence\n"
        "Ran the tests and they looked fine.\n"
        "Everything green.\n",
    )
    with pytest.raises(WorkflowError):
        validate_test_pass_marker(tmp_path)


def test_rejects_zero_tests_ran(tmp_path: Path) -> None:
    """pytest --collect-only with no tests: 'collected 0 items' or
    'no tests ran' must be rejected even though technically a 'passed'
    word may appear elsewhere."""
    write(
        tmp_path / "evidence.md",
        "$ pytest --collect-only\n"
        "collected 0 items\n"
        "no tests ran in 0.01s\n"
        "0 passed, 0 failed\n",
    )
    with pytest.raises(WorkflowError):
        validate_test_pass_marker(tmp_path)


def test_rejects_mixed_pass_and_fail(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "42 passed, 3 failed in 5.21s\n"
        "FAILED tests/test_foo.py::test_bar\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)(fail|failed)"):
        validate_test_pass_marker(tmp_path)


def test_rejects_mixed_pytest_error(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "5 passed, 0 failed, 1 error in 0.5s\n"
        "ERROR tests/test_foo.py - ImportError\n",
    )
    with pytest.raises(WorkflowError):
        validate_test_pass_marker(tmp_path)


def test_fail_in_url_path_does_not_trigger_false_positive(tmp_path: Path) -> None:
    """A FAIL substring inside an unrelated word like 'FAILOVER' in a
    package path must NOT count as a failure signal."""
    write(
        tmp_path / "evidence.log",
        "--- PASS: TestSomething (0.01s)\n"
        "ok  \tgithub.com/fisher/FAILOVER/pkg\t0.012s\n"
        "PASS\n",
    )
    # Should succeed — FAILOVER is not a test-failure anchor.
    validate_test_pass_marker(tmp_path)


def test_rejects_pass_inside_html_comment(tmp_path: Path) -> None:
    """HTML-comment-wrapped PASS must not count (mirrors TASK-001)."""
    write(
        tmp_path / "evidence.md",
        "# Evidence\n"
        "<!-- 569 passed, 2 skipped -->\n"
        "Ran the tests.\n",
    )
    with pytest.raises(WorkflowError):
        validate_test_pass_marker(tmp_path)


def test_case_insensitive_pytest(tmp_path: Path) -> None:
    """Lowercase 'passed' (pytest style) matches."""
    write(tmp_path / "e.md", "1 passed in 0.01s\n")
    validate_test_pass_marker(tmp_path)


def test_case_variant_go_uppercase(tmp_path: Path) -> None:
    """Uppercase 'PASS' (go test style) matches."""
    write(
        tmp_path / "e.log",
        "--- PASS: TestOne (0.00s)\nok\tpkg\t0.001s\n",
    )
    validate_test_pass_marker(tmp_path)


# ---------------------------------------------------------------------------
# robustness
# ---------------------------------------------------------------------------


def test_handles_non_utf8_binary_file_gracefully(tmp_path: Path) -> None:
    """Binary-only profile dir must fail with a clear error, not crash."""
    (tmp_path / "artifact.bin").write_bytes(b"\xff\xfe\x00\x01" * 200)
    with pytest.raises(WorkflowError):
        validate_test_pass_marker(tmp_path)


def test_binary_alongside_valid_evidence_still_passes(tmp_path: Path) -> None:
    """Binary artifact next to real runner output must NOT block
    acceptance — scanner must skip binaries and keep looking."""
    (tmp_path / "screenshot.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024
    )
    write(tmp_path / "pytest.log", "42 passed in 1.2s\n")
    validate_test_pass_marker(tmp_path)


def test_aggregates_across_files(tmp_path: Path) -> None:
    """PASS marker in one file + metadata in another: must accept."""
    write(tmp_path / "smoke.md", "$ pytest -q\n")
    write(tmp_path / "result.log", "569 passed in 59.2s\n")
    validate_test_pass_marker(tmp_path)


# ---------------------------------------------------------------------------
# error message schema
# ---------------------------------------------------------------------------


def test_error_message_lists_supported_runners(tmp_path: Path) -> None:
    write(tmp_path / "e.md", "no runner output here\n")
    with pytest.raises(WorkflowError) as exc:
        validate_test_pass_marker(tmp_path)
    msg = str(exc.value).lower()
    # The error must cite at least 3 of the supported runner families
    # so the author knows what to paste.
    hits = sum(
        1
        for needle in ("pytest", "go test", "jest", "cargo", "junit")
        if needle in msg
    )
    assert hits >= 3, (
        f"Error message should enumerate supported runners; got: {exc.value}"
    )
    # And name both halves of the expected shape (PASS anchor + no FAIL).
    assert "pass" in msg
