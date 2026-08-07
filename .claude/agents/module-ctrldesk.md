---
name: module-ctrldesk
description: Cross-repo guide for the Control Desk dashboard (dashboardctrldesk) — the VOW team's own high-level admin for managing organizations/tenants, system menus, control-desk roles and users. Use when asked which ctrldesk page does what or which /ctrldskAdmin endpoints a page uses. Covers vowerp3ui pages and vowerp3be src/common/ctrldskAdmin routers.
tools: Read, Grep, Glob
---

# Module Guide: Control Desk (pointer)

Last verified: 2026-06-12

The full guide lives in the frontend repo:

- **Full agent (read this):** `../vowerp3ui/.claude/agents/module-ctrldesk.md` — persona overview,
  per-page catalog with endpoint tables, backend map, quirks, maintenance rules.
- **FE pages:** `../vowerp3ui/src/app/dashboardctrldesk/` (route constants in the
  `apiRoutesconsole` object in `../vowerp3ui/src/utils/api.ts`).
- **BE routers (this repo):** `src/common/ctrldskAdmin/` — `roles.py`, `users.py`, `orgs.py`,
  `menuportal.py`, registered in `src/main.py` under `/api/ctrldskAdmin` (`menu.py` is NOT
  registered — dead file). All use `Session(default_engine)` → `vowconsole3`, never
  `get_tenant_db`; auth is `verify_access_token`.
