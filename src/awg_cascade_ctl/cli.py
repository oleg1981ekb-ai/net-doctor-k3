"""awg-ctl CLI entry point."""

import contextlib
import json
import os
import select
import sys
import time
from pathlib import Path
from typing import Literal

import typer
from pydantic import ValidationError

from awg_cascade_ctl import __version__
from awg_cascade_ctl.check import (
    audit_peers,
    build_report,
    format_report_text,
    load_e2e_probes,
    load_real_dump,
    report_schema,
    report_to_json,
)
from awg_cascade_ctl.config import CascadeConfig
from awg_cascade_ctl.diagnose import (
    diagnose_report_to_json,
    format_diagnose_report_text,
    run_diagnostics,
)
from awg_cascade_ctl.errors import ExitCode
from awg_cascade_ctl.ssh import SSHTransport

try:
    import questionary
    QUESTIONARY_AVAILABLE = True
except ImportError:
    QUESTIONARY_AVAILABLE = False

# ANSI color constants (safe when NO_COLOR or non-TTY)
_COLORS_AVAILABLE = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def _use_color(value: Literal["auto", "always", "never"] = "auto") -> bool:
    """Decide whether to emit ANSI colours."""
    if os.environ.get("NO_COLOR"):
        return False
    if value == "never":
        return False
    if value == "always":
        return True
    # TERM=dumb disables colours
    if os.environ.get("TERM", "") == "dumb":
        return False
    return sys.stdout.isatty()


def _paint(text: str, color_name: str, use_color: bool) -> str:
    if not use_color:
        return text
    return f"{_COLORS_AVAILABLE[color_name]}{text}{_COLORS_AVAILABLE['reset']}"


app = typer.Typer(
    name="awg-ctl",
    help="Service CLI for managing a 3-node AmneziaWG cascade.",
    add_completion=False,
)


def _is_interactive_mode() -> bool:
    """Check if we should run in interactive mode."""
    if not QUESTIONARY_AVAILABLE:
        return False
    return sys.stdin.isatty() and os.environ.get("CI", "").lower() not in ("true", "1", "yes")


def _wait_for_key_or_timeout(seconds: float) -> bool:
    """Return True if a key is pressed on stdin within `seconds`, False on timeout.

    Uses cbreak mode (termios + tty.setcbreak: non-canonical, echo off) so a
    single keypress is detected immediately without waiting for Enter. Safe on
    non-TTY stdin: returns False immediately without blocking. Falls back to
    plain select() when termios/tty are unavailable (e.g. Windows).
    """
    if not sys.stdin.isatty():
        return False
    try:
        import termios
        import tty
    except ImportError:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], seconds)
        except (OSError, ValueError):
            return False
        return bool(ready)
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
    except (termios.error, OSError, ValueError):
        return False
    try:
        tty.setcbreak(fd)
        ready, _, _ = select.select([sys.stdin], [], [], seconds)
        if not ready:
            return False
        termios.tcflush(fd, termios.TCIFLUSH)
        return True
    except (OSError, ValueError):
        return False
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _source_selection_menu() -> tuple[str | None, str | None, Literal["in", "mid", "out", "all"]]:
    """Open interactive source-selection menu.

    Returns (config_path, dump_file, server_target) chosen by user.
    On ESC/Ctrl+C/EOF or empty selection -> (None, None, "in").
    """
    if not QUESTIONARY_AVAILABLE:
        return (None, None, "in")
    try:
        answer = questionary.select(
            "Источник данных:",
            choices=[
                questionary.Choice(
                    title="Demo (тестовые данные) — встроенные: awg0, handshake=1700000000",
                    value="demo",
                ),
                questionary.Choice(
                    title="Dump file (локальный файл) — ввести путь к дампу (например ./dump.txt)",
                    value="dump_file",
                ),
                questionary.Choice(
                    title="SSH (servers.in) — путь к cascade.yaml -> SSH к серверу in",
                    value="ssh_in",
                ),
                questionary.Choice(
                    title="SSH (servers.mid) — путь к cascade.yaml -> SSH к серверу mid",
                    value="ssh_mid",
                ),
                questionary.Choice(
                    title="SSH (servers.out) — путь к cascade.yaml -> SSH к серверу out",
                    value="ssh_out",
                ),
                questionary.Choice(
                    title="SSH (все серверы) — путь к cascade.yaml -> SSH к in, mid, out по очереди",
                    value="ssh_all",
                ),
            ],
            use_indicator=True,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        return (None, None, "in")

    if answer is None:
        return (None, None, "in")

    if answer == "demo":
        return (None, None, "in")

    if answer == "dump_file":
        try:
            path = questionary.text(
                "Путь к файла дампа:",
                default="./dump.txt",
            ).ask()
        except (KeyboardInterrupt, EOFError):
            return (None, None, "in")
        if not path:
            return (None, None, "in")
        return (None, path, "in")

    if answer in ("ssh_in", "ssh_mid", "ssh_out", "ssh_all"):
        try:
            path = questionary.text(
                "Путь к cascade.yaml:",
                default="./cascade.yaml",
            ).ask()
        except (KeyboardInterrupt, EOFError):
            return (None, None, "in")
        if not path:
            return (None, None, "in")
        target: Literal["in", "mid", "out", "all"] = answer[len("ssh_"):]
        return (path, None, target)

    return (None, None, "in")


def _resolve_check_source(
    config_path: str | None,
    dump_file: str | None,
) -> tuple[str | None, str | None, Literal["in", "mid", "out", "all"]]:
    """Resolve the check data source.

    Explicit --config/--dump-file is used as-is. Otherwise, in interactive mode,
    print a 3-second banner and wait for a keypress; on keypress open the
    source-selection menu, otherwise fall back to demo data. Non-interactive
    returns inputs unchanged (demo).
    """
    if config_path is not None or dump_file is not None:
        return (config_path, dump_file, "in")
    if not _is_interactive_mode():
        return (None, None, "in")
    typer.echo("Источник: demo (тест) | 3с до меню... Нажмите любую клавишу для выбора.")
    if _wait_for_key_or_timeout(3.0):
        return _source_selection_menu()
    return (None, None, "in")


def _run_check(
    json_output: bool,
    color: Literal["auto", "always", "never"] = "auto",
    config_path: str | Path | None = None,
    dump_file: str | Path | None = None,
    server_target: Literal["in", "mid", "out", "all"] = "in",
    key_path: str | None = None,
    key_passphrase: str | None = None,
    ask_pass: bool = False,
) -> int:
    """Run check and return exit code. Used by both CLI menu and `check` command.

    Args:
        json_output: if True, output strict JSON.
        color: colour mode.
        config_path: path to cascade.yaml to load real config and SSH dump.
        dump_file: path to local dump file (overrides config if both given).
        server_target: SSH target server from cascade.yaml: in, mid, out, or all.
        key_path: optional SSH key path override for SSH-based dump loading.
        key_passphrase: optional SSH key passphrase override.
        ask_pass: if True, prompt interactively for passphrase on encrypted key.
    """
    # Determine data source provenance
    if dump_file:
        source = "dump_file"
    elif config_path:
        source = "ssh"
    else:
        source = "demo"

    try:
        peers = load_real_dump(
            config_path=config_path,
            dump_file=dump_file,
            server_target=server_target,
            key_path=key_path,
            key_passphrase=key_passphrase,
        )
    except RuntimeError as exc:
        # If SSH key is encrypted and no passphrase provided, try interactive prompt
        msg = str(exc).lower()
        encrypted_err = "passwordrequired" in msg or "encrypted" in msg
        if encrypted_err and ask_pass and sys.stdin.isatty():
            try:
                from typer import prompt

                new_pass = prompt("SSH key passphrase (hidden)", hide_input=True)
                try:
                    peers = load_real_dump(
                        config_path=config_path,
                        dump_file=dump_file,
                        server_target=server_target,
                        key_path=key_path,
                        key_passphrase=new_pass,
                    )
                except RuntimeError as retry_exc:
                    retry_msg = str(retry_exc).lower()
                    if "invalid key" in retry_msg or "passwordrequired" in retry_msg:
                        typer.echo(
                            "ERROR: неверная парольная фраза для SSH ключа",
                            err=True,
                        )
                        raise typer.Exit(code=ExitCode.USAGE_ERROR.value)
                    raise
            except (KeyboardInterrupt, EOFError):
                typer.echo("\nAborted.", err=True)
                raise typer.Exit(code=ExitCode.USAGE_ERROR.value)
        else:
            raise
    except FileNotFoundError as exc:
        typer.echo(f"ERROR: config file not found: {exc}", err=True)
        raise typer.Exit(code=ExitCode.USAGE_ERROR.value)

    links = audit_peers(peers, now_unix=int(time.time()))
    probes = load_e2e_probes(config_path=config_path, server_target=server_target)

    report = build_report(
        cascade="cascade-alpha",
        links=links,
        e2e_probes=probes,
        source=source,
    )

    use_color = _use_color(color)

    if json_output:
        typer.echo(report_to_json(report))
    else:
        typer.echo(format_report_text(report, use_color=use_color))

    # Map status -> exit code
    if report.status == "pass":
        return ExitCode.OK.value
    elif report.status == "warning":
        return ExitCode.WARNING.value
    else:
        return ExitCode.CRITICAL.value


@app.command(name="version")
def version() -> None:
    """Show the awg-ctl version."""
    typer.echo(f"awg-ctl {__version__}")


@app.command(name="check")
def check(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Strict JSON output; all other output is sent to stdout.",
    ),
    color: Literal["auto", "always", "never"] = typer.Option(
        "auto",
        "--color",
        help="Force colour mode: auto (default), always, or never.",
    ),
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to cascade.yaml for SSH-based real data loading.",
    ),
    dump_file: str | None = typer.Option(
        None,
        "--dump-file",
        help="Path to local AWG dump file (overrides --config).",
    ),
    server_target: Literal["in", "mid", "out", "all"] | None = typer.Option(
        None,
        "--server",
        "-s",
        help="SSH target server from cascade.yaml: in, mid, out, or all.",
    ),
    key_path: str | None = typer.Option(
        None,
        "--key-path",
        help="Path to SSH private key file (overrides agent/config auto-detect).",
    ),
    key_passphrase: str | None = typer.Option(
        None,
        "--key-passphrase",
        help="Passphrase for encrypted SSH key (use with --key-path; avoid if key in ssh-agent).",
    ),
    ask_pass: bool = typer.Option(
        False,
        "--ask-pass",
        help="Prompt interactively for passphrase when key is encrypted (CI/non-interactive use SSH_KEY_PASSPHRASE env).",
    ),
) -> None:
    """Run cascade check and E2E probe."""
    config_path, dump_file, resolved_target = _resolve_check_source(config_path, dump_file)
    final_target = server_target or resolved_target

    # Resolve passphrase priority: CLI arg → env var → interactive prompt (if --ask-pass)
    effective_passphrase = key_passphrase
    if effective_passphrase is None:
        effective_passphrase = os.environ.get("SSH_KEY_PASSPHRASE")

    exit_code = _run_check(
        json_output=json_output,
        color=color,
        config_path=config_path,
        dump_file=dump_file,
        server_target=final_target,
        key_path=key_path,
        key_passphrase=effective_passphrase,
        ask_pass=ask_pass,
    )
    raise typer.Exit(code=exit_code)


@app.command(name="schema")
def schema(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output pure JSON schema; otherwise output as markdown code block.",
    ),
) -> None:
    """Output JSON Schema of the check report contract."""
    schema_obj = report_schema()
    if json_output:
        typer.echo(json.dumps(schema_obj))
    else:
        typer.echo(f"```json\n{json.dumps(schema_obj, indent=2)}\n```")


def _run_diagnose(
    config_path: str | None,
    server: str,
    checks: list[str],
    color: str,
    json_output: bool,
    details: bool,
    key_path: str | None = None,
    key_passphrase: str | None = None,
    ask_pass: bool = True,
) -> int:
    """Run diagnose checks against a server via SSH.

    Connects to SSH, prompts for passphrase interactively if key is encrypted,
    runs checks on one connection, prints report, returns exit code.
    """
    from awg_cascade_ctl.ssh import resolve_ssh_key_from_config

    if server not in ("in", "mid", "out"):
        typer.echo(f"ERROR: invalid server: {server}", err=True)
        return ExitCode.USAGE_ERROR.value

    cfg = CascadeConfig.load(config_path) if config_path else CascadeConfig(
        servers={"in": None, "mid": None, "out": None},  # type: ignore[assignment]
        network=None,  # type: ignore[arg-type]
        ports=None,  # type: ignore[arg-type]
        scripts=None,  # type: ignore[arg-type]
        timeouts=None,  # type: ignore[arg-type]
    )

    server_cfg = cfg.servers.get(server)
    if server_cfg is None or server_cfg.host is None:
        typer.echo(f"ERROR: server {server} not found in cascade config", err=True)
        return ExitCode.USAGE_ERROR.value

    resolved_key, _needs_passphrase = resolve_ssh_key_from_config(
        cfg,
        explicit_key_path=key_path or server_cfg.ssh_key_path,
    )

    effective_passphrase = key_passphrase
    if effective_passphrase is None:
        effective_passphrase = os.environ.get("SSH_KEY_PASSPHRASE")

    transport = SSHTransport(
        host=server_cfg.host,
        port=server_cfg.port,
        user=server_cfg.username,
        key_path=resolved_key,
        passphrase=effective_passphrase,
        connect_timeout=cfg.timeouts.ssh_connect,
        command_timeout=cfg.timeouts.ssh_command,
    )

    try:
        transport.connect()
        # Pre-flight: trigger actual SSH connection to detect encrypted key
        try:
            transport.run("true")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            encrypted_err = (
                "passwordrequired" in msg
                or "encrypted" in msg
                or "passphrase" in msg
            )
            if encrypted_err and ask_pass and sys.stdin.isatty():
                try:
                    from typer import prompt as typer_prompt

                    new_pass = typer_prompt("SSH key passphrase (hidden)", hide_input=True)
                except (KeyboardInterrupt, EOFError):
                    typer.echo("\nAborted.", err=True)
                    return ExitCode.USAGE_ERROR.value
                transport.passphrase = new_pass
                transport.close()
                transport.connect()
                transport.run("true")
            else:
                typer.echo(f"ERROR: SSH connection failed: {exc}", err=True)
                return ExitCode.CRITICAL.value

        report = run_diagnostics(
            transport=transport,
            server=server,
            checks=checks,
            server_ip=server_cfg.host or "",
        )
    finally:
        contextlib.suppress(Exception)
        transport.close()

    use_color = _use_color(color)
    if json_output:
        typer.echo(diagnose_report_to_json(report))
    else:
        typer.echo(format_diagnose_report_text(report, use_color=use_color, show_details=details))

    if report.verdict == "red":
        return ExitCode.CRITICAL.value
    return ExitCode.OK.value


@app.command(name="diagnose")
def diagnose(
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to cascade.yaml for SSH-based real data loading.",
    ),
    server: str = typer.Option(
        "in",
        "--server",
        "-s",
        help="SSH target server from cascade.yaml: in, mid, out, or all.",
    ),
    checks: str = typer.Option(
        "tunnel,service,versions,firewall,routes,logs,scripts",
        "--checks",
        help="Comma-separated list of diagnostic checks to run.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Strict JSON output; all other output is sent to stdout.",
    ),
    color: Literal["auto", "always", "never"] = typer.Option(
        "auto",
        "--color",
        help="Force colour mode: auto (default), always, or never.",
    ),
    details: bool = typer.Option(
        False,
        "--details",
        help="Include detailed check output (for debug).",
    ),
) -> None:
    """Run read-only diagnostics for a cascade server."""
    check_names = [c.strip() for c in checks.split(",") if c.strip()]
    exit_code = _run_diagnose(
        config_path=config_path,
        server=server,
        checks=check_names,
        color=color,
        json_output=json_output,
        details=details,
    )
    raise typer.Exit(code=exit_code)


@app.command(name="deploy")
def deploy(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="[Phase 2] Show what would be deployed without applying changes.",
    ),
) -> None:
    """Deploy cascade configuration to all nodes (Phase 2)."""
    typer.echo(
        "ERROR: deploy is deferred to Phase 2 / Post-MVP (Out of Scope for v1).",
        err=True,
    )
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


@app.command(name="swap-exit")
def swap_exit(
    new_host: str = typer.Option(
        ...,
        "--new-host",
        help="[Phase 2] New exit node host.",
    ),
) -> None:
    """Swap exit node (Phase 2)."""
    typer.echo(
        "ERROR: swap-exit is deferred to Phase 2 / Post-MVP (Out of Scope for v1).",
        err=True,
    )
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


@app.command(name="test-failover")
def test_failover(
    target: str = typer.Option(
        ...,
        "--target",
        help="[Phase 2] Target node: mid or out.",
    ),
    wait_healthcheck: bool = typer.Option(
        False,
        "--wait-healthcheck",
        help="[Phase 2] Wait for healthcheck after failover.",
    ),
) -> None:
    """Test failover (Phase 2)."""
    typer.echo(
        "ERROR: test-failover is deferred to Phase 2 / Post-MVP (Out of Scope for v1).",
        err=True,
    )
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


@app.command(name="clients")
def clients(
    action: str = typer.Argument(
        ...,
        help="[Phase 2] Action: add|remove|list.",
    ),
) -> None:
    """Manage clients (Phase 2)."""
    typer.echo(
        "ERROR: clients is deferred to Phase 2 / Post-MVP (Out of Scope for v1).",
        err=True,
    )
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


@app.command(name="menu")
def menu(
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to cascade.yaml (passed to check if selected).",
    ),
    key_path: str | None = typer.Option(
        None,
        "--key-path",
        help="Path to SSH private key file (passed to check if selected).",
    ),
    key_passphrase: str | None = typer.Option(
        None,
        "--key-passphrase",
        help="Passphrase for encrypted SSH key (passed to check if selected).",
    ),
    ask_pass: bool = typer.Option(
        True,
        "--ask-pass",
        help="Prompt for passphrase when key is encrypted (passed to check if selected).",
    ),
) -> None:
    """Interactive menu for awg-ctl (TTY only)."""
    # When invoked programmatically (e.g. from main() via --interactive),
    # Typer's OptionInfo defaults leak into the params. Resolve them to
    # real Python values so they don't propagate downstream to paramiko.
    from typer.models import OptionInfo

    if isinstance(key_path, OptionInfo):
        key_path = None
    if isinstance(key_passphrase, OptionInfo):
        key_passphrase = None
    if isinstance(ask_pass, OptionInfo):
        ask_pass = True

    if not _is_interactive_mode():
        typer.echo(
            "ERROR: Interactive menu requires a TTY and questionary. "
            "Use individual commands or run in a terminal.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    if not QUESTIONARY_AVAILABLE:
        typer.echo(
            "ERROR: questionary is not installed. "
            "Install with: pip install questionary",
            err=True,
        )
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    choices = [
        "Server       — Full server diagnostic (tunnel/service/routes/firewall/logs/scripts)",
        "Peers        — Peer state check + E2E probe (handshake/keepalive/transfer)",
        "Clients      — Manage clients (Phase 2 stub)",
        "Swap exit    — Swap exit node (Phase 2 stub)",
        "Test failover — Test failover (Phase 2 stub)",
    ]

    try:
        selected = questionary.select(
            "awg-ctl menu — choose an action:",
            choices=choices,
            use_indicator=True,
        ).ask()
    except (KeyboardInterrupt, EOFError):
        typer.echo("\nAborted.")
        raise typer.Exit(code=ExitCode.OK)

    if not selected:
        typer.echo("No selection made.")
        raise typer.Exit(code=ExitCode.OK)

    cmd = selected.split()[0]

    if cmd == "Peers":
        resolved_config, resolved_dump, resolved_target = _resolve_check_source(config_path, None)
        exit_code = _run_check(
            json_output=False,
            config_path=resolved_config,
            dump_file=resolved_dump,
            server_target=resolved_target,
            key_path=key_path,
            key_passphrase=key_passphrase,
            ask_pass=ask_pass,
        )
        raise typer.Exit(code=exit_code)

    if cmd == "Server":
        resolved_config, resolved_dump, resolved_target = _resolve_check_source(config_path, None)
        exit_code = _run_diagnose(
            config_path=resolved_config,
            server=resolved_target,
            checks=["tunnel", "service", "versions", "firewall", "routes", "logs", "scripts"],
            color="auto",
            json_output=False,
            details=False,
            key_path=key_path,
            key_passphrase=key_passphrase,
            ask_pass=ask_pass,
        )
        raise typer.Exit(code=exit_code)

    if cmd in ("Clients", "Swap", "Test", "deploy"):
        typer.echo(
            f"ERROR: {cmd} is deferred to Phase 2 / Post-MVP (Out of Scope for v1).",
            err=True,
        )
        raise typer.Exit(code=ExitCode.USAGE_ERROR)

    typer.echo(f"Unknown command: {cmd}")
    raise typer.Exit(code=ExitCode.USAGE_ERROR)


config_app = typer.Typer(help="Configuration commands.")


@config_app.command(name="validate")
def config_validate(
    config_path: str = typer.Option(
        "cascade.yaml",
        "--config",
        "-c",
        help="Path to cascade.yaml",
    ),
) -> None:
    """Validate a cascade.yaml configuration file."""
    try:
        cfg = CascadeConfig.load(config_path)
        cfg.validate()
        typer.echo(f"OK: {config_path} is valid")
        raise typer.Exit(code=ExitCode.OK)
    except FileNotFoundError:
        typer.echo(f"ERROR: file not found: {config_path}", err=True)
        raise typer.Exit(code=ExitCode.USAGE_ERROR)
    except (ValidationError, ValueError) as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=ExitCode.USAGE_ERROR)


app.add_typer(config_app, name="config")


def main() -> None:
    """CLI entry point with --interactive guard."""
    if "--interactive" in sys.argv:
        sys.argv.remove("--interactive")
        if _is_interactive_mode() and QUESTIONARY_AVAILABLE:
            # When called from __main__ we must catch typer.Exit manually,
            # because Typer's standalone_mode handler is not in the stack.
            try:
                menu(config_path=None)
            except typer.Exit as exc:
                sys.exit(exc.exit_code)
            except KeyboardInterrupt:
                sys.exit(130)
            return
        else:
            typer.echo(
                "ERROR: --interactive requires a TTY and questionary.",
                err=True,
            )
            sys.exit(ExitCode.USAGE_ERROR)
    app()


if __name__ == "__main__":
    main()