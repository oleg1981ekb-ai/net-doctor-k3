"""Tests for the diagnose module: checks, verdict, formatting, redaction."""

import json

from awg_cascade_ctl.diagnose import (
    CheckResult,
    DiagnoseReport,
    check_firewall,
    check_routes,
    check_scripts,
    check_service,
    check_tunnel,
    check_versions,
    compute_verdict,
    diagnose_report_to_json,
    format_diagnose_report_text,
    run_diagnostics,
)


class FakeResult:
    """Mimics fabric command result."""

    def __init__(self, failed: bool, stdout: str) -> None:
        self.failed = failed
        self.stdout = stdout


class FakeTransport:
    """Mimics SSHTransport for unit tests."""

    def __init__(self, responses: dict[str, FakeResult] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or {}
        self.error = error
        self.commands: list[str] = []

    def run(self, command: str, **kwargs):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.responses.get(command, FakeResult(failed=False, stdout="ok"))


def _tunnel_pass(transport) -> CheckResult:
    return check_tunnel(transport, server="in")


def test_check_tunnel_awg_command_not_found() -> None:
    """awg: command not found -> fail with install action."""
    transport = FakeTransport(responses={"awg show": FakeResult(failed=True, stdout="awg: command not found")})
    result = check_tunnel(transport, server="in")
    assert result.status == "fail"
    assert "install" in (result.action or "")


def test_check_tunnel_awg_interface_missing() -> None:
    """awg show succeeds but no awg0 in output -> fail."""
    transport = FakeTransport(responses={"awg show": FakeResult(failed=False, stdout="interface: eth0\n")})
    result = check_tunnel(transport, server="in")
    assert result.status == "fail"


def test_check_tunnel_ok() -> None:
    """awg show with awg0 -> pass."""
    transport = FakeTransport(responses={"awg show": FakeResult(failed=False, stdout="interface: awg0\n")})
    result = check_tunnel(transport, server="in")
    assert result.status == "pass"


def test_check_tunnel_ssh_unreachable() -> None:
    """SSH transport error -> fail with unreachable summary and action."""
    transport = FakeTransport(error=Exception("SSH connection refused"))
    result = check_tunnel(transport, server="in")
    assert result.status == "fail"
    assert result.summary == "Сервер недоступен по SSH"
    assert "проверить доступ к серверу in" in (result.action or "")


def test_check_service_active() -> None:
    """systemctl is-active returns active -> pass."""
    transport = FakeTransport(responses={"systemctl is-active awg-quick@awg0": FakeResult(failed=False, stdout="active\n")})
    result = check_service(transport, server="in")
    assert result.status == "pass"


def test_check_service_inactive() -> None:
    """systemctl is-active returns inactive -> fail."""
    transport = FakeTransport(responses={"systemctl is-active awg-quick@awg0": FakeResult(failed=False, stdout="inactive\n")})
    result = check_service(transport, server="in")
    assert result.status == "fail"
    assert result.action is not None


def test_check_versions_runs_awg() -> None:
    """versions check runs awg --version."""
    transport = FakeTransport(responses={"awg --version": FakeResult(failed=False, stdout="2.2.0\n")})
    result = check_versions(transport, server="in")
    assert transport.commands[0] == "awg --version"
    assert result.status == "pass"


def test_check_firewall_runs_ufw() -> None:
    """firewall check runs ufw status verbose."""
    transport = FakeTransport(responses={"ufw status verbose": FakeResult(failed=False, stdout="Status: active\n")})
    result = check_firewall(transport, server="in")
    assert transport.commands[0] == "ufw status verbose"
    assert result.status == "pass"


def test_check_routes_runs_iptables() -> None:
    """routes check runs iptables nat -S POSTROUTING."""
    transport = FakeTransport(
        responses={"iptables -t nat -S POSTROUTING": FakeResult(failed=False, stdout="-A POSTROUTING -s 10.9.9.0/24 -j MASQUERADE\n")},
    )
    result = check_routes(transport, server="in")
    assert transport.commands[0] == "iptables -t nat -S POSTROUTING"
    assert result.status == "pass"


def test_check_scripts_missing_skips() -> None:
    """missing diagnostic scripts -> skip, not fail."""
    transport = FakeTransport(
        responses={
            "test -f /root/awg/manage_amneziawg.sh": FakeResult(failed=True, stdout=""),
            "test -f /root/awg/awg-routing.sh": FakeResult(failed=True, stdout=""),
        },
    )
    result = check_scripts(transport, server="in")
    assert result.status == "skip"
    assert "не найдены" in result.summary


def test_check_scripts_present_passes() -> None:
    """present diagnostic scripts -> pass."""
    transport = FakeTransport(
        responses={
            "test -f /root/awg/manage_amneziawg.sh": FakeResult(failed=False, stdout="ok\n"),
            "test -f /root/awg/awg-routing.sh": FakeResult(failed=False, stdout="ok\n"),
        },
    )
    result = check_scripts(transport, server="in")
    assert result.status == "pass"


def test_compute_verdict_red_for_tunnel_fail() -> None:
    """Tunnel fail -> red."""
    results = [
        CheckResult(check="tunnel", status="fail", summary="down", action=None, details={}),
        CheckResult(check="service", status="pass", summary="active", action=None, details={}),
    ]
    assert compute_verdict(results) == "red"


def test_compute_verdict_red_for_service_fail() -> None:
    """Service fail -> red."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={}),
        CheckResult(check="service", status="fail", summary="inactive", action=None, details={}),
    ]
    assert compute_verdict(results) == "red"


def test_compute_verdict_yellow_for_any_fail() -> None:
    """Any fail -> yellow (when tunnel/service pass)."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={}),
        CheckResult(check="service", status="pass", summary="active", action=None, details={}),
        CheckResult(check="firewall", status="fail", summary="bad", action=None, details={}),
    ]
    assert compute_verdict(results) == "yellow"


def test_compute_verdict_yellow_for_warn() -> None:
    """Any warn -> yellow."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={}),
        CheckResult(check="service", status="pass", summary="active", action=None, details={}),
        CheckResult(check="logs", status="warn", summary="slow", action=None, details={}),
    ]
    assert compute_verdict(results) == "yellow"


def test_compute_verdict_green_when_all_pass() -> None:
    """All pass -> green."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={}),
        CheckResult(check="service", status="pass", summary="active", action=None, details={}),
    ]
    assert compute_verdict(results) == "green"


def test_compute_verdict_green_when_skip() -> None:
    """Skips alone do not turn verdict yellow."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={}),
        CheckResult(check="scripts", status="skip", summary="missing", action=None, details={}),
    ]
    assert compute_verdict(results) == "green"


def test_run_diagnostics_all_checks_pass() -> None:
    """run_diagnostics returns green verdict with all checks run."""
    transport = FakeTransport(
        responses={
            "awg show": FakeResult(failed=False, stdout="interface: awg0\n"),
            "systemctl is-active awg-quick@awg0": FakeResult(failed=False, stdout="active\n"),
            "awg --version": FakeResult(failed=False, stdout="2.2.0\n"),
            "ufw status verbose": FakeResult(failed=False, stdout="Status: active\n"),
            "iptables -t nat -S POSTROUTING": FakeResult(failed=False, stdout="-A POSTROUTING\n"),
            "journalctl -u awg-quick@awg0 -n 50 --no-pager": FakeResult(failed=False, stdout="no errors\n"),
            "test -f /root/awg/manage_amneziawg.sh": FakeResult(failed=False, stdout="ok\n"),
            "test -f /root/awg/awg-routing.sh": FakeResult(failed=False, stdout="ok\n"),
        },
    )
    report = run_diagnostics(transport=transport, server="in", checks=None)
    assert isinstance(report, DiagnoseReport)
    assert report.server == "in"
    assert report.verdict == "green"
    assert len(report.results) == 7


def test_run_diagnostics_subset_checks() -> None:
    """run_diagnostics respects requested check subset."""
    transport = FakeTransport()
    report = run_diagnostics(transport=transport, server="in", checks=["tunnel"])
    assert len(report.results) == 1
    assert report.results[0].check == "tunnel"


def test_run_diagnostics_ssh_unreachable_red() -> None:
    """SSH unreachable -> red verdict with unreachable summary/action."""
    transport = FakeTransport(error=Exception("SSH connection refused"))
    report = run_diagnostics(transport=transport, server="in", checks=["tunnel"])
    assert report.verdict == "red"
    assert report.results[0].summary == "Сервер недоступен по SSH"
    assert "проверить доступ к серверу in" in (report.results[0].action or "")


def test_diagnose_report_to_json_valid() -> None:
    """JSON output is valid and contains expected keys."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="up", action=None, details={"output": "awg0\n"}),
    ]
    report = DiagnoseReport(server="in", results=results, verdict="green")
    text = diagnose_report_to_json(report)
    data = json.loads(text)
    assert data["server"] == "in"
    assert data["verdict"] == "green"
    assert len(data["checks"]) == 1
    assert data["checks"][0]["details"]["output"] == "awg0\n"


def test_format_diagnose_report_text_contains_verdict() -> None:
    """Human text contains verdict and check lines."""
    results = [
        CheckResult(check="tunnel", status="pass", summary="Tunnel awg0 is up", action=None, details={}),
    ]
    report = DiagnoseReport(server="in", results=results, verdict="green")
    text = format_diagnose_report_text(report, use_color=False)
    assert "VPN СЕРВЕР IN — ВСЁ РАБОТАЕТ" in text
    assert "✅ tunnel" in text
    assert "🟢 Всё в порядке, вмешательство не требуется." in text


def test_redaction_applied_after_command_output() -> None:
    """redact_text is applied immediately after command output in _exec path."""
    from awg_cascade_ctl.redact import REDACTED

    secret_output = "interface: awg0\nPresharedKey = SUPERSECRETPSK\n"
    transport = FakeTransport(responses={"awg show": FakeResult(failed=False, stdout=secret_output)})
    result = check_tunnel(transport, server="in")
    assert "SUPERSECRETPSK" not in str(result.details)
    assert REDACTED in str(result.details)
