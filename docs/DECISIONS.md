# Architecture Decision Records (ADR)

Format: Context → Decision → Alternatives → Consequences.

---

## ADR-001: Defer `questionary`-based interactive menu

- **Status:** Accepted (deferred)
- **Date:** 2026-11-17
- **Scope:** out of scope for v1.0 (`TZ-awg-ctl-v4.0-final`)

### Context

The approved stack in TZ §3.1 is limited to `Python >= 3.11, Typer, Rich, Fabric (Paramiko), Pydantic v2, PyYAML`. The CLI is a service-oriented automation tool: `check`, `deploy`, `swap-exit`, `test-failover` must be scriptable and idempotent. TZ §4.1 requires a strict machine-readable contract: `check --json` must emit only valid JSON on stdout (logs/errors to stderr).

An interactive menu library (`questionary`) would:

- intercept stdout and break the JSON contract;
- contradict the non-interactive automation design (CI, cron, Ansible);
- introduce a new dependency outside the approved stack.

### Decision

Do not add `questionary` to the stack for v1.0. Keep `Typer` (argument parsing) and `Rich` (terminal output formatting: tables, panels, progress). Any future interactive menu must be delivered as a separate scope change (new TZ revision + PR) and must not affect the `--json` output mode.

### Alternatives considered

- Add `questionary` now: rejected — violates TZ §3.1 and §4.1, out of scope.
- Build a custom TUI: rejected — over-engineering for a service CLI; Typer + Rich are sufficient.
- Skip menus entirely: accepted — CLI arguments are the intended interface.

### Consequences

- All interactions remain non-interactive and scriptable.
- Menus (if ever needed) are deferred to a future revision.
- `questionary` must not be added to `pyproject.toml` dependencies without a new decision record.

---

## ADR-002: Defer `deploy` command to Phase 2 / Post-MVP

- **Status:** Accepted
- **Date:** 2026-11-18
- **Scope:** awg-ctl v1.0 MVP

### Context

The v1 MVP includes exactly 4 CLI commands: `check`, `swap-exit`, `test-failover`, `clients`. The `deploy` command (with `--dry-run` and `pre_deploy` backups) is deferred to Phase 2.

### Decision

Defer `deploy` to Phase 2 / Post-MVP. In v1 the `deploy` command is a stub that exits with code `64` and reports `Phase 2: Not in MVP`.

### Alternatives considered

- Implement `deploy` in v1: rejected — expands scope beyond v1 MVP constraints.
- Omit the stub entirely: rejected — would risk silent misuse.
- Implement `deploy` without `--dry-run`: rejected — violates safety requirements.

### Consequences

- v1 CLI supports exactly 4 commands.
- `deploy` is tracked as Phase 2 work.
- Stub prevents accidental invocation.

---

## ADR-003: Narrow MVP to Read-Only `check` command only

- **Status:** Accepted
- **Date:** 2026-11-18
- **Scope:** awg-ctl v1.0 MVP

### Context

The v1 MVP initially included four CLI commands: `check`, `swap-exit`, `test-failover`, `clients`. `deploy` was already deferred to Phase 2 (ADR-002). The remaining mutating commands (`swap-exit`, `test-failover`, `clients`) change cascade state or trigger failover, which increases risk before Read-Only diagnostics are validated.

### Decision

Narrow the v1 MVP scope strictly to the single Read-Only command: `check`. All mutating commands are deferred to Phase 2 / Post-MVP.

### Alternatives considered

- Keep the original 4-command MVP: rejected — mutating operations require additional safety guarantees (locking, idempotency, rollback) before production use.
- Implement `check` plus one mutating command: rejected — partial support lacks full safety coverage.

### Consequences

- v1 CLI provides read-only diagnostics only.
- Mutating commands are tracked as Phase 2 work.
- Stubs (exit 64) prevent accidental invocation of Phase 2 commands.