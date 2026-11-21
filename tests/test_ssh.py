"""Tests for the SSH layer of awg-ctl."""

from unittest.mock import MagicMock, patch

from paramiko import PasswordRequiredException, SSHException
from paramiko.client import RejectPolicy
from paramiko.pkey import PKey

from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.ssh import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    SSHTransport,
    _key_needs_passphrase,
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


def test_key_needs_passphrase_encrypted_raises_password_required() -> None:
    """_key_needs_passphrase returns True when PKey.from_path raises PasswordRequiredException."""
    with patch.object(PKey, "from_path", side_effect=PasswordRequiredException("encrypted")):
        assert _key_needs_passphrase("/fake/key") is True


def test_key_needs_passphrase_encrypted_typeerror_password() -> None:
    """_key_needs_passphrase returns True when PKey.from_path raises TypeError mentioning password."""
    with patch.object(PKey, "from_path", side_effect=TypeError("Key is password-protected, but password was not provided.")):
        assert _key_needs_passphrase("/fake/key") is True


def test_key_needs_passphrase_typeerror_other() -> None:
    """_key_needs_passphrase returns False for unrelated TypeError."""
    with patch.object(PKey, "from_path", side_effect=TypeError("some other error")):
        assert _key_needs_passphrase("/fake/key") is False


def test_key_needs_passphrase_unencrypted() -> None:
    """_key_needs_passphrase returns False when PKey.from_path succeeds."""
    with patch.object(PKey, "from_path", return_value=MagicMock()):
        assert _key_needs_passphrase("/fake/key") is False


def test_key_needs_passphrase_ssh_exception() -> None:
    """_key_needs_passphrase returns False on SSHException (unknown key type)."""
    with patch.object(PKey, "from_path", side_effect=SSHException("not a valid private key")):
        assert _key_needs_passphrase("/fake/key") is False


def test_key_needs_passphrase_os_error() -> None:
    """_key_needs_passphrase returns False on OSError (file not readable)."""
    with patch.object(PKey, "from_path", side_effect=OSError("permission denied")):
        assert _key_needs_passphrase("/fake/key") is False
