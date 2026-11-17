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