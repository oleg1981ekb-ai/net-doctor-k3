"""Cascade check logic: handshake audit, E2E probe, JSON report."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

HANDSHAKE_MAX_AGE_SEC = 180
REQUIRED_KEEPALIVE = 25


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


class E2EProbe(BaseModel):
    """Result of an end-to-end IP probe."""

    model_config = ConfigDict(frozen=True)

    source: Literal["awg-in", "awg-out"]
    url: str
    ipv4: str | None = None
    ok: bool = False


class CheckReport(BaseModel):
    """Machine-readable report for `awg-ctl check --json` (schema_version 1.0)."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    cascade: str
    links: list[LinkAudit]
    e2e_probes: list[E2EProbe]
    ok: bool = False


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
        if len(parts) != 9:
            continue
        interface, _pubkey, _psk, endpoint, _allowed, handshake, _rx, _tx, keepalive = parts
        try:
            handshake_unix = int(handshake)
            keepalive_val = int(keepalive) if keepalive.strip() else None
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
    required_keepalive: int = REQUIRED_KEEPALIVE,
) -> list[LinkAudit]:
    """Evaluate freshness and keepalive for each parsed peer."""
    audits: list[LinkAudit] = []
    for peer in peers:
        age = None if peer.latest_handshake_unix == 0 else now_unix - peer.latest_handshake_unix
        keepalive_ok = peer.persistent_keepalive == required_keepalive
        handshake_fresh = age is not None and 0 <= age < max_age_sec
        audits.append(
            LinkAudit(
                interface=peer.interface,
                peer_endpoint=peer.peer_endpoint,
                persistent_keepalive=peer.persistent_keepalive,
                latest_handshake_age_sec=age,
                keepalive_ok=keepalive_ok,
                handshake_fresh=handshake_fresh,
                ok=keepalive_ok and handshake_fresh,
            )
        )
    return audits


def build_report(
    cascade: str,
    links: list[LinkAudit],
    e2e_probes: list[E2EProbe],
) -> CheckReport:
    """Assemble a CheckReport and compute the overall status."""
    ok = all(link.ok for link in links) and all(probe.ok for probe in e2e_probes)
    return CheckReport(
        schema_version="1.0",
        cascade=cascade,
        links=links,
        e2e_probes=e2e_probes,
        ok=ok,
    )


def report_to_json(report: CheckReport) -> str:
    """Serialize a report to a single-line JSON string (strict mode)."""
    return json.dumps(report.model_dump(mode="json"))


def report_schema() -> dict:
    """Return the JSON Schema for the check report contract."""
    return CheckReport.model_json_schema()


def format_report_text(report: CheckReport) -> str:
    """Format a check report as human-readable text."""
    lines = [f"awg-ctl check - {report.cascade}"]
    lines.append(f"schema_version: {report.schema_version}")
    lines.append(f"overall: {'OK' if report.ok else 'FAILED'}")
    lines.append("")
    lines.append("Links:")
    for link in report.links:
        lines.append(
            f"  {link.interface} -> {link.peer_endpoint}: "
            f"keepalive={'OK' if link.keepalive_ok else 'MISSING'}, "
            f"handshake={'fresh' if link.handshake_fresh else 'STALE'}, "
            f"ok={'yes' if link.ok else 'no'}"
        )
    lines.append("")
    lines.append("E2E probes:")
    for probe in report.e2e_probes:
        lines.append(
            f"  {probe.source} ({probe.url}): {probe.ipv4 or 'n/a'}, "
            f"ok={'yes' if probe.ok else 'no'}"
        )
    return "\n".join(lines)