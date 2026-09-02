-- Press production: stored RATE/HRS column = amount / (divisible_hrs - lost_hrs).
-- Generated from earlier generated columns (amount, divisible_hrs — MySQL allows
-- referencing generated columns defined before this one). Missing lost_hrs counts
-- as 0; zero or missing net hours give NULL (NULLIF avoids a division error).
-- Target DB: nbcl
-- Rollback: ALTER TABLE press_production DROP COLUMN rate_per_hrs;

ALTER TABLE press_production
    ADD COLUMN rate_per_hrs DOUBLE
    GENERATED ALWAYS AS (ROUND(amount / NULLIF(divisible_hrs - IFNULL(lost_hrs, 0), 0), 2)) STORED;
