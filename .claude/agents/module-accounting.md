---
name: module-accounting
description: Cross-repo guide for the Accounting module (vouchers, ledger groups, ledgers, voucher types, financial years, account determinations, auto-posting from bill pass/sales invoice, financial reports). Use when asked which accounting page does what, which backend endpoints a page uses, or how the voucher approval workflow behaves. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Accounting (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read these:

- `../vowerp3ui/.claude/agents/module-accounting.md` (the full agent body)
- `../vowerp3ui/docs/claude/modules/accounting/_index.md`
- `../vowerp3ui/docs/claude/modules/accounting/pages-01-vouchers-masters.md`
- `../vowerp3ui/docs/claude/modules/accounting/pages-02-reports.md`
- `../vowerp3ui/docs/claude/modules/accounting/backend-map.md`
- `../vowerp3ui/docs/claude/modules/accounting/approval-flows.md`

Backend source in this repo: `src/accounting/` (`routers.py`, `voucher_service.py`, `auto_post.py`,
`seed_data.py`, `query.py`, `report_query.py`, `models.py`, `constants.py`), registered in
`src/main.py:220` with prefix `/api/accounting`. Design spec: `docs/accounting-module-design.md`.
