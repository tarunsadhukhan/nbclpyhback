# R-08-04 — Spreader Roll Weight (I.S.O.)
**Stage:** selection / batching (spreader)  **Status:** UNBUILT
**Source tab:** `R-08-04 SPREADER ROLL WEIGHT (I.S.O.)` (master "Daily Summary Date Select")   **DSR workbook:** `1XG5Ojn0_sflaXIntnEXrr7nosE_Mk9xVcQgfEI7VQnQ` (sheet `DSR!A49:H91`, not shared)

## 1. Purpose
Checks the **whole-roll weight** delivered off a spreader machine for a given shift/quality. The operator weighs 10 finished rolls (in **KG**), records each roll's moisture regain (MR%), and the report corrects every weight to the quality's standard MR% so that rolls of different dampness are comparable. Output = average corrected roll weight, spread (StDev / CV%), and a distribution of how many rolls fall in each weight band — the band check is the pass/fail signal that the spreader is producing uniformly sized rolls.

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header**. Cached row = 2026-01-05. |
| shift / spell | dropdown | `spell_mst` (spell_id) | yes | **Header**. Cached = `A1`. |
| quality | dropdown | `item_mst` (raw jute, item_type_id=2) | yes | **Header**. Cached = `MESTA`. Drives STD MR% lookup. |
| machine_no | dropdown | `machine_mst` (spreader section) | yes | **Header**. Cached = `SPREADER 4`. Also drives which band set applies (Spreader 2 uses the `**` band set). |
| feeder_eb_no / feeder_name | text or `hrms` employee | free-text now | no | **Header**. Cached = `Upendra Roy`. Operator/feeder identity; keep free-text for Phase-1 (Phase-2: link to HRMS employee). |
| roll_weight_1 … roll_weight_10 | decimal (kg) | operator entry | yes (10) | **Per-reading**. Observed roll weight. Cached: 69.4, 71.32, 73.24, 67.14, 70.62, 65.91, 67.15, 71.22, 64.38, 66.24. |
| mr_pct_1 … mr_pct_10 | decimal (%) | operator entry | yes (10) | **Per-reading**. One MR% per roll. Cached: 38, 40, 46, 37, 44, 45, 43, 43, 39, 42. |

Fixed sample size = **10 rolls** (mirrors Morrah's 10-reading rule). UOM = **KG**.

## 3. Standards & constants used

| Standard / band | Example seen | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD MR% per quality** | MESTA row corrects with std MR (jute base = 16; sheet stores per-quality). | Add `std_mr_pct` column to the **raw-jute quality master = `item_mst`** row (item_type_id=2), exactly as `jute_yarn_mst.std_mr_pct` already exists for yarn. Morrah (R-08-01) needs the same column, so this is shared. ⚠️ Confirm MESTA's std MR — not printed in this tab (it shows the *corrected* numbers); derived below it is **16**. |
| **Weight bands (default set)** | `<55`, `55–60`, `61–65`, `66–70`, `71–75`, `>75` (kg) | Band edges are **per-machine** (the `**` set differs). See process×quality note below. |
| **Weight bands (Spreader-2 set, `**`)** | `<85`, `85–90`, `91–95`, `96–100`, `101–105`, `>105` (kg) | Note in tab: "** Marked range for **Spreader 2 only**." So band thresholds vary **by machine**. |
| **CV% reference** | tab prints a single CV% (0.0402) with no pass band on this report | No std CV band on R-08-04 (unlike the card report R-08-05/06/07). |

### ⚠️ process × quality standards-storage question (RAISE — NEEDS OWNER DECISION)
The **weight bands differ by machine** (Spreader 2 = the `**` 85–105 set; all other spreaders = the 55–75 set). These six band edges do **not** fit a single per-quality master, and decision #2 forbids a new standalone standards table. Two concrete reconciliations:
- **(A) Store band edges on `machine_mst`** — add `std_band_1`…`std_band_5` (5 cut points → 6 buckets) to the spreader's `machine_mst` row, since a machine implies its band set. Cleanest fit for "Spreader 2 only."
- **(B) Two fixed band sets in code/constants** keyed by a machine flag (`is_high_band`) added to `machine_mst`. Lighter schema, but bakes the numbers into code.

Recommendation: **(A)**. Mark **NEEDS OWNER DECISION**.

## 4. Calculations (formulas)

Correction constant = quality's STD MR% (MESTA = 16, derived/⚠️confirm).

- **Corrected roll weight** = `Observed × (100 + STD_MR) / (100 + Observed_MR%)`
  - Worked (roll 1): `69.4 × (100+16) / (100+38) = 69.4 × 116/138 = 58.336` → tab shows **58.34** ✓
  - Worked (roll 6): `65.91 × 116/145 = 52.728` → tab **52.73** ✓
- **Avg MR%** = `mean(mr_pct_1..10)` = `(38+40+46+37+44+45+43+43+39+42)/10` = **41.7** ✓
- **Avg Roll WT (Obs)** = `mean(observed)` = **68.66** ✓ ; **Avg Roll WT (Corr)** = `mean(corrected)` = **56.22** ✓
- **StDev (Obs)** = sample StDev (n-1) of observed = **2.89** ✓ ; **StDev (Corr)** = sample StDev of corrected = **2.26** ✓ (Python `statistics.stdev`, SQL `STDDEV_SAMP`)
- **CV%** = `StDev(Corr) / Avg(Corr)` = `2.26 / 56.22 = 0.04020` → tab **0.0402** ✓
  - ⚠️ **CV% uses the CORRECTED series**, not observed (`2.89/68.66 = 0.0421` ≠ 0.0402). Store CV% as the ratio (0.0402) and render ×100 = 4.02% in UI.
- **Band counts** — for each band, count readings whose weight falls in it; the report fills counts for **both OBS and CORR** columns (and reserves two more OBS/CORR pairs for additional machines on the same sheet).
  - Worked (CORR column, the 55–75 set): `<55`→4, `55–60`→6, `61–65`→0, `66–70`→0, `71–75`→0, `>75`→0 (corrected values 52.7–59.1 all sit ≤60) ✓
  - Worked (OBS column): `61–65`→2, `66–70`→5, `71–75`→3 (observed values 64.4–73.2) ✓

## 5. Worked example (real data)
Inputs (header): date 2026-01-05, shift A1, quality MESTA, machine SPREADER 4, feeder Upendra Roy.
Per roll (obs / MR%): (69.4/38)(71.32/40)(73.24/46)(67.14/37)(70.62/44)(65.91/45)(67.15/43)(71.22/43)(64.38/39)(66.24/42).

Compute → corrected = [58.34, 59.09, 58.19, 56.85, 56.89, 52.73, 54.47, 57.77, 53.73, 54.11].
Avg MR% = 41.7. Avg Obs = 68.66, Avg Corr = 56.22. StDev Obs = 2.89, StDev Corr = 2.26. CV% = 2.26/56.22 = **0.0402 (4.02%)**.
Bands (Spreader-4 → default 55–75 set): OBS → {61-65:2, 66-70:5, 71-75:3}; CORR → {<55:4, 55-60:6}. All rolls accounted for (10 each).

## 6. Proposed VOW data model

Flat header + JSON readings (mirrors `JuteSqcMorrahWt`). One saved test = one (date, shift, machine, quality) reading-set.

`jute_sqc_spreader_roll_wt`
| Column | Type | Notes |
|---|---|---|
| spreader_roll_wt_id | INT PK autoinc | |
| co_id | INT, NOT NULL, idx | |
| branch_id | INT, NULL | |
| entry_date | DATE, NOT NULL, idx | |
| spell_id | INT, NULL | → spell_mst |
| mc_id | INT, NULL | → machine_mst (spreader) |
| item_id | INT, NULL | quality → item_mst (item_type_id=2) |
| feeder_name | VARCHAR(255), NULL | free-text Phase-1 |
| roll_weights | JSON / TEXT | `[69.4, 71.32, …]` (10) |
| mr_pcts | JSON / TEXT | `[38, 40, …]` (10) |
| std_mr_pct | DECIMAL(5,2), NULL | snapshot of quality std MR at save |
| calc_avg_mr_pct | DECIMAL(5,2) | 41.70 |
| calc_avg_obs | DECIMAL(10,3) | 68.66 |
| calc_avg_corr | DECIMAL(10,3) | 56.22 |
| calc_stdev_obs | DECIMAL(10,4) | 2.89 |
| calc_stdev_corr | DECIMAL(10,4) | 2.26 |
| calc_cv_pct | DECIMAL(7,4) | 0.0402 (corrected ratio) |
| band_counts_obs | JSON | `{"<55":0,...}` |
| band_counts_corr | JSON | `{"<55":4,...}` |
| active | INT, NOT NULL, default 1 | soft-delete |
| updated_by | INT, NULL | |
| updated_date_time | TIMESTAMP | default current_timestamp |

Insert-only + soft delete. Recompute-on-read is also acceptable since readings+std are stored; persisting calc_* matches Morrah's stored-stats style.

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC` (router already registered).
- `GET /spreader_roll_wt_create_setup?co_id&branch_id` → dropdowns: spells (`spell_mst`), spreader machines (`machine_mst` filtered to spreader section), qualities (`item_mst` item_type_id=2) **with `std_mr_pct`**, and the machine→band-set mapping.
- `POST /create_spreader_roll_wt` → validate exactly 10 weights + 10 MR%, look up std MR from item_mst, compute stats + bands in Python (`compute_spreader_roll_wt_stats()`), insert.
- `GET /get_spreader_roll_wt_table?co_id&page&limit&search` → paginated list (date, shift, machine, quality, avg corr, CV%).
- `GET /get_spreader_roll_wt_by_id?id` → full record (JSON readings parsed) for the summary view.
- `GET /get_spreader_roll_wt_by_date?co_id&entry_date` → date-driven desktop summary.
- `POST /delete_spreader_roll_wt` → soft delete (active=0).

**Frontend** (`src/app/dashboardportal/juteSQC/r-08-04/`): mobile-first entry form — header (date/shift/quality/machine/feeder) then a 10-row weight+MR grid with a trailing live "corrected" preview; date-driven desktop summary grid with band-distribution + CV%. Route consts in `api.ts` under `apiRoutesPortalMasters` (e.g. `SPREADER_ROLL_WT_*`); calls via `fetchWithCookie`. **Masters to link:** `spell_mst`, `machine_mst`, `item_mst` (raw jute), HRMS employee (Phase-2 for feeder).

## 8. Open questions (NEEDS OWNER DECISION)
- **Weight-band storage** (process×machine): store band edges on `machine_mst` (option A) vs. two coded band-sets keyed by a machine flag (option B)? **NEEDS OWNER DECISION.**
- MESTA's **STD MR%** is not printed on this tab; derived = 16. Confirm the value and confirm it is read from the (new) `item_mst.std_mr_pct`.
- CV% confirmed to use the **corrected** series — confirm UI should display as percent (×100) and whether any pass/fail CV band exists for spreader roll weight (none seen).
- Sample size fixed at **10 rolls** — confirm it is always 10 (Morrah-style) and never variable.
- The tab reserves 3 OBS/CORR band-count column pairs — confirm whether one saved entry = one machine (recommended) or one sheet aggregates several machines side-by-side.
- "Feeder EB No." — is EB a payroll/employee number to link to HRMS, or just a name? Keep free-text Phase-1.
- Phase-2 link: "rolls actually made" from spreader production transaction (not wired now).
