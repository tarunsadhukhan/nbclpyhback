-- Layer 3: kill the carry-forward cost at the root.
--
-- get_weaving_quality_map_query's prev_quality_* ("the loom's most-recent prior mapping")
-- was a per-loom scan of jute_prod_weaving_quality_map, which on sls holds ~2,895 rows PER
-- loom (2.26M total). EXPLAIN: DEPENDENT DERIVED, rows=2895, Using filesort -- because
-- `weaving_quality_id IS NOT NULL` isn't index-resolvable, MySQL reads each loom's whole
-- history and sorts. ~7s even via LATERAL. No index fixes "latest non-null per group" over a
-- fat history; a maintained one-row-per-loom pointer does.
--
-- weaving_loom_current_quality = the latest NON-NULL mapping per (co_id, machine_id). The read
-- query LEFT JOINs it (PK lookup, O(1)/loom); quality_map_save keeps it in sync on every save.

CREATE TABLE IF NOT EXISTS weaving_loom_current_quality (
    co_id              INT       NOT NULL,
    branch_id          INT       NULL,
    machine_id         INT       NOT NULL,                 -- loom (machine_type 'Loom')
    weaving_quality_id INT       NOT NULL,                 -- latest NON-NULL mapped quality
    tran_date          DATE      NOT NULL,                 -- date that mapping is from
    spell_id           INT       NOT NULL,                 -- spell that mapping is from
    updated_date_time  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (co_id, machine_id)
);

-- Backfill: latest non-null mapping per (co_id, machine_id). One-time full scan of the map
-- table (uses idx_wqm_* ); collapses to one row per loom. Rerunnable (ON DUPLICATE KEY UPDATE).
INSERT INTO weaving_loom_current_quality
    (co_id, branch_id, machine_id, weaving_quality_id, tran_date, spell_id)
SELECT co_id, branch_id, machine_id, weaving_quality_id, tran_date, spell_id
FROM (
    SELECT co_id, branch_id, machine_id, weaving_quality_id, tran_date, spell_id,
           ROW_NUMBER() OVER (
               PARTITION BY co_id, machine_id
               ORDER BY tran_date DESC, weaving_quality_map_id DESC
           ) AS rn
    FROM jute_prod_weaving_quality_map
    WHERE active = 1 AND weaving_quality_id IS NOT NULL
) t
WHERE rn = 1
ON DUPLICATE KEY UPDATE
    branch_id          = VALUES(branch_id),
    weaving_quality_id = VALUES(weaving_quality_id),
    tran_date          = VALUES(tran_date),
    spell_id           = VALUES(spell_id);

-- Rollback:
-- DROP TABLE IF EXISTS weaving_loom_current_quality;
