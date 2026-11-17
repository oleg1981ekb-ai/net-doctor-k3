"""Tests for the SSH layer of awg-ctl."""

from unittest.mock import MagicMock

from paramiko.client import RejectPolicy

from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.ssh import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    SSHTransport,
    resolve_exit_code,
)


def test_ssh_transport_defaults() -> None:
    """Transport should use the documented defaults."""
    t = SSHTransport(host="10.10.1.2")
    assert t.host == "10.10.1.2"
    assert t.port == 22
    assert t.user == "root"
    assert t.connect_timeout == DEFAULT_CONNECT_TIMEOUT
    assert t.command_timeout == DEFAULT_COMMAND_TIMEOUT


def test_ssh_transport_missing_keys_policy_is_reject() -> None:
    """Host key policy must be RejectPolicy (fail-closed)."""
    t = SSHTransport(host="10.10.1.2")
    assert isinstance(t.missing_keys_policy, RejectPolicy)


def test_ssh_transport_run_redacts_command() -> None:
    """run() must redact sensitive values before execution."""
    t = SSHTransport(host="10.10.1.2")
    fake_connection = MagicMock()
    t._connection = fake_connection
    t.run("show PrivateKey: abc123")
    cmd = fake_connection.run.call_args.args[0]
    assert "***REDACTED***" in cmd
    assert "abc123" not in cmd
    fake_connection.run.assert_called_once()
    assert fake_connection.run.call_args.kwargs["timeout"] == DEFAULT_COMMAND_TIMEOUT


def test_ssh_transport_run_before_connect_raises() -> None:
    """run() before connect() must raise a runtime error."""
    t = SSHTransport(host="10.10.1.2")
    try:
        t.run("echo hi")
        raise AssertionError("should have raised")
    except RuntimeError:
        pass


def test_ssh_transport_close_is_safe() -> None:
    """close() before connect() must not raise."""
    t = SSHTransport(host="10.10.1.2")
    t.close()


def test_resolve_exit_code_no_error() -> None:
    """No error -> OK."""
    assert resolve_exit_code(None) == ExitCode.OK.value


def test_resolve_exit_code_ssh_error() -> None:
    """SSH/transport error -> CRITICAL."""
    assert resolve_exit_code(RuntimeError("boom")) == ExitCode.CRITICAL.value
