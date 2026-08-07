# R-08-17 — Yarn T.P.I & T.P.I. CV% (I.S.O.)
**Stage:** spinning  **Status:** UNBUILT
**Source tab:** `R-08-17 YARN T.P.I & T.P.I. CV% (I.S.O.)` (master "Daily Summary Date Select")   **DSR workbook:** `1QB_BA2rMwXZ-1bz4FsWXi7iEnNFABBdNy1zgcRYGz84` (DSR!A1:M38, not shared)

## 1. Purpose
Measures the **twist inserted into spun jute yarn** — Twist Per Inch (TPI) — on a spinning frame, by taking 20 untwist-test readings on yarn of a given count/quality. It confirms the frame's twist matches the standard TPI for that count and that twist is uniform (low CV%). Under/over-twist directly affects yarn strength and downstream weaving.

## 2. Inputs (the data-entry fields)
The cached tab is **transposed** (fields listed down column A as a row-template) and contains the field labels only — no populated reading rows in this cache. Header `LAST STUDY DONE ON = 2025-11-21` (this is a periodic study, not every day). One saved test = one **(date, frame, quality, count)** group of 20 readings.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| date | date | entry header | yes | Test date (`2026-01-05` in header). |
| spg_frame_no | int | **`machine_mst`** (`machine_id`, `mech_code`, `machine_name`); spinning frame, like spinning SQC `mc_id` | yes (header) | "SPG FRAME NO." Map to `machine_mst.machine_id`, filter to spinning frames. |
| quality | int | **`item_mst` (yarn item)** + `jute_yarn_mst` | yes (header) | "QUALITY" — yarn quality (e.g. Hessian/Sacking warp/weft). Drives STD.TPI lookup. |
| count_lbs | decimal | from yarn item / `jute_yarn_mst` (std count) or operator | yes (header) | "COUNT(LBS)" — yarn count in lb. STD.TPI depends on count. |
| reading_1 … reading_20 | decimal ×20 | operator (per-reading) | yes (per-reading) | 20 measured TPI readings (twist tester). Sample size **n = 20**. |
| prepared_by | text | `user_mst` | no | Footer "Sanjib Chakraborty". |

Header = date / frame / quality / count. Per-reading = the 20 TPI values.

## 3. Standards & constants used
| Standard / band | Example in sheet | Where it should live in VOW (decision #2: extend existing master) |
|---|---|---|
| **STD.TPI** (target twist per inch for the count/quality) | column "STD.TPI" (per-quality/count; not numerically populated in this cache) | TPI is a function of **count + quality**. Already adjacent to existing spinning standards: store `std_tpi` on **`jute_yarn_mst`** (the yarn row that also holds `std_mr_pct` and std count) keyed by yarn quality. ⚠️ If STD.TPI varies by count within the same quality, key on the yarn `item_mst` row instead. |
| **TP** ("TP" header beside STD.TPI) | column "TP" | ⚠️ Confirm meaning — likely **Twist Multiplier / Twist constant** (TPI = TP × √count or count-derived) OR "Tolerance ±". If it is the twist multiplier used to derive STD.TPI, store `std_twist_multiplier` on `jute_yarn_mst`. Mark NEEDS OWNER DECISION. |
| **CV% acceptance band** for twist | implied (ISO uniformity) e.g. typical jute twist CV% target band | No existing per-quality slot. See process×quality note below. |

**⚠️ process×quality storage question (NEEDS OWNER DECISION):** STD.TPI and the acceptable twist-CV% band vary by **spinning process × yarn quality/count**. STD.TPI fits `jute_yarn_mst` (yarn quality already lives there with `std_mr_pct`), but a **CV% band** (`std_cv_low`/`std_cv_high`) has no existing home and decision #2 forbids a standalone standards table. Concrete reconciliations:
1. Add `std_tpi` (+ `std_twist_multiplier` if TP is that) and `std_cv_low` / `std_cv_high` columns to **`jute_yarn_mst`** — keyed by yarn quality (preferred; co-locates with existing yarn standards).
2. If TPI/CV bands differ per frame group rather than per yarn, add the columns to the spinning **`machine_mst`** row instead (machine implies process). Mark **NEEDS OWNER DECISION**.

## 4. Calculations (formulas)
Sample = the 20 readings. **StDev = SAMPLE (n-1)** → Python `statistics.stdev`, SQL `STDDEV_SAMP`.

- **Average TPI** = mean of the 20 readings = `Σ reading_i / 20`.
- **Stdev** = `statistics.stdev([reading_1 … reading_20])` (n-1 sample StDev).
- **CV%** = `Stdev / Average TPI × 100` — the **weight/sliver/TPI CV% variant** (briefing §4: TPI uses StDev / mean × 100, **not** the QR%-based R-08-15 variant). Uses **raw** readings (no MR correction — twist is a count, not a weight).
- **Min-TPI** = `min(readings)`; **Max-TPI** = `max(readings)`.
- **TPI vs STD status** (proposed) = compare Average TPI to STD.TPI (±tolerance from TP/band): `OK` / `LOW-TWIST` / `HIGH-TWIST`.
- **CV% status** (proposed) = `OK` if `std_cv_low ≤ CV% ≤ std_cv_high`.
- ⚠️ **Confirm:** STD.TPI is a looked-up standard (not computed from readings). TP column purpose (twist multiplier vs tolerance). No moisture correction applies to TPI.

Worked formula example (illustrative — cache has no numeric reading rows): readings averaging **5.0 TPI** with Stdev **0.18** → CV% = 0.18 / 5.0 × 100 = **3.6 %**; Min/Max = lowest/highest of the 20. vs STD.TPI 5.0 → status **OK**.

## 5. Worked example (real data)
⚠️ This cache exposes only the **field template** (labels down column A) and header dates (`DATE 2026-01-05`, `LAST STUDY DONE ON 2025-11-21`); the 20-reading numeric rows are not present in the cached extract (they live in the un-shared DSR workbook). End-to-end with a representative reading-set of 20 TPI values, mean 5.00, Stdev 0.18:
- inputs: frame = SPG FRAME NO. (one `machine_mst` row), quality = (one `jute_yarn_mst` row), count_lbs, 20 readings.
- Average TPI = 5.00 · Stdev = 0.18 · **CV% = 3.6 %** · Min = 4.7 · Max = 5.3 · vs STD.TPI 5.0 → **OK** · vs CV band → **OK**.
Owner to supply one real numeric reading-set to lock the formula (especially TP). ⚠️ Confirm against a real study.

## 6. Proposed VOW data model
Header + detail (20 readings per group), mirroring `JuteSqcSpinningQrCv` / `...Dtl`.

```python
class JuteSqcYarnTpi(Base):
    __tablename__ = "jute_sqc_yarn_tpi"
    yarn_tpi_id   = Column(Integer, primary_key=True, autoincrement=True)
    co_id         = Column(Integer, nullable=False, index=True)
    branch_id     = Column(Integer, nullable=True)
    entry_date    = Column(Date, nullable=False, index=True)
    mc_id         = Column(Integer, nullable=False, index=True)   # SPG FRAME NO. -> machine_mst.machine_id
    item_id       = Column(Integer, nullable=False, index=True)   # yarn quality (item_mst / jute_yarn_mst)
    count_lbs     = Column(DECIMAL(10, 3), nullable=True)
    std_tpi       = Column(DECIMAL(10, 3), nullable=True)         # snapshot of std at save (from jute_yarn_mst)
    tp_value      = Column(DECIMAL(10, 3), nullable=True)         # "TP" — meaning TBD (twist multiplier/tolerance)
    prepared_by   = Column(String(150), nullable=True)
    active        = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by    = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class JuteSqcYarnTpiDtl(Base):
    __tablename__ = "jute_sqc_yarn_tpi_dtl"
    yarn_tpi_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    yarn_tpi_id     = Column(Integer, nullable=False, index=True)
    reading_no      = Column(Integer, nullable=False)             # 1..20
    reading_val     = Column(DECIMAL(10, 3), nullable=True)       # TPI reading
```
- **PK** header `yarn_tpi_id`. co_id / branch_id / entry_date / active / updated_by as shown.
- Computed stats (Average TPI, Stdev, CV%, Min, Max) are **recomputed server-side** from the 20 detail rows at read (like `compute_morrah_stats`) — not stored, except optionally a `std_tpi` snapshot for historical fidelity. (Alternative: store the 20 readings as a JSON column on the header, morrah-style — choose detail rows for ISO traceability.)
- Insert-only + soft-delete (`active=0`); duplicates allowed (periodic re-study).

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC`.
- `GET /yarn_tpi_create_setup` → frames (`machine_mst`, spinning), yarn qualities (`item_mst`/`jute_yarn_mst`) with `std_tpi`, `std_count`, `std_cv` band.
- `POST /yarn_tpi_save` → insert header + 20 detail rows; validate exactly 20 readings (mirror morrah's `SAMPLE_SIZE` guard), snapshot std_tpi.
- `GET /yarn_tpi_by_date?co_id&branch_id&entry_date[&mc_id&item_id]` → group(s) with computed Average/Stdev/CV%/Min/Max + std comparison.
- `GET /yarn_tpi_table?co_id&from&to` → range list for summary grid.
- `POST /yarn_tpi_delete` → soft delete.

**Frontend** (`juteSQC/yarn-tpi/` or a tab): mobile form — header (date/frame/quality/count) then a 20-cell reading entry (numeric keypad, trailing-blank pattern); live Average/CV% preview; std hint shown. Desktop summary grid per date, CV% color-flagged vs band, with "last study done on" surfaced. Route consts under `apiRoutesPortalMasters` (`YARN_TPI_SQC_*`); calls via `fetchWithCookie`.

**Masters to link:** `machine_mst` (spinning frames), `item_mst` + `jute_yarn_mst` (yarn quality + `std_tpi`/`std_cv`), `user_mst` (prepared_by).

## 8. Open questions (NEEDS OWNER DECISION)
- Exact **reading count** — header shows READING-1..20, so **n = 20** (confirm it is always 20, vs morrah's 10).
- Meaning of **"TP"** column (twist multiplier? tolerance ±? twist-per-something) and whether STD.TPI is derived from it (TPI = TP × √count) or a stored standard.
- Where to store **STD.TPI** and the **CV% acceptance band** (decision #2): `jute_yarn_mst` per yarn quality (preferred) vs spinning `machine_mst` — **process×quality storage question**. Does STD.TPI vary by count within a quality?
- Is **COUNT(LBS)** entered by the operator or pulled from the selected yarn item's std count?
- Confirm **CV% = Stdev / mean × 100** (assumed; TPI is the StDev/mean variant, not QR%-based).
- Pass/fail tolerance on Average TPI vs STD.TPI (±?).
- Periodicity — "LAST STUDY DONE ON" implies this is a periodic study, not daily; confirm cadence and whether the page should warn when a study is overdue.
- Need one **real 20-reading set** from the owner to lock formulas (cache had labels only).
