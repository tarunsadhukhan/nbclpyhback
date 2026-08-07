-- Migration: Weaving foundation — confirm/seed the 'Loom' machine type.
-- Date: 2026-06-23
-- Applies to: tenant database dev3 (QA). Promote to other tenants later.
--
-- Context: Weaving production runs on LOOM machines. Looms are machine_mst rows of
-- machine_type_mst.machine_type_name = 'Loom'. The backend resolves looms at runtime
-- by NAME ('Loom'), and MySQL string comparison is case-insensitive under the default
-- collation, so 'Loom' = 'LOOM'.
--
-- dev3 REALITY (verified 2026-06-23): machine_type 'LOOM' already exists at
-- machine_type_id = 6 (4 looms) — NOT id 7 as SPEC Q1 stated (that id came from the
-- code3i `type_of_mechine=7` source DB, which is a different schema). There is also a
-- separate 'Weaving' type (id 11, 1 machine). The runtime constant resolves by NAME
-- 'Loom' -> id 6. This insert is therefore a NO-OP in dev3 (the NOT EXISTS guard is
-- case-insensitive). It seeds 'Loom' only in tenants that lack any loom type.
--
-- item_type 'Jute Cloth' (id 5) is already present from beaming
-- (create_beaming_item_type_and_machine_type.sql) and is reused for woven cloth (Q2).

INSERT INTO machine_type_mst (machine_type_name, updated_by, active)
SELECT 'Loom', 1, 1
WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Loom');

-- =============================================================================
-- ROLLBACK: (do NOT drop 'LOOM' in dev3 — it predates this module and owns machines)
-- -- For tenants where THIS migration created the row only:
-- -- DELETE FROM machine_type_mst WHERE machine_type_name = 'Loom'
-- --   AND NOT EXISTS (SELECT 1 FROM machine_mst m WHERE m.machine_type_id = machine_type_mst.machine_type_id);
-- =============================================================================
