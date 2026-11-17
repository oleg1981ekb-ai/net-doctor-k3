"""Tests for the two-level locking of awg-ctl."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.locks import (
    LocalLock,
    LockError,
    RemoteLock,
    resolve_exit_code,
)


def test_local_lock_acquire_and_release(tmp_path: Path) -> None:
    """Local lock should be acquirable and releasable."""
    path = tmp_path / "cascade.lock"
    lock = LocalLock(path)
    with lock:
        assert lock._fd is not None
        assert path.exists()
    assert lock._fd is None


def test_local_lock_nested_raises() -> None:
    """Second acquisition of the same local lock (non-blocking) must fail."""
    path = Path("/tmp/awg-ctl-test-lock-xyz")
    lock1 = LocalLock(path)
    lock2 = LocalLock(path)
    lock1.acquire()
    try:
        with pytest.raises(LockError):
            lock2.acquire(blocking=False)
    finally:
        lock1.release()


def test_remote_lock_success() -> None:
    """Remote lock acquisition succeeds when flock returns ok."""
    run_command = MagicMock()
    run_command.return_value.ok = True
    lock = RemoteLock(run_command)
    lock.acquire()
    assert lock._held is True


def test_remote_lock_busy_raises() -> None:
    """Remote lock acquisition must raise when flock returns not-ok."""
    run_command = MagicMock()
    busy_result = MagicMock()
    busy_result.ok = False
    busy_result.stdout = ""
    diag_result = MagicMock()
    diag_result.stdout = "PID owner"
    run_command.side_effect = [busy_result, diag_result]
    lock = RemoteLock(run_command)
    with pytest.raises(LockError):
        lock.acquire()


def test_remote_lock_context_manager_releases() -> None:
    """RemoteLock as context manager should not leak held state."""
    run_command = MagicMock()
    run_command.return_value.ok = True
    with RemoteLock(run_command) as lock:
        assert lock._held is True
    assert lock._held is False


def test_resolve_exit_code_no_error() -> None:
    """No lock error -> OK."""
    assert resolve_exit_code(None) == ExitCode.OK.value


def test_resolve_exit_code_lock_busy() -> None:
    """Lock error -> CRITICAL."""
    assert resolve_exit_code(LockError("busy")) == ExitCode.CRITICAL.value