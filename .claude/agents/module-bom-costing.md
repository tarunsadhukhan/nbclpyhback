---
name: module-bom-costing
description: Cross-repo guide for the BOM Costing module (cost element master, item BOM master, BOM costing versions, cost sheet editor, standard rate card). Use when asked which BOM costing page does what, which backend endpoints a page uses, or how BOM statuses behave. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: BOM Costing (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read this:

- `../vowerp3ui/.claude/agents/module-bom-costing.md` (full agent body: page catalog, backend map,
  status notes — the module is small, everything is inline there)

Backend source in this repo: `src/bomcosting/` (`bomCosting.py`, `costElement.py`,
`stdRateCard.py`, shared `query.py`) plus `src/masters/itemBom.py`. Registered in `src/main.py` —
`/api/itemBomMaster` (line 155), `/api/bomCostElement`, `/api/bomCosting`, `/api/stdRateCard`
(lines 161-163). ORM models in `src/masters/models.py` (`BomHdr`, `CostElementMst`,
`BomCostEntry`, `StdRateCard`, `BomCostSnapshot`, `ItemBom`).

Domain design doc: `docs/bom_costing_db_instructions_1.md`. Migrations:
`dbqueries/migrations/create_bom_costing_tables.sql`, `item_bom.sql`,
`add_bom_status_to_item_bom_hdr_mst.sql`. No standard approval workflow — `status_id` is set to
21 on create and only changed via `bom_costing_update`; `bom_status` (New / Certified / Under
Development / Closed) is a free label with no transition rules.
