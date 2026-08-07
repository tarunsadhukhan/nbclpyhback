# AMCL Enquiry-to-Delivery Flow — Design Document

**Status:** Phase 1 IMPLEMENTED (backend + frontend, branch `claude/focused-faraday-3xjo51` in both repos) — pending dev3 migration + menu seed + QA (see §9.1)
**Target tenant:** `dev3` (QA/dev), rollout to AMCL tenant after acceptance
**Repos:** `vowerp3be` (FastAPI backend) + `vowerp3ui` (Next.js frontend)
**Sources:** `AMCL_WORK_FLOW.docx` / `AMCL_WORK_FLOW.pptx` (customer-provided), user narrative (2026-07-06), and a verified audit of both repos (six module-mapping passes, 2026-07-06)

---

## 1. Purpose

AMCL (a machine manufacturer: assemblies, machining, milling, overhauling) needs the ERP to run
its complete order lifecycle:

> Enquiry received → Design & Costing reconfirm costing (optionally consulting Procurement on
> current prices) → back to Sales to quote, confirm delivery timeline and order → Design release →
> Production planning → Procurement → materials ready → Production executes → finished work handed
> back to Stores → packing → delivery → invoice → payment.

Two things are required that the system does not have today:

1. **Noting of a received enquiry** — the front door of the whole flow.
2. **Internal feedback passed between departments at every handoff**, with one place to see
   where each enquiry/order stands and which department it is waiting on.

This document specifies what will be built, what will be reused, the data model, endpoints,
pages, stage model, phasing, and open questions.

---

## 2. Verified current-state summary

### 2.1 What exists and will be reused

| Capability | Where | Notes |
|---|---|---|
| Quotation → Sales Order → Delivery Order → Invoice | `src/sales/` (`sales_quotation`, `sales_order`, `sales_delivery_order`, `sales_invoice` + `_dtl`/`_gst`) | Full 21→1→20→3/4/6 approval; SO traces to quotation line-by-line; fulfillment views (`vw_sales_order_outstanding` etc.) |
| Indent → PO → Inward → Inspection → Store Receipt → Bill Pass | `src/procurement/` | Full traceability (`indent_dtl_id` → `po_dtl_id` → `inward_dtl_id`); auto DR/CR notes on SR approval (qty rejection + rate difference) |
| Multi-level BOM (≤15 levels) + versioned cost sheets + cost snapshots + std rate card | `src/masters/itemBom.py`, `src/bomcosting/` (`item_bom`, `item_bom_hdr_mst`, `cost_element_mst`, `bom_cost_entry`, `bom_cost_snapshot`, `std_rate_card`) | Material/conversion/overhead element tree; snapshot `status` supports `approved` but nothing sets it yet |
| Stores issue with approval + lot traceability | `src/inventory/` (`issue_hdr`, `issue_li` → `inward_dtl_id`) | Stock availability views (`vw_approved_inward_qty`, `vw_item_balance_qty_by_branch_new`) already used by purchase before PO |
| Last purchase rate per item | `src/procurement/query.py::get_last_purchase_rates_by_item_group` | Feeds the PO item dropdown today; will feed the price-check step |
| Supplier price-enquiry (RFQ) schema | `proc_enquiry`, `proc_enquiry_dtl`, `proc_price_enquiry_response(_dtl)` | ORM only, no router/UI — dormant; Phase 3 activation candidate |
| Item master + group hierarchy + composed `full_item_code` | `src/masters/items.py`, `vw_item_with_group_path` | Group-path + item code joined by `-` structurally matches AMCL's `A-660-055-00-00` |
| Customers | `party_mst` (`party_type_id` contains 2) + `party_branch_mst` | No new customer master needed |
| Project grouping | `project_mst`; `project_id` already on `proc_indent`, `proc_po`, `issue_hdr` | Optional grouping key for one customer job |
| Approval hierarchy | `approval_mst` (per menu + branch + level) via `src/common/approval_utils.py`; configured in `dashboardadmin/approvalHierarchy` | Reused as-is for all new approval-bearing documents |

### 2.2 Verified gaps (why this design exists)

| # | Gap | Evidence |
|---|---|---|
| G1 | No customer enquiry / lead entity anywhere | Cross-repo search: zero hits (only the supplier-side `proc_enquiry` RFQ schema, dormant) |
| G2 | No cross-department handoff tracking or feedback trail | Only per-document free-text remarks; rejection `reason` is logged, **not stored** (`approval_utils.py::process_rejection`); header notification bell is hardcoded mock |
| G3 | Costing ↔ Sales disconnected | Quotation rates 100% manually typed; no margin/overhead concept; `bom_cost_snapshot.status='approved'` never set; no enquiry/quotation reference in costing |
| G4 | No Work Order / generic production planning | Zero hits for work order/job order/production order (only jute-specific production) |
| G5 | Indent "BOM" type is a label only | `src/procurement/` never references `item_bom`; no explosion, no stock netting |
| G6 | No Material Request document | `issue_hdr.req_by` is free text; stores issues directly |
| G7 | No finished-goods receipt / packing | No inbound stock movement except purchase inward + jute MR; stock views = purchased − issued; DO never touches stock |
| G8 | SO lacks committed delivery date + advance fields | Only `delivery_days` int + free-text terms |
| G9 | Inspection has no "repairable" disposition; PO has no tolerance/amendment versioning | Accept/reject qty split only; `clone_po` is the only amendment facility |
| G10 | AMCL item-code format not enforced/generated | Manual `item_code`, FE-only hyphen ban, no serial generation |

---

## 3. Architecture decision

**One umbrella entity — the Sales Enquiry — carries a stage tracker and feedback log across the
whole lifecycle.** Downstream steps stay what they already are (quotation, SO, indent, PO, issue,
…): real documents with their own approval workflows. The enquiry does not duplicate their data;
it references them. Each handoff between departments is a recorded **stage transition** carrying:

- from-stage → to-stage (and therefore from-department → to-department)
- the acting user + timestamp
- a **feedback note** (mandatory on send-backs)
- optionally the **linked document** created/advanced at that stage (quotation, SO, work order, indent, PO, issue, FG receipt)

A **Flow Board** page shows every open enquiry, its current stage, days-in-stage, pending
department, and latest feedback. Department worklists are **permission-driven**: each stage's
action page is a portal menu, so users see the stages their role can act on (`role_menu_map` +
`portal_permission_token` — no user→department mapping exists in `user_mst`, verified, and none is
added). `flow_stage_mst.dept_hint` is display metadata only.

The stage-log table is deliberately generic (`doc_type` + `doc_id`) so the same mechanism can
later track other flows without schema change.

---

## 4. Target stage model

Stage master seed (`flow_stage_mst`, `module='ENQUIRY'`, sequence gaps of 10):

| Seq | Code | Stage | Owning dept (display) | Phase |
|---|---|---|---|---|
| 10 | `ENQ_NOTED` | Enquiry Noted | Sales/Marketing | 1 |
| 20 | `COSTING_REVIEW` | Design & Costing Review | Design & Costing | 1 |
| 30 | `PRICE_CHECK` | Procurement Price Check *(optional — skippable)* | Purchase | 1 |
| 40 | `QUOTATION` | Quotation & Customer Follow-up | Sales/Marketing | 1 |
| 50 | `ORDER_CONFIRMED` | Order Confirmed (SO approved, delivery committed) | Sales/Marketing | 1 |
| 60 | `DESIGN_RELEASE` | Design Release / Work Order | Design | 2 |
| 70 | `PRODUCTION_PLANNING` | Production Planning (BOM → Indent) | PPC | 2 |
| 80 | `PROCUREMENT` | Procurement in Progress | Purchase | 2 |
| 90 | `MATERIAL_READY` | Materials Ready → Production Start | PPC | 2 |
| 100 | `PRODUCTION` | Production in Progress | Production | 2 |
| 110 | `FG_HANDOVER` | Finished Goods to Stores / Packing | Stores | 2 |
| 120 | `READY_FOR_DELIVERY` | Ready for Delivery | Stores → Sales | 2 |
| 130 | `CLOSED` | Closed (delivered / invoiced / paid) | — | 2 |
| — | `LOST` | Lost / Regret (terminal, reachable from any stage ≤ 50) | — | 1 |

**Transition actions** (server-enforced, constants in `src/sales/enquiry_constants.py`):

- `FORWARD` — to the next allowed stage (each stage declares its allowed next stages; `PRICE_CHECK` is in `COSTING_REVIEW`'s allowed set, and `QUOTATION` is reachable from both `COSTING_REVIEW` and `PRICE_CHECK`, which is what makes the price check skippable). `ORDER_CONFIRMED` is also reachable directly from `COSTING_REVIEW`/`PRICE_CHECK` — the **direct-order path** (customer PO / tender, no quotation; decision Q3).
- **Approval gate (decision Q4):** the enquiry itself runs the standard approval workflow (§5.1). `FORWARD` out of `ENQ_NOTED` into `COSTING_REVIEW` requires the enquiry to be **Approved (status 3)** — approval is the explicit signal that the enquiry moves up the chain; an enquiry closed/cancelled before approval means it is not being considered.
- `SEND_BACK` — to any earlier stage; **feedback text mandatory** (this is the "internal feedback" channel, e.g. costing sends an enquiry back to sales for missing specs).
- `HOLD` / `RESUME` — freezes stage; board shows held items distinctly.
- `MARK_LOST` — terminal before order confirmation, with reason.
- `CLOSE` — terminal at the end of the chain.

**Automatic transitions** (synchronous hooks, same DB transaction as the triggering action):

- Quotation linked to an enquiry reaches status 3 (Approved) → log entry with `linked_doc_type='QUOTATION'` (stage stays `QUOTATION` — quote sent to customer).
- Sales Order linked to the enquiry (via its quotation, or directly on the tender path) reaches status 3 → enquiry advances to `ORDER_CONFIRMED` automatically, linked `SALES_ORDER`.
- Phase 2 adds equivalent hooks: WO approved → `PRODUCTION_PLANNING`; indent approved → `PROCUREMENT`; all PO lines of the WO received (SR approved) → `MATERIAL_READY`; FG receipt approved → `FG_HANDOVER`; packing done → `READY_FOR_DELIVERY`; invoice approved → `CLOSED` candidate.
- Manual `move_stage` remains available at every point (auto transitions are conveniences, not gates).

---

## 5. Data model — Phase 1

All tables in the tenant DB (dev3 first). SQLAlchemy 2.0 `Mapped`/`mapped_column` style,
migrations under `dbqueries/migrations/` with rollback comments, executed via pymysql
(`run-migration` skill). Audit = `updated_by` + `updated_date_time` (history via DB triggers, per
repo convention — no `created_by`/`created_date` columns).

### 5.1 New tables

**`sales_enquiry`** (header)

| Column | Type | Notes |
|---|---|---|
| `sales_enquiry_id` | INT PK AI | |
| `enquiry_no` | VARCHAR(50) | Minted at open — prefix `ENQ`, per branch + financial year (same numbering helpers as SQ/SO) |
| `enquiry_date` | DATE | Date received |
| `received_via` | VARCHAR(20) | `email` / `phone` / `visit` / `tender` / `other` |
| `branch_id` | INT FK → `branch_mst` | Company scope derived via branch (matches sales tables — no `co_id`, consistent with `sales_quotation`) |
| `party_id` | INT FK → `party_mst` | Customer (`party_type_id` contains 2). Nullable at Draft for brand-new prospects; a party row is required before Open |
| `contact_person` | VARCHAR(255) | |
| `contact_detail` | VARCHAR(255) | Phone/email as given on the enquiry |
| `customer_ref_no` | VARCHAR(100) | Customer's enquiry / tender reference |
| `expected_delivery_date` | DATE NULL | Customer's asked-for date |
| `enquiry_desc` | VARCHAR(1000) | What the customer asked for, verbatim summary |
| `internal_note` | VARCHAR(1000) | |
| `current_stage_id` | INT FK → `flow_stage_mst` | Denormalized pointer for fast board queries (source of truth = latest `flow_stage_log` row) |
| `stage_since` | DATETIME | When the current stage was entered (drives aging) |
| `hold_flag` | INT default 0 | 1 = on hold |
| `status_id` | INT FK → `status_mst` | **Full standard approval lifecycle (decision Q4):** 21 Draft → 1 Open (noted) → 20 Pending Approval → 3 Approved / 4 Rejected; 21→6 cancel-draft; reopen 4→1, 6→21; 5 Closed at the end. Approval (3) is the gate into `COSTING_REVIEW` — it marks the enquiry as "being considered". Multi-level via `approval_level` + `approval_mst` (menu+branch), like every other transaction. "Lost" is `status_id=5` + `close_reason='lost'` + stage `LOST` |
| `approval_level` | INT default 0 | Standard approval-level counter within status 20 |
| `close_reason` | VARCHAR(20) NULL | `won` / `lost` / `cancelled` |
| `lost_remarks` | VARCHAR(500) NULL | |
| `project_id` | INT FK → `project_mst` NULL | Optional; suggested auto-create at `ORDER_CONFIRMED` (open question Q5) |
| `active`, `updated_by`, `updated_date_time` | | Standard |

**`sales_enquiry_dtl`** (lines — the enquired items)

| Column | Type | Notes |
|---|---|---|
| `enquiry_dtl_id` | INT PK AI | |
| `sales_enquiry_id` | INT FK | |
| `item_id` | INT FK → `item_mst` NULL | NULL when the item doesn't exist yet (new design) |
| `item_desc_freetext` | VARCHAR(500) | Mandatory when `item_id` is NULL |
| `is_new_item` | INT default 0 | 1 = design must create item + BOM |
| `design_change` | INT default 0 | 1 = existing item but design change requested |
| `qty` | DOUBLE | |
| `uom_id` | INT FK NULL | |
| `target_price` | DOUBLE NULL | Customer's target, if stated |
| `bom_hdr_id` | INT FK → `item_bom_hdr_mst` NULL | Set when costing confirms which BOM/costing version applies |
| `cost_snapshot_id` | INT FK → `bom_cost_snapshot` NULL | The **confirmed cost basis** written by the costing-confirm action |
| `confirmed_cost_per_unit` | DOUBLE NULL | Copied at confirmation (immutable evidence even if snapshot recomputed later) |
| `costing_confirmed_by` / `costing_confirmed_date` | INT / DATETIME NULL | |
| `remarks` | VARCHAR(500) | |
| `active` | INT default 1 | |

**`flow_stage_mst`** (stage master — seeded per §4)

| Column | Type |
|---|---|
| `stage_id` INT PK AI, `module` VARCHAR(30) (`'ENQUIRY'`), `stage_code` VARCHAR(30), `stage_name` VARCHAR(100), `dept_hint` VARCHAR(50) (display label; NOT an FK — dept_mst rows are tenant/branch-specific), `sequence_no` INT, `is_terminal` INT default 0, `active` INT default 1 |

Unique `(module, stage_code)`.

**`flow_stage_log`** (the handoff + feedback trail — generic by design)

| Column | Type | Notes |
|---|---|---|
| `stage_log_id` | BIGINT PK AI | |
| `doc_type` | VARCHAR(30) | `'SALES_ENQUIRY'` (only value in Phase 1) |
| `doc_id` | INT | `sales_enquiry_id` |
| `from_stage_id` | INT FK NULL | NULL on the creation entry |
| `to_stage_id` | INT FK | |
| `action` | VARCHAR(20) | `CREATE` / `FORWARD` / `SEND_BACK` / `HOLD` / `RESUME` / `MARK_LOST` / `CLOSE` / `AUTO` |
| `feedback` | VARCHAR(1000) | Mandatory when `action='SEND_BACK'`; encouraged elsewhere |
| `linked_doc_type` | VARCHAR(30) NULL | `QUOTATION` / `SALES_ORDER` / `PRICE_CHECK` / (Phase 2: `WORK_ORDER` / `INDENT` / `PO` / `MATERIAL_REQUEST` / `ISSUE` / `FG_RECEIPT` / `DELIVERY_ORDER` / `INVOICE`) |
| `linked_doc_id` | INT NULL | |
| `action_by` | INT | user_id |
| `action_date_time` | DATETIME | |

Index `(doc_type, doc_id, stage_log_id)`.

**`enquiry_price_check`** (Design/Costing → Procurement pricing consult; internal, lightweight)

| Column | Type | Notes |
|---|---|---|
| `price_check_id` | INT PK AI | |
| `sales_enquiry_id` | INT FK | |
| `request_note` | VARCHAR(500) | What costing wants checked |
| `pc_status` | VARCHAR(20) | `pending` / `responded` / `cancelled` |
| `requested_by` / `requested_date_time` | | |
| `responded_by` / `responded_date_time` | | |
| `response_note` | VARCHAR(500) | Procurement's overall feedback |
| `active`, `updated_by`, `updated_date_time` | | |

**`enquiry_price_check_dtl`**

| Column | Type | Notes |
|---|---|---|
| `price_check_dtl_id` | INT PK AI | |
| `price_check_id` | INT FK | |
| `enquiry_dtl_id` | INT FK NULL | Link to the enquiry line, when applicable |
| `item_id` | INT FK | |
| `last_po_rate` / `last_po_date` / `last_supplier_id` | DOUBLE / DATE / INT NULL | **Auto-prefilled at request time** from `get_last_purchase_rates_by_item_group` (snapshot, so the answer is evidence-stable) |
| `confirmed_rate` | DOUBLE NULL | Procurement's answer |
| `rate_source` | VARCHAR(20) | `last_po` / `supplier_quote` / `estimate` |
| `supplier_id` | INT FK → `party_mst` NULL | If a specific supplier was consulted |
| `remarks` | VARCHAR(500) | |

*(Phase 3 may escalate a price check into a formal supplier RFQ by activating the dormant
`proc_enquiry` chain; `rate_source='supplier_quote'` is the seam.)*

**`co_menu_iso_map`** (ISO document numbers — decision Q2/Q7; generic and reusable across all
modules and tenants, not AMCL-specific)

| Column | Type | Notes |
|---|---|---|
| `iso_map_id` | INT PK AI | |
| `co_id` | INT FK → `co_mst` | Per company |
| `menu_id` | INT FK → `menu_mst` | The document type (each transaction type is a menu) |
| `iso_doc_no` | VARCHAR(50) | The company's ISO document number for that document type |
| `active`, `updated_by`, `updated_date_time` | | Standard |

Unique `(co_id, menu_id)`. Behavior: document view/print headers look up the map by the page's
`menu_id` + selected `co_id` — **if a row exists the ISO number is shown; if not, the space stays
blank**. Maintained via a small master page (CRUD). Rendering starts with the new enquiry pages +
quotation/SO prints and extends to other documents as their print templates are touched (the
lookup is one shared helper on both BE and FE).

### 5.2 Alterations to existing tables

| Table | Change | Purpose |
|---|---|---|
| `sales_quotation` | ADD `sales_enquiry_id` INT NULL (FK) | Quote traces to enquiry |
| `sales_quotation_dtl` | ADD `enquiry_dtl_id` INT NULL, `cost_snapshot_id` INT NULL, `base_cost` DOUBLE NULL, `overhead_pct` DOUBLE NULL, `margin_pct` DOUBLE NULL | Auto-pricing: `rate` prefilled = `base_cost × (1 + overhead_pct/100) × (1 + margin_pct/100)`, editable; cost basis stays recorded on the quote line |
| `sales_order` | ADD `committed_delivery_date` DATE NULL, `advance_amount` DOUBLE NULL, `advance_note` VARCHAR(255) NULL, `sales_enquiry_id` INT NULL (FK) | G8 + decision Q3: an order can arrive **without** a quotation (customer PO / tender), created directly from the enquiry — hence the SO carries its own enquiry link. (Recording actual advance receipt = accounting scope, out of Phase 1; these fields capture the commercial commitment) |
| `item_bom_hdr_mst` | ADD `cost_basis_qty` DOUBLE default 1 | Fixes the verified defect that `bom_cost_snapshot.cost_per_unit` is just `total_cost` (no output-qty divisor, `bomCosting.py` rollup). Rollup divides by this |
| `bom_cost_snapshot` | No DDL — start **using** `status='approved'` | Costing-confirm action sets it (today only `draft`/`superseded` are ever written) |

Every migration ships with rollback SQL and a paired ORM update (`migration-writer` conventions).

---

## 6. Backend — Phase 1

New router `src/sales/enquiry.py` → prefix **`/api/salesEnquiry`** (registered in `src/main.py`);
constants in `src/sales/enquiry_constants.py`; queries in `src/sales/query.py` (or
`enquiry_query.py` if it grows). Persona: **Portal** → `Depends(get_tenant_db)` +
`get_current_user_with_refresh`; responses `{"data": ..., "master": ...}`; `co_id`/`branch_id`
honored on every list query.

| Endpoint | Method | Behavior |
|---|---|---|
| `/get_enquiry_table` | GET | Paginated list; filters: stage, status, party, date range, search |
| `/get_enquiry_board` | GET | Rows grouped per stage with days-in-stage (from `stage_since`), hold flag, latest feedback snippet, linked-doc summary — powers the Flow Board |
| `/get_enquiry_setup` | GET | Customers (party type 2), UOMs, items (+ groups), stage master, received-via options |
| `/get_enquiry_by_id` | GET | Header + lines + full `flow_stage_log` timeline + linked docs (quotation/SO refs) + permissions block (menu_id pattern, as sales does) |
| `/create_enquiry` / `/update_enquiry` | POST / PUT | Draft (21) only; Zod-validated payload FE-side, param validation BE-side |
| `/open_enquiry` | POST | 21→1; mints `ENQ-…` number; stage → `ENQ_NOTED`; writes `CREATE` log entry |
| `/cancel_draft_enquiry` | POST | 21→6 |
| `/send_enquiry_for_approval` | POST | 1→20 (level 1) — standard workflow via `process_approval` (decision Q4) |
| `/approve_enquiry` | POST | 20→20 (next level) or 20→3; on final approval the enquiry becomes eligible to `FORWARD` into `COSTING_REVIEW` |
| `/reject_enquiry` | POST | 20→4 with `reason` — **persisted into `flow_stage_log.feedback`** (fixing the repo-wide "reason logged but not stored" gap for this document) |
| `/reopen_enquiry` | POST | 4→1, 6→21 |
| `/move_stage` | POST | `{action, to_stage_id?, feedback?, linked_doc_type?, linked_doc_id?}`; validates the transition against the allowed-next map; enforces mandatory feedback on `SEND_BACK`; updates `current_stage_id` + `stage_since` + appends log — all in one transaction |
| `/close_enquiry` | POST | `{close_reason, remarks}`; stage → `CLOSED`/`LOST`; status → 5 |
| `/confirm_line_costing` | POST | `{enquiry_dtl_id, bom_hdr_id}` → runs/validates rollup for that header, marks its current `bom_cost_snapshot.status='approved'`, writes `cost_snapshot_id` + `confirmed_cost_per_unit` + confirmer onto the line. Requires stage ∈ {`COSTING_REVIEW`, `PRICE_CHECK`} |
| `/create_price_check` | POST | Creates header+details; **prefills** `last_po_rate`/`last_po_date`/`last_supplier_id` per item; moves stage to `PRICE_CHECK` with log |
| `/get_price_check_pending_list` | GET | Procurement worklist |
| `/get_price_check_by_id` | GET | |
| `/respond_price_check` | POST | Writes confirmed rates + notes, sets `responded`; moves enquiry back to `COSTING_REVIEW` with the response note as feedback |

**Touch-points in existing routers (small, surgical):**

- `src/sales/quotation.py`: `get_quotation_setup_*` accepts `sales_enquiry_id` → returns enquiry
  lines with confirmed cost basis; `create_quotation` persists `sales_enquiry_id` + per-line
  `enquiry_dtl_id`/`cost_snapshot_id`/`base_cost`/`overhead_pct`/`margin_pct`; `approve_quotation`
  post-approval hook appends an `AUTO` log entry on the linked enquiry.
- `src/sales/salesOrder.py`: `create_sales_order` accepts the new header fields (including
  `sales_enquiry_id` for the direct/tender path — a "From Enquiry" setup mirrors the existing
  "from quotation" pattern, pulling enquiry lines with their confirmed cost basis);
  `approve_sales_order` hook advances the linked enquiry (own `sales_enquiry_id`, else via
  `quotation_id`) to `ORDER_CONFIRMED`.
- New small master router `src/masters/isoMenuMap.py` → `/api/isoMenuMap`
  (`get_iso_map_table`, `iso_map_save`, `iso_map_delete`) + a shared lookup used by document
  `get_*_by_id`/print endpoints to return `iso_doc_no` for the page's `menu_id` + `co_id`.
- `src/bomcosting/bomCosting.py`: rollup divides by `item_bom_hdr_mst.cost_basis_qty`; add
  `snapshot_approve` (or fold into `/confirm_line_costing` — implementation choice at build time).

**Tests** (pytest, mocked DB/auth per repo pattern): stage-transition matrix (legal/illegal moves,
mandatory feedback on send-back), open/numbering, costing-confirm writes, price-check prefill,
quotation/SO hooks, and the standard 400-on-missing-params suite.

---

## 7. Frontend — Phase 1

All Portal (`dashboardportal`), honoring `SidebarContext` company/branch on every call. Zod
schemas for all forms; theme tokens; types per module in one file.

| Page | Path | What it shows |
|---|---|---|
| Enquiry list | `src/app/dashboardportal/sales/enquiry/page.tsx` | Grid: enquiry no, date, customer, stage chip, days-in-stage, status; row actions |
| Enquiry create/edit/view | `sales/enquiry/createEnquiry/page.tsx` (+ `_components/`, `hooks/`, `types/`, `utils/`) | Header + lines (existing-item picker OR free-text new-item rows with `is_new_item`/`design_change` flags); Draft→Open actions |
| **Flow Board** | `sales/enquiry/board/page.tsx` | Kanban-style columns per stage (or grouped grid); cards show customer, value-so-far, aging, hold badge, pending dept, latest feedback; click-through to the enquiry |
| Enquiry detail — **Flow Timeline** | inside view page | Vertical timeline of `flow_stage_log`: stage → stage, who, when, feedback, linked-doc chips (click-through to quotation/SO); `MoveStageDialog` (action, target stage, feedback textarea — required on send-back) |
| Costing Review worklist | `BomCosting/costingReview/page.tsx` | Enquiries in `COSTING_REVIEW`; per line: open cost sheet (existing costSheet page), **Confirm costing** action, **Raise price check** action, send-back-to-sales with feedback |
| Price Check worklist | `procurement/priceCheck/page.tsx` | Pending checks; response form with prefilled last-PO rate columns |
| Quotation create (extension) | existing `sales/quotation/createQuotation/` | "From Enquiry" source selector → lines arrive with `base_cost` locked-in; margin % + overhead % columns compute `rate` (editable); cost basis shown |
| Sales Order create (extension) | existing `sales/salesOrder/createSalesOrder/` | Committed delivery date + advance amount/note fields; **"From Enquiry" source selector** for the direct/tender path (no quotation) |
| ISO Document No master | `masters/isoDocMap/page.tsx` | Small CRUD grid: menu (document type) → ISO number, per company; shared header helper renders the number on document views/prints, blank when unmapped |

Service layer: `src/utils/enquiryService.ts`; route constants added to `apiRoutes` in
`src/utils/api.ts`. Shared components reused: **`ApprovalActionsBar`** on the enquiry create/view
page (decision Q4 — standard bar, `useEnquiryApproval` hook, same wrapper pattern as
`QuotationApprovalBar`), plus `TransactionWrapper`, DataGrid patterns, `useDeferredOptionCache`.
The tenant admin's Approval Hierarchy page configures enquiry approvers (`approval_mst` rows for
the new enquiry menu).

**Menus** (via the `add-menu` process — `portal_menu_mst` template + `menu_mst` + `role_menu_map`
on dev3): Sales → *Customer Enquiry*, *Enquiry Flow Board*; BOM Costing → *Costing Review*;
Procurement → *Price Check*. Worklist visibility = menu permission (view/create/edit), which is
how "department" scoping is achieved without a user→dept mapping.

---

## 8. Phase 2 — Execution leg (design sketch; detailed after Phase 1 sign-off)

1. **Work Order** — `work_order` (`wo_no` `WO-…`, `sales_order_id`, `branch_id`, `wo_type`
   `design`/`production`, `target_date`, `status_id`+`approval_level` full workflow) +
   `work_order_dtl` (`sales_order_dtl_id`, `item_id`, `bom_hdr_id`, `qty`, `remarks`). Issued
   against an approved SO; routes to Design (new item → item+BOM creation via existing pages,
   then release) or straight to PPC for repeat items — exactly the AMCL doc's rule.
2. **BOM → Indent explosion** — endpoint that recursively explodes `item_bom` for WO lines
   (depth-capped like `build_bom_tree`), classifies children by `item_mst` flags
   (`purchaseable` → buy; `manufacturable`/`assembly` → make; leaf raw material → buy), nets
   against `vw_item_balance_qty_by_branch_new.cur_stock`, and drafts a `proc_indent`
   (`indent_type_id='BOM'` becomes real) with `work_order_id` (new column) — **selective**: PPC
   unticks/edits lines before saving, per the AMCL doc ("Create Indent Based on BOM (Selective)").
   Subcontract-vs-buy-vs-supply-material split is modeled as a per-line `procure_mode` on the
   explosion result (see Q6).
3. **Material Request** — `material_request`(+`_dtl`) from PPC to Stores (full approval
   lifecycle); `issue_li` gains `mat_req_dtl_id` so the existing stores issue is created *from* an
   approved MR with requested-vs-issued reconciliation (replaces free-text `req_by`).
4. **FG Receipt** — `fg_receipt`(+`_dtl`): production hands finished goods back to stores
   (`work_order_id`, `warehouse_id`, qty, approval). New stock view unions FG receipts into item
   balances (today's views only know purchase inward); packing flags (`packed`, `packed_date`)
   drive `READY_FOR_DELIVERY`. The dormant `proc_transfer` model is the schema seed to evaluate
   first.
5. **Stage hooks** — WO/indent/SR/FG events advance the enquiry automatically (§4); DO + invoice
   close it.

## Phase 3 — Refinements (backlog)

- Activate supplier RFQ (`proc_enquiry` chain) for formal price checks with supplier responses.
- Inspection **repairable** disposition (`repairable_qty` + negotiation state on
  `proc_inward_dtl`; DR/CR generation unchanged for rejects) — G9.
- PO line `tolerance_pct` (inward validation allows `bal_po_qty × (1 + tol)`) + PO amendment
  numbering on top of `clone_po` — G9/AMCL "Required Qty with Tolerance".
- AMCL item-code scheme: seed `item_type_master` A/B/C, group levels for division (660) + model
  (055), serial auto-suggest per group, format validator FE+BE (today the hyphen rule is FE-only
  and bulk/edit paths bypass it) — G10.
- Real notifications: replace the mock bell with a worklist-count endpoint; optional email later.
- Reports: enquiry register, enquiry-to-order conversion, stage-aging, customer order status.
- Extend ISO document-number rendering (`co_menu_iso_map`, built in Phase 1) to the remaining
  document print templates beyond the sales/enquiry chain.

---

## 9. Rollout

1. Build + migrate on **dev3**; seed `flow_stage_mst`; add menus for the QA roles.
2. QA with the `portal-ui-flow-tester` agent: full happy path (note enquiry → costing confirm →
   price check → quote → SO) + send-backs, holds, lost, and invalid-input probes.
3. When AMCL's tenant is provisioned/identified: `tenant-schema-check` vs dev3, then migrate,
   seed stages/menus, configure `approval_mst` levels for quotation/SO per AMCL's hierarchy.

---

### 9.1 Phase 1 deployment run-book (dev3)

The build machine had no route to the dev3 MySQL host, so these steps run from a machine that does
(the usual dev setup):

1. Pull `claude/focused-faraday-3xjo51` in both repos.
2. Apply `dbqueries/migrations/create_amcl_enquiry_flow_phase1.sql` to **dev3** via the
   `run-migration` skill (pymysql; credentials from `env/database.env`). Re-runnable — guarded
   CREATE/ALTERs; seeds the 14 `flow_stage_mst` rows.
3. Apply `dbqueries/migrations/seed_amcl_enquiry_menus.sql` to **dev3**, then run the verification
   queries at the bottom of that file — the inserts are silent no-ops if a sibling anchor menu was
   not found, in which case add the menu row manually with an explicit parent. Grants only role 1;
   give the costing/procurement/sales operating roles access via the Portal admin UI.
4. The commented `vowconsole3.portal_menu_mst` template block in the same file needs a separate,
   explicitly confirmed run against vowconsole3 (system DB — do not run casually).
5. In `dashboardadmin → approvalHierarchy`, configure `approval_mst` levels for the new
   **Customer Enquiry** menu (decision Q4 — approval gates the move into costing review).
6. Restart the backend (new routers `/api/salesEnquiry`, `/api/isoMenuMap`); deploy the UI build.
7. QA the happy path on dev3 (note → approve → costing confirm → price check round-trip → quote
   from enquiry → SO approve advances the enquiry + auto-creates the project), plus send-backs,
   hold/resume, and mark-lost. The `portal-ui-flow-tester` agent covers this when run from a
   machine with DB + browser access.

Verification already done at build time: 163 new backend tests (full suite zero regressions vs
baseline), `npx tsc --noEmit` clean, production `pnpm build` green.

## 10. Resolved decisions (user, 2026-07-06)

| # | Question | Decision |
|---|---|---|
| Q1 | Margin/overhead for auto-pricing | **Entered per quote** — line-level manual %, no config master |
| Q2 | Departments for stage display (`dept_hint`) | **Yes** — AMCL names seeded as labels; roles/menus control who acts |
| Q3 | Sales order without a quotation (tender / direct customer PO)? | **Yes, it may** — SO can be made directly from the enquiry; `sales_order.sales_enquiry_id` added, `QUOTATION` stage skippable |
| Q4 | Approval on the enquiry itself? | **Yes** — full standard approval workflow; approval = the signal it moves up the chain; an enquiry closed before approval means it is not being considered |
| Q5 | Auto-create a `project_mst` row at `ORDER_CONFIRMED`? | **Yes** |
| Q6 | Subcontracting / job-work | **Phase 2** — per-line `procure_mode` flag; full job-work module deferred |
| Q7 | ISO Document No | **Covered by Q2 answer** — new reusable `co_menu_iso_map` table (company × menu → ISO number); shown when entered, blank otherwise; built in **Phase 1**, extended to remaining prints in Phase 3 |
| Q8 | Overhauling / part-assembly via the same enquiry flow? | **Yes** — modeled as assembly-type lines |

---

## 11. Traceability: requirement → design element

| AMCL/user requirement | Design element |
|---|---|
| "Noting of an enquiry which is received" | `sales_enquiry`(+`_dtl`), `open_enquiry`, Enquiry pages |
| "Design and costing team reconfirm the costing" | `COSTING_REVIEW` stage, Costing Review worklist, `confirm_line_costing`, snapshot `approved` |
| "May need to speak to procurement to reconfirm pricing — or may not" | Optional `PRICE_CHECK` stage + `enquiry_price_check` with last-PO prefill; skippable transition |
| "Back to sales who confirm delivery timeline and order" | `QUOTATION`/`ORDER_CONFIRMED` stages; auto-priced quotation; SO `committed_delivery_date` + advance fields |
| "Back to design, then production, then procurement" | Phase 2: Work Order → PPC → BOM-indent → existing procurement chain |
| "Procurement informs production planning when procured" | Auto stage hook on SR approval → `MATERIAL_READY` + feedback log |
| "Production takes material and finishes work" | Material Request → existing stores issue → `PRODUCTION` stage |
| "Hand it back to stores" | FG Receipt + packing → `READY_FOR_DELIVERY` |
| "Pass on internal feedback to manage the full flow" | `flow_stage_log` feedback on every transition (mandatory on send-backs), Flow Timeline UI, Flow Board, permission-driven worklists |
| "Every document having an ISO Document No" | `co_menu_iso_map` (company × menu → ISO number), rendered on document views/prints when mapped |
| Order received directly against customer PO / tender | SO "From Enquiry" path (`sales_order.sales_enquiry_id`), quotation stage skippable |
