# Trolley Machine-Type Marker — Design

**Date:** 2026-06-18
**Repos:** `vowerp3be` (backend, migration, tests) + `vowerp3ui` (Trolly Master page)
**Status:** Approved design — ready for implementation plan

## Problem

`trolly_mst` rows (tare-weight containers used in jute production) cannot be
scoped to a production stage. The only existing marker, `trolly_type`, encodes
**Trolly (`T`) vs Spool (`S`)** — not *which* process a trolley belongs to. As a
result:

- **Spinning doff entry** lists **all** trolleys (`spinning_entry.py:333`, via
  `get_trollies_query`) with no stage filter.
- **Winding doff entry** splits by `T`/`S` (`winding_entry.py:261/275`) but across
  every trolley, regardless of stage.

We need each production page to show **only the trolleys that belong to its
stage**.

Branch mapping is **already complete** (`trolly_mst.branch_id`, persisted by
create/edit/list, surfaced in the master form + grid) — out of scope here. The
stale FE comments claiming the backend doesn't persist `branch_id`/`trolly_type`
are wrong and will be removed.

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Marker axis | `machine_type` (`machine_type_mst`) |
| Cardinality | **One** machine type per trolley (single column) |
| Untagged trolleys | **Strict** — pages show only trolleys tagged with their stage; untagged are excluded (re-tagged via master page; no blind backfill) |
| Pages wired now | Spinning doff entry + Winding doff entry |
| Master field | **Required** on create/edit |
| Dropdown scope | 4 production stages only: Spreader, Drawing, Spinning, Winding |

`machine_type_mst` is a global master (no `co_id`) with columns
`machine_type_id`, `machine_type_name`, `active`. The four stage names already
exist there and are referenced at runtime by the production-page constants
(`SPREADER/DRAWING/SPINNING/WINDING_MACHINE_TYPE_NAME`).

## Data model

```
trolly_mst
  + machine_type_id  INT NULL   -- FK machine_type_mst.machine_type_id
```

Nullable at the DB level so existing rows survive the migration; the master page
enforces "required" on new/edited rows. `trolly_type` (`T`/`S`) is unchanged and
orthogonal — a Winding trolley can still be `T` or `S`.

**ORM drift fix** — `TrollyMst` (`spinning_models.py:157`) currently omits the
`trolly_type` column that the DB and queries already use. Add **both**
`trolly_type` and `machine_type_id` to the model.

## Backend changes (`src/juteProduction/`)

1. **Migration** `dbqueries/migrations/add_machine_type_id_to_trolly_mst.sql`
   - `ALTER TABLE trolly_mst ADD COLUMN machine_type_id INT NULL;`
   - Rollback (commented): `ALTER TABLE trolly_mst DROP COLUMN machine_type_id;`
   - No data backfill — a trolley's stage is not derivable from existing rows.

2. **New endpoint** `GET /spinningMasters/trolly_machine_types`
   - Returns active `machine_type_mst` rows where
     `machine_type_name IN ('Spreader','Drawing','Spinning','Winding')`.
   - Response: `{"data": [{"machine_type_id", "machine_type_name"}]}`.
   - Stage names sourced from the existing constants, not hardcoded inline.

3. **Create / edit** (`spinning_masters.py`)
   - `TrollyCreate.machine_type_id: int` (required), `TrollyUpdate.machine_type_id:
     Optional[int]`.
   - INSERT/UPDATE persist `machine_type_id`.

4. **`get_trollies_query`** (`spinning_query.py:80`)
   - Add `machine_type_id` to the SELECT and `LEFT JOIN machine_type_mst` for
     `machine_type_name`.
   - Add an **optional** `:machine_type_name` bind:
     ```sql
     AND ( :machine_type_name IS NULL
           OR machine_type_id = (
               SELECT machine_type_id FROM machine_type_mst
               WHERE machine_type_name = :machine_type_name AND active = 1 LIMIT 1) )
     ```
   - Master list (`trolly_list`) passes `:machine_type_name = NULL` → all rows
     (tagged + untagged) so the master remains the place to see/fix everything.
   - Strict filter: when a stage name is passed, untagged (`NULL`) rows are
     excluded automatically (NULL never equals the resolved id).

5. **Spinning entry** (`spinning_entry.py:333`) — pass
   `machine_type_name = SPINNING_MACHINE_TYPE_NAME` into `get_trollies_query`.

6. **Winding entry** (`winding_entry.py:261/275`) — `get_winding_trollies_query`
   (`winding_query.py:64`) gains the same `:machine_type_name` filter; keep the
   existing `:trolly_type` `T`/`S` split. Both calls pass
   `WINDING_MACHINE_TYPE_NAME`.

## Frontend changes (`vowerp3ui` — `trollyMaster/page.tsx`)

- Add `MACHINE_TYPES` route constant + fetch from the new endpoint on mount.
- **Create/edit dialog:** add a required **Machine Type** `<Select>`; include
  `machine_type_id` in the create/edit body; disable **Save** until set.
- **Grid:** add a **Machine Type** column (resolve id → name via the loaded list).
- **Filter bar:** extend the existing Type filter (or add a parallel Machine Type
  filter) to filter the grid by stage.
- Remove the stale "backend does not persist" comments; type `machine_type_id` on
  `TrollyRow`/form state.

## Testing

- `test_spinning_masters.py` — create & edit persist `machine_type_id`; list
  returns it; new `trolly_machine_types` endpoint returns the 4 stages; create
  rejects missing `machine_type_id`.
- `test_spinning_planning_grid.py` / `test_spinning_entry.py` — spinning trolley
  list excludes other-stage and untagged trolleys.
- `test_winding_entry.py` — winding trolley/spool lists filtered to Winding +
  correct `T`/`S` split.

## Out of scope

- Spreader / Drawing pages (no trolley consumption today).
- Branch mapping (already complete).
- Many-to-many trolley↔stage sharing (single tag chosen).
- Backfilling stage tags onto existing trolleys.
