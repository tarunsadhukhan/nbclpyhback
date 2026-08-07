---
name: add-menu
description: Add a sidebar menu entry through the VoWERP3 multi-level menu system (control_desk_menu / con_menu_master / portal_menu_mst in vowconsole3, menu_mst + role_menu_map in tenant DBs). Use whenever a new page or feature needs to appear in any dashboard sidebar. Always asks which DBs/tenants and roles before inserting.
---

# Skill: add-menu

Last verified: 2026-06-12

## When to use

A new page/feature must appear in a sidebar — Control Desk, Tenant Admin, or Portal. Menus are
data-driven; nothing shows up until rows exist in the right menu tables.

## Menu architecture (which table feeds which sidebar)

| Level | Table | Database | Feeds |
|-------|-------|----------|-------|
| 1 | `control_desk_menu` | `vowconsole3` | Control Desk sidebar (`dashboardctrldesk`) |
| 2 | `con_menu_master` (+ `con_role_menu_map`) | `vowconsole3` | Tenant Admin sidebar (`dashboardadmin`) |
| 3 | `portal_menu_mst` | `vowconsole3` | **Master template** for portal menus (managed by control desk) |
| 4 | `menu_mst` (+ `role_menu_map`) | each **tenant DB** (e.g. `dev3`) | Actual Portal sidebar (`dashboardportal`) |

A portal page needs **both** the template row (`portal_menu_mst` in vowconsole3) and the tenant row
(`menu_mst` in each tenant DB that should see it), plus `role_menu_map` rows for access.

## Questions to ask the user FIRST (never assume)

1. **Which sidebar(s)?** Control Desk / Tenant Admin / Portal — determines the tables.
2. **Which database(s)/tenant(s)?** For portal menus: which tenant DBs get the `menu_mst` row?
   Suggest `dev3` (QA/dev tenant) as the default; list any others explicitly.
3. **Which module** does the menu belong to (`module_mst` / `con_module_masters` mapping)?
4. **Which roles** get access (`role_menu_map` / `con_role_menu_map` rows)? All roles or specific ones?
5. **Where in the hierarchy?** Parent menu (or root), display order, route/URL the menu points to.
6. **Portal permissions:** which action levels apply (view=1, print=2, create=3, edit=4)?

## Procedure

1. Inspect the target table's current shape first — column names vary per level. Use the pymysql
   pattern (credentials in `env/database.env`):
   `SHOW COLUMNS FROM {table}` and `SELECT * FROM {table} WHERE parent... LIMIT 5` to copy an
   existing sibling row's structure. Follow `.claude/agents/dbmanager.md` §7 (Menu System).
2. Write the INSERT(s) as a script in `dbqueries/migrations/` (descriptive snake_case name, rollback
   DELETE as comment) — one script covering all confirmed targets.
3. For portal menus: insert the `portal_menu_mst` template row (vowconsole3) AND the `menu_mst` row
   in each confirmed tenant DB, then `role_menu_map` rows for the confirmed roles.
4. Execute per target DB with the user's confirmation (use the `run-migration` skill — it re-confirms
   the target DB).
5. Frontend: confirm the route exists for the URL the menu points to; portal sidebars cache menus in
   localStorage — tell the user to re-login or clear cache to see the new entry.

## Verification

- `SELECT` the inserted rows back from every target DB.
- Log in as a user holding one of the mapped roles; the menu appears and routes correctly.
- A user WITHOUT the role must not see it.
