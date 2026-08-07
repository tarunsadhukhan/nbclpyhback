# R-08-24 — Bag Checking Report (I.S.O.)
**Stage:** finishing (finished-bag inspection)  **Status:** UNBUILT
**Source tab:** `R024` (A/B-TYPE) + `R024(BT)` (B-TYPE / BT-construction variant)   **DSR workbook:** `1OrbXjbe2VC8AN3doyyhJeEN_jXFHiYAzfjrDIq2knEk` (not shared)

## 1. Purpose
Full dimensional + weight + defect inspection of finished jute bags from a given **vendor / bag
type**. Each bag is checked for length, width, ends/dm, picks/dm, stitch/dm, MR%, weight, and visual
defects, then compared to the bag-type standard (STD length 94 cm, width 57 cm, ends 46±2, picks
50±2, stitch 10±1, weight 580 g, MR 20%). It is the acceptance gate for purchased/finished bags.

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | header; `2026-01-05` |
| bag_type / quality | select | bag-type list (A-TYPE / B-TYPE / 48×26.5 specs) — see §3 | yes | header; drives STD lookup (sheet VLOOKUP `A3` → `N:O`) |
| vendor | select | `party_mst` (party_id) | yes | header; "PUNJAB" |
| id_code | text/select | colour/ID code list | yes | header; "BLUE" |
| co_id / branch_id | header | sidebar | yes | scope |
| sl_no | int | — | yes | per-bag (1…20) |
| length_cm | decimal | operator | yes | per-bag; e.g. 94 |
| width_cm | decimal | operator | yes | per-bag; e.g. 57 |
| ends_dm | decimal | operator | yes | per-bag; ends per dm, e.g. 44 |
| picks_dm | decimal | operator | yes | per-bag; picks per dm, e.g. 48 |
| mr_pct | decimal | operator | yes | per-bag; e.g. 17 |
| bag_wt_gm | decimal | operator | yes | per-bag; observed weight, e.g. 541 |
| defects | text | defect list / free text | no | per-bag; "Nil","Float","Floatx2","S. G","C. G","S. G, float" |
| stitch_dm | decimal | operator | yes | per-bag; stitches per dm, e.g. 9 (8.5 seen) |
| (corr_wt_gm) | decimal | **computed** | no | per-bag; NOT entered — §4 |

Header vs per-reading: date / bag_type / vendor / id_code are **header**; the rest are **per-bag**
(20 bags per sheet). The `R024(BT)` tab is the same layout for a different construction (STD
ends 64±2, picks 28±2) — same table, different STD set.

## 3. Standards & constants used

| Standard | Example value | Tolerance | Compared to |
|---|---|---|---|
| STD bag weight | 580 gm (A/B-TYPE); 730/767 (48×26.5 specs) | +8/−6 | corrected avg → HY/LT% |
| STD length | 94.0 cm | +4/−0 | avg length |
| STD width | 57.0 cm | +4/−0 | avg width |
| STD ends/dm | **46.0** (A/B-TYPE) / **64.0** (BT variant) | ±2 | avg ends |
| STD picks/dm | **50.0** (A/B-TYPE) / **28.0** (BT variant) | ±2 | avg picks |
| STD stitch/dm | 10 | ±1 | avg stitch |
| STD MR% | 20% | +2 | weight correction |

The sheet stores the full STD string per bag type in a side table (`N:O`) and pulls it with
`VLOOKUP(A3, N:O, 2, 0)` — i.e. **STD set is keyed by bag type**, and the BT variant proves ends/picks
differ by construction.

**Std-value storage (decision #2 = extend existing masters):**
- **⚠️ NEEDS OWNER DECISION (process × quality standards):** this report needs **seven** STD values
  per bag type (weight, length, width, ends, picks, stitch, MR) plus their tolerances. None of these
  live on an existing master today. Two concrete reconciliations, pick one:
  1. **Add the seven `std_*` columns + tolerances to the bag's `item_mst` row** (the bag type *is*
     the finished-good item) — mirrors how `jute_yarn_mst.std_mr_pct` extends the yarn item.
  2. Add them to a **bag-quality / line-quality master** keyed per bag type (if bag types are not
     item_mst rows). The "BT" construction would be its own quality row so ends=64/picks=28 are stored once.
  Do **not** create a standalone "bag standards" table. This is the canonical VOW equivalent of the
  sheet's `N:O` lookup table.

## 4. Calculations (formulas)

- **Corrected weight (per bag)** = `bag_wt × (100 + STD_MR) / (100 + mr_pct)` (STD_MR = 20).
  Worked: bag 1 → `541 × 120/117 = 554.87` ✓; bag 18 → `520 × 120/118 = 528.81` ✓.
- For **each numeric column** (length, width, ends, picks, mr, bag_wt, stitch, corr_wt):
  - **AVG** = mean over filled bags. e.g. length 93.9, width 57.15, ends 43.8, picks 47.9,
    mr 18.675, bag_wt 564.95, stitch 8.975, corr_wt 571.10 ✓.
  - **StDev** = SAMPLE (n−1) → Python `statistics.stdev` / SQL `STDDEV_SAMP`. e.g. length 0.3078,
    bag_wt 28.48, stitch 0.1118 ✓.
  - **CV%** = `StDev / AVG × 100` (weight-CV variant). e.g. bag_wt 28.48/564.95 = **5.04%** ✓;
    length 0.3078/93.9 = **0.33%** ✓. (Sheet stores fraction.)
  - **MIN / MAX** = min/max over filled bags. e.g. bag_wt MIN 520, MAX 610 ✓.
- **OBS (HY/LT)** = `(avg_bag_wt − STD_bag_wt)/STD_bag_wt × 100` = `(564.95−580)/580 = −2.595%` ✓
  (sheet stores −0.02595 as fraction).
- **Corrected (HY/LT)** = `(avg_corr_wt − STD_bag_wt)/STD_bag_wt × 100`. Sheet = **−1.535%**
  (−0.01535). ⚠️ Confirm: 571.10 → (571.10−580)/580 = −1.534% ✓ (this report uses the **row-wise
  corr mean** 571.10, unlike R-08-23 which used the avg-of-avgs).
- **Defects** are categorical (stored verbatim); not aggregated numerically in the sheet. ⚠️ Confirm
  whether VOW should also count defect occurrences (e.g. # of "Float") — sheet does not.

## 5. Worked example (real data — R024, A-TYPE, 20 bags)
Header: date 2026-01-05, vendor PUNJAB, id_code BLUE, bag_type A-TYPE (STD wt 580, len 94, wid 57,
ends 46, picks 50, stitch 10, MR 20).
Bag 1: len 94, wid 57, ends 44, picks 48, mr 17, wt 541, defect "Float", stitch 8.5 →
corr = 541×120/117 = **554.87**.
Bag 6: len 94, wid 57, ends 43, picks 46, mr 19, wt 588, defect "S. G", stitch 9 → corr = 588×120/119 = **592.94**.
Aggregates: AVG len 93.9 / wid 57.15 / ends 43.8 / picks 47.9 / mr 18.68 / wt 564.95 / stitch 8.98 /
corr 571.10. bag_wt StDev 28.48 → CV% 5.04%. MIN/MAX wt 520/610.
OBS HY/LT = **−2.59%** (Light); Corrected HY/LT = **−1.53%** (Light).
(`R024(BT)` example is empty in the cached snapshot — all `#N/A`/`#DIV/0!` because no bags entered;
it confirms the BT STD set ends=64/picks=28 only.)

## 6. Proposed VOW data model

Header + detail (one row per bag) — this is a true multi-column per-reading set, so **detail rows**
fit better than JSON (mirrors `JuteSqcSpinningQrCv` + `…Dtl`).

`jute_sqc_bag_check` (header)
| Column | Type | Notes |
|---|---|---|
| bag_check_id | INT PK autoincr | |
| co_id | INT NOT NULL idx | |
| branch_id | INT NULL | |
| entry_date | DATE NOT NULL idx | |
| item_id | INT NULL idx | bag type / quality |
| bag_type_label | VARCHAR(100) NULL | "A-TYPE","B-TYPE","48×26.5(6×7)" |
| party_id | INT NULL idx | vendor (party_mst) |
| id_code | VARCHAR(50) NULL | "BLUE" |
| std snapshot cols | DECIMAL | `std_bag_weight, std_length, std_width, std_ends, std_picks, std_stitch, std_mr_pct` (snapshot at save) |
| calc_* cols | DECIMAL | per-column avg/stdev/cv/min/max + `calc_obs_hy_lt_pct`, `calc_corr_hy_lt_pct` |
| active / updated_by / updated_date_time | | standard |

`jute_sqc_bag_check_dtl` (one row per bag)
| Column | Type |
|---|---|
| bag_check_dtl_id | INT PK |
| bag_check_id | INT idx (FK) |
| sl_no | INT |
| length_cm, width_cm, ends_dm, picks_dm, mr_pct, bag_wt_gm, stitch_dm | DECIMAL |
| defects | VARCHAR(200) |
| corr_wt_gm | DECIMAL (computed) |

Insert-only + soft-delete. Recompute all aggregates server-side on save (store snapshots for audit).

## 7. Proposed endpoints & pages
Backend (prefix `/api/juteSQC`):
- `GET  /bag_check_create_setup` — bag types (+ their 7 std values), vendors (`party_mst`), id-code list, defect list.
- `POST /bag_check_save` — validate ≥1 bag, compute corr per bag + all aggregates, insert header+detail.
- `GET  /bag_check_by_date` — header + computed aggregates for a date (+ optional bag_type/vendor).
- `GET  /bag_check_by_id` — header + detail rows.
- `POST /bag_check_delete` — soft delete.

Frontend (`juteSQC/r-08-24/`): mobile-first entry — header (date, bag type, vendor, id code) then a
repeating bag row (8 numeric fields + defect select/text) with trailing blank row; live corr wt +
running averages; desktop date-driven summary grid (AVG/StDev/CV%/MIN/MAX per column + HY/LT%, with
the STD row shown for comparison). Route consts in `api.ts` (`BAG_CHECK_*`); `fetchWithCookie`.

**Masters to link:** bag type (`item_mst` / bag-quality), vendor (`party_mst`), id-code list, defect list.

## 8. Open questions (NEEDS OWNER DECISION)
- Where do bag types and their **7 STD values** live — `item_mst` row vs bag-quality master? (sheet's `N:O`).
- Is "BT" a separate bag type (own quality row with ends=64/picks=28) or a flag on B-TYPE? Affects STD storage.
- Source of `id_code` ("BLUE") — colour master, or free text? And `defects` — controlled list or free text?
- Should VOW aggregate/flag defects (counts per defect type), or store verbatim only (sheet stores verbatim)?
- Tolerances (±2, ±1, +4/−0, +8/−6): surface as pass/fail flags per bag/column, or display STD only?
- Vendor: tie to `party_mst` party_id, or free text? (sheet free text "PUNJAB").
- Confirm corrected HY/LT uses the **row-wise corr mean** (571.10) here (it does), vs R-08-23's avg-of-avgs — reconcile across reports.
- Bag count per entry: fixed 20 or open-ended?
