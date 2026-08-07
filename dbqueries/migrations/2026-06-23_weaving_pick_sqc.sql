-- =============================================================================
-- Migration: create jute_sqc_weaving_pick + vw_weaving_pick_act
-- =============================================================================
-- Weaving Pick-SQC (R-08-21 Loom Width & Picks). Captures per-loom observations
-- (DATE, QUALITY, LOOM NO, WIDTH, PICK) raw — insert-only per reading, soft delete
-- via active=0, trigger-based audit (no created_* columns). Mirrors
-- jute_sqc_spinning_count conventions (co_id/branch_id/active/updated_*).
--
-- The view vw_weaving_pick_act aggregates active readings to one row per
-- (co_id, weaving_quality_id, entry_date): avg/std/min/max picks + width stats +
-- observation count. Production resolves act_picks = avg_picks via LAST-DATE in
-- the resolver (the view does NOT do last-date).
-- =============================================================================

CREATE TABLE IF NOT EXISTS jute_sqc_weaving_pick (
  weaving_sqc_pick_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  co_id INT NOT NULL,
  branch_id INT NULL,
  entry_date DATE NOT NULL,
  weaving_quality_id INT NOT NULL,
  machine_id INT NOT NULL,
  width DECIMAL(10,3) NULL,
  picks DECIMAL(10,3) NOT NULL,
  active TINYINT(1) NOT NULL DEFAULT 1,
  updated_by INT NULL,
  updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_jswp_co_date (co_id, entry_date, active),
  KEY idx_jswp_co_quality_date (co_id, weaving_quality_id, entry_date, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- DOCTRINE: views may format, never accumulate — no window functions, no GROUP BY
-- over full history, no view-on-view in any request path. vw_weaving_pick_act is
-- REFERENCE SEMANTICS + DIFF ORACLE ONLY: never query it on large tenants (it
-- GROUPs the full jute_sqc_weaving_pick history); endpoints use the flattened
-- pick probes on the base table in src/juteProduction/weaving_query.py.
CREATE OR REPLACE VIEW vw_weaving_pick_act AS
SELECT
    co_id,
    weaving_quality_id,
    entry_date,
    AVG(picks)                       AS avg_picks,
    COALESCE(STDDEV_SAMP(picks), 0)  AS std_picks,
    MIN(picks)                       AS min_picks,
    MAX(picks)                       AS max_picks,
    AVG(width)                       AS avg_width,
    MIN(width)                       AS min_width,
    MAX(width)                       AS max_width,
    COUNT(*)                         AS n_obs
FROM jute_sqc_weaving_pick
WHERE active = 1
GROUP BY co_id, weaving_quality_id, entry_date;

-- Rollback:
-- DROP VIEW IF EXISTS vw_weaving_pick_act;
-- DROP TABLE IF EXISTS jute_sqc_weaving_pick;
