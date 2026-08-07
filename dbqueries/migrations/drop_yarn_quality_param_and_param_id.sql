-- Migration: FULL removal of the yarn_quality_param "operating-point set" master.
--
-- The 3rd yarn page (Yarn Quality Parameters) is retired. Its standards role was
-- already taken over by jute_prod_spng_target_map (time-versioned standards/targets),
-- and yarn qualities now anchor to a yarn item. The param_id foreign reference is
-- removed from every consumer table.
--
-- The param_id columns on daily_doff_tbl / daily_doff_frames_winding were ADDED by
-- the spinning migration (not original mobile-app columns), so dropping them is safe
-- for the mobile app.
--
-- Run on dev3 first (per CLAUDE.md), then other tenants after verification.

ALTER TABLE daily_doff_tbl              DROP COLUMN param_id;
ALTER TABLE daily_doff_frames_winding   DROP COLUMN param_id;
ALTER TABLE jute_prod_spinning_daily    DROP COLUMN param_id;
ALTER TABLE spinning_quality_xref       DROP COLUMN param_id;

DROP TABLE IF EXISTS yarn_quality_param;

-- Menu cleanup (tenant DB): remove the retired page from the portal menu, if seeded.
-- Adjust the LIKE pattern to your menu_mst URL/path column if it differs.
-- DELETE rmm FROM role_menu_map rmm
--   JOIN menu_mst m ON m.menu_id = rmm.menu_id
--   WHERE m.menu_url LIKE '%juteProduction/masters/yarnQualityParam%';
-- DELETE FROM menu_mst WHERE menu_url LIKE '%juteProduction/masters/yarnQualityParam%';

-- ============================================================================
-- ROLLBACK
-- ============================================================================
-- CREATE TABLE yarn_quality_param (
--   param_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
--   yarn_quality_id INT NOT NULL,
--   co_id INT NOT NULL,
--   set_name VARCHAR(60) NULL,
--   speed DECIMAL(10,2) NULL,
--   tpi DECIMAL(10,3) NULL,
--   std_count DECIMAL(10,3) NULL,
--   spindle INT NULL,
--   frame_type VARCHAR(10) NULL,
--   jbo_rbo VARCHAR(10) NULL,
--   subgroup_type VARCHAR(20) NULL,
--   target_eff DECIMAL(8,2) NULL,
--   active TINYINT(1) NOT NULL DEFAULT 1,
--   updated_by INT NULL,
--   updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
--   KEY idx_yqp_lookup (co_id, yarn_quality_id)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
-- ALTER TABLE daily_doff_tbl              ADD COLUMN param_id INT NULL;
-- ALTER TABLE daily_doff_frames_winding   ADD COLUMN param_id INT NULL;
-- ALTER TABLE jute_prod_spinning_daily    ADD COLUMN param_id INT NULL;
-- ALTER TABLE spinning_quality_xref       ADD COLUMN param_id INT NULL;
