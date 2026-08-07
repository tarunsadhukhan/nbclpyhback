# vowsls → sls Data Migration Guide

Reusable guidelines for migrating tenant data from the **legacy** `vowsls` database (older software, `tbl_*` schema) to the **current** `sls` database (new schema, no `tbl_` prefix).

This file evolves as new tables are migrated. Add a row to the **Migration Log** at the bottom for every table you migrate.

---

## 1. Pre-flight checklist

Before touching a new table, do these in order:

1. **Compare schemas** — run `SHOW CREATE TABLE` on both legacy and new tables. Diff column-by-column.
2. **Profile source data** — `COUNT(*)`, distinct values for enum/status columns, NULL distribution, range checks (min/max IDs, dates).
3. **Identify dropped columns** — confirm with the product owner whether each dropped column is (a) absorbed elsewhere, (b) replaced by a derivation, (c) audit data handled by triggers/log tables, or (d) truly discarded.
4. **Identify added columns** — for every NOT NULL added column, define a backfill rule.
5. **Verify lookup-table parity** — see §2 below. **Never assume IDs are aligned.**
6. **Confirm scope filters** — usually `is_active = 1` (skip soft-deleted). Confirm with user.
7. **Plan PK preservation** — downstream FK tables (e.g., `proc_indent_dtl.indent_id`) depend on legacy IDs. Preserve the source PK on insert unless explicitly told otherwise.
8. **Define rollback** — write the `DELETE` statement that reverses the migration before running it.

---

## 2. Lookup table parity

### `status_master` (vowsls) ↔ `status_mst` (sls)

| Aspect | vowsls.status_master | sls.status_mst |
|--------|----------------------|----------------|
| PK | `status_id bigint` | `status_id int` |
| AUTO_INCREMENT | 48 | 48 |
| Extra columns | `company_id`, `jute`, `store`, `auto_datetime_insert` | `status_grp` |
| Charset | latin1 | utf8mb4 |

**Verified ID alignment (1–47):** rows match by `status_id` and `status_name` for all entries actually used in transactions.

**Known semantic shifts (do not break migrations because unused in real data):**
| status_id | vowsls name | sls name |
|-----------|-------------|----------|
| 2 | INPROGRESS | DRAFT -1 |
| 20 | PENDING APPROVAL LEVEL 5 | PENDING APPROVAL LEVEL |

**Approval-level collapse rule (applies wherever a header has approval state):**
| Legacy status_id | New `status_id` | New `approval_level` |
|------------------|-----------------|----------------------|
| 17 (PENDING APPROVAL LEVEL 2) | 20 | 2 |
| 18 (PENDING APPROVAL LEVEL 3) | 20 | 3 |
| 19 (PENDING APPROVAL LEVEL 4) | 20 | 4 |
| 20 (PENDING APPROVAL LEVEL 5) | 20 | 5 |
| any other | passthrough | NULL |

Always verify which of 17–20 actually appear in the source table; for `tbl_proc_indent` only 17 was present.

### `branch_master` (vowsls) ↔ `branch_mst` (sls)

`branch_id` values **are aligned** between vowsls and sls (confirmed by user).

- Single-branch companies: passthrough.
- Multi-branch companies in legacy data (currently companies 1, 2): branch IDs already aligned to the correct factory branch in sls. Pass through.
- **Default: passthrough `branch` → `branch_id`.** Only remap if the user instructs otherwise for a specific table.

### `scm_indent_type_master` (vowsls) ↔ `expense_type_mst` (sls)

`indent_type_id` (legacy `category` column) values map directly to `expense_type_id` in the new schema. **Type-master IDs are aligned** (confirmed by user). Use direct passthrough.

### `indent_type_id` literal codes (sls)

The new `proc_indent.indent_type_id` is `varchar(25)`. Allowed literal values:

| Code | Maps from legacy `record_type` |
|------|--------------------------------|
| `Regular` | `INDENT`, `BOQ`, `BOM` (all non-Open variants in legacy data) |
| `Open` | `OPENINDENT` |
| `BOM` | (BOM did not exist in legacy data; reserved for new entries) |

Note: legacy `record_type='BOM'` (only 2 rows in vowsls) is mapped to `Regular` per confirmation, because legacy BOM was not the same concept as new-schema BOM.

### Other masters (verify before using)

`company_master`, `customer_master`, `tbl_proc_project`, `tbl_proc_projects_phase`, `dept_master`, `user_master` — **not yet verified for ID alignment**. When migrating any table that references these, dump both source and target masters first and confirm with user before assuming passthrough.

---

## 3. Standard column transformations

Apply these consistently across all tables.

### Active flag
| Legacy | New | Action |
|--------|-----|--------|
| `is_active int` | `active tinyint(1)` | Filter source rows on `is_active = 1`. New rows get `active = 1`. |

### Audit columns (legacy, all dropped in new)
- `created_by`, `created_date`, `last_modified_by`, `last_modified_date`, `last_update`
- `approved_by`, `approved_date`, `rejected_by`, `rejected_date`, `rejected_reasons`

**Rule:** drop. New schema relies on database triggers (CLAUDE.md §"Audit logging"). Do not migrate audit data unless explicitly asked.

### `updated_by` / `updated_date_time` (new schema, NOT NULL)
- `updated_date_time`: omit from INSERT; column has `DEFAULT CURRENT_TIMESTAMP`.
- `updated_by`: insert sentinel `0`. No FK constraint exists; safe placeholder. Do not attempt to map legacy user strings.

### Document numbers
Legacy holds formatted strings like `'LC/FACTORY/26-27/000003'` or `'M_64'`.
New schema typically holds plain int (`indent_no`, etc.).

**Extraction rule:**
```sql
CAST(COALESCE(REGEXP_SUBSTR(legacy_seq_no, '[0-9]+$'), '0') AS UNSIGNED)
```
Handles both slash-prefixed and underscore-prefixed legacy formats.

### Remarks concatenation
Legacy often has both `remarks` and `internal_remarks`. New schema usually keeps only `remarks`.

```sql
NULLIF(
    TRIM(CONCAT(
        COALESCE(remarks, ''),
        CASE
            WHEN internal_remarks IS NOT NULL AND internal_remarks <> ''
            THEN CONCAT(
                CASE WHEN COALESCE(remarks, '') <> '' THEN ' ' ELSE '' END,
                '[internal: ', internal_remarks, ']'
            )
            ELSE ''
        END
    )),
    ''
) AS remarks
```

### Empty strings → NULL
Legacy stores empty strings (`''`) in many varchar columns; new schema prefers NULL. Wrap with `NULLIF(col, '')`.

### Charset/collation
Legacy: latin1. New: utf8mb4_0900_ai_ci. INSERT…SELECT handles conversion automatically; no manual encoding step needed.

### Type narrowing (bigint → int)
Verify `MAX(legacy_id) < 2^31` before assuming the cast is safe. Indent IDs in vowsls peak at 9555, well within int range.

---

## 4. Columns to drop (encountered so far)

These columns are dropped in the new schema and have no replacement. Discard during migration.

| Column | Concept |
|--------|---------|
| `fy` | Financial year — derive from date if needed |
| `source` | Origin tracking — never used in real data |
| `total_value` | Header denormalization — recompute from detail rows |
| `phase` | Project phase concept removed |
| `store` | Separate store-branch concept; collapsed into `branch_id` |
| `customer` (header) | Customer reference removed from headers |
| `company` | New schema uses `branch_id` to deduce company; no `co_id` column on `proc_indent` |
| `record_type` | Replaced by `indent_type_id` |
| `indent_expiry_date` | Open-indent expiry concept removed; type alone signals open |
| `dept_id` (legacy header had no such column anyway) | Leave NULL on new side |

Always cross-check with the user when encountering a new dropped column — it may have been moved to a sibling table.

---

## 5. Scope rules (apply by default)

- **Active only**: `WHERE is_active = 1`.
- **No audit data**: skip `approved_*`, `rejected_*`, `created_by/date`, `last_modified_*` unless requested.
- **Preserve PKs**: insert with the legacy `indent_id`/`po_id`/etc. so downstream FK tables migrate cleanly.
- **One company at a time?** Default is "all companies in source DB", since new tenant DB receives all of them. If migrating into a multi-company tenant, filter on `company IN (...)`.

---

## 6. Migration script template

Every migration consists of two files in `dbqueries/migrations/`:

1. `migrate_<source_db>_<source_table>_to_<target_db>.sql`
   - SQL header comment block with mapping rules and rollback.
   - Single `INSERT INTO <target> (...) SELECT ... FROM <source> WHERE is_active = 1`.

2. `run_migrate_<source_db>_<source_table>_to_<target_db>.py`
   - Pymysql runner with dry-run-by-default, `--commit` flag.
   - Pre-flight: count source active rows, count target rows, abort on PK collisions.
   - Post-flight: print last 5 rows, status distribution, type distribution.
   - Use a wrapped transaction; rollback unless `--commit` passed.

**SQL parser caveat:** the runner strips lines starting with `--` before splitting on `;`. Do not put `--` comments inside SQL string literals; do not use `/* */` block comments unless the runner is updated to strip them.

**Reference implementation:**
- [migrate_vowsls_proc_indent_to_sls.sql](migrate_vowsls_proc_indent_to_sls.sql)
- [run_migrate_vowsls_proc_indent_to_sls.py](run_migrate_vowsls_proc_indent_to_sls.py)

---

## 7. Verification queries (run after every commit)

```sql
-- Row count parity
SELECT
    (SELECT COUNT(*) FROM vowsls.<source> WHERE is_active = 1) AS source_active,
    (SELECT COUNT(*) FROM sls.<target>)                        AS target_after;

-- PK preservation spot check
SELECT s.indent_id, t.indent_id
  FROM vowsls.<source> s
  LEFT JOIN sls.<target> t USING (indent_id)
 WHERE s.is_active = 1 AND t.indent_id IS NULL
 LIMIT 20;     -- should be empty

-- Status distribution sanity
SELECT status_id, approval_level, COUNT(*) FROM sls.<target> GROUP BY 1, 2;

-- FK integrity (branch_id, project_id, expense_type_id, status_id)
SELECT 'orphan_branch'   AS chk, COUNT(*) FROM sls.<target> t LEFT JOIN sls.branch_mst       b USING(branch_id)        WHERE b.branch_id IS NULL AND t.branch_id IS NOT NULL
UNION ALL SELECT 'orphan_status', COUNT(*) FROM sls.<target> t LEFT JOIN sls.status_mst      s USING(status_id)        WHERE s.status_id IS NULL AND t.status_id IS NOT NULL
UNION ALL SELECT 'orphan_expense', COUNT(*) FROM sls.<target> t LEFT JOIN sls.expense_type_mst e USING(expense_type_id) WHERE e.expense_type_id IS NULL AND t.expense_type_id IS NOT NULL;
```

All counts in the `orphan_*` checks should be zero. Investigate any non-zero result before proceeding to dependent tables.

---

## 8. Tables to migrate (planned order)

Migrate in dependency order. Headers first, then detail/line tables, then transactional follow-ons (PO, inward, issue, invoice).

| Order | Source (`vowsls`) | Target (`sls`) | Status |
|-------|-------------------|----------------|--------|
| 1 | `tbl_proc_indent` | `proc_indent` | ✅ Done — 4234 rows (2026-05-04) |
| 2 | `tbl_proc_indent_detail` | `proc_indent_dtl` | Pending |
| 3 | `tbl_proc_po` | `proc_po` | Pending |
| 4 | `tbl_proc_po_detail` | `proc_po_dtl` | Pending |
| 5 | `tbl_proc_inward` | `proc_inward` | Pending |
| 6 | `tbl_proc_inward_detail` | `proc_inward_dtl` | Pending |
| ... | ... | ... | ... |

Update this table after each migration is committed.

---

## 9. Migration Log

| Date | Source → Target | Rows inserted | Notes |
|------|-----------------|---------------|-------|
| 2026-05-04 | `vowsls.tbl_proc_indent` → `sls.proc_indent` | 4234 | 4 inactive skipped. 17→20+L2 (58 rows). 7 rows with `M_xxx` / `G_xxx` numbering handled via `REGEXP_SUBSTR`. BOQ/BOM legacy folded into `Regular`. |
| 2026-07-27 | HRMS "small companies" (all except comp_id 67,65,2,106,139,1) → `sls` | 336 employees + 8 ed child tables, 3201 daily_attendance, 59+101 leave txn/details, 29 leave types; masters: 30 dept_mst, 33 sub_dept_mst (legacy dept ids preserved), 43 designation_mst, 22 category_mst (ids preserved) | `run_migrate_vowsls_hrms_smallco_to_sls.py`. eb_ids preserved except 6 collisions remapped to 59082–59087; full map in `sls._map_hrms_eb_smallco`. Inactive employees migrated (active=0 kept). Skipped: payroll (`tbl_pay_*`), attendance_summary, holiday tables, leave_ledger/policies (no compatible target), 5 junk leave rows with company_id=1000001 (co-1 employees). Rollback block in script header; run logged in `sls.migration_log` step `vowsls_hrms_smallco`. |
| 2026-07-28 | HRMS comp_id 1 + 2 (EJM), ALL remaining emp_code-missing employees → `sls` | 8,238 employees (8,229 co-2 identity-mapped + 9 co-1 remapped to fresh eb_ids 59088–59096); 8,255 official rows, ~8,150 rows each addr/bank/contact/esi/pf/resign (per-table eb guards skipped ~30–84 partially-migrated actives), 9 personal (co-1 only), 17,847 daily_attendance (INSERT IGNORE vs 89 pre-existing), 20+279 leave txn/details, 1 experience; masters: only designation 909 & 1190 created | `run_migrate_vowsls_hrms_missing_rest_to_sls.py`. co-2 personal rows pre-existed 1:1 (earlier EJM migration copied personal for everyone, official only for a subset) → identity map, personal untouched; collision rule = remap ONLY on first-name mismatch. 2 co-2 officials had branch_id=0 → sls personal branch fallback. 2 junk test employees (`ejclx`/`ejclxx`, all-zero FK refs) excluded by design; `mohit@abc.com` is a historical junk code of T20010 (employee present). After this run the vowsls→sls emp_code diff is EMPTY apart from those 3 junk codes. Log step `vowsls_hrms_missing_rest`; rollback block in script header (NOTE: identity personal rows + pre-existing child rows for skipped ebs are NOT migration-owned). |
| 2026-07-28 | HRMS comp_id 67 (AVPL) + 106 (LLCPL) + 139 (VES), emp_code-missing employees only → `sls` | 101 employees (12+30+59) + personal/official/6 ed child tables, 9 experience, 740 daily_attendance, 32+1525 leave txn/details, 15 leave types; masters: 9 dept_mst (15125–15133), 11 sub_dept_mst (96,97,117,170,179,180,181,182,387,389,391), 24 designation_mst, 4 category_mst (29,42,59,68) — legacy ids preserved | `run_migrate_vowsls_hrms_co67_106_139_to_sls.py`. Scope = employees whose trimmed emp_code is absent from sls (co 106 has 4,366 of 4,399 already present via the co1→106 remap; 11 employees without any emp_code skipped). eb_ids preserved (0 collisions); map appended to `sls._map_hrms_eb_smallco`. `reporting_eb_id=0` nulled; 38 junk legacy reporting ids passed through. dept 182 referenced only by attendance → master collection unions attendance worked ids. One junk `leave_type_id=0` nulled. Log step `vowsls_hrms_co67_106_139`. Remaining gaps: co 1 (9 codes, sls eb slots occupied → need fresh eb_ids), co 2 EJM (8,232 personal-only, no official rows — scope decision pending). |
| 2026-07-28 | HRMS comp_id 65 (ACPL, Anurashi Commotrade) → `sls` | 7 employees (official + 6 ed child tables; personal rows pre-existed with same eb_ids and were left untouched), 329 daily_attendance, 8+8 leave txn/details, 2 leave types; masters: 2 dept_mst (15080, 15081), sub_dept 120/164, designation 1210/1211, category 44 (legacy ids preserved) | `run_migrate_vowsls_hrms_co65_to_sls.py`. Identity eb map (no collisions) appended to `sls._map_hrms_eb_smallco` with company_id=65 — those personal rows are NOT migration-owned, never delete them on rollback. Run logged in `sls.migration_log` step `vowsls_hrms_co65`. Still missing in sls by emp_code afterwards: co 67 AVPL (12 emp), co 106 LLCPL (30), co 139 VES (59) — all eb absent from sls, user-excluded on 2026-07-27; co 1 (9 codes, sls eb slots occupied → would need new eb_ids); co 2 EJM (8,240 employees with personal rows but no official rows in sls — earlier EJM migration scope); co 120 ` BFSPL032` is a false positive (leading space; in sls trimmed). |

---

## 10. Open questions / deferrals

- **`dept_id` source**: legacy `tbl_proc_indent` has no dept column. Currently inserting NULL. If a future table has a usable dept reference, revisit.
- **Multi-company tenants**: confirm before migrating any table that the target tenant DB is intended to receive all source companies' data, not a subset.
- **Lookup masters not yet verified**: `company_master`, `customer_master`, `tbl_proc_project`, `tbl_proc_projects_phase`, `dept_master`, `user_master`. Verify on first encounter.
