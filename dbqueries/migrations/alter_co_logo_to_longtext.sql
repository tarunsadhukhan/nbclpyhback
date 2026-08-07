-- Alter co_logo from VARCHAR(255) to LONGTEXT to store base64 data URIs
ALTER TABLE co_mst MODIFY COLUMN co_logo LONGTEXT NULL;
-- Rollback: ALTER TABLE co_mst MODIFY COLUMN co_logo VARCHAR(255) NULL;
