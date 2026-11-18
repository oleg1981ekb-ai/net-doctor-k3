# ADR-002: Defer `deploy` command to Phase 2 / Post-MVP

- **Status:** Accepted
- **Date:** 2026-11-18
- **Scope:** awg-ctl v1.0 MVP (`TZ-awg-ctl-v4.0-final`)

## Context

The approved v1 MVP scope includes exactly 4 CLI commands:
- `check` — cascade check and E2E probe (strict JSON contract via `--json`)
- `swap-exit` — swap exit node (`--new-host`)
- `test-failover` — failover test (`--target mid|out`, `--wait-healthcheck`)
- `clients` — client management (`add|remove|list`)

The `deploy` command (including `--dry-run` and `pre_deploy` backups) was initially part of the broader roadmap, but v1 must stay minimal, scriptable, and idempotent per TZ §3.1 and §4.1.

## Decision

Defer `deploy` to **Phase 2 / Post-MVP**. In v1 the `deploy` command exists only as a stub that exits with code `64` (`ExitCode.USAGE_ERROR`) and reports `Phase 2: Not in MVP`.

- `SPEC/spec.yaml` and `SPEC/SPEC.md` list `deploy` under `Phase 2 / Post-MVP (Out of Scope for v1)`.
- `docs/ARCHITECTURE.md` reflects that `deploy` is Phase 2.
- `SPEC/diagrams/00_lifecycle.mmd` (if created) should route `deploy` to `NotImplemented[Phase 2: Not in MVP -> Exit 64]`.

## Alternatives considered

- **Implement `deploy` in v1:** rejected — expands scope, risks blocking the v1 release, and requires pre_deploy backup logic not yet validated.
- **Omit the stub entirely:** rejected — a stub with a clear exit code and message prevents silent misuse and aligns with the non-interactive automation contract.
- **Implement `deploy` without `--dry-run`:** rejected — violates the idempotency and safety requirements for production automation.

## Consequences

- v1 CLI supports exactly 4 commands: `check`, `swap-exit`, `test-failover`, `clients`.
- `deploy` (with `--dry-run` and `pre_deploy` backups) is tracked as Phase 2 work.
- The stub prevents accidental invocation and exits with code 64.
- No new diagrams are created at this step; `00_lifecycle.mmd` may be added later.
- Phase 2 backlog must include `deploy` implementation with pre_deploy backup verification.
