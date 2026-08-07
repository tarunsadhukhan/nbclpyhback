-- Migration: Add transporter GST, doc number/date, buyer order, and e-invoice fields to sales_invoice
-- Date: 2026-04-01
-- Rollback: Remove all added columns (see rollback section at end)

-- Add 9 new columns to sales_invoice table
ALTER TABLE sales_invoice
ADD COLUMN transporter_branch_id INT NULL AFTER transporter_state_name,
ADD COLUMN transporter_doc_no VARCHAR(255) NULL AFTER transporter_branch_id,
ADD COLUMN transporter_doc_date DATE NULL AFTER transporter_doc_no,
ADD COLUMN buyer_order_no VARCHAR(255) NULL AFTER transporter_doc_date,
ADD COLUMN buyer_order_date DATE NULL AFTER buyer_order_no,
ADD COLUMN irn VARCHAR(255) NULL AFTER buyer_order_date,
ADD COLUMN ack_no VARCHAR(100) NULL AFTER irn,
ADD COLUMN ack_date DATE NULL AFTER ack_no,
ADD COLUMN qr_code LONGTEXT NULL AFTER ack_date;

-- Add foreign key constraint on transporter_branch_id
ALTER TABLE sales_invoice
ADD CONSTRAINT fk_sales_invoice_transporter_branch
FOREIGN KEY (transporter_branch_id) REFERENCES party_branch_mst(party_mst_branch_id);

-- ROLLBACK:
-- ALTER TABLE sales_invoice DROP FOREIGN KEY fk_sales_invoice_transporter_branch;
-- ALTER TABLE sales_invoice DROP COLUMN transporter_branch_id, DROP COLUMN transporter_doc_no, DROP COLUMN transporter_doc_date, DROP COLUMN buyer_order_no, DROP COLUMN buyer_order_date, DROP COLUMN irn, DROP COLUMN ack_no, DROP COLUMN ack_date, DROP COLUMN qr_code;
