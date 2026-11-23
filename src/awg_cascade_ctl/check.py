"""Cascade check logic: handshake audit, E2E probe, JSON report."""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from paramiko import AuthenticationException, PasswordRequiredException
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


class SSHDumpError(RuntimeError):
    """Raised when fetching an AWG dump over SSH fails.

    Carries structured metadata so callers can emit a clean one-line
    error instead of a full traceback. Subclasses ``RuntimeError`` so the
    existing ``--ask-pass`` handling keeps working; ``str(exc)`` mirrors the
    wrapped error ``str`` (e.g. it still contains ``"encrypted"``).
    """

    def __init__(
        self,
        *,
        server: str,
        host: str,
        port: int,
        key_path: str | None,
        exc: BaseException,
    ) -> None:
        super().__init__(str(exc))
        self.server = server
        self.host = host
        self.port = port
        self.key_path = key_path
        self.exc = exc


def describe_ssh_error(
    exc: BaseException,
    server_name: str,
    host: str,
    port: int,
    key_path: str | None,
) -> str:
    """Return a single-line English error string for an SSH failure.

    The message contains no traceback, no passphrase, and no key material.
    Walks the ``__cause__`` chain so wrapped ``RuntimeError`` messages
    (e.g. from ``run_awg_dump``) are reduced to their underlying cause.
    """
    seen: set[int] = set()
    current = exc
    while id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PasswordRequiredException):
            kp = key_path if key_path else "ssh-agent / auto-detect"
            return (
                f"SSH key for server {server_name} is encrypted: {kp}. "
                "Use --ask-pass, set SSH_KEY_PASSPHRASE, or add the key to ssh-agent."
            )
        if isinstance(current, AuthenticationException):
            kp = key_path if key_path else "ssh-agent / auto-detect"
            return f"SSH authentication failed for server {server_name} ({host}) with key {kp}."
        if isinstance(current, FileNotFoundError):
            return f"SSH key file not found for server {server_name}: {key_path}"
        if isinstance(
            current,
            (
                OSError,
                socket.timeout,
                TimeoutError,
            ),
        ):
            return f"Cannot connect to server {server_name} ({host}:{port}): {current}"
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        break
    return f"SSH error for server {server_name} ({host}): {exc}"


def _demo_dump() -> str:
    """Return the hardcoded demo AWG dump (used when no real source is available)."""
    return (
        "awg0\tpub1\tpsk1\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )


def _key_path_from_config(
    cfg: CascadeConfig,
    target: Literal["in", "mid", "out"],
    explicit_key_path: str | None,
) -> str | None:
    """Return the SSH key path for *target*.

    Priority (explicit CLI always wins):
    1. ``explicit_key_path`` – from CLI ``--key-path`` (overrides all).
    2. ``server.ssh_key_path`` – from ``cascade.yaml`` for the target server.
    3. First ``ssh_key_path`` from servers in order ("in", "mid", "out").
    4. ``None`` – let SSHTransport auto‑detect (agent / defaults).
    """
    if explicit_key_path is not None and isinstance(explicit_key_path, str):
        return os.path.expanduser(explicit_key_path)
    if target in cfg.servers and cfg.servers[target].ssh_key_path is not None:
        return os.path.expanduser(cfg.servers[target].ssh_key_path)
    # Fallback: first server with ssh_key_path in order
    for fb in ("in", "mid", "out"):
        if fb in cfg.servers and cfg.servers[fb].ssh_key_path is not None:
            return os.path.expanduser(cfg.servers[fb].ssh_key_path)
    return None


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
    from awg_cascade_ctl.ssh import SSHTransport

    server = cfg.servers[target]
    # Resolve key: explicit CLI → config for target server → auto-detect
    resolved_key = _key_path_from_config(cfg, target, key_path)

    # If passphrase provided via CLI/env, use it; otherwise rely on agent
    effective_passphrase = key_passphrase if key_passphrase is not None else None

    # Emit key status for user-facing diagnostics
    if resolved_key is not None:
        from awg_cascade_ctl.ssh import _key_needs_passphrase

        if not Path(resolved_key).is_file():
            raise SSHDumpError(
                server=target,
                host=server.host,
                port=server.port,
                key_path=resolved_key,
                exc=FileNotFoundError(resolved_key),
            )

        needs_passphrase = _key_needs_passphrase(resolved_key)
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
        try:
            return transport.run_awg_dump()
        except RuntimeError as exc:
            raise SSHDumpError(
                server=target,
                host=server.host,
                port=server.port,
                key_path=resolved_key,
                exc=exc,
            ) from exc
    except SSHDumpError:
        raise
    except RuntimeError as exc:
        raise SSHDumpError(
            server=target,
            host=server.host,
            port=server.port,
            key_path=resolved_key,
            exc=exc,
        ) from exc
    except Exception as exc:
        raise SSHDumpError(
            server=target,
            host=server.host,
            port=server.port,
            key_path=resolved_key,
            exc=exc,
        ) from exc
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
    keepalive_passive: bool = False
    handshake_fresh: bool = False
    ok: bool = False
    keepalive_status: Literal["OK", "OFF", "MISMATCH"] = "OK"
    keepalive_min: int | None = None
    keepalive_max: int | None = None
    role: Literal["link", "client"] = "link"


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
    allowed_ips: str = ""


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
        allowed_ips = parts[4]
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
                allowed_ips=allowed_ips,
                latest_handshake_unix=handshake_unix,
                persistent_keepalive=keepalive_val,
            )
        )
    return peers


def endpoint_host(endpoint: str) -> str | None:
    """Return the host without port from a WireGuard endpoint string.

    "1.2.3.4:51820" -> "1.2.3.4"; "[2001:db8::1]:51820" -> "2001:db8::1";
    "(none)" or unparseable -> None.
    """
    if endpoint == "(none)":
        return None
    if endpoint.startswith("["):
        end = endpoint.find("]")
        if end == -1:
            return None
        host = endpoint[1:end]
        return host if host else None
    if ":" not in endpoint:
        return None
    host = endpoint.rsplit(":", 1)[0]
    return host if host else None


def _hosts_match(a: str, b: str) -> bool:
    """Compare two host strings, preferring IP-aware equality when both parse as IPs."""
    try:
        return ipaddress.ip_address(a) == ipaddress.ip_address(b)
    except ValueError:
        return a == b


def has_default_route(allowed_ips: str) -> bool:
    """Return True if any comma-separated allowed-ips entry is a default route (prefixlen == 0).

    Split on comma, strip whitespace, skip empty/"(none)"/invalid entries via ipaddress.ip_network(strict=False)
    catching ValueError, return True if any prefixlen == 0. Invalid entries and "(none)" ignored without exceptions.
    Empty string -> False.
    """
    for entry in allowed_ips.split(","):
        entry = entry.strip()
        if not entry or entry == "(none)":
            continue
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if network.prefixlen == 0:
            return True
    return False


def classify_peer(
    peer: RawPeer, link_hosts: frozenset[str]
) -> Literal["link", "client"]:
    """Classify a peer as a cascade link or a client.

    Returns "link" if has_default_route(peer.allowed_ips) OR
    endpoint_host(peer.peer_endpoint) is in link_hosts; else "client".
    If both sides are IP addresses, compare via ipaddress.ip_address;
    otherwise compare plain strings.
    """
    if has_default_route(peer.allowed_ips):
        return "link"
    host = endpoint_host(peer.peer_endpoint)
    if host is None:
        return "client"
    for link_host in link_hosts:
        if _hosts_match(host, link_host):
            return "link"
    return "client"


def audit_peers(
    peers: list[RawPeer],
    now_unix: int,
    max_age_sec: int = HANDSHAKE_MAX_AGE_SEC,
    required_keepalive: int | None = None,
    min_keepalive: int = KEEPALIVE_MIN,
    max_keepalive: int = KEEPALIVE_MAX,
    link_hosts: frozenset[str] | None = None,
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
        role: Literal["link", "client"] = (
            "link" if link_hosts is None else classify_peer(peer, link_hosts)
        )
        keepalive_passive = False
        if role == "link" and link_hosts is not None and kv == 0 and handshake_fresh:
            keepalive_ok = True
            keepalive_passive = True
        ok = keepalive_ok and handshake_fresh
        audits.append(
            LinkAudit(
                interface=peer.interface,
                peer_endpoint=peer.peer_endpoint,
                persistent_keepalive=peer.persistent_keepalive,
                latest_handshake_age_sec=age,
                keepalive_ok=keepalive_ok,
                keepalive_passive=keepalive_passive,
                handshake_fresh=handshake_fresh,
                ok=ok,
                keepalive_status=keepalive_status,
                keepalive_min=keepalive_min_val,
                keepalive_max=keepalive_max_val,
                role=role,
            )
        )
    return audits


def build_report(
    cascade: str,
    links: list[LinkAudit],
    e2e_probes: list[E2EProbe],
    source: Literal["demo", "dump_file", "ssh"] = "demo",
    roles_active: bool = False,
) -> CheckReport:
    """Assemble a CheckReport and compute the overall status."""
    if roles_active:
        link_audits = [link for link in links if link.role == "link"]
        ok = all(link.ok for link in link_audits) and all(
            probe.ok for probe in e2e_probes
        )
        if not link_audits:
            ok = False
    else:
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
    """Serialize a report to a single-line JSON string (strict mode).

    schema_version flows through from the CheckReport model default ("1.0").
    """
    data = report.model_dump(mode="json", by_alias=True)
    return json.dumps(data)


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
        f"               2) keepalive is within {min_keepalive}..{max_keepalive} s"
    )
    if source == "ssh":
        lines[-1] = (
            f"               2) keepalive is within {min_keepalive}..{max_keepalive} s "
            f"(OFF is accepted on the receiving end of a link while its handshake is fresh)"
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
    result_text = "OK" if report.ok else "FAILED"
    result_color = "green" if report.ok else "red"
    lines.append(f"Result: {_paint(result_text, result_color, use_color)}")
    lines.append(f"source: {report.source}")
    lines.append(f"generated_at: {report.generated_at}")
    lines.append("")

    if report.links:
        lines.append("Links:")
        link_count = sum(1 for link in report.links if link.role == "link")
        ok_count = sum(1 for link in report.links if link.role == "link" and link.ok)
        lines.append(f"  {ok_count}/{link_count} ok")
        if link_count == 0:
            lines.append("no cascade links found")
        passive_shown = False
        for link in report.links:
            ka_text = link.keepalive_status
            if link.keepalive_status == "MISMATCH":
                ka_text = f"MISMATCH (got {link.persistent_keepalive}, expected {link.keepalive_min}..{link.keepalive_max})"
            passive_marker = ""
            if link.keepalive_passive:
                passive_marker = " (receiving end)"
                passive_shown = True
            link_line = (
                f"  {link.interface} -> {link.peer_endpoint}: "
                f"keepalive={ka_text}{passive_marker}, "
                f"handshake={'fresh' if link.handshake_fresh else 'STALE'}, "
                f"ok={'yes' if link.ok else 'no'}"
            )
            if link.role == "client":
                link_line += " [client, not counted]"
            lines.append(link_line)
        if passive_shown:
            lines.append(
                "  note: keepalive=OFF on a link with a fresh handshake is normal on the receiving end (the other server sends the keepalives)."
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


def _is_tty() -> bool:
    """Return True when stdout is a terminal (emoji allowed)."""
    try:
        return sys.stdout.isatty()
    except OSError:
        return False


def format_summary(report: CheckReport, status: str | None = None) -> str:
    """Render the single-line светофор summary for a check report.

    TTY: emoji + text; non-TTY: ASCII bracketed status.
    Always ends with ``exit: N``. Counter N/N ok over counted links only
    (role=="link", clients excluded).
    """
    is_tty = _is_tty()

    if status is None:
        status = report.status

    status_lower = status.lower() if isinstance(status, str) else "unknown"
    if status_lower == "warning":
        status_lower = "warn"

    if status_lower == "pass":
        status_disp = "🟢 PASS" if is_tty else "[PASS]"
        exit_code = 0
    elif status_lower == "warn":
        status_disp = "🟡 WARN" if is_tty else "[WARN]"
        exit_code = 3
    elif status_lower == "fail":
        status_disp = "🔴 FAIL" if is_tty else "[FAIL]"
        exit_code = 1
    else:
        status_disp = "⚪ UNKNOWN" if is_tty else "[UNKNOWN]"
        exit_code = 3

    link_count = sum(1 for link in report.links if link.role == "link")
    ok_count = sum(1 for link in report.links if link.role == "link" and link.ok)

    line = f"{status_disp}   {ok_count}/{link_count} ok   exit: {exit_code}"
    lines: list[str] = [line]

    if status_lower in ("fail", "warn"):
        added = 0
        for link in report.links:
            if added >= 3:
                break
            if link.role != "link" or link.ok:
                continue
            parts = [
                f"   {link.interface} -> {link.peer_endpoint}",
                f"keepalive={link.keepalive_status}",
                f"handshake={'fresh' if link.handshake_fresh else 'STALE'}",
            ]
            lines.append(" ".join(parts))
            added += 1

    if status_lower == "unknown":
        lines.append("   reason: SSH error")

    return "\n".join(lines)


def format_verbose(report: CheckReport, level: int) -> str:
    """Render verbose output for a check report.

    level=1: светофор line + blank line + Links (counted) section + Clients
    (not counted) section + E2E section + ℹ note line.
    level=2: level=1 PLUS per-peer introspect block.
    """
    is_tty = _is_tty()
    lines: list[str] = []

    # Fresh line with separator
    lines.append("──────────────────────────────────────────────────")

    # Status line
    if report.status == "pass":
        status_disp = "🟢 PASS" if is_tty else "[PASS]"
        exit_code = 0
    elif report.status == "warning":
        status_disp = "🟡 WARN" if is_tty else "[WARN]"
        exit_code = 3
    elif report.status == "fail":
        status_disp = "🔴 FAIL" if is_tty else "[FAIL]"
        exit_code = 1
    else:
        status_disp = "⚪ UNKNOWN" if is_tty else "[UNKNOWN]"
        exit_code = 3

    link_count = sum(1 for link in report.links if link.role == "link")
    ok_count = sum(1 for link in report.links if link.role == "link" and link.ok)
    lines.append(f"{status_disp}   {ok_count}/{link_count} ok   exit: {exit_code}")
    lines.append("")

    # Links (counted) section
    counted_links = [l for l in report.links if l.role == "link"]
    client_links = [l for l in report.links if l.role == "client"]

    lines.append("Links (counted)")
    ka_w = max(
        [len(l.keepalive_status) for l in counted_links] + [9]
    )  # "keepalive" is 9
    hs_w = max(
        [len("fresh" if l.handshake_fresh else "STALE") for l in counted_links] + [5]
    )

    if counted_links:
        for link in counted_links:
            ka_text = link.keepalive_status
            if link.keepalive_status == "MISMATCH":
                ka_text = f"MISMATCH (got {link.persistent_keepalive}, expected {link.keepalive_min}..{link.keepalive_max})"
            passive_marker = " (receiving end)" if link.keepalive_passive else ""
            hs = "fresh" if link.handshake_fresh else "STALE"
            ok_mark = "✅" if is_tty else "OK"
            fail_mark = "❌" if is_tty else "FAIL"
            warn_mark = "⚠️" if is_tty else "WARN"
            status_mark = (
                ok_mark
                if link.ok
                else (warn_mark if link.keepalive_status != "OK" else fail_mark)
            )
            ka_field = ka_text.ljust(ka_w)
            hs_field = hs.ljust(hs_w)
            lines.append(
                f"  {link.interface} -> {link.peer_endpoint}  "
                f"keepalive={ka_field}  handshake={hs_field}  {status_mark}{passive_marker}"
            )
    else:
        lines.append("  none")

    lines.append("")

    # Clients (not counted) section — always shown
    lines.append("Clients (not counted)")
    if client_links:
        for link in client_links:
            ok_mark = "⚪" if is_tty else "OK"
            lines.append(f"  {link.interface} -> {link.peer_endpoint}  {ok_mark}")
    else:
        lines.append("  none")

    lines.append("")

    # E2E section
    lines.append("E2E")
    if report.e2e_probes:
        for probe in report.e2e_probes:
            ok_mark = "✅" if is_tty else "OK"
            fail_mark = "❌" if is_tty else "FAIL"
            mark = ok_mark if probe.ok else fail_mark
            lines.append(
                f"  {probe.source} ({probe.url}): {probe.ipv4 or 'n/a'}, ok={'yes' if probe.ok else 'no'} {mark}"
            )
    else:
        lines.append("  — skipped (not in/all)")
    lines.append("")

    # ℹ note line (single line)
    passive_shown = any(l.keepalive_passive for l in counted_links)
    if passive_shown:
        lines.append(
            "ℹ note: keepalive=OFF on a link with a fresh handshake is normal on the receiving end (the other server sends the keepalives)."
        )
    else:
        lines.append("ℹ note: —")

    # level=2: per-peer introspect block
    if level >= 2:
        lines.append("")
        lines.append("── Introspect (debug) ──")
        for link in report.links:
            lines.append(f"  [{link.role}] {link.interface} -> {link.peer_endpoint}")
            lines.append(
                f"    raw: {link.interface}<TAB>..."
                f"<TAB>{link.peer_endpoint}<TAB>...<TAB>keepalive={link.persistent_keepalive}"
            )
            lines.append(
                f"    parse: keepalive_min={link.keepalive_min} "
                f"keepalive_max={link.keepalive_max} "
                f"handshake_age={link.latest_handshake_age_sec}"
            )
            lines.append(
                "    file:line: src/awg_cascade_ctl/check.py:379 (parse_awg_dump), "
                "src/awg_cascade_ctl/check.py:493 (audit_peers)"
            )
            lines.append("    cmd: awg show all dump")
            lines.append("")

    return "\n".join(lines)
