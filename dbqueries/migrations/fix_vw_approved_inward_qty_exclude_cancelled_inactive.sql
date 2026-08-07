-- Rebuild vw_approved_inward_qty so reserved (issued) qty EXCLUDES issues that are
-- cancelled (issue_hdr.status_id = 6) or inactive (issue_hdr.active = 0).
--
-- Drafts and every other status (open/pending/approved/rejected/closed) and legacy
-- rows with NULL status STILL reserve stock — only cancelled and soft-deleted
-- issues release their qty back to balance_qty.
--
-- Before: the issued subquery summed ALL issue_li with no link to issue_hdr, so a
-- cancelled or soft-deleted issue kept holding stock and items vanished from the
-- create-issue available list (WHERE balance_qty > 0).
--
-- issue_li has no status/active column; status and active live on issue_hdr, hence
-- the added join. status_id IS NULL is kept (migrated history has NULL status).
--
-- Apply per tenant DB (run on sls now; replay on dev3 and other tenants).

CREATE OR REPLACE VIEW vw_approved_inward_qty AS
SELECT
    pid.inward_dtl_id   AS inward_dtl_id,
    pid.inward_id       AS inward_id,
    pid.item_id         AS item_id,
    pid.approved_qty    AS approved_qty,
    pid.uom_id          AS uom_id,
    pid.rate            AS rate,
    pid.accepted_rate   AS accepted_rate,
    pi.inward_date      AS inward_date,
    pi.branch_id        AS branch_id,
    pi.sr_status        AS sr_status,
    COALESCE(ili.total_issue_qty, 0)                      AS issue_qty,
    (pid.approved_qty - COALESCE(ili.total_issue_qty, 0)) AS balance_qty
FROM (
        proc_inward_dtl pid
        JOIN proc_inward pi ON pid.inward_id = pi.inward_id
    )
    LEFT JOIN (
        SELECT il.inward_dtl_id            AS inward_dtl_id,
               SUM(il.issue_qty)           AS total_issue_qty
        FROM issue_li il
        JOIN issue_hdr ih ON ih.issue_id = il.issue_id
        WHERE (ih.active = 1 OR ih.active IS NULL)
          AND (ih.status_id IS NULL OR ih.status_id <> 6)
        GROUP BY il.inward_dtl_id
    ) ili ON pid.inward_dtl_id = ili.inward_dtl_id
WHERE pi.sr_status = 3;

-- ROLLBACK (restores original definition: all issue_li reserve stock, no hdr join):
-- CREATE OR REPLACE VIEW vw_approved_inward_qty AS
-- SELECT pid.inward_dtl_id, pid.inward_id, pid.item_id, pid.approved_qty, pid.uom_id,
--        pid.rate, pid.accepted_rate, pi.inward_date, pi.branch_id, pi.sr_status,
--        COALESCE(ili.total_issue_qty,0) AS issue_qty,
--        (pid.approved_qty - COALESCE(ili.total_issue_qty,0)) AS balance_qty
-- FROM (proc_inward_dtl pid JOIN proc_inward pi ON pid.inward_id = pi.inward_id)
--      LEFT JOIN (SELECT inward_dtl_id, SUM(issue_qty) AS total_issue_qty
--                 FROM issue_li GROUP BY inward_dtl_id) ili
--        ON pid.inward_dtl_id = ili.inward_dtl_id
-- WHERE pi.sr_status = 3;
