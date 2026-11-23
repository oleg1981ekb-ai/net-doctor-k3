"""Tests for check module: dump parsing, audit, report building, schema."""

import json
from pathlib import Path
from unittest import mock

from awg_cascade_ctl.check import (
    HANDSHAKE_MAX_AGE_SEC,
    RawPeer,
    audit_peers,
    build_report,
    classify_peer,
    describe_check_plan,
    endpoint_host,
    format_report_text,
    has_default_route,
    parse_awg_dump,
    report_schema,
    report_to_json,
)

DUMP_LINE = (
    "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
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
    assert peers[0].interface == "awg1"
    assert peers[0].peer_endpoint == "10.10.1.1:51820"
    assert peers[0].persistent_keepalive == 25


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
    peers = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t0\n"))
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
    line = (
        "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\toff\n"
    )
    peers = parse_awg_dump(line)
    assert len(peers) == 1
    assert peers[0].persistent_keepalive == 0


def test_parse_awg_dump_interface_plus_peer() -> None:
    """One interface line + one real peer line -> one peer in list."""
    interface = "awg0\tPUBKEY\tPSK\t51821\t10.10.1.0/30\t1700000000\t1000\t2000\t5\t60\t1\t2\t3\t4"
    peer = (
        "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )
    peers = parse_awg_dump(interface + "\n" + peer)
    assert len(peers) == 1
    assert peers[0].interface == "awg1"


def test_parse_awg_dump_interface_line_15_fields() -> None:
    """Interface line (15 fields) is skipped, following peer line is parsed."""
    interface_15 = "awg0\tPUBKEY\tPSK\t51821\t10.10.1.0/30\t1700000000\t1000\t2000\t5\t60\t1\t2\t3\t4\textra"
    peer = (
        "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )
    peers = parse_awg_dump(interface_15 + "\n" + peer)
    assert len(peers) == 1
    assert peers[0].interface == "awg1"
    assert peers[0].persistent_keepalive == 25


def test_audit_peers_keepalive_25_ok() -> None:
    """keepalive=25 -> ok with default range 1..33."""
    peers = parse_awg_dump(DUMP_LINE)
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].keepalive_ok is True
    assert audits[0].keepalive_status == "OK"


def test_audit_peers_keepalive_33_ok() -> None:
    """keepalive=33 -> ok with default range 1..33."""
    peers = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t33\n"))
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].keepalive_ok is True
    assert audits[0].keepalive_status == "OK"


def test_audit_peers_keepalive_34_mismatch() -> None:
    """keepalive=34 -> mismatch (out of range 1..33)."""
    peers = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t34\n"))
    audits = audit_peers(peers, now_unix=1700000030)
    assert audits[0].keepalive_ok is False
    assert audits[0].keepalive_status == "MISMATCH"


def test_audit_peers_keepalive_0_off() -> None:
    """keepalive=0 or off -> OFF."""
    peers_off = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t0\n"))
    audits = audit_peers(peers_off, now_unix=1700000030)
    assert audits[0].keepalive_status == "OFF"
    off_line = "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\toff\n"
    peers_off3 = parse_awg_dump(off_line)
    audits_off = audit_peers(peers_off3, now_unix=1700000030)
    assert audits_off[0].keepalive_status == "OFF"


def test_format_report_text_keepalive_mismatch() -> None:
    """Report text shows MISMATCH for out-of-range keepalive."""
    peers = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t34\n"))
    audits = audit_peers(peers, now_unix=1700000030)
    report = build_report("cascade", audits, [])
    text = format_report_text(report, use_color=False)
    assert "MISMATCH (got 34, expected 1..33)" in text


def test_check_with_config_keepalive_in_range() -> None:
    """Test check config with keepalive_max=60 and peer keepalive=50 -> OK."""
    import os
    import tempfile

    import yaml

    from awg_cascade_ctl.config import CascadeConfig

    cfg_data = {
        "servers": {
            "in": {"host": "10.0.0.1", "username": "root"},
            "mid": {"host": "10.0.0.2", "username": "root"},
            "out": {"host": "10.0.0.3", "username": "root"},
        },
        "network": {
            "client_subnet": "10.9.9.0/24",
            "link1_subnet": "10.10.1.0/30",
            "link2_subnet": "10.10.2.0/30",
            "dns": ["1.1.1.1"],
            "ip_checker_url": "http://example.com",
        },
        "sysctl": {},
        "ports": {"client_in": 51820, "link1": 51821, "link2": 51822, "mobile": None},
        "scripts": {
            "manage_amneziawg": "/root/awg/manage_amneziawg.sh",
            "routing": "/root/awg/awg-routing.sh",
            "backup_prefixes": "/root/awg/ru.zone",
        },
        "timeouts": {"ssh_connect": 10, "ssh_command": 30, "deploy": 600, "check": 60},
        "check": {"keepalive_min": 1, "keepalive_max": 60},
        "log_level": "info",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg_data, f)
        fpath = f.name
    try:
        cfg = CascadeConfig.load(fpath)
        peers = [
            type(
                "P",
                (),
                {
                    "interface": "awg1",
                    "peer_endpoint": "10.10.1.1:51820",
                    "latest_handshake_unix": 1700000000,
                    "persistent_keepalive": 50,
                },
            )()
        ]
        audits = audit_peers(
            peers,
            now_unix=1700000030,
            min_keepalive=cfg.check.keepalive_min,
            max_keepalive=cfg.check.keepalive_max,
        )
        assert audits[0].keepalive_ok is True
        assert audits[0].keepalive_status == "OK"
    finally:
        os.unlink(fpath)


def test_check_with_config_keepalive_out_of_range() -> None:
    """Test check config with default max=33 and peer keepalive=50 -> MISMATCH."""
    import os
    import tempfile

    import yaml

    from awg_cascade_ctl.config import CascadeConfig

    cfg_data = {
        "servers": {
            "in": {"host": "10.0.0.1", "username": "root"},
            "mid": {"host": "10.0.0.2", "username": "root"},
            "out": {"host": "10.0.0.3", "username": "root"},
        },
        "network": {
            "client_subnet": "10.9.9.0/24",
            "link1_subnet": "10.10.1.0/30",
            "link2_subnet": "10.10.2.0/30",
            "dns": ["1.1.1.1"],
            "ip_checker_url": "http://example.com",
        },
        "sysctl": {},
        "ports": {"client_in": 51820, "link1": 51821, "link2": 51822, "mobile": None},
        "scripts": {
            "manage_amneziawg": "/root/awg/manage_amneziawg.sh",
            "routing": "/root/awg/awg-routing.sh",
            "backup_prefixes": "/root/awg/ru.zone",
        },
        "timeouts": {"ssh_connect": 10, "ssh_command": 30, "deploy": 600, "check": 60},
        "check": {"keepalive_min": 1, "keepalive_max": 33},
        "log_level": "info",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(cfg_data, f)
        fpath = f.name
    try:
        cfg = CascadeConfig.load(fpath)
        peers = [
            type(
                "P",
                (),
                {
                    "interface": "awg1",
                    "peer_endpoint": "10.10.1.1:51820",
                    "latest_handshake_unix": 1700000000,
                    "persistent_keepalive": 50,
                },
            )()
        ]
        audits = audit_peers(
            peers,
            now_unix=1700000030,
            min_keepalive=cfg.check.keepalive_min,
            max_keepalive=cfg.check.keepalive_max,
        )
        assert audits[0].keepalive_ok is False
        assert audits[0].keepalive_status == "MISMATCH"
    finally:
        os.unlink(fpath)


def test_check_config_validator_min_gt_max() -> None:
    """Test CheckConfig validator raises ValueError when keepalive_min > keepalive_max."""
    from awg_cascade_ctl.config import CheckConfig

    try:
        CheckConfig(keepalive_min=60, keepalive_max=33)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "keepalive_min must be <= keepalive_max" in str(e)


def test_format_report_text_keepalive_off() -> None:
    """Report text shows OFF for keepalive=0 or off."""
    # Test with 0
    peers0 = parse_awg_dump(DUMP_LINE.replace("\t25\n", "\t0\n"))
    report0 = build_report("cascade", audit_peers(peers0, now_unix=1700000030), [])
    text0 = format_report_text(report0, use_color=False)
    assert "OFF" in text0
    # Test with off literal
    off_line = "awg1\tPUBKEY\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\toff\n"
    peers_off = parse_awg_dump(off_line)
    report_off = build_report(
        "cascade", audit_peers(peers_off, now_unix=1700000030), []
    )
    text_off = format_report_text(report_off, use_color=False)
    assert "OFF" in text_off


def test_describe_check_plan_demo_has_demo_warning() -> None:
    """Demo source includes a prominent DEMO DATA warning and demo label."""
    text = describe_check_plan(
        source="demo",
        server_target="in",
        min_keepalive=1,
        max_keepalive=33,
        max_age_sec=HANDSHAKE_MAX_AGE_SEC,
        probe_url=None,
        probe_skipped_reason="no --config",
    )
    assert "DEMO DATA: your servers are NOT being checked." in text
    assert "built-in demo data" in text


def test_describe_check_plan_dump_file_source() -> None:
    """Dump-file source shows the file path."""
    text = describe_check_plan(
        source="dump_file",
        server_target="in",
        min_keepalive=1,
        max_keepalive=33,
        probe_url=None,
        probe_skipped_reason="no --config",
        dump_file="/tmp/dump.txt",
    )
    assert "dump file /tmp/dump.txt" in text


def test_describe_check_plan_ssh_in_source() -> None:
    """SSH in source text and probe line with URL and timeout."""
    text = describe_check_plan(
        source="ssh",
        server_target="in",
        min_keepalive=1,
        max_keepalive=33,
        probe_url="https://example.com",
        probe_skipped_reason=None,
    )
    assert 'SSH, server "in" (from cascade.yaml)' in text
    assert "curl https://example.com (timeout 5 s)" in text


def test_describe_check_plan_ssh_all_source() -> None:
    """SSH all source lists all three servers."""
    text = describe_check_plan(
        source="ssh",
        server_target="all",
        min_keepalive=1,
        max_keepalive=33,
        probe_url="https://example.com",
        probe_skipped_reason=None,
    )
    assert "SSH, servers in, mid, out" in text


def test_describe_check_plan_thresholds_from_config() -> None:
    """Keepalive range in text follows the passed min/max values."""
    text = describe_check_plan(
        source="ssh",
        server_target="in",
        min_keepalive=1,
        max_keepalive=60,
        probe_url=None,
        probe_skipped_reason="no --config",
    )
    assert "within 1..60 s" in text


def test_describe_check_plan_probe_skipped_no_config() -> None:
    """Probe skip reason for missing config is shown verbatim."""
    text = describe_check_plan(
        source="demo",
        server_target="in",
        min_keepalive=1,
        max_keepalive=33,
        probe_url=None,
        probe_skipped_reason="no --config",
    )
    assert "internet access: skipped (no --config)" in text


def test_describe_check_plan_probe_skipped_mid_server() -> None:
    """Probe skip reason for mid/out server is shown verbatim."""
    text = describe_check_plan(
        source="ssh",
        server_target="mid",
        min_keepalive=1,
        max_keepalive=33,
        probe_url="https://example.com",
        probe_skipped_reason="server is not in/all",
    )
    assert "internet access: skipped (server is not in/all)" in text


def test_check_intro_shown_when_should_show_true(monkeypatch) -> None:
    """When _should_show_intro is True and no --json, intro goes to stderr only."""
    from typer.testing import CliRunner

    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr("time.time", lambda: 1700000030)
    monkeypatch.setattr(cli_module, "_should_show_intro", lambda json_output: True)
    result = CliRunner().invoke(cli_module.app, ["check"])
    assert "DEMO DATA" in result.stderr
    assert "DEMO DATA" not in result.stdout


def test_check_intro_suppressed_with_json(monkeypatch) -> None:
    """--json suppresses the intro (real _should_show_intro returns False)."""
    from typer.testing import CliRunner

    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr("time.time", lambda: 1700000030)
    result = CliRunner().invoke(cli_module.app, ["check", "--json"])
    assert "DEMO DATA" not in result.stderr
    data = json.loads(result.output)
    assert data["schema"] == "awg-ctl/check/v1"


def test_check_intro_suppressed_when_should_show_false(monkeypatch) -> None:
    """When _should_show_intro is False, no intro appears."""
    from typer.testing import CliRunner

    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr("time.time", lambda: 1700000030)
    monkeypatch.setattr(cli_module, "_should_show_intro", lambda json_output: False)
    result = CliRunner().invoke(cli_module.app, ["check"])
    assert "DEMO DATA" not in result.stderr


DUMP_LINE_ALLOWED_DEFAULT = (
    "awg1\tPUB\tPSK\t198.51.100.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t25\n"
)

DUMP_LINE_ALLOWED_HOST_ROUTE = (
    "awg1\tPUB\tPSK\t198.51.100.5:51820\t172.16.17.2/32\t1700000000\t1000\t2000\t25\n"
)


def test_parse_awg_dump_fills_allowed_ips() -> None:
    """parse_awg_dump fills RawPeer.allowed_ips from parts[4]."""
    peers = parse_awg_dump(DUMP_LINE_ALLOWED_DEFAULT + DUMP_LINE_ALLOWED_HOST_ROUTE)
    assert len(peers) == 2
    assert peers[0].allowed_ips == "0.0.0.0/0,::/0"
    assert peers[1].allowed_ips == "172.16.17.2/32"


def test_endpoint_host_ipv4_strips_port() -> None:
    """IPv4 endpoint -> host without port."""
    assert endpoint_host("1.2.3.4:51820") == "1.2.3.4"


def test_endpoint_host_ipv6_bracketed_strips_port() -> None:
    """Bracketed IPv6 endpoint -> host without brackets or port."""
    assert endpoint_host("[2001:db8::1]:51820") == "2001:db8::1"


def test_endpoint_host_none_endpoint() -> None:
    """'(none)' endpoint -> None."""
    assert endpoint_host("(none)") is None


def test_endpoint_host_garbage() -> None:
    """Unparseable endpoint -> None."""
    assert endpoint_host("garbage") is None


def test_has_default_route_full() -> None:
    """Default route (both families) -> True."""
    assert has_default_route("0.0.0.0/0,::/0") is True


def test_has_default_route_ipv6_default() -> None:
    """IPv6 default route -> True."""
    assert has_default_route("::/0") is True


def test_has_default_route_host_route() -> None:
    """Single-host route is not a default route -> False."""
    assert has_default_route("172.16.17.2/32") is False


def test_has_default_route_private_subnet() -> None:
    """Subnet without default prefix is not a default route -> False."""
    assert has_default_route("10.0.0.0/8,172.16.17.2/32") is False


def test_has_default_route_none_and_empty() -> None:
    """'(none)' and empty string are not default routes -> False."""
    assert has_default_route("(none)") is False
    assert has_default_route("") is False


def test_has_default_route_garbage_then_default() -> None:
    """Invalid entry skipped, default route still detected -> True."""
    assert has_default_route("garbage,0.0.0.0/0") is True


def test_classify_peer_default_route_is_link() -> None:
    """Default route -> link even with unknown endpoint."""
    peer = RawPeer(
        interface="awg1",
        peer_endpoint="198.51.100.99:51820",
        latest_handshake_unix=1700000000,
        persistent_keepalive=25,
        allowed_ips="0.0.0.0/0,::/0",
    )
    assert classify_peer(peer, frozenset()) == "link"


def test_classify_peer_endpoint_match_is_link() -> None:
    """Endpoint host equals a link_host -> link even with /32 allowed-ips."""
    peer = RawPeer(
        interface="awg1",
        peer_endpoint="203.0.113.1:51820",
        latest_handshake_unix=1700000000,
        persistent_keepalive=25,
        allowed_ips="203.0.113.2/32",
    )
    assert classify_peer(peer, frozenset({"203.0.113.1"})) == "link"


def test_classify_peer_host_route_foreign_endpoint_is_client() -> None:
    """/32 allowed-ips with foreign endpoint -> client."""
    peer = RawPeer(
        interface="awg1",
        peer_endpoint="198.51.100.5:51820",
        latest_handshake_unix=1700000000,
        persistent_keepalive=25,
        allowed_ips="203.0.113.2/32",
    )
    assert classify_peer(peer, frozenset({"203.0.113.1"})) == "client"


def test_classify_peer_none_endpoint_with_none_allowed_ips_is_client() -> None:
    """'(none)' in endpoint AND allowed-ips -> client."""
    peer = RawPeer(
        interface="awg1",
        peer_endpoint="(none)",
        latest_handshake_unix=1700000000,
        persistent_keepalive=25,
        allowed_ips="(none)",
    )
    assert classify_peer(peer, frozenset()) == "client"


def test_classify_peer_ipv6_link_host_matches_bracketed() -> None:
    """IPv6 link_host matches bracketed endpoint -> link."""
    peer = RawPeer(
        interface="awg1",
        peer_endpoint="[2001:db8::1]:51820",
        latest_handshake_unix=1700000000,
        persistent_keepalive=25,
        allowed_ips="2001:db8::2/128",
    )
    assert classify_peer(peer, frozenset({"2001:db8::1"})) == "link"


DUMP_LINE_LINK_ROLE = (
    "awg1\tPUB\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t33\n"
)
DUMP_LINE_CLIENT_BAD = (
    "awg1\tPUB\tPSK\t198.51.100.5:51820\t203.0.113.2/32\t1700000000\t1000\t2000\t0\n"
)
DUMP_LINE_CLIENT_HEALTHY = (
    "awg1\tPUB\tPSK\t198.51.100.5:51820\t203.0.113.2/32\t1700000000\t1000\t2000\t25\n"
)
DUMP_LINE_LINK_BAD_KEEPALIVE = (
    "awg1\tPUB\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t34\n"
)


def test_audit_peers_no_link_hosts_all_link() -> None:
    """Without link_hosts every audit has role "link"."""
    peers = parse_awg_dump(DUMP_LINE + DUMP_LINE_ALLOWED_DEFAULT)
    audits = audit_peers(peers, now_unix=1700000030, link_hosts=None)
    assert audits
    assert all(audit.role == "link" for audit in audits)
    audits_default = audit_peers(peers, now_unix=1700000030)
    assert all(audit.role == "link" for audit in audits_default)


def test_audit_peers_roles_with_link_hosts() -> None:
    """link_hosts classifies default-route peer as link and /32 peer as client."""
    peers = parse_awg_dump(DUMP_LINE_LINK_ROLE + DUMP_LINE_CLIENT_BAD)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    assert audits[0].role == "link"
    assert audits[1].role == "client"
    assert audits[0].ok is True
    assert audits[1].ok is False
    # Clients are ignored by build_report, not by audit_peers.
    report = build_report("cascade", audits, [], roles_active=True)
    assert report.ok is True


def test_build_report_roles_active_ok() -> None:
    """roles_active=True: healthy link + bad client -> ok True."""
    peers = parse_awg_dump(DUMP_LINE_LINK_ROLE + DUMP_LINE_CLIENT_BAD)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    assert report.ok is True
    assert report.status == "pass"


def test_build_report_roles_active_link_bad() -> None:
    """roles_active=True: bad link (keepalive 34) + healthy clients -> ok False."""
    peers = parse_awg_dump(DUMP_LINE_LINK_BAD_KEEPALIVE + DUMP_LINE_CLIENT_HEALTHY)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    assert report.ok is False
    assert report.status == "fail"


def test_build_report_roles_active_all_clients() -> None:
    """roles_active=True with only clients -> ok False, status fail."""
    peers = parse_awg_dump(DUMP_LINE_CLIENT_HEALTHY + DUMP_LINE_CLIENT_BAD)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    assert report.ok is False
    assert report.status == "fail"


def test_format_report_text_client_not_counted() -> None:
    """Client line is flagged and excluded from the N/M ok counter."""
    peers = parse_awg_dump(DUMP_LINE_LINK_ROLE + DUMP_LINE_CLIENT_BAD)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "[client, not counted]" in text
    assert "1/1 ok" in text


def test_format_report_text_no_cascade_links() -> None:
    """Only clients -> 'no cascade links found' in the Links section."""
    peers = parse_awg_dump(DUMP_LINE_CLIENT_HEALTHY + DUMP_LINE_CLIENT_BAD)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "no cascade links found" in text


def test_report_json_contains_role() -> None:
    """report_to_json includes each audit's role in links[]."""
    peers = parse_awg_dump(DUMP_LINE_LINK_ROLE + DUMP_LINE_CLIENT_HEALTHY)
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade", audits, [], roles_active=True)
    data = json.loads(report_to_json(report))
    assert data["links"][0]["role"] == "link"
    assert data["links"][1]["role"] == "client"


def test_run_check_wires_link_hosts_and_roles_active(monkeypatch, tmp_path) -> None:
    """_run_check passes cascade hosts as link_hosts and roles_active=True.

    With --config (and no --dump-file), audit_peers receives link_hosts built
    from the three server hosts in cascade.yaml and build_report receives
    roles_active=True. With --dump-file, link_hosts is None and roles_active
    is False.
    """
    import yaml

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.check import (
        RawPeer,
    )
    from awg_cascade_ctl.check import (
        audit_peers as real_audit_peers,
    )
    from awg_cascade_ctl.check import (
        build_report as real_build_report,
    )

    monkeypatch.setattr("time.time", lambda: 1700000030)

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {"host": hosts[0], "username": "root"},
                    "mid": {"host": hosts[1], "username": "root"},
                    "out": {"host": hosts[2], "username": "root"},
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    def _peer(endpoint: str, keepalive: int, allowed_ips: str) -> RawPeer:
        return RawPeer(
            interface="awg1",
            peer_endpoint=endpoint,
            latest_handshake_unix=1700000000,
            persistent_keepalive=keepalive,
            allowed_ips=allowed_ips,
        )

    link_peer = _peer(f"{hosts[0]}:51820", 25, "0.0.0.0/0,::/0")
    client_peer = _peer("198.51.100.5:51820", 0, "203.0.113.2/32")

    def fake_load_real_dump(**kw):
        if kw.get("dump_file"):
            return [link_peer]
        return [link_peer, client_peer]

    monkeypatch.setattr(cli_module, "load_real_dump", fake_load_real_dump)
    monkeypatch.setattr(cli_module, "load_e2e_probes", lambda **kw: [])

    captured: dict = {}

    def fake_audit_peers(*args, **kwargs):
        captured["audit_peers"] = kwargs
        return real_audit_peers(*args, **kwargs)

    def fake_build_report(**kwargs):
        captured["build_report"] = kwargs
        return real_build_report(**kwargs)

    monkeypatch.setattr(cli_module, "audit_peers", fake_audit_peers)
    monkeypatch.setattr(cli_module, "build_report", fake_build_report)

    code = cli_module._run_check(json_output=True, config_path=str(cfg_path))
    assert code == 0
    assert captured["audit_peers"]["link_hosts"] == frozenset(
        {"203.0.113.10", "203.0.113.11", "203.0.113.12"}
    )
    assert captured["build_report"]["roles_active"] is True

    captured.clear()
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text(
        "awg1\tPUB\tPSK\t203.0.113.10:51820\t0.0.0.0/0,::/0\t"
        "1700000000\t1000\t2000\t25\n"
    )
    code = cli_module._run_check(
        json_output=True,
        config_path=str(cfg_path),
        dump_file=str(dump_path),
    )
    assert code == 0
    assert captured["audit_peers"]["link_hosts"] is None
    assert captured["build_report"]["roles_active"] is False


def test_describe_ssh_error_password_required(tmp_path) -> None:
    """describe_ssh_error returns single-line for encrypted key."""
    from paramiko import PasswordRequiredException

    from awg_cascade_ctl.check import describe_ssh_error

    exc = PasswordRequiredException("Private key file is encrypted")
    msg = describe_ssh_error(exc, "mid", "198.51.100.10", 22, "/tmp/key")
    assert "SSH key for server mid is encrypted" in msg
    assert "/tmp/key" in msg
    assert "Use --ask-pass" in msg
    assert "Traceback" not in msg
    assert "\n" not in msg


def test_describe_ssh_error_auth_failed(tmp_path) -> None:
    """describe_ssh_error returns single-line for auth failure."""
    from paramiko import AuthenticationException

    from awg_cascade_ctl.check import describe_ssh_error

    exc = AuthenticationException("Permission denied")
    msg = describe_ssh_error(exc, "mid", "198.51.100.10", 22, "/tmp/key")
    assert "SSH authentication failed for server mid" in msg
    assert "198.51.100.10" in msg
    assert "/tmp/key" in msg
    assert "Traceback" not in msg
    assert "\n" not in msg


def test_describe_ssh_error_network_error(tmp_path) -> None:
    """describe_ssh_error returns single-line for network error."""
    from awg_cascade_ctl.check import describe_ssh_error

    exc = OSError("Connection refused")
    msg = describe_ssh_error(exc, "mid", "198.51.100.10", 22, "/tmp/key")
    assert "Cannot connect to server mid" in msg
    assert "198.51.100.10:22" in msg
    assert "Connection refused" in msg
    assert "Traceback" not in msg
    assert "\n" not in msg


def test_describe_ssh_error_fallback(tmp_path) -> None:
    """describe_ssh_error returns single-line for unknown error."""
    from awg_cascade_ctl.check import describe_ssh_error

    exc = ValueError("boom")
    msg = describe_ssh_error(exc, "mid", "198.51.100.10", 22, None)
    assert "SSH error for server mid" in msg
    assert "198.51.100.10" in msg
    assert "boom" in msg
    assert "Traceback" not in msg
    assert "\n" not in msg


def test_load_real_dump_target_per_server_key(monkeypatch, tmp_path) -> None:
    """load_real_dump_target uses the target server's ssh_key_path."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.config import CascadeConfig
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "in_key"),
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "mid_key"),
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "out_key"),
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    captured: dict = {}

    # Create fake key files so Path.is_file() passes
    for kp in (
        str(tmp_path / "in_key"),
        str(tmp_path / "mid_key"),
        str(tmp_path / "out_key"),
    ):
        Path(kp).write_text("")

    def fake_transport(**kwargs):
        captured[kwargs.get("host")] = kwargs.get("key_path")
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)
    cfg = CascadeConfig.load(cfg_path)

    check_module.load_real_dump_target(cfg, "in")
    check_module.load_real_dump_target(cfg, "mid")
    check_module.load_real_dump_target(cfg, "out")

    assert captured.get(cfg.servers["in"].host) == str(tmp_path / "in_key")
    assert captured.get(cfg.servers["mid"].host) == str(tmp_path / "mid_key")
    assert captured.get(cfg.servers["out"].host) == str(tmp_path / "out_key")


def test_load_real_dump_target_cli_key_override(monkeypatch, tmp_path) -> None:
    """load_real_dump_target respects CLI --key-path override."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.config import CascadeConfig
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "in_key"),
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "mid_key"),
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "out_key"),
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    captured_key: dict = {}

    def fake_transport(**kwargs):
        captured_key["key_path"] = kwargs.get("key_path")
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)
    cfg = CascadeConfig.load(cfg_path)

    Path(tmp_path / "cli_override_key").write_text("")

    check_module.load_real_dump_target(
        cfg, "mid", key_path=str(tmp_path / "cli_override_key")
    )

    assert captured_key["key_path"] == str(tmp_path / "cli_override_key")


def test_run_check_encrypted_key_clean_error(monkeypatch, tmp_path) -> None:
    """_run_check returns 1 and prints clean SSH error for encrypted key."""
    import io
    import sys

    import yaml
    from paramiko import PasswordRequiredException

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "fake_key"),
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    def raising_connect(self):
        raise PasswordRequiredException("Private key file is encrypted")

    monkeypatch.setattr(SSHTransport, "connect", raising_connect)

    Path(tmp_path / "fake_key").write_text("")

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        code = cli_module._run_check(
            json_output=True,
            config_path=str(cfg_path),
            server_target="in",
        )
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert code == 1
    error_lines = [
        ln
        for ln in stderr_output.splitlines()
        if "SSH key for server in is encrypted" in ln
    ]
    assert len(error_lines) == 1
    assert str(tmp_path / "fake_key") in error_lines[0]
    assert "Traceback" not in stderr_output


def test_run_check_server_all_names_failing_server(monkeypatch, tmp_path) -> None:
    """_run_check with --server all names the failing server in error."""
    import io
    import sys

    import yaml
    from paramiko import PasswordRequiredException

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "198.51.100.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "in_key"),
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "mid_key"),
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "out_key"),
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    Path(tmp_path / "in_key").write_text("")
    Path(tmp_path / "mid_key").write_text("")
    Path(tmp_path / "out_key").write_text("")

    # in -> success (no peers), mid -> raises PasswordRequiredException
    call_count = {"value": 0}

    def raising_connect(self):
        call_count["value"] += 1
        if call_count["value"] == 2:
            raise PasswordRequiredException("Private key file is encrypted")
        return mock.MagicMock()

    monkeypatch.setattr(SSHTransport, "connect", raising_connect)

    def fake_run_awg_dump(self):
        if self.host == hosts[0]:
            return []
        raise RuntimeError("SSH dump failed: x")

    monkeypatch.setattr(SSHTransport, "run_awg_dump", fake_run_awg_dump)

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        code = cli_module._run_check(
            json_output=True,
            config_path=str(cfg_path),
            server_target="all",
        )
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert code == 1
    assert "server mid" in stderr_output.lower()
    assert "encrypted" in stderr_output.lower()
    assert "Traceback" not in stderr_output


def test_load_real_dump_target_mid_out_use_in_key(monkeypatch, tmp_path) -> None:
    """T1: only in has ssh_key_path; mid and out fall back to in's key."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "in_key"),
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    captured: dict = {}

    def fake_transport(**kwargs):
        captured[kwargs.get("host")] = kwargs.get("key_path")
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)

    Path(tmp_path / "in_key").write_text("")

    from awg_cascade_ctl.config import CascadeConfig

    cfg = CascadeConfig.load(cfg_path)

    check_module.load_real_dump_target(cfg, "mid")
    check_module.load_real_dump_target(cfg, "out")

    assert captured.get(cfg.servers["mid"].host) == str(tmp_path / "in_key")
    assert captured.get(cfg.servers["out"].host) == str(tmp_path / "in_key")


def test_load_real_dump_target_mid_own_out_fallback(monkeypatch, tmp_path) -> None:
    """T2: mid has own key; in/out have none; out falls back to mid's key."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "mid_key"),
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    captured: dict = {}

    def fake_transport(**kwargs):
        captured[kwargs.get("host")] = kwargs.get("key_path")
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)

    Path(tmp_path / "mid_key").write_text("")

    from awg_cascade_ctl.config import CascadeConfig

    cfg = CascadeConfig.load(cfg_path)

    check_module.load_real_dump_target(cfg, "mid")
    check_module.load_real_dump_target(cfg, "out")

    assert captured.get(cfg.servers["mid"].host) == str(tmp_path / "mid_key")
    assert captured.get(cfg.servers["out"].host) == str(tmp_path / "mid_key")


def test_load_real_dump_target_no_key_auto_detect(
    monkeypatch, tmp_path, capsys
) -> None:
    """T3: no ssh_key_path anywhere and no CLI key → key_path None, auto-detect banner."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    captured: dict = {}

    def fake_transport(**kwargs):
        captured.update(kwargs)
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)

    from awg_cascade_ctl.config import CascadeConfig

    cfg = CascadeConfig.load(cfg_path)

    check_module.load_real_dump_target(cfg, "mid")

    assert captured["key_path"] is None
    captured_stderr = capsys.readouterr().err
    assert "* SSH key: ssh-agent / auto-detect (decrypted)" in captured_stderr


def test_load_real_dump_target_missing_key_file(monkeypatch, tmp_path) -> None:
    """T4: nonexistent key file → SSHDumpError with exc being FileNotFoundError."""
    import yaml

    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "does_not_exist_key"),
                    },
                    "mid": {
                        "host": hosts[1],
                        "username": "root",
                    },
                    "out": {
                        "host": hosts[2],
                        "username": "root",
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    def fake_transport(**kwargs):
        mock_transport = mock.MagicMock(spec=SSHTransport)
        mock_transport.run_awg_dump.return_value = []
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)

    from awg_cascade_ctl.config import CascadeConfig

    cfg = CascadeConfig.load(cfg_path)

    try:
        check_module.load_real_dump_target(cfg, "in")
    except check_module.SSHDumpError as exc:
        assert isinstance(exc.exc, FileNotFoundError)
    else:
        raise AssertionError("SSHDumpError was not raised")


def test_describe_ssh_error_file_not_found(tmp_path) -> None:
    """T5: FileNotFoundError → single line 'SSH key file not found for server mid: <path>'."""
    from awg_cascade_ctl.check import describe_ssh_error

    msg = describe_ssh_error(
        FileNotFoundError("/some/missing.key"),
        "mid",
        "198.51.100.10",
        22,
        "/some/missing.key",
    )
    assert msg == "SSH key file not found for server mid: /some/missing.key"
    assert "Traceback" not in msg
    assert "\n" not in msg


def test_run_check_missing_key_file_single_line(monkeypatch, tmp_path) -> None:
    """T6: _run_check with nonexistent key file → code 1, one missing-file line, no Traceback."""
    import io
    import sys

    import yaml

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                        "ssh_key_path": str(tmp_path / "does_not_exist_key"),
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    def raising_connect(self):
        raise FileNotFoundError(str(tmp_path / "does_not_exist_key"))

    monkeypatch.setattr(SSHTransport, "connect", raising_connect)

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        code = cli_module._run_check(
            json_output=True,
            config_path=str(cfg_path),
            server_target="in",
        )
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert code == 1
    missing_lines = [
        ln for ln in stderr_output.splitlines() if "SSH key file not found" in ln
    ]
    assert len(missing_lines) == 1
    assert "Traceback" not in stderr_output
    assert "config file not found" not in stderr_output


def test_run_check_no_mid_out_roles_inactive(monkeypatch, tmp_path) -> None:
    """T7: config with only 'in' → audit_peers link_hosts=None, build_report roles_active=False."""
    import yaml

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.check import (
        RawPeer,
    )
    from awg_cascade_ctl.check import (
        audit_peers as real_audit_peers,
    )
    from awg_cascade_ctl.check import (
        build_report as real_build_report,
    )

    monkeypatch.setattr("time.time", lambda: 1700000030)

    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {"host": "203.0.113.10", "username": "root"},
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    def _peer(endpoint: str, keepalive: int, allowed_ips: str) -> RawPeer:
        return RawPeer(
            interface="awg1",
            peer_endpoint=endpoint,
            latest_handshake_unix=1700000000,
            persistent_keepalive=keepalive,
            allowed_ips=allowed_ips,
        )

    link_peer = _peer("203.0.113.10:51820", 25, "0.0.0.0/0,::/0")

    def fake_load_real_dump(**kw):
        return [link_peer]

    monkeypatch.setattr(cli_module, "load_real_dump", fake_load_real_dump)
    monkeypatch.setattr(cli_module, "load_e2e_probes", lambda **kw: [])

    captured: dict = {}

    def fake_audit_peers(*args, **kwargs):
        captured["audit_peers"] = kwargs
        return real_audit_peers(*args, **kwargs)

    def fake_build_report(**kwargs):
        captured["build_report"] = kwargs
        return real_build_report(**kwargs)

    monkeypatch.setattr(cli_module, "audit_peers", fake_audit_peers)
    monkeypatch.setattr(cli_module, "build_report", fake_build_report)

    code = cli_module._run_check(json_output=True, config_path=str(cfg_path))
    assert code == 0
    assert captured["audit_peers"]["link_hosts"] is None
    assert captured["build_report"]["roles_active"] is False


def test_run_check_cli_key_missing_single_line(monkeypatch, tmp_path) -> None:
    """T8: explicit CLI key missing on disk → one missing-file line, code 1."""
    import io
    import sys

    import yaml

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.ssh import SSHTransport

    hosts = ["203.0.113.10"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {
                        "host": hosts[0],
                        "username": "root",
                    },
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    missing_key = tmp_path / "cli_missing.key"

    def raising_connect(self):
        raise FileNotFoundError(str(missing_key))

    monkeypatch.setattr(SSHTransport, "connect", raising_connect)

    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        code = cli_module._run_check(
            json_output=True,
            config_path=str(cfg_path),
            server_target="in",
            key_path=str(missing_key),
        )
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    assert code == 1
    missing_lines = [
        ln for ln in stderr_output.splitlines() if "SSH key file not found" in ln
    ]
    assert len(missing_lines) == 1
    assert str(missing_key) in missing_lines[0]
    assert "Traceback" not in stderr_output
    assert "config file not found" not in stderr_output


def test_audit_peers_passive_keepalive_fresh() -> None:
    """T1: link, link_hosts, keepalive 0, fresh handshake -> keepalive_ok True, passive True, ok True."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    assert len(audits) == 1
    assert audits[0].role == "link"
    assert audits[0].persistent_keepalive == 0
    assert audits[0].keepalive_status == "OFF"
    assert audits[0].handshake_fresh is True
    assert audits[0].keepalive_ok is True
    assert audits[0].keepalive_passive is True
    assert audits[0].ok is True


def test_audit_peers_passive_keepalive_stale() -> None:
    """T2: link, keepalive 0, handshake 1000s old -> ok False, passive False."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700001030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    assert len(audits) == 1
    assert audits[0].keepalive_passive is False
    assert audits[0].handshake_fresh is False
    assert audits[0].ok is False


def test_audit_peers_passive_no_link_hosts_strict() -> None:
    """T3: link_hosts=None -> strict evaluation, keepalive 0 -> ok False, passive False."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=None,
    )
    assert len(audits) == 1
    assert audits[0].keepalive_passive is False
    assert audits[0].keepalive_ok is False
    assert audits[0].ok is False


def test_audit_peers_keepalive_34_mismatch_passive_false() -> None:
    """T4: keepalive 34 -> MISMATCH, ok False, passive False."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t34\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    assert len(audits) == 1
    assert audits[0].keepalive_status == "MISMATCH"
    assert audits[0].keepalive_ok is False
    assert audits[0].keepalive_passive is False
    assert audits[0].ok is False


def test_audit_peers_client_keepalive_0_passive_false() -> None:
    """T5: client keepalive 0 -> role client, keepalive_passive False."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t198.51.100.5:51820\t203.0.113.2/32\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    assert len(audits) == 1
    assert audits[0].role == "client"
    assert audits[0].keepalive_passive is False


def test_build_report_passive_link_ok() -> None:
    """T6: roles_active=True, passive link + offline client -> ok True, pass."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
        + "awg1\tPUBKEY2\tPSK2\t198.51.100.5:51820\t203.0.113.2/32\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    assert report.ok is True
    assert report.status == "pass"


def test_format_report_text_passive_receiving_end_note() -> None:
    """T7: text shows "(receiving end)" and note line for passive link."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "(receiving end)" in text
    assert "keepalive=OFF (receiving end)" in text
    assert "note: keepalive=OFF on a link with a fresh handshake" in text


def test_format_report_text_no_passive_no_note() -> None:
    """T7: no passive links -> no "(receiving end)" and no note line."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t33\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "(receiving end)" not in text
    assert "note:" not in text


def test_result_ok_passive_link() -> None:
    """T8: Result OK for two links, one passive."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
        + "awg1\tPUBKEY2\tPSK2\t203.0.113.2:51821\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t33\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1", "203.0.113.2"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "Result: OK" in text
    assert text.count("ok=yes") == 2


def test_result_failed_passive_stale_handshake() -> None:
    """T9: passive link + stale handshake -> FAILED with both reasons."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700001030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    text = format_report_text(report, use_color=False)
    assert "Result: FAILED" in text
    assert "keepalive is off" in text.lower() or "keepalive" in text.lower()
    assert "no fresh handshake" in text.lower() or "handshake" in text.lower()


def test_describe_check_plan_ssh_keepalive_text() -> None:
    """T10: ssh source new keepalive text with receiving end note."""
    text = describe_check_plan(
        source="ssh",
        server_target="in",
        min_keepalive=1,
        max_keepalive=33,
        probe_url="https://example.com",
        probe_skipped_reason=None,
    )
    lines = text.splitlines()
    keepalive_line = [l for l in lines if l.startswith("               2) keepalive")]
    assert len(keepalive_line) == 1
    assert "OFF is accepted on the receiving end" in keepalive_line[0]


def test_describe_check_plan_demo_dumpfile_keepalive_old() -> None:
    """T10: demo and dump_file keep old keepalive text."""
    for source, kw in [
        ("demo", {}),
        ("dump_file", {"dump_file": "/tmp/dump.txt"}),
    ]:
        text = describe_check_plan(
            source=source,
            server_target="in",
            min_keepalive=1,
            max_keepalive=33,
            probe_url="https://example.com",
            probe_skipped_reason=None,
            **kw,
        )
        lines = text.splitlines()
        keepalive_line = [
            l for l in lines if l.startswith("               2) keepalive")
        ]
        assert len(keepalive_line) == 1
        assert "OFF is accepted" not in keepalive_line[0]


def test_json_contains_keepalive_passive() -> None:
    """T11: JSON output contains keepalive_passive field."""
    peers = parse_awg_dump(
        "awg1\tPUBKEY\tPSK\t203.0.113.1:51820\t0.0.0.0/0,::/0\t1700000000\t1000\t2000\t0\n"
    )
    audits = audit_peers(
        peers,
        now_unix=1700000030,
        link_hosts=frozenset({"203.0.113.1"}),
    )
    report = build_report("cascade-alpha", audits, [], roles_active=True)
    data = json.loads(report_to_json(report))
    assert data["links"][0]["keepalive_passive"] is True


def test_schema_contains_keepalive_passive() -> None:
    """T11: schema --json contains keepalive_passive."""
    schema = report_schema()
    link_audit_props = schema["$defs"]["LinkAudit"]["properties"]
    assert "keepalive_passive" in link_audit_props
    assert link_audit_props["keepalive_passive"]["type"] == "boolean"


def test_run_check_passive_link_ok(monkeypatch, tmp_path) -> None:
    """T12: _run_check via CliRunner, mocked load_real_dump, passive link -> code 0, Result: OK."""
    import yaml
    from typer.testing import CliRunner

    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.check import RawPeer

    monkeypatch.setattr("time.time", lambda: 1700000030)

    hosts = ["203.0.113.10", "203.0.113.11", "203.0.113.12"]
    cfg_path = tmp_path / "cascade.yaml"
    cfg_path.write_text(
        yaml.dump(
            {
                "servers": {
                    "in": {"host": hosts[0], "username": "root"},
                    "mid": {"host": hosts[1], "username": "root"},
                    "out": {"host": hosts[2], "username": "root"},
                },
                "network": {
                    "client_subnet": "10.9.9.0/24",
                    "link1_subnet": "10.10.1.0/30",
                    "link2_subnet": "10.10.2.0/30",
                    "dns": ["1.1.1.1"],
                    "ip_checker_url": "http://example.com",
                },
                "ports": {
                    "client_in": 51820,
                    "link1": 51821,
                    "link2": 51822,
                    "mobile": None,
                },
            }
        )
    )

    link_peer = RawPeer(
        interface="awg1",
        peer_endpoint=f"{hosts[0]}:51820",
        latest_handshake_unix=1700000000,
        persistent_keepalive=0,
        allowed_ips="0.0.0.0/0,::/0",
    )

    def fake_load_real_dump(**kw):
        return [link_peer]

    monkeypatch.setattr(cli_module, "load_real_dump", fake_load_real_dump)
    monkeypatch.setattr(cli_module, "load_e2e_probes", lambda **kw: [])

    runner = CliRunner()
    result = runner.invoke(
        cli_module.app,
        ["check", "--config", str(cfg_path), "--server", "in", "--json"],
    )
    assert result.exit_code == 0
    output = result.output
    assert "keepalive_passive" in output
    assert "Result: OK" in output or '"status": "pass"' in output
