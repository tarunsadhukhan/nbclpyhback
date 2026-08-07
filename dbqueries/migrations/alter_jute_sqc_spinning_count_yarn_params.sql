-- Migration: R-08-16 Yarn Parameter — capture raw count-test inputs on each
-- jute_sqc_spinning_count observation and store the computed counts.
--
-- The operator enters DP, TP, WT/450 YDS (gms) and MR% per reading. The app computes:
--   observed_count  = round( (wt_450_gms / 450) * (14400 / 454), 2 )   [already a column]
--   corrected_count = observed_count / (100 + mr_pct) * (100 + std_mr_pct)
-- where std_mr_pct comes from yarn_quality_master (per quality).
--
-- DP and TP are stored-only (not used in any formula).

ALTER TABLE jute_sqc_spinning_count
    ADD COLUMN dp DECIMAL(10,3) NULL AFTER yarn_quality_id,
    ADD COLUMN tp DECIMAL(10,3) NULL AFTER dp,
    ADD COLUMN wt_450_gms DECIMAL(10,3) NULL AFTER tp,
    ADD COLUMN mr_pct DECIMAL(5,2) NULL AFTER wt_450_gms,
    ADD COLUMN corrected_count DECIMAL(10,3) NULL AFTER observed_count;

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- ALTER TABLE jute_sqc_spinning_count
--     DROP COLUMN corrected_count,
--     DROP COLUMN mr_pct,
--     DROP COLUMN wt_450_gms,
--     DROP COLUMN tp,
--     DROP COLUMN dp;
