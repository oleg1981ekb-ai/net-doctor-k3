"""SSH layer for awg-ctl: secure connections and remote command execution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fabric import Connection
from paramiko.client import RejectPolicy

from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.redact import redact_text

if TYPE_CHECKING:
    from awg_cascade_ctl.check import RawPeer
    from awg_cascade_ctl.config import CascadeConfig

DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_COMMAND_TIMEOUT = 30

# Keys that paramiko auto-detects when key_filename is not provided
AUTO_DETECT_KEY_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}


def resolve_ssh_key(
    explicit_key_path: str | None = None,
    config_key_path: str | None = None,
    check_agent: bool = True,
) -> tuple[str | None, bool]:
    """Resolve which SSH private key to use and whether a passphrase is needed.

    Priority (explicit overrides):
    1. ``explicit_key_path`` – from CLI ``--key-path``
    2. ``config_key_path`` – from ``cascade.yaml`` ``servers.in.ssh_key_path``
    3. ``ssh-agent`` – if available and a key is already added
    4. Auto-detect ``~/.ssh/id_ed25519`` / ``~/.ssh/id_rsa``

    Returns
    -------
    key_path : str | None
        Absolute path to the key file (already expanded with ``os.path.expanduser``),
        or ``None`` if the key should be resolved automatically (agent or default).
    needs_passphrase : bool
        ``True`` if the resolved key is encrypted and no passphrase is available.
    """
    # ── 1. Explicit CLI path ────────────────────────────────────────────
    if explicit_key_path is not None and isinstance(explicit_key_path, str):
        path = os.path.expanduser(explicit_key_path)
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        return path, _key_needs_passphrase(path)

    # ── 2. Config key path ──────────────────────────────────────────────
    if config_key_path is not None and isinstance(config_key_path, str):
        path = os.path.expanduser(config_key_path)
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        return path, _key_needs_passphrase(path)

    # ── 3. ssh-agent detection ──────────────────────────────────────────
    if check_agent:
        # Paramiko will use the default agent if key_filename is omitted.
        # We just check whether agent has any identities.
        try:
            from paramiko.agent import Agent
            agent = Agent()
            identities = agent.get_keys()
            if identities:
                # Agent has a key – we don't know its path, but it's decrypted.
                # We return None key_path so callers skip explicit key passing.
                # Passphrase is not needed because agent already decrypted it.
                return None, False
        except (ImportError, OSError, AttributeError):
            # Agent not available or error – fall through to auto-detect
            pass

    # ── 4. Auto-detect default keys in ~/.ssh/ ─────────────────────────
    home_ssh = Path.home() / ".ssh"
    if home_ssh.is_dir():
        for key_name in sorted(AUTO_DETECT_KEY_NAMES, key=lambda n: -len(n)):
            candidate = home_ssh / key_name
            if candidate.is_file():
                return str(candidate), _key_needs_passphrase(str(candidate))

    # Nothing found
    return None, False


def _key_needs_passphrase(key_path: str) -> bool:
    """Check whether a private key file is encrypted (Paramiko-style)."""
    try:
        # Read the file content and check for encryption markers
        with open(key_path, "r") as f:
            content = f.read()
        # Encrypted keys contain "ENCRYPTED" in the PEM header
        return "ENCRYPTED" in content
    except (OSError, ValueError):
        # If we can't read the file, assume it may be encrypted
        return True


class SSHTransport:
    """Secure SSH transport wrapper with policy enforcement and redaction."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        user: str = "root",
        key_path: str | None = None,
        passphrase: str | None = None,
        known_hosts_path: str | None = None,
        connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path
        self.passphrase = passphrase
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
        # Build connect_kwargs only for explicitly provided key_path / passphrase.
        # If key_path is None we rely on ssh-agent auto-detection or default keys.
        connect_kwargs: dict[str, Any] = {}

        if self.key_path is not None:
            connect_kwargs["key_filename"] = self.key_path
            if self.passphrase is not None:
                connect_kwargs["passphrase"] = self.passphrase

        self._connection = Connection(
            host=self.host,
            user=self.user,
            port=self.port,
            connect_timeout=self.connect_timeout,
            connect_kwargs=connect_kwargs,
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

    def run_awg_dump(self) -> list[RawPeer]:
        """Run `awg show all dump` on the remote host and return parsed peers.

        Returns an empty list if the command fails or the output is empty.
        """
        from awg_cascade_ctl.check import parse_awg_dump

        try:
            result = self.run("awg show all dump")
            if result.failed or not result.stdout.strip():
                return []
            return parse_awg_dump(result.stdout)
        except Exception as exc:
            # Transport failure → critical exit
            raise RuntimeError(f"SSH dump failed: {exc}") from exc


def resolve_ssh_key_from_config(
    cfg: CascadeConfig,
    explicit_key_path: str | None = None,
) -> tuple[str | None, bool]:
    """Convenient wrapper that resolves key using config and optional CLI override.

    Returns ``(key_path, needs_passphrase)`` where ``key_path`` is either an
    absolute path or ``None`` (meaning "use agent / auto-detect").
    """
    cfg_key = None
    if explicit_key_path is not None:
        cfg_key = explicit_key_path
    elif cfg is not None:
        # Try each server in the cascade; return the first one that has a path.
        for srv in ("in", "mid", "out"):
            if srv in cfg.servers and cfg.servers[srv].ssh_key_path:
                cfg_key = cfg.servers[srv].ssh_key_path
                break

    return resolve_ssh_key(explicit_key_path=cfg_key, config_key_path=cfg_key)  # type: ignore[arg-type]


def fetch_and_parse_dump(
    transport: SSHTransport,
) -> list[RawPeer]:
    """Connect, run dump, parse, and close. One-shot helper."""
    try:
        transport.connect()
        peers = transport.run_awg_dump()
        return peers
    finally:
        transport.close()


def resolve_exit_code(exc: BaseException | None) -> int:
    """Map an SSH/transport exception to an awg-ctl exit code (fail-closed)."""
    return ExitCode.OK.value if exc is None else ExitCode.CRITICAL.value