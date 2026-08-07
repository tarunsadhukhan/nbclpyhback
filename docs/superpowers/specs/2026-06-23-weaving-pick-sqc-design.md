# Weaving Pick-SQC (R-08-21 Loom Width & Picks) — Design

**Date:** 2026-06-23
**Module:** Jute SQC (`src/juteSQC/`) + Jute Production weaving (`src/juteProduction/`)
**Frontend:** `vowerp3ui/src/app/dashboardportal/juteSQC/weaving/`

## Problem

The Weaving SQC "Actual" screen currently lets the operator type a single actual
PPI (and actual loom speed) per quality+date straight into the weaving target map
(`jute_prod_weaving_target_map`, `value_role='actual'`, `param='picks'`). Production
`act_picks` resolves that single typed value.

The real QC process (Google Form "LOOM WIDTH AND PICKS — RECHECKING OF LOOM WIDTH
AND PICK FOR ISO R-08-21") records, per day, **multiple per-loom observations** —
`DATE, QUALITY, LOOM NO, WIDTH, PICK` — and for a quality on a day there are many
looms (and many qualities per day). The actual picks-per-inch used by production
must be the **average of those observations**, and the screen must also surface
std deviation, max and min.

## Goal

1. Replace the single typed "actual PPI" with a per-loom observation entry grid
   (date, quality, loom, width, pick); store every reading raw.
2. Compute and show, per (quality, date): average PPI, sample std deviation, min,
   max, observation count (plus width avg/min/max for display).
3. Wire weaving production so `act_picks` = the **average picks** for that quality,
   resolved through a DB **view** using the existing LAST-DATE resolution.
4. Keep actual loom **speed** entry as it is today (a separate small editor).

## Decisions (locked with the user)

- **act_speed:** keep the existing target-map actual-speed editor unchanged.
- **Wiring:** a DB **view** aggregates the raw readings; production resolves
  `act_picks` from the view (LAST-DATE), so the raw table stays the single source
  of truth and nothing is double-written into the target map.
- **Width:** stored + shown in stats only; NOT wired into any production calc and
  NOT pushed back into `jute_prod_weaving_quality.width`.
- **LOOM NO:** modelled as a loom **picker** (`machine_id` FK to the looms,
  resolved by `machine_type_mst.machine_type_name = 'Loom'`), not free text.
- **Searchable inputs:** quality and loom selectors are **type-ahead** (MUI
  `Autocomplete`) — the operator filters by typing, not a plain scroll dropdown.
- **Std deviation:** sample stddev (`STDDEV_SAMP`, n−1), `0` when n = 1; 2-dp display.

## Architecture

### 1. New raw table — `jute_sqc_weaving_pick`

Clone of `jute_sqc_spinning_count` semantics (insert-only per reading, soft delete,
trigger-based audit — no `created_*`).

| column | type | notes |
|---|---|---|
| `weaving_sqc_pick_id` | INT PK auto-increment | |
| `co_id` | INT NOT NULL | company scope |
| `branch_id` | INT NULL | NULL-tolerant (company-scoped) |
| `entry_date` | DATE NOT NULL | form DATE |
| `weaving_quality_id` | INT NOT NULL | FK `jute_prod_weaving_quality` (form QUALITY) |
| `machine_id` | INT NOT NULL | FK `machine_mst` (loom; form LOOM NO) |
| `width` | DECIMAL(10,3) NULL | form WIDTH |
| `picks` | DECIMAL(10,3) NOT NULL | form PICK (PPI) |
| `active` | TINYINT NOT NULL DEFAULT 1 | soft delete |
| `updated_by` | INT NULL | audit (trigger fills the rest) |
| `updated_date_time` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

Indexes: `(co_id, entry_date, active)` and `(co_id, weaving_quality_id, entry_date, active)`
to serve the by-date grid and the view aggregation.

Each save inserts a NEW reading (no upsert) — exactly like `sqc_count_save`.
Delete is a per-reading soft delete (`active = 0`).

### 2. View — `vw_weaving_pick_act`

One row per `(co_id, weaving_quality_id, entry_date)` over `active = 1`:

```sql
CREATE OR REPLACE VIEW vw_weaving_pick_act AS
SELECT
    co_id,
    weaving_quality_id,
    entry_date,
    AVG(picks)                       AS avg_picks,
    COALESCE(STDDEV_SAMP(picks), 0)  AS std_picks,
    MIN(picks)                       AS min_picks,
    MAX(picks)                       AS max_picks,
    AVG(width)                       AS avg_width,
    MIN(width)                       AS min_width,
    MAX(width)                       AS max_width,
    COUNT(*)                         AS n_obs
FROM jute_sqc_weaving_pick
WHERE active = 1
GROUP BY co_id, weaving_quality_id, entry_date;
```

The view does NOT do last-date; the resolver does (`ORDER BY entry_date DESC LIMIT 1`),
matching `resolve_param`.

### 3. Production wiring

In `src/juteProduction/services/weaving_standards.py`:

- Add `resolve_act_picks(db, co_id, weaving_quality_id, on_date) -> float`:
  selects `avg_picks` from `vw_weaving_pick_act` for `(co_id, weaving_quality_id)`
  with `entry_date <= :on_date`, `ORDER BY entry_date DESC LIMIT 1`; returns `0.0`
  when no observation exists.
- In `resolve_quality_standards`, replace the `act_picks` line:
  - **Old:** `resolve_param(db, co_id, qid, 'qid', 'actual', 'picks', on_date)`
  - **New:** `resolve_act_picks(db, co_id, weaving_quality_id, on_date)`
- `eff_picks = act_picks if act_picks else std_picks` — UNCHANGED.
- `act_speed`, `std_*`, `target_eff`, etc. — UNCHANGED (still target map).

Effects:
- The planning grid (`/weavingProd/planning_grid`) recomputes live, so it reflects
  new averages immediately.
- `entry_create` / `entry_edit` / `planning_grid_save` snapshot the view-average
  into `jute_prod_weaving_daily.act_picks` on next save.
- Already-saved daily snapshots from before this change keep their old `act_picks`
  until re-saved (acceptable; the live grid is authoritative).
- Pre-existing target-map `actual/picks` rows become inert (left in place, not
  deleted). Actual loom speed rows (`actual/speed`) keep working.

### 4. Backend module — `src/juteSQC/weaving_sqc.py` + `weaving_sqc_query.py`

Portal persona (`get_tenant_db` + `get_current_user_with_refresh`, `{"data": ...}`
responses), cloned from `spinning_sqc.py`. Router registered in `src/main.py` under
`prefix="/api/juteSQC"`, `tags=["jute-sqc-weaving"]`.

Endpoints:

| method | path | purpose |
|---|---|---|
| GET | `/weaving_sqc_pick_setup` | `{qualities, looms, readings, summary}` for a co/entry_date/branch |
| POST | `/weaving_sqc_pick_save` | batch insert observations (insert-only) |
| GET | `/weaving_sqc_pick_by_date` | `{readings, summary}` for a co/entry_date/branch |
| DELETE | `/weaving_sqc_pick_delete/{id}` | soft-delete one reading |

- `qualities` — reuse `get_weaving_entry_qualities_query` (weaving_query.py).
- `looms` — reuse `get_weaving_entry_machines_query` (weaving_query.py, type 'Loom').
- `readings` — active rows for the date with quality/loom labels.
- `summary` — `SELECT ... FROM vw_weaving_pick_act` joined to the quality master for
  labels, filtered by co_id + entry_date. Width/picks stats come straight from the
  view; values cast to float for JSON.

> Branch note: the view aggregates without `branch_id` (the pick table is
> company-scoped and branch is NULL-tolerant, mirroring the target map). The
> summary endpoint filters by `co_id, entry_date` only; readings carry branch for
> display. If per-branch summaries are later needed, add `branch_id` to the view
> GROUP BY — out of scope now.

Pydantic models (mirror `SqcCountRow`/`SqcCountSave`):

```python
class WeavingPickRow(BaseModel):
    weaving_quality_id: int
    machine_id: int
    width: Optional[float] = Field(default=None, ge=0)
    picks: float = Field(ge=0)

class WeavingPickSave(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: date
    entries: List[WeavingPickRow] = Field(default_factory=list)
```

ORM model `WeavingSqcPick` added to `src/juteProduction/weaving_models.py`
(weaving tables live there; the SQC pick table is weaving-specific).

### 5. Frontend — `juteSQC/weaving/page.tsx`

Tabs become `["Loom Width & Picks (R-08-21)", "Actual Speed"]`:

- **Tab 0 — Loom Width & Picks (new):**
  - `hooks/useWeavingPickSetup(coId, entryDate, branchId)` — loads qualities, looms,
    readings, summary (mirror `useSqcCountSetup`).
  - `hooks/useWeavingPickByDate(coId, entryDate, branchId)` — `{readings, summary, refresh}`
    (mirror `useSqcCountByDate`).
  - `_components/PickForm.tsx` — add observation rows. Quality and loom use MUI
    `Autocomplete` (**searchable / type-ahead**); width + pick are number fields.
    POST `weaving_sqc_pick_save`; calls `refresh` on save.
  - `_components/PickGrid.tsx` — readings table (date, quality, loom, width, pick,
    delete) + a per-quality **summary** block: avg PPI, std dev, min, max, n, avg width.
- **Tab 1 — Actual Speed:** existing `TargetMapEditor` (valueRole `actual`) but
  **speed-only** — drop `picks` from the actual params so the editor offers only
  Speed. (`paramLabels={{ speed: "Speed (picks/min)" }}`.)

`api.ts` — add under the Spinning-SQC block:

```ts
WEAVING_SQC_PICK_SETUP:   `${API_URL}/juteSQC/weaving_sqc_pick_setup`,
WEAVING_SQC_PICK_SAVE:    `${API_URL}/juteSQC/weaving_sqc_pick_save`,
WEAVING_SQC_PICK_BY_DATE: `${API_URL}/juteSQC/weaving_sqc_pick_by_date`,
WEAVING_SQC_PICK_DELETE:  `${API_URL}/juteSQC/weaving_sqc_pick_delete`, // base path; append /${id}
```

### 6. `WEAVING_PARAMS_ACTUAL` change

`src/juteProduction/constants.py`: `WEAVING_PARAMS_ACTUAL` changes from
`("speed", "picks")` to `("speed",)` — actual picks no longer live in the target
map. Verify and follow every consumer (`weaving_target_map.py` actual-role grid /
bulk-save param set) so the Actual target-map grid only offers Speed. The `'picks'`
under `actual` is now owned by the pick-SQC table.

### 7. Migration

`dbqueries/migrations/2026-06-23_weaving_pick_sqc.sql` (target **dev3** via pymysql):
- `CREATE TABLE jute_sqc_weaving_pick (...)` + indexes.
- `CREATE OR REPLACE VIEW vw_weaving_pick_act AS ...`.
- Rollback SQL as comments (`DROP VIEW vw_weaving_pick_act; DROP TABLE jute_sqc_weaving_pick;`).

### 8. Tests — `src/test/test_weaving_sqc.py`

- `weaving_sqc_pick_setup` returns qualities/looms/readings/summary; missing `co_id`
  → 400; missing/invalid `entry_date` → 400.
- `weaving_sqc_pick_save` inserts N rows (insert-only); response `{"saved": N}`.
- `weaving_sqc_pick_by_date` returns readings + per-quality summary (avg/std/min/max/n).
- `weaving_sqc_pick_delete` soft-deletes; 404 when not found.
- `resolve_quality_standards` (or `resolve_act_picks`) returns the view's `avg_picks`
  as `act_picks` (mock the view row); `0.0` when no observations.

## Out of scope

- Per-branch view aggregation (view groups by co+quality+date only for now).
- Back-filling old daily snapshots' `act_picks` (live grid is authoritative).
- Removing legacy target-map `actual/picks` rows (left inert).
- Pushing width back into the quality master.

## File-change summary

**Backend (`vowerp3be`):**
- `dbqueries/migrations/2026-06-23_weaving_pick_sqc.sql` — new
- `src/juteProduction/weaving_models.py` — add `WeavingSqcPick`
- `src/juteSQC/weaving_sqc.py` — new router
- `src/juteSQC/weaving_sqc_query.py` — new query builders
- `src/juteProduction/services/weaving_standards.py` — `resolve_act_picks` + swap `act_picks`
- `src/juteProduction/constants.py` — `WEAVING_PARAMS_ACTUAL = ("speed",)`
- `src/juteProduction/weaving_target_map.py` — follow the actual-param change (if it enumerates picks)
- `src/main.py` — register weaving SQC router
- `src/test/test_weaving_sqc.py` — new tests

**Frontend (`vowerp3ui`):**
- `src/app/dashboardportal/juteSQC/weaving/page.tsx` — rework tabs
- `src/app/dashboardportal/juteSQC/weaving/hooks/useWeavingPickSetup.ts` — new
- `src/app/dashboardportal/juteSQC/weaving/hooks/useWeavingPickByDate.ts` — new
- `src/app/dashboardportal/juteSQC/weaving/_components/PickForm.tsx` — new (searchable Autocomplete pickers)
- `src/app/dashboardportal/juteSQC/weaving/_components/PickGrid.tsx` — new
- `src/utils/api.ts` — add `WEAVING_SQC_PICK_*`
