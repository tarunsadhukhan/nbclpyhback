# Accounting Module — Gap Analysis & Cross-Module Integration Plan

**Date:** 2026-07-12
**Status:** Analysis — findings verified against source in both repos
**Companion doc:** `docs/accounting-module-design.md` (the original design spec; this doc records what was actually built vs. that spec, and how to close the distance)
**Frontend summary:** `../vowerp3ui/docs/claude/modules/accounting/gap-analysis.md`

**Scope of this analysis:** the accounting module itself, plus its (intended) connections to the three purchase/sales modules — **Procurement**, **Jute Purchase**, and **Sales** — with focus on the three business outcomes that matter most:

1. **Payments pending** (accounts payable — who do we owe, how much, by when)
2. **Payments receivable** (accounts receivable — who owes us, how much, by when)
3. **Easy expense booking**

…and on making the behavior **configurable per company**, since each company functions slightly differently.

---

## 1. Executive Summary

**What exists:** Accounting Phase 1 is genuinely built — 15 `acc_*` tables (chart of accounts, voucher types, financial years, account determination, vouchers/lines/GST, bill refs, settlements, opening bills), 34 endpoints at `/api/accounting`, 15 frontend pages, per-company activation seeding, and three ready-written auto-posting functions for procurement bill pass, jute bill pass, and sales invoice. The architecture (Tally-style vouchers + SAP-style account determination, balances always computed, `co_id`-scoped everything) is sound and is the right foundation.

**What's wrong, in one sentence:** the accounting module is an island whose bridges were built but never connected, and whose own internal write path is broken against its own schema.

Five headline findings:

1. **Nothing posts to accounting.** Not one business event (procurement bill pass, jute bill pass, sales invoice approval, DR/CR note, payroll) calls into accounting. The three `auto_post_*` functions have **zero callers** (`grep auto_post src/` → only tests). The de-facto accounting integration today is the **manual Tally xlsx export** (jute purchase + raw-jute sales), with hardcoded ledger names and a hardcoded 180-day credit term.

2. **Two incompatible schema dialects inside `src/accounting/`.** The DDL (`dbqueries/migrations/create_accounting_phase1.sql`) matches `models.py`, `query.py`, `seed_data.py`, and the masters endpoints. But `voucher_service.py`, `auto_post.py`, the AP/AR report queries, and the opening-bills endpoint are written against a **phantom schema** (`acc_fy_id`, `voucher_seq`, `debit_amount`/`credit_amount`, `acc_bill_ref.co_id/party_id/pending_amount`, tables `acc_financial_period`/`acc_approval_mst`) that **no migration creates**. If the deployed DB matches the committed DDL, every voucher save/approve/settle call and the party-outstanding/ageing reports fail with unknown-column errors.

3. **The auto-post functions are also wrong about the source modules.** They select columns that don't exist on `proc_inward` (`co_id`, `taxable_amount`), `jute_mr` (`co_id`, `mr_id`, `mr_date`, `mr_no`), and `sales_invoice` (`co_id`, `sales_invoice_id`, `net_amount`, `round_off_value`) — and they look up account-determination `line_type` values (`PURCHASE`, `JUTE_PURCHASE`, `SALES`, …) that the seeder never inserts (it seeds `MATERIAL`, `REVENUE`, `TDS`, …). Four independent failures stand between "wired" and "working".

4. **Payables/receivables are structurally present but functionally empty.** `acc_bill_ref` + `acc_bill_settlement` + `/settle_bills` + party-outstanding/ageing reports exist — but nothing ever writes a bill ref (manual voucher creation ignores the FE's `bill_refs` array; auto-post is unwired), there is **no payment/receipt entry UX** beyond the generic voucher form (which cannot currently save due to FE↔BE payload mismatches), no allocation UI, no advance lifecycle, no bank/instrument capture, and no due-date derivation from credit terms. Meanwhile the business modules track **no payment state at all** — procurement/jute/sales have due-date fields (manually keyed) and nothing else.

5. **Expense booking does not exist.** No expense entry flow, no expense-category master, no `EXPENSE` doc type in account determination. The only path is a manual Journal/Payment voucher against a manually created ledger — and that form is currently broken.

**Per-company dynamism:** `acc_account_determination` (per `co_id` × doc_type × line_type → ledger) is the right mechanism and is already seeded and editable. What's missing is (a) a **per-company accounting settings** table governing *how* posting behaves (auto vs. draft-for-review vs. off, due-date rules, ageing buckets, FY convention, TDS/TCS switches), and (b) richer determination resolution (item-group/branch overrides — the column exists, the lookup ignores it). The existing `co_config` table (`india_gst`, `india_tds`, `india_tcs`, …) is the established pattern to follow and link to.

**Recommended order of attack:** repair the foundation first (schema dialect decision + rewrite of the write path + FE contract fixes), then wire posting through a **config-driven, failure-isolated posting service** (business approvals must never fail because accounting hiccuped), then build the payables/receivables workspaces and the expense entry page on top. Details in §5–§7.

---

## 2. Current State — What Exists

### 2.1 Backend (`src/accounting/`, router at `/api/accounting`, registered `src/main.py:301`)

| Area | Status |
|---|---|
| Masters: ledger groups, ledgers, voucher types (read-only), financial years, account determinations, parties dropdown | ✅ Working (ORM-dialect SQL, matches DDL) |
| `POST /activate_company` seeding (28 groups, 18 system ledgers, 8 voucher types, party ledgers, 21 determination rules, FY + 12 period locks, numbering rows) | ✅ Works, with two seed defects (§3.1 A4, A5) |
| Voucher list / voucher detail (`GET /vouchers`, `GET /vouchers/{id}`) | ✅ Working (no total count for pagination) |
| Voucher create/update/open/cancel/send/approve/reject/reopen/reverse, `/settle_bills`, `POST /opening_bills` | ❌ **Broken** — phantom-dialect SQL (§3.1 A1) |
| Reports: trial balance, P&L, balance sheet, ledger, day book, cash book | ✅ Working (BE side; balance sheet FE sends wrong params) |
| Reports: party outstanding, ageing analysis | ❌ Broken (phantom `acc_bill_ref` columns) — and empty by construction (nothing writes bill refs) |
| Report: GST summary | ✅ BE exists; no FE page; would return nothing (no GST rows ever written) |
| Auto-posting: `auto_post_procurement_billpass` (:293), `auto_post_jute_billpass` (:493), `auto_post_sales_invoice` (:694) in `auto_post.py` | ❌ Built, **never called**, and broken on 4 axes (§3.2) |

### 2.2 Frontend (`src/app/dashboardportal/accounting/` in vowerp3ui)

15 pages: voucher list + create/edit/view, voucher types, ledgers, ledger groups, financial years, account determinations, and 8 report pages. Service layer `src/utils/accountingService.ts`, routes `ACC_*` in `src/utils/api.ts:681-719`.

Unused service functions (no page calls them): `activateCompany`, `importOpeningBills`, `settleBills`, `fetchGstSummary`. No pages exist for: payment/receipt entry, bill settlement, opening-bill import, GST summary, expense entry, settings/activation.

### 2.3 What the business modules carry today (financial data available for posting)

| Module | Payable/receivable document | Financial completeness | Payment state |
|---|---|---|---|
| **Procurement** | Bill Pass = computed view over `proc_inward` (+dtl +`proc_gst` +additional +DR/CR notes). `net_payable` computed per-request in `src/procurement/query.py:2462` (list) and `:2590` (detail) — **two different formulas**; never persisted | Full GST split available in `proc_gst` (`c_tax_amount`/`s_tax_amount`/`i_tax_amount`); DR/CR notes with own GST table (different column names: `cgst_amount`…) | **None.** `invoice_due_date` manually keyed; PO `credit_days`/`advance_*` fields dead-end after PO print; `proc_tds` table exists with no read/write path |
| **Jute Purchase** | Bill Pass = columns on `jute_mr` (status 3). `total_amount`, `claim_amount`, `tds_amount` (194Q auto-computed at MR approval), `roundoff`, `net_total`, `frieght_paid` | Complete — every number a purchase voucher needs is persisted at MR approval. ⚠️ `net_total` semantics conflict: BE = `total − claim + roundoff` (`mr.py:1481`), FE bill-pass editor deducts TDS too (`billPass/edit/page.tsx:260`) | **None.** `payment_due_date` manually keyed; no paid/advance/settlement state; brokerage columns on `jute_po` never written by API or FE |
| **Sales** | Sales Invoice (`sales_invoice` + dtl + dtl_gst + additional + type-specific extensions). `invoice_amount`, `tax_amount`, `round_off`, `due_date`, `payment_terms` (int days, free-form) | Complete GST split per line; header totals trusted from FE payload (not recomputed server-side) | **None.** No receipts, no outstanding-amount tracking; qty-only outstanding views (`vw_sales_*`); TCS deliberately removed; no customer credit-note document |

All three modules reference `party_mst` — which itself has **no financial fields** (no credit limit/days, no opening balance, no bank details, no ledger link). Credit terms exist only on `acc_ledger.credit_days/credit_limit`, populated only when a party ledger is created, used by nothing.

---

## 3. Gap Register

Findings are grouped: **A** foundation defects (block everything), **B** integration gaps (auto-posting), **C** payables/receivables, **D** expense booking, **E** configurability. Evidence given as `file:line` in vowerp3be unless prefixed `FE:` (vowerp3ui).

### 3.1 A — Foundation defects (must fix before anything is built on top)

| # | Gap | Evidence | Impact |
|---|---|---|---|
| A1 | **Two schema dialects.** `voucher_service.py`, `auto_post.py`, `report_query.get_party_outstanding`/`get_ageing_analysis`, and `POST /opening_bills` use phantom columns/tables (`acc_fy_id`, `fy_start_date`, `voucher_seq`, `debit_amount`/`credit_amount`, `line_no`, `voucher_prefix`, `action_date`, `acc_bill_ref.co_id/party_id/total_amount/pending_amount`, `acc_financial_period`, `acc_approval_mst`) that no migration creates. DDL + ORM (`models.py`) + `query.py` + `seed_data.py` form the other, consistent dialect | `voucher_service.py:48,66,121,158,192`; `report_query.py:196-232`; `routers.py:1168`; DDL `create_accounting_phase1.sql` (grep for phantom cols = 0 hits) | Entire voucher write path + AP/AR reports fail at runtime against the committed schema. **Decision #1 (§7): verify what dev3 actually has before rewriting** |
| A2 | **FE↔BE contract breaks** — each independently fatal: (a) send-for-approval URL: FE `/send_approval` vs BE `/send_for_approval`; (b) ledger create: FE sends `acc_group_id`, BE requires `acc_ledger_group_id` → every UI ledger create 400s; (c) voucher payload: FE sends `acc_voucher_type_id` + `{debit, credit}` lines, BE reads `type_category` + `{debit_amount, credit_amount}`; (d) balance sheet: FE sends `as_on_date`, BE requires `from_date`+`to_date`; (e) opening-bills route mismatch; (f) FE maps `cost_center_id: line.branch_id`; (g) FE service-local types diverge from real payloads; `fetchVouchers` fakes the pagination total | FE:`accountingService.ts:557,678-695`; FE:`ledgers/page.tsx:284,299`; FE:`createVoucher/page.tsx:456-470`; `routers.py:180-182,715` | Even the parts of the module whose BE works are unusable from the UI |
| A3 | **Seed ↔ lookup line_type mismatch.** Seeder inserts `MATERIAL`/`REVENUE`/`TDS`/`FREIGHT`/`CLAIMS`; auto_post looks up `PURCHASE`/`JUTE_PURCHASE`/`SALES`/`TDS_PAYABLE`/`FREIGHT_INWARD`/`CLAIMS_RECEIVABLE`/`CASH` (the last never seeded at all). The auto_post strings aren't in `constants.LINE_TYPES` | `seed_data.py:409-434` vs `auto_post.py:373-377,555-560,774` | Auto-post would fail "account not configured" on a freshly activated company even after A1/B-fixes |
| A4 | **Party ledger classifier bug.** `party_mst.party_type_id` is a comma-separated **string** (`src/models/mst.py:531`); `seed_party_ledgers` compares it to int 2 → every party (customers included) is seeded under **Sundry Creditors** | `seed_data.py:349` | All customer ledgers are misgrouped; receivable reports would classify wrongly |
| A5 | **Referenced tables that don't exist:** `acc_approval_mst` (voucher approve reads max level from it), `acc_financial_period` (period-lock check), `acc_ageing_slab` (seeder is an explicit placeholder) | `voucher_service.py:63,948`; `seed_data.py:470-477` | Approve path can't work; period locking unenforceable; ageing buckets hardcoded in SQL |
| A6 | **No menu provisioning.** No `dbqueries` migration seeds accounting entries into `portal_menu_mst`/`menu_mst`; the `APPROVAL_MENU_MAP` keys (`acc_payment`, `acc_receipt`, …) are never inserted anywhere | `constants.py:114-121`; grep of `dbqueries/` | Pages unreachable through the standard role-menu system unless rows were added by hand |
| A7 | **Near-zero test coverage.** Only two accounting tests exist (parties dropdown; a proc_gst column regression guard whose docstring anticipates the wiring) | `src/test/test_accounting_parties.py`, `test_accounting_auto_post_gst_columns.py` | The A1–A5 class of defect is exactly what tests would have caught |
| A8 | Misc: `acc_voucher_numbering` seeded but never consumed (numbering uses phantom `MAX(voucher_seq)`); `acc_voucher_warning` + `WARNING_CODES` never written; `create_manual_voucher` ignores `bill_refs`/`ref_no`/`ref_date`/`party_ledger_id` and never persists `total_amount`/header `party_id`; a complete correct-dialect insert layer in `query.py` (`insert_*`, `get_next_voucher_number`, `get_party_outstanding_bills`, `update_bill_ref_pending`) is **never called**; reopen goes 6→1 instead of doc-specified 6→21 | `voucher_service.py`; `query.py:469+` | The unused `query.py` layer is a head start for the A1 rewrite — much of the correct SQL already exists |

### 3.2 B — Integration gaps (business modules → accounting)

**B0 (common): no triggers wired.** The design doc names the three call sites (`docs/accounting-module-design.md:1785-1787`): `src/procurement/billpass.py` `update_bill_pass()`, `src/juteProcurement/billPass.py` `update_bill_pass()`, `src/sales/salesInvoice.py` `approve_sales_invoice()`. None calls accounting. No posting exists for DR/CR notes, payroll (`SOURCE_DOC_TYPES` reserves `PAYROLL`/`PAYROLL_DISBURSEMENT`/`STATUTORY_REMITTANCE`; `src/hrms/` has zero accounting references), or inventory issues.

| # | Gap | Evidence | Impact |
|---|---|---|---|
| B1 | **Procurement poster broken vs source schema:** reads `proc_inward.co_id` (doesn't exist — co_id reached via `branch_mst` join) and `proc_inward_dtl.taxable_amount` (real column: `amount`); omits additional-charge GST (`proc_gst` rows linked via `proc_inward_additional_id`); ignores approved DR/CR notes entirely (design §3.1 includes them; the two `net_payable` formulas in `query.py:2462/:2590` differ on additional charges) | `auto_post.py:317,340,349-359` | Would crash if wired; and would post the wrong payable if only crash-fixed |
| B2 | **Jute poster broken vs source schema:** reads `jm.co_id/mr_id/mr_date/mr_no` (real: no co_id, `jute_mr_id`, `jute_mr_date`, `branch_mr_no`); `jute_mr.party_id` is `String(255)` (every join casts) vs int lookup in `_get_party_ledger`; **voucher doesn't balance** — DR−CR = `claim_amount − tds_amount` off under the BE net_total formula (claims leg double-adjusts the creditor); `net_total` TDS semantics differ BE vs FE (§2.3) | `auto_post.py:519-529,555-687`; `models/jute.py:85`; `mr.py:1481-1488`; FE:`billPass/edit/page.tsx:260-267` | Must resolve the net_total definition and re-derive the entry before wiring |
| B3 | **Sales poster broken vs source schema:** reads `si.co_id/net_amount/round_off_value`, PK `sales_invoice_id` (real: `invoice_id`, `invoice_amount`, `round_off`, no co_id); detail/GST reads use `taxable_amount`/`sales_invoice_dtl_id` (real: `amount_without_tax`, `invoice_line_item_id`); ignores `sales_invoice_additional(_gst)` which design §3.3 includes; jute-type invoices' `claim_amount` needs a decision (post gross + claim contra, matching the Tally export, or post net) | `auto_post.py:715-757` | Same class of fix as B1 |
| B4 | **No customer credit/debit note document** exists in sales (DR/CR notes are procurement-only), so sales returns/adjustments have no posting source; accounting's DEBIT_NOTE/CREDIT_NOTE voucher categories are seeded but unreachable | `src/procurement/drcr_note.py`; `src/models/sales.py` | Receivables corrections would have to be manual journals |
| B5 | **Bill pass is a 2-state flag, not a workflow** (both procurement `billpass_status` 0→1 and jute `bill_pass_complete` 0→1; `billpass_no`/`billpass_approved_by` never written in procurement; DR/CR `STATUS_PENDING_APPROVAL=20` defined, never used) | `billpass.py:430-508`; `drcr_note.py:37` | The posting trigger is a single irreversible flag — acceptable, but there is no approval gate in front of the ledger unless posting-mode DRAFT (§5.3) provides one |
| B6 | **Brokerage never captured** (jute): `jute_po.brokrage_rate/brokrage_percentage` are read back but never written by create/update or FE; no commission amount is ever computed → no payable exists to post. (Sales quotations/orders *do* carry `brokerage_percentage`) | `models/jute.py:459-460`; `jutePO.py:812-814` | If broker commission payables are wanted, capture must be built first — flagged as open decision §7 |
| B7 | **TDS/TCS not integrated:** `tds_mst` rate master is a complete orphan (no CRUD, no consumers); `proc_tds` table has no read/write path; jute computes 194Q TDS in code with hardcoded threshold/rate (`mr.py:992-995`); sales TCS was deliberately removed (regression-tested) though `co_config.india_tcs` exists | `src/models/mst.py:655-664`; `models/procurement.py:797-818`; `test_sales_invoice_fields.py:431-478` | TDS payable postings and a TDS register need a real rate/threshold source |

### 3.3 C — Payments pending & payments receivable

| # | Gap | Evidence | Impact |
|---|---|---|---|
| C1 | **`acc_bill_ref` is never populated** — the only writers are the unwired auto_post functions; manual voucher creation ignores the FE `bill_refs` array; opening-bills endpoint is broken (A1) and has no UI | `voucher_service.py` (never reads `bill_refs`); `routers.py:1168` | Party outstanding and ageing are empty even after the SQL is fixed. **This is the root cause of "no payments pending/receivable visibility"** |
| C2 | **No payment/receipt entry UX.** No dedicated Make-Payment / Record-Receipt pages; PAYMENT/RECEIPT voucher types exist only as options inside the generic (broken) voucher form; no outstanding-bill picker/allocation grid; `settleBills` service fn has no UI; `/settle_bills` BE is phantom-dialect | FE: no `payment*`/`receipt*` folders under `accounting/`; `routers.py:826` | An accountant cannot record "paid supplier X ₹Y against bills A,B" at all |
| C3 | **No payment instrument capture.** `acc_payment_detail` (mode/cheque/NEFT/UTR) is Phase-2 designed, not built; no cheque register; company bank master `bank_details_mst` is **not linked** to `acc_ledger` (bank ledgers seeded independently); no petty-cash concept | design doc `:855-902`; `src/masters/bankDetails.py` | Payments can't reference how they were made; bank book/BRS impossible |
| C4 | **Advance lifecycle unbuilt** (design §3.5): PO `advance_type/value/amount` computed then dead-ends — nothing downstream reads them, no advance payment voucher, no `ADVANCE` bill-ref creation, no adjustment-at-bill-pass | `po.py:1137,1796` | Advances — common in jute trade — invisible to payables |
| C5 | **No due-date derivation / credit control.** Due dates are manually keyed in all three modules; PO `credit_days` and invoice `payment_terms` never compute anything; `acc_ledger.credit_days/credit_limit` stored but consumed by nothing (no warning, no report); `party_mst` has no financial fields at all | `models/mst.py:510-531`; `accounting/models.py:86-89` | "What's due this week" cannot be answered reliably |
| C6 | **AP/AR reports broken + no dashboards.** `party_outstanding`/`ageing_analysis` SQL uses phantom columns; ageing buckets hardcoded; FE filter params ignored by BE; no payables/receivables dashboard widgets; no supplier/customer statement; procurement has no pending-payments report (only the bill-pass xlsx with net payable); jute captures `payment_due_date` but never aggregates it | `report_query.py:196-232`; `reports.py` (both modules) | Even posted data would have no usable surface |
| C7 | **Tally is the real system of record for money** — jute purchase Tally export (`juteReports/tally-download`, hardcoded ledger strings `reportQueries.py:605-647`) and raw-jute sales Tally export (hardcoded 180 credit days, `sales/reportQueries.py:385`) are how payables/receivables reach accounting today; `co_mst.tally_sync` flag exists | `src/juteProcurement/reportQueries.py`; `src/sales/reportQueries.py:243-519` | Transition plan must keep these working per company until in-app accounting is trusted (§5.3 posting-mode OFF) |

### 3.4 D — Expense booking

| # | Gap | Evidence |
|---|---|---|
| D1 | **No expense-booking flow at all**: no expense entry page, no simplified voucher, no attachments. Only path = generic voucher form (broken) with a manually pre-created expense ledger | FE: no `expense*` anywhere; grep both repos |
| D2 | **No expense-category master** and no `EXPENSE` doc_type in account determination (seeded doc_types: PROC_BILLPASS, JUTE_BILLPASS, SALES_INVOICE only) → a non-accountant has no "Office Rent / Diesel / Freight" vocabulary that maps to ledgers | `seed_data.py:411-431` |
| D3 | **Cost dimension confusion:** `acc_voucher_line.cost_center_id` exists with no `acc_cost_center` table, no endpoints, no UI (Phase-3 reserved); the existing `cost_factor_mst` is an inventory-issue tagging dimension, unrelated to GL; FE currently stuffs `branch_id` into `cost_center_id` | `models.py`; FE:`createVoucher/page.tsx:468` |
| D4 | **HRMS payroll posts nothing** (salary & wages are most companies' largest expense): design §3.4 fully specifies the salary journal/disbursement/statutory-remittance entries and the constants are reserved, but no `auto_post_payroll` exists and `src/hrms/` never references accounting | design doc `:157-232`; grep `src/hrms/` |

### 3.5 E — Per-company configurability

| # | Gap | Evidence |
|---|---|---|
| E1 | `acc_account_determination` is the **only** editable accounting config: UI supports ledger reassignment per existing doc_type × line_type row only — cannot add/remove rules; `item_grp_id` column exists but the lookup ignores it (no item-group or branch-level overrides) | `auto_post.py:19-31`; FE:`accountDeterminations/page.tsx` |
| E2 | **No accounting settings table** — nothing controls per-company posting behavior (auto vs. review vs. off), rounding ledger, due-date rules, ageing buckets, numbering format, FY convention (Apr–Mar hardcoded), duplicate-check tolerance, warning severity | `seed_data.py` (hardcoded lists); `voucher_service.py` |
| E3 | The system-wide per-company config pattern exists — `co_config` (`india_gst`, `india_tds`, `india_tcs`, `back_date_allowable`, workflow toggles) consumed by sales/procurement — but accounting reads none of it. ⚠️ `co_config` DDL is defined **twice** with different columns in `dbqueries/procurement.sql:26,47` | `src/common/companyAdmin/models.py:188-207` |
| E4 | Approval-hierarchy config for vouchers is broken two ways: code reads the non-existent `acc_approval_mst` instead of the shared `approval_mst` + `process_approval()` framework every other module uses (and which the design doc §12 specifies) | `voucher_service.py:948`; `src/common/approval_utils.py` |
| E5 | Hardcoded chart-of-accounts contents, party→creditor classification rule, voucher number format `{prefix}{00000}`, ageing buckets, bank/cash-required categories | `seed_data.py`; `report_query.py` |

---

## 4. Root-Cause Reading

The pattern across all five agent sweeps is consistent: **design → build → integrate was abandoned between "build" and "integrate", and "build" itself was done twice against different schema assumptions.** The correct-dialect data layer (`models.py`, `query.py`, DDL, seeds) and the phantom-dialect service layer (`voucher_service.py`, `auto_post.py`) were almost certainly written in separate passes without a live DB check between them — and since nothing calls the service layer in any test or business flow, the breakage was never observed. Everything else (empty bill refs, dead reports, missing UX) follows from that.

Practical implication: **do not build any new feature on `src/accounting/` until Phase 0 (§6) lands.** The good news: the fix is mostly *reconciliation*, not invention — the unused correct-dialect insert layer in `query.py`, the seeded determinations, and the FE pages are all salvageable, and the design doc remains a valid target.

---

## 5. Target Architecture — Interconnecting Accounting with Procurement, Jute & Sales

### 5.1 Flow overview

```
                                  ┌─────────────────────────────────────────┐
 Procurement bill pass complete ──►                                         │
 Jute bill pass complete ─────────►   POSTING SERVICE  (src/accounting/     │
 Sales invoice approved ──────────►   posting_service.py — one entry point: │──► acc_voucher (+lines,+gst)
 DR/CR note approved ─────────────►   post_document(doc_type, doc_id, user))│──► acc_bill_ref  (AP/AR open items)
 Payroll finalized (later) ───────►                                         │──► acc_voucher_approval_log
                                  │  • reads acc_company_settings:          │
                                  │      posting_mode per doc_type          │
                                  │      AUTO_APPROVED | AUTO_DRAFT | OFF   │
                                  │  • resolves ledgers via                 │
                                  │      acc_account_determination          │
                                  │      (item_grp → default fallback)      │
                                  │  • idempotent (source_doc guard)        │
                                  │  • failure-isolated via posting queue   │
                                  └─────────────────────────────────────────┘
 Payment / Receipt / Expense UX ──► manual vouchers ──► acc_bill_settlement ──► outstanding = bill_ref − settlements
                                                                              ──► dashboards, ageing, statements
```

### 5.2 The posting service (replaces direct `auto_post_*` calls)

One module-level entry point, `post_document(db, source_doc_type, source_doc_id, user_id)`, with per-doc-type recipe functions. Non-negotiable properties:

1. **Failure isolation.** A business approval must never fail or roll back because accounting posting failed. Wire the trigger as: business transaction commits → enqueue row in a new `acc_posting_queue` (source_doc_type, source_doc_id, co_id, status PENDING/POSTED/FAILED, attempt count, last_error) → attempt the post in the same request after commit; on failure the queue row stays FAILED and is retryable from a small "Posting Queue" admin page. This also gives a natural backfill path for historical documents.
2. **Idempotency.** Keep the existing duplicate guard (`source_doc_type + source_doc_id`, non-cancelled) — it is already correctly designed in `auto_post.py:266-291`.
3. **Correct source reads.** Rewrite each recipe against the real schemas (§3.2 B1–B3 lists every wrong column). Procurement must include additional-charge GST and approved DR/CR notes so that the posted payable equals the bill-pass detail `net_payable` formula (`query.py:2590`) — and that formula should first be unified with the list formula.
4. **Balanced by construction.** Assemble entries as a list of (line_type, dr_cr, amount) and assert ΣDR = ΣCR before insert; unit-test each recipe against fixture documents (the jute recipe currently fails this — §3.2 B2).
5. **Reversal on source change.** Bill pass and invoices are immutable once complete/approved, so v1 needs no sync logic; but a cancelled/reopened source document must post a reversal voucher (the reversal machinery already exists).

### 5.3 Per-company dynamism (the "each company functions differently" requirement)

Three layers, from coarse to fine:

**Layer 1 — `acc_company_settings` (new table, one row per co_id):**

| Setting | Values | Default | Serves |
|---|---|---|---|
| `posting_mode_purchase` / `_jute_purchase` / `_sales` / `_drcr` / `_payroll` | `AUTO_APPROVED` (voucher born status 3), `AUTO_DRAFT` (born 21 — accountant reviews & approves via existing workflow), `OFF` (no posting; company keeps Tally export) | `OFF` until the company activates | Companies with a full accounts team want review; small companies want automation; Tally-loyal companies want neither yet |
| `due_date_rule` | `PARTY_CREDIT_DAYS` → `DOC_CREDIT_DAYS` → `MANUAL` precedence order | party → doc → manual | Payables/receivables due dates without forcing one convention |
| `default_rounding_ledger`, `default_cash_ledger`, `default_bank_ledger_id` | ledger FKs | seeded system ledgers | Recipe fallbacks |
| `ageing_slabs` | via `acc_ageing_slab` rows (finally build the table; seed 0-30/31-60/61-90/91-180/180+) | per design doc | Company-specific ageing buckets |
| `fy_start_month` | 1–12 | 4 (April) | Non-Indian-FY tenants later |
| `enable_tds`, `enable_tcs` | mirror/link `co_config.india_tds/india_tcs` | from co_config | TDS legs in recipes only where enabled |
| `expense_approval_required` | bool | false | Whether quick expenses go 21→…→3 or post directly |

Follow the `co_config` pattern (it is the established precedent) but keep this table in accounting's own namespace; read `co_config.india_*` rather than duplicating where possible.

**Layer 2 — `acc_account_determination` v2 (resolution order):** keep the table; fix the lookup to resolve most-specific-first: `(co_id, doc_type, line_type, item_grp_id)` → `(co_id, doc_type, line_type, is_default=1)`. Add UI to create/remove rules (not just reassign ledgers) and expose `item_grp_id`. This alone covers most "company A books jute under a different head than company B" needs without code changes. Branch-level overrides can be a later column if a tenant needs them.

**Layer 3 — recipe constants:** unify `LINE_TYPES` so seeds, recipes, and constants share one vocabulary (fix A3), and add `EXPENSE` and `BROKERAGE` doc/line types for §5.5/§7.

### 5.4 Payments pending & receivable — the product surface

Once purchase/sales vouchers create `acc_bill_ref` rows with due dates, build the workspace (mostly FE + a few thin endpoints over already-designed queries):

1. **Payments Pending (AP) page** — open supplier bills from `acc_bill_ref` (+ opening bills), grouped by party, bucketed by due date (overdue / due this week / later), drill-down to source bill pass. The correct-dialect query already exists unused: `query.get_party_outstanding_bills` (`query.py:469`).
2. **Make Payment flow** — pick supplier → open bills listed → allocate amounts (full/partial, multiple bills per payment) → choose bank/cash ledger + payment mode/instrument (build `acc_payment_detail` from the Phase-2 design) → creates an approved (or draft, per settings) PAYMENT voucher + `acc_bill_settlement` rows in one transaction. `ref_type=ADVANCE` when paying without a bill (creates an open advance to adjust later); on-account receipts likewise.
3. **Payments Receivable (AR) page + Record Receipt flow** — mirror image for customers; receipt against invoices, advances from customers.
4. **Fix the reports:** rewrite `party_outstanding`/`ageing_analysis` on the ORM dialect (outstanding = `bill_ref.amount − Σ settlements`, union opening bills), honor the FE's `party_type`/`branch_id` filters, drive buckets from `acc_ageing_slab`.
5. **Dashboard widgets** (portal landing): Total payables / receivables, overdue amounts, top 5 parties, cash+bank balance — all computable from voucher lines + bill refs.
6. **Credit control (cheap wins):** invoice/PO screens derive `due_date` from the due-date rule; warning (using the existing, never-used `acc_voucher_warning` table) when a sales order/invoice would breach `acc_ledger.credit_limit`.
7. **Opening balances:** fix `POST /opening_bills` (A1) and give the existing unused FE service function a small import page — companies onboarding mid-year need their open bills in before any of this is credible.

### 5.5 Easy expense booking

1. **Expense Entry page** (`accounting/expenses/`): date, paid-from (cash/bank ledger or "unpaid — book as payable to party"), **expense category**, amount, optional GST (registered vendor case), optional party, narration, attachment upload. One screen, no debit/credit vocabulary.
2. **`acc_expense_category` master** (new, small): category name → `acc_ledger_id` (+ optional default GST treatment). Seed sensible defaults (Freight, Rent, Electricity, Repairs, Office, Vehicle, …) per company at activation; editable per company — this is deliberately the same determination idea, scoped to expenses, so non-accountants pick "Diesel" and the ledger mapping is a company-level decision.
3. Behind the scenes it creates a PAYMENT voucher (paid now) or JOURNAL + payable bill_ref (book now, pay later — which then appears in Payments Pending), honoring `expense_approval_required`.
4. **Payroll posting** (design §3.4) closes the biggest expense hole — implement `post_document('PAYROLL', pay_period_id)` reading `pay_employee_payperiod`/`pay_employee_payroll` once Phase 0–2 are stable.

### 5.6 Bank & cash

- Link `bank_details_mst` ↔ `acc_ledger` (`ledger_type='B'`): add `acc_ledger_id` to `bank_details_mst` (or build `acc_bank_account` per Phase-2 design) with a one-time backfill/mapping screen. Sales invoices already carry `bank_detail_id` — this makes receipts default to the right bank ledger.
- `acc_payment_detail` (mode, instrument no/date, UTR) on every payment/receipt voucher → enables the bank book report and, later, bank reconciliation (Phase-2 design already specifies both).

---

## 6. Sequenced Roadmap

Ordering rule: nothing in a later phase starts until the earlier phase's exit criteria pass on dev3.

### Phase 0 — Repair the foundation (blocking everything)
1. **Decision gate:** run `tenant-schema-check` against dev3's `acc_*` tables to determine which dialect the live DB actually has (the phantom columns may exist out-of-band). Pick one source of truth — recommendation: the ORM/DDL dialect, since models.py is the repo's declared authority and `query.py`'s unused insert layer already targets it.
2. Rewrite `voucher_service.py`, `auto_post.py` (as `posting_service.py`), `report_query.py` AP/AR queries, and `POST /opening_bills` on the chosen dialect; reuse the dormant `query.py` layer; make `create_manual_voucher` persist `total_amount`, header `party_id`, `ref_no/ref_date`, and honor `bill_refs`; consume `acc_voucher_numbering` for numbering.
3. Replace `acc_approval_mst` usage with the shared `approval_mst` + `process_approval()` framework (matches design §12 and every other module).
4. Fix seeds: unify `LINE_TYPES` (A3), fix party classifier for comma-separated `party_type_id` (A4), seed the missing determinations.
5. Fix all FE↔BE contract breaks (A2) and align `accountingService.ts` types with `types/accountingTypes.ts`.
6. Provision menus (`add-menu` skill) for existing pages.
7. Tests: voucher lifecycle round-trip, each report query against the DDL schema (a simple "SQL columns ⊆ schema" guard like the existing proc_gst test, generalized), seeding assertions.
   **Exit:** a manual Journal/Payment/Receipt voucher can be created, approved, and appears in trial balance + day book from the UI on dev3.

### Phase 1 — Wire the three postings (config-driven)
1. `acc_company_settings` + `acc_posting_queue` + `acc_ageing_slab` tables; settings page (or section) in accounting UI.
2. Rewrite the three recipes against real source schemas (B1–B3), including additional charges + DR/CR notes (procurement), resolved `net_total`/claims/TDS treatment (jute — decisions §7), additional charges + claim handling (sales). Balanced-entry unit tests per recipe.
3. Wire triggers in `update_bill_pass` (both) and `approve_sales_invoice` via the queue; posting-mode honored; reversal on source cancel/reopen.
4. DR/CR-note posting recipe (procurement) so post-billpass notes adjust the payable.
   **Exit:** on dev3, completing a bill pass / approving an invoice produces a balanced voucher + bill_ref (or a draft voucher in AUTO_DRAFT mode), visible in party outstanding.

### Phase 2 — Payables/receivables workspace
Make Payment + Record Receipt flows with allocation grid; `acc_payment_detail`; fixed AP/AR reports + ageing on slabs; Payments Pending / Receivable pages; opening-bills import UI; dashboard widgets; due-date rule wiring into invoice/bill-pass screens; advance capture from PO advance fields + adjustment during posting; credit-limit warning.

### Phase 3 — Expense booking + TDS
Expense Entry page + `acc_expense_category`; expense payable → Payments Pending; wire `tds_mst` (CRUD + rates) and TDS legs in purchase/expense recipes per `enable_tds`; TDS register report; payroll posting.

### Phase 4 — Bank & compliance depth
Bank ledger ↔ `bank_details_mst` link; bank book; bank reconciliation; GST summary page (FE exists-not); GSTR-1/3B data endpoints (Phase-2 design); customer credit-note document (B4) if sales returns need first-class treatment; retire Tally exports tenant-by-tenant (flip `posting_mode` from OFF).

---

## 7. Open Decisions — ANSWERED by owner (2026-07-12)

1. **Schema dialect:** the accounting module is not used anywhere yet. The ORM models (`src/accounting/models.py`) are the schema of record — rewrite the phantom-dialect code against them and update all DBs (dev3 first) via migrations to match the models.
2. **Jute `net_total` semantics:** net payable at bill pass **must deduct TDS**. Where it doesn't (the BE MR-approval formula), add that behaviour: `net_total = total − claim − tds + roundoff`, recomputed server-side.
3. **Jute claims treatment:** post **gross purchase + separate claim recovery** (matches the Tally export's "Claim on Gross Purchase").
4. **Credit terms:** derive due dates from **PO credit days** (doc due date wins when manually entered).
5. **Approval gate:** yes — nothing reaches accounting until the document is approved / bill pass is marked complete, as the case may be. (A full 21/1/20/3 workflow on bill pass itself remains a follow-up; posting triggers on the existing terminal markers, and AUTO_DRAFT posting mode provides an accountant review gate.)
6. **Brokerage:** no accounting impact — brokerage is paid by someone else and noted only. Out of scope.
7. **Tally coexistence:** keep it simple — just post in-app; revisit reconciliation only if needed later.
8. **Backfill:** nothing now; will be run after testing.

---

## 8. Implementation Status (2026-07-12 — same branch)

Phase 0 and Phase 1 are **built** on this branch:

- **Phase 0:** `voucher_service.py` fully rewritten on the ORM schema (create/update/lifecycle/reverse/settle, numbering via `acc_voucher_numbering`, shared `process_approval` framework with single-level fallback); AP/AR report queries rewritten (`acc_bill_ref.pending_amount` + opening bills, ageing bucketed per `acc_ageing_slab`); `POST /opening_bills` fixed; seeds fixed (party classifier, Claim on Purchase/Sales ledgers, final determination vocabulary, ageing slabs, default settings row); all FE↔BE contract breaks fixed in vowerp3ui.
- **Phase 1:** `posting_service.py` (replaces the deleted `auto_post.py`) — config-driven `post_document()` honoring `acc_company_settings` posting modes (OFF / AUTO_DRAFT / AUTO_APPROVED), idempotent, failure-isolated via `acc_posting_queue`, balanced-by-construction; recipes for PROC_BILLPASS (incl. additional-charge GST + DR/CR-note cascade), DRCR_NOTE, JUTE_BILLPASS (gross + claim recovery, TDS-deducting `net_total` via `src/juteProcurement/totals.py`, freight as separate payment voucher), SALES_INVOICE (incl. additional charges + jute claims); wired into `update_bill_pass` (procurement + jute), `approve_drcr_note`, and `approve_sales_invoice` after the business commit. New endpoints: company_settings (GET/PUT), posting_queue (GET + retry). New FE page: Accounting Settings + posting-queue monitor.
- **To go live on dev3:** run `dbqueries/migrations/create_accounting_phase1.sql` (if the `acc_*` tables don't exist yet) then `dbqueries/migrations/accounting_integration_phase1_upgrade.sql`; call `POST /api/accounting/activate_company` per company (idempotent — safe to re-run on already-activated companies to pick up new seeds); flip posting modes on the new Settings page. Menu rows for the accounting pages are still unprovisioned (needs DB access — `add-menu` skill).
- **Still pending (per roadmap):** Phase 2 AP/AR workspaces (Make Payment / Record Receipt with allocation UI, opening-bills import page, dashboards, `acc_payment_detail`), Phase 3 expense entry + TDS master wiring + payroll posting, Phase 4 bank/GST depth, and a real approval workflow on bill pass itself.

## Appendix A — Evidence Index (key files)

| Area | Files |
|---|---|
| Accounting BE | `src/accounting/{routers,voucher_service,auto_post,query,report_query,seed_data,models,constants}.py`; DDL `dbqueries/migrations/create_accounting_phase1.sql`; registration `src/main.py:301` |
| Accounting FE | `../vowerp3ui/src/app/dashboardportal/accounting/**`; `../vowerp3ui/src/utils/accountingService.ts`; `../vowerp3ui/src/utils/api.ts:681-719` |
| Procurement financials | `src/procurement/{billpass,sr,drcr_note,po}.py`; `src/procurement/query.py:2462,2590` (net_payable); `src/models/procurement.py:470-591,797-818,882-998` |
| Jute financials | `src/juteProcurement/{billPass,mr,jutePO}.py`; `src/models/jute.py:60-223,417-424,455-462`; TDS logic `mr.py:992-1105`; Tally export `src/juteProcurement/reportQueries.py:447-719` |
| Sales financials | `src/sales/{salesInvoice,reports}.py`; `src/models/sales.py:37-330,1084-1178`; Tally export `src/sales/reportQueries.py:243-519` |
| Config patterns | `co_config`: `src/common/companyAdmin/models.py:188-207` (+ duplicate DDL `dbqueries/procurement.sql:26,47`); orphan `tds_mst`: `src/models/mst.py:655-664`; `party_mst`: `src/models/mst.py:510-531` |
| Prior design | `docs/accounting-module-design.md` (esp. §3 triggers, §3.5 advances, §4.2 Phase-2 tables, §12 approvals) |

## Appendix B — Method

Produced by a five-agent parallel sweep (accounting current-state, procurement financial touchpoints, sales financial touchpoints, jute-purchase financial touchpoints, cross-cutting payments/config sweep), each verifying against router/model/DDL source in both repos; headline claims (unwired auto_post, phantom columns, seed/lookup mismatch, FE contract breaks) independently re-verified by direct grep before publication. Live-DB state (dev3) was **not** inspected — see Open Decision #1.
