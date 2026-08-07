-- sls-ONLY data fix (run BEFORE alter_spreader_machine_attr_add_branch_id.sql).
-- Problem: co 106 (LC) configured spreader roll weights against co 2's EJM machines
-- (665-669 = Spreader 1-5, 670-671 = Inter-Spreader 1-2) because the weight-master
-- machine picker was not branch-scoped. co 106's own spreaders in branch 87 are
-- 2930-2934 (Spreader -1..-5, codes 100001-100005) and had no weight rows.
--
-- Fix: re-point the 5 "Spreader N" rows (100 kg) to the matching LC machines by
-- name order; delete the 2 Inter-Spreader rows (90 kg) - LC has no inter-spreaders.
--
-- Rollback:
--   UPDATE spreader_machine_attr SET machine_id = 665 WHERE spreader_machine_attr_id = 8;
--   UPDATE spreader_machine_attr SET machine_id = 666 WHERE spreader_machine_attr_id = 9;
--   UPDATE spreader_machine_attr SET machine_id = 667 WHERE spreader_machine_attr_id = 10;
--   UPDATE spreader_machine_attr SET machine_id = 668 WHERE spreader_machine_attr_id = 11;
--   UPDATE spreader_machine_attr SET machine_id = 669 WHERE spreader_machine_attr_id = 12;
--   INSERT INTO spreader_machine_attr (spreader_machine_attr_id, co_id, machine_id, wt_per_roll, active) VALUES
--     (13, 106, 670, 90.000, 1), (14, 106, 671, 90.000, 1);

UPDATE spreader_machine_attr SET machine_id = 2930 WHERE spreader_machine_attr_id = 8 AND co_id = 106 AND machine_id = 665;
UPDATE spreader_machine_attr SET machine_id = 2931 WHERE spreader_machine_attr_id = 9 AND co_id = 106 AND machine_id = 666;
UPDATE spreader_machine_attr SET machine_id = 2932 WHERE spreader_machine_attr_id = 10 AND co_id = 106 AND machine_id = 667;
UPDATE spreader_machine_attr SET machine_id = 2933 WHERE spreader_machine_attr_id = 11 AND co_id = 106 AND machine_id = 668;
UPDATE spreader_machine_attr SET machine_id = 2934 WHERE spreader_machine_attr_id = 12 AND co_id = 106 AND machine_id = 669;

DELETE FROM spreader_machine_attr WHERE spreader_machine_attr_id IN (13, 14) AND co_id = 106 AND machine_id IN (670, 671);
