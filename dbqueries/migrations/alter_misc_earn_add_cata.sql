-- Misc Earn rules can be restricted to an employee category (category_mst) —
-- e.g. the BEAMING beam-changes allowance applies to CAT-7 only. NULL = all categories.
-- Target DB: nbcl
-- Rollback: ALTER TABLE misc_earn_mst DROP COLUMN cata_id;

ALTER TABLE misc_earn_mst
    ADD COLUMN cata_id BIGINT NULL AFTER designation_id,
    ADD KEY idx_misc_earn_cata (cata_id);
