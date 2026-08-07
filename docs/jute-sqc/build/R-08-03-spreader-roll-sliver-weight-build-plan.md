# Build Plan — R-08-03 Spreader Roll Sliver Weight (2nd report of the Sliver/Roll-weight family)

> Source-verified delta on the shipped R-08-04 build. Same module/persona/pattern.
> Module: `juteSQC` · Portal (`get_tenant_db`, scoped by `co_id`/`branch_id`) · insert-only + compute-on-read.
> R-08-03 ships as a **second tab on the existing Spreader SQC page** next to R-08-04.

## What's the same as R-08-04 (REUSE — do not rebuild)
- **Masters & setup queries:** identical — spells (`get_spreader_roll_wt_spells_query`), spreader machines (`get_spreader_machines_query` from `src.juteProduction.query`), raw-jute qualities (`get_morrah_wt_jute_qualities_query`). Reuse them verbatim.
- **Standards:** the std-MR% satellite `jute_spreader_quality_attr` already exists (built with R-08-04). Reuse `get_spreader_quality_std_query()` for the per-quality std MR% lookup (fallback 16). **No new standards table, no new columns anywhere.**
- **Correction algebra:** `corrected_i = obs_i * (100 + std_mr) / (100 + mr_i)`; CV% = `stdev_corr / avg_corr` (corrected basis); sample stdev (n-1, guard n<=1 → 0).

## What's different from R-08-04
1. **Variable 1–12 readings** (not fixed 10). Validate `1 <= len <= 12`, parallel weight/MR arrays of equal length, each weight `> 0`, each MR% `>= 0`.
2. **No weight bands / buckets** (R-08-04's only extra). Drop all band logic — no `band_edges`, no `band_counts_*`, no `_bucket_counts`. (This also means none of the R-08-04 band type-mismatch issues exist here.)
3. **Units = lb/100yds**, sample length 5 yds — both are header constants; the operator enters the already-scaled lb/100yds value (no system ×20). Store `sample_length_yds` (default 5) and `weight_basis` ("LB/100YDS") as nullable header constants for the record.
4. **CATEGORY** header field — no master identified in the source. **YAGNI: store as nullable free-text `category VARCHAR(100)`**; FE = optional free-text input. (Flagged as an owner open item; do NOT invent a master.)
5. **No std-weight comparison column** — the report's outputs are Avg Obs / Avg Corr / Avg MR% / StDev / CV% only (the source tab prints no std-sliver-weight or CV-band column). So there is nothing to compare against beyond the computed stats. (STD sliver weight + CV band are deferred owner items — not built.)

## Apply these R-08-04 REVIEW LESSONS (do not repeat the bugs)
- **by-date endpoint MUST return `{"data": {"readings": [...]}}`** (object with `readings`), matching the FE hook/type — NOT a bare `{"data": [...]}` list.
- **by-id query MUST be tenant-scoped**: include `AND (:co_id IS NULL OR rw.co_id = :co_id)` and bind `co_id` from the endpoint.
- **ORM ↔ migration lockstep**: every column in the DDL exists on the ORM model and vice-versa.
- Add a **by-date envelope test** asserting the `{"data":{"readings":[...]}}` shape and JSON round-trip.

## 1. New storage — `jute_sqc_spreader_sliver_wt` (ONE new table; no satellite)
Morrah-shaped flat header + JSON readings (VARCHAR(500) + `json.dumps`/`json.loads`). Columns:
`spreader_sliver_wt_id` PK AI · `co_id` INT NOT NULL · `branch_id` INT NULL · `entry_date` DATE NOT NULL · `spell_id` INT NULL · `category` VARCHAR(100) NULL · `mc_id` INT NULL · `item_id` INT NULL · `sample_length_yds` DECIMAL(5,2) NULL · `weight_basis` VARCHAR(20) NULL · `observed_weights` VARCHAR(500) NOT NULL (JSON, 1–12) · `mr_pcts` VARCHAR(500) NOT NULL (JSON, parallel) · `std_mr_pct` DECIMAL(5,2) NULL (snapshot) · `calc_avg_obs` DECIMAL(10,3) · `calc_avg_corr` DECIMAL(10,3) · `calc_avg_mr` DECIMAL(5,2) · `calc_stdev` DECIMAL(10,4) (corrected, sample) · `calc_cv_pct` DECIMAL(7,4) (ratio) · `active` INT NOT NULL DEFAULT 1 · `updated_by` INT NULL · `updated_date_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP. Indexes: co_id, entry_date, (co_id,entry_date), mc_id, item_id. Rollback `DROP TABLE` comment. Migration file: `dbqueries/migrations/create_jute_sqc_spreader_sliver_wt.sql`.

## 2. Backend (mirror `spreader_roll_wt.py`)
- ORM `JuteSqcSpreaderSliverWt` in `src/models/jute.py` next to `JuteSqcSpreaderRollWt`.
- Queries in `src/juteSQC/query.py`: `get_spreader_sliver_wt_table_query`/`_count_query`, `get_spreader_sliver_wt_by_id_query` (co_id-scoped), `get_spreader_sliver_wt_by_date_query`, `get_spreader_sliver_wt_active_row_query`, `soft_delete_spreader_sliver_wt_query`. Reuse the spell/machine/quality/std builders.
- New file `src/juteSQC/spreader_sliver_wt.py`: `compute_spreader_sliver_stats(observed, mr, std_mr_pct) -> dict` (no bands) + endpoints `GET /get_spreader_sliver_wt_setup`, `POST /create_spreader_sliver_wt`, `GET /get_spreader_sliver_wt_table`, `GET /get_spreader_sliver_wt_by_id`, `GET /get_spreader_sliver_wt_by_date`, `DELETE /spreader_sliver_wt_delete/{id}`. Register router in `src/main.py` (prefix `/api/juteSQC`, tag `jute-sqc-spreader-sliver-weight`).
- Tests `src/test/test_jute_sqc_spreader_sliver_wt.py`: stats helper (verified single correction `20.32×116/129 = 18.27`; avg/stdev/CV identity on the corrected series; std-MR fallback 16; variable-length 3 and 12 readings), endpoint validation (len<1 or >12 → 400, setup 200, missing co_id/branch_id → 400, create-success, by-date envelope, delete-404).

## 3. Frontend — 2nd tab on the Spreader SQC page
- Route consts `SPREADER_SLIVER_WT_{SETUP,SAVE,BY_DATE,DELETE}` in `src/utils/api.ts` (next to the roll-wt block; `_DELETE` is a base path).
- Update `spreader/page.tsx` `TABS` to `["R-08-04 Roll Weight", "R-08-03 Sliver Weight"]`; render the sliver Form+Grid on the 2nd tab (reuse the same setup hook shape; the sliver setup returns the same spells/machines/qualities).
- Add to `spreader/types/sqcSpreaderTypes.ts`: `SpreaderSliverWtReadingRow`, `SpreaderSliverWtByDateResponse = { readings: [...] }`, `SpreaderSliverWtSavePayload`, and a Zod schema (1–12 readings, each weight > 0). band_counts: **omit entirely**.
- `spreader/hooks/useSqcSliverWtSetup.ts` + `useSqcSliverWtByDate.ts` (copy the roll-wt hooks; swap route + type).
- `spreader/_components/SliverWtForm.tsx` — responsive, **dynamic add/remove reading rows (1–12)** with a live corrected/avg/StDev/CV preview; optional CATEGORY free-text + spell/machine/quality pickers; POST `{co_id, branch_id, entry_date, spell_id, mc_id, item_id, category, observed_weights, mr_pcts}` (empty selects → null). Math in `spreader/utils/spreaderSliverCalc.ts` (no bands).
- `spreader/_components/SliverWtGrid.tsx` — date-driven summary (Avg Obs / Avg Corr / Avg MR% / StDev / CV%) + DataGrid + delete; theme tokens only; synthetic `getRowId`.

## 4. Owner open items (non-blocking; defaults taken)
1. **CATEGORY** field source — stored as free text now; confirm if it should be a master-backed dropdown.
2. **STD sliver weight (lb/100yds) + CV% band** — not computed now (source tab shows none); confirm if a per-(machine/quality) target should be added later (would extend `spreader_machine_attr` or the satellite, like R-08-04's band edges).
3. Confirm readings are operator-entered **already scaled to lb/100yds** (assumed; no system ×20).
4. Migrations target **dev3**; applied later (live DB unreachable from CI sandbox).
