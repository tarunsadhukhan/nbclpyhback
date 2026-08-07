# 03 — Setup Guide (how to stand this up)

A concrete, ordered plan to build the unbuilt reports in VOW. Follow the built reports as templates;
nothing here invents a new pattern.

## 0. Prerequisites / decisions to close first

1. Resolve the **per-(process × quality) standards storage** question (`05-open-questions.md` Q1) —
   it blocks the std-column migrations for the whole sliver/weave family.
2. Confirm the **target tenant**: build & QA on **dev3** first (default), then promote to the live
   jute tenant. (Empire Jute Mill's live tenant DB to be named by the owner; the built SQC tables
   already have an `sls` precedent — `sls_create_jute_sqc_spinning_tables.sql`.)
3. Confirm the **line/blend quality master** (`jute_quality_mst` vs item-based) and the **cloth/fabric
   quality master** exist for weaving reports; if not, that is the only place a new master may be
   unavoidable — raise with owner before assuming.

## 1. Phasing (recommended build order — by shared pattern, cheapest reuse first)

| Phase | Reports | Why grouped |
|-------|---------|-------------|
| **1. Sliver/Roll weight family** | 03, 04, 05/06/07, 07A, 08/09/10, 12/13/14 | One shared model + one stats helper + one mobile form, parameterised per stage. Biggest payoff. |
| **2. Spinning finish** | 17 TPI | Extends the existing spinning tab; small. |
| **3. Beam + simple MR%** | 18 beam, 25 packing | MR%-only, trivial. |
| **4. Weaving construction** | 19, 20, 21, 22 | Std-vs-actual fabric measures; share a model. |
| **5. Bag/finishing** | 23, 24 | Bag weight + checklist. |
| **6. Defect & environment** | 28 fabric fault, humidity | Distinct shapes (matrix score; env log). |
| **7. Emulsion** | 02 | A daily recipe log (different shape — no QC stats). Can be done any time. |

## 2. Backend steps (per report, mirroring `morrahWeight.py` / `spinning_sqc.py`)

1. **Migration** `dbqueries/migrations/create_jute_sqc_<report>.sql` — new entry table(s)
   `jute_sqc_<report>` (+ `_dtl` if many readings). Columns: `co_id, branch_id, entry_date`, header
   keys (`mc_id`/`item_id`/`spell_id`/`dept_id` as needed), raw readings (JSON like morrah OR detail
   rows), `active, updated_by, updated_date_time`. Include rollback SQL as a comment. Pair an `sls_`
   copy if promoting to that tenant (precedent: `sls_create_jute_sqc_spinning_tables.sql`).
2. **Standards satellite** (`05-standards-storage.md`) — standards live in an **`item_id`-keyed
   satellite table**, not on `item_mst`. Reuse `jute_yarn_mst` for spinning; create a stage satellite
   (`create_jute_<stage>_quality_std.sql`) keyed `(item_id)` or `(item_id, process)` only when that
   report's stage is built. **Case-by-case** — do not batch one composite standards table.
3. **ORM** — append model class(es) to `src/juteSQC/models.py` (legacy `Column(...)` style, reuse `Base`).
4. **Queries** — add `text()` builders to `src/juteSQC/query.py` (or a new `<report>_query.py`):
   setup dropdowns (+ std values), insert header/detail, by-date read, soft-delete. Use
   `:x IS NULL OR col=:x` optional filters and `active=1`.
5. **Router** — endpoints on the existing `/api/juteSQC` router (or a new file included with the same
   prefix): `<report>_create_setup`, `<report>_save`, `<report>_by_date` (or `_table`), `<report>_delete`.
   Compute stats in Python (`statistics.stdev`, the §A correction, §C CV%, §D buckets). Wrap all
   responses as `{"data": ...}`. Validate `co_id`/`branch_id` first.
6. **Tests** — `src/test/test_jute_sqc_<report>.py`, mocking `get_tenant_db` + `get_current_user_with_refresh`
   (pattern: `test_spinning_sqc*.py`). Assert the worked example from the report spec (correction, CV%,
   buckets) and the 400s for missing params.
7. **Run migration** via pymysql against **dev3** first (no `mysql` CLI — see repo `CLAUDE.md`).

## 3. Frontend steps (tabbed page per stage; entry tabs responsive)

Group a stage's reports into **one page with tabs** (mirror `juteSQC/spinning/page.tsx`: tabs Count /
Speed-TPI / RHMR / QR-CV). Each report = a tab. **Entry tabs are built responsive** (phone/tablet on
the floor); summary/report tabs can be desktop grids.

1. **Route consts** in `src/utils/api.ts` under `apiRoutesPortalMasters`, e.g. `JUTE_SQC_<REPORT>_SETUP/_SAVE/_BY_DATE/_DELETE` (mirror `SPINNING_SQC_*`).
2. **Stage page** `src/app/dashboardportal/juteSQC/<stage>/page.tsx` with a `TABS` array; each report
   renders its Form+Grid tab. Honour the **sidebar `co_id`/`branch_id`** (`SidebarContext`).
3. **Responsive entry tab** `_components/<Report>Form.tsx` — date + header pickers (machine/quality/spell
   from setup) then the reading inputs (`type="number"`, large touch targets, single reading-set,
   stacks to one column on small screens), with a **live client-side preview** of the computed stats
   (server stays authoritative).
4. **Summary/report tab** `_components/<Report>Grid.tsx` — date-driven, the "master tab" equivalent:
   per reading-set + per-quality grand averages, pass/fail vs band, delete action.
5. **Hooks** `hooks/use<Report>Setup.ts` + `use<Report>ByDate.ts` (mirror `useSqcCountSetup`/`useSqcCountByDate`).
6. **Types + Zod** in a single types file per report (no `any`).
7. All API calls via `fetchWithCookie`.

## 4. Menu / access

Add a sidebar entry per report (or one "Jute SQC" group with sub-items) through the multi-level menu
system: `portal_menu_mst` template (vowconsole3) → `menu_mst` in the tenant DB → `role_menu_map`.
Use the `add-menu` skill; it asks which DBs/tenants and roles. The juteSQC landing
(`juteSQC/page.tsx`) currently tiles Morrah / Spinning / Beaming — extend its `TILES`.

## 5. Definition of done (per report)

- Migration applied to dev3; ORM + queries + endpoints + tests green (`pytest src/test/test_jute_sqc_<report>.py`).
- Mobile entry saves a reading-set; summary view reproduces the report's worked example exactly
  (correction, CV%, buckets match the spec's numbers).
- Std values come from the masters (no hardcoded standards), honouring the sidebar company/branch.
- Menu entry visible to the SQC role.
