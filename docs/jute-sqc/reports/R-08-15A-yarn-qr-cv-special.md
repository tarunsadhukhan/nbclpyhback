# R-08-15A — Yarn QR% & CV% — Special Purpose (3rd Drawing + Spinning Frame)
**Stage:** spinning (special — sliver+spun)  **Status:** NOT BUILT (planned variant of R-08-15)
**Source tab:** `R-08-15A YARN QR% & CV%` (master "Daily Summary Date Select")   **DSR workbook:** `13nq5EsttVmM9hy6vqgGFZqS_ff-XiQBS4lONH9F5_K8` / `DSR15A!A3:L28` (not shared)

> AS-BUILT status check: **R-08-15A is NOT implemented.** There is no `..._15a` table, endpoint,
> tab, or component anywhere in `vowerp3be/src/juteSQC/` or `vowerp3ui/.../juteSQC/spinning/`. The
> master tab dump (`R15A.txt`) is an **empty template** — only header labels, no real example row,
> all stat cells `0`/blank. This spec documents what the sheet needs and how it differs from the
> built R-08-15, so the variant can be added as a 5th tab. Everything below the "what exists" line
> is a **proposal**, not as-built.

## What exists vs what the sheet needs

| | R-08-15 (BUILT) | R-08-15A (this report) |
|---|---|---|
| Status | BUILT (Tab 4) | **NOT BUILT** |
| Machine keys | 1 machine (spinning frame, `mc_id`) | **2 machines:** `3RD DRAWING MACHINE NO` **and** `SPINNING FRAME NO` |
| Readings per group | 6 spindles × 5 = 30 (`spindle_no` + `reading_no`) | **flat 12 readings** (`READING 1..12`), no spindle grouping |
| Obs Count / MR% | AVG from R-08-16 saved values | entered/sourced per row (`OBS COUNT(LB)`, `MR%`) — sourcing TBD |
| Stats | max/min/SD/avg_bs/QR%/CV% (+ "QR% at min" in sheet, not in build) | same stat block (max/min/SD/avg_bs/QR%/CV%/QR% at min) |

## 1. Purpose

Same QC intent as R-08-15 (yarn strength QR% + uniformity CV%) but **"special purpose"**: the test
is keyed to **both** the 3rd-drawing machine that fed the spinning frame **and** the spinning frame,
to trace a strength issue back across the draw-spin pair. Readings are a flat 12-value set per group
(no 6×5 spindle structure).

## 2. Inputs (the data-entry fields) — PROPOSED (from sheet header labels)

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| Date | date | n/a | Yes | **Header** — `entry_date`. |
| 3rd Drawing machine no | dropdown | `machine_mst` (drawing-type) → `drawing_mc_id` | Yes | **NEW vs R-08-15** — second machine key. |
| Spinning frame no | dropdown | `machine_mst` (spinning-type) → `mc_id` | Yes | as R-08-15's machine. |
| Quality (yarn item) | dropdown | `item_mst` (yarn, `item_type_id=4`) | Yes | **Per-group key** — `item_id`. |
| Obs Count (lb) | number / derived | TBD (R-08-16 AVG, like R-08-15, OR entered) | Yes | sheet column `OBS COUNT(LB)` — sourcing is an open question. |
| MR% | number / derived | TBD | Yes | sheet column `MR%`. |
| Reading 1..12 | number | operator-entered | per reading | **flat 12 b/s readings** (no spindle no). |

## 3. Standards & constants used

Same as R-08-15: the yarn quality's `std_count` / `std_mr_pct` live in the **satellite
`jute_yarn_mst` keyed by `item_id`** (briefing 9a pattern — reuse, no new satellite). No QR%/CV%
acceptance band stored. The only structural addition is the **drawing-machine key**, which is a
`machine_mst` link, not a standard.

## 4. Calculations (formulas) — PROPOSED, identical to R-08-15

Over the 12 non-null readings:
- `avg_bs = mean(readings)`
- `max`, `min`
- `std_dev = sample (n-1) stdev`
- `qr_pct = (avg_bs / observed_count) × 100`
- `cv_pct = (std_dev / qr_pct) × 100` — but see the **same CV% divergence flagged for R-08-15**
  (sheet may intend SD ÷ mean). The 15A template has all stat cells zeroed (no real data), so the
  exact form **cannot be confirmed from the dump** — inherit R-08-15's resolution.
- `qr_pct_at_min = (min / observed_count) × 100` — present as a sheet row; not in any build.

⚠️ **Confirm:** every formula here is derived from R-08-15 by analogy; the 15A tab carries no cached
numbers to verify against.

## 5. Worked example (real data)

**None available.** The R15A cached tab is an empty template (labels only; stats `0`/blank, no DSR
data imported). No end-to-end example can be reproduced.

## 6. As-built data model

**None exists.** Proposed (mirror R-08-15 header+detail, add drawing machine, flatten readings):

### `jute_sqc_spinning_qr_cv_special` (header) — PROPOSED

| Column | Type | Notes |
|--------|------|-------|
| `spinning_sqc_qr_cv_special_id` | INT PK AI | group id |
| `co_id` / `branch_id` | INT / INT NULL | tenant scope (as R-08-15) |
| `entry_date` | DATE NOT NULL, idx | header date |
| `drawing_mc_id` | INT NULL | **3rd-drawing machine** → `machine_mst.machine_id` (NEW) |
| `mc_id` | INT NULL | spinning frame → `machine_mst.machine_id` |
| `item_id` | INT NOT NULL, idx | yarn quality → `item_mst.item_id` |
| `observed_count` / `mr_pct` | DECIMAL NULL | if entered (vs derived) — decision pending |
| `active` / `updated_by` / `updated_date_time` | INT / INT / TIMESTAMP | soft-delete + audit |

### `jute_sqc_spinning_qr_cv_special_dtl` (detail) — PROPOSED

| Column | Type | Notes |
|--------|------|-------|
| `…_dtl_id` | INT PK AI | |
| `…_special_id` | INT NOT NULL, idx | FK → header |
| `reading_no` | INT NOT NULL | 1..12 (no spindle grouping) |
| `reading_val` | DECIMAL(10,3) NULL | b/s reading |

(Alternatively, reuse the existing `jute_sqc_spinning_qr_cv` / `_dtl` tables with a
`report_variant` discriminator + an extra `drawing_mc_id` column — owner's call.)

## 7. As-built endpoints & pages

**None.** Proposed (mirror the R-08-15 set, new suffix), prefix `/api/juteSQC`, registered in the
same `spinning_sqc.py` router:
- `GET /sqc_qr_cv_special_setup`, `POST /sqc_qr_cv_special_save`, `GET /sqc_qr_cv_special_by_date`,
  `DELETE /sqc_qr_cv_special_delete/{id}`.
- FE: a **5th tab** on `juteSQC/spinning/page.tsx` ("R-08-15A …"), `_components/YarnQrCvSpecialForm.tsx`
  + `…Grid.tsx`, hooks `useSqcQrCvSpecialSetup/ByDate`, route consts `SPINNING_SQC_QR_CV_SPECIAL_*`.
- **Masters to link:** `machine_mst` twice (drawing + spinning), `item_mst` (yarn), satellite
  `jute_yarn_mst`. Whether Obs Count/MR% pull from R-08-16 (as R-08-15) is the key open question.

## 8. Open questions (NEEDS OWNER DECISION)

- **Build it at all?** R-08-15A is unimplemented; confirm it is in scope and whether it should be a
  5th tab on the Spinning SQC page or folded into R-08-15 with a variant flag.
- **Reading geometry:** 15A is **flat 12 readings** (no spindle no) vs 15's 6×5=30. Confirm 12 is
  fixed; decide whether to reuse the `_dtl` table (ignore `spindle_no`) or a new flat detail.
- **Drawing machine key:** confirm `3RD DRAWING MACHINE NO` maps to `machine_mst` (drawing-type) and
  whether it's required for traceability or optional.
- **Obs Count / MR% sourcing:** entered manually on this tab, or AVG'd from R-08-16 like R-08-15?
  The sheet shows them as columns (suggesting entry), but R-08-15 reads them from R-08-16.
- **CV% definition + "QR% at Min Reading":** inherit whatever is resolved for R-08-15 (the 15A
  template has no data to confirm independently).
- **No standards band** (QR%/CV% pass/fail) is defined — same as R-08-15.
