"""awg-ctl CLI entry point."""

import json
import os
import sys

import typer
from pydantic import ValidationError

from awg_cascade_ctl import __version__
from awg_cascade_ctl.check import (
    audit_peers,
    build_report,
    format_report_text,
    parse_awg_dump,
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


@app.command(name="version")
def version() -> None:
    """Show the awg-ctl version."""
    typer.echo(f"awg-ctl {__version__}")


@app.command(name="check")
def check(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Strict JSON output; all other output is sent to stderr.",
    ),
) -> None:
    """Run cascade check and E2E probe."""
    peers = parse_awg_dump(
        "awg0\tpub1\tpsk1\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
    )
    links = audit_peers(peers, now_unix=1700000030)
    probes = []
    report = build_report(cascade="cascade-alpha", links=links, e2e_probes=probes)

    if json_output:
        typer.echo(report_to_json(report))
    else:
        typer.echo(format_report_text(report))
    raise typer.Exit(code=ExitCode.OK if report.ok else ExitCode.CRITICAL)


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
def menu() -> None:
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
        from awg_cascade_ctl.check import (
            audit_peers,
            build_report,
            format_report_text,
            parse_awg_dump,
        )
        peers = parse_awg_dump(
            "awg0\tpub1\tpsk1\t10.10.1.1:51820\t10.10.1.0/30\t1700000000\t1000\t2000\t25\n"
        )
        links = audit_peers(peers, now_unix=1700000030)
        probes = []
        report = build_report(cascade="cascade-alpha", links=links, e2e_probes=probes)
        typer.echo(format_report_text(report))
        raise typer.Exit(code=ExitCode.OK if report.ok else ExitCode.CRITICAL)

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
            menu()
            return
        else:
            typer.echo(
                "ERROR: --interactive requires a TTY and questionary.",
                err=True,
            )
            raise typer.Exit(code=ExitCode.USAGE_ERROR)
    app()


if __name__ == "__main__":
    main()