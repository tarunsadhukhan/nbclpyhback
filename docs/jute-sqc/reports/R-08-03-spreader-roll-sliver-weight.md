# R-08-03 — Spreader Roll Sliver Weight (I.S.O.)
**Stage:** selection / batching (spreader)  **Status:** UNBUILT
**Source tab:** `R-08-03 SPREADER ROLL SLIVER WEIGHT (I.S.O.)` (master "Daily Summary Date Select")   **DSR workbook:** `11-5G5S3klBie3fn4hBxHyaGshPRLcnXkGA6NLSOH2O4` (sheet `GMDSR!A2:I55`, not shared)

## 1. Purpose
Checks the **sliver (web) weight per unit length** coming off a spreader roll — i.e. the linear density of the sliver, not the whole roll. A 5-yard length of sliver is cut and weighed, expressed in **LB per 100 yds**, with MR% per cut. Weights are corrected to the quality's standard MR% and averaged so the spreader's sliver count (lb/100yds) can be compared to standard, with StDev/CV% measuring uniformity. This is the linear-density sibling of R-08-04 (whole-roll weight).

> Header literal: `UOM for Roll- LB` and `(SAMPLE LENGTH 5 YDS & SAMPLE WT IN LBS/100 YDS)`. So a 5-yd cut is weighed, then **scaled to lb/100yds** (×20) before comparison. Weight is recorded/compared **directly** — there is **no count conversion** (per briefing §4, reports that state their sample length compare weight directly to STD).

## 2. Inputs (the data-entry fields)

The tab is laid out as **up to 4 reading-sets side-by-side** (4 OBS/CORR column pairs across the header row), each a `(SHIFT, CATEGORY, QUALITY, MACHINE NO)` group with up to **12** observed-weight + MR% pairs. Treat each column-group as one saved entry.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | **Header**. Cached = 2026-01-05. |
| shift / spell | dropdown | `spell_mst` (spell_id) | yes | **Header** ("SHIFT"). |
| category | dropdown | TBD master (see Q) | no | **Header** ("CATEGORY"). Not labelled with a value in this cached snapshot — confirm what list it draws from (likely roll/process category). |
| quality | dropdown | `item_mst` (raw jute, item_type_id=2) | yes | **Header** ("QUALITY"). Drives STD MR% lookup. |
| machine_no | dropdown | `machine_mst` (spreader section) | yes | **Header** ("MACHINE NO"). |
| observed_weight_1 … _12 | decimal (lb / 100 yds) | operator entry | yes (≥1, ≤12) | **Per-reading**. Sliver weight of the 5-yd cut, scaled to lb/100yds. Variable count up to 12 (blank rows allowed). |
| mr_pct_1 … _12 | decimal (%) | operator entry | yes per filled reading | **Per-reading**. One MR% per weight cut. |

⚠️ The cached snapshot shows the **label scaffold but no entered values** for the reading rows (the source workbook wasn't imported on this date) and **STD MR% = `#N/A`** (the quality lookup returned nothing). Field set is fully confirmed from labels; example numeric values are taken from the sibling reports and the universal formula set.

## 3. Standards & constants used

| Standard | Example / source | Where it should live in VOW (decision #2) |
|---|---|---|
| **STD MR% per quality** | Tab shows `#N/A` (lookup failed this snapshot); jute base = 16, per-quality stored (Hessian≈16, Sacking≈20). | Add `std_mr_pct` to the **raw-jute quality master = `item_mst`** (item_type_id=2). Shared with R-08-01 / R-08-04. The `#N/A` proves the report **expects a per-quality STD MR lookup** — confirms the column must exist. |
| **STD sliver weight (lb/100yds)** | Not printed in this cached snapshot, but every spreader-sliver report compares Avg Corr to a target lb/100yds. | ⚠️ process×quality — see below. |
| **STD CV% band** | Not printed on this tab (no CV band column seen). | None enforced on R-08-03 in this snapshot — confirm whether a sliver-CV band applies (the card report R-08-05/06/07 does have one). |

### ⚠️ process × quality standards-storage question (RAISE — NEEDS OWNER DECISION)
A **standard sliver weight** for a quality at the **spreader** stage differs from the same quality's standard at breaker/drawing (briefing: HESSIAN finisher-drawing STD 125 lb but breaker differs). A single per-quality `item_mst.std_mr_pct` cannot hold a *process-specific weight target*, and decision #2 forbids a standalone standards table. Concrete reconciliations:
- **(A)** Add `std_sliver_wt` to the spreader **`machine_mst`** row (machine ⇒ process), so each spreader carries its sliver-weight target. Per-machine is the natural grain here since the report keys on MACHINE NO.
- **(B)** Add `std_sliver_wt` (+ optional `std_cv_low`/`std_cv_high`) to a **line-quality `item_mst`** row keyed per stage (a per-(quality, process) item row), if qualities already split by stage.

Recommendation: **(A)** for the weight target (keyed by machine = stage), **(B)** only if a CV band turns out to apply per quality. Mark **NEEDS OWNER DECISION**.

## 4. Calculations (formulas)

Correction constant = quality's STD MR% (per-quality; jute base 16). **CV% uses the corrected series** (consistent with R-08-04, which we verified).

- **Corrected sliver weight** = `Observed × (100 + STD_MR) / (100 + Observed_MR%)`
  - Worked (using the universal verified row — HESSIAN-style cut 20.32 @MR29, stdMR16): `20.32 × 116/129 = 18.27` ✓ (same correction algebra applies to lb/100yds units).
- **Avg Obs** = `mean(observed_weight filled)`
- **Avg Corr** = `mean(corrected filled)`
- **Avg Mr** = `mean(mr_pct filled)`
- **StDDev** = sample StDev (n-1) of the **corrected** weights (Python `statistics.stdev` / SQL `STDDEV_SAMP`). ⚠️ Confirm obs-vs-corr basis from a populated snapshot; R-08-04 used corrected, so default to corrected.
- **CV** = `StDDev / Avg Corr` (store ratio; render ×100 for %).

⚠️ Confirm: whether the 5-yd cut is pre-scaled to lb/100yds by the operator (header implies the *recorded* value is already lb/100yds) or whether the system multiplies the raw 5-yd weight by 20. Recommendation: operator enters the already-scaled lb/100yds value (matches the header label), system does no length scaling.

## 5. Worked example (real data)
The 2026-01-05 cached snapshot has the **label structure only** (reading cells empty; STD MR% = `#N/A`). End-to-end illustration using the correction verified in the universal set, applied to this report's structure:

Header: date 2026-01-05, shift A1, quality HESSIAN (std MR 16), machine SPREADER n.
Readings (obs lb/100yds / MR%): say (20.32/29), (21.47/32), (20.41/28) …
Corrected: 20.32×116/129 = 18.27; 21.47×116/132 = 18.87; 20.41×116/128 = 18.50 …
Avg Corr = mean(corrected); Avg Mr = mean(29,32,28,…); StDDev = stdev(corrected); CV = StDDev/AvgCorr.
*(Numbers above are illustrative of the algorithm — the real cached cells were not imported on this date; only the column/label structure is confirmed.)*

## 6. Proposed VOW data model

Flat header + JSON readings (mirrors `JuteSqcMorrahWt`; readings variable-length up to 12).

`jute_sqc_spreader_sliver_wt`
| Column | Type | Notes |
|---|---|---|
| spreader_sliver_wt_id | INT PK autoinc | |
| co_id | INT, NOT NULL, idx | |
| branch_id | INT, NULL | |
| entry_date | DATE, NOT NULL, idx | |
| spell_id | INT, NULL | → spell_mst (SHIFT) |
| category | VARCHAR(100), NULL | "CATEGORY" — pending master (Q) |
| mc_id | INT, NULL | → machine_mst (spreader) |
| item_id | INT, NULL | quality → item_mst (item_type_id=2) |
| sample_length_yds | DECIMAL(5,2), NULL | 5 (header constant) |
| weight_basis | VARCHAR(20), NULL | "LB/100YDS" (header constant) |
| observed_weights | JSON / TEXT | up to 12 values |
| mr_pcts | JSON / TEXT | parallel up to 12 |
| std_mr_pct | DECIMAL(5,2), NULL | snapshot at save |
| calc_avg_obs | DECIMAL(10,3) | |
| calc_avg_corr | DECIMAL(10,3) | |
| calc_avg_mr | DECIMAL(5,2) | |
| calc_stdev | DECIMAL(10,4) | sample StDev (corrected) |
| calc_cv_pct | DECIMAL(7,4) | StDev/AvgCorr ratio |
| active | INT, NOT NULL, default 1 | soft-delete |
| updated_by | INT, NULL | |
| updated_date_time | TIMESTAMP | default current_timestamp |

Insert-only + soft delete. Variable reading count (1–12) — validate ≥1 filled pair, weight>0 and MR%≥0 for each filled reading.

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC`.
- `GET /spreader_sliver_wt_create_setup?co_id&branch_id` → spells (`spell_mst`), spreader machines (`machine_mst`), qualities (`item_mst` item_type_id=2) with `std_mr_pct`, and the category list (pending Q).
- `POST /create_spreader_sliver_wt` → validate ≥1 (weight, MR%) pair (≤12), look up std MR, compute stats in `compute_spreader_sliver_stats()`, insert.
- `GET /get_spreader_sliver_wt_table?co_id&page&limit&search` → paginated list.
- `GET /get_spreader_sliver_wt_by_id?id` → full record (JSON parsed).
- `GET /get_spreader_sliver_wt_by_date?co_id&entry_date` → desktop date summary (may show several machine column-groups for the day).
- `POST /delete_spreader_sliver_wt` → soft delete.

**Frontend** (`src/app/dashboardportal/juteSQC/r-08-03/`): mobile-first entry — header (date/shift/category/quality/machine), then a dynamic weight+MR list (add-row up to 12) with live corrected preview and running Avg/StDev/CV; desktop date-driven summary grid. Route consts in `api.ts` (`SPREADER_SLIVER_WT_*`); `fetchWithCookie`. **Masters to link:** `spell_mst`, `machine_mst`, `item_mst` (raw jute); CATEGORY master TBD.

## 8. Open questions (NEEDS OWNER DECISION)
- **STD sliver weight (lb/100yds)** storage — process×quality. Recommend `machine_mst.std_sliver_wt` (option A). **NEEDS OWNER DECISION.**
- **"CATEGORY"** header field — which master/list does it draw from? (roll category? jute category?) No value in the cached snapshot. **NEEDS OWNER DECISION.**
- Cached snapshot had **empty reading cells** and **STD MR% = `#N/A`** — confirm the full input set from a populated day, and confirm StDev/CV are computed on the **corrected** series (defaulted from R-08-04).
- Confirm operator enters the **already-scaled lb/100yds** value (vs. raw 5-yd weight that the system multiplies by 20).
- Max readings = **12** (vs 10 elsewhere) — confirm it is variable 1–12.
- Whether a **CV% pass band** applies to spreader sliver (none seen on this tab).
- Phase-2: link to spreader production ("rolls/frames running") — not wired now.
