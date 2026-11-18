# ADR-001: Initial SPEC Structure for {{ project_name }}

## Context
New repository using AI Infrastructure Governance Standard v1.2 with spec-driven development.

## Decision
Establish `SPEC/` directory as the source of truth for project specification and generate downstream artifacts from it.

## Consequences
- `SPEC/spec.yaml` is the canonical source of project metadata
- All new projects copied via Copier must first update `SPEC/spec.yaml`
- Architecture diagrams and ADRs evolve from this base
- Governance gate (`make ai-smoke`) validates SPEC before code generation

## Status: Accepted