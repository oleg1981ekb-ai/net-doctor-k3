"""Tests for new real data loading functionality."""

from pathlib import Path
from unittest import mock

from awg_cascade_ctl.check import (
    E2EProbe,
    RawPeer,
    load_e2e_probes,
    load_real_dump,
)


def test_load_real_dump_with_dump_file(tmp_path: Path) -> None:
    """load_real_dump reads a local dump file."""
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text(
        "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )
    peers = load_real_dump(dump_file=dump_path)
    assert len(peers) == 1
    peer = peers[0]
    assert isinstance(peer, RawPeer)
    assert peer.interface == "awg0"
    assert peer.peer_endpoint == "10.10.1.1:51820"
    assert peer.latest_handshake_unix == 1700000000
    assert peer.persistent_keepalive == 25


def test_load_real_dump_without_source_uses_demo() -> None:
    """load_real_dump falls back to demo data when no source given."""
    peers = load_real_dump()
    assert len(peers) == 1
    assert peers[0].interface == "awg0"
    assert peers[0].peer_endpoint == "10.10.1.1:51820"


def test_load_e2e_probes_without_config() -> None:
    """load_e2e_probes returns empty list when config_path is None."""
    probes = load_e2e_probes(config_path=None)
    assert probes == []


def test_load_e2e_probes_success(monkeypatch) -> None:
    """load_e2e_probes runs curl and returns E2EProbe on success."""
    from awg_cascade_ctl.config import CascadeConfig

    mock_cfg = mock.MagicMock()
    mock_cfg.network.ip_checker_url = "https://example.com"
    monkeypatch.setattr(CascadeConfig, "load", lambda path: mock_cfg)

    fake_result = mock.Mock(returncode=0, stdout="192.168.1.1\n")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: fake_result)

    probes = load_e2e_probes(config_path="/path/to/config.yaml")
    assert len(probes) == 1
    probe = probes[0]
    assert isinstance(probe, E2EProbe)
    assert probe.source == "awg-in"
    assert probe.url == "https://example.com"
    assert probe.ipv4 == "192.168.1.1"
    assert probe.ok is True


def test_load_e2e_probes_failure(monkeypatch) -> None:
    """load_e2e_probes returns empty list when curl fails."""
    from awg_cascade_ctl.config import CascadeConfig

    mock_cfg = mock.MagicMock()
    mock_cfg.network.ip_checker_url = "https://example.com"
    monkeypatch.setattr(CascadeConfig, "load", lambda path: mock_cfg)

    def fake_run(*args, **kwargs):
        raise OSError("curl not found")

    monkeypatch.setattr("subprocess.run", fake_run)

    probes = load_e2e_probes(config_path="/some/path")
    assert probes == []


def test_ssh_transport_run_awg_dump() -> None:
    """SSHTransport.run_awg_dump parses AWG dump from remote host."""
    from awg_cascade_ctl.ssh import SSHTransport

    transport = SSHTransport(host="vpn-in.example.com", user="root")
    transport.connect = mock.Mock()
    transport.run = mock.Mock(
        return_value=mock.Mock(
            failed=False,
            stdout=(
                "awg0\tpub1\tpsk1\t10.10.1.1:51820\t10.10.1.0/30\t"
                "1700000000\t1000\t2000\t25\n"
            ),
        )
    )

    peers = transport.run_awg_dump()
    assert len(peers) == 1
    assert peers[0].interface == "awg0"
    assert peers[0].peer_endpoint == "10.10.1.1:51820"


def test_ssh_transport_run_awg_dump_failed() -> None:
    """SSHTransport.run_awg_dump returns empty list when command fails."""
    from awg_cascade_ctl.ssh import SSHTransport

    transport = SSHTransport(host="vpn-in.example.com", user="root")
    transport.connect = mock.Mock()
    transport.run = mock.Mock(return_value=mock.Mock(failed=True, stdout=""))

    peers = transport.run_awg_dump()
    assert peers == []


def test_fetch_and_parse_dump() -> None:
    """fetch_and_parse_dump connects, fetches, and closes."""
    from awg_cascade_ctl.ssh import SSHTransport, fetch_and_parse_dump

    mock_transport = mock.MagicMock(spec=SSHTransport)
    mock_transport.run_awg_dump.return_value = []

    result = fetch_and_parse_dump(mock_transport)
    mock_transport.connect.assert_called_once()
    mock_transport.run_awg_dump.assert_called_once()
    mock_transport.close.assert_called_once()
    assert result == []


def test_load_real_dump_target_ssh(monkeypatch) -> None:
    """load_real_dump_target SSHs to cfg.servers["mid"] and returns parsed peers."""
    from awg_cascade_ctl import check as check_module
    from awg_cascade_ctl.ssh import SSHTransport

    mock_cfg = mock.MagicMock()
    mock_server = mock.MagicMock()
    mock_server.host = "vpn-mid.example.com"
    mock_server.port = 2222
    mock_server.username = "awg"
    mock_cfg.servers = {"mid": mock_server}
    mock_cfg.timeouts.ssh_connect = 10
    mock_cfg.timeouts.ssh_command = 30

    captured = {}

    mock_transport = mock.MagicMock(spec=SSHTransport)
    mock_transport.run_awg_dump.return_value = [
        RawPeer(
            interface="awg0",
            peer_endpoint="10.10.1.2:51820",
            latest_handshake_unix=1700000001,
            persistent_keepalive=25,
        )
    ]

    def fake_transport(**kwargs):
        captured.update(kwargs)
        return mock_transport

    monkeypatch.setattr("awg_cascade_ctl.ssh.SSHTransport", fake_transport)

    peers = check_module.load_real_dump_target(mock_cfg, "mid")
    assert len(peers) == 1
    assert peers[0].peer_endpoint == "10.10.1.2:51820"
    assert captured["host"] == "vpn-mid.example.com"
    assert captured["port"] == 2222
    assert captured["user"] == "awg"


def test_load_real_dump_all_aggregates(monkeypatch) -> None:
    """load_real_dump_all aggregates peers from in, mid, out targets."""
    from awg_cascade_ctl import check as check_module

    captured_targets = []

    def fake_load_real_dump_target(cfg, target, **kwargs):
        captured_targets.append(target)
        return [
            RawPeer(
                interface=f"awg-{target}",
                peer_endpoint=f"10.10.1.{len(target)}:51820",
                latest_handshake_unix=1700000000,
                persistent_keepalive=25,
            )
        ]

    monkeypatch.setattr(check_module, "load_real_dump_target", fake_load_real_dump_target)

    peers = check_module.load_real_dump_all(mock.MagicMock())
    assert len(peers) == 3
    assert captured_targets == ["in", "mid", "out"]
    assert {peer.interface for peer in peers} == {"awg-in", "awg-mid", "awg-out"}


def test_load_e2e_probes_skips_for_mid_out(monkeypatch) -> None:
    """load_e2e_probes returns [] for mid/out without calling subprocess."""
    from awg_cascade_ctl import check as check_module

    subprocess_called = {"value": False}

    def fake_run(*args, **kwargs):
        subprocess_called["value"] = True
        return mock.Mock(returncode=0, stdout="1.2.3.4\n")

    monkeypatch.setattr(check_module.subprocess, "run", fake_run)

    assert check_module.load_e2e_probes(config_path="/path/to/config.yaml", server_target="mid") == []
    assert check_module.load_e2e_probes(config_path="/path/to/config.yaml", server_target="out") == []
    assert subprocess_called["value"] is False
