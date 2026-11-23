# Architecture Decision Records (ADR)

Format: Context → Decision → Alternatives → Consequences.

---

## ADR-001: Defer `questionary`-based interactive menu

- **Status:** Reversed (interactive menu reintroduced for MVP phase 2 scope)
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

### Reversal (2026-11-18)
The interactive menu scope was revisited for MVP phase planning. The `menu` command / `--interactive` flag was implemented as an **opt-in** flow, isolated from the read-only `check` JSON contract, with TTY/CI guards. ADR-001 is therefore reversed; the underlying guardrails (no JSON pollution, non-interactive fallback, minimal scope) remain.

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

---

## ADR-004: Per-server SSH key selection; clean SSH error messages

- **Status:** Accepted
- **Date:** 2026-11-23
- **Scope:** awg-ctl v1.0 MVP (`check` command)

### Context

`load_real_dump_target` previously resolved the SSH key via
`resolve_ssh_key_from_config(cfg, explicit_key_path=key_path)`, which iterated
servers in `("in", "mid", "out")` order and returned the *first* server with a
`ssh_key_path`. Consequently `mid`, `out` and `all` always used the `in`
server's key (`~/.ssh/awg_in_key`), producing `PasswordRequiredException` for
encrypted mid/out keys and leaking full Python tracebacks to the user.

### Decision

Resolve the SSH key strictly per target server, mirroring the fix already applied
to `diagnose` (commit `87cae0e`):

1. CLI `--key-path` (explicit override, always wins).
2. `cascade.yaml` `servers.<target>.ssh_key_path` for the target server.
3. `None` → `SSHTransport` auto-detect (agent / default keys).

Wrap `connect()` / `run_awg_dump()` failures in `SSHDumpError(RuntimeError)`
carrying `server`, `host`, `port`, `key_path` and the original `exc`. In
`_run_check` print a single-line English message via `describe_ssh_error(...)` to
stderr and return `ExitCode.CRITICAL` (1). No traceback, passphrase, or key
material is leaked. `--server all` aborts on the first failing server and names
it in the message.

### Alternatives considered

- Keep first-server key resolution: rejected — breaks `mid`/`out`/`all` with
  encrypted keys; the wrong key is silently used.
- Return raw exception / full traceback to user: rejected — violates the
  non-interactive automation contract and leaks internals.
- Introduce a new dedicated exit code: rejected — reuse `ExitCode.CRITICAL` (1),
  no new codes introduced.

### Consequences

- `mid`, `out`, `all` use their own `servers.<target>.ssh_key_path`.
- SSH failures produce exactly one clean stderr line and exit code 1.
- The `--ask-pass` interactive flow is preserved unchanged.
- No new dependency is added.