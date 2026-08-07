-- Migration: widen jute_sqc_bag_weight.bag_type_label 100 -> 255
-- Module: juteSQC (R-08-23 Bag Weight SQC)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Reason: bag_type_label snapshots item_mst.item_name (VARCHAR(255)) for the chosen
-- JUTE CLOTH bag type. The original 100 was too narrow -- real bag names such as the
-- "PRINTED TYPE A JUTE BAGS(580 GMS) ... AS PER BIS SPEC NO.IS-16186:2014,500 PCS"
-- items run to 154 chars in dev3 co1, so the INSERT failed with pymysql 1406
-- "Data too long for column bag_type_label". Match the source item_name width (255).
--
-- NOTE the documented migration runner splits on the statement terminator so
-- comment lines carry NO semicolons.
;

ALTER TABLE jute_sqc_bag_weight MODIFY COLUMN bag_type_label VARCHAR(255) NULL;

-- Rollback:
-- ALTER TABLE jute_sqc_bag_weight MODIFY COLUMN bag_type_label VARCHAR(100) NULL
