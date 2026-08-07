# R-08-23 — Bag Weight Summary (I.S.O.)
**Stage:** finishing (sewing / packing — finished bag)  **Status:** UNBUILT
**Source tab:** `R023` (master "Daily Summary Date Select")   **DSR workbook:** `1WG_PRFZQ8bK9QKdQjpiSlEr3KjRi7aEuvpQDNXEP1z0` (not shared)

## 1. Purpose
Measures the as-sewn weight of finished jute bags of a given **bag type** (e.g. A-TYPE, or a
sacking spec like 48×26.5(6×7)) and corrects each weight to the bag's **standard MR%** so the lot
can be judged Heavy/Light against the **standard bag weight**. It is the packing-floor weight
control: keep average corrected weight close to STD (e.g. 580 g for A-TYPE) with low spread (CV%).

## 2. Inputs (the data-entry fields)
The sheet has **two parallel column blocks** (block 1 = A-TYPE STD 580g/STD MR 20%; block 2 =
"48×26.5(6×7)" STD 730g). Each block is the same shape; treat block = one **header + reading-set**.
In VOW each saved entry is one bag type for one date — the desktop summary can show several side by side.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | header; sheet shows `2026-01-05` |
| bag_type / quality | select | `item_mst` (bag item, item_grp parent `item_type_id=2` family) OR bag-quality master — see §3 | yes | header; "A-TYPE", "48×26.5(6×7)" |
| co_id / branch_id | header | sidebar | yes | standard scope |
| sl_no | int | — | yes | per-reading (1…N, up to 24 rows) |
| mr_reading_pct | decimal | operator | yes | per-reading; e.g. 17, 18, 22, 17.5 |
| obs_bag_weight_gm | decimal | operator | yes | per-reading; observed sewn-bag weight in grams, e.g. 541 |
| (corr_bag_weight_gm) | decimal | **computed** | no | per-reading; NOT entered — see §4 |

Notes: up to **24 reading rows** per block; in the cached data only 20 are filled. Empty rows are
ignored in the averages (AVERAGE over filled rows only). No machine/loom/spell on this report.

## 3. Standards & constants used

| Standard | Example value (sheet) | Compared to | Where it should live in VOW (decision #2) |
|---|---|---|---|
| STD bag weight (gm) | A-TYPE = **580** (+8/−6); 48×26.5(6×7) = **730** (also seen 767, 686–788 range) | corrected & observed avg → HY/LT% | per bag-type/quality master row (see open question) |
| STD MR% (regain) | **20%** (+2) for jute bags (Hessian≈16, Sacking≈20) | used in weight correction | per bag-quality `std_mr_pct` column |
| STD weight tolerance | +8 / −6 gm; range e.g. 721–828, 686–788 | acceptance band | optional `std_wt_tol_hi`/`std_wt_tol_lo` |
| STD length / width | 122 cm / 67 cm (in header text) | — (not computed here; lives in R-08-24) | bag-quality master |

**Std-value storage (decision #2 = extend existing masters):**
- `std_mr_pct` for the bag quality → add to whichever master holds the bag/finished-bag item. Yarn
  already has `jute_yarn_mst.std_mr_pct`; the bag finished-good has no equivalent yet.
- **⚠️ NEEDS OWNER DECISION (process × quality standards):** STD bag weight (580 vs 730 vs 767) and
  the ± weight tolerance vary by **bag type / quality**, not by a single global constant, and there
  is no existing per-bag-quality master carrying a `std_weight`. Two concrete reconciliations,
  pick one:
  1. **Add `std_weight`, `std_mr_pct`, `std_wt_tol_hi`, `std_wt_tol_lo` columns to the bag's
     `item_mst` row** (finished-bag item), since the bag type *is* the item. Cleanest if every bag
     type is an item_mst row.
  2. If bag types are modelled as a **line/bag-quality master** (e.g. `jute_quality_mst` line rows),
     add the same columns there, keyed per bag quality.
  Do **not** create a standalone "bag standards" table.

## 4. Calculations (formulas)

- **Corrected bag weight (per reading)** =
  `obs_bag_weight × (100 + STD_MR_pct) / (100 + mr_reading_pct)`
  CV%/correction constant: STD_MR_pct comes from the bag quality (**20** for A-TYPE here).
  Worked: row 1 → `541 × (100+20) / (100+17) = 541 × 120 / 117 = 554.87` ✓ (sheet 554.872).
  Worked: row 12 → `610 × 120 / 122 = 600.0` ✓.
- **Average MR%** = mean(mr_reading over filled rows). Worked: 18.675 ✓ (shown 18.68).
- **Average OBS weight** = mean(obs over filled rows) = **564.95** ✓.
- **Average CORR weight** = mean(corr over filled rows) = **571.10** ✓.
  (There is also a separate "CORRECTED" cell = 571.26 computed as `avg_obs ×
  (100+stdMR)/(100+avg_MR)` = `564.95 × 120 / 118.675 = 571.26`. ⚠️ Confirm: the report shows BOTH
  the row-wise mean of corrected (571.10) and the avg-of-avgs corrected (571.26). Store/show the
  row-wise mean as primary; expose the avg-of-avgs only if the owner wants it.)
- **StDev** = SAMPLE (n−1) of the column over filled rows → Python `statistics.stdev`,
  SQL `STDDEV_SAMP`. Worked: obs StDev = **28.48**; corr StDev = 218.5 (⚠️ the corr StDev 218.5 is
  inflated by 24-vs-20 row mismatch / blank-as-0 in the sheet's range — recompute over filled rows
  only; do not replicate the sheet's blank-row bug).
- **CV%** = `StDev / mean × 100` (weight-CV variant). MR CV% = 1.398/18.675 = **7.49%** ✓;
  OBS CV% = 28.48/564.95 = **5.04%** ✓. (Sheet stores as fraction 0.0749, 0.0504.)
- **OBS HY/LT %** = `(avg_obs − STD_bag_wt) / STD_bag_wt × 100` =
  `(564.95 − 580)/580 = −2.59%` ✓.
- **CORR HY/LT %** = `(avg_corr − STD_bag_wt) / STD_bag_wt × 100` =
  `(571.10 − 580)/580 = −1.53%` ✓. (Sheet uses 571.26 → −1.507; ⚠️ Confirm which corrected avg
  feeds HY/LT — sheet uses the avg-of-avgs 571.26, giving −1.507.)
  Negative = lot is **Light** vs STD; positive = **Heavy**.

## 5. Worked example (real data, A-TYPE block, 20 readings)
Inputs (mr, obs): (17,541)(18,605)(19,576)(18,575)(18,559)(19,588)(19,547)(18,566)(19,541)
(18,566)(19,576)(22,610)(20,586)(21,610)(21,595)(18,540)(17.5,530)(18,520)(17,523)(17,545).
STD bag wt = 580, STD MR = 20.
- Corr row 1 = 541×120/117 = **554.87**; corr row 12 = 610×120/122 = **600.0**; corr row 20 =
  545×120/117 = **558.97**.
- Avg MR = **18.68**; Avg OBS = **564.95**; Avg CORR (row-wise) = **571.10**.
- OBS StDev = **28.48** → OBS CV% = **5.04%**; MR CV% = **7.49%**.
- OBS HY/LT = (564.95−580)/580 = **−2.59%** (Light); CORR HY/LT (using 571.26) = **−1.51%** (Light).

## 6. Proposed VOW data model

Header + JSON-readings (mirrors `JuteSqcMorrahWt`, raw readings as JSON). One row = one bag type for
one date/block.

`jute_sqc_bag_weight`
| Column | Type | Notes |
|---|---|---|
| bag_weight_id | INT PK autoincr | |
| co_id | INT NOT NULL idx | |
| branch_id | INT NULL | |
| entry_date | DATE NOT NULL idx | |
| item_id | INT NULL idx | bag type / quality (item_mst) |
| bag_type_label | VARCHAR(100) NULL | free label fallback ("A-TYPE","48×26.5(6×7)") |
| std_bag_weight | DECIMAL(8,2) NULL | snapshot of std at entry time |
| std_mr_pct | DECIMAL(5,2) NULL | snapshot of std MR used for correction |
| readings | JSON / VARCHAR(2000) NOT NULL | `[{"mr":17,"obs":541}, …]` |
| calc_avg_mr | DECIMAL(6,3) NULL | computed |
| calc_avg_obs_wt | DECIMAL(8,2) NULL | computed |
| calc_avg_corr_wt | DECIMAL(8,2) NULL | computed (row-wise mean) |
| calc_obs_stdev | DECIMAL(8,3) NULL | computed |
| calc_obs_cv_pct | DECIMAL(6,2) NULL | computed |
| calc_obs_hy_lt_pct | DECIMAL(6,2) NULL | computed |
| calc_corr_hy_lt_pct | DECIMAL(6,2) NULL | computed |
| active | INT NOT NULL default 1 | soft-delete |
| updated_by | INT NULL | |
| updated_date_time | TIMESTAMP default now | |

Insert-only + soft-delete. Recompute stats server-side on save; store snapshots of std for audit.

## 7. Proposed endpoints & pages
Backend (prefix `/api/juteSQC`):
- `GET  /bag_weight_create_setup` — dropdowns: bag types (item_mst) **with std_bag_weight/std_mr_pct**.
- `POST /bag_weight_save` — validate ≥1 reading, compute stats (Python, like `compute_morrah_stats`), insert.
- `GET  /bag_weight_by_date` — list entries for a date (+ optional item_id) with computed columns.
- `GET  /bag_weight_table` / `GET /bag_weight_by_id` — paginated list / single (parse `readings` JSON).
- `POST /bag_weight_delete` — soft delete (`active=0`).

Frontend (`juteSQC/r-08-23/`): mobile-first entry form — pick date + bag type, add reading rows
(mr%, obs wt) with a trailing blank row; show live corr/avg/CV; desktop date-driven summary grid
(one block per bag type, AVG/StDev/CV%/HY-LT). Route consts in `api.ts` under `apiRoutesPortalMasters`
(`BAG_WEIGHT_*`); calls via `fetchWithCookie`.

**Masters to link:** bag type/quality (`item_mst`), and the std columns from §3.

## 8. Open questions (NEEDS OWNER DECISION)
- Where do bag types live — `item_mst` finished-bag rows or a bag-quality master? Std columns go there.
- **Process×quality standards storage:** add `std_weight`/`std_mr_pct`/`std_wt_tol_hi/lo` to the
  bag's `item_mst` row, or to a bag-quality master? (decision #2 forbids a new standards table.)
- Confirm STD_MR per bag type (A-TYPE=20 seen; is Hessian-bag 16 vs Sacking-bag 20?).
- Which corrected average feeds HY/LT% — row-wise mean (571.10) or avg-of-avgs (571.26)? Sheet uses 571.26.
- Confirm StDev uses **filled rows only** (sheet's corr StDev 218.5 is a blank-row bug — do not replicate).
- Max readings per entry: cap at 24 (sheet) or allow open-ended?
- Is the ±8/−6 tolerance band a hard pass/fail flag to surface, or display-only?
- The second column block (730g spec) — is it a separate bag type entry or always paired? Treat as separate entries.
