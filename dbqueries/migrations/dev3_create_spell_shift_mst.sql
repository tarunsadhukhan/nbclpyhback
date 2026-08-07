-- Migration: Replicate sls shift_mst / spell_mst schema into dev3 + seed
-- Date: 2026-06-11
-- Applies to: dev3 ONLY (sls already has these tables)
--
-- DDL captured verbatim from `SHOW CREATE TABLE` on sls (2026-06-11), minus AUTO_INCREMENT offsets.
-- Chosen seed IDs (deterministic rule: reuse dev3 spreader seed scope):
--   co_id = 1, branch_id = 2 ('Factory', co 1) — dev3 spreader machines live in
--   dept_id 2 ('Jute5') on branch 2; spreader_prod_entry/spreader_machine_attr use co_id 1.
-- Shift timings copied from sls branch-4 rows: A 06:00-17:00, B 11:00-22:00, C 22:00-06:00 (overnight).
-- Spell hours mirror sls: A1=5, B1=3, A2=3, B2=5, C=8 (overnight).

CREATE TABLE IF NOT EXISTS `shift_mst` (
  `shift_id` int NOT NULL AUTO_INCREMENT,
  `shift_name` varchar(25) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL,
  `status` int DEFAULT NULL,
  `branch_id` int DEFAULT NULL,
  `spell_type` int DEFAULT NULL,
  `starting_time` time DEFAULT NULL,
  `working_hours` decimal(5,2) DEFAULT NULL,
  `minimum_work_hours` decimal(5,2) DEFAULT NULL,
  `break_hours` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `halfday_work_hours` decimal(5,2) DEFAULT NULL,
  `late_minutes` int DEFAULT NULL,
  `late_minutes2` int DEFAULT NULL,
  `week_off_day` int DEFAULT NULL COMMENT 'Monday=1,Tuesday=2,Wednesday=3,Thursday=4,Friday=5,Saturday=6,Sunday=7',
  `week_off_day2` int DEFAULT NULL COMMENT 'Monday=1,Tuesday=2,Wednesday=3,Thursday=4,Friday=5,Saturday=6,Sunday=7',
  `week_off_halfDay` int DEFAULT NULL COMMENT 'Monday=1,Tuesday=2,Wednesday=3,Thursday=4,Friday=5,Saturday=6,Sunday=7',
  `is_overnight` int DEFAULT '0' COMMENT 'For yes=1, no = 0, default=0',
  `updated_by` int DEFAULT NULL,
  `update_date_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `end_time` time DEFAULT NULL,
  PRIMARY KEY (`shift_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS `spell_mst` (
  `spell_id` int NOT NULL AUTO_INCREMENT,
  `spell_code` varchar(25) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL,
  `spell_name` varchar(25) CHARACTER SET latin1 COLLATE latin1_swedish_ci NOT NULL,
  `status` int DEFAULT NULL,
  `shift_id` int DEFAULT NULL,
  `end_time` time DEFAULT NULL,
  `starting_time` time DEFAULT NULL,
  `working_hours` decimal(5,2) DEFAULT NULL,
  `minimum_work_hours` decimal(5,2) DEFAULT NULL,
  `break_hours` varchar(10) CHARACTER SET latin1 DEFAULT NULL,
  `halfday_work_hours` decimal(5,2) DEFAULT NULL,
  `late_minutes` int DEFAULT NULL,
  `late_minutes2` int DEFAULT NULL,
  `is_overnight` int DEFAULT '0' COMMENT 'For yes=1, no = 0, default=0',
  `updated_by` int DEFAULT NULL,
  `update_date_time` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`spell_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Seed shifts (idempotent via NOT EXISTS; branch_id 2 per chosen-ID rule above)
INSERT INTO shift_mst (shift_name, status, branch_id, starting_time, end_time, working_hours, is_overnight)
SELECT 'A', 1, 2, '06:00:00', '17:00:00', 8.00, 0
WHERE NOT EXISTS (SELECT 1 FROM shift_mst WHERE shift_name = 'A' AND branch_id = 2);

INSERT INTO shift_mst (shift_name, status, branch_id, starting_time, end_time, working_hours, is_overnight)
SELECT 'B', 1, 2, '11:00:00', '22:00:00', 8.00, 0
WHERE NOT EXISTS (SELECT 1 FROM shift_mst WHERE shift_name = 'B' AND branch_id = 2);

INSERT INTO shift_mst (shift_name, status, branch_id, starting_time, end_time, working_hours, is_overnight)
SELECT 'C', 1, 2, '22:00:00', '06:00:00', 8.00, 1
WHERE NOT EXISTS (SELECT 1 FROM shift_mst WHERE shift_name = 'C' AND branch_id = 2);

-- Seed spells — self-contained subquery inserts (pymysql split-on-';' executor:
-- LAST_INSERT_ID()/session vars are unreliable across statements)
INSERT INTO spell_mst (spell_code, spell_name, status, shift_id, starting_time, end_time, working_hours, minimum_work_hours, is_overnight)
SELECT 'A1', 'A1', 1, (SELECT shift_id FROM shift_mst WHERE shift_name = 'A' AND branch_id = 2 LIMIT 1),
       '06:00:00', '11:00:00', 5.00, 5.00, 0
WHERE NOT EXISTS (SELECT 1 FROM spell_mst WHERE spell_code = 'A1');

INSERT INTO spell_mst (spell_code, spell_name, status, shift_id, starting_time, end_time, working_hours, minimum_work_hours, is_overnight)
SELECT 'B1', 'B1', 1, (SELECT shift_id FROM shift_mst WHERE shift_name = 'B' AND branch_id = 2 LIMIT 1),
       '11:00:00', '14:00:00', 3.00, 3.00, 0
WHERE NOT EXISTS (SELECT 1 FROM spell_mst WHERE spell_code = 'B1');

INSERT INTO spell_mst (spell_code, spell_name, status, shift_id, starting_time, end_time, working_hours, minimum_work_hours, is_overnight)
SELECT 'A2', 'A2', 1, (SELECT shift_id FROM shift_mst WHERE shift_name = 'A' AND branch_id = 2 LIMIT 1),
       '14:00:00', '17:00:00', 3.00, 3.00, 0
WHERE NOT EXISTS (SELECT 1 FROM spell_mst WHERE spell_code = 'A2');

INSERT INTO spell_mst (spell_code, spell_name, status, shift_id, starting_time, end_time, working_hours, minimum_work_hours, is_overnight)
SELECT 'B2', 'B2', 1, (SELECT shift_id FROM shift_mst WHERE shift_name = 'B' AND branch_id = 2 LIMIT 1),
       '17:00:00', '22:00:00', 5.00, 5.00, 0
WHERE NOT EXISTS (SELECT 1 FROM spell_mst WHERE spell_code = 'B2');

INSERT INTO spell_mst (spell_code, spell_name, status, shift_id, starting_time, end_time, working_hours, minimum_work_hours, is_overnight)
SELECT 'C', 'C', 1, (SELECT shift_id FROM shift_mst WHERE shift_name = 'C' AND branch_id = 2 LIMIT 1),
       '22:00:00', '06:00:00', 8.00, 8.00, 1
WHERE NOT EXISTS (SELECT 1 FROM spell_mst WHERE spell_code = 'C');

-- =============================================================================
-- ROLLBACK:
-- DELETE FROM spell_mst WHERE spell_code IN ('A1','B1','A2','B2','C');
-- DELETE FROM shift_mst WHERE shift_name IN ('A','B','C') AND branch_id = 2;
-- DROP TABLE IF EXISTS spell_mst;   -- only if created by this migration
-- DROP TABLE IF EXISTS shift_mst;   -- only if created by this migration
-- =============================================================================
