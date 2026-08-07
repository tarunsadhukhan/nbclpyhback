---
name: module-masters
description: Cross-repo guide for the Masters module (item/item group, party, warehouse, project, cost factor, departments, jute/yarn/machine masters, HR and finance masters — 27 portal pages, ~23 backend routers). Use when asked which master page does what, which backend endpoints a master page uses, or where to add a new master. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Masters (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-masters.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/masters/_index.md`
- `../vowerp3ui/docs/claude/modules/masters/pages-01-items-inventory.md`
- `../vowerp3ui/docs/claude/modules/masters/pages-02-jute-yarn-machines.md`
- `../vowerp3ui/docs/claude/modules/masters/pages-03-hr-finance-misc.md`
- `../vowerp3ui/docs/claude/modules/masters/backend-map.md`

Backend source in this repo: `src/masters/` (~23 routers, registered in `src/main.py:133-158`),
plus `src/juteProcurement/juteAgentMap.py` (`/api/juteAgentMap`, main.py:179) and
`src/bomcosting/stdRateCard.py` (`/api/stdRateCard`, main.py:163) which serve masters FE pages.
No approval workflows; masters are CRUD.
