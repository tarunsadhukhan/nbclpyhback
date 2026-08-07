-- Canteen Details page (hrms/CanteenDetails).
-- Table `canteen_details` and menu row 981 already exist in sls; only the role
-- mapping is missing, so no role can see the menu. Mirrors the access given to
-- the sibling Cash/Daily Rate Entry page (menu 979, role 13, edit).
-- Target: sls
INSERT INTO role_menu_map (role_id, menu_id, access_type_id, updated_by, updated_date_time)
SELECT 13, 981, 4, 4, NOW() FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM role_menu_map WHERE role_id = 13 AND menu_id = 981
);

-- Rollback:
-- DELETE FROM role_menu_map WHERE role_id = 13 AND menu_id = 981;
