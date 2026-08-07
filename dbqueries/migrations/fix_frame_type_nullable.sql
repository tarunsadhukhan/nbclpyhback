-- Migration to drop frame_type column from mechine_spg_details table
-- This aligns the database schema with the ORM model where frame_type was removed

ALTER TABLE mechine_spg_details DROP COLUMN frame_type;
