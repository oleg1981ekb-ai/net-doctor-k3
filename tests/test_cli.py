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
    mock_select.return_value.ask.return_value = "clients      — Manage clients (Phase 2 stub)"
    monkeypatch.setattr(questionary, "select", mock_select)

    result = runner.invoke(app, ["menu"])
    assert result.exit_code == 64
    assert "Phase 2" in result.output


def test_check_json_non_tty_valid_no_ansi(monkeypatch) -> None:
    """check --json in non-TTY (CI) emits valid JSON without ANSI codes."""
    result = runner.invoke(app, ["check", "--json"])
    assert result.exit_code == 0
    assert "\033[" not in result.output
    data = json.loads(result.output)
    assert data["schema"] == "awg-ctl/check/v1"
    assert data["ok"] is True


def test_check_stdout_empty_stderr_on_success(monkeypatch) -> None:
    """check success writes nothing to stderr."""
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert result.stderr == ""


def test_check_color_never_no_ansi(monkeypatch) -> None:
    """check with --color never emits ANSI codes."""
    result = runner.invoke(app, ["check", "--color", "never"])
    assert result.exit_code == 0
    assert "\033[" not in result.output


def test_check_with_dump_file(tmp_path) -> None:
    """check --dump-file reads from a local dump file."""
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text(
        "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t"
        "1700000000\t1000\t2000\t25\n"
    )
    result = runner.invoke(app, ["check", "--dump-file", str(dump_path)])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_check_with_dump_file_json(tmp_path) -> None:
    """check --dump-file --json outputs valid JSON."""
    dump_path = tmp_path / "dump.txt"
    dump_path.write_text(
        "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t"
        "1700000000\t1000\t2000\t25\n"
    )
    result = runner.invoke(app, ["check", "--dump-file", str(dump_path), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["schema"] == "awg-ctl/check/v1"
    assert data["ok"] is True


def test_check_with_config(monkeypatch, tmp_path) -> None:
    """check --config loads from cascade.yaml and SSH dump."""
    from awg_cascade_ctl import cli as cli_module
    from awg_cascade_ctl.check import parse_awg_dump

    # Mock load_real_dump to avoid actual SSH
    mock_peers = parse_awg_dump(
        "awg0\tPUB\tPSK\t10.10.1.1:51820\t10.10.1.0/30\t"
        "1700000000\t1000\t2000\t25\n"
    )
    monkeypatch.setattr(cli_module, "load_real_dump", lambda **kw: mock_peers)
    monkeypatch.setattr(cli_module, "load_e2e_probes", lambda **kw: [])

    result = runner.invoke(app, ["check", "--config", str(tmp_path / "cascade.yaml")])
    assert result.exit_code == 0
    assert "overall: OK" in result.output


def test_menu_with_config(monkeypatch) -> None:
    """menu --config forwards config to check."""
    monkeypatch.setattr(
        "awg_cascade_ctl.cli._is_interactive_mode",
        lambda: True,
    )
    monkeypatch.setattr(
        "awg_cascade_ctl.cli.QUESTIONARY_AVAILABLE",
        True,
    )
    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "check        — Run cascade check and E2E probe"
    monkeypatch.setattr(questionary, "select", mock_select)

    # Mock _run_check to capture args
    captured = {}
    def fake_run_check(**kwargs):
        captured.update(kwargs)
        return 0
    monkeypatch.setattr("awg_cascade_ctl.cli._run_check", fake_run_check)

    result = runner.invoke(app, ["menu", "--config", "/tmp/cascade.yaml"])
    assert result.exit_code == 0
    assert captured.get("config_path") == "/tmp/cascade.yaml"

def test_check_explicit_config_skips_pause(monkeypatch) -> None:
    """check --config skips 3s pause and never calls _wait_for_key_or_timeout."""
    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr(cli_module, "_is_interactive_mode", lambda: True)
    called = {"value": False}

    def failing_wait(seconds: float) -> bool:
        called["value"] = True
        raise AssertionError("_wait_for_key_or_timeout must not be called for explicit source")

    monkeypatch.setattr(cli_module, "_wait_for_key_or_timeout", failing_wait)

    captured = {}

    def fake_run_check(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_module, "_run_check", fake_run_check)

    result = runner.invoke(app, ["check", "--config", "/tmp/cascade.yaml"])
    assert result.exit_code == 0
    assert called["value"] is False
    assert captured.get("config_path") == "/tmp/cascade.yaml"


def test_check_explicit_dump_file_skips_pause(monkeypatch) -> None:
    """check --dump-file skips 3s pause and never calls _wait_for_key_or_timeout."""
    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr(cli_module, "_is_interactive_mode", lambda: True)
    called = {"value": False}

    def failing_wait(seconds: float) -> bool:
        called["value"] = True
        raise AssertionError("_wait_for_key_or_timeout must not be called for explicit source")

    monkeypatch.setattr(cli_module, "_wait_for_key_or_timeout", failing_wait)

    captured = {}

    def fake_run_check(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_module, "_run_check", fake_run_check)

    result = runner.invoke(app, ["check", "--dump-file", "/tmp/dump.txt"])
    assert result.exit_code == 0
    assert called["value"] is False
    assert captured.get("dump_file") == "/tmp/dump.txt"


def test_check_non_interactive_runs_demo(monkeypatch) -> None:
    """check in non-interactive mode runs demo directly without pause."""
    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr(cli_module, "_is_interactive_mode", lambda: False)
    called = {"value": False}

    def failing_wait(seconds: float) -> bool:
        called["value"] = True
        raise AssertionError("_wait_for_key_or_timeout must not be called when non-interactive")

    monkeypatch.setattr(cli_module, "_wait_for_key_or_timeout", failing_wait)

    captured = {}

    def fake_run_check(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(cli_module, "_run_check", fake_run_check)

    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0
    assert called["value"] is False
    assert captured.get("config_path") is None
    assert captured.get("dump_file") is None


def test_resolve_check_source_explicit_passthrough() -> None:
    """_resolve_check_source returns explicit config/dump unchanged."""
    from awg_cascade_ctl import cli as cli_module

    assert cli_module._resolve_check_source("/tmp/c.yaml", None) == ("/tmp/c.yaml", None)
    assert cli_module._resolve_check_source(None, "/tmp/d.txt") == (None, "/tmp/d.txt")


def test_resolve_check_source_interactive_timeout_returns_demo(monkeypatch) -> None:
    """_resolve_check_source interactive + timeout -> demo (None, None)."""
    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr(cli_module, "_is_interactive_mode", lambda: True)
    monkeypatch.setattr(cli_module, "_wait_for_key_or_timeout", lambda seconds: False)
    assert cli_module._resolve_check_source(None, None) == (None, None)


def test_resolve_check_source_interactive_keypress_opens_menu(monkeypatch) -> None:
    """_resolve_check_source interactive + keypress -> chosen menu values."""
    from awg_cascade_ctl import cli as cli_module

    monkeypatch.setattr(cli_module, "_is_interactive_mode", lambda: True)
    monkeypatch.setattr(cli_module, "_wait_for_key_or_timeout", lambda seconds: True)
    monkeypatch.setattr(cli_module, "_source_selection_menu", lambda: ("/tmp/c.yaml", None))
    assert cli_module._resolve_check_source(None, None) == ("/tmp/c.yaml", None)


def test_source_selection_menu_demo_choice(monkeypatch) -> None:
    """_source_selection_menu Demo choice -> demo (None, None)."""
    from awg_cascade_ctl import cli as cli_module

    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "demo"
    monkeypatch.setattr(questionary, "select", mock_select)
    assert cli_module._source_selection_menu() == (None, None)


def test_source_selection_menu_dump_file_choice(monkeypatch) -> None:
    """_source_selection_menu Dump file choice -> (None, path)."""
    from awg_cascade_ctl import cli as cli_module

    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "dump_file"
    mock_text = mock.MagicMock()
    mock_text.return_value.ask.return_value = "./dump.txt"
    monkeypatch.setattr(questionary, "select", mock_select)
    monkeypatch.setattr(questionary, "text", mock_text)
    assert cli_module._source_selection_menu() == (None, "./dump.txt")


def test_source_selection_menu_ssh_choice(monkeypatch) -> None:
    """_source_selection_menu SSH choice -> (config_path, None)."""
    from awg_cascade_ctl import cli as cli_module

    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = "ssh"
    mock_text = mock.MagicMock()
    mock_text.return_value.ask.return_value = "./cascade.yaml"
    monkeypatch.setattr(questionary, "select", mock_select)
    monkeypatch.setattr(questionary, "text", mock_text)
    assert cli_module._source_selection_menu() == ("./cascade.yaml", None)


def test_source_selection_menu_esc_falls_back_to_demo(monkeypatch) -> None:
    """_source_selection_menu ESC / empty selection -> demo (None, None)."""
    from awg_cascade_ctl import cli as cli_module

    mock_select = mock.MagicMock()
    mock_select.return_value.ask.return_value = None
    monkeypatch.setattr(questionary, "select", mock_select)
    assert cli_module._source_selection_menu() == (None, None)


def test_wait_for_key_or_timeout_non_tty_returns_false(monkeypatch) -> None:
    """_wait_for_key_or_timeout returns False on non-TTY stdin without blocking."""
    from awg_cascade_ctl import cli as cli_module

    fake_stdin = mock.MagicMock()
    fake_stdin.isatty.return_value = False
    monkeypatch.setattr(cli_module.sys, "stdin", fake_stdin)
    assert cli_module._wait_for_key_or_timeout(0.01) is False
