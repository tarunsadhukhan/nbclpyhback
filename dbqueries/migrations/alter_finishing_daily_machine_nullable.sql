-- Migration: make jute_prod_finishing_daily.machine_id NULLABLE.
-- Date: 2026-06-26
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: the Sack Sewing finishing process is LABOUR-based — it has NO machine.
-- Production is keyed by the worker (eb_id) instead. machine_id was created
-- INT NOT NULL with FK fk_fd_machine -> machine_mst; relaxing it to NULL lets a
-- sacksewing row store machine_id = NULL while still keeping the FK (FK constraints
-- permit NULL). All other 8 processes are unchanged (they still send a machine_id).
--
-- eb_id is already NULL; no other column changes are needed.

ALTER TABLE jute_prod_finishing_daily
    MODIFY COLUMN machine_id INT NULL;

-- =============================================================================
-- ROLLBACK (only safe while no NULL-machine rows exist):
-- ALTER TABLE jute_prod_finishing_daily MODIFY COLUMN machine_id INT NOT NULL;
-- =============================================================================
