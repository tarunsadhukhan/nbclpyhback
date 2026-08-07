# Build Plan — R-08-04 Spreader Roll Weight (first Sliver/Roll-weight report)

> Source-verified blueprint produced from the as-built Morrah/Spinning code, the real master schemas,
> the report specs, and the FE Spinning-SQC page. This is the single source of truth for the build.
>
> Module: `juteSQC` · Persona: **Portal** (`get_tenant_db`, scoped by `co_id`/`branch_id`) ·
> Pattern: **insert-only + compute-on-read**, mirroring built Morrah (R-08-01).

## Decisions locked for this build
- **First report:** R-08-04 Spreader Roll Weight. R-08-03 (Spreader Roll Sliver Weight) is the immediate follow-up (same page, second tab).
- **Standards:** `std_mr_pct` nullable on a new `item_id`-keyed satellite + **code fallback to base 16** (matches the verified worked example). Default weight bands `55–75`; Spreader-2 `85–105`. Seed real per-quality values later.
- **Target tenant:** dev3 (migrations generated; applied later where dev3 is reachable).

---

## 1. Connect map (what is drawn from the existing system vs newly entered)

| Input field | Origin | Source detail (verified against real code) |
|---|---|---|
| `co_id`, `branch_id` | existing — sidebar | `SidebarContext` selected company/branch; on every call |
| `entry_date` | new typed (defaults today) | free date, no master |
| `spell_id` (SHIFT) | existing master `spell_mst` | `FROM spell_mst sp INNER JOIN shift_mst sh ON sh.shift_id = sp.shift_id WHERE sp.status=1 AND sh.status=1 AND (:branch_id IS NULL OR sh.branch_id=:branch_id)`. `spell_mst` has no `branch_id`/`co_id`; branch via `shift_mst`. De-dupe by `spell_code`. Filter is `status=1`, NOT `active`. |
| `mc_id` (MACHINE NO) | existing master `machine_mst` (spreaders) | **REUSE `get_spreader_machines_query()`** (`src/juteProduction/query.py:8`). `machine_mst` has no `process`/`section`/`branch_id`; spreader filter = `INNER JOIN machine_type_mst mt ... WHERE mt.machine_type_name = :spreader_type` (`SPREADER_MACHINE_TYPE_NAME = "Spreader"`), branch via `INNER JOIN dept_mst d ON d.dept_id = m.dept_id` + `(:branch_id IS NULL OR d.branch_id=:branch_id)`. Already returns `wt_per_roll` (std roll weight) from the `spreader_machine_attr` satellite — free standards pull. |
| `item_id` (QUALITY) | existing master `item_mst` raw-jute | **REUSE `get_morrah_wt_jute_qualities_query()`** (in `src/juteSQC/query.py`). Raw jute = 3-level walk: `FROM item_mst im JOIN item_grp_mst igm ON igm.item_grp_id=im.item_grp_id JOIN item_grp_mst parent ON parent.item_grp_id=igm.parent_grp_id WHERE parent.item_type_id=2 AND im.co_id=:co_id AND (im.active=1 OR im.active IS NULL)`. The `item_type_id=2` is on the **parent** group. Keep the `OR im.active IS NULL` tolerance. Do NOT use deprecated `jute_quality_mst`. |
| `feeder_name` | new free text (Phase 1) | HRMS-employee picker deferred to Phase 2 |
| `roll_weight_1..10` (kg) | new typed numbers | exactly 10; validate `len==10`, each `> 0` |
| `mr_pct_1..10` (%) | new typed numbers | exactly 10, parallel to weights |
| `std_mr_pct` | derived — new satellite | looked up by `item_id` from `jute_spreader_quality_attr`, **snapshotted onto the saved row** at save (mirrors spinning reading `jute_yarn_mst.std_mr_pct`); fallback 16 |
| band edges | derived — `spreader_machine_attr` | per-machine from `spreader_machine_attr` band columns at save; default `55/60/65/70/75` when unset |
| `calc_avg_mr_pct`, `calc_avg_obs`, `calc_avg_corr`, `calc_stdev_obs`, `calc_stdev_corr`, `calc_cv_pct`, `band_counts_obs`, `band_counts_corr` | computed (server, persisted) | from the stats helper at save; FE preview advisory, server authoritative |

**Production linkage:** this report is essentially **independent of production** — every input is a master pull or a fresh bench reading. Deferred to Phase 2 (Decision #4): feeder→HRMS employee, "rolls actually made"→spreader production run. Neither is needed to compute the QC stats.

---

## 2. Formulas (verified worked example — assert these in tests)

```
corrected_i = obs_i * (100 + std_mr_pct) / (100 + mr_i)      # std_mr fallback 16
avg_obs   = mean(obs)
avg_mr    = mean(mr)
avg_corr  = mean(corrected)
stdev_obs  = statistics.stdev(obs)          # sample n-1; guard n<=1 -> 0.0
stdev_corr = statistics.stdev(corrected)
cv_pct    = stdev_corr / avg_corr           # ratio on corrected basis; render ×100; guard avg_corr>0
band_counts_obs / band_counts_corr via 5-edge bucketer (<55 / 55-60 / 61-65 / 66-70 / 71-75 / >75)
```

Verified single correction: `69.40 × 116 / 138 = 58.34` (std_mr 16, obs_mr 38). Avg-corr `56.22`, stdev-obs `2.89`, stdev-corr `2.26`, CV `0.0402` (= 4.02%).

---

## 3. New storage

### 3a. Entry table — `jute_sqc_spreader_roll_wt` (NEW)
Morrah-shaped: flat header + JSON readings (`VARCHAR(500)` + `json.dumps`/`json.loads`, matching `jute_sqc_morrah_wt`) + persisted `calc_*`/band columns + `co_id, branch_id, entry_date, active, updated_by, updated_date_time`.

Columns: `spreader_roll_wt_id` PK AI · `co_id` NOT NULL · `branch_id` NULL · `entry_date` DATE NOT NULL · `spell_id` NULL · `mc_id` NULL · `item_id` NULL · `feeder_name` VARCHAR(255) NULL · `roll_weights` VARCHAR(500) NOT NULL (JSON 10) · `mr_pcts` VARCHAR(500) NOT NULL (JSON 10) · `std_mr_pct` DECIMAL(5,2) NULL · `calc_avg_mr_pct` DECIMAL(5,2) · `calc_avg_obs` DECIMAL(10,3) · `calc_avg_corr` DECIMAL(10,3) · `calc_stdev_obs` DECIMAL(10,4) · `calc_stdev_corr` DECIMAL(10,4) · `calc_cv_pct` DECIMAL(7,4) · `band_counts_obs` VARCHAR(500) NULL (JSON) · `band_counts_corr` VARCHAR(500) NULL (JSON) · `active` INT NOT NULL DEFAULT 1 · `updated_by` INT NULL · `updated_date_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP. Indexes: co_id, entry_date, (co_id,entry_date), mc_id, item_id. Include rollback `DROP TABLE` as a comment.

### 3b. Standards satellite — `jute_spreader_quality_attr` (NEW, `item_id`-keyed)
Mirrors `jute_yarn_mst`. Columns: `spreader_quality_attr_id` PK AI · `co_id` NOT NULL · `item_id` NOT NULL (→ item_mst raw jute) · `std_mr_pct` DECIMAL(5,2) NULL · `std_roll_wt` DECIMAL(10,3) NULL (optional; nullable/unused until needed) · `active` INT DEFAULT 1 · `updated_by` INT NULL · `updated_date_time` TIMESTAMP. Indexes: item_id, co_id. **Standards live here, NOT as columns on `item_mst`.**

### 3c. Band edges — extend EXISTING `spreader_machine_attr` (ALTER, not CREATE)
`std` roll weight already lives in `spreader_machine_attr.wt_per_roll` (already returned by `get_spreader_machines_query()`). Add 5 nullable band-edge columns: `band_edge_1..5` DECIMAL(10,3) NULL (default set 55/60/65/70/75 → 6 buckets; Spreader-2 uses 85/90/95/100/105). Helper falls back to the 55–75 set when a machine has no edges configured. Include rollback `DROP COLUMN` as a comment.

---

## 4. Backend build steps (file-by-file, mirror `morrahWeight.py`)

1. **Migrations** in `dbqueries/migrations/`: `create_jute_spreader_quality_attr.sql` (first — setup lookup needs it), `alter_spreader_machine_attr_band_edges.sql`, `create_jute_sqc_spreader_roll_wt.sql`. Each with rollback comment.
2. **ORM** — append `JuteSqcSpreaderRollWt` next to `JuteSqcMorrahWt` (wherever that class actually lives — check `src/models/jute.py` and `src/juteSQC/models.py`), copy its structure, swap columns per §3a. Add `JuteSpreaderQualityAttr`. Use whatever style the neighbouring SQC models use; `__table_args__ = {"extend_existing": True}` if needed.
3. **Query functions** in `src/juteSQC/query.py`: `get_spreader_roll_wt_spells_query()` (spell picker, §1); **import & reuse** `get_spreader_machines_query` from `src.juteProduction.query` and the existing `get_morrah_wt_jute_qualities_query`; `get_spreader_quality_std_query()` (`SELECT std_mr_pct FROM jute_spreader_quality_attr WHERE item_id=:item_id AND active=1`); `get_spreader_roll_wt_table_query()` + `_count_query()`; `get_spreader_roll_wt_by_id_query()`; `get_spreader_roll_wt_by_date_query()`; `soft_delete_spreader_roll_wt_query()` + `get_spreader_roll_wt_active_row_query()`.
4. **Endpoints** — new file `src/juteSQC/spreader_roll_wt.py`, `router = APIRouter()`, Portal deps (`get_tenant_db` + `get_current_user_with_refresh`):
   - `GET /get_spreader_roll_wt_setup` — validate `co_id`+`branch_id`; return `{"data": {"spells":…, "machines":…, "qualities":…, "entries": [by-date rows]}}`.
   - `POST /create_spreader_roll_wt` — Pydantic body (`co_id/branch_id/entry_date` in body); validate `len(roll_weights)==10`, `len(mr_pcts)==10`, weights `>0`; look up `std_mr_pct` (fallback 16) + band edges; call stats helper; build ORM row with `json.dumps(...)` readings + persisted `calc_*`/`band_counts_*`; `updated_by = token_data.get("user_id")`; `db.add/commit/refresh`; `db.rollback()` before re-raise.
   - `GET /get_spreader_roll_wt_table` — pagination (`page`/`limit`/`search`).
   - `GET /get_spreader_roll_wt_by_id` — `json.loads` readings + band JSON.
   - `GET /get_spreader_roll_wt_by_date` — date-driven rows.
   - `DELETE /spreader_roll_wt_delete/{spreader_roll_wt_id}` — guard active row → 404 → `UPDATE active=0, updated_by`.
5. **Stats helper** in `spreader_roll_wt.py`: `compute_spreader_roll_wt_stats(observed, mr, std_mr_pct, band_edges) -> dict` per §2. Reuse Morrah/Spinning idioms.
6. **Register router** — `src/main.py`, `app.include_router(spreader_roll_wt_router, prefix="/api/juteSQC", tags=["jute-sqc-spreader-roll-weight"])` alongside the other juteSQC routers.
7. **Tests** — `src/test/test_jute_sqc_spreader_roll_wt.py`. Unit-test `compute_spreader_roll_wt_stats` against the §2 verified fixture (corrected 58.34, avg-corr 56.22, stdev 2.89/2.26, CV 0.0402, band counts). Endpoint tests mock `get_tenant_db`/`get_current_user_with_refresh` (pattern: `test_yarn_quality.py`/`test_spinning_sqc*.py`): setup-200, missing-co_id-400, missing-branch_id-400, `len!=10`-400, create-success, by-id, delete-404-when-absent.

---

## 5. Frontend build steps (vowerp3ui — copy-adapt from Spinning SQC; weaving/page.tsx as minimal base)

1. **Route consts** in `src/utils/api.ts`, under `apiRoutesPortalMasters` (with the other SQC blocks). `_DELETE` is a base path (caller appends `/${id}`):
   `SPREADER_SQC_ROLL_WT_SETUP` → `/juteSQC/get_spreader_roll_wt_setup` · `_SAVE` → `/juteSQC/create_spreader_roll_wt` · `_BY_DATE` → `/juteSQC/get_spreader_roll_wt_by_date` · `_DELETE` → `/juteSQC/spreader_roll_wt_delete`.
2. **Stage page** `src/app/dashboardportal/juteSQC/spreader/page.tsx` — copy `weaving/page.tsx`; `TABS = ["R-08-04 Roll Weight"]` (single tab now). Mount-gate, `coId` from `useSelectedCompanyCoId`, branch resolution (1→auto, many→picker), guard cascade, per-tab `date` state + setup/by-date hooks, render `<RollWtForm>` then `<RollWtGrid>`.
3. **Types** `spreader/types/sqcSpreaderTypes.ts` — ALL types in one file: `SqcSpell`, `SqcMachine` (+`wt_per_roll`), `RawJuteQualityOption` (+`std_mr_pct`), `SpreaderRollWtSetup`, `SpreaderRollWtReadingRow`, `SpreaderRollWtByDateResponse`, `SpreaderRollWtSavePayload`. No `any`. Add a Zod schema for the form.
4. **Hooks** `spreader/hooks/useSqcRollWtSetup.ts` + `useSqcRollWtByDate.ts` — copy Spinning templates; swap route const + type; effect keyed `[coId, entryDate, branchId, version]`, `cancelled` flag.
5. **Entry Form** `spreader/_components/RollWtForm.tsx` — `{coId, branchId, entryDate, setup, onSaved}`; header pickers (spell/machine/quality — Autocomplete for quality); 10×(weight, MR%) number inputs (`type="number"`, `step:"any"`, `min:0`, string state) in a responsive grid (`gridTemplateColumns: {xs:"1fr", sm:"repeat(2…)", md:"repeat(3…)"}`); live preview of corrected/avg/CV/bands (advisory). POST `{co_id:Number(coId), branch_id, entry_date, roll_weights, mr_pcts, spell_id, mc_id, item_id, feeder_name}` (empty selects → null); snackbar; clear numeric fields; `onSaved()`. Math in `spreader/utils/spreaderCalc.ts`.
6. **Summary Grid** `spreader/_components/RollWtGrid.tsx` — date-driven summary `<Table>` (heavy/light/out-of-range flags via theme tokens, never hardcoded colors) + MUI X `<DataGrid autoHeight>` of readings with numeric `valueFormatter`s + delete action; synthetic `getRowId` (`${serverId}-${index}`); delete appends `/${id}?co_id=` to `_DELETE`, `confirm()`, `fetchWithCookie(url,"DELETE")`, `onDeleted()`.
7. **Landing tile** `src/app/dashboardportal/juteSQC/page.tsx` — add a `TILES` entry `{href:"/dashboardportal/juteSQC/spreader", title:"Spreader SQC", subtitle:"Spreader roll/sliver weight quality checks", icon:<Cog .../>}`.
8. **Sidebar menu** — NOT in FE repo; add `/dashboardportal/juteSQC/spreader` via the backend multi-level menu system (`portal_menu_mst` + `menu_mst` + `role_menu_map`) using the `add-menu` skill later.

---

## 6. Open items the owner can refine later (non-blocking)
1. Confirm exact `machine_type_mst.machine_type_name` string in dev3 (we reuse the production query, so consistent with the live Spreader Production page regardless).
2. Provide real std MR% per raw-jute quality (we default to base 16) and decide if per-quality `std_roll_wt` is wanted (machine-only `wt_per_roll` is the default std weight).
3. Confirm band-edge-on-`spreader_machine_attr` storage (vs a coded high/low flag).
4. R-08-03 follow-up: confirm variable 1–12 readings and that operators enter already-scaled lb/100yds.
