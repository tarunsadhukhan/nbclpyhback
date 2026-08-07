---
name: module-sales
description: Cross-repo guide for the Sales module (quotation, sales order, delivery order, sales invoice, jute tally download, reports). Use when asked which sales page does what, which backend endpoints a page uses, or how sales approval workflows behave. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Sales (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-sales.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/sales/_index.md`
- `../vowerp3ui/docs/claude/modules/sales/pages-01-quotation-salesorder.md`
- `../vowerp3ui/docs/claude/modules/sales/pages-02-delivery-invoice-reports.md`
- `../vowerp3ui/docs/claude/modules/sales/backend-map.md`
- `../vowerp3ui/docs/claude/modules/sales/approval-flows.md`

Backend source in this repo: `src/sales/` (`quotation.py`, `salesOrder.py`, `deliveryOrder.py`,
`salesInvoice.py`, `reports.py`, `query.py`, `reportQueries.py`, `constants.py`,
`hessian_calculations.py`, `e_invoice_handler.py`), registered in `src/main.py:204-208`
(imports at `src/main.py:77-81`). Shared approval helpers: `src/common/approval_utils.py`.
