# ADR-004: Per-server SSH key selection and clean SSH error messages

- **Status:** Accepted
- **Date:** 2026-11-23
- **Scope:** awg-ctl v1.0 MVP (`check` command)

## Context

`load_real_dump_target` previously resolved the SSH key via
`resolve_ssh_key_from_config(cfg, explicit_key_path=key_path)`, which iterated
servers in `("in", "mid", "out")` order and returned the *first* server with a
`ssh_key_path`. Consequently `mid`, `out` and `all` always used the `in`
server's key (`~/.ssh/awg_in_key`), producing `PasswordRequiredException` for
encrypted mid/out keys and leaking full Python tracebacks to the user.

## Decision

Resolve the SSH key strictly per target server, mirroring the fix already
applied to `diagnose` (commit `87cae0e`):

1. CLI `--key-path` (explicit override, always wins).
2. `cascade.yaml` `servers.<target>.ssh_key_path` for the target server.
3. `None` → `SSHTransport` auto-detect (agent / default keys).

Wrap `connect()` / `run_awg_dump()` failures in `SSHDumpError(RuntimeError)`
carrying `server`, `host`, `port`, `key_path` and the original `exc`. In
`_run_check` print a single-line English message via `describe_ssh_error(...)` to
stderr and return `ExitCode.CRITICAL` (1). No traceback, passphrase, or key
material is leaked. `--server all` aborts on the first failing server and names
it in the message.

## Alternatives considered

- Keep first-server key resolution: rejected — breaks `mid`/`out`/`all` with
  encrypted keys; the wrong key is silently used.
- Return raw exception / full traceback to user: rejected — violates the
  non-interactive automation contract and leaks internals.
- Introduce a new dedicated exit code: rejected — reuse `ExitCode.CRITICAL` (1),
  no new codes introduced.

## Consequences

- `mid`, `out`, `all` use their own `servers.<target>.ssh_key_path`.
- SSH failures produce exactly one clean stderr line and exit code 1.
- The `--ask-pass` interactive flow is preserved unchanged.
- No new dependency is added.