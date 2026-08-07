-- Migration: Humidity Recording SQC table (jute_sqc_humidity)
-- Module: juteSQC (plant-wide department temperature / RH log)
-- Date: 2026-06-28
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Flat single-table morrah/bag_weight pattern (NO detail table). One row per
-- (report_date, dept, round) reading-set carries 1..3 SPOT readings as a JSON
-- string array of objects {spot_label, reading_time, temp_c, rh_pct}
-- (spots VARCHAR(1000), json.dumps / json.loads). round_no 1=Morning, 2=Noon,
-- 3=Evening. avg_temp = mean(temp_c over spots), avg_rh = mean(rh_pct over spots),
-- both computed server-side at save and stored (2dp). No StDev/CV, no band.
-- Coexists with the spinning RHMR report and does NOT supersede it.
--
-- NOTE the documented migration runner splits on the statement terminator so
-- comment lines carry NO semicolons.
;

CREATE TABLE jute_sqc_humidity (
    humidity_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    co_id INT NOT NULL,
    branch_id INT NULL,
    report_date DATE NOT NULL,
    dept_id INT NULL,
    round_no INT NOT NULL,
    spots VARCHAR(1000) NOT NULL,
    calc_avg_temp DECIMAL(5,2) NULL,
    calc_avg_rh DECIMAL(5,2) NULL,
    prepared_by VARCHAR(150) NULL,
    active INT NOT NULL DEFAULT 1,
    updated_by INT NULL,
    updated_date_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_humidity_co_id (co_id),
    INDEX idx_humidity_report_date (report_date)
);

-- Rollback:
-- DROP TABLE jute_sqc_humidity
