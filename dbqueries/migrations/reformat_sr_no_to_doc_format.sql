-- Migration: Reformat proc_inward.sr_no from 'SR-YYYY-NNNNN' to
-- '{co_prefix}/{branch_prefix}/SR/{FY}/{seq}' to match the shared Inward/SR
-- formatter (format_inward_no with doc_type="SR").
--
-- Sequence number is preserved. Financial year (YY-YY) is derived from
-- sr_date (fallback inward_date). Only rows matching the old pattern are
-- touched; rows in the new format or NULL are left alone.
--
-- Rollback (best-effort, sequence recoverable but old year segment lost):
--   Not straightforward — recommend backing up proc_inward.sr_no before run.

UPDATE proc_inward pi
JOIN branch_mst bm ON bm.branch_id = pi.branch_id
JOIN co_mst cm ON cm.co_id = bm.co_id
SET pi.sr_no = CONCAT(
    COALESCE(cm.co_prefix, ''), '/',
    COALESCE(bm.branch_prefix, ''), '/SR/',
    CASE
        WHEN MONTH(COALESCE(pi.sr_date, pi.inward_date)) >= 4
            THEN CONCAT(
                LPAD(YEAR(COALESCE(pi.sr_date, pi.inward_date)) % 100, 2, '0'),
                '-',
                LPAD((YEAR(COALESCE(pi.sr_date, pi.inward_date)) + 1) % 100, 2, '0')
            )
        ELSE CONCAT(
            LPAD((YEAR(COALESCE(pi.sr_date, pi.inward_date)) - 1) % 100, 2, '0'),
            '-',
            LPAD(YEAR(COALESCE(pi.sr_date, pi.inward_date)) % 100, 2, '0')
        )
    END,
    '/',
    CAST(SUBSTRING_INDEX(pi.sr_no, '-', -1) AS UNSIGNED)
)
WHERE pi.sr_no REGEXP '^SR-[0-9]{4}-[0-9]+$';
