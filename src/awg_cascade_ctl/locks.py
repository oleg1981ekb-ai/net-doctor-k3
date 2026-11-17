"""Two-level locking for awg-ctl cascade operations.

Local lock: ``~/.cache/awg-ctl/cascade.lock`` via ``fcntl.flock``.
Remote lock: ``/run/awg-ctl.cascade.lock`` on ``awg-in`` via ``flock -n``.
When either lock is busy the utility must exit with code ``1`` (CRITICAL)
and print diagnostics of the lock owner (``lslocks``/``fuser`` when available).
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import Self

from awg_cascade_ctl.errors import ExitCode

LOCAL_LOCK_DIR = Path.home() / ".cache" / "awg-ctl"
LOCAL_LOCK_PATH = LOCAL_LOCK_DIR / "cascade.lock"
REMOTE_LOCK_PATH = Path("/run/awg-ctl.cascade.lock")


class LockError(RuntimeError):
    """Raised when a lock cannot be acquired."""


class LocalLock:
    """Advisory lock on the administrator's machine (fcntl.flock)."""

    def __init__(self, path: Path = LOCAL_LOCK_PATH) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self, blocking: bool = True) -> None:
        """Acquire the local lock; raise LockError if already held."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT
        self._fd = os.open(self.path, flags, 0o600)
        operation = fcntl.LOCK_EX
        if not blocking:
            operation |= fcntl.LOCK_NB
        try:
            fcntl.flock(self._fd, operation)
        except OSError as exc:
            os.close(self._fd)
            self._fd = None
            raise LockError(f"Local lock is busy: {self.path}: {exc}") from exc

    def release(self) -> None:
        """Release and remove the local lock file."""
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RemoteLock:
    """Advisory lock on ``awg-in`` (``flock -n`` over SSH)."""

    def __init__(self, run_command, path: str = str(REMOTE_LOCK_PATH)) -> None:
        self._run_command = run_command
        self.path = path
        self._held = False

    def acquire(self) -> None:
        """Acquire the remote lock; raise LockError if already held."""
        cmd = f"flock -n {self.path} sh -c 'echo LOCKED'"
        result = self._run_command(cmd)
        if getattr(result, "ok", False) is False:
            owner = self._diagnose_owner()
            raise LockError(f"Remote lock is busy: {self.path}. Owner diagnostics: {owner}")
        self._held = True

    def _diagnose_owner(self) -> str:
        """Best-effort owner diagnostics via lslocks/fuser."""
        try:
            diag = self._run_command(f"lslocks 2>/dev/null | grep {self.path} || fuser {self.path} 2>&1")
            return str(getattr(diag, "stdout", "")) or "owner unknown"
        except (OSError, RuntimeError):  # best-effort diagnostics
            return "owner unknown"

    def release(self) -> None:
        """Release the remote lock (best effort; file stays, lock is released)."""
        self._held = False

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def resolve_exit_code(lock_error: LockError | None) -> int:
    """Return CRITICAL (1) when a lock is held, OK (0) otherwise."""
    return ExitCode.CRITICAL.value if lock_error is not None else ExitCode.OK.value
