-- Drop unique constraint on item_bom so the same (parent_item_id, child_item_id, co_id)
-- tuple may appear multiple times. additional_description differentiates rows;
-- bom_id is the row identity. Soft-delete and read filtering still use active=1.
--
-- Background: commit 34b2472 added item_bom.additional_description and removed the
-- duplicate-check / soft-delete-reactivate block in bom_add_component, intending to
-- allow the same child item under one parent multiple times. The DB-level unique
-- key was missed and now blocks every legitimate duplicate insert with error 1062.

ALTER TABLE item_bom DROP INDEX uk_bom_parent_child_co;

-- Rollback (only safe if no current duplicates exist for any (parent_item_id, child_item_id, co_id)):
-- ALTER TABLE item_bom ADD UNIQUE KEY uk_bom_parent_child_co (parent_item_id, child_item_id, co_id);
