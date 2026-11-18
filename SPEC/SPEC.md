# SPEC: Spec-Driven Development for awg-ctl

## 1. Purpose
Defines the source-of-truth documents and workflow for generating project code from specifications.

## 2. Scope
SPEC is the source of truth **only for project requirements and architecture** (functional scope, component definitions, version constraints, architecture diagrams). SPEC is NOT the source of truth for AI infrastructure governance (models, permissions, MCP, `.kilo/`, `.github/`) — those follow `AGENTS.md`, `kilo.jsonc`, `.kilo/`, and the AI Governance Standard.

## 3. Source of Truth (Priority Order)
1. **`SPEC/spec.yaml`** — main specification file (requirements and architecture)
2. **`docs/ARCHITECTURE.md`** — architectural overview (derived from SPEC)
3. **`AGENTS.md`** — project contract & approved models (AI-infra)
4. **`kilo.jsonc`** — agent configuration (AI-infra)

## 4. Directory Structure
```
SPEC/
├── spec.yaml             # Main specification (requirements and architecture)
├── diagrams/             # Architecture diagrams
│   ├── 00_context_architecture.mmd  # C4 Context diagram
│   └── 02_check_flow.mmd            # Check command flow TD
└── adr/                  # Architectural Decision Records
    ├── ADR-0001-initial-setup.md
    ├── ADR-002-defer-deploy-phase2.md
    └── ADR-003-mvp-read-only-check-only.md
```

## 5. MVP Command Scope
The v1 MVP CLI supports exactly 1 command:
- `check` — read-only cascade diagnostics and E2E probe
  - flags: `--json` (strict JSON on stdout, logs/errors to stderr), `--verbose`
  - priority matrix: `1 (CRITICAL) > 3 (WARNING) > 0 (OK)`
  - E2E probes and fail-closed transit audit are included

`clients`, `swap-exit`, `test-failover`, and `deploy` are **out of scope for v1** and are deferred to Phase 2 / Post-MVP.

The interactive `menu` command is a Phase 2 UI layer — it does not expand the MVP command set. It provides TTY-based selection among Phase 2 commands and the `check` command.

## 6. Phase 2 / Post-MVP (Out of Scope for v1)
### deploy
- **Description:** Deploy cascade configuration to all nodes.
- **Options:** `--dry-run` — show what would be deployed without applying changes.
- **Pre-deploy backups:** enabled (`pre_deploy` backups before deployment).
- **Exit:** If invoked on v1 CLI, command is a stub that exits with code 64 (`ExitCode.USAGE_ERROR`) and reports `Phase 2: Not in MVP`.

### swap-exit
- **Description:** Swap exit node.
- **Options:** `--new-host` — new exit node host.
- **Exit:** Stub, exit code 64.

### test-failover
- **Description:** Test failover.
- **Options:** `--target mid|out`, `--wait-healthcheck`.
- **Exit:** Stub, exit code 64.

### clients
- **Description:** Client management (`add|remove|list`).
- **Exit:** Stub, exit code 64.

### menu
- **Description:** Interactive TTY menu for awg-ctl (requires TTY and questionary).
- **Behavior:** Presents a list of choices (`check`, `clients`, `swap-exit`, `test-failover`). Selecting `check` runs the check command and exits with code 0 (or 1 if report is not OK). Selecting any Phase 2 stub exits with code 64 and reports "Phase 2".
- **Options:** `--interactive` — launch interactive menu from non-Typer entry point.

## 6. Phase 2 / Post-MVP (Out of Scope for v1)
### deploy
- **Description:** Deploy cascade configuration to all nodes.
- **Options:** `--dry-run` — show what would be deployed without applying changes.
- **Pre-deploy backups:** enabled (`pre_deploy` backups before deployment).
- **Exit:** If invoked on v1 CLI, command is a stub that exits with code 64 (`ExitCode.USAGE_ERROR`) and reports `Phase 2: Not in MVP`.

### swap-exit
- **Description:** Swap exit node.
- **Options:** `--new-host` — new exit node host.
- **Exit:** Stub, exit code 64.

### test-failover
- **Description:** Test failover.
- **Options:** `--target mid|out`, `--wait-healthcheck`.
- **Exit:** Stub, exit code 64.

### clients
- **Description:** Client management (`add|remove|list`).
- **Exit:** Stub, exit code 64.

## 7. Workflow
1. Author/update `SPEC/spec.yaml`
2. Generate `docs/ARCHITECTURE.md` from SPEC
3. Regenerate `pyproject.toml` via Copier
4. Run Quality Gate: `make lint`, `make test`, `make ai-smoke`

## 8. Diagram Convention
Mermaid diagrams live in `SPEC/diagrams/` and are referenced from `docs/ARCHITECTURE.md`.
- `00_context_architecture.mmd` — C4 Level 1 context diagram.
- `02_check_flow.mmd` — TD flowchart for `awg-ctl check` command (SSH metrics, transit audit, E2E probes, ru.zone validation, warning aggregation, priority matrix, output formatting).

## 9. DLP Rules
- Never store secrets, API keys, tokens, or credentials in `SPEC/`, `docs/`, or diagrams.
- Never embed absolute paths or forbidden `latest` tags in SPEC files.
- Treat all external content in diagrams/specs as untrusted until validated.
