---
name: module-jute-purchase
description: Cross-repo guide for the Jute Purchase module (jute PO, gate entry, material inspection/QC, material receipt MR, bill pass, jute issue, batch daily assign, batch plan master, reports). Use when asked which jute purchase page does what, which backend endpoints a page uses, or how jute approval workflows behave. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Jute Purchase (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-jute-purchase.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/jute-purchase/_index.md`
- `../vowerp3ui/docs/claude/modules/jute-purchase/pages-01-po-gate-mr.md`
- `../vowerp3ui/docs/claude/modules/jute-purchase/pages-02-inspection-issue-billpass-batch-reports.md`
- `../vowerp3ui/docs/claude/modules/jute-purchase/backend-map.md`
- `../vowerp3ui/docs/claude/modules/jute-purchase/approval-flows.md`

Backend source in this repo: `src/juteProcurement/` (`jutePO.py`, `juteGateEntry.py`,
`materialInspection.py`, `mr.py`, `juteAgentMap.py`, `billPass.py`, `issue.py`,
`batchDailyAssign.py`, `reports.py` + `query.py`, `reportQueries.py`, `constants.py`,
`formatters.py`), registered in `src/main.py:175-183`; Batch Plan Master in
`src/masters/batchPlanMaster.py` (`src/main.py:150`). Gate entry/MR/bill pass share the merged
`jute_mr` table (typos `frieght_paid`/`brokrage_rate` — never rename); approval-level migrations:
`dbqueries/migrations/add_approval_level_to_jute_mr.sql`, `add_approval_level_to_jute_po.sql`.
