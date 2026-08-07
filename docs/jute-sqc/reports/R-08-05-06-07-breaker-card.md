# R-08-05/06/07 — Breaker Card (Coarse Side SWT) (I.S.O.)
**Stage:** carding (breaker card, coarse side)  **Status:** UNBUILT
**Source tab:** `R-08-05/06/07 BREAKER CARD (COARSE SIDE SWT) (I.S.O.)` (master "Daily Summary Date Select")   **DSR workbook:** `1cTV9X8LQF4YxLPwj9EKUwsnm5t6oTs77flhbETDsCMs` (sheet `GRAMDSR!A1:V45`, not shared)

## 1. Purpose
Checks the **sliver weight (SWT)** off the **coarse side** of a breaker card. For each (machine, spell, quality) a 5-yard sliver length is weighed **4 times** (4 cuts, each with its MR%), expressed **LB per 5 yds**. Weights are corrected to the quality's STD MR% and averaged to give the card's sliver weight, with StDev/CV%. The report also rolls every row up into a **per-quality grand average** and flags each row's CV% against a **per-quality STD CV% band** ("6-8%", "8-10%"). This is the carding-stage uniformity check feeding the three report codes R-08-05/06/07 (multiple machines on one sheet).

> Header: `(SAMPLE LENGTH 5 YDS & SAMPLE WT IN LBS/5 YDS)`. Weight compared **directly** (no count conversion). This tab is **row-per-reading-set** (multiple machines stacked), unlike the single-machine R-08-04 layout.

## 2. Inputs (the data-entry fields)

Each **row** = one (machine, spell, quality) reading-set with 4 weight+MR pairs. The day's sheet holds many rows (cached: 3 real + blank rows).

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header** (one date for the sheet). Cached = 2026-01-05. |
| mc (machine) | dropdown | `machine_mst` (breaker-card section) | yes | **Per-row** ("Mc"). Cached rows = 4, 5, 10. |
| spell | dropdown | `spell_mst` (spell_id) | yes | **Per-row** ("Spell"). Cached = A1. |
| quality | dropdown | `item_mst` line-quality (item_type_id=5 "Jute Cloth" / line qualities) | yes | **Per-row** ("Qlty"). Cached = HESSIAN, HESSIAN, SACKING WEFT. Drives STD MR% + STD CV% band. (NOTE: line qualities are item_type_id=**5**, not 2 — 2 is raw jute.) |
| wt1, wt2, wt3, wt4 | decimal (lb/5yds) | operator entry | yes (4) | **Per-reading**. 4 sliver-cut weights. Row1: 21.47, 20.41, 20.81, 18.56. |
| m1, m2, m3, m4 | decimal (%) | operator entry | yes (4) | **Per-reading**. MR% per cut. Row1: 32, 28, 30, 26. |

Fixed **4 readings per row**. Computed columns (STD MR%, WT, MR%, Corr Wt, sdev, cv%, STD CV%) are **derived**, not entered.

## 3. Standards & constants used

| Standard / band | Example seen | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD MR% per quality** | HESSIAN → **16**, SACKING WEFT → **20** (printed in "STD MR%" column per row). | Add `std_mr_pct` to the **line-quality `item_mst`** row (item_type_id=2 line qualities). The tab prints distinct std MR per quality, confirming a per-quality column. Shared with all corrected-weight reports. |
| **STD CV% band per quality** | HESSIAN → **"8-10%"**, SACKING WEFT → **"6-8%"** (printed in "STD CV%" column per row). | ⚠️ process×quality — see below. This is a **band (low,high)**, not a single value. |
| StDev basis | sample StDev of the **corrected** 4 readings. | n/a (computed). |

### ⚠️ process × quality standards-storage question (RAISE — NEEDS OWNER DECISION)
The **STD CV% band** ("6-8%", "8-10%") is keyed by **quality**, but the *same quality* will carry a **different band at breaker vs. drawing vs. spinning** — so it is genuinely a (quality × process) standard. Likewise a **STD sliver weight** target per quality at the breaker stage differs from other stages. Neither fits a single per-quality `item_mst` column cleanly, and decision #2 forbids a standalone standards table. Concrete reconciliations:
- **(A) Per-machine on `machine_mst`:** add `std_cv_low`, `std_cv_high` (and `std_sliver_wt` if a weight target applies) to the breaker-card `machine_mst` rows. A machine implies its process, so a card machine's row carries the breaker bands. Fits this report (keyed by Mc per row).
- **(B) Per (quality, stage) line-quality `item_mst` rows:** if qualities already exist split by stage, add `std_cv_low`/`std_cv_high`/`std_mr_pct` to those rows. Keeps the band with the quality but requires stage-split quality rows.

In the cached data the band tracks **quality** (HESSIAN=8-10 on both card 4 and card 5), which slightly favors **(B)** (band follows quality, not machine). But cross-process variance favors keeping it stage-scoped → **(A)** if quality rows are not stage-split. Mark **NEEDS OWNER DECISION** — do not invent a table.

## 4. Calculations (formulas)

Per row, correction constant = that quality's STD MR% (HESSIAN 16, SACKING WEFT 20). **CV% uses the corrected series.**

- **WT** (row avg observed) = `mean(wt1..wt4)`
  - Row1: `(21.47+20.41+20.81+18.56)/4 = 20.315` → tab **20.32** ✓
- **MR%** (row avg) = `mean(m1..m4)` = `(32+28+30+26)/4 = 29` → tab **29** ✓
- **Corr Wt** = `WT × (100 + STD_MR) / (100 + MR%)`
  - Row1 (HESSIAN, stdMR16): `20.32 × 116/129 = 18.27` → tab **18.26** ✓ (rounding)
  - Row3 (SACKING WEFT 20.40 @MR32.25, stdMR20): `20.40 × 120/132.25 = 18.51` → tab **18.51** ✓
  - ⚠️ Confirm: Corr Wt is computed from row-avg WT & row-avg MR (verified above). The per-reading-then-average path gives a near-identical number; the avg-then-correct path matches the cached value exactly.
- **sdev** = sample StDev (n-1) of the **4 corrected** readings (Python `statistics.stdev` / SQL `STDDEV_SAMP`)
  - Row1: tab **0.7951**; Row3: **0.4444** (consistent with stdev of corrected cuts).
- **cv%** = `sdev / Corr Wt`
  - Row1: `0.7951 / 18.26 = 0.04355` → tab **0.04355** ✓ ; Row3: `0.4444 / 18.51 = 0.02401` → tab **0.02401** ✓
  - Store ratio; render ×100. **Pass test:** cv%×100 within the row's STD CV% band → e.g. Row1 4.36% is **inside** "8-10%"? No → it is **below** 8% (good: lower CV = more uniform; band is the *upper tolerance*). ⚠️ Confirm band semantics (likely "alert if CV% exceeds the high edge"; low edge informational).
- **GRAND AVERAGE block (per quality, across that quality's rows):**
  - OBS = `mean(row WT for quality)` — HESSIAN: `(20.32+22.92)/2 = 21.62` → tab **21.62** ✓
  - MR% = `mean(row MR% for quality)` — HESSIAN: `(29+31)/2 = 30` → tab **30** ✓
  - CORR = `mean(row Corr Wt for quality)` — HESSIAN: `(18.26+20.28)/2 ≈ 19.29` → tab **19.29** ✓
  - CV% = recomputed across the quality's pooled corrected readings — HESSIAN tab **0.05173** (note: ≠ mean of row cv%s; it is the CV of the combined set; SACKING WEFT single-row = 0.02401 matches its row). ⚠️ Confirm grand CV% = StDev(all corrected readings for quality)/mean(corrected for quality).

## 5. Worked example (real data)
Row 1 — Mc 4, Spell A1, Qlty HESSIAN (STD MR 16, STD CV% 8-10%).
Readings: (21.47/32)(20.41/28)(20.81/30)(18.56/26).
WT = 20.32, MR% = 29. Corr Wt = 20.32×116/129 = **18.26**. Corrected cuts ≈ [19.30,18.49,18.55,17.10] → sdev = **0.795**. cv% = 0.795/18.26 = **0.0436 (4.36%)** → within/under the 8-10% band (uniform).
Row 3 — Mc 10, A1, SACKING WEFT (STD MR 20, band 6-8%): (19.93/32)(19.66/30)(20.63/32)(21.38/35) → WT 20.40, MR% 32.25, Corr 20.40×120/132.25 = **18.51**, sdev 0.444, cv% **0.0240 (2.40%)**.
Grand avg HESSIAN (rows 1+2): OBS 21.62, MR% 30, CORR 19.29, CV% 0.05173.

## 6. Proposed VOW data model

**Header + detail** (multiple rows per date; each row has 4 readings). Mirrors `JuteSqcSpinningQrCv` + `...Dtl` header/detail style, OR a flat row with a 4-element JSON. Given exactly-4 readings and per-row stats, a **flat row-per-reading-set** table is simplest:

`jute_sqc_breaker_card_swt`  (one row = one Mc/Spell/Qlty reading-set)
| Column | Type | Notes |
|---|---|---|
| breaker_card_swt_id | INT PK autoinc | |
| co_id | INT, NOT NULL, idx | |
| branch_id | INT, NULL | |
| entry_date | DATE, NOT NULL, idx | |
| mc_id | INT, NULL | → machine_mst (breaker card) |
| spell_id | INT, NULL | → spell_mst |
| item_id | INT, NULL | quality → item_mst |
| wt1..wt4 | DECIMAL(10,3) | 4 observed cut weights (or `weights` JSON) |
| mr1..mr4 | DECIMAL(5,2) | 4 MR% (or `mr_pcts` JSON) |
| std_mr_pct | DECIMAL(5,2), NULL | snapshot (16 / 20) |
| std_cv_low | DECIMAL(5,2), NULL | band low (e.g. 8) snapshot |
| std_cv_high | DECIMAL(5,2), NULL | band high (e.g. 10) snapshot |
| calc_wt | DECIMAL(10,3) | row avg observed (20.32) |
| calc_mr_pct | DECIMAL(5,2) | row avg MR% (29) |
| calc_corr_wt | DECIMAL(10,3) | 18.26 |
| calc_sdev | DECIMAL(10,4) | 0.7951 (corrected) |
| calc_cv_pct | DECIMAL(7,4) | 0.04355 ratio |
| cv_within_band | INT/bool | computed pass flag |
| active | INT, NOT NULL, default 1 | soft-delete |
| updated_by | INT, NULL | |
| updated_date_time | TIMESTAMP | default current_timestamp |

Grand-average (per quality) is **recomputed at read** from that date's rows — do **not** store it. Insert-only + soft delete; one save can insert several rows (the day's grid).

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC`.
- `GET /breaker_card_swt_create_setup?co_id&branch_id` → breaker-card machines (`machine_mst`), spells (`spell_mst`), qualities (`item_mst`) **with `std_mr_pct` + `std_cv_low`/`std_cv_high`**.
- `POST /create_breaker_card_swt` → accept an array of rows; per row validate exactly 4 (wt, MR%) pairs, look up std MR + CV band, compute stats in `compute_breaker_card_stats()`, insert each row.
- `GET /get_breaker_card_swt_by_date?co_id&entry_date` → all rows for the date **plus** the recomputed per-quality grand-average block (desktop summary).
- `GET /get_breaker_card_swt_table?co_id&page&limit&search` → paginated history.
- `GET /get_breaker_card_swt_by_id?id` → single row detail.
- `POST /delete_breaker_card_swt` → soft delete a row.

**Frontend** (`src/app/dashboardportal/juteSQC/r-08-05-06-07/`): mobile-first entry — pick date, add rows (Mc/Spell/Qlty + 4 wt/MR), live per-row Corr Wt / CV% with band pass/fail color; desktop date view shows the rows table + per-quality grand-average block. Route consts in `api.ts` (`BREAKER_CARD_SWT_*`); `fetchWithCookie`. **Masters to link:** `machine_mst` (breaker card), `spell_mst`, `item_mst` (line qualities).

## 8. Open questions (NEEDS OWNER DECISION)
- **STD CV% band** storage (process×quality): on `machine_mst` (option A) or per-(quality,stage) `item_mst` row (option B)? Cached data shows the band follows **quality**, but cross-stage variance argues for stage scoping. **NEEDS OWNER DECISION.**
- **STD CV% band semantics** — is pass = CV% ≤ high edge, or strictly *within* [low, high]? Row1 (4.36%) sits **below** the 8-10% band yet is presumably "good" → confirm low edge is informational/alert-if-too-uniform vs. a hard fail.
- Confirm **Corr Wt = avg-WT corrected by avg-MR** (verified to match cached) vs. mean of per-cut corrected weights (nearly identical).
- Confirm **grand-average CV% = CV of pooled corrected readings per quality** (0.05173 for HESSIAN ≠ mean of row CVs).
- Is there a **STD sliver-weight target** for breaker card (none printed here, but other carding/drawing reports have one)? If yes, store where the CV band lives.
- "Coarse side" — confirm whether a parallel "fine side" report exists and shares this table (a `card_side` column may be needed).
- Codes **R-08-05/06/07** map to three machines/sides — confirm whether they are separate report instances or one multi-row sheet (modeled here as one multi-row sheet).
- Phase-2: link to carding production (frames running) — not wired now.
