# ADR-005: Add traceroute diagnostics to check command

- **Status:** Accepted
- **Date:** 2026-11-23
- **Scope:** awg-ctl v1.0 MVP (`check` command)

## Context

The `check` command performs cascade health diagnostics and E2E probes but lacks a network path visibility tool. Operators often need to verify routing and intermediate hops to cascade servers (`in`, `mid`, `out`) to distinguish between server-side issues and network path problems.

A traceroute capability was requested to be integrated into `check` as an opt-in diagnostic.

## Decision

Add a traceroute module to `check` with the following design:

1. **Target**: Only the IP address of the server selected via `--server` (`in`/`mid`/`out`/`all`). For `all`, traceroute runs sequentially for each server.

2. **Tool selection**: Fallback chain `traceroute → mtr → ping`. The first available tool on the system is used.
   - `traceroute` (standard, prints hops with RTTs)
   - `mtr` (one-shot mode `--report --report-cycles 1`)
   - `ping` with incrementing TTL (emulates traceroute if others unavailable)

3. **Trigger**: Opt-in via **both** mechanisms:
   - CLI flag `--trace` (typer.Option, default `False`)
   - Interactive prompt (when stdin is TTY, `--server` given, no `--trace` flag)

4. **Output**: 
   - Text report: separate section "Traceroute:" printed after E2E probes.
   - JSON (`--json`): **not modified** — traceroute is a human-readable diagnostic, not part of the strict contract.
   - Exit code / status: **unchanged** — traceroute failure does not affect `check` pass/fail.

5. **Timeouts & reliability**: 
   - Subprocess timeout: 30 seconds per traceroute.
   - If no tool available, print "No traceroute tool available" and continue.
   - Errors from the tool captured and printed in the output section.

6. **Tests**: Synthetic only, no real network calls. Mock `subprocess.run` to return canned traceroute/mtr/ping output.

## Alternatives considered

- Always run traceroute: rejected — adds latency and noise for CI/automation; opt-in preferred.
- Only flag `--trace` without interactive prompt: rejected — interactive prompt matches existing `--ask-pass` UX pattern.
- Include traceroute in JSON output: rejected — JSON contract is frozen for v1; traceroute is unstructured text.
- New command `awg-ctl trace`: rejected — traceroute is tightly coupled to `check`'s server selection; keeping it inside `check` avoids duplication of `--server`/config logic.
- Affect `check` status on traceroute failure: rejected — traceroute is informational; network path issues are often outside cascade control.

## Consequences

- New dependency: none (uses standard `subprocess`).
- New option: `--trace` in `check` command.
- New interactive flow: prompt "Run traceroute to <server>?" (if TTY, no `--trace`).
- Text report gains a "Traceroute:" section.
- JSON output unchanged.
- Exit codes unchanged.
- Tests added to `tests/test_check.py` with mocked subprocess.