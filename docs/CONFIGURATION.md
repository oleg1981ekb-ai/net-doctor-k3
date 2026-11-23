# Configuration Guide: awg-ctl `cascade.yaml`

This document describes how to configure `awg-ctl` for production use via `cascade.yaml`.

## 1. Overview

`awg-ctl` reads its runtime configuration from a `cascade.yaml` file. The file defines the cascade topology (servers, subnets, ports), network parameters, timeouts, and E2E probe targets. Secrets (passwords, private keys) are **not** stored in this file — they live in `~/.ssh/` and are referenced by path.

## 2. File Location & Priority

`cascade.yaml` is resolved in the following order:

| Priority | Source | Example |
|----------|--------|---------|
| 1 (highest) | `--config <path>` CLI flag | `awg-ctl --config /etc/awg-ctl/cascade.yaml check` |
| 2 | `AWG_CTL_CONFIG` env var | `export AWG_CTL_CONFIG=/etc/awg-ctl/cascade.yaml` |
| 3 | `./cascade.yaml` | `awg-ctl check` (run from project root) |
| 4 (lowest) | `/etc/awg-ctl/cascade.yaml` | System-wide installation |

**Create your config:**

```bash
cp examples/cascade.yaml.dist cascade.yaml
# Edit cascade.yaml with real values
chmod 600 cascade.yaml
```

## 3. Configuration Sections

### 3.1 `servers` — Cascade Nodes

Defines the three cascade servers (`in`, `mid`, `out`). Each requires `host`, optional `port` (default 22), and `username`.

```yaml
servers:
  in:
    host: "192.0.2.10"
    port: 22
    username: "root"
  mid:
    host: "192.0.2.11"
    port: 22
    username: "root"
  out:
    host: "203.0.113.5"
    port: 22
    username: "root"
```

### 3.2 `network` — WireGuard / AmneziaWG Parameters

```yaml
network:
  client_subnet: 10.9.9.0/24
  link1_subnet: 10.10.1.0/30       # awg-in <-> awg-mid
  link2_subnet: 10.10.2.0/30       # awg-mid <-> awg-out
  mtu: 1360
  mss_clamp: true
  persistent_keepalive: 33  # Reserved; not used by `check` (see check.keepalive_min/max)
  dns:
    - 1.1.1.1
    - 9.9.9.9
  ip_checker_url: "https://api.ipify.org"  # E2E probe target (HTTP GET)
```

- `ip_checker_url`: Used by E2E probes to verify connectivity through the cascade. Must start with `http`.

### 3.3 `sysctl` — Kernel Parameters

Applied on all nodes via `awg-routing.sh` during deploy (Phase 2).

```yaml
sysctl:
  net.ipv4.ip_forward: 1
  net.ipv4.conf.all.rp_filter: 2
  net.netfilter.nf_conntrack_max: 65536
  net.ipv6.conf.all.disable_ipv6: 1
```

### 3.4 `ports` — UDP Port Assignments

```yaml
ports:
  client_in: 51820    # Clients connect to awg-in
  link1: 51821        # awg-in <-> awg-mid
  link2: 51822        # awg-mid <-> awg-out
  mobile: 443         # Optional mobile clients
```

### 3.5 `scripts` — Helper Script Paths on Servers

Paths to scripts installed on each cascade node.

```yaml
scripts:
  manage_amneziawg: "/root/awg/manage_amneziawg.sh"
  routing: "/root/awg/awg-routing.sh"
  backup_prefixes: "/root/awg/ru.zone"
```

### 3.6 `timeouts` — Seconds

```yaml
timeouts:
  ssh_connect: 10
  ssh_command: 30
  deploy: 600
  check: 60
```

### 3.7 `check` — Peer Keepalive Validation

Defines the allowed persistent-keepalive range for the `check` command. Peers with `persistent_keepalive` outside this range are flagged as `MISMATCH`.

```yaml
check:
  keepalive_min: 1    # minimum allowed keepalive (default: 1)
  keepalive_max: 33   # maximum allowed keepalive (default: 33)
```

- `keepalive_min`: Minimum allowed persistent keepalive in seconds. Must be >= 1 and <= 120.
- `keepalive_max`: Maximum allowed persistent keepalive in seconds. Must be >= 0 and <= 120.
- `keepalive_min` must be <= `keepalive_max`, otherwise a `ValueError` is raised.
- Peers with `persistent_keepalive` of 0 or "off" are always flagged as `OFF` regardless of range.

**Receiving-end rule for keepalive `OFF`:** in a cascade in -> mid -> out the peer that starts the tunnel (the initiator) sends keepalives; the receiving end sets the peer's keepalive to `OFF` (0). When the receiving end reports `OFF` but the handshake is fresh, `check` accepts it as healthy and flags the link as passive (`keepalive_passive: true`).

**Known limitation:** a single server cannot distinguish the receiving end from a misconfiguration, so a passive link only resolves correctly for `in`, `mid` and `out` taken together (`--server all`); a paired check is not implemented yet.

### 3.8 `log_level` — Logging

```yaml
log_level: info   # debug | info | warning | error
```

## 4. Secrets Handling

### 4.1 What Goes in `cascade.yaml`

✅ Server hostnames/IPs, ports, usernames  
✅ Network subnets, MTU, DNS  
✅ `ip_checker_url`  
✅ Timeouts, script paths  

### 4.2 What Does NOT Go in `cascade.yaml`

❌ SSH passwords  
❌ Private keys  
❌ API tokens  
❌ Authentication secrets  

### 4.3 SSH Authentication

`awg-ctl` connects via SSH using key-based auth. The operator must:

1. Generate an Ed25519 key:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_awg -N ""
   ```
2. Install the public key on each cascade node:
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519_awg root@<server-host>
   ```
3. Populate `known_hosts` (host key verification):
   ```bash
   ssh-keyscan -H <server-host> >> ~/.ssh/known_hosts
   ```

`SSHTransport` uses `RejectPolicy` — unknown hosts are **never** automatically trusted.

### 4.4 File Permissions

```bash
chmod 600 cascade.yaml          # Config readable only by owner
chmod 600 ~/.ssh/id_ed25519_awg # Private key
chmod 700 ~/.ssh/               # SSH directory

### 4.5 Per-server key path and passphrase

Each cascade node may reference its own SSH key via `ssh_key_path`. If the key is protected by a passphrase, pass it via the `SSH_KEY_PASSPHRASE` environment variable (CI) or interactively when prompted:

```yaml
servers:
  in:
    host: "192.0.2.10"
    username: "root"
    ssh_key_path: "~/.ssh/id_ed25519_in"
  mid:
    host: "192.0.2.11"
    username: "root"
    ssh_key_path: "~/.ssh/id_ed25519_mid"
```

```bash
# CI / non-interactive:
SSH_KEY_PASSPHRASE="<passphrase>" awg-ctl diagnose --server mid --config cascade.yaml

# Interactive:
awg-ctl diagnose --server mid --config cascade.yaml
# Enter passphrase when prompted
```

SSH key passphrase takes priority: CLI `--key-passphrase` → `SSH_KEY_PASSPHRASE` env → interactive prompt.

## 5. Validation

`awg-ctl` validates `cascade.yaml` on load:

- All three servers (`in`, `mid`, `out`) must be present.
- Subnets must not overlap.
- `ip_checker_url` must start with `http`.
- `keepalive` must be between 0–120 seconds.

Validate without running a check:

```bash
awg-ctl config validate -c cascade.yaml
# Output: OK: cascade.yaml is valid
```

## 7. Check & Menu Command Integration

Both `awg-ctl check` and `awg-ctl menu` support loading real data from `cascade.yaml` via SSH, with fallback to demo data:

```bash
# Using SSH from cascade.yaml (production)
awg-ctl check --config cascade.yaml
awg-ctl menu --config cascade.yaml

# Using local dump file (CI/test, no SSH needed)
awg-ctl check --dump-file /path/to/dump.txt
```

**Data source priority:**
1. `--dump-file PATH` — parse local AWG dump file (highest, overrides config)
2. `--config PATH` — load cascade.yaml, SSH to `servers.in`, run `awg show all dump`
3. Fallback — hardcoded demo data (backward compatible)

**E2E probe (requires `--config`):**
When `--config` is provided, `check` reads `network.ip_checker_url` from the config and runs a `curl` GET to verify the external IP visible through the cascade. The result is included in the report as an `E2EProbe` (source: `awg-in`). If probe fails, it's recorded as `ok: false` without aborting the check.

**Example output with real data:**
```bash
$ awg-ctl check --config cascade.yaml
awg-ctl check - cascade-alpha
status: PASS (pass)
overall: OK
generated_at: 2024-01-15T10:30:00+00:00

Links:
  2/2 ok
  awg0 -> 10.10.1.1:51821: keepalive=OK, handshake=fresh, ok=yes
  awg1 -> 10.10.2.1:51822: keepalive=OK, handshake=fresh, ok=yes

E2E probes:
  1/1 ok
  awg-in (https://api.ipify.org): 203.0.113.42, ok=yes
```

## 6. Exit Codes and Legacy Mode

### 6.1 Exit-code schemes

`awg-ctl check` and `awg-ctl diagnose` support three exit-code schemes, selected by flags:

| Flag | Mode | `ok` / `green` | `warn` / `yellow` | `fail` / `red` |
|------|------|----------------|-------------------|----------------|
| (none) | **Nagios** (default) | 0 | 3 (`WARNING`) | 1 (`CRITICAL`) |
| `--exit-unix` | **Unix** | 0 | 1 | 1 |
| `--exit-unix --warn-as-ok` | **Unix + warn-as-ok** | 0 | 0 | 1 |

- `--strict`: reclassifies `warn` → `fail` **before** the scheme mapping. In Nagios mode this makes `warn` exit 1 instead of 3; in Unix mode it still exits 1.
- `--warn-as-ok` is mutually exclusive with `--strict` (usage error if both given).
- `--legacy-until YYYY-MM-DD`: legacy mode until the date (inclusive). Prints a one-line deprecation warning to stderr on each run. After the date the flag becomes a usage error (exit 64).

### 6.2 Known limitations

- **Unix scheme collapses `warn` and `fail` into a single exit code (1).** To distinguish them, use the Nagios scheme (default) or `--strict` in Nagios mode.
- **Usage errors** (invalid flags, `--legacy-until` past date, Phase 2 stubs) exit with `64` (`EX_USAGE` / `USAGE_ERROR`).
- `schema_version` is always present in JSON output, including error envelopes.

### 6.3 Examples

```bash
# Default (Nagios): warn=3, fail=1
awg-ctl diagnose --server in --config cascade.yaml
echo $?   # 0 / 1 / 3

# Unix scheme: warn=1, fail=1 (collapse)
awg-ctl diagnose --server in --config cascade.yaml --exit-unix
echo $?   # 0 / 1

# Unix with warn-as-ok: warn=0, fail=1
awg-ctl diagnose --server in --config cascade.yaml --exit-unix --warn-as-ok
echo $?   # 0 / 1

# Strict: treat warn as fail
awg-ctl diagnose --server in --config cascade.yaml --strict
echo $?   # 0 / 1 (warn→fail→1)

# Legacy mode until 2026-12-31
awg-ctl diagnose --server in --config cascade.yaml --legacy-until 2026-12-31
# stderr: [legacy] awg-ctl legacy mode until 2026-12-31
```

## 7. Related Documents

- `docs/ARCHITECTURE.md` — Architecture overview, command scope, configuration section summary
- `SPEC/spec.yaml` — Machine-readable specification
- `SPEC/SPEC.md` — Process and workflow specification
- `AGENTS.md` — Project AI contract

## 8. Security Notes

- `cascade.yaml` contains real infrastructure topology — treat as sensitive.
- Never commit `cascade.yaml` to version control (see `.gitignore`).
- RejectPolicy host key verification prevents man-in-the-middle during SSH connections.
- All remote commands via `SSHTransport` are redacted for secrets before transmission/logging.

### Check intro

Before running, `awg-ctl check` prints a short plan to **stderr** describing the data source, the handshake/keepalive thresholds, the E2E probe URL, and what is not checked. The intro is suppressed under `--json` and when stderr is not a terminal.
