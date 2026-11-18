"""Tests for awg-ctl CLI commands."""

import json
from unittest import mock

import questionary
from typer.testing import CliRunner

from awg_cascade_ctl.cli import app

runner = CliRunner()


def test_help() -> None:
    """Help exits 0 and lists check/schema commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check" in result.output
    assert "schema" in result.output


def test_version() -> None:
    """Version exits 0."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "awg-ctl" in result.output


def test_check_human() -> None:
    """check without --json outputs human-readable text."""
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_check_json() -> None:
    """check --json outputs valid JSON only."""
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema_version"] == "1.0"
    assert "links" in data


def test_schema_json() -> None:
    """schema --json outputs valid JSON schema."""
    result = runner.invoke(app, ["schema", "--json"])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"


def test_config_validate_stub_runs() -> None:
    """config validate runs without crashing."""
    result = runner.invoke(app, ["config", "validate", "--help"])
    assert result.exit_code == 0


def test_exit_code_ok_for_good_report() -> None:
    """A good report returns exit code 0."""
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0


def test_phase2_stubs_exit_64() -> None:
    """Phase 2 command stubs exit with code 64 and report Phase 2."""
    commands = [
        ["deploy"],
        ["swap-exit", "--new-host", "vpn-out2.example.com"],
        ["test-failover", "--target", "mid"],
        ["clients", "list"],
    ]
    for cmd_args in commands:
        result = runner.invoke(app, cmd_args)
        assert result.exit_code == 64
        assert "Phase 2" in result.output
        assert "Out of Scope for v1" in result.output


def test_menu_no_tty_exits_64(monkeypatch) -> None:
    """Menu exits with code 64 when stdin is not a TTY."""
    monkeypatch.setattr(
        "awg_cascade_ctl.cli._is_interactive_mode",
        lambda: False,
    )
    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 64
    assert "TTY" in result.output


def test_menu_tty_runs_check(monkeypatch) -> None:
    """Menu with TTY and mocked questionary select runs check."""
    monkeypatch.setattr(
        "awg_cascade_ctl.cli._is_interactive_mode",
        lambda: True,
    )
    monkeypatch.setattr(
        "awg_cascade_ctl.cli.QUESTIONARY_AVAILABLE",
        True,
    )
    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "check        \u2014 Run cascade check and E2E probe"
    monkeypatch.setattr(questionary, "select", mock_select)

    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_menu_phase2_stub_exits_64(monkeypatch) -> None:
    """Menu selecting a Phase 2 command exits with code 64."""
    monkeypatch.setattr(
        "awg_cascade_ctl.cli._is_interactive_mode",
        lambda: True,
    )
    monkeypatch.setattr(
        "awg_cascade_ctl.cli.QUESTIONARY_AVAILABLE",
        True,
    )
    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "clients      \u2014 Manage clients (Phase 2 stub)"
    monkeypatch.setattr(questionary, "select", mock_select)

    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 64
    assert "Phase 2" in result.output