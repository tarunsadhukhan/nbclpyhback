# R-08-18 — Beam MR% (Hessian/Sacking) (I.S.O.)

**Stage:** weaving (beaming / warping — the warp beam wound for the loom)  **Status:** UNBUILT
**Source tab:** `R18` ("R-08-18 BEAM MR% (I.S.O.)", master "Daily Summary Date Select")   **DSR workbook:** `1VxTGh23uYQpKDrBwUcwW48G5xrEItLzEDhyxYda6wME` (DSR!A1:H40, not shared)

## 1. Purpose
Measures the **moisture regain % (MR%)** of the warp **beams** before they go to the loom, separately for **Hessian** and **Sacking** qualities. High beam MR means damp warp (weaving faults, weight gain); the check confirms each machine's beams sit near the quality's target MR. Each beam machine gets 5 moisture readings; the report shows per-machine average and an overall average per quality.

## 2. Inputs (the data-entry fields)

The tab is organised as **two quality blocks** (Hessian, Sacking), each block holding **one or more machine columns**, each machine column carrying **5 readings**. In the cached data each block has 2 machines.

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| `entry_date` | date | — (header) | yes | Header. Cached: `2026-01-05`. Appears once per quality block. |
| `quality_group` | enum/text | derived ("HESSIAN" / "SACKING") | yes | Header per block. Drives which quality list + std MR applies. |
| `spell_id` (Shift) | FK | `spell_mst` (spell_code) | yes | Per-machine. Cached: "A1". |
| `quality` (Qlty) | FK | see §3 — Hessian uses a **fabric/construction quality** ("38.00"-(11x10)-7.714"); Sacking cached as plain "SACKING" | yes | Per-machine. The Hessian string encodes width-(ends×picks)-oz; Sacking is the line quality name. |
| `machine_no` | FK | `machine_mst` (`mech_code`/`machine_name`), beaming dept | yes | Per-machine. Cached: "HS 10","HS 1" (Hessian beams), "S5","S7" (Sacking beams). |
| `reading_1..5` (MR%) | number(5,2) | operator entry | yes | Per-machine, 5 moisture-meter readings. Cached Hessian HS 10: 20,18,17,21,20. |

**Header vs per-reading:** `entry_date`, `quality_group` are header (block-level). `spell_id`, `quality`, `machine_no` are per-machine (one reading-set). `reading_1..5` are the 5 per-reading values inside a reading-set.

## 3. Standards & constants used

| Standard / threshold | Example in sheet | Where it should live in VOW (decision #2 = extend existing master) |
|---|---|---|
| **Std MR% per quality** (the target MR the average is judged against) | Not shown as a printed column on this tab, but jute MR standards are quality-specific: Hessian ≈ 16, Sacking ≈ 20 (briefing §4). | Add `std_mr_pct` to the **line/fabric quality master** that holds Hessian/Sacking qualities. For yarn this already exists on `jute_yarn_mst.std_mr_pct`; for these **woven/line qualities** propose adding `std_mr_pct` to the master that backs the `quality` dropdown (see Open Questions — which master holds "HESSIAN"/"SACKING"/fabric-construction strings). |
| **Acceptable MR band** (pass/fail around target) | Not printed on this tab — only Average + Overall Average are computed. No LT/OK/HY-style buckets appear here. | If owner wants a pass band (e.g. ±2 MR around std), store band as `std_mr_low`/`std_mr_high` on the same quality master. **NEEDS OWNER DECISION** — see §8. |

This report (unlike weight reports) has **no weight standard and no CV% band** — it only averages raw MR readings. So the **process×quality standards-storage question** applies only weakly here (just the per-quality std MR). It is still raised: the std MR for **Hessian** vs **Sacking** differs, and "beam MR" may need its own target distinct from the yarn/raw MR for the same quality. If the owner wants a beam-specific target, that single value does **not** fit a per-quality yarn master cleanly. Proposed reconciliation: add `std_mr_pct` (and optional `std_mr_low`/`std_mr_high`) to the **line/fabric quality master**; if a beam-stage-specific value is needed, key it on the **machine_mst** beam row (a machine implies its stage). **NEEDS OWNER DECISION.**

## 4. Calculations (formulas)

This tab computes only averages — no correction, no CV%, no stdev (stdev is NOT in the cached tab).

- **Per-machine Average** = mean of that machine's 5 readings.
  - Worked (Hessian HS 10): (20+18+17+21+20)/5 = 96/5 = **19.2** ✓ (matches cached 19.2)
  - Worked (Hessian HS 1): (19+21+18+22+21)/5 = 101/5 = **20.2** ✓
  - Worked (Sacking S5): (20+19+22+18+21)/5 = 100/5 = **20.0** ✓
  - Worked (Sacking S7): (20+17+20+19+21)/5 = 97/5 = **19.4** ✓
- **Overall Average (per quality block)** = mean of the per-machine averages in that block.
  - Hessian: (19.2+20.2)/2 = **19.7** ✓ (matches cached "Overall Average 19.7")
  - Sacking: (20.0+19.4)/2 = **19.7** ✓
  - ⚠️ Confirm: with only 2 machines the mean-of-means equals the grand mean of all 10 readings (Hessian grand mean = 197/10 = 19.7). When machines have **unequal reading counts**, mean-of-averages ≠ grand-mean. Confirm with owner whether Overall Average is **mean of machine averages** (assumed) or **grand mean of all readings**. Both give 19.7 on the cached symmetric data, so the cache can't disambiguate.
- **Deviation vs std MR** (proposed VOW addition, not in sheet): `deviation = per_machine_avg − std_mr_pct(quality)`. Pass flag if within owner-defined band. Not computed in the Google tab today.

The `#DIV/0!` cells in the cached row are empty machine columns (no readings) — VOW computes averages only over machines that have a complete reading-set.

## 5. Worked example (real data)

**Hessian block, machine HS 10, shift A1, date 2026-01-05:**
- Inputs: readings = [20, 18, 17, 21, 20]
- Per-machine Average = 96/5 = **19.2**
- (sibling machine HS 1 average = **20.2**)
- Hessian Overall Average = (19.2 + 20.2)/2 = **19.7**
- vs std MR (Hessian ≈ 16): deviation = 19.2 − 16 = **+3.2** MR (warp wetter than standard) — flag depends on owner band.

**Sacking block, machine S5, shift A1:** readings [20,19,22,18,21] → avg **20.0**; with S7 (19.4) → Sacking Overall Average **19.7**; vs std MR (Sacking ≈ 20) deviation ≈ **0.0** (on target).

## 6. Proposed VOW data model

Header/detail. One header per machine reading-set (mirrors `JuteSqcSpinningQrCv` + `...Dtl` style; legacy `Column(...)` like `src/juteSQC/models.py`). Store readings as detail rows (5 per set); the `quality_group` is a header field. Insert-only + soft-delete.

```python
class JuteSqcBeamMr(Base):
    """R-08-18 Beam MR% — one row per (date, quality, machine) reading-set."""
    __tablename__ = "jute_sqc_beam_mr"

    beam_mr_id        = Column(Integer, primary_key=True, autoincrement=True)
    co_id             = Column(Integer, nullable=False, index=True)
    branch_id         = Column(Integer, nullable=True)
    entry_date        = Column(Date, nullable=False, index=True)
    quality_group     = Column(String(20), nullable=False)   # 'HESSIAN' | 'SACKING'
    spell_id          = Column(Integer, nullable=True)        # spell_mst
    quality_id        = Column(Integer, nullable=True)        # FK -> quality master (see §8)
    quality_text      = Column(String(120), nullable=True)    # snapshot of the printed Qlty string
    mc_id             = Column(Integer, nullable=True)         # machine_mst.machine_id (beam machine)
    readings          = Column(String(200), nullable=True)    # JSON [20,18,17,21,20] (morrah-style)
    calc_avg_mr       = Column(DECIMAL(6, 2), nullable=True)  # recomputable; cache for grid
    std_mr_pct        = Column(DECIMAL(6, 2), nullable=True)  # snapshot of quality std MR at save
    active            = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by        = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```

- **PK:** `beam_mr_id`. Scoping cols: `co_id`, `branch_id`, `entry_date`, `active`, `updated_by`.
- `readings` stored as JSON (morrah pattern) — simpler than a detail table for a fixed 5; alternatively a `jute_sqc_beam_mr_dtl(reading_no, reading_val)` table if owner wants per-reading querying. **Overall Average per quality** is computed at read by averaging the active per-machine averages within (entry_date, quality_group).

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`, `src/juteSQC/beamMr.py` + `query.py` additions):
- `GET /beam_mr_create_setup` — returns dropdowns: spells (`spell_mst`), beam machines (`machine_mst` filtered to beaming dept/section), quality list (+ its `std_mr_pct`), split by HESSIAN/SACKING group.
- `POST /create_beam_mr` — validates 5 readings, snapshots `std_mr_pct`, computes `calc_avg_mr`, inserts.
- `GET /get_beam_mr_by_date` — all machine sets for a date, grouped by quality, with per-machine avg + per-quality Overall Average computed server-side.
- `GET /get_beam_mr_table` — paginated list (like `get_morrah_wt_table`).
- `POST /delete_beam_mr` — soft delete (`active=0`).

Frontend (`src/app/dashboardportal/juteSQC/r-08-18/`, mobile-first like `r-08-01`):
- **Entry form** (one reading-set at a time): pick quality group → quality → machine → shift → 5 MR readings; live per-machine average. Honors `co_id`/`branch_id` from `SidebarContext`.
- **Summary view** (date-driven): two grouped tables (Hessian, Sacking), per-machine rows + per-quality Overall Average; deviation vs std MR shown.
- Route consts in `src/utils/api.ts` under `apiRoutesPortalMasters` (`BEAM_MR_*`); calls via `fetchWithCookie`.

**Masters to link:** `spell_mst` (shift), `machine_mst` (beam machines), the line/fabric quality master (§8) for the Qlty dropdown + std MR.

## 8. Open questions (NEEDS OWNER DECISION)

- **Which master holds the `Qlty` values?** Hessian shows a fabric-construction string `38.00"-(11x10)-7.714` (width-(ends×picks)-oz) while Sacking shows plain `SACKING`. Confirm whether the dropdown should be the **fabric-construction quality master** (shared with R-08-19) for Hessian and a **line/sacking quality** for Sacking, or one unified quality list. This decides where `std_mr_pct` is added.
- **Std MR per quality value:** confirm Hessian std MR (≈16) and Sacking std MR (≈20), and whether **beam-stage** MR has a *different* target than yarn/raw MR for the same quality (would require a beam-specific std, possibly keyed on `machine_mst`).
- **Pass/fail band:** the tab prints averages only — no buckets. Does the owner want a tolerance band (e.g. std ±2 MR) and a pass flag, stored as `std_mr_low`/`std_mr_high`? If yes, on which master?
- **Overall Average definition:** mean of machine averages (assumed) vs grand mean of all readings — confirm (cached symmetric data can't disambiguate).
- **Readings per machine:** always 5? (cache shows 5). And **machines per quality** is variable (cache shows 2) — confirm max columns for the grid.
- **Beam machine identification:** are "HS 10 / S5" `mech_code` values already in `machine_mst` under a beaming department, or do they need adding? (link, not Phase-2).
