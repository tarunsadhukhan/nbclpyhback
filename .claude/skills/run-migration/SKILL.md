---
name: run-migration
description: Execute a dbqueries/migrations/*.sql script against a VoWERP3 database via pymysql (no mysql CLI on dev machines). Always asks which target tenant DB before executing — suggests dev3, never assumes. Use whenever a migration script needs to be applied.
---

# Skill: run-migration

Last verified: 2026-06-12

## When to use

A migration script in `dbqueries/migrations/` needs to be applied — after `migration-writer`
generates one, as part of `new-master`/`add-menu`/`tenant-schema-check`, or on user request.

## Questions to ask the user FIRST (never assume)

1. **Which target database?** Suggest `dev3` (the QA/dev tenant — the default for all new work) but
   **always confirm**; for `vowconsole3` (system DB) or production tenants, require an explicit yes.
2. **Which script** in `dbqueries/migrations/` (if not already specified)?
3. Show the SQL (or summarize DDL statements) and get a final **confirm before executing** — this
   changes database state.

## Procedure

1. Read credentials from `env/database.env` (`DATABASE_HOST`, `DATABASE_USER`, `DATABASE_PASSWORD`,
   `DATABASE_PORT`). Never hardcode or print the password.
2. Safety checks before executing:
   - Script contains `DROP TABLE`/`TRUNCATE`? Re-confirm explicitly with the user.
   - For ALTERs: `SHOW TRIGGERS LIKE '{table}'` first (audit triggers exist — see
     `.claude/agents/dbmanager.md` §17).
3. Execute with the project pattern (statement-by-statement, skipping comments):

```bash
python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cursor = conn.cursor()
with open('dbqueries/migrations/<migration_file>.sql', 'r') as f:
    for stmt in f.read().split(';'):
        stmt = stmt.strip()
        if stmt and not stmt.startswith('--'):
            cursor.execute(stmt)
conn.commit()
conn.close()
print('Migration applied successfully')
"
```

4. If anything fails mid-script: report exactly which statement failed, and offer the rollback SQL
   from the script's comment header.
5. Remind: if the same change is needed on other tenants later, run `tenant-schema-check` first and
   confirm each target with the user.

## Verification

- `SHOW COLUMNS FROM {table}` / `SHOW TABLES LIKE '{name}'` on the target DB reflects the change.
- The paired ORM model in `src/models/` matches the new schema.
- Note the applied (db, script) pair back to the user for their records.
