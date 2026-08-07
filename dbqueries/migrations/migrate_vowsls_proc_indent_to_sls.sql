-- ============================================================================
-- Migrate vowsls.tbl_proc_indent (legacy) -> sls.proc_indent (new schema)
-- Header rows only. Detail rows (proc_indent_dtl) migrated separately.
-- ----------------------------------------------------------------------------
-- Mapping rules (confirmed with user):
--   indent_id         -> indent_id (preserved; downstream FKs depend on it)
--   indent_date       -> indent_date
--   indent_squence_no -> indent_no   (numeric tail after last '/')
--   is_active=1 only  -> active=1    (inactive rows skipped)
--   record_type       -> indent_type_id ('OPENINDENT'->'Open', else 'Regular')
--   remarks + internal_remarks -> remarks (concatenated)
--   branch            -> branch_id   (IDs already aligned across DBs)
--   category          -> expense_type_id (IDs aligned)
--   project           -> project_id  (IDs aligned)
--   indent_status=17  -> status_id=20, approval_level=2
--   indent_status<>17 -> status_id=indent_status, approval_level=NULL
--   title             -> indent_title
--   updated_by        -> 0 (sentinel; column is NOT NULL, no FK)
--   updated_date_time -> omitted (defaults to CURRENT_TIMESTAMP)
-- Dropped per user: approved_by/date, rejected_*, fy, source, total_value,
--   phase, store, customer, company, indent_expiry_date, last_update,
--   created_by, created_date, last_modified_by, last_modified_date, dept_id.
-- ----------------------------------------------------------------------------
-- Rollback:
--   DELETE FROM sls.proc_indent
--    WHERE indent_id IN (
--        SELECT indent_id FROM vowsls.tbl_proc_indent WHERE is_active = 1
--    );
-- ============================================================================

INSERT INTO sls.proc_indent (
    indent_id,
    indent_date,
    indent_no,
    active,
    indent_type_id,
    remarks,
    branch_id,
    expense_type_id,
    project_id,
    status_id,
    indent_title,
    approval_level,
    updated_by
)
SELECT
    o.indent_id,
    o.indent_date,
    CAST(COALESCE(REGEXP_SUBSTR(o.indent_squence_no, '[0-9]+$'), '0') AS UNSIGNED) AS indent_no,
    1 AS active,
    CASE WHEN o.record_type = 'OPENINDENT' THEN 'Open' ELSE 'Regular' END AS indent_type_id,
    NULLIF(
        TRIM(CONCAT(
            COALESCE(o.remarks, ''),
            CASE
                WHEN o.internal_remarks IS NOT NULL AND o.internal_remarks <> ''
                THEN CONCAT(
                    CASE WHEN COALESCE(o.remarks, '') <> '' THEN ' ' ELSE '' END,
                    '[internal: ', o.internal_remarks, ']'
                )
                ELSE ''
            END
        )),
        ''
    ) AS remarks,
    o.branch     AS branch_id,
    o.category   AS expense_type_id,
    o.project    AS project_id,
    CASE WHEN o.indent_status = 17 THEN 20 ELSE o.indent_status END AS status_id,
    NULLIF(o.title, '') AS indent_title,
    CASE WHEN o.indent_status = 17 THEN 2 ELSE NULL END AS approval_level,
    0 AS updated_by
FROM vowsls.tbl_proc_indent o
WHERE o.is_active = 1;
