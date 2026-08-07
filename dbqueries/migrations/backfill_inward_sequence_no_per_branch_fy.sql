-- ============================================================================
-- Backfill: fix polluted proc_inward.inward_sequence_no in the CURRENT FY only
-- ============================================================================
--
-- WHY:
--   The old create_inward code stamped inward_sequence_no = inward_id (the global
--   auto-increment PK) on every portal-created inward. So some rows hold large
--   global ids (e.g. 10285) instead of a per-branch per-FY counter. After the
--   code fix (MAX(inward_sequence_no)+1 scoped to branch+FY), MAX reads those
--   polluted values and returns e.g. 10286 instead of 6.
--
-- SCOPE (deliberately narrow):
--   * Only the CURRENT financial year (2026-04-01 .. 2027-03-31). New-inward
--     numbering only ever queries the current FY, so prior/closed years are
--     irrelevant to the bug and are LEFT UNTOUCHED (they carry gaps and legacy
--     values; a blanket dense renumber would shift audited historical numbers).
--   * Only rows whose inward_sequence_no = inward_id -- the exact leak signature.
--     In this FY the global ids (>=10191) are far above any real sequence (<=81),
--     so the match is unambiguous.
--
-- EFFECT: each polluted row is renumbered to clean_max + rank, where clean_max is
--   the MAX sequence among NON-polluted rows of the same branch in this FY, and
--   rank orders the polluted rows by inward_date, inward_id. Clean rows untouched.
--   e.g. branch 29 FY26-27: clean rows 1..5, polluted 10285 -> 6.
--
-- REQUIRES: MySQL 8.0+ (ROW_NUMBER window function).
-- TARGET DB: sls (per user approval). Run via pymysql; back up first.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- STEP 0 (REQUIRED): backup before touching anything.
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS proc_inward_seqno_backup;
CREATE TABLE proc_inward_seqno_backup AS
SELECT inward_id, branch_id, inward_date, inward_sequence_no
FROM proc_inward;

-- ---------------------------------------------------------------------------
-- STEP 1: renumber polluted current-FY rows to clean_max + rank.
-- ---------------------------------------------------------------------------
UPDATE proc_inward pi
JOIN (
    SELECT
        p.inward_id,
        cm.clean_max + ROW_NUMBER() OVER (
            PARTITION BY p.branch_id ORDER BY p.inward_date, p.inward_id
        ) AS new_seq
    FROM proc_inward p
    JOIN (
        SELECT
            branch_id,
            COALESCE(MAX(CASE WHEN inward_sequence_no <> inward_id
                              THEN inward_sequence_no END), 0) AS clean_max
        FROM proc_inward
        WHERE inward_date >= '2026-04-01' AND inward_date <= '2027-03-31'
        GROUP BY branch_id
    ) cm ON cm.branch_id = p.branch_id
    WHERE p.inward_date >= '2026-04-01' AND p.inward_date <= '2027-03-31'
      AND p.inward_sequence_no = p.inward_id        -- pollution signature
) ren ON ren.inward_id = pi.inward_id
SET pi.inward_sequence_no = ren.new_seq;

-- ---------------------------------------------------------------------------
-- VERIFY (expect no row left with seq = inward_id in this FY; dense per branch):
--   SELECT branch_id, MIN(inward_sequence_no), MAX(inward_sequence_no), COUNT(*)
--   FROM proc_inward
--   WHERE inward_date >= '2026-04-01' AND inward_date <= '2027-03-31'
--   GROUP BY branch_id;
--   SELECT COUNT(*) FROM proc_inward
--   WHERE inward_date >= '2026-04-01' AND inward_date <= '2027-03-31'
--     AND inward_sequence_no = inward_id;   -- expect 0
-- ---------------------------------------------------------------------------

-- ============================================================================
-- ROLLBACK (restore original values from the STEP 0 backup):
--
--   UPDATE proc_inward pi
--   JOIN proc_inward_seqno_backup b ON b.inward_id = pi.inward_id
--   SET pi.inward_sequence_no = b.inward_sequence_no;
--
--   DROP TABLE proc_inward_seqno_backup;
-- ============================================================================
