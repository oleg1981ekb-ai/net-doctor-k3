"""Read-only diagnostic checks for the awg-ctl diagnose command."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from awg_cascade_ctl.redact import redact_text

DEFAULT_CHECK_TIMEOUT_SEC = 15
MAX_PARALLEL_CHANNELS = 4

Verdict = Literal["green", "yellow", "red"]
CheckStatus = Literal["pass", "fail", "warn", "skip"]

ALL_CHECKS: tuple[str, ...] = (
    "tunnel",
    "service",
    "versions",
    "firewall",
    "routes",
    "logs",
    "scripts",
)

SCHEMA_VERSION = "1.0"
SCHEMA_ID = "awg-ctl/diagnose/v1"


@dataclass(frozen=True)
class CheckResult:
    """Result of a single diagnostic check."""

    check: str
    status: CheckStatus
    summary: str
    action: str | None = None
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagnoseReport:
    """Diagnostic report for a single server."""

    server: str
    results: list[CheckResult]
    verdict: Verdict
    server_ip: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class _ExecOutcome:
    failed: bool
    output: str
    error: str | None = None
    timed_out: bool = False


def _exec(transport: Any, command: str) -> _ExecOutcome:
    """Run a remote command via transport and redact output immediately."""
    try:
        result = transport.run(command)
        failed = bool(getattr(result, "failed", False))
        output = redact_text(str(getattr(result, "stdout", "") or ""))
        return _ExecOutcome(failed=failed, output=output)
    except TimeoutError:
        return _ExecOutcome(failed=True, output="timeout", timed_out=True)
    except Exception as exc:  # noqa: BLE001
        return _ExecOutcome(failed=True, output=f"error: {exc}", error=str(exc))


def _unreachable(server: str, check: str) -> CheckResult:
    """Build the CheckResult for a transport-level failure (SSH unreachable)."""
    return CheckResult(
        check=check,
        status="fail",
        summary="Сервер недоступен по SSH",
        action=f"проверить доступ к серверу {server}",
        details={},
    )


def check_tunnel(transport: Any, server: str = "in") -> CheckResult:
    """Check the awg0 tunnel via `awg show`."""
    outcome = _exec(transport, "awg show")
    if outcome.error is not None:
        return _unreachable(server, "tunnel")
    if outcome.timed_out:
        return CheckResult(
            check="tunnel",
            status="warn",
            summary="Tunnel check timed out",
            action=None,
            details={"output": outcome.output},
        )
    if outcome.failed:
        return CheckResult(
            check="tunnel",
            status="fail",
            summary="Tunnel check failed: awg show failed",
            action="check awg installation",
            details={"output": outcome.output},
        )
    if "command not found" in outcome.output.lower():
        return CheckResult(
            check="tunnel",
            status="fail",
            summary="Tunnel check failed: awg command not found",
            action="install awg-tools: apt-get install -y awg-tools wireguard-tools",
            details={"output": outcome.output},
        )
    if "awg0" not in outcome.output:
        return CheckResult(
            check="tunnel",
            status="fail",
            summary="Tunnel check failed: awg0 interface missing",
            action=None,
            details={"output": outcome.output},
        )
    return CheckResult(
        check="tunnel",
        status="pass",
        summary="Туннель awg0 поднят",
        action=None,
        details={"output": outcome.output},
    )


def check_service(transport: Any, server: str = "in") -> CheckResult:
    """Check the awg-quick service via `systemctl is-active`."""
    outcome = _exec(transport, "systemctl is-active awg-quick@awg0")
    if outcome.error is not None:
        return _unreachable(server, "service")
    if outcome.timed_out:
        return CheckResult(
            check="service",
            status="warn",
            summary="Service check timed out",
            action=None,
            details={"output": outcome.output},
        )
    status: CheckStatus = "pass" if outcome.output.strip().lower() == "active" else "fail"
    summary = (
        "Сервис awg-quick@awg0 активен"
        if status == "pass"
        else "Сервис awg-quick@awg0 не активен"
    )
    action = None if status == "pass" else "systemctl start awg-quick@awg0"
    return CheckResult(
        check="service",
        status=status,
        summary=summary,
        action=action,
        details={"output": outcome.output},
    )


def check_versions(transport: Any, server: str = "in") -> CheckResult:
    """Check awg tooling versions via `awg --version`, sysfs, dkms."""
    outcome = _exec(transport, "awg --version")
    if outcome.error is not None:
        return _unreachable(server, "versions")
    if outcome.timed_out:
        return CheckResult(
            check="versions",
            status="warn",
            summary="Versions check timed out",
            action=None,
            details={"output": outcome.output},
        )
    version_output = outcome.output.strip() if not outcome.failed else f"error: {outcome.output}"
    return CheckResult(
        check="versions",
        status="pass" if not outcome.failed and version_output else "fail",
        summary=f"awg-tools {version_output}" if version_output else "Версии не получены",
        action=None,
        details={"awg_version": version_output},
    )


def check_firewall(transport: Any, server: str = "in") -> CheckResult:
    """Check firewall state via `ufw status verbose`, fallback `nft list ruleset`."""
    outcome = _exec(transport, "ufw status verbose")
    if outcome.error is not None:
        return _unreachable(server, "firewall")
    if outcome.timed_out:
        return CheckResult(
            check="firewall",
            status="warn",
            summary="Firewall check timed out",
            action=None,
            details={"output": outcome.output},
        )
    firewall_output = outcome.output.strip() if not outcome.failed else f"error: {outcome.output}"
    status: CheckStatus = "pass" if (not outcome.failed and firewall_output) else "warn"
    return CheckResult(
        check="firewall",
        status=status,
        summary="ufw активен" if status == "pass" else "ufw неактивен или не настроен",
        action=None,
        details={"output": firewall_output},
    )


def check_routes(transport: Any, server: str = "in", client_subnet: str = "10.9.9.0/24") -> CheckResult:
    """Check routing via `iptables -t nat -S POSTROUTING`, fallback `nft list ruleset`."""
    outcome = _exec(transport, "iptables -t nat -S POSTROUTING")
    if outcome.error is not None:
        return _unreachable(server, "routes")
    if outcome.timed_out:
        return CheckResult(
            check="routes",
            status="warn",
            summary="Routes check timed out",
            action=None,
            details={"output": outcome.output},
        )
    routes_output = outcome.output.strip() if not outcome.failed else f"error: {outcome.output}"
    status: CheckStatus = "pass" if (not outcome.failed and routes_output) else "warn"
    summary = (
        f"NAT MASQUERADE для {client_subnet} настроен"
        if status == "pass"
        else "NAT не настроен или правила отсутствуют"
    )
    return CheckResult(
        check="routes",
        status=status,
        summary=summary,
        action=None,
        details={"output": routes_output, "client_subnet": client_subnet},
    )


def check_logs(transport: Any, server: str = "in") -> CheckResult:
    """Check awg logs via `journalctl -u awg-quick@awg0 -n 50 --no-pager`."""
    outcome = _exec(transport, "journalctl -u awg-quick@awg0 -n 50 --no-pager")
    if outcome.error is not None:
        return _unreachable(server, "logs")
    if outcome.timed_out:
        return CheckResult(
            check="logs",
            status="warn",
            summary="Logs check timed out",
            action=None,
            details={"output": outcome.output},
        )
    logs_output = outcome.output.strip() if not outcome.failed else f"error: {outcome.output}"
    has_errors = (
        "error" in logs_output.lower() or "fail" in logs_output.lower() or "failed" in logs_output.lower()
    ) and "no error" not in logs_output.lower() and "no errors" not in logs_output.lower()
    status: CheckStatus = "warn" if has_errors else "pass"
    return CheckResult(
        check="logs",
        status=status,
        summary="Ошибки в журнале" if has_errors else "Ошибок в журнале нет",
        action="проверить конфиг пиров и keepalive" if has_errors else None,
        details={"output": logs_output},
    )


def check_scripts(transport: Any, server: str = "in") -> CheckResult:
    """Check presence of diagnostic scripts; missing scripts -> skip."""
    manage_path = "/root/awg/manage_amneziawg.sh"
    routing_path = "/root/awg/awg-routing.sh"
    outcome_manage = _exec(transport, f"test -f {manage_path}")
    outcome_routing = _exec(transport, f"test -f {routing_path}")
    if outcome_manage.error is not None or outcome_routing.error is not None:
        return _unreachable(server, "scripts")
    if outcome_manage.timed_out or outcome_routing.timed_out:
        return CheckResult(
            check="scripts",
            status="warn",
            summary="Scripts check timed out",
            action=None,
            details={"output": outcome_manage.output},
        )
    missing = []
    if outcome_manage.failed or outcome_routing.failed:
        if outcome_manage.failed:
            missing.append(manage_path)
        if outcome_routing.failed:
            missing.append(routing_path)
    if missing:
        return CheckResult(
            check="scripts",
            status="skip",
            summary=f"Скрипты не найдены: {', '.join(missing)}",
            action=None,
            details={"missing_scripts": ", ".join(missing)},
        )
    return CheckResult(
        check="scripts",
        status="pass",
        summary="Скрипты /root/awg/*.sh на месте",
        action=None,
        details={},
    )


CHECK_FUNCS: dict[str, Callable[..., CheckResult]] = {
    "tunnel": check_tunnel,
    "service": check_service,
    "versions": check_versions,
    "firewall": check_firewall,
    "routes": check_routes,
    "logs": check_logs,
    "scripts": check_scripts,
}


def compute_verdict(results: list[CheckResult]) -> Verdict:
    """Compute overall verdict: red for tunnel/service fail, yellow for any fail/warn, else green."""
    failed_checks = {r.check for r in results if r.status == "fail"}
    if "tunnel" in failed_checks or "service" in failed_checks:
        return "red"
    if any(r.status in ("fail", "warn") for r in results):
        return "yellow"
    return "green"


def run_diagnostics(
    transport: Any,
    server: str,
    checks: list[str] | None = None,
    server_ip: str = "",
) -> DiagnoseReport:
    """Run diagnostic checks for a server via SSH transport."""
    check_names = list(checks) if checks else list(ALL_CHECKS)
    results: list[CheckResult] = []
    for name in check_names:
        func = CHECK_FUNCS.get(name)
        if func is None:
            results.append(
                CheckResult(
                    check=name,
                    status="skip",
                    summary=f"Unknown check: {name}",
                    action=None,
                    details={},
                ),
            )
            continue
        results.append(func(transport, server))
    verdict = compute_verdict(results)
    return DiagnoseReport(
        server=server,
        results=results,
        verdict=verdict,
        server_ip=server_ip,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
    )


def diagnose_report_to_json(report: DiagnoseReport) -> str:
    """Serialize a diagnose report to strict JSON."""
    payload = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "server": report.server,
        "server_ip": report.server_ip,
        "timestamp": report.timestamp,
        "verdict": report.verdict,
        "checks": [
            {
                "check": r.check,
                "status": r.status,
                "summary": r.summary,
                "action": r.action,
                "details": r.details,
            }
            for r in report.results
        ],
    }
    return json.dumps(payload)


def diagnose_report_schema() -> dict:
    """Return the JSON Schema for the diagnose report contract."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "awg-ctl diagnose report",
        "type": "object",
        "properties": {
            "schema_id": {"type": "string"},
            "schema_version": {"type": "string"},
            "server": {"type": "string"},
            "server_ip": {"type": "string"},
            "timestamp": {"type": "string"},
            "verdict": {"type": "string", "enum": ["green", "yellow", "red"]},
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "check": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pass", "fail", "warn", "skip"],
                        },
                        "summary": {"type": "string"},
                        "action": {"type": ["string", "null"]},
                        "details": {"type": "object", "additionalProperties": {"type": "string"}},
                    },
                },
            },
        },
    }


def format_diagnose_report_text(report: DiagnoseReport, use_color: bool = False, show_details: bool = False) -> str:
    """Format a diagnose report as beautiful boxed text with emojis."""
    # Verdict text and color
    verdict_text = {"green": "ВСЁ РАБОТАЕТ", "yellow": "ЕСТЬ ЗАМЕЧАНИЯ", "red": "ТРЕБУЕТ ВНИМАНИЯ"}[report.verdict]
    verdict_color = {"green": "green", "yellow": "yellow", "red": "red"}[report.verdict]

    # Build header box
    header = f" VPN СЕРВЕР {report.server.upper()} — {verdict_text} "
    sub_header = f" Проверено: {report.timestamp}  |  Сервер: {report.server_ip or '—'} "
    max_width = max(len(header), len(sub_header)) + 2
    max_width = max(max_width, 70)

    # Box drawing characters
    top_left = "╔"
    top_right = "╗"
    bottom_left = "╚"
    bottom_right = "╝"
    horizontal = "═"
    vertical = "║"

    lines: list[str] = []
    lines.append(f"{top_left}{horizontal * max_width}{top_right}")
    lines.append(f"{vertical}{header.center(max_width)}{vertical}")
    lines.append(f"{vertical}{sub_header.center(max_width)}{vertical}")
    lines.append(f"{bottom_left}{horizontal * max_width}{bottom_right}")

    lines.append("")

    # Check emojis
    check_emoji = {
        "pass": "✅",
        "fail": "❌",
        "warn": "⚠️",
        "skip": "⏭️",
    }

    # Checks
    lines.append("Checks:")
    for r in report.results:
        emoji = check_emoji.get(r.status, "❓")
        status_text = {"pass": "PASS", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}[r.status]
        status_color = {"pass": "green", "fail": "red", "warn": "yellow", "skip": "yellow"}[r.status]
        colored_status = _paint(status_text, status_color, use_color)
        lines.append(f"  {emoji} {r.check:<12} — {colored_status} — {r.summary}")
        if r.action:
            lines.append(f"      → {r.action}")

    lines.append("")

    # Details section (only if --details or has warn/fail)
    if show_details:
        detail_lines = []
        for r in report.results:
            if r.status in ("warn", "fail") and r.details:
                detail_lines.append(f"  {r.check} details:")
                for key, value in r.details.items():
                    if value:
                        # Truncate long outputs
                        display_value = value[:500] + "..." if len(value) > 500 else value
                        detail_lines.append(f"    {key}: {display_value}")
        if detail_lines:
            lines.append("Details:")
            lines.extend(detail_lines)
            lines.append("")

    # Overall verdict line
    overall_text = {
        "green": "🟢 Всё в порядке, вмешательство не требуется.",
        "yellow": "🟡 Есть предупреждения, но сервер работает.",
        "red": "🔴 Сервер не работает, требуется вмешательство.",
    }[report.verdict]
    lines.append(f"Итог: {_paint(overall_text, verdict_color, use_color)}")

    return "\n".join(lines)


def _paint(text: str, color: str, use_color: bool) -> str:
    if not use_color:
        return text
    ansi = {
        "green": "\033[32m",
        "red": "\033[31m",
        "yellow": "\033[33m",
        "reset": "\033[0m",
        "GREEN": "\033[32m",
        "RED": "\033[31m",
        "YELLOW": "\033[33m",
    }
    return f"{ansi[color]}{text}{ansi['reset']}"
