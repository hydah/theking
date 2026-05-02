"""sprint-017 TASK-001: per-profile evidence schema gate.

The existing ``has_substantive_verification_evidence`` only checks that a
profile dir carries >= 40 substantive characters. That keeps out pure
placeholders but not "40 characters of prose with no actual command or
HTTP status line". This gate adds a sibling check that requires the
evidence to contain profile-specific anchors:

- backend.cli: a command anchor (``$ ...`` / ``Command:``) + an exit anchor
  (``Exit:`` / ``exit code`` / ``returncode`` / ``Status:``)
- backend.http: an HTTP method verb line + a 3-digit status code line
- backend.job: a start anchor (``ran`` / ``started`` / ``Invoked``) + a
  completion anchor (``completed`` / ``finished`` / ``done``)
- web.browser: >= 1 binary artifact >= 512B OR a markdown image reference
  that resolves to such a file

Same stance as ADR-001: no ``--skip`` flag, clear error messages naming
the missing anchor + profile.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from constants import WorkflowError  # noqa: E402
from validation import (  # noqa: E402
    PROFILE_SCHEMA_MIN_BINARY_BYTES,
    has_substantive_verification_evidence,
    validate_profile_evidence_shape,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_png(path: Path, size: int) -> None:
    """Write a real PNG file of approximately ``size`` bytes.

    Header bytes are the canonical PNG signature so magic-byte detection
    works; the rest is junk padding that still passes the size floor.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    png_signature = b"\x89PNG\r\n\x1a\n"
    payload = png_signature + b"\x00" * max(0, size - len(png_signature))
    path.write_bytes(payload)


def write_fake_png(path: Path, size: int) -> None:
    """Write a file with .png extension but WRONG magic bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a png" + b"\x00" * max(0, size - 9))


# ---------------------------------------------------------------------------
# backend.cli — command anchor
# ---------------------------------------------------------------------------


def test_backend_cli_accepts_dollar_prefix_and_exit(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# smoke\n"
        "$ workflowctl check --task-dir X\n"
        "OK /path/to/task\n"
        "Exit: 0\n",
    )
    # Should not raise.
    validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_backend_cli_accepts_command_colon_prefix(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Command: pytest tests -q\n"
        "569 passed, 2 skipped in 59.23s\n"
        "exit code 0\n",
    )
    validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_backend_cli_rejects_missing_command_anchor(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# smoke\n"
        "Ran pytest and it was fine.\n"
        "Exit: 0\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.cli.*command"):
        validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_backend_cli_rejects_missing_exit_anchor(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# smoke\n"
        "$ pytest tests -q\n"
        "All tests seemed to pass.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.cli.*(exit|status|returncode)"):
        validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_backend_cli_command_inside_html_comment_does_not_count(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# smoke\n"
        "<!-- Command: pretend-cmd\n"
        "     Exit: 0 -->\n"
        "This is prose without anchors.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.cli"):
        validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_backend_cli_case_insensitive_anchors(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "COMMAND: make test\n"
        "RETURNCODE: 0\n",
    )
    # Both anchors present in uppercase forms — must accept.
    validate_profile_evidence_shape(tmp_path, "backend.cli")


# ---------------------------------------------------------------------------
# backend.http — method + status
# ---------------------------------------------------------------------------


def test_backend_http_accepts_method_and_status(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "GET /api/users HTTP/1.1\n"
        "Host: localhost:8080\n"
        "\n"
        "HTTP/1.1 200 OK\n"
        "Content-Type: application/json\n",
    )
    validate_profile_evidence_shape(tmp_path, "backend.http")


def test_backend_http_accepts_curl_verbose_style(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "> POST /v1/sessions HTTP/1.1\n"
        "> Content-Length: 42\n"
        "< HTTP/1.1 201 Created\n",
    )
    validate_profile_evidence_shape(tmp_path, "backend.http")


def test_backend_http_rejects_missing_method(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Request hit the service and it returned HTTP 200.\n"
        "Response body: {\"ok\": true}\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.http.*method"):
        validate_profile_evidence_shape(tmp_path, "backend.http")


def test_backend_http_rejects_missing_status_code(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "GET /foo HTTP/1.1\n"
        "Made a request, server replied with OK.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.http.*status"):
        validate_profile_evidence_shape(tmp_path, "backend.http")


def test_backend_http_verb_in_url_does_not_count(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Fetched https://api.example.com/GET/items/42\n"
        "HTTP/1.1 200 OK\n",
    )
    # "GET" appears inside URL path only, not a method anchor.
    with pytest.raises(WorkflowError, match=r"(?is)backend\.http.*method"):
        validate_profile_evidence_shape(tmp_path, "backend.http")


# ---------------------------------------------------------------------------
# backend.job — started + completed
# ---------------------------------------------------------------------------


def test_backend_job_accepts_started_and_completed(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Job started at 2026-05-02 18:30.\n"
        "Processed 420 rows.\n"
        "Job completed without errors.\n",
    )
    validate_profile_evidence_shape(tmp_path, "backend.job")


def test_backend_job_rejects_missing_start_anchor(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Background worker finished.\n"
        "It completed all tasks.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.job.*(start|ran|invoked)"):
        validate_profile_evidence_shape(tmp_path, "backend.job")


def test_backend_job_rejects_missing_completion_anchor(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "Invoked the worker.\n"
        "It started processing.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)backend\.job.*(complete|finish|done)"):
        validate_profile_evidence_shape(tmp_path, "backend.job")


# ---------------------------------------------------------------------------
# web.browser — binary artifact OR resolvable markdown reference
# ---------------------------------------------------------------------------


def test_web_browser_accepts_real_png_artifact(tmp_path: Path) -> None:
    write_png(tmp_path / "screenshot.png", size=2048)
    validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_accepts_markdown_reference_to_real_artifact(
    tmp_path: Path,
) -> None:
    write_png(tmp_path / "after-login.png", size=1024)
    write(
        tmp_path / "evidence.md",
        "# Login flow smoke\n"
        "![After login](./after-login.png)\n",
    )
    validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_rejects_without_any_artifact(tmp_path: Path) -> None:
    write(
        tmp_path / "evidence.md",
        "# smoke\n"
        "Navigated to /login and it worked.\n"
        "Looked fine in chromium, firefox, webkit.\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)web\.browser.*(artifact|screenshot|binary)"):
        validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_rejects_fake_png_by_magic_byte(tmp_path: Path) -> None:
    # File has .png extension and > 512B but wrong magic bytes.
    write_fake_png(tmp_path / "fake.png", size=1024)
    with pytest.raises(WorkflowError, match=r"(?is)web\.browser"):
        validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_rejects_undersized_png(tmp_path: Path) -> None:
    # Real PNG header but total size < floor.
    write_png(tmp_path / "tiny.png", size=PROFILE_SCHEMA_MIN_BINARY_BYTES - 1)
    with pytest.raises(WorkflowError, match=r"(?is)web\.browser"):
        validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_rejects_markdown_reference_to_missing_file(
    tmp_path: Path,
) -> None:
    write(
        tmp_path / "evidence.md",
        "![missing](./not-there.png)\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)web\.browser"):
        validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_rejects_markdown_reference_to_undersized_file(
    tmp_path: Path,
) -> None:
    # Existing file that's too small.
    (tmp_path / "tiny.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
    write(
        tmp_path / "evidence.md",
        "![tiny](./tiny.png)\n",
    )
    with pytest.raises(WorkflowError, match=r"(?is)web\.browser"):
        validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_accepts_webm_and_mp4_and_pdf(tmp_path: Path) -> None:
    # WebM signature begins with EBML header 0x1A 0x45 0xDF 0xA3
    (tmp_path / "trace.webm").write_bytes(
        b"\x1a\x45\xdf\xa3" + b"\x00" * 1024
    )
    validate_profile_evidence_shape(tmp_path, "web.browser")


def test_web_browser_accepts_webp(tmp_path: Path) -> None:
    # WebP: "RIFF" + 4-byte size + "WEBP" + VP8 chunk (omitted here).
    payload = b"RIFF" + (1024).to_bytes(4, "little") + b"WEBP" + b"\x00" * 1024
    (tmp_path / "screenshot.webp").write_bytes(payload)
    validate_profile_evidence_shape(tmp_path, "web.browser")


# ---------------------------------------------------------------------------
# error message quality
# ---------------------------------------------------------------------------


def test_error_messages_name_anchor_and_profile(tmp_path: Path) -> None:
    write(tmp_path / "evidence.md", "no anchors here at all\n")
    with pytest.raises(WorkflowError) as exc:
        validate_profile_evidence_shape(tmp_path, "backend.cli")
    msg = str(exc.value)
    assert "backend.cli" in msg, f"error must name the profile: {msg}"
    assert "command" in msg.lower() or "$" in msg, (
        f"error must name the missing anchor: {msg}"
    )


def test_error_message_suggests_remediation(tmp_path: Path) -> None:
    write(tmp_path / "evidence.md", "bare prose without anchors\n")
    with pytest.raises(WorkflowError) as exc:
        validate_profile_evidence_shape(tmp_path, "backend.http")
    msg = str(exc.value)
    # Remediation hint: author should know which anchor families are accepted.
    assert "method" in msg.lower() or "status" in msg.lower(), msg


# ---------------------------------------------------------------------------
# interaction with existing gates
# ---------------------------------------------------------------------------


def test_shape_gate_does_not_break_substantive_check(tmp_path: Path) -> None:
    """Both helpers must be independently callable on the same dir."""
    write(
        tmp_path / "evidence.md",
        "Command: pytest -q\n" + "Exit: 0\n" + "x" * 60,
    )
    assert has_substantive_verification_evidence(tmp_path) is True
    validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_shape_gate_handles_non_utf8_files_gracefully(tmp_path: Path) -> None:
    """Binary-only profile dir with no text markdown should fail shape gate
    with a clear error, not crash on UnicodeDecodeError."""
    (tmp_path / "blob.bin").write_bytes(b"\xff\xfe\x00\x01" * 200)
    with pytest.raises(WorkflowError):
        validate_profile_evidence_shape(tmp_path, "backend.cli")


def test_shape_gate_unknown_profile_is_noop(tmp_path: Path) -> None:
    """A profile we have no schema for must not raise — forward compat."""
    write(tmp_path / "evidence.md", "whatever\n" * 10)
    # Unknown profile name must not raise — schema gate is opt-in per profile.
    validate_profile_evidence_shape(tmp_path, "backend.totally-new-profile")
