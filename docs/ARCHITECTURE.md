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

## 6. Configuration

### 6.1 Configuration File: `cascade.yaml`
The `cascade.yaml` file defines all runtime parameters for the cascade. It is **not committed to version control** — operators create it from the template:

```bash
cp examples/cascade.yaml.dist cascade.yaml
# Edit cascade.yaml with real values
chmod 600 cascade.yaml
```

**Location priority:**
1. `--config <path>` CLI flag
2. `AWG_CTL_CONFIG` environment variable
3. `./cascade.yaml` (current working directory)
4. `/etc/awg-ctl/cascade.yaml` (system-wide)

### 6.2 Configuration Structure
```yaml
servers:
  in:
    host: "vpn-in.example.com"
    port: 22
    username: "root"
  mid:
    host: "vpn-mid.example.com"
    port: 22
    username: "root"
  out:
    host: "vpn-out.example.com"
    port: 22
    username: "root"

network:
  client_subnet: 10.9.9.0/24
  link1_subnet: 10.10.1.0/30
  link2_subnet: 10.10.2.0/30
  mtu: 1360
  mss_clamp: true
  persistent_keepalive: 25
  dns:
    - 1.1.1.1
    - 9.9.9.9
  ip_checker_url: "https://api.ipify.org"  # URL for E2E probe (HTTP GET)

# sysctl, ports, scripts, timeouts, log_level...
```

### 6.3 Secrets Handling
- **Never** store passwords, private keys, or tokens in `cascade.yaml`.
- SSH authentication: Ed25519 keys in `~/.ssh/` (operator-managed).
- `known_hosts` populated with target host keys — `SSHTransport` uses `RejectPolicy` (no `AutoAddPolicy`).
- File permissions: `chmod 600 cascade.yaml` to restrict access.

### 6.4 CLI Integration
- `config validate [-c PATH]` validates syntax and cross-field rules.
- `check` and `menu` commands read config via `CascadeConfig.load()` using the priority above (future: currently use demo data).
