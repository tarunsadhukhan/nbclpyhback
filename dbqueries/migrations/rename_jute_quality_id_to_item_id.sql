-- Migration: Rename jute_quality_id → item_id in jute_issue table
-- Purpose: Deprecate jute_quality_id naming; align DB column with ORM model and API
-- Date: 2026-02-17
-- Applied to: dev3 database
-- Run this migration in each tenant database

ALTER TABLE jute_issue CHANGE COLUMN jute_quality_id item_id INT NULL;
