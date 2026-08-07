# R-08-16 (Count) — Yarn Count / Parameter
**Stage:** spinning  **Status:** BUILT
**Source tab:** R-08-16 Yarn Test Parameter (master "Daily Summary Date Select")   **DSR workbook:** spinning DSR (not shared)

> AS-BUILT spec. Real implementation:
> - BE router `src/juteSQC/spinning_sqc.py` (count surface), queries `src/juteSQC/spinning_sqc_query.py`, ORM `JuteSqcSpinningCount` in `src/juteSQC/models.py`.
> - FE page `vowerp3ui/src/app/dashboardportal/juteSQC/spinning/page.tsx` → tab **"R-08-16 Yarn Parameter"** (tab index 0), components `_components/CountForm.tsx` + `_components/CountGrid.tsx`, hooks `useSqcCountSetup.ts` / `useSqcCountByDate.ts`, types `types/sqcSpinningTypes.ts`.
> - Route consts `apiRoutesPortalMasters.SPINNING_SQC_COUNT_*` in `vowerp3ui/src/utils/api.ts`.

## 1. Purpose
Measures the actual yarn count (lb per 14,400 yds) spun on each spinning frame and corrects it to the standard moisture regain so it can be compared to the yarn's standard count. Flags frames running heavier/coarser (`$$`) or lighter (`$`) than std, per quality and per spell, so spinning can adjust draft/speed.

## 2. Inputs (the data-entry fields)
Multi-observation entry: the operator records one yarn-test reading per (date, spell, frame, yarn quality); many readings per day. Save inserts each as a fresh row. Sheet header: `Test length = 75 YDS / Bobbin (6 sample bobbins → 6×75 = 450 yds)`.

| Field | Type | Source/Master | Required | Header/per-reading | Notes |
|---|---|---|---|---|---|
| `entry_date` | date | sidebar/today | yes | header (whole save) | |
| `spell_id` | int | `spell_mst` (status=1) | no | per-reading | "SPELL" (A1/A2…); stored per reading |
| `mc_id` | int | `machine_mst` (spinning type, via `spinning_query.get_spinning_machines_query`) | no | per-reading | "FRAME NO" |
| `item_id` | int | yarn item: `jute_yarn_mst` join `item_mst`, `item_grp_mst.item_type_id=4` | yes | per-reading | "QUALITY" — e.g. HESSIAN WEFT-8.8Lb |
| `dp` | float | manual | no | per-reading | Draft/parameter; **store-only**, not used in calc |
| `tp` | float | manual | no | per-reading | Twist/parameter; **store-only** |
| `wt_450_gms` | float (g) | manual | no (but needed for count) | per-reading | "WT /450 YDS IN GMS" — weight of the 450-yd (6×75) sample; drives observed count |
| `mr_pct` | float | manual | no (needed for corrected) | per-reading | "MR" — moisture regain % of the sample |
| `co_id`, `branch_id` | int | sidebar | yes | header | |

DC, TC, REMARKS columns on the sheet are NOT captured (DC/TC are spindle/twist constants 600/180; REMARKS is free text — neither persisted). `observed_count`/`corrected_count` may be sent by the FE as a preview but are **ignored and recomputed server-side**.

## 3. Standards & constants used
| Standard | Example (sheet) | As-built location | Notes |
|---|---|---|---|
| Std count `STD(LB)` | 8.8, 9.0, 9.5, 10, 13.2, 16.2, 20 (lb) | `jute_yarn_mst.jute_yarn_count` (`std_count`) — satellite keyed by `item_id` | Exposed via `get_yarn_qualities_query()`; surfaced in setup `yarn_items[].std_count`. |
| Std MR% (per quality) | Hessian≈16, Sacking≈20 | **`jute_yarn_mst.std_mr_pct`** — satellite keyed by `item_id` | Read at save (`get_quality_std_mr_query`) for the correction. |
| Count factor | 14400/454 ≈ 31.718 | Python `_COUNT_FACTOR` in `spinning_sqc.py` | Sample 450 yds → lb/14,400 yds. ⚠️ uses **454** g/lb (briefing §4 derived 453.592). |
| `$$` heavy flag | obs higher than std by +0.2 | **NOT built** | Sheet marks `$$` (coarse/heavy) / `$` (light) per the ±0.2 threshold; the as-built does NOT compute or store these symbols. |

**Std-storage note (briefing §9a):** the yarn quality IS an `item_mst` row; its standards (std count, std MR%) live in the existing satellite **`jute_yarn_mst`** keyed by `item_id` — this is exactly the §9a pattern and is REUSED as-is (no new table needed for count/MR). Only the `$$`/`$` band threshold (±0.2) and any per-quality CV band have no home yet.

## 4. Calculations (formulas)
Computed server-side at **save** (`sqc_count_save`), recomputed from raw inputs — FE values ignored.

| Output | Formula (as-built) | Worked (row: HESSIAN WEFT-8.8Lb, frame 2) |
|---|---|---|
| `observed_count` (OBS LB) | `round((wt_450_gms / 450) × (14400 / 454), 2)` | wt=128 → 128/450×31.718 = **9.02** (sheet shows 9.03 with the 453.592 divisor — see ⚠️) |
| `corrected_count` (CORR LB) | `round(observed / (100 + mr_pct) × (100 + std_mr_pct), 2)` | obs 9.03, MR 17, std_mr 16 → 9.03×116/117 = **8.95** ✓ (sheet 8.953) |
| Act count per quality (read) | `AVG(observed_count)` grouped by `item_id` for the date | `get_sqc_count_avg_query` → `averages[].avg_count` |
| Avg corrected (read) | `AVG(corrected_count)` per `item_id` | `averages[].avg_corrected` |
| Obs count (read) | `COUNT(*)` readings per `item_id` | `averages[].obs_count` |

CV% is NOT computed for this report (count report has no StDev/CV — that is R-08-15 QR&CV). The sheet's per-quality AVG-A1 / AVG-A2 / AVG(A1&A2) blocks correspond to grouping the readings by spell then averaging; the as-built only does AVG per `item_id` across the date (spell-split averaging is not built — see §8).

⚠️ Confirm: `_COUNT_FACTOR = 14400/454` vs the textbook `14400/453.592`. With 454 the example gives 9.02 not 9.03; the small discrepancy is the g/lb constant. Owner to confirm the intended divisor.

## 5. Worked example (real data)
From the R16 cached tab, quality HESSIAN WEFT-8.8Lb, spell A2:
- Frame 2: DP 39, TP 40, WT/450 = 128 g, MR 17. OBS = 9.03, CORR = 8.953, STD = 8.8.
- Frame 47: DP 41, TP 41, WT/450 = 132 g, MR 17. OBS = 9.31, CORR = 9.23, STD = 8.8, flagged `$$`.
- Sheet AVG-A2: MR 17, OBS 9.17, CORR 9.092, STD 8.8, `$$`.

As-built reproduction: each frame inserts one `jute_sqc_spinning_count` row with observed/corrected recomputed; the by-date read returns `averages` for item_id "HESSIAN WEFT-8.8Lb" with `avg_count ≈ 9.17`, `avg_corrected ≈ 9.09`, `obs_count = 2`. The `$$` flag (both > 8.8 + 0.2) is NOT emitted by the API.

## 6. As-built data model
Table `jute_sqc_spinning_count` (ORM `JuteSqcSpinningCount`, `src/juteSQC/models.py`, legacy `Column(...)` style on `mst.Base`).

| Column | Type | Notes |
|---|---|---|
| `spinning_sqc_count_id` | Integer PK, autoincrement | |
| `co_id` | Integer, not null, indexed | |
| `branch_id` | Integer, null | |
| `entry_date` | Date, not null, indexed | |
| `spell_id` | Integer, null | → `spell_mst` |
| `mc_id` | Integer, null | → `machine_mst` (frame) |
| `item_id` | Integer, not null, indexed | yarn item → `item_mst` / `jute_yarn_mst` |
| `dp` | DECIMAL(10,3), null | store-only |
| `tp` | DECIMAL(10,3), null | store-only |
| `wt_450_gms` | DECIMAL(10,3), null | sample weight, drives observed count |
| `mr_pct` | DECIMAL(5,2), null | sample MR%, drives corrected count |
| `observed_count` | DECIMAL(10,3), not null, default 0 | computed at save |
| `corrected_count` | DECIMAL(10,3), null | computed at save (uses `jute_yarn_mst.std_mr_pct`) |
| `active` | Integer, not null, default 1 | soft-delete |
| `updated_by` | Integer, null | |
| `updated_date_time` | TIMESTAMP, server default now | |

Flat, insert-only, one row per observation; averages computed at read by GROUP BY `item_id`. No `_dtl` table.

## 7. As-built endpoints & pages
Router prefix `/api/juteSQC`. Portal persona.

| Endpoint | Method | Returns / does |
|---|---|---|
| `/sqc_count_setup` | GET | Needs `co_id`, `entry_date` (branch opt). Returns `{data:{machines, yarn_items(+std_count,+std_mr_pct), spells, entries}}` — dropdowns + already-saved readings for the date. |
| `/sqc_count_save` | POST | Body `{co_id, branch_id, entry_date, entries:[{spell_id, mc_id, item_id, dp, tp, wt_450_gms, mr_pct}]}`. Recomputes observed/corrected per row (std_mr cached per item_id), inserts each. Returns `{data:{saved}}`. |
| `/sqc_count_by_date` | GET | `{data:{readings, averages}}` — readings (per-frame) + per-quality `avg_count`/`avg_corrected`/`obs_count`. |
| `/sqc_count_delete/{count_id}` | DELETE | Soft-delete (active=0) one reading. `{data:{message}}`. |

Route consts: `SPINNING_SQC_COUNT_SETUP`, `SPINNING_SQC_COUNT_SAVE`, `SPINNING_SQC_COUNT_BY_DATE`, `SPINNING_SQC_COUNT_DELETE` (base path; caller appends `/${id}`).

**FE:** tab 0 ("R-08-16 Yarn Parameter") of `juteSQC/spinning/page.tsx`. `CountForm` = responsive entry (frame/quality/spell + DP/TP/WT/MR with live observed/corrected preview); `CountGrid` = date-driven readings + averages. This count report ALSO feeds R-08-15 QR&CV: that report reads `AVG(observed_count)`/`AVG(mr_pct)` per `item_id` from these saved rows (`get_sqc_count_obs_mr_avg_query`) rather than re-entering them.

**Masters linked (as-built):** `machine_mst` (spinning frames), `item_mst`+`item_grp_mst` (`item_type_id=4`) + `jute_yarn_mst` (yarn identity, std_count, std_mr_pct), `spell_mst` (status=1).

## 8. Open questions (NEEDS OWNER DECISION)
- **`$$` / `$` flags not built:** the heavy(`$$`, std+0.2)/light(`$`) symbols on the sheet are not computed or returned. Confirm exact threshold (±0.2 vs other) and add to read output / FE band.
- **g/lb divisor:** as-built `_COUNT_FACTOR = 14400/454`; textbook 14400/453.592 gives the sheet's 9.03. Confirm intended constant.
- **Spell-split averaging:** sheet shows AVG-A1, AVG-A2, AVG(A1&A2) per quality; as-built averages across all spells per item_id only. Confirm whether per-spell averages are required.
- **DP/TP/DC/TC:** stored DP/TP are unused; DC/TC/REMARKS not captured. Confirm whether DP/TP feed any TPI/draft check (R-08-16 Speed/TPI is a separate `jute_sqc_spinning_entry` surface — see RHMR/Speed spec) or are reference-only.
- **CV band per quality:** none stored; if a count CV band is wanted it would need a per-(item_id[,process]) satellite — case-by-case (briefing §9a).
