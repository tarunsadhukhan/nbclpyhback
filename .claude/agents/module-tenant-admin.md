---
name: module-tenant-admin
description: Cross-repo guide for the Tenant Admin dashboard (dashboardadmin) — where each tenant configures companies, branches, departments, users, roles, and the approval hierarchy. Use when asked which dashboardadmin page does what or which /companyAdmin or /admin/PortalData endpoints a page uses. Covers vowerp3ui pages and vowerp3be src/common routers.
tools: Read, Grep, Glob
---

# Module Guide: Tenant Admin (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-tenant-admin.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/tenant-admin/_index.md`
- `../vowerp3ui/docs/claude/modules/tenant-admin/pages-01-company-org-structure.md`
- `../vowerp3ui/docs/claude/modules/tenant-admin/pages-02-users-roles-approvals.md`
- `../vowerp3ui/docs/claude/modules/tenant-admin/backend-map.md`

Backend source in this repo: `src/common/companyAdmin/` (`menu.py`, `roles.py`, `users.py` →
vowconsole3 org-scoped; `company.py`, `branch.py`, `dept_subdept.py` → tenant DB) and
`src/common/portal/` (`roles.py`, `users.py`, `menu.py`, `approval.py` → tenant DB), registered
in `src/main.py:119-132` under `/api/companyAdmin` and `/api/admin/PortalData`. Pages also borrow
`/api/mechMaster` (`src/masters/mechineMaster.py`) and `/api/hrms` (`src/hrms/payScheme.py`,
`payComponent.py`).
