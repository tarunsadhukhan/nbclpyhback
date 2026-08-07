# Weaving Production — Backend Design (proposed)

Last verified: 2026-06-24 (jugar model REVISED — `close_jugar` is the operator input, `open_jugar` =
last-available close for the loom+quality (skips empty spells), `jugar` derived `X=jc−oj+cj; jugar=X−jc
if X>jc else X; max(0,·)`, `production_yds = (cuts + jugar/jc)·FL`; see Formulas. open/close/jugar cols
→ DECIMAL(10,3). 2026-06-23: open questions resolved: loom machine type 'Loom' id 7, quality-only target
map + target speed+eff, composite _dtl, spinning-style Loom→Quality map + beam-change tab, EB via
attendance view, recompute cascade. Earlier: reconciled vs Sacking S14 + Hessian loom calculators: core engine MATCH,
Q13 kg-constant RESOLVED to 28.35/1000, warp-prep→beaming cross-ref; + code3i + vow-ui-1.2 cross-walk:
std_ozs_yds/less_production/ticket_no fields, std_prod_kg, Loom-Hours page, reports. Initial 2026-06-22.)

> **Canonical spec:** `../vowerp3ui/docs/claude/modules/jute-production/weaving/SPEC.md` (cross-repo,
> full design incl. FE). This file is the **backend-authoritative** extract: tables, ORM, routers,
> services, formulas. Keep in sync with the canonical spec.
>
> Weaving is the jute-production stage **after Beaming** (spreader → drawing → spinning → winding →
> beaming → **weaving**). It clones the **beaming** backend module (`src/juteProduction/beaming_*.py`,
> `services/beaming_*.py`) and the `spng_target_map`/`beaming_target_map` save pattern. Persona:
> **Portal** (`get_tenant_db` + `get_current_user_with_refresh`, `{"data": …}`, soft delete
> `active=0`, **no approval workflow**, trigger-based audit).

## Tables (tenant DB) — `dbqueries/migrations/create_weaving_tables.sql`

1. **`jute_prod_weaving_quality`** (quality master, flat) — `weaving_quality_id` PK, `co_id`,
   `branch_id`, `item_id` (woven cloth, `item_grp_mst.item_type_id=5`), `weaving_quality_code`,
   `weaving_quality_name`, `ends`, `finished_length` DEC(12,3), `ozs_yds` DEC(10,4) (ACTUAL basis
   weight, drives `production_kg`; legacy `q_ozs_yds`), `std_ozs_yds` DEC(10,4) (STANDARD basis
   weight, drives `std_prod_kg`; distinct from `ozs_yds`; legacy `std_ozs_yds`),
   `no_of_jugar_per_cut` DEC(10,3) **(mandatory — production divisor)**, `width`, `ports`, `shots`,
   `jbo_rbo` VARCHAR(10) (single/double-loom indicator), `reed_space` DEC(10,3), `reed_porter` DEC(10,3)
   (ends-in-beam input; clarify vs `ports`, SPEC Q16), `shrinkage_pct` DEC(6,3) (ends-in-beam; may be
   beaming-owned, SPEC Q14), `tpi`, `yarn_count`,
   `mc_teeth`, `active`, `updated_by`, `updated_date_time`. (Clone `JuteProdBmQuality`.)
   **1b. `jute_prod_weaving_quality_dtl`** (Q6 — composite qualities, mirror `jute_prod_bm_quality_dtl`):
   header `weaving_quality_id` FK + per-warp-component rows. (Clone `JuteProdBmQualityDtl`.)
2. **`jute_prod_weaving_target_map`** — **same shape as `jute_prod_beaming_target_map`** (PK
   `weaving_target_map_id`): `co_id`, `branch_id`, `effective_date`, `ref_id` (**`weaving_quality_id`
   qid only** — Q5 quality-only, no `mcid`), `id_type` VARCHAR(8) (`'qid'`), `value_role` VARCHAR(10),
   `param` VARCHAR(20), `value` DEC(12,4), `active`, `updated_by`, `updated_date_time`. Branch-agnostic
   LAST-DATE resolve.
   **2b. `jute_prod_weaving_quality_map`** (§6.6 — spinning-style Loom→Quality map; clone
   `daily_doff_frames_winding` S-rows): `weaving_quality_map_id` PK, `co_id`, `branch_id`, `tran_date`,
   `spell_id`, `machine_id` (loom), `weaving_quality_id`, `active`, audit. **One active row per
   `(tran_date, spell_id, machine_id)`** (upsert). Production inherits quality from this map.
   **2c. `jute_prod_weaving_beam_map`** (§6.7 — beam-change tab): `weaving_beam_map_id` PK, `co_id`,
   `branch_id`, `tran_date`, `spell_id`, `machine_id`, `beam_no` VARCHAR(50), `active`, audit.
3. **`jute_prod_weaving_daily`** (production **INPUTS ONLY**, per loom+quality+spell) — grain
   `(co_id, tran_date, spell_id, machine_id, weaving_quality_id, active=1)`. **STORAGE MODEL = FREEZE
   NOTHING + VIEW (2026-06-24).** The table stores ONLY identity + operator inputs:
   `weaving_daily_id` PK, `co_id`, `branch_id`, `tran_date`, `spell_id`, `machine_id`,
   `weaving_quality_id` (**inherited from quality-map §6.6**), `eb_id` (**via attendance view**, Q7),
   `beam_no` (**from beam-map §6.7**, Q7), `cuts` INT, `close_jugar` DEC(10,3) (operator closing
   reading; 0 ≤ cj ≤ jc), `less_production` DEC(12,3), `active`, `updated_by`, `updated_date_time`.
   **DROPPED from the table** (all reproducible — recomputed by the view): `open_jugar`, `jugar`,
   `finished_length`, `ozs_yds`, `std_ozs_yds`, `no_of_jugar_per_cut`, `std_speed`, `act_speed`,
   `std_picks`, `act_picks`, `std_eff`, `target_eff`, `working_hours`, `production_yds`, `production_kg`,
   `production_mt`, `std_prod_yds`, `target_prod_yds`, `efficiency`, `std_prod_kg`, `target_kg`,
   `actual_eff`, `aports`.

   **3a. `vw_weaving_daily`** (view — computes EVERYTHING on read). JOINs `jute_prod_weaving_quality`
   (FL/ozs_yds/std_ozs_yds/no_of_jugar_per_cut), as-of-resolves std/act speed+picks+eff from
   `jute_prod_weaving_target_map` (LAST-DATE, branch-agnostic; `act_picks` from `vw_weaving_pick_act`),
   nets `spell_mst.working_hours` − Σ stoppage, and computes `open_jugar` via a window LAG over the
   existing active rows:
   ```sql
   open_jugar = COALESCE(LAG(close_jugar) OVER (
       PARTITION BY co_id, machine_id, weaving_quality_id
       ORDER BY tran_date, spell_rank), 0)   -- spell_rank A1=1,B1=2,A2=3,B2=4,C=5
   ```
   The LAG over **existing rows** inherently SKIPS empty spells (B1 with no row ⇒ A2 opens from A1's
   close) AND auto-propagates downstream / across the day boundary — so there is **no Python recompute
   cascade and no compute-on-save**. From there the view derives `jugar`, `production_yds/kg/mt`,
   `std_prod_yds`, `target_prod_yds`, `efficiency`, `std_prod_kg`, `target_kg`. **Nothing is frozen** —
   reads always reflect current masters + as-of standards. Requires MySQL 8.0+ (dev3 = 8.0.42, verified
   2026-06-24); below 8.0 substitute a correlated-subquery `open_jugar`.

ORM: `src/juteProduction/weaving_models.py` — `JuteProdWeavingQuality`, `JuteProdWeavingQualityDtl`,
`JuteProdWeavingTargetMap`, `JuteProdWeavingDaily` (**slim to inputs-only**),
`JuteProdWeavingQualityMap`, `JuteProdWeavingBeamMap` (legacy `Column(...)` + shared `Base`, matching
beaming).

## Routers (register in `src/main.py` after beaming `:216`)

| File | Prefix | Endpoints |
|------|--------|-----------|
| `weaving_masters.py` | `/api/weavingMasters` | `weaving_quality_setup` (GET), `weaving_quality_list` (GET), `weaving_quality_create` (POST), `weaving_quality_edit/{id}` (PUT), `weaving_quality_delete/{id}` (DELETE) |
| `weaving_target_map.py` | `/api/weavingTargetMap` | `target_map_setup`, `target_map_grid`, `target_map_bulk_save`, `target_map_list`, `target_map_create`, `target_map_edit/{id}`, `target_map_delete/{id}` (clone beaming; `grid_params_for` below) |
| `weaving_entry.py` | `/api/weavingProd` | `entry_create_setup`, `entries_by_date`, `machine_standards`, `entry_create`, `entry_edit/{id}`, `entry_delete/{id}`, `planning_grid`, `planning_grid_save` (**persist INPUTS only — no compute-on-save, no cascade**; reads SELECT from `vw_weaving_daily`); **`quality_map_get`/`quality_map_save`/`quality_map_mapped`** (§6.6 Loom→Quality, clone spinning `frame_map_*`); **`beam_map_get`/`beam_map_save`** (§6.7) |

`grid_params_for(id_type, value_role)` (the applicable-params single source of truth — no param table):
```
qid  standard -> ("speed","picks","eff")     qid  target -> ("speed","eff")     qid  actual -> ("speed","picks")  # SQC
# mcid (loom-linked) DROPPED — Q5 quality-only (target = speed + eff, Q5b).
```
**Quality is mapped, not selected inline** (spinning-style): `entries_by_date`/`planning_grid` inherit
`weaving_quality_id` via `COALESCE(daily.weaving_quality_id, quality_map.weaving_quality_id)`; planning
driver rows are sourced from the active `jute_prod_weaving_quality_map` rows (clone
`get_spinning_plan_driver_query`). `eb_id` resolved via attendance **view**; `beam_no` from the beam map.

## Services (FREEZE-NOTHING — most compute moved INTO the view)

- `services/weaving_standards.py::resolve_quality_standards(db, co_id, weaving_quality_id, on_date)`
  — LAST-DATE resolve qid std/target/actual `speed`/`picks`/`eff` (**quality-only, no mcid** — Q5);
  `act_picks` from `vw_weaving_pick_act`. **Retained** for `machine_standards` (FE prefill) parity; the
  daily reads no longer call it (the view resolves standards itself).
- `services/weaving_rules.py` — **`resolve_open_jugar`, `close_jugar()`, `recompute_cascade`, and the
  `compute_weaving_daily` save-path are DELETED.** The view's `open_jugar` LAG (over existing rows)
  subsumes the cascade + last-available resolver entirely. Keep ONLY a thin pure formula module
  (`effective_jugar(jc, oj, cj)` + `production_yds`) used for **FE parity + unit tests** — it is NOT on
  any save path. Math (REVISED 2026-06-30): `total_jugar = cuts·jc + cj − oj − adj` (adj=less_production,
  no wrap/clamp — cuts·jc keeps it ≥0); `production_yds = total_jugar·FL/jc` (guard jc>0). The `jugar`
  column now reports `total_jugar`.
- `weaving_entry.py` — `entry_create`/`entry_edit`/`planning_grid_save` **persist INPUTS only** (after
  validating the quality is mapped + `cj ≤ jc`); they do NOT compute or store outputs and drop
  `_snapshot_params`' standards/computed binds. `entries_by_date`/`planning_grid` **SELECT from
  `vw_weaving_daily`** (planning_grid still starts from the quality-map driver rows LEFT JOIN the view,
  so a mapped loom with no entry still shows). Pydantic field `jugar` → `close_jugar` on
  `WeavingEntryCreate`/`Update`/`PlanningGridRow`.

## Formulas (constants `WEAVING_GRAMS_PER_OZ=28.35` → `production_kg = yds * ozs_yds * 28.35 / 1000` divisor 35.273, `WEAVING_YARD_FACTOR=36`; SPEC §12 Q13 **RESOLVED 2026-06-23** — both authoritative loom calculators + code3i confirm 28.35/1000; the 35.2 placeholder is dropped)

> **Computed by `vw_weaving_daily` (FREEZE NOTHING, 2026-06-24), NOT by Python on save.** The block
> below is the exact SQL the view implements (every divisor guarded: `jc>0`, `36*eff_picks>0`,
> `std_prod_yds>0`). `open_jugar` is the view's window `LAG(close_jugar)` over existing active rows in
> spell order (skips empty spells, crosses days). The thin `weaving_rules` formula module mirrors these
> for FE preview + unit tests only.

```
eff_speed     = COALESCE(act_speed, std_speed)      # SQC actual overrides std (legacy mapping)
# picks (REVISED 2026-06-30): std_picks = "actual PPI" = AVG(picks) from vw_weaving_pick_act
#   (SQC R-08-21 jute_sqc_weaving_pick) for the EXACT tran_date — no last-date carry, no target-map
#   fallback (no SQC that day ⇒ std_picks=0 ⇒ std_prod=0 ⇒ eff=0). act_picks/eff_picks now VESTIGIAL.
working_hours = max(0, spell.working_hours - Σ jute_prod_stoppage_hours[machine,date,spell])
# jugar model (REVISED 2026-06-30): oj=open, cj=close ENTERED, jc=no_of_jugar_per_cut, adj=less_production
oj            = LAST AVAILABLE close_jugar for (loom, quality) before this (date,spell); skips empty
                spells, across days (A1.close=12, B1 empty ⇒ A2.open=12); 0 at chain start
cj            = operator-entered closing jugar (0 ≤ cj ≤ jc)
adj           = less_production (reduce-jugar, Adjustment tab; COALESCE 0)
total_jugar   = cuts*jc + cj - oj - adj      # straight count, NO wrap, NO clamp (cuts*jc keeps it ≥0)
jugar         = total_jugar                  # the reported `jugar` column == total_jugar
production_yds = total_jugar * FL / jc       # guard jc>0; A1 oj0,cuts10,cj12,jc16→172/16·FL=10.75·FL; A2 oj12,cuts5,cj4→72/16·FL=4.5·FL
production_kg  = production_yds * ozs_yds * 28.35 / 1000   ;  production_mt = production_kg/1000   # divisor 35.273; round 3dp (Q13 RESOLVED)
std_prod_kg    = production_yds * std_ozs_yds * 28.35 / 1000   # STANDARD basis weight (code3i :315-318); round 0dp
std_prod_yds   = (eff_speed * working_hours * 60) / (36 * std_picks)   # "100prod" = 100% eff theoretical (REVISED 2026-06-30: divide by std_picks not eff_picks)
std_prod_eff   = std_prod_yds * std_eff / 100                 # "std prod" = 100prod × std eff% (planning_grid serializer, not the view)
efficiency     = production_yds * 100 / std_prod_yds          # ACTUAL eff vs 100prod; guard std_prod_yds>0; == legacy 'a_eff'
```
Legacy sources: `WeavingProductionServiceImpl.java:56,62`; `CutsJugarBuff1DAO.java:580-589,616-625,
496-540,371-386`. **Do NOT replicate** legacy bugs: per-spell FL (not `finished_length_a2`),
`(a+b)/2` group avg (not `a+b/2`), use `working_hours` (not hardcoded 8h).

**code3i cross-walk (original CodeIgniter source, verified 2026-06-23):**
- **Two efficiencies:** vowerp3 `efficiency` == legacy `a_eff` (actual-shots basis). Optional 2nd
  `actual_eff` = vs std-shots average (`yds100avg`). Both round 2 dp. **picks ≡ shots** (legacy
  `actual_shots`/`ashots`). Guard denominators > 0 (legacy has none — do-not-replicate).
- **Working-hours divergence:** real legacy = `daily_attendance.working_hours − idle_hours` per
  ticket/spell; stoppage separate in `daily_ebmc_attendance.mc_stoppage_hours`
  (`Loom_hrs_prod_updt.php:74-84`). Spec keeps `spell − Σ stoppage` (simplification).
- **Aggregate-path note:** code3i quality-aggregate save uses `production_yds = cuts*FL` (NO jugar
  term, `Weaving_daily_entry.php:263-273`); the jugar-aware formula is the per-loom engine only.
  vowerp3 uses the **revised** per-loom engine (§Formulas, 2026-06-24): `(cuts + jugar/jc)·FL` with
  `close` entered + `jugar` derived — NOT the legacy `cuts*FL − open*FL/jpc + jugar*FL/jpc`.
- **Rounding (legacy):** actual kg 3 dp; target kg & std-prod kg integer; efficiencies 2 dp;
  per-spell yards integer. vowerp3 stores full DEC precision, rounds at display.
- **Do-not-replicate (code3i):** `company_id=2` hardcoded in SELECTs
  (`Weaving_daily_entry.php:497-498,717,789`); duplicate `worker_name` CONCAT
  (`Loom_hrs_prod_updt.php:75`); two inconsistent oz→kg constants (actual `28.35/1000`=35.273 vs
  target `4408/125`=35.264); `tarkgs` computed twice.

## Constants (`src/juteProduction/constants.py`)

See canonical spec §8. `WEAVING_MACHINE_TYPE_NAME="Loom"`, `WEAVING_MACHINE_TYPE_ID=7` (Q1 2026-06-23;
matches code3i `type_of_mechine=7`; was "Weaving"), `WEAVING_ITEM_TYPE_IDS=(5,)`,
`WEAVING_GRAMS_PER_OZ=28.35` (CANONICAL, Q13: `*28.35/1000`=divisor 35.273), `WEAVING_OZ_PER_LB=16`
(cut-weight ref), `WEAVING_YARD_FACTOR=36`, **`qid`-only** param tuples (`WEAVING_QID_PARAMS_TARGET=
("speed","eff")` — Q5b; no `mcid`), `WEAVING_VALUE_ROLES=("standard","target","actual")`. `SPELLS` defined.

## Tests (`src/test/`)

`test_weaving_target_map.py` (grid resolution, bulk_save insert/update/clear, invalid-param 400),
`test_weaving_entry.py` (upsert, recompute), `test_weaving_masters.py` (CRUD),
`test_weaving_rules.py` (production_yds, production_kg, efficiency, **jugar carry-forward** across
spells/days). Mock `get_tenant_db` + `get_current_user_with_refresh`.

## Foundations (apply to dev3 first)

- `machine_type_mst`: confirm/seed **`'Loom'` = id 7** (Q1; matches code3i `type_of_mechine=7`; was `'Weaving'`).
- `item_type_master`: reuse `'Jute Cloth'=5` (woven product).
- Menus: `seed_weaving_menu.sql` (3 rows under Jute Production) + `seed_weaving_sqc_menu.sql` (Weaving
  SQC under juteSQC parent). Mirror beaming's seeds.

## Quality mapping + beam-change tabs (NEW — Q7, quality-mapping requirement)

Weaving production entry is a **tabbed** page like spinning (not beaming): **Loom→Quality** |
Production | Beam-Change | Planning. Quality is **mapped to looms** (`jute_prod_weaving_quality_map`,
per `date/spell/loom`) on the Loom→Quality tab — clone spinning `frame_map_get/save/mapped`
(`spinning_entry.py:678-852`, `spinning_query.py:251-441`, FE `FrameMapGrid.tsx`) — with carry-forward
prefill. The production grid has **no quality dropdown**; each loom shows its mapped quality read-only
(inherited via COALESCE; planning driver rows from the active map). Beam→loom is recorded on the
Beam-Change tab (`jute_prod_weaving_beam_map`, on each beam change with spell+date). **EB** is mapped
separately at attendance (attendance-taker enters `eb_no`) and **joined via a view** for display —
not entered on the weaving screen.

## Loom-Hours / Production-Update page (NEW — code3i `Loom_hrs_prod_updt.php`)

Operator edit screen surfaced by the original code3i source. Grain = **(date, spell, loom)**. Only
**Stoppage Hrs** + **Less Prod** editable; cuts/jugar/prod/eff read-only (derived). Save atomically
writes `less_production` → `jute_prod_weaving_daily` and `mc_stoppage_hours` → the stoppage source.
**Loom-data build** (legacy 3-step AJAX chain; vowerp3 = one server transaction): resolve
quality+actual_shots → `ticket_no`(EB)+working_hours from attendance → `open_A1`(prior `close_C`)
+`close` per spell. ⚠ Intra-day open chaining `open_B1=close_A1` … not in the controllers seen —
confirm vs vow2.0 `CutsJugarBuff1DAO.java:496-540`. Endpoints to add under `/api/weavingProd`:
`loom_hours_records` (GET, by date/spell/loom), `loom_hours_update` (POST — writes `less_production`
+ stoppage). `legacy_ref: Loom_hrs_prod_updt.php:455-490,74-84,712-745; Weaving_daily_entry.php:841-925`.

## Reports (informs SPEC §12 Q8) — code3i `weaving_daily_transaction`

Quality-wise daily aggregate (grain `co_id+tran_date+q_code`; 3-spell A/B/C rollup, A=A1+A2, B=B1+B2,
C=C). Derived by query in `reportQueries.py`, **NOT** a stored table. Columns of note: `yds100` (std
100% prod), `prd_std_ozs` (= std prod KG; misnamed in legacy), `aports`, `actual_eff`/`a_eff`,
`tarprda/b/c`. Single/double loom = COUNT of loom rows per quality/spell. EB-wise efficiency via
`ticket_no`/`eb` linkage. `legacy_ref: Weaving_daily_entry.php:321-353; Loom_hrs_prod_updt.php:297-335`.

## code3i legacy tables → vowerp3 (cross-walk; full version in SPEC §13.A)

`weaving_master`/`weaving_quality_master` → `jute_prod_weaving_quality` (+ `std_ozs_yds`, `jbo_rbo`,
`reed_space`, `tpi`, `yarn_count`); `daily_weaving_qualities` (per-loom-per-spell quality assignment) →
the loom+quality+spell grain; `cuts_jugar_buff_1` (wide 5-spell engine) → `jute_prod_weaving_daily`
(tall); `weaving_daily_transaction` → derived report; `tbl_prod_weaving_quality_mapping` →
`jute_prod_weaving_target_map` `value_role='actual'` (SQC); `daily_attendance`/`daily_ebmc_attendance`
→ working-hours + stoppage source; `mechine_master` looms `type_of_mechine=7` → `machine_mst`
`machine_type='Loom'` (id 7, Q1); `daily_weaving_qualities` → `jute_prod_weaving_quality_map` (§6.6).

## Loom production reference calculators (Sacking S14 + Hessian) — reconciled 2026-06-23

Two authoritative Excel calculators verified against the formulas above. **Core engine matches
exactly:** "Production @ 100% eff" = `std_prod_yds = (speed*hours*60)/(36*picks)`; "Production @ set
eff" = `target_prod_yds = std_prod_yds * eff/100` (Hessian `522.2 * 0.85 = 443.870`). Difference is
**direction only** — calculators take efficiency as INPUT (planning/forward); the daily-entry path
computes efficiency as OUTPUT from `cuts`/`jugar` (actuals). FE `weavingCalc.ts` = the planning view.

- **kg constant** = `oz * 28.35 / 1000` (divisor 35.273) — resolves SPEC Q13 (above).
- **Display-only derivations** (no column): `picks/dm = picks/in * 3.937` (store PPI; if a tenant
  enters metric picks/dm, `/3.937` before persisting to `qid/picks`); `cut_weight_lbs =
  finished_length * ozs_yds / 16`.
- **Warp-prep params belong to BEAMING, not weaving** — never on the weaving screen: laid_length
  (`jute_prod_beaming_target_map` qid/laid_length), std warp count (`jute_prod_bm_quality.std_count`),
  ends (`jute_prod_bm_quality.ends`), warp weight (beaming `kg_per_cut`; lbs = kg × 2.20462). The
  Hessian ends-in-beam derivation `((width*(1+shrink%))*reed_porter*2)/1.85` is NEW → beaming-quality
  if adopted (SPEC Q14). Keep one source of truth for `ends`.
