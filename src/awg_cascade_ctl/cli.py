"""awg-ctl CLI entry point."""

import typer
from pydantic import ValidationError

from awg_cascade_ctl import __version__
from awg_cascade_ctl.config import CascadeConfig
from awg_cascade_ctl.errors import ExitCode

app = typer.Typer(
    name="awg-ctl",
    help="Service CLI for managing a 3-node AmneziaWG cascade.",
)

config_app = typer.Typer(help="Configuration commands.")


@app.command(name="version")
def version() -> None:
    """Show the awg-ctl version."""
    typer.echo(f"awg-ctl {__version__}")


@app.command(name="check")
def check() -> None:
    """Run cascade check and E2E probe."""
    typer.echo("check: not implemented yet")


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
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()