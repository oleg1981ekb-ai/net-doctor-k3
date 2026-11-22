"""Tests for the awg_cascade_ctl package."""

import typer

from awg_cascade_ctl import __version__
from awg_cascade_ctl.cli import app


def test_version() -> None:
    """Version should be exposed."""
    assert __version__ == "0.1.0"


def test_cli_app_exists() -> None:
    """CLI app should be constructed."""
    assert app is not None


def test_version_command() -> None:
    """Version command should run via Typer."""
    runner = typer.testing.CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
