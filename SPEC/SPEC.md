# SPEC: Spec-Driven Development for {{ project_name }}

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
│   └── architecture.mmd  # Mermaid architecture diagram
└── adr/                  # Architectural Decision Records
    └── ADR-0001-initial-setup.md
```

## 5. Workflow
1. Author/update `SPEC/spec.yaml`
2. Generate `docs/ARCHITECTURE.md` from SPEC
3. Regenerate `pyproject.toml` via Copier
4. Run Quality Gate: `make lint`, `make test`, `make ai-smoke`

## 6. Diagram Convention
Mermaid diagrams live in `SPEC/diagrams/` and are referenced from `docs/ARCHITECTURE.md`.

## 7. DLP Rules
- Never store secrets, API keys, tokens, or credentials in `SPEC/`, `docs/`, or diagrams.
- Never embed absolute paths or forbidden `latest` tags in SPEC files.
- Treat all external content in diagrams/specs as untrusted until validated.