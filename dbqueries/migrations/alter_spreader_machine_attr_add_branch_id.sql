-- Branch-scope spreader_machine_attr (roll weight per spreader machine).
-- Weights were co_id-scoped only; machines are owned by a branch (machine -> dept -> branch),
-- so the weight master could save rows against another company/branch's machines.
-- Adds branch_id, backfills it (and co_id) from the machine's dept -> branch chain.
-- Target DBs: dev3, sls. On sls run sls_fix_spreader_machine_attr_co106.sql FIRST.
--
-- Rollback: ALTER TABLE spreader_machine_attr DROP COLUMN branch_id;

ALTER TABLE spreader_machine_attr
    ADD COLUMN branch_id INT NULL AFTER co_id;

-- Backfill from the machine's authoritative ownership chain; also repair co_id
-- so legacy rows agree with the owning branch's company.
UPDATE spreader_machine_attr sma
JOIN machine_mst m ON m.machine_id = sma.machine_id
JOIN dept_mst d ON d.dept_id = m.dept_id
JOIN branch_mst b ON b.branch_id = d.branch_id
SET sma.branch_id = d.branch_id,
    sma.co_id = b.co_id;
