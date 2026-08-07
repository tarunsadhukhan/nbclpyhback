-- Migration: alter sales_delivery_order schema
-- Date: 2026-02-25
-- Changes:
--   1. delivery_order_no: VARCHAR(255) -> BIGINT
--   2. Remove column: party_branch_id
--   3. Remove column: eway_bill_no
--   4. Remove column: eway_bill_date

-- Forward migration
ALTER TABLE sales_delivery_order
    MODIFY COLUMN delivery_order_no BIGINT NULL,
    DROP COLUMN party_branch_id,
    DROP COLUMN eway_bill_no,
    DROP COLUMN eway_bill_date;

-- Rollback (run manually if needed):
-- ALTER TABLE sales_delivery_order
--     MODIFY COLUMN delivery_order_no VARCHAR(255) NULL,
--     ADD COLUMN party_branch_id INT NULL AFTER party_id,
--     ADD COLUMN eway_bill_no VARCHAR(100) NULL AFTER driver_contact,
--     ADD COLUMN eway_bill_date DATE NULL AFTER eway_bill_no;
