-- Mobile app menu permissions per portal role (Tenant Admin > User Management Portal >
-- Mobile Menu Permissions). Run in each TENANT DB (nbjcl, winsome).
-- menu_id -> menus.id (the mobile app's own menu list); role_id -> roles_mst.role_id.
-- Named mobile_* because menu_mst / role_menu_map are already the ERP portal tables.

CREATE TABLE IF NOT EXISTS mobile_role_menu_map (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    role_id           INT        NOT NULL,
    menu_id           INT        NOT NULL,
    can_view          TINYINT(1) NOT NULL DEFAULT 0,
    can_add           TINYINT(1) NOT NULL DEFAULT 0,
    can_modify        TINYINT(1) NOT NULL DEFAULT 0,
    can_delete        TINYINT(1) NOT NULL DEFAULT 0,
    can_print         TINYINT(1) NOT NULL DEFAULT 0,
    updated_by        INT        NULL,
    updated_date_time DATETIME   NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_mobile_role_menu (role_id, menu_id),
    KEY idx_mobile_role_menu_menu (menu_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- Rollback:
-- DROP TABLE IF EXISTS mobile_role_menu_map;
