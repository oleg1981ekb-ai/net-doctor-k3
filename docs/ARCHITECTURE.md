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
