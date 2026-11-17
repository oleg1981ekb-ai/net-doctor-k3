"""awg-ctl CLI entry point."""

import typer

from awg_cascade_ctl import __version__

app = typer.Typer(
    name="awg-ctl",
    help="Service CLI for managing a 3-node AmneziaWG cascade.",
)


@app.command(name="version")
def version() -> None:
    """Show the awg-ctl version."""
    typer.echo(f"awg-ctl {__version__}")


@app.command(name="check")
def check() -> None:
    """Run cascade check and E2E probe."""
    typer.echo("check: not implemented yet")


def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()