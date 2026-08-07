-- Convert proc_po.po_no from varchar(30) to INT.
-- Safe: all stored values are numeric or NULL (verified sls + dev3, 0 non-numeric).
-- po_no is a display sequence (max+1 per branch+FY); pretty form built at render time.
-- Rollback: ALTER TABLE proc_po MODIFY COLUMN po_no VARCHAR(30) NULL;

ALTER TABLE proc_po MODIFY COLUMN po_no INT NULL;
