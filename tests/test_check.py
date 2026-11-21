"""Tests for check module: dump parsing, audit, report building, schema."""

import json

from awg_cascade_ctl.check import (
    HANDSHAKE_MAX_AGE_SEC,
    audit_peers,
    build_report,
    format_report_text,
    parse_awg_dump,
    report_schema,
    report_to_json,
)

DUMP_LINE = (
    "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t"
    "1700000000\t1000\t2000\t25\n"
)

# AmneziaWG format with extra obfuscation fields (jitter, port, etc.)
DUMP_LINE_AMNEZIA = (
    "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t"
    "1700000000\t1000\t2000\t25\tjitter=40\tport=12345\n"
)


def test_parse_awg_dump_single_peer() -> None:
    """A valid peer line is parsed into a RawPeer record."""
    peers = parse_awg_dump(DUMP_LINE)
    assert len(peers) == 1
    peer = peers[0]
    assert peer.interface == "awg1"
    assert peer.peer_endpoint == "10.10.1.1:51820"
    assert peer.latest_handshake_unix == 1700000000
    assert peer.persistent_keepalive == 25


def test_parse_awg_dump_amnezia_extra_fields() -> None:
    """AmneziaWG dump lines with extra obfuscation fields are parsed."""
    peers = parse_awg_dump(DUMP_LINE_AMNEZIA)
    assert len(peers) == 1
    peer = peers[0]
    assert peer.interface == "awg1"
    assert peer.peer_endpoint == "10.10.1.1:51820"
    assert peer.persistent_keepalive == 25


def test_parse_awg_dump_ignores_bad_lines() -> None:
    """Malformed lines are skipped."""
    bad = "not-a-dump-line\n" + DUMP_LINE + "short\tline\n"
    peers = parse_awg_dump(bad)
    assert len(peers) == 1


def test_audit_peers_fresh_handshake() -> None:
    """Fresh handshake + keepalive 25 -> ok."""
    peers = parse_awg_dump(DUMP_LINE)
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].latest_handshake_age_sec == 30
    assert audits[0].keepalive_ok is True
    assert audits[0].handshake_fresh is True
    assert audits[0].ok is True


def test_audit_peers_stale_handshake() -> None:
    """Handshake older than threshold -> not fresh, not ok."""
    peers = parse_awg_dump(DUMP_LINE)
    audits = audit_peers(peers, now_unix=1700000000 + HANDSHAKE_MAX_AGE_SEC + 1)
    assert audits[0].handshake_fresh is False
    assert audits[0].ok is False


def test_audit_peers_missing_keepalive() -> None:
    """Keepalive other than required -> not ok even if fresh."""
    peers = parse_awg_dump(
        DUMP_LINE.replace("\t25\n", "\t0\n")
    )
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].keepalive_ok is False
    assert audits[0].ok is False


def test_audit_peers_zero_handshake() -> None:
    """Handshake timestamp 0 -> age None, not fresh."""
    peers = parse_awg_dump(DUMP_LINE.replace("1700000000", "0"))
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].latest_handshake_age_sec is None
    assert audits[0].handshake_fresh is False


def test_build_report_ok() -> None:
    """Report ok flag reflects all links ok and all probes ok."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000030)
    probes = []
    report = build_report("cascade", links, probes)
    assert report.ok is True
    assert report.schema_version == "1.0"


def test_build_report_failed_when_link_bad() -> None:
    """Report not ok when a link is bad."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000000 + HANDSHAKE_MAX_AGE_SEC + 1)
    report = build_report("cascade", links, [])
    assert report.ok is False


def test_report_to_json_strict_json() -> None:
    """report_to_json returns a valid single-line JSON."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000030)
    report = build_report("cascade", links, [])
    text = report_to_json(report)
    data = json.loads(text)
    assert data["schema"] == "awg-ctl/check/v1"
    assert data["schema_version"] == "1.0"
    assert data["cascade"] == "cascade"
    assert isinstance(data["links"], list)


def test_report_to_json_has_no_ansi() -> None:
    """report_to_json never emits ANSI escape sequences."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000030)
    report = build_report("cascade", links, [])
    text = report_to_json(report)
    assert "\033[" not in text


def test_report_schema_is_dict() -> None:
    """report_schema returns a JSON Schema dict."""
    schema = report_schema()
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"
    assert "$defs" in schema


def test_format_report_text_contains_overall() -> None:
    """Human text contains overall status."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000030)
    report = build_report("cascade", links, [])
    text = format_report_text(report)
    assert "overall: OK" in text
    assert "awg1" in text


def test_format_report_text_golden_no_color() -> None:
    """Golden: human text is stable with --no-color (use_color=False)."""
    peers = parse_awg_dump(DUMP_LINE)
    links = audit_peers(peers, now_unix=1700000030)
    probes = []
    report = build_report("cascade-alpha", links, probes)
    text = format_report_text(report, use_color=False)
    # Summary-first order (no ANSI without colour)
    assert "\033[" not in text  # no ANSI
    assert text.startswith("awg-ctl check - cascade-alpha")
    assert "status: PASS (pass)" in text
    assert "overall: OK" in text
    assert "generated_at:" in text
    assert "Links:" in text
    assert "1/1 ok" in text
    assert "awg1 -> 10.10.1.1:51820" in text
    assert "E2E probes:" in text
    assert "\n  none" in text  # no probes list items


def test_format_report_text_zero_links() -> None:
    """Zero links -> 'Links: 0 links', ok flag depends on status."""
    report = build_report("cascade-alpha", links=[], e2e_probes=[])
    text = format_report_text(report, use_color=False)
    assert "Links: 0 links" in text
    assert "\033[" not in text  # no ANSI
    assert "status: PASS (pass)" in text


def test_report_to_json_zero_links() -> None:
    """JSON with zero links is valid."""
    report = build_report("cascade-alpha", links=[], e2e_probes=[])
    data = json.loads(report_to_json(report))
    assert data["schema"] == "awg-ctl/check/v1"
    assert data["links"] == []
    assert data["ok"] is True


def test_parse_awg_dump_handles_off_keepalive() -> None:
    """Real AWG dump uses 'off' for keepalive; should parse as 0."""
    line = "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\toff\n"
    peers = parse_awg_dump(line)
    assert len(peers) == 1
    assert peers[0].persistent_keepalive == 0
