---
name: module-hrms
description: Cross-repo guide for the HRMS module (employee database/wizard, leave type master, leave request, pay scheme, pay param, pay roll, pay register). Use when asked which HRMS page does what, which backend endpoints a page uses, or how the payroll chain and HRMS status lifecycles behave. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: HRMS (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-hrms.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/hrms/_index.md`
- `../vowerp3ui/docs/claude/modules/hrms/pages-01-employee-leave.md`
- `../vowerp3ui/docs/claude/modules/hrms/pages-02-payroll.md`
- `../vowerp3ui/docs/claude/modules/hrms/backend-map.md`
- `../vowerp3ui/docs/claude/modules/hrms/approval-flows.md`

Backend source in this repo: `src/hrms/` (`employee.py`, `payScheme.py`, `payParam.py`,
`payRegister.py`, `payRoll.py`, `payComponent.py`, `leaveType.py`, shared `query.py`), registered
in `src/main.py:211-217` — all under `/api/hrms` except `leaveType.py` under `/api/hrmsMasters`
(prefix shared with `src/masters/` designation/category/shift/spell — see `module-masters`).
Deep-dive: `docs/hrms-payroll-design.md` (code uses status 28 for Processed, not the doc's 32).
