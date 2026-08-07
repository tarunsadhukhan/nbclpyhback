# R-08-15 — Yarn QR% & CV% (I.S.O.)
**Stage:** spinning  **Status:** BUILT
**Source tab:** `R-08-15 YARN QR% & CV%` (master "Daily Summary Date Select")   **DSR workbook:** `1CdOZfalDJbX-OlbSdT1aFs70Y8dd0K1BI3Im3BApI-4` / `NEWDSR!A3:L50` (not shared)

> AS-BUILT spec. The inputs/outputs/data-model/endpoints/pages below are the ACTUAL ones in
> `vowerp3be/src/juteSQC/` and `vowerp3ui/.../juteSQC/spinning/`, cross-checked against the worked
> design spec `…/spinning/types/R-0-15_spec_sheet.md`. This is **Tab 4** ("R-08-15 Yarn QR & CV %")
> of the existing Spinning SQC tabbed page.

## 1. Purpose

Per-yarn lab QC of yarn **strength quality (QR%)** and its **uniformity (CV%)**. For a chosen date,
the inspector picks a yarn item that already has R-08-16 count readings and records a 30-reading
bundle/lea-strength (b/s) test on one spinning frame; the system derives Avg B/S, SD, QR% and CV%
and compares against the yarn's standard count. It quantifies how strong the spun yarn is relative
to its nominal count and how consistent that strength is across spindles.

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| Date | date | n/a | Yes | **Header** — `entry_date`; defaults to today (`todayISO()`). |
| Yarn item (quality) | dropdown | `item_mst` (yarn, `item_type_id=4`) via `yarn_obs` | Yes | **Per-group key** — `item_id`. Selectable only if it has R-08-16 count rows that date. Source: `_fetch_yarn_obs` (R-08-16 `jute_sqc_spinning_count`). |
| Machine / SPG frame | dropdown | `machine_mst` (spinning-type) → `mc_id` | Yes (FE) | **Per-group key.** Same spinning-machine dropdown as R-08-16. Nullable in DB, required in FE. |
| Spindle no (×6) | number | operator-entered | Yes | **Per-reading group** — actual spindle position; 6 distinct spindles per group. Stored in `..._dtl.spindle_no`. |
| Reading / b/s (×5 per spindle) | number | operator-entered | per reading | **Per-reading** — bundle/lea strength (`reading_val`); 5 slots per spindle = 30 readings. Blanks → NULL, ignored by stats. |
| Observed Count (lb) | display-only | R-08-16 `jute_sqc_spinning_count.observed_count` (AVG per item) | derived | **NOT entered here** — read from R-08-16's saved values (`_qr_cv_obs_map`). |
| MR% obtained | display-only | R-08-16 `jute_sqc_spinning_count.mr_pct` (AVG per item) | derived | **NOT entered here** — read from R-08-16's saved values. |

Header = date. Per-group keys = yarn item + machine. Per-reading = spindle no + b/s readings.

## 3. Standards & constants used

| Standard / value | Example in sheet | Where it lives in VOW (as-built / proposed) |
|------------------|------------------|---------------------------------------------|
| Std/report count for the yarn ("Report For The Count") | `8.5 LB HSWT`, `13.2 LB SWT`, `16.2 LBS SKWP` | The yarn quality's nominal count — **`jute_yarn_mst.std_count`** keyed by `item_id` (satellite of `item_mst`). Fetched by `_fetch_qualities` (returned as `std_count`) but **not currently used in the QR%/CV% math** (QR% uses the *observed* count, not std). |
| Std MR% (per quality) | implied (Hessian≈16, Sacking≈20) | **`jute_yarn_mst.std_mr_pct`** keyed by `item_id` (`get_quality_std_mr_query`). Used in R-08-16 to correct count; R-08-15 only reuses the AVG observed count + AVG MR%, not std MR directly. |
| QR% acceptance band | none stored in this tab | **Not configured** — no per-quality QR% pass/fail band in the build. |
| CV% acceptance band | none stored in this tab | **Not configured** — no CV% band master. |

**Standards-storage note (briefing 9a):** the per-yarn standards (`std_count`, `std_mr_pct`) already
live in the **satellite table `jute_yarn_mst` keyed by `item_id`** — exactly the prescribed pattern
(do not add columns to `item_mst`). No new satellite is needed for R-08-15. If a QR%/CV% **acceptance
band** is later wanted, it would extend that same `jute_yarn_mst` satellite (e.g. `std_qr_pct`,
`cv_low`/`cv_high`) — case-by-case, **NEEDS OWNER DECISION**.

## 4. Calculations (formulas)

All stats are computed **server-side at read** in `_qr_cv_stats()` (`spinning_sqc.py`), never stored.
`vals` = the non-null `reading_val`s of the group (the 30 b/s readings).

| Output | Formula (as-built) | Notes |
|--------|--------------------|-------|
| `avg_bs` | `sum(vals) / n` | mean of all readings in the group |
| `max` | `max(vals)` | |
| `min` | `min(vals)` | |
| `std_dev` | `statistics.stdev(vals)` (n≥2) | **SAMPLE (n-1)** standard deviation |
| `observed_count` | `AVG(observed_count)` of R-08-16 rows for `(co, date, item_id)` | read from saved `jute_sqc_spinning_count` (D6); NOT recomputed |
| `mr_pct` | `AVG(mr_pct)` of R-08-16 rows for `(co, date, item_id)` | display context only |
| `qr_pct` | `(avg_bs / observed_count) * 100` | guarded: null when `observed_count` is 0/null |
| `cv_pct` | `(std_dev / qr_pct) * 100` | **lab-specific CV% = SD ÷ QR% × 100** (NOT SD÷mean). Guarded: null when `qr_pct` is 0/null |

All rounded to 2 dp. `qr_pct`/`cv_pct` are stored in the sheet as fractions (`0.79`, `0.1812`); the
build multiplies by 100 (so `qr_pct ≈ 79.0`, `cv_pct ≈ 18.12`) per the resolved D7 decision.

⚠️ **Confirm:** the sheet's **"QR % at Min Reading"** (`min_reading / observed_count × 100`, e.g.
`5/9.03 = 55.37`) is **NOT computed in the build** — see Open Questions.

## 5. Worked example (real data)

Cached row 1 — `HESSIAN WARP`, machine no 2, date 2026-01-05, OBS Count `9.03`, MR% `18`.
30 b/s readings across 6 spindles (85–90): `7.4, 6.2, 7.0, 5.4, 6.8 | 8.4, 9.2, 7.0, 7.4, 6.2 |
6.4, 9.0, 7.2, 5.4, 6.2 | 7.4, 8.6, 9.0, 5.6, 6.2 | 8.4, 8.0, 5.8, 7.4, 6.0 | 10.0, 5.0, 7.2, 6.0, 8.2`.

- `max` = 10.0 ✓ (sheet 10)
- `min` = 5.0 ✓ (sheet 5)
- `avg_bs` = 7.1333 → 7.13 ✓ (sheet 7.133)
- `std_dev` (sample) = 1.2922 → 1.29 ✓ (sheet 1.2922)
- `qr_pct` = (7.1333 / 9.03) × 100 = 79.00 (sheet fraction 0.7899 → ×100) ✓
- `cv_pct` = (1.2922 / 79.00) × 100 = 1.6357... ⚠️ **mismatch with sheet.** The sheet computes
  `cv_pct = 0.1812` using the **fraction QR% (0.7899)**: `1.2922 / 0.7899 / 100 = 0.01636`? No —
  the sheet value `0.1812` = `SD / (avg_bs) × something`. In fact `1.2922 / 7.1333 = 0.18115` =
  **SD ÷ mean** (textbook CV%). So the **sheet's CV% is actually SD÷mean**, while the **build uses
  SD÷QR%×100**. This is a known divergence — flagged below.

## 6. As-built data model

Header + detail pair (a group = one test of 30 readings). Defined in
`src/juteSQC/models.py`; created by `dbqueries/migrations/create_jute_sqc_spinning_qr_cv.sql`.
observed_count / mr_pct are **NOT stored** (read from R-08-16 at read time).

### `jute_sqc_spinning_qr_cv` (header) — class `JuteSqcSpinningQrCv`

| Column | Type | Notes |
|--------|------|-------|
| `spinning_sqc_qr_cv_id` | INT PK AI | group id |
| `co_id` | INT NOT NULL, idx | tenant scope |
| `branch_id` | INT NULL | optional scope (`:x IS NULL OR …` idiom) |
| `entry_date` | DATE NOT NULL, idx | header date |
| `mc_id` | INT NULL | machine → `machine_mst.machine_id` |
| `item_id` | INT NOT NULL, idx | yarn quality → `item_mst.item_id` (also satellite `jute_yarn_mst`) |
| `active` | INT NOT NULL default 1 | soft-delete |
| `updated_by` | INT NULL | audit |
| `updated_date_time` | TIMESTAMP default CURRENT_TIMESTAMP | audit |

### `jute_sqc_spinning_qr_cv_dtl` (detail) — class `JuteSqcSpinningQrCvDtl`

| Column | Type | Notes |
|--------|------|-------|
| `spinning_sqc_qr_cv_dtl_id` | INT PK AI | |
| `spinning_sqc_qr_cv_id` | INT NOT NULL, idx | FK → header |
| `spindle_no` | INT NOT NULL | spindle position (6 per group) |
| `reading_no` | INT NOT NULL | 1..5 within a spindle |
| `reading_val` | DECIMAL(10,3) NULL | the b/s reading |

No `active` on detail — visibility follows the header (soft-delete the header only). Save is
**insert-only** (duplicates allowed); a group is deleted as a unit.

## 7. As-built endpoints & pages

**Router:** `src/juteSQC/spinning_sqc.py`, prefix `/api/juteSQC` (registered in `src/main.py:203`).
Queries in `src/juteSQC/spinning_sqc_query.py`.

| Method / path | Function | Returns |
|---------------|----------|---------|
| `GET /api/juteSQC/sqc_qr_cv_setup` | `sqc_qr_cv_setup` | `{data:{machines, yarn_items, yarn_obs, groups}}` — dropdowns + per-yarn R-08-16 AVG observed_count/mr_pct + existing groups with stats |
| `POST /api/juteSQC/sqc_qr_cv_save` | `sqc_qr_cv_save` | insert-only: 1 header + 30 detail rows per entry → `{data:{saved, ids}}` |
| `GET /api/juteSQC/sqc_qr_cv_by_date` | `sqc_qr_cv_by_date` | `{data:{groups:[…readings + stats…]}}` (`_qr_cv_groups`) |
| `DELETE /api/juteSQC/sqc_qr_cv_delete/{qr_cv_id}` | `sqc_qr_cv_delete` | soft-delete header (`active=0`), 404 guard |

Query builders: `get_sqc_count_obs_mr_avg_query`, `get_sqc_qr_cv_by_date_query`,
`get_sqc_qr_cv_dtl_query` (expanding `IN :ids`), `insert_sqc_qr_cv_header_query`,
`insert_sqc_qr_cv_dtl_query`, `get_sqc_qr_cv_active_row_query`, `soft_delete_sqc_qr_cv_query`.

**Frontend (Tab 4 of the Spinning SQC page):**
- Page: `vowerp3ui/src/app/dashboardportal/juteSQC/spinning/page.tsx` — `TABS[3] = "R-08-15 Yarn QR & CV %"`, rendered in the `tab === 3` block.
- Components: `_components/YarnQrCvForm.tsx` (entry; mobile-responsive: yarn Autocomplete over `yarn_obs`, machine, 6 spindles × 5 readings, live preview), `_components/YarnQrCvGrid.tsx` (summary DataGrid + delete).
- Hooks: `hooks/useSqcQrCvSetup.ts`, `hooks/useSqcQrCvByDate.ts`.
- Types: `types/sqcSpinningTypes.ts` (`SqcQrCvSetup`, `SqcQrCvGroup`, `SqcQrCvStats`, `SqcYarnObs`, …).
- Route consts (`src/utils/api.ts`, lines 829–833): `SPINNING_SQC_QR_CV_SETUP/SAVE/BY_DATE/DELETE`.
- All calls via `fetchWithCookie`.

**Masters linked:** `machine_mst` (spinning frame, `mc_id`), `item_mst` (yarn item), satellite
`jute_yarn_mst` (`std_count`, `std_mr_pct`). Observed count + MR% are pulled from the R-08-16
transaction table `jute_sqc_spinning_count` (intra-module link, already wired).

## 8. Open questions (NEEDS OWNER DECISION)

- **CV% definition divergence (highest priority):** the cached sheet's CV% (e.g. `0.1812` for row 1)
  is **SD ÷ mean** (= `1.2922/7.1333 = 0.18115`), but the build computes **CV% = SD ÷ QR% × 100**.
  These give different numbers. Confirm which is correct; if the sheet wins, change `_qr_cv_stats`
  to `cv_pct = std_dev/avg_bs*100`.
- **"QR % at Min Reading"** (sheet row, e.g. `55.37` = `min/observed_count×100`) is **not computed
  or displayed** in the build. Add it if the lab still needs it.
- **Std count / std MR% unused in math:** `std_count` is fetched but QR% uses *observed* count, not
  the standard. Confirm QR% should stay observed-based (sheet uses OBS Count, so likely yes).
- **No QR%/CV% acceptance band** is stored or evaluated — there is no pass/fail flag. Decide whether
  bands per quality should extend `jute_yarn_mst`.
- **Fixed 6×5 geometry** is hard-coded in the FE; the header/detail model supports any count. Confirm
  spindle/reading counts never vary.
- **Scaling ambiguity:** build returns QR%/CV% ×100 (true %), sheet stores fractions. Confirm the
  displayed convention with the owner (cosmetic, but affects band thresholds).
