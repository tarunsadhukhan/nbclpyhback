# Spinning Day-Slice + Process→Lock Conversion — Design Spec

**Date:** 2026-07-12
**Scope repos:** `vowerp3be` (backend), `vowerp3ui` (frontend)
**Pattern source:** weaving Phase 1 (day-slice reads) + weaving entry→process→lock (frozen posting table, set-based Process)
**Approved decisions:** Phase-1 day-slice pattern (no dirty-journal/scheduler); entry/grid pages only (reports out of scope); dev3 + sls both; weaving review findings fixed in a separate effort; spinning gets Process+Lock, winding stays raw entry; Process replaces the manual Save button.

---

## 1. Problem

The spinning planning grid (`GET /api/spinningProd/planning_grid`, `src/juteProduction/spinning_entry.py`) is the last unconverted "compute-on-read with unbounded cost" screen:

1. **N+1 per driver row:** ~11 sequential DB round trips per mapped frame×spell (9 `resolve_param` last-date lookups against `jute_prod_spng_target_map`, 1 `resolve_act_count`, 1 doff-net query). A 50-frame × 2-spell day ≈ 1100+ sequential queries.
2. **Unbounded view read per (item, shift) group:** `get_winding_total_query()` (`spinning_query.py`) reads `vw_winding_daily_reconciled`, whose `GROUP BY` aggregates the **entire** `jute_prod_winding_doff` history on every call. This is the sole remaining app reader of any unbounded view — tracked in `src/test/test_no_unbounded_view_readers.py` ALLOWLIST as "Phase 2: remove". Same failure shape that 504'd weaving on sls (2.2M rows).
3. **Posting is manual and row-at-a-time:** `planning_grid_save` loops rows in Python (1 SELECT + 1 INSERT/UPDATE each) into `jute_prod_spinning_daily`, whose 5-column upsert lookup has no composite index. No freeze/lock semantics — anyone can re-save any day.

**Winding is NOT part of the problem.** Recon confirmed the winding page reads zero views: all its endpoints are day-scoped inline SQL over `jute_prod_winding_doff` / `jute_prod_winding_jugar` / `jute_prod_winding_daily_qlty`, covered by existing composite indexes. Winding stays raw entry, unlocked, unchanged.

## 2. Architecture

### 2.1 Read path: `spinning_day_slice_sql()`

New parameterized SQL fragment in `spinning_query.py` (weaving `weaving_day_slice_sql` as the template). Driver = `daily_doff_frames_winding` (`spg_wdg='S'`) filtered to `(co_id, tran_date[, spell_id, branch_id])` in the innermost FROM, then LEFT JOINed once-per-request set-based derived tables:

| Alias | Replaces | Mechanism |
|---|---|---|
| `tm` | 9 per-row `resolve_param` calls | `ROW_NUMBER() OVER (PARTITION BY ref_id, value_role, param ORDER BY effective_date DESC, <pk> DESC)` rn=1 over `jute_prod_spng_target_map` (`active=1`, `effective_date <= :tran_date`), pivoted with `MAX(CASE ...)` into std/target/actual speed, tpi, eff, spindles |
| `cnt` | per-row `resolve_act_count` | `AVG` over `jute_sqc_spinning_count`, date semantics byte-matched to the current resolver |
| `doff` | per-row `get_doff_net_by_frame_query` | one day-scoped `SUM(net_weight) ... GROUP BY mc_id, spell` over `daily_doff_tbl` |
| `wnd` | per-(item,shift) `vw_winding_daily_reconciled` read | inline day-scoped reconciliation over winding base tables: per (machine, spell, item) `SUM(production_qty) − COALESCE(MAX open jugar) + COALESCE(MAX close jugar)`, then `GROUP BY item_id, LEFT(spell_code,1)`. Formula source: `get_winding_reconciliation_query()` / `winding_rules.py`. Branch predicate replicated exactly: `(:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)` |

Outer layers compute `p100prod`, `std_prod`, `target_prod`, `eff_doff`, and the doff-share allocation `act_prod_wind = ROUND(winding_total * act_prod_doff / SUM(act_prod_doff) OVER (PARTITION BY co_id, tran_date, item_id, shift_bucket), 3)`, `eff_winding` — byte-matched to `vw_spinning_planning_grid` (the oracle, which already mirrors today's Python). Window functions are allowed here because the partition is day-bounded inside the slice (doctrine forbids them only over unbounded history).

Consumers:
- `GET /planning_grid` — one slice execution when unit is live; response shape (`rows` + `shift_rollup`) unchanged.
- `POST /process` — `INSERT ... SELECT` from the slice (§2.2).

`get_winding_total_query()` is deleted; the ALLOWLIST entry in `test_no_unbounded_view_readers.py` is removed, making the tripwire zero-allowlist across all three views. `vw_spinning_planning_grid` and `vw_winding_daily_reconciled` remain diff oracles only. Python `resolve_param`/`spinning_rules` stay for write-time/form resolvers and unit tests.

### 2.2 Entry→Process→Lock (clone of weaving)

- **Frozen log = `jute_prod_spinning_daily`** (existing table, grain already per frame/spell/item). Written ONLY by Process from this point on. Additions: drift-fingerprint columns (`sqc_count_avg DECIMAL(10,3)`, `sqc_count_maxdate DATE`, `winding_total_fp DECIMAL(12,3)`) and composite index `(co_id, tran_date, spell_id, machine_id, item_id)`.
- **New `jute_prod_spinning_process_lock`** — one row per `(co_id, branch_id, tran_date, spell_id)`: `is_locked`, `reprocess_needed`, `processed_by`, `processed_date_time`, `active`, audit cols. Mirror of `jute_prod_weaving_process_lock`.
- **`POST /api/spinningProd/process`** (body: `co_id`, `branch_id`, `tran_date`, `spell_id`, all validated — 400 on missing): one transaction —
  1. BLOCK: machines with doff production on the unit but no active frame mapping → 400, nothing written.
  2. WARN collectors (set-based): frames missing standards, missing act_count, zero winding total.
  3. Soft-delete prior log rows for the unit (idempotent reprocess).
  4. `INSERT INTO jute_prod_spinning_daily (<explicit cols>) SELECT ... FROM (slice)` — one statement, cost independent of frame count.
  5. Lock-header upsert; clear `reprocess_needed`.
- **`GET /api/spinningProd/process_status`**: lock state + on-read drift compare — frozen fingerprints vs fresh recompute (act_count avg, winding_total). Winding edits after lock therefore flip `reprocess_needed` without coupling winding writers to spinning (weaving D11 v1 semantics).
- **Read switch:** `planning_grid` serves frozen log rows when the unit is locked, live slice otherwise (weaving `get_weaving_log_rows_query` pattern).
- **Lock gates on ALL spinning mutation sites** — `doff_entry_create`, `doff_entry_edit`, `doff_entry_delete`, `doff_dedup_run`, `frame_map_save`, `frame_map_mapped` — via a `require_edit_if_locked`-style gate (edit permission holders may mutate; mutation on a locked unit sets `reprocess_needed`). Lesson baked in from the weaving review: map-save endpoints must NOT bypass the gate, and unit scoping includes `branch_id` everywhere (freeze, soft-delete, gates).
- **`planning_grid_save` endpoint removed** (Process replaces Save). Its FE caller goes too (§2.4).

### 2.3 Small fixes riding along

- `doff_entry_create_setup`: per-machine `_resolve_bobbin` loop → one batched rn=1 pivot query (weaving `resolve_weaving_grid_cells_batch_query` pattern).
- `get_doff_net_by_frame_query` binds `co_id` but its WHERE never uses it. Inspect live `daily_doff_tbl` schema (legacy table, not in repo migrations): if a co/tenant column exists, filter on it in the slice's `doff` derived table; if not, document the machine_id-scoping assumption inline.

### 2.4 Frontend (`vowerp3ui` spinning page only)

- Remove PlanningGrid Save button + `SPINNING_PLANNING_GRID_SAVE` wiring.
- Add Process/Lock bar cloned from the weaving page (process button, lock state, reprocess badge, WARN display), new route constants for `/process` and `/process_status`.
- Grid inputs disabled when locked.
- Winding page: zero changes.

## 3. Migrations (`dbqueries/migrations/`, target dev3 then sls)

1. `create_jute_prod_spinning_process_lock.sql` — new table + `idx_slock_unit (co_id, tran_date, spell_id)`; rollback comment.
2. `alter_jute_prod_spinning_daily_log.sql` — fingerprint columns + composite index `(co_id, tran_date, spell_id, machine_id, item_id)`; rollback comment.
3. Index audit (EXPLAIN on live dev3/sls before writing DDL): `jute_prod_spng_target_map` pivot scan (existing index leads `(co_id, ref_id, ...)` — the set-based scan filters co_id + id_type + param without ref_id; add `(co_id, id_type, param, value_role, effective_date)` only if EXPLAIN shows a scan), `daily_doff_tbl` day-scan `(doff_date, spell, mc_id)`.
4. **No backfills** — spinning has no cross-day stored carry column (no `open_jugar` analog). ORM updates paired in `src/models/`/`spinning` model files for every DDL change.

**Deploy order:** migrations before code on every tenant (dev3 first, parity-verify, then sls). Runner constraint: no semicolons inside comment prose. sls DDL is additive-only (new table + columns + indexes) — no chunked backfill needed; check `daily_doff_tbl` size before any index add there.

## 4. Verification

- **Parity harness:** `dbqueries/verify_spinning_dayslice_parity.py` — slice output vs `SELECT ... FROM vw_spinning_planning_grid` per (co_id, tran_date), numeric tolerance 0.011, exit codes 0/1/2 (clone of `verify_weaving_dayslice_parity.py`). Run on dev3 and sls before the FE switch.
- **Pytest:** slice-query construction tests, process/lock suite (BLOCK, WARN, idempotent reprocess, lock gates incl. frame_map endpoints, branch scoping, read switch), setup-batch test, `test_no_unbounded_view_readers.py` now zero-allowlist. Existing spinning tests updated where `planning_grid_save` dies; suite green.
- **Browser QA** on dev3 (portal-ui-flow-tester) after FE lands.

## 5. Out of scope

- Winding page/endpoints/reports (already day-scoped; no lock).
- Jute production reports reading any view.
- The 45 open weaving review findings (separate effort) — but their failure patterns are baked into the NEW code as guards (lock-gated map saves, branch-scoped units, validated process body).
- Phase-2 dirty-journal + scheduled batch drain (not needed under compute-on-read doctrine).
- The uncommitted weaving_entry.py / weaving_process.py working-tree changes — left untouched, never staged by this effort.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Slice formulas drift from Python semantics | Oracle view diff (byte-mirror of Python) + tolerance parity harness on real dev3/sls data |
| `daily_doff_tbl` is legacy, schema unknown in repo | Live-DB inspection step before writing the `doff` derived table + index DDL |
| Removing Save breaks a workflow someone relies on | Process supersedes it 1:1 (same table, same grain, plus lock); FE removal shipped with Process bar in the same release |
| Locked-unit corrections | Same as weaving: edit-permission holders mutate through gates, `reprocess_needed` flags, re-Process refreezes |
| sls index add on large legacy tables | Size check first; online DDL; no backfill UPDATEs anywhere in this design |
