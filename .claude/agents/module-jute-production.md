---
name: module-jute-production
description: Cross-repo guide for the Jute Production module (spreader production/issue/roll stock, drawing meter entry, spinning/doff backend, production masters, roll stock reports) AND Jute SQC (morrah weight QC, r-08-01). Use when asked which juteProduction or juteSQC page does what, which backend endpoints a page uses, or how the spreader→drawing→spinning chain works. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Jute Production (+ Jute SQC) (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read this (catalog is inline, no part files):

- `../vowerp3ui/.claude/agents/module-jute-production.md` (the full agent body)

Backend source in this repo: `src/juteProduction/` (`spreader_entry.py`, `spreader_issue.py`,
`spreader_stock.py`, `spreader_masters.py`, `drawing_entry.py`, `drawing_masters.py`,
`spinning_entry.py`, `spinning_masters.py`, `reports.py`, plus `constants.py`, `*query*.py`,
`models.py`/`spinning_models.py`, `services/`) and `src/juteSQC/` (`morrahWeight.py`, `query.py`).
Registered in `src/main.py:186-197` under `/api/spreaderProd`, `/api/spreaderMasters`,
`/api/drawingProd`, `/api/drawingMasters`, `/api/spinningProd`, `/api/spinningMasters`,
`/api/juteProductionReports`, `/api/juteSQC`. Spinning routers have **no frontend page yet**.
No approval workflow anywhere in this module — soft-delete CRUD only.

**Winding (design only, not implemented):** legacy code3i winding production (Doff / Jugar /
Quality screens) is fully documented in `docs/winding-production-design.md` (logical flow, data
points, formulas, and a proposed `/api/windingProd` + `/api/windingMasters` target). FE catalog:
`../vowerp3ui/docs/claude/modules/jute-production/`. No winding code exists in `src/juteProduction/` yet.
