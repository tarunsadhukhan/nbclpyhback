# Design — Overhead & Margin as %, and Per-Line Costing-Done on the Enquiry Flow

**Date:** 2026-07-16
**Repos:** `vowerp3be` (backend, primary) + `vowerp3ui` (frontend)
**Modules:** BOM Costing (`src/bomcosting/`), Sales Enquiry (`src/sales/enquiry*`), Sales Quotation (prefill only)
**Status:** Approved design — ready for implementation plan.

---

## 1. Problem / Client requirement

1. **Overhead and margin must be added as a % of the total costing**, not as absolute cost-sheet
   amounts.
2. The **BOM cost sheet must stop at base cost** — "everything except overheads and margin".
3. The **sales-enquiry person** who receives the costing applies overhead% + margin% (as % of the
   confirmed base cost) to arrive at the indicative sell price, which flows to the quotation.
4. **Link costing to the enquiry**: the costing person marks, **per line**, that costing is done for
   enquiry X, and the **flow board** reflects it.

## 2. Current state (as-found)

Chain today:

```
Cost sheet (item_bom_hdr_mst + bom_cost_entry over cost_element_mst; element_type material|conversion|overhead, all ABSOLUTE ₹)
  → rollup (compute_full_rollup) → bom_cost_snapshot {material_cost, conversion_cost, overhead_cost, total_cost = M+C+OH, cost_per_unit}
  → enquiry line (sales_enquiry_dtl): confirm_line_costing stamps bom_hdr_id + cost_snapshot_id + confirmed_cost_per_unit + costing_confirmed_by/date   (COST only)
  → quotation line (sales_quotation_dtl): base_cost + overhead_pct + margin_pct;  rate = base_cost × (1+oh/100) × (1+margin/100)
  → sales order
```

Problems:
- **Overhead applied twice, inconsistently**: absolute inside the cost sheet (`bom_cost_snapshot.overhead_cost`, summed into total) AND as a percent on the quotation (`overhead_pct`).
- **Margin exists only on the quotation line** — nowhere earlier.
- **The enquiry person sets nothing** on pricing; the quotation person enters OH%/margin% from scratch.
- **"Costing done" is implicit**: a generic "Costing Done → Sales" button forwards `COSTING_REVIEW → QUOTATION` with **no validation** that lines are actually costed, and the board shows only the stage.

## 3. Decisions (locked with the user)

| # | Decision | Choice |
|---|----------|--------|
| D1 | Where OH%/margin% are set & applied | **Enquiry line** (Costing Review stage); flows to quote. Cost sheet = base only. |
| D2 | Cost-sheet "overhead" category | **Drop from base cost** — total = material + conversion. |
| D3 | Margin formula | **Markup on cost**: `sell = base × (1+oh/100) × (1+margin/100)` (same as quotation). |
| D4 | Quotation OH%/margin% behaviour | **Inherit** from enquiry (prefilled), still **editable**. |
| D5 | Costing-done marking | **Per-line**, aggregated to the enquiry; **reuse existing per-line stamps** (no new boolean). |

## 4. Key reuse finding

Per-line costing-done is ~90% already built. **No new `costing_done` flag.**

| Need | Reuses (existing) |
|------|-------------------|
| Per-line "cost confirmed" | `sales_enquiry_dtl.cost_snapshot_id`, `confirmed_cost_per_unit`, `costing_confirmed_by`, `costing_confirmed_date` (written by `confirm_line_costing`, `src/sales/enquiry.py:1499` via `update_enquiry_dtl_costing()`) |
| Per-line confirm UI | costingReview per-line "Confirm Costing / Re-confirm" dialog |
| Per-line status chip | createEnquiry "Cost Basis" column chip; costingReview line chip |
| Board per-card count | `get_enquiry_board_query()` already returns `line_count` via correlated subquery (`enquiry_query.py:153`) |
| Enquiry-level who/when | `flow_stage_log` (action_by / action_date_time / feedback) on the FORWARD |
| Completion gate | `move_stage` + `validate_transition` (`enquiry.py:1296`) |

Derived state (no storage):

```
line_done    = cost_snapshot_id IS NOT NULL AND overhead_pct IS NOT NULL AND margin_pct IS NOT NULL
enquiry_done = every active line is line_done
               (free-text / new-item lines, item_id IS NULL, must be resolved first — confirm_line_costing already rejects them)
sell_price_per_unit = confirmed_cost_per_unit × (1 + overhead_pct/100) × (1 + margin_pct/100)   -- computed, never stored
```

## 5. Target flow

```
BOM Cost Sheet        base = material + conversion         (overhead DROPPED from total)
   │ rollup → bom_cost_snapshot.cost_per_unit (= base cost/unit)
   ▼ confirm_line_costing  (Costing Review; per line)
Enquiry line          confirmed_cost_per_unit + overhead_pct + margin_pct   ← NEW cols, set by costing/enquiry person
   │                  line_done when all three set;  sell/unit computed
   ▼  Mark Costing Complete → Sales   (gated: every active line line_done)
Quotation line        base_cost + overhead_pct + margin_pct  (prefilled from enquiry, editable)
   ▼
Sales order
```

## 6. Schema changes — ONE migration

File: `dbqueries/migrations/enquiry_costing_overhead_margin.sql` (with rollback SQL as comment).

1. `ALTER TABLE sales_enquiry_dtl ADD COLUMN overhead_pct DOUBLE NULL, ADD COLUMN margin_pct DOUBLE NULL;`
   (nullable — a line is "priced" once both are set; no CHECK bounds to match existing `*_pct` convention.)
2. `CREATE OR REPLACE VIEW vw_bom_cost_summary` so `total_cost` sums only material + conversion
   (`SUM(CASE WHEN element_type IN ('material','conversion') THEN amount ELSE 0 END)`); keep the
   per-category `overhead_cost` column for reference.
3. `sales_quotation_dtl` — **no change** (already carries `base_cost`, `overhead_pct`, `margin_pct`, `cost_snapshot_id`, `enquiry_dtl_id`).

**Rollout:** apply to `dev3` first (QA), then `sls` and every other tenant **before** the code deploy
(schema-drift rule; nullable columns are back-compatible so ordering is safe but must precede code
that SELECTs them).

## 7. Backend changes (`vowerp3be`)

- **`src/bomcosting/bomCosting.py` — `compute_full_rollup`**: `total_cost = material_cost + conversion_cost`.
  Still compute `overhead_cost` (for the snapshot/JSON), just exclude it from `total_cost` and thus `cost_per_unit`.
- **ORM `src/models/enquiry.py` — `SalesEnquiryDtl`**: add `overhead_pct: Mapped[Optional[float]]`,
  `margin_pct: Mapped[Optional[float]]` (Double, nullable).
- **`confirm_line_costing` (`src/sales/enquiry.py:1499`)**: accept optional `overhead_pct`, `margin_pct`
  in the body; validate 0 ≤ pct (warn, don't hard-cap); persist via extended `update_enquiry_dtl_costing()`.
  Backward compatible when omitted.
- **`get_enquiry_dtl_by_id_query` (`enquiry_query.py:268`)**: SELECT `overhead_pct`, `margin_pct`, and
  computed `sell_price_per_unit` (`confirmed_cost_per_unit*(1+overhead_pct/100)*(1+margin_pct/100)`).
- **`get_enquiry_board_query` (`enquiry_query.py:112`)**: add a `costed_line_count` correlated
  subquery (COUNT where `cost_snapshot_id IS NOT NULL AND overhead_pct IS NOT NULL AND margin_pct IS NOT NULL`)
  next to the existing `line_count`.
- **`move_stage` (`enquiry.py:1296`)**: when action=FORWARD and `from` stage is `COSTING_REVIEW`, block
  unless every active line is `line_done` and there are no unresolved free-text lines; 400 lists the
  pending `enquiry_dtl_id`s. (Keeps `flow_stage_log` as the "costing complete" audit.)
- **Quotation prefill** (`QUOTATION_ENQUIRY_LINES` read + `insert_sales_quotation_dtl`, `src/sales/query.py:182`):
  carry `overhead_pct` / `margin_pct` from the enquiry line into the seeded quote line.

## 8. Frontend changes (`vowerp3ui`)

- **costingReview `page.tsx` — `ConfirmCostingDialog`**: add OH% + margin% inputs and a live
  sell-price preview; on confirm send them. Per-line action label stays "Confirm / Re-confirm".
  The "Costing Done → Sales" button surfaces the 400 (lists pending lines) instead of forwarding.
  Line chips: Costed → Priced → Done.
- **board `page.tsx`**: card shows "Costed X/Y" chip while in COSTING_REVIEW; "Costing ✓ · ₹<sell value>"
  once forwarded. Read from `costed_line_count` / `line_count`.
- **bomCosting costSheet `page.tsx` + `CostEntrySummaryBar`**: total = material + conversion; render
  overhead as an "excluded" reference row, not part of the total.
- **bomCosting list `page.tsx`**: `total_cost` already reflects the new rollup; overhead column shown as reference.
- **costElementMaster `CostElementForm.tsx`**: `ELEMENT_TYPES = ["material","conversion"]` for NEW
  elements (existing overhead rows remain, edit-only, excluded from total).
- **createEnquiry `page.tsx`**: cost-basis chip also shows OH%/margin%/sell (read-only).
- **`src/utils/enquiryService.ts`**: `EnquiryLine` += `overhead_pct`, `margin_pct`, `sell_price_per_unit`;
  `confirmLineCosting(enquiry_dtl_id, bom_hdr_id, overhead_pct?, margin_pct?)`.

## 9. Testing

**Backend (pytest, `src/test/`):**
- `compute_full_rollup`: total = material + conversion; overhead excluded; cost_per_unit reflects it.
- `confirm_line_costing`: persists OH%/margin%; omitted → nulls (back-compat); computes/returns cost.
- `move_stage`: FORWARD out of COSTING_REVIEW blocked (400 + pending ids) until all lines done; allowed when done.
- board query: `costed_line_count` correct across mixed lines.

**Real-usage dev3 browser test** (portal-ui-flow-tester / qa-portal-page):
build cost sheet (material+conversion) → rollup → note base cost/unit → create enquiry → open →
FORWARD to COSTING_REVIEW → per line confirm cost + enter OH% + margin% → verify sell price + per-line
Done chip + board "Costed X/Y" → try to complete with one line unpriced (expect block) → finish all →
Mark Costing Complete → verify board "Costing ✓" and QUOTATION stage → create quotation → verify
OH%/margin% prefilled and editable.

## 10. Deferred / out of scope

- Company-level default OH%/margin% (chose enquiry-set). Easy add later (company config or std_rate_card `overhead_pct`, currently dead code).
- Re-rollup of existing BOMs — not forced; old snapshots keep their totals so already-confirmed enquiry costs don't retro-change.
- Wiring `std_rate_card.rate_type='overhead_pct'` (dead) — leave as-is.
- Locking quotation OH%/margin% to enquiry values — chose editable.

## 11. Risks / watch-items

- **Tenant rollout ordering**: migrate `sls` + other tenants before deploying code that SELECTs the new columns / new view.
- **Overhead semantics change** is a business behaviour change — existing cost sheets' totals drop by
  their overhead on next rollup. Intended, but flag to users.
- **Free-text/new-item lines** can never be costed; the completion gate must clearly tell the user to
  create the item + BOM first (reuses existing confirm rejection message).
- `sell_price_per_unit` is computed, not stored — any report needing it must apply the same formula.
