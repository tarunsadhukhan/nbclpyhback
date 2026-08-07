# GST Taxation — Procurement Module (Backend)

> Authoritative guide for how GST should work across all procurement endpoints.
> Last updated: 2026-02-26

---

## 1. Business Rules & Configuration

### 1.1 GST Applicability

GST is enabled **per company** via the `co_config` table:

```sql
SELECT india_gst FROM co_config WHERE co_id = :co_id;
```

- `india_gst = 1` → GST enabled; calculate and store GST on all transactions
- `india_gst = 0` → GST disabled; skip all GST logic, store zero/null

**Deriving co_id:** If only `branch_id` is provided, derive via:
```sql
SELECT co_id FROM branch_mst WHERE branch_id = :branch_id;
```

**Query functions:**
- `india_gst_applicable()` — `src/masters/query.py:89-94`
- `get_co_config_by_id_query()` — `src/common/companyAdmin/query.py:160-174`

### 1.2 Tax Percentage Source

| Transaction Type | Tax % Source |
|-----------------|-------------|
| Line items | `item_mst.tax_percentage` (per item) |
| Additional charges | `additional_charges_mst.default_value` (per charge type) |

Tax percentage is stored on the item master and is the **total tax rate** (e.g., 18%). The split into CGST/SGST or IGST is determined by state comparison.

### 1.3 State Comparison — IGST vs CGST/SGST

**Inputs:**
- **Supplier state:** `party_branch_mst.state_id` (from the supplier's billing branch, stored as `supplier_branch_id`)
- **Destination state:** `branch_mst.state_id` (from the company's shipping/billing branch)

**Rules:**
| Condition | Tax Type | Split |
|-----------|----------|-------|
| `supplier_state_id == destination_state_id` | Intra-state | CGST = tax% / 2, SGST = tax% / 2 |
| `supplier_state_id != destination_state_id` | Inter-state | IGST = tax% (full) |
| Either state is NULL | Skip GST | Store zero/null |

### 1.4 Calculation Function

**Location:** `src/procurement/po.py:709-756`

```python
def calculate_gst_amounts(amount, tax_percentage, source_state_id, destination_state_id) -> dict:
    # Returns: i_tax_percentage, s_tax_percentage, c_tax_percentage,
    #          i_tax_amount, s_tax_amount, c_tax_amount,
    #          tax_amount, tax_pct, stax_percentage
```

> **TODO:** Move this to `src/common/utils.py` or `src/common/gst_utils.py` for reuse across modules.

### 1.5 GST Storage Rule

GST is **always stored at line-item level** in parallel GST tables. Never at header level.

---

## 2. GST Database Tables

### 2.1 `po_gst` — Purchase Order GST (WORKING)

**Model:** `src/models/procurement.py:877-904`

| Column | Type | FK | Purpose |
|--------|------|-----|---------|
| `po_gst_id` | INT PK | — | Auto-increment ID |
| `po_dtl_id` | INT NULL | `proc_po_dtl.po_dtl_id` | FK to PO line item (mutually exclusive with po_additional_id) |
| `po_additional_id` | INT NULL | `proc_po_additional.po_additional_id` | FK to PO additional charge |
| `tax_pct` | DOUBLE | — | Total tax percentage (e.g., 18.0) |
| `stax_percentage` | DOUBLE | — | Combined state tax (SGST + CGST) |
| `s_tax_amount` | DOUBLE | — | SGST amount |
| `s_tax_percentage` | DOUBLE | — | SGST percentage |
| `i_tax_amount` | DOUBLE | — | IGST amount |
| `i_tax_percentage` | DOUBLE | — | IGST percentage |
| `c_tax_amount` | DOUBLE | — | CGST amount |
| `c_tax_percentage` | DOUBLE | — | CGST percentage |
| `tax_amount` | DOUBLE | — | Total tax amount |
| `active` | INT | — | Soft-delete (1=active) |

**Note:** `po_dtl_id` and `po_additional_id` are mutually exclusive — each GST record links to either a line item OR an additional charge, never both.

### 2.2 `proc_gst` — Inward/SR GST (EXISTS, NEVER POPULATED)

**Model:** `src/models/procurement.py:91-110`

| Column | Type | FK | Purpose |
|--------|------|-----|---------|
| `gst_invoice_type` | INT PK | — | Auto-increment ID (unusual name) |
| `proc_inward_dtl` | INT NULL | — | FK to `proc_inward_dtl.inward_dtl_id` (no formal FK constraint in model) |
| `tax_pct` | DOUBLE | — | Total tax percentage |
| `stax_percentage` | DOUBLE | — | Combined state tax |
| `s_tax_amount` | DOUBLE | — | SGST amount |
| `i_tax_amount` | DOUBLE | — | IGST amount |
| `i_tax_percentage` | DOUBLE | — | IGST percentage |
| `c_tax_amount` | DOUBLE | — | CGST amount |
| `c_tax_percentage` | DOUBLE | — | CGST percentage |
| `tax_amount` | DOUBLE | — | Total tax amount |
| `active` | INT | — | Soft-delete |
| `updated_by` | INT | — | Audit column |
| `updated_date_time` | DATETIME | — | Audit column |

**Schema gaps vs `po_gst`:**
- Missing `s_tax_percentage` column (SGST percentage stored separately)
- No FK to additional charges table (only links to line items)

### 2.3 `drcr_note_dtl_gst` — DR/CR Note GST (EXISTS, NEVER POPULATED)

**Model:** `src/models/procurement.py:977-994`

| Column | Type | FK | Purpose |
|--------|------|-----|---------|
| `drcr_note_dtl_gst_id` | INT PK | — | Auto-increment ID |
| `drcr_note_dtl_id` | INT NULL | `drcr_note_dtl.drcr_note_dtl_id` | FK to DR/CR note detail |
| `cgst_amount` | DOUBLE | — | CGST amount |
| `igst_amount` | DOUBLE | — | IGST amount |
| `sgst_amount` | DOUBLE | — | SGST amount |
| `active` | BOOLEAN | — | Soft-delete |

**Schema gaps:** Significantly simplified compared to `po_gst`:
- Missing `tax_pct` (total tax percentage)
- Missing `i_tax_percentage`, `c_tax_percentage`, `stax_percentage`
- Missing `s_tax_amount` (uses `sgst_amount` naming instead)
- Missing `tax_amount` (total tax)

> **MIGRATION NEEDED:** Add `tax_pct`, `i_tax_percentage`, `c_tax_percentage`, `s_tax_percentage`, `stax_percentage`, `tax_amount` columns for consistency.

### 2.4 `proc_inward_additional_gst` — NEW TABLE NEEDED

For storing GST on inward/SR additional charges. Separate from `proc_gst` (per user requirement).

**Proposed schema:**

| Column | Type | FK | Purpose |
|--------|------|-----|---------|
| `proc_inward_additional_gst_id` | INT PK | — | Auto-increment ID |
| `inward_additional_id` | INT NULL | `proc_inward_additional.inward_additional_id` | FK to additional charge |
| `tax_pct` | DOUBLE | — | Total tax percentage |
| `stax_percentage` | DOUBLE | — | Combined SGST + CGST |
| `s_tax_amount` | DOUBLE | — | SGST amount |
| `s_tax_percentage` | DOUBLE | — | SGST percentage |
| `i_tax_amount` | DOUBLE | — | IGST amount |
| `i_tax_percentage` | DOUBLE | — | IGST percentage |
| `c_tax_amount` | DOUBLE | — | CGST amount |
| `c_tax_percentage` | DOUBLE | — | CGST percentage |
| `tax_amount` | DOUBLE | — | Total tax amount |
| `active` | INT | — | Soft-delete (default 1) |

---

## 3. PO GST — Reference Implementation (Gold Standard)

### 3.1 Flow Overview

```
create_po / update_po
  │
  ├─ 1. Check co_config.india_gst (lines 830-841)
  │
  ├─ 2. Get supplier_state_id from party_branch_mst (lines 816-822)
  │     SELECT state_id FROM party_branch_mst WHERE party_mst_branch_id = :supplier_branch_id
  │
  ├─ 3. Get shipping_state_id from branch_mst (lines 824-828)
  │     SELECT state_id FROM branch_mst WHERE branch_id = :shipping_branch_id
  │
  ├─ 4. For each line item (lines 899-937):
  │     a. Get tax_percentage from item_mst
  │     b. Accept frontend GST amounts (igst, cgst, sgst)
  │     c. Derive percentages from amounts if needed
  │     d. Accumulate totals
  │
  ├─ 5. For each additional charge (lines 970-988):
  │     a. Get tax_pct from additional_charges_mst.default_value
  │     b. Call calculate_gst_amounts() server-side
  │
  ├─ 6. Insert po_gst records (lines 1057-1072)
  │     Uses insert_po_gst() from query.py:884-909
  │
  └─ 7. On update: delete_po_gst() first, then re-insert
        Uses delete_po_gst() from query.py:964-972
```

### 3.2 Key Code Locations

| Step | File | Lines | Function/Query |
|------|------|-------|---------------|
| Config check | `po.py` | 830-841 | `get_co_config_by_id_query()` |
| Supplier state | `po.py` | 816-822 | Inline SQL on `party_branch_mst` |
| Shipping state | `po.py` | 824-828 | Inline SQL on `branch_mst` |
| GST calculation | `po.py` | 709-756 | `calculate_gst_amounts()` |
| Insert GST | `query.py` | 884-909 | `insert_po_gst()` |
| Delete GST | `query.py` | 964-972 | `delete_po_gst()` — hard delete |
| Read GST | `query.py` | 1098-1119 | `get_po_gst_by_id_query()` |

### 3.3 PO GST Pattern: Frontend-Driven with Backend Validation

For **line items**, the PO accepts GST amounts from the frontend and derives percentages:

```python
# po.py:899-936 (simplified)
if india_gst and tax_percentage > 0:
    igst_amt = item.get("igst_amount", 0)
    cgst_amt = item.get("cgst_amount", 0)
    sgst_amt = item.get("sgst_amount", 0)
    tax_amt = igst_amt + cgst_amt + sgst_amt

    # Derive percentages from amounts
    if igst_amt > 0:
        igst_pct = tax_percentage
        sgst_pct = cgst_pct = 0
    else:
        sgst_pct = cgst_pct = tax_percentage / 2
        igst_pct = 0
```

For **additional charges**, the PO calculates GST server-side using `calculate_gst_amounts()`.

### 3.4 Update Pattern: Delete + Re-insert

```python
# Delete existing GST records for the PO
db.execute(delete_po_gst(), {"po_id": po_id})

# Re-insert all GST records
for gst_data in gst_records:
    db.execute(insert_po_gst(), gst_data)
```

---

## 4. Inward GST — GAP ANALYSIS

### 4.1 Current State

| What | Exists? | Location |
|------|---------|----------|
| `proc_gst` table | Yes | `src/models/procurement.py:91-110` |
| `co_config.india_gst` in setup | Yes | `src/procurement/inward.py:194-202` |
| GST calculation in create_inward | **NO** | `src/procurement/inward.py:566-824` |
| `insert_proc_gst()` query | **NO** | Not in `query.py` |
| GST fields in request payload | **NO** | No schema fields |
| State determination logic | **NO** | Not implemented |

### 4.2 Architectural Decision: Hybrid Approach

| Inward Type | GST Source | Logic |
|-------------|-----------|-------|
| PO-linked (has `po_dtl_id`) | Default from PO GST, allow override | Query `po_gst` via `po_dtl_id`, use as defaults; if frontend sends different values, use those |
| Non-PO (direct inward) | Calculate independently | Use supplier_branch_id + shipping_branch_id for state comparison |

### 4.3 What Needs to Be Built

1. **Query functions** (in `src/procurement/query.py`):
   - `insert_proc_gst()` — modeled on `insert_po_gst()`
   - `delete_proc_gst_by_inward()` — delete GST records by inward_id
   - `get_proc_gst_by_inward_id()` — read GST for an inward

2. **PO GST carry-forward query:**
   ```sql
   SELECT pg.* FROM po_gst pg
   JOIN proc_po_dtl ppd ON pg.po_dtl_id = ppd.po_dtl_id
   WHERE ppd.po_dtl_id = :po_dtl_id;
   ```

3. **State determination** in `create_inward`:
   - Supplier state: `SELECT state_id FROM party_branch_mst WHERE party_mst_branch_id = :supplier_branch_id`
   - Shipping state: `SELECT state_id FROM branch_mst WHERE branch_id = :ship_branch_id`
   - Note: `proc_inward` already has `bill_branch_id` and `ship_branch_id` columns

4. **GST logic in create/update endpoints**:
   - Check `co_config.india_gst`
   - For each line item: get tax_percentage, calculate or carry forward GST
   - Insert into `proc_gst`

---

## 5. SR (Stores Receipt) GST — GAP ANALYSIS

### 5.1 Current State

| What | Exists? | Location |
|------|---------|----------|
| Frontend GST calculation | Yes | UI calculates per-line GST |
| `proc_gst` table | Yes | Same table as Inward |
| SR queries reading proc_gst | Yes | `query.py:2087-2292` (Bill Pass queries) |
| GST write in `save_sr` | **NO** | `sr.py:380-534` |
| `insert_proc_gst()` query | **NO** | Not in `query.py` |
| GST in save payload | **PARTIAL** | Additional charges have GST; line items do NOT |

### 5.2 BUG: `india_gst` Hardcoded

**Location:** `src/procurement/query.py:1731`

```sql
-- CURRENT (BUG):
1 AS india_gst

-- SHOULD BE:
cc.india_gst
-- with JOIN: LEFT JOIN co_config cc ON cc.co_id = bm.co_id
```

This causes GST to always appear enabled in SR, even for companies without GST.

### 5.3 What Needs to Be Built

1. **Fix `india_gst` hardcode** in `get_inward_for_sr_query()` at `query.py:1731`
   - Add `LEFT JOIN co_config cc ON cc.co_id = bm.co_id`
   - Replace `1 AS india_gst` with `cc.india_gst`

2. **Add GST write to `save_sr`** (`sr.py:380-534`):
   - Accept GST fields from frontend in line item payload
   - After updating `proc_inward_dtl`, insert/update `proc_gst`
   - Delete existing `proc_gst` records before re-inserting

3. **Add GST to additional charges save** (if separate table created):
   - Save to `proc_inward_additional_gst`

4. **Bill Pass auto-fix:** Once `proc_gst` is populated by SR save, Bill Pass queries will automatically show correct GST values.

---

## 6. DR/CR Notes GST — GAP ANALYSIS

### 6.1 Current State

| What | Exists? | Location |
|------|---------|----------|
| `drcr_note_dtl_gst` table | Yes | `src/models/procurement.py:977-994` |
| Read query joining GST | Yes | `query.py:1971` |
| GST write in create_drcr_note | **NO** | `drcr_note.py:284-362` |
| GST in auto-created DRCR (SR approval) | **NO** | `sr.py:634-712` |
| GST fields in DrcrNoteLineItem schema | **NO** | `drcr_note.py:51-59` |
| `insert_drcr_note_dtl_gst()` query | **NO** | Not in `query.py` |

### 6.2 DR/CR GST Calculation Rules

| Note Type | Base Amount for GST | Logic |
|-----------|-------------------|-------|
| Rate difference | `(new_rate - old_rate) * qty` = difference amount | Calculate GST on the difference amount |
| Quantity rejection | Parent inward line amount (after discount) | Calculate GST on the parent amount per rejected qty |

Both use the same state comparison (IGST vs CGST/SGST) from the parent inward's supplier/shipping branch.

### 6.3 What Needs to Be Built

1. **Schema migration:** Add percentage columns to `drcr_note_dtl_gst`:
   ```sql
   ALTER TABLE drcr_note_dtl_gst
     ADD COLUMN tax_pct DOUBLE NULL,
     ADD COLUMN i_tax_percentage DOUBLE NULL,
     ADD COLUMN c_tax_percentage DOUBLE NULL,
     ADD COLUMN s_tax_percentage DOUBLE NULL,
     ADD COLUMN stax_percentage DOUBLE NULL,
     ADD COLUMN tax_amount DOUBLE NULL;
   ```

2. **Query functions** (in `src/procurement/query.py`):
   - `insert_drcr_note_dtl_gst()`
   - `delete_drcr_note_dtl_gst()`

3. **Update `DrcrNoteLineItem` schema** (`drcr_note.py:51-59`):
   ```python
   igst_amount: Optional[float] = None
   cgst_amount: Optional[float] = None
   sgst_amount: Optional[float] = None
   tax_amount: Optional[float] = None
   tax_percentage: Optional[float] = None
   ```

4. **Add GST to manual DRCR creation** (`create_drcr_note`):
   - Get state info from parent inward
   - Calculate GST based on note type (rate-diff or qty-diff)
   - Insert into `drcr_note_dtl_gst`

5. **Add GST to auto-created DRCR** (`approve_sr` in `sr.py:634-712`):
   - When creating DRCR notes for rate differences: GST on difference amount
   - When creating DRCR notes for rejections: GST on parent line amount
   - Insert into `drcr_note_dtl_gst`

---

## 7. Bill Pass GST — Read-Only (Depends on SR)

### 7.1 Current State

Bill Pass queries at `query.py:2087-2292` already JOIN `proc_gst`:

```sql
LEFT JOIN proc_gst pg ON pg.proc_inward_dtl = pid.inward_dtl_id
-- Returns: SUM(c_tax_amount + s_tax_amount + i_tax_amount) AS sr_tax
```

**Problem:** `proc_gst` is never populated → all tax values show as 0.

**Fix:** No changes needed to Bill Pass. Once SR writes to `proc_gst`, these queries will automatically return correct values.

---

## 8. Known Bugs

### 8.1 Cross-Module Bugs (SR / Inward / DRCR / Bill Pass)

| # | Severity | Description | Location |
|---|----------|-------------|----------|
| 1 | **CRITICAL** | `india_gst` hardcoded as `1` in SR query | `query.py:1731` |
| 2 | **CRITICAL** | `proc_gst` never populated — SR/Inward write no GST | `sr.py:380-534`, `inward.py:566-824` |
| 3 | **CRITICAL** | `drcr_note_dtl_gst` never populated | `drcr_note.py:284-362`, `sr.py:634-712` |
| 4 | **HIGH** | Bill Pass GST always shows 0 (depends on bug #2) | `query.py:2087-2292` |
| 5 | **MEDIUM** | `proc_gst` missing `s_tax_percentage` column | `src/models/procurement.py:91-110` |
| 6 | **MEDIUM** | `drcr_note_dtl_gst` missing percentage columns | `src/models/procurement.py:977-994` |
| 7 | **MEDIUM** | No `insert_proc_gst()` or `delete_proc_gst()` query functions exist | `query.py` |
| 8 | **MEDIUM** | No `insert_drcr_note_dtl_gst()` query function exists | `query.py` |
| 9 | **LOW** | `proc_gst` PK named `gst_invoice_type` (misleading) | Model |
| 10 | **LOW** | `po_gst.get` query doesn't filter by `active=1` | `query.py:1098-1119` |
| 11 | **LOW** | `po_gst` delete is hard-delete, not soft-delete | `query.py:964-972` |
| 12 | **HIGH** | SR query joins `party_branch_mst` on `party_id` (not unique) instead of `party_mst_branch_id`. Suppliers with multiple branches return duplicate rows → wrong supplier state picked arbitrarily. PO correctly uses `supplier_branch_id`. | `query.py:1736` |
| 13 | **MEDIUM** | Bill Pass totals ignore `discount_amount` — uses `approved_qty * accepted_rate` without subtracting `discount_amount`. Overstates totals when discounts exist. | `query.py:2096, 2267` |
| 14 | **MEDIUM** | Bill Pass totals exclude `proc_inward_additional` — only sums line items, not additional charges. Causes mismatch with header `net_amount` which includes charges. | `query.py` bill pass subqueries |
| 15 | **LOW** | `stax_percentage` aliased as `sgst_percent` in Bill Pass detail query. This is the combined SGST+CGST %, not SGST alone. Misleading display on frontend. | `query.py:2273`, `billpass.py:274` |
| 16 | **LOW** | `insert_po_gst()` raw SQL does not include `active` column. Relies on DB-level DEFAULT 1 instead of explicit value. Inconsistent with `proc_gst` queries that filter `active=1`. | `query.py:884-909` |

### 8.2 PO GST Bugs (Reference Implementation)

Even the PO "gold standard" has issues that must be fixed before replicating the pattern:

| # | Severity | Description | Location |
|---|----------|-------------|----------|
| P1 | **CRITICAL** | Backend does NOT validate frontend GST amounts against actual state comparison. Frontend sends igst/cgst/sgst amounts, backend accepts them without verifying they match supplier vs shipping state. Allows GST miscalculation if frontend sends wrong split. | `po.py:899-937`, `po.py:1482-1519` |
| P2 | **CRITICAL** | `s_tax_percentage` (individual SGST %) is never stored in `po_gst`. The INSERT query only stores `stax_percentage` (combined SGST+CGST %). No column for individual SGST percentage — data loss for GST audit trail. | `query.py:884-909`, `models/procurement.py:877-904` |
| P3 | **MEDIUM** | NULL `state_id` on `party_branch_mst` or `branch_mst` causes silent GST skip for additional charges. No error raised — user won't know why charges have no tax. | `po.py:970` condition check |
| P4 | **MEDIUM** | GET PO response returns only amounts (`igst`, `sgst`, `cgst`) but NOT percentages (`i_tax_percentage`, `c_tax_percentage`). When editing a PO, frontend must recalculate instead of preserving original values. | `po.py:1300-1304` |
| P5 | **MEDIUM** | Backend ignores `apply_tax` flag from frontend for additional charges. Users cannot disable tax on specific charges. | `po.py:970-988` |
| P6 | **MEDIUM** | `item_mst.tax_percentage = NULL` results in silent GST skip (tax_percentage defaults to 0.0, then condition `tax_percentage > 0` is false). No warning to user. | `po.py:872-879` |
| P7 | **MEDIUM** | Floating-point rounding mismatch: frontend rounds to 2 decimal places via `.toFixed(2)`, backend does pure float math with no rounding. Can cause mismatches for certain discount/amount combinations. | `po.py:731-743` vs frontend |
| P8 | **MEDIUM** | Hard delete of `po_gst` records (DELETE FROM) but soft delete of `proc_po_dtl` (SET active=0). Inconsistent audit trail — detail lines survive deletion but their GST data is permanently lost. | `query.py:964-972` vs `query.py:947-954` |
| P9 | **LOW** | Confusing field naming: `stax_percentage` means "combined state tax" (SGST + CGST), not "state tax percentage". Should be `combined_state_tax_pct` for clarity. | `po.py:754` |
| P10 | **LOW** | HSN code from item_mst stored without format validation (should be 4-8 digits for Indian GST). | `po.py:873` |

### 8.3 Recommended Fix Priority

**Immediate (before replicating PO pattern to other modules):**
1. **P1** — Add server-side GST validation: recalculate using `calculate_gst_amounts()` and compare with frontend values
2. **P2** — Add `s_tax_percentage` to `insert_po_gst()` query (or accept it's stored in `stax_percentage/2`)
3. **#1** — Fix `india_gst` hardcode in SR query

**Short-term:**
4. **P4** — Return GST percentages in GET PO response
5. **P7** — Add `round(value, 2)` to `calculate_gst_amounts()` function
6. **#2, #3** — Implement GST writes for SR and DRCR

**Medium-term:**
7. **P5** — Respect `apply_tax` flag for additional charges
8. **P6** — Log warning when item has no tax_percentage
9. **P8** — Consider soft-delete for `po_gst` to maintain audit trail

---

## 9. Implementation Roadmap (Priority Order)

### Phase 1: SR GST (Highest Impact — Fixes Bill Pass too)

1. Fix `india_gst` hardcode at `query.py:1731`
2. Create `insert_proc_gst()` query function
3. Create `delete_proc_gst_by_inward()` query function
4. Add GST write logic to `save_sr` in `sr.py`
5. Verify Bill Pass auto-reads correct values

### Phase 2: Inward GST

6. Add GST calculation to `create_inward` (hybrid: PO carry-forward + independent)
7. Add GST calculation to `update_inward` (if exists)
8. Create `get_proc_gst_by_inward_id()` read query

### Phase 3: Additional Charges GST

9. Create `proc_inward_additional_gst` table (migration)
10. Create ORM model `ProcInwardAdditionalGst`
11. Create insert/delete/read query functions
12. Add additional charges GST to SR save
13. Add additional charges GST to Inward save

### Phase 4: DR/CR Notes GST

14. Migrate `drcr_note_dtl_gst` to add percentage columns
15. Create `insert_drcr_note_dtl_gst()` query function
16. Update `DrcrNoteLineItem` schema with GST fields
17. Add GST to manual `create_drcr_note`
18. Add GST to auto-created DRCR notes in `approve_sr`

### Phase 5: Shared Utilities

19. Move `calculate_gst_amounts()` from `po.py` to `src/common/gst_utils.py`
20. Update PO imports to use shared function
21. Use shared function in SR, Inward, and DRCR modules

---

## 10. Query Function Templates

### insert_proc_gst (to be created)

```python
def insert_proc_gst():
    sql = """INSERT INTO proc_gst (
        proc_inward_dtl,
        tax_pct, stax_percentage,
        s_tax_amount, i_tax_amount, i_tax_percentage,
        c_tax_amount, c_tax_percentage,
        tax_amount, active, updated_by
    ) VALUES (
        :proc_inward_dtl,
        :tax_pct, :stax_percentage,
        :s_tax_amount, :i_tax_amount, :i_tax_percentage,
        :c_tax_amount, :c_tax_percentage,
        :tax_amount, 1, :updated_by
    );"""
    return text(sql)
```

### delete_proc_gst_by_inward

```python
def delete_proc_gst_by_inward():
    sql = """DELETE FROM proc_gst
    WHERE proc_inward_dtl IN (
        SELECT inward_dtl_id FROM proc_inward_dtl WHERE inward_id = :inward_id
    );"""
    return text(sql)
```

### insert_drcr_note_dtl_gst (to be created)

```python
def insert_drcr_note_dtl_gst():
    sql = """INSERT INTO drcr_note_dtl_gst (
        drcr_note_dtl_id,
        cgst_amount, igst_amount, sgst_amount,
        tax_pct, i_tax_percentage, c_tax_percentage, s_tax_percentage,
        stax_percentage, tax_amount, active
    ) VALUES (
        :drcr_note_dtl_id,
        :cgst_amount, :igst_amount, :sgst_amount,
        :tax_pct, :i_tax_percentage, :c_tax_percentage, :s_tax_percentage,
        :stax_percentage, :tax_amount, 1
    );"""
    return text(sql)
```
