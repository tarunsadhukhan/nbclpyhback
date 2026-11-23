-- Winsome "Production" menu: indexes on the legacy tables mirrored by migrate_payowagesrate_ocp.py
-- (the mirror copies columns only). Target DB: winsome. Used by src/production/winsomeProduction.py
-- (document lookup by DocEntry, newest-first list by date, last quality per machine).
ALTER TABLE PayOProdWDG  ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (WDate), ADD INDEX ix_mch (Mch1Code, WDate);
ALTER TABLE PayOProdBMG  ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (WDate), ADD INDEX ix_mch (Mch1Code, WDate);
-- WVG ix_mch also carries Shift: Fill picks each loom's last quality by (date, shift).
ALTER TABLE PayOProdWVG  ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (WDate), ADD INDEX ix_mch (Mch1Code, WDate, Shift);
-- Line-level list (newest first) on the 595k-row weaving table.
ALTER TABLE PayOProdWVG  ADD INDEX ix_list (WDate DESC, DocEntry DESC, LineID);
ALTER TABLE PayOProdSACK ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (WDate), ADD INDEX ix_mch (Mch1Code, WDate);
ALTER TABLE PayProdAll   ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (DocDate);
ALTER TABLE PayProdWIL   ADD INDEX ix_doc (CompCode, DocEntry), ADD INDEX ix_date (DocDate);
ALTER TABLE PayOQLT      ADD INDEX ix_dept (DeptCode, QCode);
