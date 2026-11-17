"""Tests for awg-ctl CLI commands."""

from typer.testing import CliRunner

from awg_cascade_ctl.cli import app

runner = CliRunner()


def test_help() -> None:
    """Help should exit with code 0 and show command info."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output


def test_version_flag() -> None:
    """Version flag should exit with code 0."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0