-- Migration: index item_grp_mst (co_id, parent_grp_id)
-- Purpose: speeds the recursive group-path CTE behind vw_item_with_group_path
--          (anchor was full-scanning for parent_grp_id IS NULL; recursive step
--           seeks per parent). Benefits the Item Master list + item_search.
-- Note: item_grp_mst already has a standalone index on co_id; the composite
--       (co_id, parent_grp_id) supersedes it for these lookups.
-- Rollback: DROP INDEX idx_item_grp_co_parent ON item_grp_mst;

ALTER TABLE item_grp_mst ADD INDEX idx_item_grp_co_parent (co_id, parent_grp_id);
