-- Migration: Restructure jute_prod_finishing_quality — the ITEM is now the identity.
-- Date: 2026-06-25
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: The finishing module was just built and is NOT live, so dropping the old
-- structural-spec columns (and their data) is acceptable. Three changes:
--   1. Type relabel is DISPLAY ONLY (quality_type stays INT 1/2 — no value change here):
--        quality_type=1 -> "Hessian"  (was "Cloth")
--        quality_type=2 -> "Sacking"  (was "Bag")
--   2. Drop the separate quality code/name (fin_quality_code / fin_quality_name). The
--      item_mst label IS the quality now; one row per (co_id, item_id, quality_type).
--   3. Drop ALL old structural params; add THREE new OPTIONAL (nullable) params:
--        packsheet_wt     DECIMAL(14,3) NULL   -- kg
--        std_bale_weight  DECIMAL(14,3) NULL   -- kg
--        no_of_bags       INT           NULL   -- pcs
--
-- Uniqueness is APP-LEVEL on (co_id, quality_type, item_id) among active=1 (no DB
-- unique constraint — matches the existing soft-delete pattern). The existing indexes
-- idx_fq_co_item (co_id, item_id), idx_fq_type (co_id, quality_type) and the FK
-- fk_fq_item (item_id -> item_mst) all STAY. Conventions match
-- create_finishing_tables.sql: audit cols handled by triggers (NO created_*).

ALTER TABLE jute_prod_finishing_quality
    ADD COLUMN packsheet_wt    DECIMAL(14,3) NULL AFTER item_id,
    ADD COLUMN std_bale_weight DECIMAL(14,3) NULL AFTER packsheet_wt,
    ADD COLUMN no_of_bags      INT           NULL AFTER std_bale_weight,
    DROP COLUMN fin_quality_code,
    DROP COLUMN fin_quality_name,
    DROP COLUMN width_in,
    DROP COLUMN ports,
    DROP COLUMN ends,
    DROP COLUMN shots,
    DROP COLUMN oz_per_yd,
    DROP COLUMN std_oz_per_yd,
    DROP COLUMN lead_length,
    DROP COLUMN finished_length,
    DROP COLUMN mc_teeth,
    DROP COLUMN cloth_quality_id,
    DROP COLUMN bag_length_in,
    DROP COLUMN bag_width_in,
    DROP COLUMN mouth_type,
    DROP COLUMN bags_per_bale;

-- =============================================================================
-- ROLLBACK (re-ADD the dropped columns as nullable — original data is gone — and
-- DROP the three new params):
-- ALTER TABLE jute_prod_finishing_quality
--     ADD COLUMN fin_quality_code  VARCHAR(50)  NULL AFTER item_id,
--     ADD COLUMN fin_quality_name  VARCHAR(100) NULL AFTER fin_quality_code,
--     ADD COLUMN width_in          DECIMAL(10,3) NULL,
--     ADD COLUMN ports             INT          NULL,
--     ADD COLUMN ends              INT          NULL,
--     ADD COLUMN shots             DECIMAL(10,3) NULL,
--     ADD COLUMN oz_per_yd         DECIMAL(10,3) NULL,
--     ADD COLUMN std_oz_per_yd     DECIMAL(10,3) NULL,
--     ADD COLUMN lead_length       DECIMAL(12,4) NULL,
--     ADD COLUMN finished_length   DECIMAL(12,4) NULL,
--     ADD COLUMN mc_teeth          INT          NULL,
--     ADD COLUMN cloth_quality_id  INT          NULL,
--     ADD COLUMN bag_length_in     DECIMAL(10,3) NULL,
--     ADD COLUMN bag_width_in      DECIMAL(10,3) NULL,
--     ADD COLUMN mouth_type        VARCHAR(30)  NULL,
--     ADD COLUMN bags_per_bale     INT          NULL,
--     DROP COLUMN packsheet_wt,
--     DROP COLUMN std_bale_weight,
--     DROP COLUMN no_of_bags;
-- =============================================================================
