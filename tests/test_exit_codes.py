"""Tests for exit-code mapping and diagnose schema_version."""

import json
from datetime import date

from typer.testing import CliRunner

from awg_cascade_ctl.cli import app
from awg_cascade_ctl.diagnose import (
    CheckResult,
    DiagnoseReport,
    diagnose_report_to_json,
)
from awg_cascade_ctl.errors import (
    ExitCode,
    is_legacy_expired,
    parse_legacy_until,
    resolve_exit_code_from_outcome,
    resolve_legacy_exit_code,
    validate_exit_flags,
)

runner = CliRunner()


def test_nagios_default_mapping() -> None:
    assert resolve_exit_code_from_outcome("pass") == ExitCode.OK
    assert resolve_exit_code_from_outcome("warning") == ExitCode.WARNING
    assert resolve_exit_code_from_outcome("fail") == ExitCode.CRITICAL
    assert resolve_exit_code_from_outcome("green") == ExitCode.OK
    assert resolve_exit_code_from_outcome("yellow") == ExitCode.WARNING
    assert resolve_exit_code_from_outcome("red") == ExitCode.CRITICAL


def test_unix_mapping_warns_and_fail_both_critical() -> None:
    assert resolve_exit_code_from_outcome("warning", unix=True) == ExitCode.CRITICAL
    assert resolve_exit_code_from_outcome("fail", unix=True) == ExitCode.CRITICAL
    assert resolve_exit_code_from_outcome("pass", unix=True) == ExitCode.OK


def test_unix_warn_as_ok() -> None:
    assert (
        resolve_exit_code_from_outcome("warning", unix=True, warn_as_ok=True)
        == ExitCode.OK
    )
    assert (
        resolve_exit_code_from_outcome("fail", unix=True, warn_as_ok=True)
        == ExitCode.CRITICAL
    )


def test_strict_maps_warn_to_fail() -> None:
    assert resolve_exit_code_from_outcome("warning", strict=True) == ExitCode.CRITICAL
    assert resolve_exit_code_from_outcome("pass", strict=True) == ExitCode.OK


def test_validate_exit_flags_conflict() -> None:
    assert validate_exit_flags(strict=True, warn_as_ok=True) == ExitCode.USAGE_ERROR
    assert validate_exit_flags(strict=True, warn_as_ok=False) is None
    assert validate_exit_flags(strict=False, warn_as_ok=True) is None


def test_parse_legacy_until_valid_and_invalid() -> None:
    parsed = parse_legacy_until("2026-11-21")
    assert isinstance(parsed, date)
    try:
        parse_legacy_until("not-a-date")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_is_legacy_expired() -> None:
    today = date(2026, 11, 21)
    assert is_legacy_expired(date(2020, 1, 1), today=today) is True
    assert is_legacy_expired(date(2099, 1, 1), today=today) is False
    assert is_legacy_expired(date(2026, 11, 21), today=today) is False


def test_resolve_legacy_exit_code() -> None:
    assert resolve_legacy_exit_code("red") == ExitCode.CRITICAL
    assert resolve_legacy_exit_code("yellow") == ExitCode.OK
    assert resolve_legacy_exit_code("green") == ExitCode.OK


def test_diagnose_json_has_schema_version() -> None:
    report = DiagnoseReport(
        server="in",
        results=[
            CheckResult(check="tunnel", status="pass", summary="Туннель awg0 поднят")
        ],
        verdict="green",
        server_ip="10.0.0.1",
        timestamp="2026-11-21 17:00",
    )
    payload = json.loads(diagnose_report_to_json(report))
    assert payload["schema_version"] == "1.0"
    assert payload["schema_id"] == "awg-ctl/diagnose/v1"
    assert payload["verdict"] == "green"


def test_cli_check_strict_warn_as_ok_usage_error() -> None:
    result = runner.invoke(app, ["check", "--strict", "--warn-as-ok"])
    assert result.exit_code == ExitCode.USAGE_ERROR.value
    assert "--strict and --warn-as-ok are mutually exclusive" in result.output


def test_cli_check_exit_unix_collapses_fail_to_1() -> None:
    result = runner.invoke(app, ["check", "--exit-unix"])
    assert result.exit_code == ExitCode.CRITICAL.value
    assert "[unix]" in result.output


def test_cli_diagnose_strict_warn_as_ok_usage_error() -> None:
    result = runner.invoke(app, ["diagnose", "--strict", "--warn-as-ok"])
    assert result.exit_code == ExitCode.USAGE_ERROR.value
    assert "--strict and --warn-as-ok are mutually exclusive" in result.output


def test_cli_diagnose_legacy_until_past_date_usage_error() -> None:
    result = runner.invoke(app, ["diagnose", "--legacy-until", "2020-01-01"])
    assert result.exit_code == ExitCode.USAGE_ERROR.value
    assert "--legacy-until" in result.output


def test_cli_diagnose_legacy_until_bad_format_usage_error() -> None:
    result = runner.invoke(app, ["diagnose", "--legacy-until", "not-a-date"])
    assert result.exit_code == ExitCode.USAGE_ERROR.value
    assert "--legacy-until" in result.output
