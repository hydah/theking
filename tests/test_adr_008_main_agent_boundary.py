from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADR_008_PATH = REPO_ROOT / ".theking" / "context" / "adr" / "ADR-008-main-agent-boundary.md"
FOLLOWUPS_PATH = (
    REPO_ROOT
    / ".theking"
    / "workflows"
    / "theking"
    / "sprints"
    / "sprint-021-main-agent-boundary-and-runtime-provenance"
    / "followups.md"
)


def read_adr_008() -> str:
    assert ADR_008_PATH.is_file(), "ADR-008 must exist at .theking/context/adr/ADR-008-main-agent-boundary.md"
    return ADR_008_PATH.read_text(encoding="utf-8")


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def section_body(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL)
    assert match is not None, f"ADR-008 must include section: ## {heading}"
    body = match.group("body").strip()
    assert len(body) > 50, f"ADR-008 section ## {heading} must contain substantive prose"
    return body


def test_adr_008_exists_with_required_sections() -> None:
    text = read_adr_008()

    for heading in (
        "Context",
        "Decision",
        "Bootstrap Exemption",
        "Consequences",
        "Risks And Known Limits",
        "Segment B Followups",
        "Alternatives Considered",
        "Status",
    ):
        section_body(text, heading)


def test_adr_008_cites_predecessor_adrs() -> None:
    normalized = normalize(read_adr_008())

    assert "adr-006" in normalized
    assert "adr-007" in normalized
    assert any(word in normalized for word in ("extends", "builds on", "predecessor"))
    assert "machine" in normalized and ("gate" in normalized or "gated" in normalized)
    assert "audit" in normalized and "trail" in normalized


def test_adr_008_separates_segment_a_from_segment_b() -> None:
    text = read_adr_008()
    segment_a = normalize(section_body(text, "Decision"))
    segment_b = normalize(section_body(text, "Segment B Followups"))

    for token in ("p0-1", "p0-5", "p0-7", "p0-8", "adr-008"):
        assert token in segment_a
    for token in ("p0-2", "p0-3", "p0-4", "p0-6", "p1-1", "p1-2", "p1-3", "p1-4", "p1-5"):
        assert token in segment_b
        assert token not in segment_a, f"{token} must not be described as a segment A deliverable"

    assert "hmac" in segment_b
    assert "spawn-subagent" in segment_b


def test_bootstrap_exemption_is_explicit_and_temporary() -> None:
    body = normalize(section_body(read_adr_008(), "Bootstrap Exemption"))

    assert "bootstrap" in body and "exemption" in body
    assert "degraded" in body or "declared" in body
    assert any(phrase in body for phrase in ("temporary", "segment b", "not yet", "expires"))
    assert "are hmac-signed" not in body
    assert "is hmac-signed" not in body
    assert any(phrase in body for phrase in ("not hmac-signed", "are not hmac-signed", "not signed"))
    assert "runtime-captured" in body
    assert any(phrase in body for phrase in ("not runtime-captured", "rather than runtime-captured", "cannot be runtime-captured"))
    assert "spawn-subagent" in body or "subagent" in body


def test_adr_008_records_known_limits() -> None:
    body = section_body(read_adr_008(), "Risks And Known Limits")
    normalized = normalize(body)

    risk_checks = (
        ("hmac", ("secret", "compromise")),
        ("degraded", ("abuse", "bypass", "attack")),
        ("bash", ("hook", "write", "boundary", "bypass")),
    )
    for required, companions in risk_checks:
        assert required in normalized
        assert any(companion in normalized for companion in companions)

    bullets = [line for line in body.splitlines() if line.startswith("- ")]
    assert len(bullets) >= 3
    assert all(len(line) > 30 for line in bullets[:3])


def test_sprint_021_followups_cover_segment_b_backlog() -> None:
    assert FOLLOWUPS_PATH.is_file(), "sprint-021 followups.md must exist"
    normalized = normalize(FOLLOWUPS_PATH.read_text(encoding="utf-8"))

    for token in ("p0-2", "p0-3", "p0-4", "p0-6", "p1-1", "p1-2", "p1-3", "p1-4", "p1-5"):
        assert token in normalized
    for token in ("spawn-subagent", "hmac", "degraded", "write-boundary"):
        assert token in normalized
    assert "design-main-agent-boundary.md" in normalized
    assert "segment b" in normalized or "段 b" in normalized