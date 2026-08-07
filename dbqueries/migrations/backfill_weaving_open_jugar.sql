-- Migration: backfill_weaving_open_jugar.sql
-- Backfill jute_prod_weaving_daily.open_jugar (added by
-- add_weaving_open_jugar_column.sql) for ALL active rows from the
-- vw_weaving_daily reference LAG ordering:
--   COALESCE(LAG(close_jugar) OVER (PARTITION BY co_id, machine_id,
--   weaving_quality_id ORDER BY tran_date, spell_rank, weaving_daily_id), 0)
-- with spell_rank = A1:1 B1:2 A2:3 B2:4 C:5 else 99 (the view CASE, verbatim).
-- LAG over COALESCE(close_jugar, 0) equals the view LAG + outer COALESCE for
-- every row (a NULL-close predecessor yields 0 either way).
--
-- IDEMPOTENT and RERUNNABLE: recomputes every active row from scratch.
-- Re-run to heal drift after bulk imports that bypass the app writers
-- (detect drift with dbqueries/check_weaving_open_jugar_parity.sql).
-- Inactive rows keep NULL (invisible to all readers).
--
-- EXECUTOR CONSTRAINT: no semicolon in comment prose, header terminated by
-- the lone semicolon below.
--
-- ROLLBACK (as comments):
-- UPDATE jute_prod_weaving_daily SET open_jugar = NULL
;

UPDATE jute_prod_weaving_daily wd
JOIN (
    SELECT x.weaving_daily_id,
           COALESCE(LAG(x.close_jugar_z) OVER (
               PARTITION BY x.co_id, x.machine_id, x.weaving_quality_id
               ORDER BY x.tran_date, x.spell_rank, x.weaving_daily_id
           ), 0) AS oj
    FROM (
        SELECT wd2.weaving_daily_id, wd2.co_id, wd2.machine_id,
               wd2.weaving_quality_id, wd2.tran_date,
               COALESCE(wd2.close_jugar, 0) AS close_jugar_z,
               CASE sp.spell_code WHEN 'A1' THEN 1 WHEN 'B1' THEN 2
                    WHEN 'A2' THEN 3 WHEN 'B2' THEN 4 WHEN 'C' THEN 5
                    ELSE 99 END AS spell_rank
        FROM jute_prod_weaving_daily wd2
        LEFT JOIN spell_mst sp ON sp.spell_id = wd2.spell_id
        WHERE wd2.active = 1
    ) x
) l ON l.weaving_daily_id = wd.weaving_daily_id
SET wd.open_jugar = l.oj
