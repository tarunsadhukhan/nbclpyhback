-- Add "Jute Invoice" invoice type to invoice_type_mst
-- Run on each tenant database that needs this type

INSERT INTO invoice_type_mst (invoice_type_name) VALUES ('Jute Invoice');

-- After inserting, map to specific companies via:
-- INSERT INTO invoice_type_co_map (co_id, invoice_type_id, active, updated_by)
-- SELECT <co_id>, invoice_type_id, 1, <user_id>
-- FROM invoice_type_mst WHERE invoice_type_name = 'Jute Invoice';

-- Rollback:
-- DELETE FROM invoice_type_co_map WHERE invoice_type_id = (SELECT invoice_type_id FROM invoice_type_mst WHERE invoice_type_name = 'Jute Invoice');
-- DELETE FROM invoice_type_mst WHERE invoice_type_name = 'Jute Invoice';
