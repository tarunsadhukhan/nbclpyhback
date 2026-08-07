# Weaving Standards — add Machine dimension, move `speed` to machine

**Date:** 2026-06-24 · **Target tenant DB:** dev3 (promote later) · **Repos:** vowerp3be + vowerp3ui

## Problem

The Weaving Standards page (`jute_prod_weaving_target_map`) is QUALITY-ONLY: every
standard/target keys off `id_type='qid'` (ref = `weaving_quality_id`). But loom **speed
(picks/min)** is a property of the **machine (loom)**, not the cloth quality. It must be
entered per loom, while **Picks (PPI)** and **Efficiency %** stay per quality.

## Decision

Make weaving standards **two-dimensional**, identical in shape to the existing
**beaming** target map (mcid + qid). No new patterns — clone beaming.

### Param contract (single source of truth: `grid_params_for`)

```
mcid (ref_id = machine_id / loom):   standard → (speed)        target → (speed)   actual → (speed)
qid  (ref_id = weaving_quality_id):  standard → (picks, eff)   target → (eff)     actual → ()  none
```

- `actual speed` moves qid → mcid (entered on the Weaving SQC "Actual Speed" tab, now per loom).
- `actual picks` is unchanged — owned by `vw_weaving_pick_act` (Pick-SQC page), never the target map.
- Machine list = looms: `machine_type_mst.machine_type_name = 'Loom'` (dev3 id 6),
  active + company-scoped — the same loom list the planning grid uses
  (`get_weaving_entry_machines_query`).

### Migration policy for existing data

Existing rows `id_type='qid' param='speed'` are keyed to a quality and cannot be
auto-mapped to a loom → **soft-delete (`active=0`)**. Speed is re-entered per loom on the
new Machine tab. Until re-entered, production `std_speed`/efficiency resolve to 0 (accepted).

## Changes

### Backend (vowerp3be)

1. **`src/juteProduction/constants.py`** — add `WEAVING_ID_TYPE_MC = "mcid"`. Replace the
   QUALITY-ONLY param block with:
   ```python
   WEAVING_MC_PARAMS_STD     = ("speed",)
   WEAVING_MC_PARAMS_TARGET  = ("speed",)
   WEAVING_MC_PARAMS_ACTUAL  = ("speed",)   # Weaving SQC Actual Speed tab
   WEAVING_QID_PARAMS_STD    = ("picks", "eff")
   WEAVING_QID_PARAMS_TARGET = ("eff",)
   # qid has NO actual params (actual picks → vw_weaving_pick_act; actual speed → mcid)
   ```
   Keep `WEAVING_PARAMS_ACTUAL` removed/renamed; update the union comment.

2. **`src/juteProduction/weaving_target_map.py`** — clone beaming's two-dim handling:
   - `ID_TYPES = [WEAVING_ID_TYPE_MC, WEAVING_ID_TYPE_QLTY]`
   - `PARAMS` = union of all 5 param tuples
   - `grid_params_for(id_type, value_role)` covers both dims (mcid: std/target/actual=speed;
     qid: std=(picks,eff), target=(eff))
   - `target_map_setup` returns both `machines` (looms) + `qualities`
   - `target_map_grid` selects loom refs for mcid, quality refs for qid
     (mirror `beaming_target_map.target_map_grid`)

3. **`src/juteProduction/weaving_query.py`** — no new query needed; reuse
   `get_weaving_entry_machines_query()` (returns machine_id/mech_code/machine_name →
   ref_id/ref_code/ref_name) for the mcid refs, bound with `:loom_type`. Refresh the
   PAGE B header comment (no longer QID-only).

4. **`src/juteProduction/services/weaving_standards.py`** — `resolve_quality_standards`
   gains a `machine_id` param. Resolve `std_speed`/`act_speed` from `mcid`
   (ref=machine_id); `std_picks`/`std_eff`/`target_eff` stay qid; `act_picks` stays
   `vw_weaving_pick_act`. Returned keys unchanged → callers need only pass `machine_id`.

5. **`weaving_entry.py`** — the machine-standards prefill (≈ line 531) passes `machine_id`
   to the updated resolver (already in scope).

6. **`vw_weaving_daily` view** — in the `s` sub-select, carry `machine_id` into the inner
   `d2` derived table (`w.machine_id AS mid`), and switch the two `speed` subselects to
   `id_type='mcid' AND tm.ref_id = d2.mid`; `picks`/`eff` subselects stay
   `id_type='qid' ref_id=d2.qid`. The view DDL is **duplicated verbatim** in:
   - `dbqueries/migrations/alter_weaving_daily_lean_and_view.sql`
   - `dbqueries/migrations/create_weaving_tables.sql`
   Edit BOTH byte-identically.

7. **New migration** `dbqueries/migrations/weaving_standards_machine_dimension.sql`:
   - `UPDATE jute_prod_weaving_target_map SET active=0 WHERE id_type='qid' AND param='speed' AND active=1;`
   - `CREATE OR REPLACE VIEW vw_weaving_daily AS ...` (the repointed view)
   - rollback SQL as comments
   Run against dev3 via the run-migration skill.

### Frontend (vowerp3ui)

8. **`masters/weavingTargetMap/page.tsx`** — add a **Type** selector (Machine / Quality)
   driving `idType` into `TargetMapEditor`. Roles stay [standard, target]. Drop the
   QUALITY-ONLY comment.

9. **`masters/weavingTargetMap/_components/TargetGrid.tsx`** — add `refLabel` prop
   (default `"Quality"`); the page passes `"Loom"` for Machine type. Generalize the empty
   message ("No rows found for this company").

10. **`juteSQC/weaving/page.tsx`** — "Actual Speed" tab: `idType="qid"` → `"mcid"`; label
    "Quality" → "Loom". `valueRole="actual"`, param `speed` unchanged.

### Tests (vowerp3be)

11. `src/test/test_weaving_target_map.py` — two-dim `grid_params_for`, machine refs in
    setup/grid, mcid speed save, qid picks/eff save.
12. `src/test/test_weaving_entry.py` — prefill resolves speed by machine.

## Out of scope

- Loom-Hours page / weaving reports (already deferred).
- No change to the Pick-SQC (R-08-21) path or `vw_weaving_pick_act`.
