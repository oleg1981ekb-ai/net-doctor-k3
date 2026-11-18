"""awg-ctl CLI entry point."""

import json
import os
import sys
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
from awg_cascade_ctl.errors import ExitCode

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


def _run_check(
    json_output: bool,
    color: Literal["auto", "always", "never"] = "auto",
    config_path: str | Path | None = None,
    dump_file: str | Path | None = None,
) -> int:
    """Run check and return exit code. Used by both CLI menu and `check` command.

    Args:
        json_output: if True, output strict JSON.
        color: colour mode.
        config_path: path to cascade.yaml to load real config and SSH dump.
        dump_file: path to local dump file (overrides config if both given).
    """
    peers = load_real_dump(config_path=config_path, dump_file=dump_file)
    links = audit_peers(peers, now_unix=1700000030)
    probes = load_e2e_probes(config_path=config_path)
    report = build_report(cascade="cascade-alpha", links=links, e2e_probes=probes)

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
) -> None:
    """Run cascade check and E2E probe."""
    exit_code = _run_check(
        json_output=json_output,
        color=color,
        config_path=config_path,
        dump_file=dump_file,
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
) -> None:
    """Interactive menu for awg-ctl (TTY only)."""
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
        "check        — Run cascade check and E2E probe",
        "clients      — Manage clients (Phase 2 stub)",
        "swap-exit    — Swap exit node (Phase 2 stub)",
        "test-failover — Test failover (Phase 2 stub)",
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

    if cmd == "check":
        exit_code = _run_check(json_output=False, config_path=config_path)
        raise typer.Exit(code=exit_code)

    if cmd in ("clients", "swap-exit", "test-failover", "deploy"):
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
                menu()
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