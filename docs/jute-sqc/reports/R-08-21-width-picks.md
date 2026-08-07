# R-08-21 — Width & Picks Checking Report (I.S.O.)
**Stage:** weaving  **Status:** UNBUILT
**Source tab:** `R-08-21-LOOM WIDTH AND PICKS` (master "Daily Summary Date Select")  **DSR workbook:** `1TPLTy2jENjaFoG1HGs7Fo9FYS2q9VQeiAxb1ObCG3pY` (REPORT!A3:Y218, not shared)

## 1. Purpose
On-loom dimensional QC for woven jute cloth: per loom, an inspector measures the reed **width** (cm)
and the **picks per dm** (weft density). Per cloth quality, the report compares average width against
the quality's STD width ±0.5% tolerance and reports average/StDev/max/min of picks, flagging qualities
that drift outside band. It is the weaving counterpart of Morrah weight QC (raw weights) and the
sliver/count family (corrected weights).

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header.** Report date (cached `2026-01-05`). |
| co_id / branch_id | int | sidebar | yes | **Header**, from SidebarContext. |
| shift / spell | int (FK) | `spell_mst` (spell_id) | optional | **Header.** Not shown in R-08-21 columns but present in R-08-28; ⚠️ confirm whether width/picks is captured per spell. |
| quality (cloth quality) | int (FK) | cloth quality master — see §3 | yes | **Per reading-group.** Sheet groups readings into up to 5 quality blocks. Cached values: `39.00"- 8x 7-5.85`, `38.00"-11x10-7.71`, `40.00"- 8x 8-6.5`, `SACKING S4(22.50"- 5x 7-9.44)`. |
| loom_no | int (FK) | `machine_mst` (machine_id via `mech_code`/`line_no`), dept = Weaving | yes | **Per reading.** Loom number, e.g. 21, 29, 133. |
| width | decimal(6,2) | operator | yes | **Per reading.** Reed width in cm, e.g. 100, 99.5, 97.5, 57. |
| pick | decimal(6,2) | operator | optional | **Per reading.** Picks/dm, e.g. 24, 34, 30, 57. Sparse: not every loom row has a pick value (only a sampled subset of looms is pick-checked — see worked example). |

A "reading" = one loom row (loom_no + width + optional pick). A "reading-group" = all looms measured
for one cloth quality on that date. One save covers one (date, quality) group with N loom rows.

## 3. Standards & constants used

| Standard | Example value (cached) | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD WIDTH (cm)** per cloth quality | 39.00"=99.06, 38.00"=96.52, 40.00"=102, SACKING S4=57.15 | Add `std_width_cm` column to the **cloth-quality master** (see open question). 39"×2.54 = 99.06 cm → STD width = nominal inches × 2.54. |
| **Width tolerance band** ±0.5% | +.5% = STD×1.005, −.5% = STD×0.995 (e.g. 99.06 → 99.56 / 98.56) | Constant `WIDTH_TOL_PCT = 0.005`. Computed, not stored. ⚠️ Confirm 0.5% is universal vs per-quality. |
| **STD PICKS** per cloth quality | 39.00"=24, 38.00"=34, 40.00"=31, SACKING S4=50 | Add `std_picks` column to the **cloth-quality master**. (This is the "x" weft figure embedded in the quality name: `8x 7` → warp 8 / picks 7? — actually std picks differs from the name; store explicitly.) |
| Width **REMARK** flag `$` | shown when AVG width is **outside** the ±0.5% band | Computed at read; not stored as a standard. 39.00": AVG 99.88 > +.5% 99.56 → `$`. SACKING: 57.88 > 57.52 → `$`. 38.00" (97.79 within 96.04–97.0? AVG 97.79 > 97.0 +tol)… ⚠️ see §4 Confirm. |

**⚠️ KEY OPEN DESIGN QUESTION (process × quality standards storage) — NEEDS OWNER DECISION:**
The cloth qualities here (`39.00"- 8x 7-5.85`, `SACKING S4(22.50"- 5x 7-9.44)`) are **weaving cloth
qualities**, not raw-jute qualities. Their `std_width_cm` and `std_picks` are weaving-stage standards.
Decision #2 forbids a new standalone standards table. Two concrete reconciliations:
1. **Add `std_width_cm` + `std_picks` to the cloth-quality master** (the `item_mst` row that represents
   the woven cloth quality, or `jute_quality_mst` if that is where weaving qualities live). A cloth
   quality implies a single width/picks standard, so this fits one-per-quality cleanly. **Preferred.**
2. If width/picks std can vary by loom group within a quality, attach `std_width_cm`/`std_picks` to the
   **`machine_mst`** loom row instead (machine implies its setting).
**Owner must confirm WHICH master holds weaving cloth qualities** (item_mst cloth items vs jute_quality_mst)
before adding columns — see Open Questions.

## 4. Calculations (formulas)

All per (date, quality) group, over that group's loom readings.

- **AVG width (cm)** = mean(width readings). 39.00" group widths `[100, 99.5, 100, 100]` → mean = **99.88** ✓ (cached 99.88).
- **TOLERANCE +.5%** = STD_WIDTH × (1 + 0.005). 99.06 × 1.005 = **99.56** ✓.
- **TOLERANCE −.5%** = STD_WIDTH × (1 − 0.005). 99.06 × 0.995 = **98.56** ✓.
- **Width REMARK** = `$` if AVG width **>** TOL+.5% OR AVG width **<** TOL−.5%, else blank.
  39.00": 99.88 > 99.56 → `$` ✓. 40.00": AVG 101.9, band 101.49–102.51 → within → blank ✓.
  ⚠️ Confirm: 38.00" shows blank with AVG 97.79 but band (96.04–97.0) would flag it; the SACKING −.5% column
  shows 57.15 (= STD, not STD×0.995 = 56.86) — **the −.5% column for SACKING appears to repeat STD**, so the
  sheet's `$` rule may compare AVG only to the **+.5%** upper bound (one-sided "too wide"). Worked: 39.00"
  99.88>99.56 `$`, SACKING 57.88>57.52 `$`, 38.00" 97.79>97.0 would be `$` but is blank → ⚠️ rule not
  fully consistent in cached data; **derive as: `$` when AVG > TOL+.5%** and flag for owner.
- **AVG picks** = mean(pick readings present in group). 39.00" picks `[24,24,25]` (4th row blank) → mean = **24.33** ✓.
- **STDEV (picks)** = `statistics.stdev` (sample, n−1). 39.00" `[24,24,25]` → 0.5774 ✓ (cached 0.5774).
  SACKING picks → 0.7432 ✓. **CV% variant:** this report does **not** compute a picks CV%; it reports raw
  StDev only (unlike Morrah/sliver which compute CV% = StDev/mean×100). No MR correction applies — width &
  picks are physical dimensions, never moisture-corrected.
- **MAX picks / MIN picks** = max/min of pick readings. 39.00" → MAX 25, MIN 24 ✓. SACKING → MAX 50, MIN 48 ✓.

No moisture correction, no count conversion. StDev = sample (n−1).

## 5. Worked example (real data)

Date 2026-01-05, quality **39.00"- 8x 7-5.85**, looms 21/29/133/134.

| Loom | Width | Pick |
|---|---|---|
| 21 | 100 | 24 |
| 29 | 99.5 | 24 |
| 133 | 100 | 25 |
| 134 | 100 | (blank) |

Computed:
- AVG width = (100+99.5+100+100)/4 = **99.88 cm**
- STD width (39"×2.54) = **99.06**, +.5% = 99.06×1.005 = **99.56**, −.5% = **98.56**
- REMARK: 99.88 > 99.56 → **`$`** (too wide)
- AVG picks = (24+24+25)/3 = **24.33**, STD picks = **24**
- STDEV picks = stdev([24,24,25]) = **0.5774**, MAX = **25**, MIN = **24**

All match the cached WIDTH/PICKS SUMMARY rows exactly.

## 6. Proposed VOW data model

Header + detail (reading-set has many loom rows). Follows `JuteSqc*` legacy `Column(...)` style on
`Base` from `src/models/mst.py`.

```python
class JuteSqcWidthPicks(Base):                  # header: one (date, quality) group
    __tablename__ = "jute_sqc_width_picks"
    width_picks_id       = Column(Integer, primary_key=True, autoincrement=True)
    co_id                = Column(Integer, nullable=False, index=True)
    branch_id            = Column(Integer, nullable=True)
    entry_date           = Column(Date, nullable=False, index=True)
    spell_id             = Column(Integer, nullable=True)        # if captured (⚠️ confirm)
    quality_id           = Column(Integer, nullable=False, index=True)  # cloth-quality master FK
    inspector_name       = Column(String(120), nullable=True)   # "PIJUSH BISWAS"
    active               = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by           = Column(Integer, nullable=True)
    updated_date_time    = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class JuteSqcWidthPicksDtl(Base):               # one loom reading
    __tablename__ = "jute_sqc_width_picks_dtl"
    width_picks_dtl_id   = Column(Integer, primary_key=True, autoincrement=True)
    width_picks_id       = Column(Integer, nullable=False, index=True)
    loom_id              = Column(Integer, nullable=True)        # machine_mst.machine_id
    loom_no              = Column(Integer, nullable=True)        # raw entered loom number (fallback)
    width_cm             = Column(DECIMAL(6, 2), nullable=True)
    picks_dm             = Column(DECIMAL(6, 2), nullable=True)  # nullable: not every loom is pick-checked
```

Insert-only + soft-delete (active=0). Width/picks summary stats (avg/stdev/max/min/remark) are
**recomputed server-side at read** from the detail rows (do not persist them) — mirrors `compute_morrah_stats`.

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`):
- `GET /width_picks_create_setup` — dropdowns: cloth qualities (with `std_width_cm`, `std_picks`),
  looms from `machine_mst` filtered to Weaving dept, spells from `spell_mst`.
- `POST /width_picks_save` — insert header + detail rows (one quality group, N loom readings).
- `GET /width_picks_by_date` — for a date (+ optional quality), return each quality group with its loom
  rows AND the computed WIDTH SUMMARY (avg, std_width, tol±, remark) + PICKS SUMMARY (avg, std_picks,
  stdev, max, min).
- `GET /width_picks_delete` — soft delete by id.

Frontend (`src/app/dashboardportal/juteSQC/r-08-21/`): mobile-first entry — pick date + quality, then a
repeating "add loom" row (loom dropdown, width, pick). Desktop summary grid keyed by date showing per-quality
WIDTH/PICKS summary blocks like the sheet. Route consts in `api.ts` under `apiRoutesPortalMasters`
(`WIDTH_PICKS_SETUP`, `WIDTH_PICKS_SAVE`, `WIDTH_PICKS_BY_DATE`, `WIDTH_PICKS_DELETE`). Calls via
`fetchWithCookie`. Hooks `useWidthPicksSetup` / `useWidthPicksByDate`; `_components/` Form + SummaryGrid.

**Masters to link:** cloth-quality master (qualities + std width/picks), `machine_mst` (looms, Weaving dept),
`spell_mst` (if used). **Std columns to add:** `std_width_cm`, `std_picks` on the cloth-quality master.

## 8. Open questions (NEEDS OWNER DECISION)
- **Which master holds the weaving cloth qualities** (`39.00"- 8x 7-5.85`, `SACKING S4...`)? `item_mst`
  cloth items or `jute_quality_mst`? This determines where `std_width_cm` / `std_picks` columns go.
- Add `std_width_cm` + `std_picks` to that cloth-quality master (decision #2 extend-existing) — confirm.
- Is STD width always nominal inches × 2.54, or stored independently per quality? (40.00" cached STD = 102,
  but 40×2.54 = 101.6 → stored value differs from pure conversion → must be stored explicitly.)
- **Width `$` remark rule:** one-sided (AVG > +.5% only) or two-sided (outside ±0.5%)? Cached data is
  inconsistent (38.00" not flagged despite AVG above band; SACKING −.5% column = STD, not STD×0.995).
- Is width/picks captured **per spell/shift**? R-08-21 has no shift column but R-08-28 does.
- Is the picks check on a **sampled subset of looms** by design (sparse pick column), and should the UI
  allow leaving picks blank for a width-only loom row?
- Picks: report only StDev (no CV%) — confirm no CV% is wanted for picks.
- Tolerance 0.5% — universal constant or per-quality override?
