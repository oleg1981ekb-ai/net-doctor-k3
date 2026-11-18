# ADR-003: Narrow MVP to Read-Only `check` command

- **Status:** Accepted
- **Date:** 2026-11-18
- **Scope:** awg-ctl v1.0 MVP

## Context

The v1 MVP initially included 4 CLI commands: `check`, `swap-exit`, `test-failover`, `clients`. The `deploy` command was already deferred to Phase 2 (see ADR-002). However, `swap-exit`, `test-failover`, and `clients` are **mutating operations** that change cascade state, reconfigure peers, or trigger failover. Introducing them in v1 increases the risk of unintended state changes before the Read-Only diagnostics are proven in production.

## Decision

Narrow the v1 MVP scope **strictly to one Read-Only command**: `check` (diagnostics and reporting). All mutating commands (`swap-exit`, `test-failover`, `clients`) are deferred to Phase 2 / Post-MVP.

In v1 CLI:
- `check` is the only fully implemented command.
- `swap-exit`, `test-failover`, `clients`, and `deploy` are stubs that exit with code `64` (`ExitCode.USAGE_ERROR`) and report `Phase 2: Not in MVP`.

## Alternatives considered

- Keep 4-command MVP: rejected — mutating commands require additional safety guarantees (locks, idempotency, rollback) not yet validated in production.
- Omit stubs entirely: rejected — silent acceptance of unknown commands would violate the explicit error contract.
- Implement `check` plus one mutating command: rejected — partial mutating support gives false confidence without full safety coverage.

## Consequences

- v1 CLI surface is minimal and safe: read-only diagnostics only.
- `check` must satisfy TZ §4.1 strict JSON contract and priority matrix `1 > 3 > 0`.
- Mutating commands are tracked as Phase 2 work.
- Stubs prevent accidental invocation and keep CLI behavior aligned with documentation.
- Phase 2 must re-validate locking, idempotency, and rollback before implementing mutating commands.
