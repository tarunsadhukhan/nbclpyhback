---
name: module-inventory
description: Cross-repo guide for the Inventory module (material issue from stores, inventory stock / issue-itemwise reports). Use when asked which inventory page does what, which backend endpoints a page uses, or how the issue approval workflow behaves. Covers vowerp3ui pages and vowerp3be routers.
tools: Read, Grep, Glob
---

# Module Guide: Inventory (pointer)

Last verified: 2026-06-12

The full guide lives in the sibling frontend repo — read this:

- `../vowerp3ui/.claude/agents/module-inventory.md` (full agent body, inline page catalog,
  backend map, issue lifecycle state diagram)

Backend source in this repo: `src/inventory/` (`issue.py`, `reports.py`, `query.py`,
`reportQueries.py`, `models.py`), registered in `src/main.py:200-201` as `/api/inventoryIssue`
and `/api/inventoryReports`. Canonical ORM models: `src/models/inventory.py` (`IssueHdr`,
`IssueLi`, `VwApprovedInwardQty`). Issue traces to procurement inward via
`issue_li.inward_dtl_id`; approval lifecycle runs through `PUT /update_issue_status/{issue_id}`
using `src/common/approval_utils.py` (see
`dbqueries/migrations/add_approval_level_to_issue_hdr.sql`).
