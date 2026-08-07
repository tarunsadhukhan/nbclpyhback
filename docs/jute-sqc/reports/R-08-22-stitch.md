# R-08-22 — Stitch Report (I.S.O.)
**Stage:** finishing (sewing / bag-making)  **Status:** UNBUILT
**Source tab:** `R-08-22  STITCH REPORT (I.S.O.)` (master "Daily Summary Date Select")  **DSR workbook:** `1NvpfnD9LwltlY29NeACCnyoAaqmGHPVGvJVHin_nyvs` (DSR!A3:G40, not shared)

## 1. Purpose
Finishing-stage QC of sewing/stitching density: per sewing machine, the inspector takes 5 stitch
counts (number of stitches per decimetre) and averages them, comparing against the standard of
**9 stitches/dm**. It flags machines stitching too loose (e.g. 8/dm) or too tight.

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header.** Cached `2026-01-05`. |
| co_id / branch_id | int | sidebar | yes | **Header**, from SidebarContext. |
| mc_no (machine) | int (FK) | `machine_mst` (machine_id), dept = Sewing/Finishing | yes | **Per reading-set.** Cached MC values: 1, 2, 3, 6, 7, 8, 10, 10. Note MC 10 appears twice (two sets) — duplicates allowed, insert-only. |
| reading_1..reading_5 | int | operator | yes (≥1) | **Per reading-set.** Five stitch counts. Cached all `9,9,9,9,9` except one `8,8,8,8,8` set. |

A "reading-set" = one sewing machine's 5 stitch counts on that date. One save = one (date, mc) set with
5 readings.

## 3. Standards & constants used

| Standard | Example value (cached) | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD NO OF STITCH/DM = 9** | header literal `READINGS (STD NO OF STITCH/DM = 9)` | A fixed mill constant for jute bag stitching. Store as `STD_STITCH_PER_DM = 9` constant in the router (like `STANDARD_MIN_WEIGHT` in `morrahWeight.py`). |

**⚠️ process × quality storage:** This report's standard does **not** vary by quality or process in the
cached data — it is a single global `9/dm`. No CV%/weight band applies, so the process×quality
standards-storage question is **not triggered** here. If the owner says the std stitch count varies by
**bag quality** (sacking vs hessian) or by **machine**, the cleanest extend-existing home would be a
`std_stitch_per_dm` column on the cloth/bag-quality master or on `machine_mst` — but the sheet shows one
fixed value, so keep it a constant unless told otherwise (raise in Open Questions).

## 4. Calculations (formulas)

Per (date, mc) reading-set:
- **AVG READING** = mean(reading_1..reading_5). Set `[9,9,9,9,9]` → **9** ✓. Set `[8,8,8,8,8]` → **8** ✓.
- **PASS/FAIL flag** (proposed; not explicit in cached columns) = `OK` if round(AVG) == STD (9), else
  `LOW` if AVG < 9 / `HIGH` if AVG > 9. The `[8,...]` MC-10 set → AVG 8 < 9 → **LOW**. ⚠️ Confirm: the
  sheet shows only AVG READING with no flag column; flagging is inferred from the std-in-header convention.
- **CV% variant:** not computed in this report (readings are integer counts, usually identical). No StDev/CV%
  column exists. No moisture correction, no count conversion. If owner wants variability, CV% = StDev/AVG×100
  (sample StDev) could be added — flag as optional.

## 5. Worked example (real data)

Date 2026-01-05, MC **10** (the low set):
- readings = `[8, 8, 8, 8, 8]`
- AVG READING = (8+8+8+8+8)/5 = **8** ✓ (cached 8)
- vs STD 9 → **LOW / fail** (1 short of standard)

Contrast MC 1: `[9,9,9,9,9]` → AVG 9 → **OK**.

## 6. Proposed VOW data model

Simplest as a **flat table with readings stored inline** (only 5, fixed) — or JSON like morrah. Given the
fixed count of 5, individual columns are clearest:

```python
class JuteSqcStitch(Base):
    __tablename__ = "jute_sqc_stitch"
    stitch_id            = Column(Integer, primary_key=True, autoincrement=True)
    co_id                = Column(Integer, nullable=False, index=True)
    branch_id            = Column(Integer, nullable=True)
    entry_date           = Column(Date, nullable=False, index=True)
    mc_id                = Column(Integer, nullable=True, index=True)   # machine_mst.machine_id
    mc_no                = Column(Integer, nullable=True)               # raw entered machine number
    reading_1            = Column(Integer, nullable=True)
    reading_2            = Column(Integer, nullable=True)
    reading_3            = Column(Integer, nullable=True)
    reading_4            = Column(Integer, nullable=True)
    reading_5            = Column(Integer, nullable=True)
    inspector_name       = Column(String(120), nullable=True)          # "Anamika Sarkar"
    active               = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by           = Column(Integer, nullable=True)
    updated_date_time    = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```

Insert-only + soft-delete; duplicate (date, mc) allowed (MC 10 twice). `avg_reading` and the pass/fail flag
are **recomputed at read** (do not persist). Alternative: store `readings` as JSON text (morrah style) if a
variable number of readings is desired — but cached data is fixed at 5, so inline columns are recommended.

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`):
- `GET /stitch_create_setup` — dropdown: sewing/finishing machines from `machine_mst` (dept filter);
  returns the std constant (9) for the UI.
- `POST /stitch_save` — insert one (date, mc) set with 5 readings (validate ≥1 reading, positive ints).
- `GET /stitch_by_date` — for a date, list each MC set with computed AVG + flag.
- `GET /stitch_delete` — soft delete by id.

Frontend (`src/app/dashboardportal/juteSQC/r-08-22/`): mobile-first form — date + machine + 5 number
inputs; shows live AVG and OK/LOW/HIGH vs 9. Desktop summary grid keyed by date (MC | R1..R5 | AVG | flag).
Route consts in `api.ts` `apiRoutesPortalMasters` (`STITCH_SETUP`, `STITCH_SAVE`, `STITCH_BY_DATE`,
`STITCH_DELETE`); calls via `fetchWithCookie`; hooks `useStitchSetup`/`useStitchByDate`; `_components/`
Form + Grid.

**Masters to link:** `machine_mst` (sewing/finishing machines). **Std columns to add:** none required (9 is a
global constant) — unless owner says std varies by quality/machine (then `std_stitch_per_dm` on that master).

## 8. Open questions (NEEDS OWNER DECISION)
- Is **STD 9 stitches/dm** a fixed global constant, or does it vary by bag/cloth quality or machine? (Cached
  data shows one fixed 9; if variable, where does `std_stitch_per_dm` live — quality master or `machine_mst`?)
- Should a **pass/fail (OK/LOW/HIGH)** flag column be shown? The sheet only shows AVG READING; flagging is
  inferred from the std-in-header.
- Is the reading count always exactly **5**, or should the UI allow a variable number (→ JSON readings)?
- Should **CV%/StDev** of stitch readings be computed (variability), or is AVG-vs-9 sufficient?
- The MC list (1,2,3,6,7,8,10) — does MC map to a **sewing machine** in `machine_mst`, and which dept/section
  filter selects them? Confirm the loom/sewing-machine numbering matches `machine_mst.mech_code`/`line_no`.
- Is **spell/shift** captured for stitch checks? (No shift column in R-08-22.)
