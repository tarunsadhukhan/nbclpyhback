-- Add bom_status lifecycle column to item_bom_hdr_mst.
-- Independent from status_id (which feeds BOM Costing approval workflow).
-- Allowed values (enforced at app layer): 'New', 'Certified', 'Under Development', 'Closed'.

ALTER TABLE item_bom_hdr_mst
ADD COLUMN bom_status VARCHAR(32) NOT NULL DEFAULT 'New' AFTER status_id;

-- Rollback:
-- ALTER TABLE item_bom_hdr_mst DROP COLUMN bom_status;
