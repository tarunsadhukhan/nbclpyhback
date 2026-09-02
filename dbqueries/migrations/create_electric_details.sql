-- Electric Data (electric_details) + portal sidebar menu Other Menus -> Electric Data.
-- One row per employee + date: the electric amount charged to the worker.
-- Same shape as canteen_details, minus meals/rate (the amount is keyed directly).
-- ponytail: plain active=1 soft-delete lifecycle; add the canteen-style
-- draft/approve statuses if payroll starts consuming these rows.
-- Menu: new top-level 'Other Menus' (others) with child 'Electric Data'
-- (others/electricdata), role 13 — parent access 1, child access 4,
-- mirroring the Productions menu rows.
-- Target DB: nbcl
-- Rollback:
--   DROP TABLE electric_details;
--   DELETE FROM role_menu_map WHERE menu_id IN (SELECT menu_id FROM menu_mst WHERE menu_path IN ('others', 'others/electricdata'));
--   DELETE FROM menu_mst WHERE menu_path = 'others/electricdata';
--   DELETE FROM menu_mst WHERE menu_path = 'others';

CREATE TABLE IF NOT EXISTS electric_details (
    tran_id INT PRIMARY KEY AUTO_INCREMENT,
    branch_id INT NOT NULL,
    tran_date DATE NOT NULL,
    eb_id BIGINT NOT NULL,
    amount DOUBLE NOT NULL,
    remarks VARCHAR(255) NULL,
    active INT NOT NULL DEFAULT 1,
    KEY idx_electric_branch_date (branch_id, tran_date),
    KEY idx_electric_eb (eb_id)
);

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Other Menus', 'others', 1, NULL, 1, NULL, 1, NULL, NULL
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'others');

INSERT INTO menu_mst (menu_name, menu_path, active, menu_parent_id, menu_type_id, menu_icon, module_mst_id, order_by, report)
SELECT 'Electric Data', 'others/electricdata', 1, t.menu_id, 2, NULL, 1, 2, NULL
FROM (SELECT menu_id FROM menu_mst WHERE menu_path = 'others') t
WHERE NOT EXISTS (SELECT 1 FROM menu_mst WHERE menu_path = 'others/electricdata');

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT 13, m.menu_id, 1, 4
FROM menu_mst m
WHERE m.menu_path = 'others'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 13);

INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by)
SELECT 13, m.menu_id, 4, 4
FROM menu_mst m
WHERE m.menu_path = 'others/electricdata'
  AND NOT EXISTS (SELECT 1 FROM role_menu_map r WHERE r.menu_id = m.menu_id AND r.role_id = 13);
