# VoWERP3 Backend — Documentation Index

Repo-wide navigation for all documentation, agents, and tooling in `vowerp3be`.
The sibling frontend repo is at `../vowerp3ui` (see its `CLAUDE.md` and `docs/claude/`).

> The yarn-quality-specific index that previously lived here has moved to
> `docs/yarn-quality/INDEX.md`.

## Core guides

| File | Purpose |check
|------|---------|
| `CLAUDE.md` | Main developer guide: three-persona architecture, tenancy model, DB patterns, conventions, file-path registry |
| `README.md` | Setup and Docker commands |
| `.github/copilot-instructions.md` | AI coding agent guide (patterns, pitfalls, hotspots) |
| `.github/WORKSPACE-INSTRUCTIONS.md` | Active vs legacy repositories, workspace layout |

## Agents (`.claude/agents/`)

| Agent | Role |
|-------|------|
| `api-builder.md` | Scaffolds new endpoints (persona-aware) |
| `dbmanager.md` | Database schema, ORM models, queries, dev3 tenancy rules |
| `migration-writer.md` | SQL migrations + paired ORM updates |
| `test-writer.md` | Pytest suites with mocked DB/auth |
| `reviewer.md` | Convention review of code changes |
| `tenant-auditor.md` | Multi-tenant safety audit |
| `module-*.md` | Per-module guides (pointers — full bodies live in `../vowerp3ui/.claude/agents/`) |

## Skills (`.claude/skills/`)

Reusable step-by-step procedures for highly-repeated processes (menu addition,
FE+BE API wiring, master scaffolding, tenant schema checks, migrations).
Each skill states the questions it must ask before acting.

## Commands (`.claude/commands/`)

`graph-find`, `graph-trace`, `graph-reuse`, `graph-bridge` — query the
knowledge-graph artifacts in `graphify-out/` (secondary lookup; may be stale —
the module guides are the primary reference).

## Domain documentation (`docs/`)

| File | Domain |
|------|--------|
| `docs/procurement-inward-to-bill-pass-approval-flows.md` | Procurement approval chain (Inward → Inspection → SR → Bill Pass) |
| `docs/GST_PROCUREMENT.md` | GST calculations in procurement |
| `docs/accounting-module-design.md` | Accounting module design |
| `docs/bom_costing_db_instructions_1.md` | BOM costing database setup |
| `docs/hrms-payroll-design.md` | HRMS payroll creation (Payroll / Payscheme / components) |
| `docs/TENANT_PROVISIONING.md` | New tenant provisioning workflow |
| `docs/yarn-quality/` | Yarn-quality feature docs (see `docs/yarn-quality/INDEX.md`) |
| `docs/changelogs/` | Historical change logs |
| `docs/test-workflows/` | E2E test workflow documentation |
| `docs/superpowers/` | Historical design specs and plans |

## Cross-repo references (in `../vowerp3ui`)

| File | Purpose |
|------|---------|
| `../vowerp3ui/CLAUDE.md` | Frontend developer guide (three-dashboard architecture) |
| `../vowerp3ui/docs/claude/TEAM.md` | Agent team roster, skills table, team norms |
| `../vowerp3ui/docs/claude/roles-and-users.md` | Users/roles/permissions across all dashboards |
| `../vowerp3ui/docs/claude/modules/` | Module knowledge docs (page catalogs, backend maps, approval flows) |
| `../vowerp3ui/.claude/agents/module-*.md` | Full module guide agents (this repo holds pointers) |

## Knowledge-graph artifacts (`graphify-out/`)

`graph.json`, `index_be.json`, `index_fe.json`, `bridge.json`, `GRAPH_REPORT.md` —
machine-generated indices. **Status: the graphify CLI is currently non-operational;
artifacts may be stale.** Verify against source before trusting; regenerate with
`tools/bridge_extractor.py`, `tools/index_extractor_be.py`, `tools/index_extractor_fe.py`.
