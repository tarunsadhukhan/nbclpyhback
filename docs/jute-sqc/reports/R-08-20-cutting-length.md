# R-08-20 — Cutting Length (I.S.O.)

**Stage:** finishing (cut-bag / sacking-bag cutting — the cut length of woven cloth pieces)  **Status:** UNBUILT
**Source tab:** `R020` ("R-08-20 CUTTING LENGTH (I.S.O.)", master "Daily Summary Date Select")   **DSR workbook:** `1-1fz_CSGbQqHmixMAceg3VSayHedc3cIkE45ChGctHY` (DSR!A1:W32, not shared)

## 1. Purpose
Checks the **cut length** of cloth pieces against the standard (target) length, to confirm the cutting operation holds dimensional consistency. Each day, **20 pieces** are measured; the report computes the daily Average, sample StDev and CV against the per-piece STD. Low CV = consistent cutting; drift in the average from STD = mis-set cutting length.

> Note: the title says "measured in INCH" but the STD row is labelled "STD(cm)". The cached values (~78) and STD = 78 are consistent with **inches** for a ~78" cut piece. The "(cm)" label appears to be a mislabel in the sheet. ⚠️ Confirm unit (see §8).

## 2. Inputs (the data-entry fields)

The tab is a **date-matrix**: rows = READING 1..20 (+ STD, Average, Stdev, CV), columns = one per **measurement date**. Each column is one day's reading-set of 20 pieces. The master tab shows ~15 dates (2026-01-02 … 2026-01-19). In VOW, **one entry = one date's 20 readings**.

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| `entry_date` | date | — (header) | yes | One column per date. Cached dates 2026-01-02 … 2026-01-19. |
| `std_length` | number | per-piece standard (see §3) | yes | Cached STD = **78** for every date. Same for all readings in a column. |
| `reading_1..20` | number | operator entry | yes | 20 measured cut lengths. Cached col 2026-01-02: 78,78,79,78,78,78,78,78,78,78,78,79,77,78,78,78,78,78,78,78. |

**Header vs per-reading:** `entry_date` + `std_length` are header (per date). `reading_1..20` are the 20 per-reading values. No quality/machine/spell columns appear on this tab (it is a single product line's daily cut-length check). ⚠️ Confirm whether a **quality/machine** should be added in VOW (the Google tab tracks only one stream).

## 3. Standards & constants used

| Standard | Example in sheet | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD cut length** (target length per piece) | `78` (constant across all dates) | The target is per **quality / product** (a 78" cut for that sacking/hessian bag size). Add `std_cut_length` to the **line/product quality master** that identifies the cut item. Since this tab carries no quality column, the std currently lives only as a typed-in row. **NEEDS OWNER DECISION** (see below). |
| **CV% acceptance band** | Not printed (CV computed but no pass band shown). Cached CV is tiny (~0.005 = 0.5%). | If a CV band is wanted (e.g. "≤2%"), store `std_cv_low`/`std_cv_high` — see process×quality note below. |

**⚠️ Process×quality standards-storage question (RAISED):** the STD length (78) and any CV% band are **process×quality** values (cutting stage × specific bag/cloth quality). The tab has **no quality column**, so today the standard is just a manually-typed STD row. Per decision #2 (no new standalone standards table), proposed reconciliations:
1. Add a **quality/product selector** to the VOW entry (link to the line/product quality master) and add `std_cut_length` (+ optional `std_cv_low`/`std_cv_high`) to that quality master — a quality implies its standard cut length. **PREFERRED.**
2. If cutting standards vary by **machine** (different cutting machines/sizes), key `std_cut_length` on the **`machine_mst`** row instead (a machine implies its process/size). Briefing §3 explicitly allows adding `std_weight`/`std_cv_*`-style columns to `machine_mst` since a machine implies its process — the same applies to `std_cut_length`.
**NEEDS OWNER DECISION:** is cut-length standard keyed by quality, by machine, or both — and store the CV band there too.

## 4. Calculations (formulas)

Per **date column** (n = 20 readings):

- **Average** = mean of the 20 readings.
  - Worked (2026-01-02): sum = 1561, 1561/20 = **78.05** ✓ (matches cached 78.05)
  - Worked (2026-01-03): cached **78.2**; (sum 1564/20 = 78.2) ✓
- **Stdev** = **SAMPLE** standard deviation (n−1) → Python `statistics.stdev`, SQL `STDDEV_SAMP`.
  - Worked (2026-01-02): readings have sixteen 78s, three 79s, one 77. Variance(sample) = Σ(x−78.05)²/19. Σ of squared devs = 3×(0.95²) + 1×(−1.05²) + 16×(−0.05²) = 3×0.9025 + 1.1025 + 16×0.0025 = 2.7075 + 1.1025 + 0.04 = 3.85; /19 = 0.2026; √ = **0.3940** ✓ (matches cached 0.3940344628…). Confirms **sample (n−1)** stdev. (Population stdev would give 0.3840 — does NOT match.) ✓
- **CV** = Stdev / Average (the cached CV is a **fraction**, not ×100).
  - Worked (2026-01-02): 0.3940344628 / 78.05 = **0.005048487…** ✓ (matches cached CV 0.005048487672…).
  - **CV% variant:** this is the **weight/dimension family** variant — `CV = StDev / mean`. The cached column is the raw ratio (0.005); VOW should display **CV% = ratio × 100 = 0.50%** for readability (state both). ⚠️ Confirm display preference (fraction vs %).
- **Deviation from STD** (proposed, not in sheet): `avg − std_length` (78.05 − 78 = **+0.05"**). Optional pass flag vs tolerance/CV band.

No correction/MR is involved (pure linear measurement). No buckets on this tab.

## 5. Worked example (real data)

**Date 2026-01-02, 20 cut-length readings (inches):**
`[78,78,79,78,78,78,78,78,78,78,78,79,77,78,78,78,78,78,78,78]`
- STD = 78
- Average = 1561 / 20 = **78.05**
- Stdev (sample, n−1) = **0.3940** (Σsq devs 3.85 / 19 = 0.2026 → √ = 0.3940)
- CV (ratio) = 0.3940 / 78.05 = **0.005048**  →  **CV% = 0.50%**
- Deviation from STD = 78.05 − 78 = **+0.05"** (essentially on target; very consistent cutting)

All four outputs match the cached tab exactly, confirming the formulas.

## 6. Proposed VOW data model

Flat header + JSON readings (morrah-style) — one row per date's 20 readings. Insert-only + soft-delete. Stats recomputable but cached for the grid.

```python
class JuteSqcCuttingLength(Base):
    """R-08-20 Cutting Length — one row per (date[, quality/machine]) set of 20 readings."""
    __tablename__ = "jute_sqc_cutting_length"

    cutting_length_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id             = Column(Integer, nullable=False, index=True)
    branch_id         = Column(Integer, nullable=True)
    entry_date        = Column(Date, nullable=False, index=True)
    quality_id        = Column(Integer, nullable=True)        # FK -> line/product quality master (if adopted, §3)
    mc_id             = Column(Integer, nullable=True)         # machine_mst (if std keyed by machine, §3)
    std_length        = Column(DECIMAL(10, 2), nullable=False) # target cut length (snapshot, e.g. 78)
    readings          = Column(String(500), nullable=False)    # JSON of 20 readings (morrah pattern)
    calc_avg          = Column(DECIMAL(10, 3), nullable=True)  # cached
    calc_stdev        = Column(DECIMAL(10, 4), nullable=True)  # sample stdev, cached
    calc_cv_pct       = Column(DECIMAL(10, 4), nullable=True)  # CV% = stdev/avg*100, cached
    active            = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by        = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```

- **PK:** `cutting_length_id`. Scoping: `co_id`, `branch_id`, `entry_date`, `active`, `updated_by`.
- Readings as JSON (fixed count, like `JuteSqcMorrahWt.weights`) — no detail table needed. Stats computed in a `compute_cutting_stats(readings, std_length)` helper mirroring `compute_morrah_stats` (avg, `statistics.stdev`, CV% = stdev/avg×100). ⚠️ Confirm reading count is fixed at 20.

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`, `src/juteSQC/cuttingLength.py` + `query.py`):
- `GET /cutting_length_create_setup` — returns std length (from quality/machine master if linked) + optional quality/machine dropdowns.
- `POST /create_cutting_length` — validates 20 readings positive, snapshots `std_length`, computes avg/stdev/cv via `compute_cutting_stats`, inserts.
- `GET /get_cutting_length_by_date` — readings + stats for a date (and a **date-range / trend** variant to reproduce the multi-column matrix view: avg/stdev/cv per date across a month).
- `GET /get_cutting_length_table` — paginated list (like `get_morrah_wt_table`).
- `POST /delete_cutting_length` — soft delete.

Frontend (`src/app/dashboardportal/juteSQC/r-08-20/`):
- **Entry form** (mobile): one date's 20 cut-length readings (optionally pick quality/machine) → live Average / Stdev / CV%. Honors `co_id`/`branch_id`.
- **Summary view** (date-driven + date-range): single-date detail, plus a **trend grid** matching the Google matrix — columns = dates, rows = STD / Average / Stdev / CV% — for a chosen month. Route consts `CUTTING_LENGTH_*` in `api.ts`; `fetchWithCookie`.

**Masters to link:** `spell_mst` only if a shift is added (none today); the line/product quality master and/or `machine_mst` for the std cut length (§3). Otherwise no master dropdowns — the std is the only reference.

## 8. Open questions (NEEDS OWNER DECISION)

- **Unit:** title says INCH, STD row labelled "STD(cm)". Values ~78 fit inches for a cut piece; "(cm)" looks like a mislabel. Confirm the unit and fix the label in VOW.
- **Where does the STD cut length live?** The tab has no quality/machine column. Add a quality/product selector (preferred) or key it on `machine_mst`? And confirm the std value(s) per quality (78 is the only one cached).
- **CV display:** cached CV is a raw ratio (0.005). Display as **CV% (×100)** in VOW? And is there an acceptance band (e.g. CV% ≤ 2%)? If yes, store `std_cv_low`/`std_cv_high` on the chosen master.
- **Reading count fixed at 20?** Cache shows 20 per date — confirm this is always 20 (drives validation, like morrah's exactly-10 rule).
- **Should a quality and/or machine/operator be captured** per date (the Google tab tracks a single stream — VOW may want to attribute the check)?
- **Deviation/pass flag:** owner wants a flag on `avg − std` and/or on CV band? (none printed today).
- **Trend view scope:** confirm the date-range matrix (month of columns) is the desired summary, matching the current sheet layout.
