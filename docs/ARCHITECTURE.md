# Architecture: awg-ctl

## 1. Overview
CLI для управления многоуровневым каскадом AmneziaWG (awg-in → awg-mid → awg-out) с поддержкой SSH ProxyJump, кэскадных блокировок, проверок и failover команд.

## 2. Directory Structure
- `src/awg_cascade_ctl/` — core application code
- `tests/` — automated unit and smoke tests
- `.kilo/` — AI agent workflows, registries, and security policies
- `scripts/` — governance validation and smoke test scripts

## 3. Context Diagram
See `SPEC/diagrams/00_context_architecture.mmd` for the high-level flow of admin traffic through awg-in, awg-mid, awg-out (ProxyJump), cascade subnets (10.9.9.0/24, 10.10.1.0/30, 10.10.2.0/30), routing tables 100/200, and external dependencies.

## 4. Check Command Flow
See `SPEC/diagrams/02_check_flow.mmd` for the TD flowchart of `awg-ctl check` covering SSH metrics, transit audit, E2E probes, ru.zone validation, warning aggregation, priority matrix, and output formatting.

## 5. Command Scope
MVP (v1) supports exactly one **Read-Only** command: `check` (incl. `--json`, `--verbose`, priority matrix `1 > 3 > 0`, E2E probes, fail-closed audit).
The mutating commands `clients`, `swap-exit`, `test-failover` are deferred to **Phase 2 / Post-MVP**. The `deploy` command (incl. `--dry-run` and `pre_deploy` backups) is also deferred to Phase 2 / Post-MVP.
Phase 2 stubs exit with code 64 (`ExitCode.USAGE_ERROR`) and report the deferral.

**Phase 2 UI Layer:** The `menu` command provides an interactive TTY-based menu (via `questionary`) with items `check`, `clients`, `swap-exit`, `test-failover`. Selecting `check` runs the check command and exits with its code (0 for OK, 1 for CRITICAL). Selecting any Phase 2 stub exits with code 64 and reports "Phase 2". The `--interactive` flag launches the menu from the CLI entry point. Requires TTY and questionary; otherwise exits with code 64.
