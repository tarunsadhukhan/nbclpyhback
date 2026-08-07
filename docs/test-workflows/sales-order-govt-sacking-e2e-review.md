# Sales Order — Govt Sacking E2E Test & Review Workflow

> **Purpose:** Reusable workflow for driving the Sales Order (Government Sacking / `invoice_type=5`) flow end-to-end on the dev environment using **chrome-devtools MCP**, with the goal of producing a structured defect report. This is the first of a series of page-level review workflows; the same shape applies to other pages (PO, Inward, Indent, Sales Invoice, etc.) — just swap the page-specific sections.
>
> **Mode:** Identify defects only — **no code fixes** are made by the agent during the run.
>
> **Originally drafted:** 2026-04-08 · plan id `dapper-fluttering-treasure`

---

## Context

Validate the **Sales Order → Govt Invoice (Government Sacking)** flow end-to-end on the running dev environment, using a browser-driving MCP so the agent can directly observe DOM, console, network, and identify issues.

This is the **first** of a series of pages to be reviewed under the same workflow (sales order today, more pages later). The output of this run is a structured **defect report** with file:line references so the user can triage. Backend (`vowerp3be`) and frontend (`vowerp3ui`) have already been mapped (see "Code Map" below). Govt Sacking is `invoice_type=5` with extension tables `sales_order_govtskg` (header) and `sales_order_govtskg_dtl` (line). All 5 govt_skg header fields are treated as **required** during validation review.

---

## Prerequisites (must be true before execution)

1. **chrome-devtools MCP enabled** — install/register the chrome-devtools MCP server and **fully restart Claude Code** so tools like `navigate_page`, `click`, `fill`, `take_screenshot`, `take_snapshot`, `list_console_messages`, `list_network_requests`, `get_network_request`, `evaluate_script` become available. Quick install:
   ```bash
   claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest
   ```
   Then close & reopen Claude Code, run `/mcp` to confirm `chrome-devtools` is connected. Requires Node.js 22+ and Chrome.
2. **Backend running** — `uvicorn src.main:app` up at the API URL the UI expects.
3. **Frontend running** — `vowerp3ui` dev server up at `dev3.localhost:3000`.
4. **Tenant DB** `dev3` reachable, with seed data for Empire company / Factory branch, user `user1@empirejute.com`, and item `3-002` (PRINTED TYPE A JUTE BAGS 580 GMS) marked saleable in `item_mst`.

---

## Test Credentials & Target Data

| Field | Value |
|-------|-------|
| URL | `http://dev3.localhost:3000` |
| User | `user1@empirejute.com` |
| Password | `vowjute@1234` |
| Company | Empire |
| Branch | Factory |
| Invoice type | Govt Sacking (`invoice_type=5`) |
| Item group | 3 — SACKING |
| Item | `3-002` — PRINTED TYPE A JUTE BAGS (580 GMS) WITH FOUR CONSECUTIVE RED WARP TREADS AS PER BIS SPEC NO.IS-16186:2014, 500 PCS |

---

## Code Map

### Backend — `vowerp3be (this repo)`

- Router: [src/sales/salesOrder.py](../../src/sales/salesOrder.py) — registered at `/api/salesOrder` in [src/main.py:173](../../src/main.py#L173)
- Queries: [src/sales/query.py](../../src/sales/query.py)
- Models: [src/models/sales.py](../../src/models/sales.py) — `SalesOrder`, `SalesOrderDtl`, `SalesOrderGovtSkg`, `SalesOrderGovtSkgDtl`
- Key endpoints:
  - `GET /api/salesOrder/get_sales_order_setup_1` — branches, customers, brokers, transporters, invoice_types, item_groups
  - `GET /api/salesOrder/get_sales_order_setup_2?item_group=3` — items in SACKING group
  - `POST /api/salesOrder/create_sales_order` — payload includes `invoice_type:5`, `govtskg:{...}`, `items[].govtskg_dtl:{...}`
  - Workflow: `open_sales_order`, `send_sales_order_for_approval`, `approve_sales_order`, `cancel_draft_sales_order`
- Govt SKG header insert: [src/sales/salesOrder.py:819-830](../../src/sales/salesOrder.py#L819-L830)
- Govt SKG line insert: [src/sales/salesOrder.py:780-790](../../src/sales/salesOrder.py#L780-L790)

### Frontend — `../vowerp3ui`

- List page: `src/app/dashboardportal/sales/salesOrder/page.tsx`
- Create page: `src/app/dashboardportal/sales/salesOrder/createSalesOrder/page.tsx`
- Header form: `createSalesOrder/components/SalesOrderHeaderForm.tsx`
- Govt SKG schema hook: `createSalesOrder/hooks/useSalesOrderGovtskgSchema.ts`
- Header schema: `createSalesOrder/hooks/useSalesOrderFormSchemas.tsx`
- Line items table: `createSalesOrder/components/SalesOrderLineItemsTable.tsx`
- Totals: `createSalesOrder/components/SalesOrderTotalsDisplay.tsx`
- Additional charges: `createSalesOrder/components/AdditionalChargesSection.tsx`
- Service layer: `src/utils/salesOrderService.ts`
- Invoice type detection (name-match, NOT id-match): `createSalesOrder/utils/salesOrderConstants.ts` — `isGovtSkgOrder()` matches names containing "govt", "sacking", or "skg"

---

## Test Workflow (chrome-devtools MCP driven)

The agent executes these steps using chrome-devtools MCP tools, capturing console messages, network requests, and DOM snapshots after every meaningful action. **No fixes are made**; defects are only logged.

### Stage 0 — Browser session setup
1. `new_page` → navigate to `http://dev3.localhost:3000`
2. `take_snapshot` to confirm the login page renders
3. Enable console + network capture (`list_console_messages`, `list_network_requests`)

### Stage 1 — Login
1. Fill `user1@empirejute.com` / `vowjute@1234` and submit
2. Wait for redirect to dashboard
3. **Check:** any console errors, any failed network calls (4xx/5xx), `access_token` cookie set
4. `take_screenshot` of post-login state

### Stage 2 — Company / Branch selection
1. Open the company switcher; confirm/select **Empire**
2. Open the branch switcher; confirm/select **Factory**
3. **Check:** `co_id` and `branch_id` propagate (read from cookie/storage via `evaluate_script`); confirm subsequent API calls carry these values

### Stage 3 — Navigate to Sales Order
1. Navigate via sidebar: Sales → Sales Order (or directly to `/dashboardportal/sales/salesOrder`)
2. Verify list loads (`GET /api/salesOrder/get_sales_order_table`)
3. Click **Create** → land on `/dashboardportal/sales/salesOrder/createSalesOrder?mode=create&branch_id=<id>`
4. Verify `GET /api/salesOrder/get_sales_order_setup_1` fires and returns invoice_types containing a "Govt Sacking" entry

### Stage 4 — Invoice type & header
1. In the **Invoice Type** dropdown, select the **Govt Sacking** option (whichever name matches `isGovtSkgOrder()`). Confirm govt_skg fields appear in the header form.
2. Take snapshot — record which govt_skg fields render, their labels, required-marker status, and input types.
3. **Check (per direction "all required"):** Verify each of the 5 govt_skg header fields is marked required and blocks submit when empty:
   - `govtskg_pcso_no`
   - `govtskg_pcso_date`
   - `govtskg_admin_office`
   - `govtskg_rail_head`
   - `govtskg_loading_point`
   - Log every field whose `required` flag is missing in the schema as a defect.
4. Fill all standard header fields (Date, Customer, Billing/Shipping, Transporter, Delivery Terms, Payment Terms, Delivery Days, Broker Commission %, Freight Charges, Expiry Date) and the 5 govt_skg fields with valid sample values. Snapshot after each.

### Stage 5 — Add Item
1. Click **Add Items** → confirm `ItemSelectionDialog` opens
2. In the dialog, filter to item group **3 — SACKING**, then locate `3-002 — PRINTED TYPE A JUTE BAGS (580 GMS)...`
3. **Check:** the network call `GET /api/salesOrder/get_sales_order_setup_2?item_group=3` fires; response contains item id for `3-002`
4. Select the item and confirm. Verify a new line is added to `SalesOrderLineItemsTable`
5. Fill quantity, UOM, rate. **Check** tax auto-recalc fires (`useSalesOrderTaxCalculations`) and CGST/SGST/IGST update
6. **Check** if any govt_skg per-line fields exist in the UI (`pack_sheet`, `net_weight`, `total_weight`) — backend expects these in `items[].govtskg_dtl`. Log as defect if UI does NOT expose them.

### Stage 6 — Footer
1. Fill **Additional Charges** rows (one freight, one misc) with rates and GST
2. Fill **Footer Note**, **Internal Note**, **Terms & Conditions**
3. Verify Totals panel (Gross, Tax, Freight, Additional, Net) updates correctly. Cross-check arithmetic against the line items.

### Stage 7 — Submit (Create as Draft)
1. Click **Save** / **Create**
2. Capture the `POST /api/salesOrder/create_sales_order` request payload (`get_network_request`) and response
3. **Check:** payload contains `invoice_type:5`, `govtskg:{...all 5 fields...}`, and each `items[].govtskg_dtl` (if backend requires)
4. **Check:** response status, returned `sales_order_id`, any error messages
5. If successful, capture the new SO id

### Stage 8 — Reload / Edit roundtrip
1. Navigate to the new SO via the list page
2. Open it in **edit** mode (`?mode=edit&id=<id>`)
3. **Check:** all header, govt_skg, line, additional charge, and footer fields populate exactly as submitted
4. **Check:** `GET /api/salesOrder/get_sales_order_by_id` response matches what the form re-renders (any field-mapping bug surfaces here)
5. Snapshot for comparison against Stage 6 state

### Stage 9 — Workflow transitions (only if Stage 7 succeeded)
> **Pause and ask the user before running this stage** — it writes durable state (status changes) to the dev DB.
1. Open Sales Order → expect status DRAFT(21)→OPEN(1); confirm doc number generated
2. Send for Approval → expect 1→20
3. Approve → expect 20→3 (single-level) or 20→20 (multi-level)
4. **Check:** each transition's network response and the UI status badge update

---

## Defect Report Structure (deliverable)

```
## Sales Order — Govt Sacking Test Report

### Environment
- URLs, user, company, branch, browser session id, timestamps

### Stage-by-stage results
For each stage 0–9:
- Status: PASS / PARTIAL / FAIL
- Screenshot reference
- Console messages observed (errors/warnings)
- Network calls (method, URL, status, latency)
- Defects found (each as a structured entry below)

### Defects
For each defect:
- ID: SO-GOVT-001, ...
- Severity: BLOCKER / HIGH / MEDIUM / LOW
- Stage: where it surfaced
- Symptom: what was observed
- Expected: what should have happened
- Evidence: console line / network req / screenshot
- Suspected cause: file:line ref in vowerp3be or vowerp3ui
- Suggested fix: short description (NOT applied)

### Coverage gaps
Anything that couldn't be tested and why (e.g. seed data missing, MCP limitation)
```

---

## Agent Team Composition

- **Driver agent (general-purpose, foreground)** — owns the chrome-devtools MCP browser session, executes the test stages sequentially, captures snapshots/network/console, and writes the running log.
- **Diagnosis agent (Explore, on-demand)** — when the driver hits an unexpected response/error, spawn an Explore agent with the exact symptom + relevant request payload + suspected file area to trace root cause to a `file:line`. This isolates investigation from the browser session and keeps the driver's context lean.
- **Report agent (general-purpose, end of run)** — consumes the driver's running log + diagnosis findings and emits the final structured defect report. Run only once at the end.

The driver must NOT make code edits; if it identifies a fix, it logs it as a defect entry and continues.

---

## Out of Scope

- No code changes (identify only)
- No git commits / PRs
- No DB writes outside the normal API flow (no manual `pymysql` inserts)
- No testing of other invoice types (Hessian, Jute, Jute Yarn) in this run
- No load / performance testing — functional only

---

## Verification of Workflow Execution

The run is "successful" when:
1. All 9 stages have been attempted (or skipped with documented reason)
2. A complete defect report exists in the chat output
3. Each defect has a file:line suspected cause
4. The user has enough information to triage fixes without re-running the browser session

---

## Adapting This Workflow to Other Pages

To reuse this template for another page (e.g. PO, Inward, Sales Invoice):

1. **Swap the Code Map section** — replace backend router/model/endpoint refs and frontend page/component refs with those of the target page.
2. **Swap Test Credentials & Target Data** — keep user/company/branch the same, change the page URL and any item/master data the test uses.
3. **Rewrite Stages 3–8** — same shape (navigate → header → add item → footer → submit → reload), but with the page's specific fields, dialogs, and endpoints.
4. **Keep Stages 0–2 and 9** as-is (login, switcher, workflow transitions follow the same pattern across pages).
5. **Keep the Defect Report Structure and Agent Team Composition unchanged** — same deliverable shape across all page reviews.
