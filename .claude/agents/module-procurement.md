---
name: module-procurement
description: Cross-repo guide for the Procurement module (indent, purchase order, inward/GRN, material inspection, store receipt, bill pass, DR/CR note, reports). Use when asked which procurement page does what, which backend endpoints a page uses, or how procurement approval workflows behave. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Procurement (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-procurement.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/procurement/_index.md`
- `../vowerp3ui/docs/claude/modules/procurement/pages-01-indent-po-inward.md`
- `../vowerp3ui/docs/claude/modules/procurement/pages-02-inspection-sr-billpass-reports.md`
- `../vowerp3ui/docs/claude/modules/procurement/backend-map.md`
- `../vowerp3ui/docs/claude/modules/procurement/approval-flows.md`

Backend source in this repo: `src/procurement/` (`indent.py`, `po.py`, `inward.py`,
`material_inspection.py`, `sr.py`, `drcr_note.py`, `billpass.py`, `reports.py`), registered in
`src/main.py:165-172`. Deep-dive: `docs/procurement-inward-to-bill-pass-approval-flows.md`.
