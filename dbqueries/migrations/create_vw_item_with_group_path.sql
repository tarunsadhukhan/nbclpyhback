-- Migration: Create vw_item_with_group_path
-- Purpose: Provides item listing with full hierarchical group code path concatenated with item code
--          Enables searching by combined group_code-item_code (e.g. 'MAT-RAW-COTTON001')
-- Rollback: DROP VIEW IF EXISTS vw_item_with_group_path;

DROP VIEW IF EXISTS vw_item_with_group_path;

CREATE VIEW vw_item_with_group_path AS
WITH RECURSIVE item_hierarchy AS (
  -- Anchor: top-level item groups (no parent)
  SELECT
    igm.item_grp_id,
    igm.co_id,
    CAST(igm.item_grp_code AS CHAR(500)) AS item_group_code_display,
    CAST(igm.item_grp_name AS CHAR(500)) AS item_group_name_display
  FROM item_grp_mst igm
  WHERE igm.parent_grp_id IS NULL
  UNION ALL
  -- Recursive: build full path by concatenating parent path with child code/name
  SELECT
    child.item_grp_id,
    child.co_id,
    CONCAT(parent.item_group_code_display, '-', child.item_grp_code),
    CONCAT(parent.item_group_name_display, '-', child.item_grp_name)
  FROM item_grp_mst child
  JOIN item_hierarchy parent
    ON child.parent_grp_id = parent.item_grp_id
   AND child.co_id = parent.co_id
)
SELECT
  im.item_id,
  im.item_grp_id,
  ih.co_id,
  ih.item_group_code_display,
  ih.item_group_name_display,
  im.item_code,
  im.item_name,
  CONCAT(ih.item_group_code_display, '-', im.item_code) AS full_item_code,
  im.active
FROM item_mst im
INNER JOIN item_hierarchy ih
  ON im.item_grp_id = ih.item_grp_id;
