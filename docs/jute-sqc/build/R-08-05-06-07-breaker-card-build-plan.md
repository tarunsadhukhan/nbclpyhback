# Build Plan — R-08-05/06/07 Breaker Card (Coarse Side SWT) — carding stage, 3rd report of the family

> Source-verified. Module `juteSQC` · Portal (`get_tenant_db`, co_id/branch_id scoped) · insert-only + compute-on-read.
> New stage = **Breaker Card**. First report of the carding/drawing sub-family that uses **line qualities** + the **(item_id, process) standards satellite**.

## Decisions locked for this build (owner defaults taken; reversible)
1. **Standards home = NEW `(item_id, process)`-keyed satellite `jute_draw_quality_std`** (the standards-storage doc's agreed approach; band follows quality, `process` key handles cross-stage variance). All std columns **nullable + code fallbacks**: std MR → 16; CV pass/fail only computed when a band is seeded (else `cv_within_band = NULL`). Reversible.
2. **Line qualities = `item_mst` under parent group `item_type_id = 5` ("Jute Cloth")** — NOT `item_type_id=2` (that is raw jute; the spec text is wrong — see investigation). Copy the `get_finishing_items_query` pattern (`src/juteProduction/finishing_query.py`).
3. **Breaker-card machines:** there is **no 'Breaker Card' machine_type** seeded. Mirror the spreader precedent: filter `machine_mst` via `machine_type_mst.machine_type_name = :breaker_type` with a new constant `BREAKER_CARD_MACHINE_TYPE_NAME = "Breaker Card"`, and **ship an idempotent seed migration** creating that machine type. Usability then needs the owner to tag breaker-card machines with the type in the machine master (one-time admin task — same as 'Spreader'). Flag this prerequisite.
4. **One multi-row report** (not three). `R-08-05/06/07` = one sheet, many (machine, spell, quality) rows. Add a nullable `card_side VARCHAR(10) DEFAULT 'COARSE'` for the future fine-side variant. `process = 'BREAKER'` constant for the std lookup.
5. **Migrations target dev3**; generated, applied later (live DB unreachable).

## 1. Connect map
| Input | Source | Detail |
|---|---|---|
| co_id / branch_id | existing — sidebar | every call |
| entry_date | new typed | one date per sheet |
| mc (per row) | existing master `machine_mst` (breaker card) | NEW query `get_breaker_card_machines_query()` — copy `get_spreader_machines_query`, swap the type constant to `BREAKER_CARD_MACHINE_TYPE_NAME`; branch via `dept_mst` |
| spell (per row) | existing master `spell_mst` | reuse `get_spreader_roll_wt_spells_query()` |
| quality (per row) | existing master `item_mst` line quality | NEW query `get_line_quality_items_query()` — item_type_id=5 walk (copy finishing pattern) |
| std_mr_pct, std_cv_low/high | derived — new satellite | `get_draw_quality_std_query()` by (item_id, process='BREAKER'); snapshot onto each saved row; std MR fallback 16 |
| wt1..wt4, mr1..mr4 (per row) | new typed | exactly 4 cut weights + 4 MR% |
| calc_* + cv_within_band | computed server-side, persisted | per row |

**Production linkage:** independent (masters + bench readings). Carding-production "frames running" link is Phase 2.

## 2. Formulas (verified against cached values — assert in tests)
Per row (avg-then-correct path matches the sheet exactly):
```
calc_wt      = mean(wt1..wt4)                              # Row1: (21.47+20.41+20.81+18.56)/4 = 20.32 ✓
calc_mr_pct  = mean(mr1..mr4)                              # Row1: (32+28+30+26)/4 = 29 ✓
calc_corr_wt = calc_wt * (100 + std_mr) / (100 + calc_mr_pct)   # Row1 HESSIAN std16: 20.32*116/129 = 18.26 ✓
                                                          # Row3 SACKING WEFT std20: 20.40*120/132.25 = 18.51 ✓
corrected_i  = wt_i * (100 + std_mr) / (100 + mr_i)        # the 4 corrected cuts
calc_sdev    = statistics.stdev(corrected_i)  (sample n-1, guard n<=1 -> 0)   # Row1: 0.795 ; Row3: 0.444
calc_cv_pct  = calc_sdev / calc_corr_wt  (ratio; render x100; guard corr>0)   # Row1: 0.0436 ; Row3: 0.0240
cv_within_band = (std_cv_high is not None) ? (calc_cv_pct*100 <= std_cv_high) : None   # high edge = upper tolerance
```
**Per-quality GRAND AVERAGE (recomputed at read, NOT stored)** over that date's rows for the quality:
```
OBS  = mean(calc_wt for the quality's rows)        # HESSIAN: (20.32+22.92)/2 = 21.62 ✓
MR%  = mean(calc_mr_pct ...)                        # HESSIAN: (29+31)/2 = 30 ✓
CORR = mean(calc_corr_wt ...)                       # HESSIAN: (18.26+20.28)/2 = 19.29 ✓
CV%  = stdev(ALL pooled corrected cuts for the quality) / mean(pooled corrected)   # HESSIAN: 0.05173 ✓ (pooled, not mean-of-row-CVs)
```
> The grand CV% needs the individual corrected cuts → keep the readings (JSON) so by_date can re-pool them.

## 3. New storage (3 migrations)
### 3a. Satellite `jute_draw_quality_std` (NEW, (item_id, process)-keyed)
`draw_quality_std_id` PK AI · `co_id` INT NOT NULL · `item_id` INT NOT NULL · `process` VARCHAR(30) NOT NULL · `std_mr_pct` DECIMAL(5,2) NULL · `std_cv_low` DECIMAL(5,2) NULL · `std_cv_high` DECIMAL(5,2) NULL · `std_weight` DECIMAL(10,3) NULL · `std_wt_tol` DECIMAL(10,3) NULL · `active` INT NOT NULL DEFAULT 1 · `updated_by` INT NULL · `updated_date_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP. Indexes: (item_id, process), co_id. Rollback comment. Serves the whole carding/drawing family (breaker, inter, drawhead, finisher).

### 3b. Entry table `jute_sqc_breaker_card_swt` (NEW)
Flat row-per-reading-set (one save inserts several rows). `breaker_card_swt_id` PK AI · `co_id` NOT NULL · `branch_id` NULL · `entry_date` DATE NOT NULL · `mc_id` NULL · `spell_id` NULL · `item_id` NULL · `card_side` VARCHAR(10) NULL DEFAULT 'COARSE' · `weights` VARCHAR(500) NOT NULL (JSON 4) · `mr_pcts` VARCHAR(500) NOT NULL (JSON 4) · `std_mr_pct` DECIMAL(5,2) NULL · `std_cv_low` DECIMAL(5,2) NULL · `std_cv_high` DECIMAL(5,2) NULL · `calc_wt` DECIMAL(10,3) · `calc_mr_pct` DECIMAL(5,2) · `calc_corr_wt` DECIMAL(10,3) · `calc_sdev` DECIMAL(10,4) · `calc_cv_pct` DECIMAL(7,4) · `cv_within_band` INT NULL · `active` INT NOT NULL DEFAULT 1 · `updated_by` INT NULL · `updated_date_time` TIMESTAMP. Indexes: co_id, entry_date, (co_id,entry_date), mc_id, item_id. Rollback comment.

### 3c. Seed `Breaker Card` machine type (NEW, idempotent)
`INSERT INTO machine_type_mst (machine_type_name, active) SELECT 'Breaker Card', 1 WHERE NOT EXISTS (SELECT 1 FROM machine_type_mst WHERE machine_type_name = 'Breaker Card');` (adjust columns to the real `machine_type_mst` schema — agent verifies via ORM/model). Rollback comment. **Prerequisite to flag:** owner tags breaker-card machines with this type in the machine master.

ORM: `JuteDrawQualityStd` + `JuteSqcBreakerCardSwt` in `src/models/jute.py` (lockstep with DDL).

## 4. Backend (mirror `spreader_roll_wt.py`, adapt for multi-row + grand average)
- Constant `BREAKER_CARD_MACHINE_TYPE_NAME = "Breaker Card"` and `BREAKER_PROCESS = "BREAKER"` (in `src/juteSQC/` constants or the module file).
- Queries in `src/juteSQC/query.py`: `get_breaker_card_machines_query()` (copy spreader machines, swap type), `get_line_quality_items_query()` (item_type_id=5), `get_draw_quality_std_query()` ((item_id, process)), `get_breaker_card_swt_by_date_query()`, `get_breaker_card_swt_table_query`/`_count`, `get_breaker_card_swt_by_id_query` (tenant-scoped), active-row + soft-delete. Reuse `get_spreader_roll_wt_spells_query`.
- `src/juteSQC/breaker_card_swt.py`: `compute_breaker_card_stats(weights, mr, std_mr, std_cv_low, std_cv_high) -> dict` (§2, exactly 4 readings) + `compute_grand_averages(rows) -> per-quality block`. Endpoints:
  - `GET /get_breaker_card_swt_setup` (co_id+branch_id; machines/spells/qualities-with-std; the day's rows if entry_date given)
  - `POST /create_breaker_card_swt` — body = **array of rows** (`rows: [...]`); per row validate exactly 4 (wt,mr), wt>0, mr>=0; look up std MR + CV band per (item_id, BREAKER); compute + persist each; return inserted ids.
  - `GET /get_breaker_card_swt_by_date` — `{"data": {"rows": [...], "grand_averages": [...]}}` (object envelope; grand block recomputed at read).
  - `GET /get_breaker_card_swt_table` (pagination), `GET /get_breaker_card_swt_by_id` (tenant-scoped), `DELETE /breaker_card_swt_delete/{id}` (soft-delete).
  - Register router in `src/main.py` (prefix `/api/juteSQC`, tag `jute-sqc-breaker-card`).
- Tests `src/test/test_jute_sqc_breaker_card.py`: stats vs Row1 (corr 18.26, sdev 0.795, cv 0.0436) and Row3 (corr 18.51, cv 0.0240); grand-average HESSIAN (OBS 21.62, CORR 19.29, pooled CV 0.05173); std MR fallback 16; cv_within_band None when no band, 1/0 when seeded; multi-row create; len!=4 → 400; by-date envelope `{"data":{"rows":...,"grand_averages":...}}`; setup/missing-param/delete-404.

## 5. Frontend — new stage page `juteSQC/breakerCard`
- Route consts `BREAKER_CARD_SWT_{SETUP,SAVE,BY_DATE,DELETE}` in `api.ts`.
- `juteSQC/breakerCard/page.tsx` — copy the spreader page skeleton (sidebar co_id/branch_id guard cascade), single stage (tab "R-08-05/06/07 Breaker Card").
- Types (one file, Zod), hooks (setup + by-date), calc utils (no bands buckets — corrected/avg/CV + within-band flag).
- Entry `_components/BreakerCardForm.tsx` — **multi-row grid**: add rows (Mc/Spell/Quality + 4 wt/MR), per-row live Corr Wt + CV% with **band pass/fail color** (theme tokens; green within high edge, error when over), submit the whole array.
- Summary `_components/BreakerCardGrid.tsx` — date-driven rows table + the **per-quality grand-average block**; delete per row.
- Landing tile "Breaker Card SQC".

## 6. Apply the R-08-04/03 review lessons
by-date returns an **object** envelope (here `{rows, grand_averages}`); by-id **tenant-scoped**; **ORM↔migration lockstep**; **by-date envelope test**; soft-delete active=0 + updated_by; reused builders imported not duplicated; `{"data":...}` wrapping; None for SQL NULLs; type-cast binds; no hardcoded colors / `any` on FE.

## 7. Owner open items (non-blocking; defaults taken)
1. **Seed + tag breaker-card machines** with the new 'Breaker Card' machine type (migration ships the type; tagging is an admin task).
2. **Seed `jute_draw_quality_std`** rows (std MR%, std_cv_low/high per line quality at process='BREAKER'); until then std MR falls back to 16 and CV pass/fail is not shown.
3. **CV band semantics** — assumed pass = `CV%×100 ≤ std_cv_high` (high edge = upper tolerance; low edge informational). Confirm.
4. **Fine side** — `card_side` defaults 'COARSE'; confirm if a fine-side variant shares this table.
5. Migrations target dev3.
