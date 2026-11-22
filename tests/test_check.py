"""Tests for check module: dump parsing, audit, report building, schema."""

import json

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
