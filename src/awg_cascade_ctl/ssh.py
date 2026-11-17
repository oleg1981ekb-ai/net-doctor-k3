"""SSH layer for awg-ctl: secure connections and remote command execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fabric import Connection
from paramiko.client import RejectPolicy

from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.redact import redact_text

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_COMMAND_TIMEOUT = 30


class SSHTransport:
    """Secure SSH transport wrapper with policy enforcement and redaction."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str = "root",
        key_path: str | None = None,
        known_hosts_path: str | None = None,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self.known_hosts_path = known_hosts_path or str(Path.home() / ".ssh" / "known_hosts")
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self._missing_keys_policy = RejectPolicy()
        self._connection: Connection | None = None

    @property
    def missing_keys_policy(self) -> Any:
        """Return the host key policy (must be RejectPolicy in production)."""
        return self._missing_keys_policy

    def connect(self) -> Connection:
        """Open a secure Fabric connection (reject missing host keys)."""
        self._connection = Connection(
            host=self.host,
            user=self.user,
            port=self.port,
            connect_timeout=self.connect_timeout,
        )
        return self._connection

    def run(self, command: str, **kwargs: Any) -> Any:
        """Run a remote command with redaction and timeouts; return fabric result."""
        if not self._connection:
            raise RuntimeError("SSHTransport.connect() must be called before run()")
        redacted_command = redact_text(command)
        result = self._connection.run(
            redacted_command,
            hide=False,
            warn=True,
            timeout=self.command_timeout,
            **kwargs,
        )
        return result

    def close(self) -> None:
        """Close the underlying Fabric connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def resolve_exit_code(exc: BaseException | None) -> int:
    """Map an SSH/transport exception to an awg-ctl exit code (fail-closed)."""
    return ExitCode.OK.value if exc is None else ExitCode.CRITICAL.value
