---
name: tenant-schema-check
description: Compare a VoWERP3 tenant database schema against dev3 (the QA/dev tenant) via information_schema — report tables and columns that exist in one but not the other, then ask the user whether to generate a migration syncing the drift into dev3. Use before developing against any non-dev3 tenant or when schema drift is suspected.
---

# Skill: tenant-schema-check

Last verified: 2026-06-12

## When to use

- Before doing development that references a production tenant (e.g. `sls`).
- When a query works on one tenant but fails on another (suspected drift).
- Periodically, to keep dev3 representative of production schemas.

**Why:** `dev3` is the QA/dev tenant and the default target for new work, but production tenants may
carry tables/columns dev3 lacks. Per the team norm: detect the drift, report it, and **ask the user
whether to incorporate it into dev3 — never sync silently.**

## Questions to ask the user FIRST (never assume)

1. **Which tenant DB** to compare against `dev3`?
2. Compare **tables only**, or **tables + columns** (column-level is slower but catches ALTERs)?
3. Include the partitioned side-DBs (`{name}_c`, `{name}_c_1`...) or just the main tenant DB?

## Procedure

1. Connect with pymysql using credentials from `env/database.env` (host/user/password/port).
2. Pull both schemas from `information_schema` (read-only — no writes in this step):

```python
import pymysql
conn = pymysql.connect(host=HOST, port=3306, user=USER, password=PASS,
                       database='information_schema')
cur = conn.cursor()
cur.execute("""
    SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT
    FROM COLUMNS WHERE TABLE_SCHEMA = %s
    ORDER BY TABLE_NAME, ORDINAL_POSITION
""", (db_name,))
```

3. Diff in both directions and report three sections:
   - **Tables in {tenant} missing from dev3** (and vice versa)
   - **Columns in {tenant} missing from dev3** (per shared table; include type/nullability)
   - **Type mismatches** on shared columns
4. **Ask the user** which (if any) drift items to incorporate into dev3.
5. For approved items only: generate a migration in `dbqueries/migrations/`
   (`sync_{tenant}_drift_to_dev3.sql`, rollback as comment) following
   `.claude/agents/migration-writer.md`, then execute via the `run-migration` skill
   (which re-confirms the target = dev3).
6. Update the matching ORM models in `src/models/` for anything added to dev3.

## Verification

- Re-run the diff after syncing — approved items no longer appear.
- `SHOW COLUMNS` on dev3 confirms the new columns/tables.
- ORM models import cleanly: `python -c "import src.models"` (via the project venv).
