---
name: new-master
description: Scaffold a brand-new VoWERP3 master end-to-end — DDL migration, SQLAlchemy ORM model, backend CRUD endpoints, frontend master page, and sidebar menu entry. Use when the user asks for a new master (table) that doesn't exist yet. Asks entity fields, target tenant DB, and menu placement first.
---

# Skill: new-master

Last verified: 2026-06-12

## When to use

The user wants a new master/reference entity (e.g. "Vehicle Master", "Godown Master") that has no
table yet. This skill chains the full stack in order: table → model → endpoints → page → menu.
If the table already exists, skip to step 3 (or use `wire-api` for endpoints only).

## Questions to ask the user FIRST (never assume)

1. **Entity name + fields** — names, types, which are required, FK references (e.g. `co_id`,
   `branch_id`, other masters).
2. **Target tenant DB(s)** — suggest `dev3` (QA/dev tenant) as the default; confirm any others.
3. **Company/branch scope** — is the master scoped by `co_id` only, or `co_id` + `branch_id`?
4. **Menu placement + roles** — where in the portal sidebar, and which roles get access
   (collected for the `add-menu` step).
5. **Form complexity** — simple dialog (5–10 fields) or nested tables/dependent dropdowns?

## Procedure

1. **DDL migration** — `dbqueries/migrations/create_{entity}_mst.sql`, following
   `.claude/agents/migration-writer.md`: `{entity}_mst` naming, `{entity}_id` PK, `co_id` column
   (tenant isolation), `active INT DEFAULT 1`, `DOUBLE` for money/qty, indexed FKs, rollback SQL
   as comment. **No audit columns** (handled by triggers).
2. **ORM model** — add to the matching domain file in `src/models/` using SQLAlchemy 2.0
   `Mapped`/`mapped_column` style (see `CLAUDE.md` → ORM Model Style).
3. **Execute the migration** with the `run-migration` skill (re-confirms the target DB with the user).
4. **Backend CRUD endpoints** — follow `.claude/agents/api-builder.md` (portal persona,
   `Depends(get_tenant_db)`): `get_{entity}_table` (paginated + search), `create_setup` (dropdown
   options), `create_{entity}`, `update_{entity}`, `get_{entity}_by_id`. Register a
   `/api/{entity}Master` prefix in `src/main.py`. Tests per `.claude/agents/test-writer.md`.
5. **Frontend page** — delegate to the `master-page` agent in `../vowerp3ui/.claude/agents/`
   (list page + MuiForm dialog under `src/app/dashboardportal/masters/{entity}Master/`). Wire
   constants + service via the `wire-api` skill steps 5–7. Honor the company/branch sidebar scope.
6. **Menu entry** — run the `add-menu` skill with the placement/roles answers from question 4.
7. **Offer the module-guide update** — the new pages/endpoints belong in `module-masters`'s
   knowledge docs; ask the user before updating (team maintenance norm).

## Verification

- Migration applied and `SELECT` works on the target DB; rollback comment present.
- `pytest src/test/test_masters_{entity}.py -v` passes.
- Page lists, creates, edits, and views records end-to-end against dev3.
- Menu appears for mapped roles only.
