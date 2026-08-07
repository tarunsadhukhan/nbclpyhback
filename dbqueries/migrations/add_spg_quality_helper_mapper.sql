-- Migration: spg_quality_helper + spg_quality_mapper + daily_doff_tbl additive changes + seed
-- Spec: docs/spinning-doff-attendance-quality-spec.md section 5.1 (v2 Helper + Mapper architecture)
-- Target: dev3 (then other tenants before code deploy)

-- Current mapping. ONE row per machine. Written ONLY by the mapper-save code path
-- (no CRUD endpoint of its own) -- helper is derived data.
CREATE TABLE spg_quality_helper (
  quality_helper_id   INT NOT NULL AUTO_INCREMENT,
  branch_id           INT NULL,              -- denormalized from machine's dept; display/scope only
  mc_id               INT NOT NULL,
  item_id             INT NOT NULL,          -- yarn item (item_mst)
  effective_from_date DATE NOT NULL,         -- copy of the producing mapper row
  effective_from_spell_id INT NULL,
  quality_mapper_id   INT NOT NULL,          -- provenance: mapper row that produced this state
  updated_by          INT NULL,
  updated_date_time   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (quality_helper_id),
  UNIQUE KEY uq_sqh_mc (mc_id),        -- grain PENDING D9: becomes (mc_id, spell_id) if mill runs per-spell qualities
  KEY idx_sqh_branch (branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Append-only change log. Owns history, as-of resolution, retro updates.
CREATE TABLE spg_quality_mapper (
  quality_mapper_id   INT NOT NULL AUTO_INCREMENT,
  branch_id           INT NULL,
  mc_id               INT NOT NULL,
  item_id             INT NOT NULL,
  effective_from_date DATE NOT NULL,
  effective_from_spell_id INT NULL,          -- NULL = start of day; else from that spell onward
                                             -- (spell order within day = spell_mst.starting_time)
  retro_mode          VARCHAR(10) NOT NULL DEFAULT 'fill',  -- fill | synced | all (what the save applied)
  retro_rows          INT NOT NULL DEFAULT 0,               -- doff rows the retro update touched (audit)
  active              TINYINT(1) NOT NULL DEFAULT 1,
  updated_by          INT NULL,
  updated_date_time   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (quality_mapper_id),
  KEY idx_sqm_lookup (mc_id, effective_from_date, quality_mapper_id),
  KEY idx_sqm_branch_date (branch_id, effective_from_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- daily_doff_tbl additive changes (no composite index exists today)
ALTER TABLE daily_doff_tbl
  ADD COLUMN item_source VARCHAR(8) NULL,
  ADD COLUMN eb_source   VARCHAR(8) NULL,
  ADD INDEX idx_ddt_mc_date (mc_id, doff_date),
  ADD INDEX idx_ddt_date_spell (doff_date, spell);

-- SEED (spec 5.1): latest active daily_doff_frames_winding S row per machine
-- -> one mapper row + one matching helper row.
-- "Latest" = max tran_date, tie-broken by max daily_doff_frm_wdg_id.
INSERT INTO spg_quality_mapper
  (branch_id, mc_id, item_id, effective_from_date, effective_from_spell_id, retro_mode, updated_by)
SELECT t.branch_id, t.mc_eb_id, t.item_id, t.tran_date, t.spell_id, 'fill', 1
FROM (
  SELECT w.branch_id, w.mc_eb_id, w.item_id, w.tran_date, w.spell_id,
         ROW_NUMBER() OVER (
           PARTITION BY w.mc_eb_id
           ORDER BY w.tran_date DESC, w.daily_doff_frm_wdg_id DESC
         ) AS rn
  FROM daily_doff_frames_winding w
  WHERE w.spg_wdg = 'S'
    AND (w.active = 1 OR w.active IS NULL)
    AND w.item_id IS NOT NULL
) t
WHERE t.rn = 1;

-- Helper mirrors the mapper seed. Valid because spg_quality_mapper was created
-- empty by this migration, so every row in it at this point IS a seed row.
INSERT INTO spg_quality_helper
  (branch_id, mc_id, item_id, effective_from_date, effective_from_spell_id, quality_mapper_id, updated_by)
SELECT m.branch_id, m.mc_id, m.item_id, m.effective_from_date, m.effective_from_spell_id, m.quality_mapper_id, 1
FROM spg_quality_mapper m
WHERE m.active = 1;

-- Rollback:
-- DROP TABLE spg_quality_helper;
-- DROP TABLE spg_quality_mapper;
-- ALTER TABLE daily_doff_tbl
--   DROP COLUMN item_source,
--   DROP COLUMN eb_source,
--   DROP INDEX idx_ddt_mc_date,
--   DROP INDEX idx_ddt_date_spell;
