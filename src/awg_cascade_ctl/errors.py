"""Exit code definitions and priority handling."""

from datetime import date, datetime
from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for awg-ctl CLI."""

    OK = 0
    CRITICAL = 1
    WARNING = 3
    USAGE_ERROR = 64


# Priority: lower value = higher priority when multiple events occur
# 1 (CRITICAL) > 3 (WARNING) > 0 (OK)
PRIORITY_ORDER = [ExitCode.CRITICAL, ExitCode.WARNING, ExitCode.OK]


def resolve_exit_code(codes: list[ExitCode]) -> ExitCode:
    """Return the exit code with the highest priority from a list."""
    for priority in PRIORITY_ORDER:
        if priority in codes:
            return priority
    return ExitCode.OK


def _normalize_status(status: str) -> str:
    """Map a report status/verdict onto a canonical severity token."""
    normalized = status.strip().lower()
    if normalized in ("green", "ok", "pass"):
        return "ok"
    if normalized in ("yellow", "warn", "warning"):
        return "warn"
    if normalized in ("red", "critical", "fail"):
        return "fail"
    raise ValueError(f"unknown status: {status}")


def resolve_exit_code_from_outcome(
    status: str,
    *,
    unix: bool = False,
    warn_as_ok: bool = False,
    strict: bool = False,
) -> ExitCode:
    """Resolve the process exit code from a check/diagnose status.

    Args:
        status: canonical-ish status ("pass"/"ok"/"green", "warn"/"yellow",
            "fail"/"red"/"critical").
        unix: use the unix exit scheme (OK=0, fail=1, warn=1 unless warn_as_ok).
        warn_as_ok: opt-in: in unix mode, warn -> OK (0).
        strict: remap warn -> fail before mapping.

    Returns:
        The exit code for the process.
    """
    norm = _normalize_status(status)
    ok = norm == "ok"
    warn = norm == "warn"

    if strict and warn:
        warn = False

    if unix:
        if ok:
            return ExitCode.OK
        if warn and warn_as_ok:
            return ExitCode.OK
        # unix collapses warn and fail into a single failure code
        return ExitCode.CRITICAL

    if ok:
        return ExitCode.OK
    if warn:
        return ExitCode.WARNING
    return ExitCode.CRITICAL


def resolve_legacy_exit_code(status: str) -> ExitCode:
    """Legacy exit-code mapping for diagnose/check statuses.

    Legacy behaviour: only hard failures (fail/red/critical) are critical;
    warnings/ok are treated as OK.
    """
    return ExitCode.CRITICAL if _normalize_status(status) == "fail" else ExitCode.OK


def validate_exit_flags(strict: bool, warn_as_ok: bool) -> ExitCode | None:
    """Return a usage exit code when --strict and --warn-as-ok conflict.

    They are mutually exclusive; the conflict must be detected at parse time
    (before checks run), not during exit-code rendering.
    """
    if strict and warn_as_ok:
        return ExitCode.USAGE_ERROR
    return None


def parse_legacy_until(raw: str) -> date:
    """Parse --legacy-until value as YYYY-MM-DD. Raises ValueError if invalid."""
    return datetime.strptime(raw, "%Y-%m-%d").date()


def is_legacy_expired(legacy_until: date, today: date | None = None) -> bool:
    """Return True when the legacy-until date is strictly in the past."""
    if today is None:
        today = date.today()
    return today > legacy_until
