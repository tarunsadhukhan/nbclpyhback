---
name: migrate-tenant-tables
description: Migrate missing tables/views (structure, optionally data) from a source VoWERP3 tenant DB to a target tenant DB via SHOW CREATE — module-agnostic (table set chosen by an explicit list, name prefix/regex, or "all missing"), always confirms the target (explicit yes required for production tenants or vowconsole3). Use for requests like "migrate X tables to Y db from Z db", "copy tables between tenants", or "sync missing tables to <tenant>".
---

# Skill: migrate-tenant-tables

Last verified: 2026-07-01

## When to use

Some tables/views exist in one tenant DB (usually `dev3`, where new work is built) and need to be
copied into another tenant DB that lacks them — backfilling a production tenant, or seeding a new one.
Structure-only by default; source rows are keyed to the source tenant's `co_id`/`branch_id`/`machine_id`
and are usually invalid elsewhere.

## Questions to ask the user FIRST (never assume)

1. **Source DB** [suggest `dev3`] and **target DB** [confirm — require an explicit yes for any
   production tenant or `vowconsole3`].
2. **Which tables** — explicit list / name prefix or regex / **all tables in source missing from target**.
3. **STRUCTURE ONLY or structure + data?** Default STRUCTURE ONLY — warn that source rows carry
   source-tenant ids (`co_id`/`branch_id`/`machine_id`) that are almost always wrong in another tenant.
4. Include **VIEWS** too?
5. Include the **side-DBs** (`{name}_c`, `{name}_c_1`..) or just the main tenant DB?

## Procedure

1. Read credentials from `env/database.env` (`DATABASE_HOST/USER/PASSWORD/PORT`). Connect via pymysql
   through the project venv. Never print the password.
2. **Diff** via `information_schema.TABLES` (source-minus-target), apply the user's filter, split
   `BASE TABLE` vs `VIEW`. Show source row counts so the user sees which are test data:
   ```python
   cur.execute("SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS FROM information_schema.TABLES "
               "WHERE TABLE_SCHEMA=%s", (source_db,))
   ```
3. Generate `dbqueries/migrations/migrate_<scope>_<source>_to_<target>.sql`:
   - Header comment: intent + **ROLLBACK** (DROP VIEW list first, then DROP TABLE list).
   - `SET FOREIGN_KEY_CHECKS=0;` then, per table, `SHOW CREATE TABLE` — rewrite
     `` CREATE TABLE `x` `` → `` CREATE TABLE IF NOT EXISTS `x` ``. Then `SET FOREIGN_KEY_CHECKS=1;`.
   - Then views: `SHOW CREATE VIEW`, strip the `ALGORITHM=.. DEFINER=..@.. SQL SECURITY .. VIEW`
     prefix → `CREATE OR REPLACE VIEW`, and strip any `` `<source>`. `` db-qualifier.
     A view may reference another new view, so **order matters**: simplest robust approach is to emit
     all views, apply, collect failures, and retry the failing set until it stabilises (a view whose
     dependencies now exist succeeds on a later pass).
   - **structure + data** chosen: after each CREATE add `INSERT`s, but WARN loudly in the header
     comment about cross-tenant id mismatch (see Q3).
4. **Apply via the `run-migration` skill** (its pymysql statement-by-statement `split(';')` pattern)
   against the confirmed target. Re-confirm before executing — this changes prod state.
   - `split(';')` breaks on semicolons inside comments — keep the ROLLBACK block fully commented
     (`--` per line) and avoid stray `;` in comments.
5. Update paired ORM models in `src/models/` **only** if the target was dev3 and the tables are new to
   the repo — for a prod backfill of tables already modelled, skip this.

## Verification

- Re-run the `information_schema` diff → the migrated objects no longer appear.
- `SHOW TABLES LIKE '<name>'` / `SHOW CREATE VIEW <name>` on the target confirm they exist.
- Report the applied (source, target, script path, object count) back to the user for their records.
