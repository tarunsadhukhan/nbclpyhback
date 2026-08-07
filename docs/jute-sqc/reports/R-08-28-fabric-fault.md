# R-08-28 — Fabric Fault (I.S.O)
**Stage:** weaving (woven-cloth inspection)  **Status:** UNBUILT
**Source tab:** `R-08-28  FABRIC FAULT (I.S.O)` (master "Daily Summary Date Select")  **DSR workbook:** `1gZDM2LgZF-Mp4ipNVKFvdQ1xfwLdaXjflQc8qw5fbDk` (DSR!A1:AB30, not shared)

## 1. Purpose
Weaving fabric-fault audit: a fixed checklist of cloth defects is counted per inspected piece (one
column per loom/piece). The report sums each fault type across all pieces (TOTAL) and converts to a
faults-per-piece **SCORE**, plus an overall fabric SCORE for the day. It is the qualitative cloth-defect
counterpart to the dimensional R-08-21 width/picks check.

## 2. Inputs (the data-entry fields)

The sheet is a **matrix**: columns = inspected pieces, rows = fault types. In VOW each column becomes one
saved "piece" record; faults are entered per piece.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header (report date).** Cached `2026-01-05`. |
| co_id / branch_id | int | sidebar | yes | **Header.** |
| shift | int (FK) | `spell_mst` (spell_id) — values `A`/`B` | yes | **Per piece.** Cached: B,B,B,B,B,B,B,A,B,A,B,B,A. (`A`/`B` are shift/spell codes.) |
| quality (cloth quality) | int (FK) | cloth-quality master (see §3) | yes | **Per piece.** Cached all `SACKING S4(22.50"- 5x 7-9.44)`. |
| loom_no | int (FK) | `machine_mst` (machine_id), Weaving dept | yes | **Per piece.** Cached: 32,36,58,45,43,24,44,62,40,66,59,12,42. |
| date_of_weaving | date | operator | yes | **Per piece.** When the cloth was woven (cached `2026-01-03`, one `2026-01-05`). Distinct from the report entry_date. |
| fault counts (14 types) | int | operator (count) | per piece | **Per piece.** One integer count per fault type (blank = 0). Fault list in §3. |
| remarks | text | operator | optional | Free text per piece (sheet row "REMARKS"). |

A "piece record" = one column = one inspected loom/cloth piece with its 14 fault counts. One save can be a
single piece, or a batch of pieces for the date.

## 3. Standards & constants used

The **fault checklist** is the standard (fixed 14 defect types, in order):

| # | Fault type | Cached row TOTAL | Cached row SCORE |
|---|---|---|---|
| 1 | Single Broken Warp | 0 | 0 |
| 2 | Minor Gaw | 93 | 5.8125 |
| 3 | Major Gaw | 7 | 0.4375 |
| 4 | Minor Multiple Broken Warp | 1 | 0.0625 |
| 5 | Major multiple Broken Warp | 0 | 0 |
| 6 | Minor Float | 11 | 0.6875 |
| 7 | Major Float | 6 | 0.375 |
| 8 | Mildew Stain | 0 | 0 |
| 9 | Hole/Snarl | 0 | 0 |
| 10 | Weft Bar Minor | 0 | 0 |
| 11 | Curled Selvage | 0 | 0 |
| 12 | Weft Bar Major | 0 | 0 |
| 13 | Cut Selvage | 0 | 0 |
| 14 | Loopy Selvage | 0 | 0 |
| 15 | Smash | 0 | 0 |
| | **Grand** | **118** | **7.375** |

(15 rows listed; "Single Broken Warp" + 14 others — the checklist count is fixed.)

| Standard / constant | Cached value | Where it lives in VOW (decision #2) |
|---|---|---|
| **Fault-type checklist** (fixed defect names + order) | 15 named rows above | A small **fault-type master** is the natural home — but decision #2 forbids new standalone *standards* tables. These are an **enumerated checklist**, not a numeric standard; propose a `jute_sqc_fault_type_mst` lookup ONLY for the defect-name list (or a Python enum/constant list). ⚠️ NEEDS OWNER DECISION (see below) — this is a list-of-categories, not a per-quality threshold. |
| **Pieces inspected (N)** | 16 columns | Derived = count of piece records for the date. Drives the SCORE divisor. |
| **Per-fault SCORE weight** | 0.0625 = **1/16** = 1/N | NOT a stored standard — it is `1 / pieces_inspected`. 93 × (1/16) = 5.8125 ✓. So SCORE = faults ÷ pieces inspected (faults-per-piece). |

**⚠️ process × quality storage:** This report has **no per-quality weight/CV band**, so the
process×quality standards-storage question is **not numerically triggered**. The only "standard" is the
fixed fault checklist. The open design question here is instead: **should defect names live in a small
lookup master or a code constant** (decision #2 leans away from new tables; a checklist enum is acceptable).

## 4. Calculations (formulas)

Let N = number of inspected pieces (columns) for the date. Cached N = 16.

- **Per-piece Total** = sum of that piece's 14 fault counts (column total). Piece (loom 36): Minor Gaw 13 +
  Major Float 1 + Minor Float 3 = **17** ✓ (cached column total 17). Piece (loom 32): Minor Gaw 3 + Minor
  Float 1 = **4** ✓.
- **Per-fault Total** = sum of that fault across all pieces (row total). Minor Gaw row
  `[3,13,5,5,4,7,8,4,11,3,9,3,3,8,3,4]` → **93** ✓.
- **Per-fault SCORE** = row Total ÷ N = row Total ÷ pieces inspected. Minor Gaw: 93 / 16 = **5.8125** ✓.
  Major Gaw: 7 / 16 = **0.4375** ✓. Minor Float: 11 / 16 = **0.6875** ✓.
- **Grand TOTAL** = Σ all fault counts = **118** ✓ (= Σ per-fault totals = Σ per-piece totals).
- **Grand SCORE** = Grand Total ÷ N = 118 / 16 = **7.375** ✓ (= Σ per-fault SCOREs = faults per piece).

No StDev, no CV%, no moisture correction, no count conversion. **CV% variant: none** — this is a pure
counting/scoring report. ⚠️ Confirm: N = "pieces inspected" = number of columns; if some columns are blank
placeholders, N should be the count of pieces actually entered (the 16 trailing zero columns in the TOTAL row
are empty placeholders → real N = 16 non-empty? cached shows 16 data columns then padding — derive N from
non-empty piece records).

## 5. Worked example (real data)

Date 2026-01-05, piece = **loom 36, shift B, SACKING S4, woven 2026-01-03**:
- Minor Gaw = 13, Major Float = 1, Minor Float = 3, all other faults = 0
- Per-piece Total = 13 + 1 + 3 = **17** ✓

Day roll-up across 16 pieces:
- Minor Gaw row total = **93** → SCORE 93/16 = **5.8125**
- Grand Total = **118** → Grand SCORE 118/16 = **7.375** ✓

## 6. Proposed VOW data model

Header (one inspected piece) + detail (per-fault count). Storing only non-zero fault rows keeps it sparse.

```python
class JuteSqcFabricFault(Base):                 # header: one inspected piece/column
    __tablename__ = "jute_sqc_fabric_fault"
    fabric_fault_id      = Column(Integer, primary_key=True, autoincrement=True)
    co_id                = Column(Integer, nullable=False, index=True)
    branch_id            = Column(Integer, nullable=True)
    entry_date           = Column(Date, nullable=False, index=True)   # report date
    spell_id             = Column(Integer, nullable=True)             # shift A/B -> spell_mst
    quality_id           = Column(Integer, nullable=False, index=True)# cloth-quality master FK
    loom_id              = Column(Integer, nullable=True)             # machine_mst.machine_id
    loom_no              = Column(Integer, nullable=True)             # raw loom number
    date_of_weaving      = Column(Date, nullable=True)
    remarks              = Column(String(255), nullable=True)
    inspector_name       = Column(String(120), nullable=True)        # "Saiba Hembram"
    active               = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by           = Column(Integer, nullable=True)
    updated_date_time    = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class JuteSqcFabricFaultDtl(Base):              # one fault count for a piece (non-zero rows only)
    __tablename__ = "jute_sqc_fabric_fault_dtl"
    fabric_fault_dtl_id  = Column(Integer, primary_key=True, autoincrement=True)
    fabric_fault_id      = Column(Integer, nullable=False, index=True)
    fault_type_id        = Column(Integer, nullable=False)           # -> fault-type lookup/enum
    fault_count          = Column(Integer, nullable=False, default=0)
```

Optional companion lookup (⚠️ owner decision §8): `jute_sqc_fault_type_mst (fault_type_id, fault_name,
sort_order, active)` seeded with the 15 defect names — OR a Python constant list in `constants.py`.
Insert-only + soft-delete. Per-fault TOTAL/SCORE and grand TOTAL/SCORE are **recomputed at read** over the
date's piece records (do not persist scores).

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`):
- `GET /fabric_fault_create_setup` — dropdowns: cloth qualities, looms (`machine_mst`, Weaving), spells
  (`spell_mst`), and the fixed fault-type list (lookup or constant).
- `POST /fabric_fault_save` — insert one piece header + its non-zero fault detail rows (or a batch).
- `GET /fabric_fault_by_date` — for a date, return all piece records, the fault matrix, per-fault TOTAL+SCORE,
  and grand TOTAL+SCORE (computing N = piece count).
- `GET /fabric_fault_delete` — soft delete a piece by id.

Frontend (`src/app/dashboardportal/juteSQC/r-08-28/`): mobile-first per-piece form — date, shift, quality,
loom, date-of-weaving, then the 15-row fault checklist with number inputs (default 0) + remarks; live
per-piece total. Desktop summary = the fault matrix (faults × pieces) with TOTAL and SCORE columns/rows like
the sheet. Route consts in `api.ts` `apiRoutesPortalMasters` (`FABRIC_FAULT_SETUP`, `FABRIC_FAULT_SAVE`,
`FABRIC_FAULT_BY_DATE`, `FABRIC_FAULT_DELETE`); calls via `fetchWithCookie`; hooks
`useFabricFaultSetup`/`useFabricFaultByDate`; `_components/` Form + Matrix grid.

**Masters to link:** cloth-quality master (quality), `machine_mst` (looms, Weaving dept), `spell_mst` (shift
A/B). **Std columns to add:** none numeric; only the **fault-type list** (lookup master or constant) — owner
to choose.

## 8. Open questions (NEEDS OWNER DECISION)
- **Fault-type list home:** a small `jute_sqc_fault_type_mst` lookup table vs a hard-coded constant list?
  (Decision #2 discourages new standalone *standards* tables; a category lookup is borderline — owner decides.)
  Confirm the canonical 15 defect names + order + which are "Minor"/"Major" pairs.
- **Per-fault SCORE weight** is `1 / pieces_inspected` (= 0.0625 at N=16) — confirm SCORE = faults ÷ pieces
  inspected, and that N is the count of inspected pieces for the date (not a fixed sample size).
- Are some defect counts **weighted differently** (e.g. Major faults heavier than Minor)? Cached data shows a
  uniform 1/16 weight, so no per-fault weighting is applied — confirm there is no demerit-point weighting.
- **Shift A/B → `spell_mst`:** confirm A/B map to spell codes (vs a separate shift master).
- Which master holds the **cloth quality** `SACKING S4(22.50"- 5x 7-9.44)` (item_mst cloth vs jute_quality_mst)?
  (Shared with R-08-21 — must be the same master.)
- **Granularity of save:** one record per inspected piece (column), or one batch record per date? (Model above
  assumes per-piece, matching the matrix columns.)
- `date_of_weaving` vs `entry_date` — both captured per piece; confirm both are required.
