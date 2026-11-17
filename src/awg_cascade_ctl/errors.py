"""Exit code definitions and priority handling."""

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