"""Cascade check logic: handshake audit, E2E probe, JSON report."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from awg_cascade_ctl.config import CascadeConfig

HANDSHAKE_MAX_AGE_SEC = 180
REQUIRED_KEEPALIVE = 25
KEEPALIVE_MIN = 1
KEEPALIVE_MAX = 33
E2E_CURL_TIMEOUT_SEC = 5

SCHEMA_VERSION = "awg-ctl/check/v1"

# ANSI color constants (used only when use_color=True)
_ANSI = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def _paint(text: str, color: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def _demo_dump() -> str:
    """Return the hardcoded demo AWG dump (used when no real source is available)."""
    return (
        "awg0\tpub1\tpsk1\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )


def load_real_dump_target(
    cfg: CascadeConfig,
    target: Literal["in", "mid", "out"],
    key_path: str | None = None,
    key_passphrase: str | None = None,
) -> list[RawPeer]:
    """Load AWG peer data from a specific cascade server via SSH.

    Args:
        cfg: Loaded CascadeConfig containing server configuration.
        target: Which server to fetch the dump from (in, mid, or out).
        key_path: Optional explicit SSH key path (CLI override).
        key_passphrase: Optional passphrase for encrypted key.
    """
    from awg_cascade_ctl.ssh import SSHTransport, resolve_ssh_key_from_config

    server = cfg.servers[target]
    # Resolve key: explicit CLI → config → agent → auto-detect
    resolved_key, needs_passphrase = resolve_ssh_key_from_config(
        cfg, explicit_key_path=key_path
    )
    # If passphrase provided via CLI/env, use it; otherwise rely on agent
    effective_passphrase = key_passphrase if key_passphrase is not None else None

    # Emit key status for user-facing diagnostics
    if resolved_key:
        status = "encrypted" if needs_passphrase else "unencrypted"
        print(f"* SSH key: {resolved_key} ({status})", file=sys.stderr)
    else:
        print("* SSH key: ssh-agent / auto-detect (decrypted)", file=sys.stderr)

    transport = SSHTransport(
        host=server.host,
        port=server.port,
        user=server.username,
        key_path=resolved_key,
        passphrase=effective_passphrase,
        connect_timeout=cfg.timeouts.ssh_connect,
        command_timeout=cfg.timeouts.ssh_command,
    )
    try:
        transport.connect()
        return transport.run_awg_dump()
    finally:
        transport.close()


def load_real_dump_all(
    cfg: CascadeConfig,
    key_path: str | None = None,
    key_passphrase: str | None = None,
) -> list[RawPeer]:
    """Load AWG peer data from all cascade servers via SSH (in, mid, out)."""
    peers: list[RawPeer] = []
    for target in ("in", "mid", "out"):
        peers.extend(
            load_real_dump_target(
                cfg, target, key_path=key_path, key_passphrase=key_passphrase
            )
        )
    return peers


def load_real_dump(
    config_path: str | Path | None = None,
    dump_file: str | Path | None = None,
    server_target: Literal["in", "mid", "out", "all"] = "in",
    key_path: str | None = None,
    key_passphrase: str | None = None,
) -> list[RawPeer]:
    """Load AWG peer data from a real source.

    Priority:
    1. `dump_file` — local dump file (used for tests/CI).
    2. `config_path` — cascade.yaml → SSH to the selected server to fetch dump.
    3. Fallback — hardcoded demo data (backward compatible).
    """
    if dump_file:
        text = Path(dump_file).read_text(encoding="utf-8")
        return parse_awg_dump(text)
    if config_path:
        from awg_cascade_ctl.config import CascadeConfig

        cfg = CascadeConfig.load(config_path)
        if server_target == "all":
            return load_real_dump_all(
                cfg, key_path=key_path, key_passphrase=key_passphrase
            )
        return load_real_dump_target(
            cfg, server_target, key_path=key_path, key_passphrase=key_passphrase
        )
    return parse_awg_dump(_demo_dump())


def load_e2e_probes(
    config_path: str | Path | None = None,
    server_target: Literal["in", "mid", "out", "all"] = "in",
) -> list[E2EProbe]:
    """Run E2E IP probe from config's `ip_checker_url` via curl.

    Returns a list with one E2EProbe (source: awg-in) if probe succeeds,
    or an empty list if config is missing or probe fails. The probe runs
    only for the "in" server or for all servers; other targets skip it.
    """
    if server_target not in ("in", "all"):
        return []
    if not config_path:
        return []
    from awg_cascade_ctl.config import CascadeConfig

    cfg = CascadeConfig.load(config_path)
    url = cfg.network.ip_checker_url
    try:
        result = subprocess.run(
            ["curl", "-sS", "--max-time", str(E2E_CURL_TIMEOUT_SEC), url],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        ipv4 = result.stdout.strip()
        return [
            E2EProbe(
                source="awg-in",
                url=url,
                ipv4=ipv4,
                ok=bool(ipv4),
            )
        ]
    except (subprocess.TimeoutExpired, OSError):
        return []


class LinkAudit(BaseModel):
    """Audit of a single WireGuard link."""

    model_config = ConfigDict(frozen=True)

    interface: str
    peer_endpoint: str
    persistent_keepalive: int | None = None
    latest_handshake_age_sec: int | None = None
    keepalive_ok: bool = False
    handshake_fresh: bool = False
    ok: bool = False
    keepalive_status: Literal["OK", "OFF", "MISMATCH"] = "OK"
    keepalive_min: int | None = None
    keepalive_max: int | None = None


class E2EProbe(BaseModel):
    """Result of an end-to-end IP probe."""

    model_config = ConfigDict(frozen=True)

    source: Literal["awg-in", "awg-out"]
    url: str
    ipv4: str | None = None
    ok: bool = False


class CheckReport(BaseModel):
    """Machine-readable report for `awg-ctl check --json` (schema awg-ctl/check/v1)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_id: Literal["awg-ctl/check/v1"] = Field(
        default="awg-ctl/check/v1",
        alias="schema",
    )
    schema_version: Literal["1.0"] = "1.0"
    generated_at: str = ""
    cascade: str
    links: list[LinkAudit]
    e2e_probes: list[E2EProbe]
    ok: bool = False
    status: Literal["pass", "fail", "warning"] = "pass"
    source: Literal["demo", "dump_file", "ssh"] = "demo"


@dataclass(frozen=True)
class RawPeer:
    """Raw parsed peer line from `awg show all dump`."""

    interface: str
    peer_endpoint: str
    latest_handshake_unix: int
    persistent_keepalive: int | None


def parse_awg_dump(dump: str) -> list[RawPeer]:
    """Parse `awg show all dump` output into raw peer records.

    Peer lines have 9 tab-separated fields:
    interface, pubkey, psk, endpoint, allowed-ips, latest-handshake,
    transfer-rx, transfer-tx, persistent-keepalive.
    """
    peers: list[RawPeer] = []
    for line in dump.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            continue
        interface = parts[0]
        endpoint = parts[3]
        if ":" not in endpoint and endpoint != "(none)":
            continue
        handshake = parts[5]
        keepalive_str = parts[8]
        try:
            handshake_unix = int(handshake)
            keepalive_str = keepalive_str.strip()
            if keepalive_str in ("", "off", "Off", "OFF"):
                keepalive_val = 0
            else:
                try:
                    keepalive_val = int(keepalive_str)
                except ValueError:
                    continue
        except ValueError:
            continue
        peers.append(
            RawPeer(
                interface=interface,
                peer_endpoint=endpoint,
                latest_handshake_unix=handshake_unix,
                persistent_keepalive=keepalive_val,
            )
        )
    return peers


def audit_peers(
    peers: list[RawPeer],
    now_unix: int,
    max_age_sec: int = HANDSHAKE_MAX_AGE_SEC,
    required_keepalive: int | None = None,
    min_keepalive: int = KEEPALIVE_MIN,
    max_keepalive: int = KEEPALIVE_MAX,
) -> list[LinkAudit]:
    """Evaluate freshness and keepalive for each parsed peer."""
    audits: list[LinkAudit] = []
    for peer in peers:
        age = (
            None
            if peer.latest_handshake_unix == 0
            else now_unix - peer.latest_handshake_unix
        )
        handshake_fresh = age is not None and 0 <= age < max_age_sec
        kv = peer.persistent_keepalive
        if kv == 0:
            keepalive_ok = False
            keepalive_status = "OFF"
            keepalive_min_val = min_keepalive
            keepalive_max_val = max_keepalive
        elif required_keepalive is not None:
            keepalive_ok = kv == required_keepalive
            keepalive_status = "OK" if keepalive_ok else "MISMATCH"
            keepalive_min_val = required_keepalive
            keepalive_max_val = required_keepalive
        else:
            keepalive_ok = min_keepalive <= kv <= max_keepalive
            keepalive_status = "OK" if keepalive_ok else "MISMATCH"
            keepalive_min_val = min_keepalive
            keepalive_max_val = max_keepalive
        ok = keepalive_ok and handshake_fresh
        audits.append(
            LinkAudit(
                interface=peer.interface,
                peer_endpoint=peer.peer_endpoint,
                persistent_keepalive=peer.persistent_keepalive,
                latest_handshake_age_sec=age,
                keepalive_ok=keepalive_ok,
                keepalive_status=keepalive_status,
                keepalive_min=keepalive_min_val,
                keepalive_max=keepalive_max_val,
                handshake_fresh=handshake_fresh,
                ok=ok,
            )
        )
    return audits


def build_report(
    cascade: str,
    links: list[LinkAudit],
    e2e_probes: list[E2EProbe],
    source: Literal["demo", "dump_file", "ssh"] = "demo",
) -> CheckReport:
    """Assemble a CheckReport and compute the overall status."""
    ok = all(link.ok for link in links) and all(probe.ok for probe in e2e_probes)
    status: Literal["pass", "fail", "warning"] = "pass"
    if not ok:
        status = "fail"
    elif not links and not e2e_probes:
        status = "pass"
    return CheckReport(
        schema_id="awg-ctl/check/v1",
        schema_version="1.0",
        generated_at=datetime.now(UTC).isoformat(),
        cascade=cascade,
        links=links,
        e2e_probes=e2e_probes,
        ok=ok,
        status=status,
        source=source,
    )


def report_to_json(report: CheckReport) -> str:
    """Serialize a report to a single-line JSON string (strict mode)."""
    return json.dumps(report.model_dump(mode="json", by_alias=True))


def report_schema() -> dict:
    """Return the JSON Schema for the check report contract."""
    return CheckReport.model_json_schema()


def describe_check_plan(
    *,
    source: Literal["demo", "dump_file", "ssh"],
    server_target: Literal["in", "mid", "out", "all"],
    min_keepalive: int,
    max_keepalive: int,
    max_age_sec: int = HANDSHAKE_MAX_AGE_SEC,
    probe_url: str | None = None,
    probe_skipped_reason: str | None = None,
    dump_file: str | None = None,
) -> str:
    """Return a plain-English description of what `check` will verify.

    Pure function: performs no I/O. All numbers/URLs must come from the same
    values used by the actual check (threshold, keepalive range, probe URL,
    curl timeout constant).
    """
    lines: list[str] = []
    if source == "demo":
        lines.append("DEMO DATA: your servers are NOT being checked.")
    lines.append("awg-ctl check")

    if source == "ssh":
        if server_target == "all":
            src_text = "SSH, servers in, mid, out"
        else:
            src_text = f'SSH, server "{server_target}" (from cascade.yaml)'
    elif source == "dump_file":
        src_text = f"dump file {dump_file}" if dump_file else "dump file"
    else:
        src_text = "built-in demo data"

    lines.append(f"  Source:      {src_text}")
    lines.append(
        f"  Checks:      1) handshake is newer than {max_age_sec} s for every peer"
    )
    lines.append(
        f"               2) keepalive is enabled and within {min_keepalive}..{max_keepalive} s"
    )
    if probe_skipped_reason is not None:
        lines.append(
            f"               3) internet access: skipped ({probe_skipped_reason})"
        )
    else:
        lines.append(
            f"               3) internet access: curl {probe_url} (timeout {E2E_CURL_TIMEOUT_SEC} s)"
        )
    lines.append("  Not checked: traffic counters, allowed-ips, routes, services")
    lines.append("               (see `awg-ctl diagnose`)")

    return "\n".join(lines)


def format_report_text(report: CheckReport, use_color: bool = False) -> str:
    """Format a check report as human-readable text (summary-first)."""
    lines: list[str] = [f"awg-ctl check - {report.cascade}"]
    status_text = {"pass": "PASS", "fail": "FAIL", "warning": "WARN"}[report.status]
    status_color = {"pass": "green", "fail": "red", "warning": "yellow"}[report.status]
    lines.append(
        f"status: {_paint(status_text, status_color, use_color)} ({report.status})"
    )
    overall_text = "OK" if report.ok else "FAILED"
    overall_color = "green" if report.ok else "red"
    lines.append(f"overall: {_paint(overall_text, overall_color, use_color)}")
    lines.append(f"source: {report.source}")
    lines.append(f"generated_at: {report.generated_at}")
    lines.append("")

    if report.links:
        lines.append("Links:")
        ok_count = sum(1 for link in report.links if link.ok)
        lines.append(f"  {ok_count}/{len(report.links)} ok")
        for link in report.links:
            ka_text = link.keepalive_status
            if link.keepalive_status == "MISMATCH":
                ka_text = f"MISMATCH (got {link.persistent_keepalive}, expected {link.keepalive_min}..{link.keepalive_max})"
            lines.append(
                f"  {link.interface} -> {link.peer_endpoint}: "
                f"keepalive={ka_text}, "
                f"handshake={'fresh' if link.handshake_fresh else 'STALE'}, "
                f"ok={'yes' if link.ok else 'no'}"
            )
    else:
        lines.append("Links: 0 links")

    lines.append("")
    lines.append("E2E probes:")
    if report.e2e_probes:
        ok_probes = sum(1 for probe in report.e2e_probes if probe.ok)
        lines.append(f"  {ok_probes}/{len(report.e2e_probes)} ok")
        for probe in report.e2e_probes:
            lines.append(
                f"  {probe.source} ({probe.url}): {probe.ipv4 or 'n/a'}, "
                f"ok={'yes' if probe.ok else 'no'}"
            )
    else:
        lines.append("  none")

    return "\n".join(lines)
