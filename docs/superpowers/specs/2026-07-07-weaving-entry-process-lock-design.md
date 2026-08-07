# Weaving Entry → Process → Lock — Design Spec

**Date:** 2026-07-07
**Status:** Approved (design); pending implementation plan
**Repos:** `vowerp3be` (backend), `vowerp3ui` (frontend)
**Branch:** `claude/gracious-ptolemy-hmnq72`
**Module:** Jute Production → Weaving (`src/juteProduction/weaving_*`, FE `src/app/dashboardportal/juteProduction/weaving/`)

---

## 1. Motivation

Today weaving **blocks entry until the Loom→Quality map is done**, and every computed value is derived **on read** by `weaving_day_slice_sql` (`vw_weaving_daily` is oracle/reference only). Two problems:

1. Operators cannot record cuts / closing-jugar for a loom until a quality is mapped — but cut length (hence jugar) genuinely cannot be known before mapping, so the **calculation** should not gate the **input**.
2. There is no point-in-time freeze or lock. Standards (`jute_prod_weaving_target_map`, last-date-effective) and SQC picks (`jute_sqc_weaving_pick`, append-only) both change retroactively, so reported numbers drift silently and nothing marks a day "final."

**Goal:** split **capture** (raw input, always allowed) from **processing** (validate all inputs → compute → freeze into a log → lock), with re-processing/mutation of a locked unit gated by **Edit** permission, and a **reprocess flag** raised when SQC changes after processing.

---

## 2. Current-state facts (evidence)

| Fact | Evidence |
|---|---|
| Storage = inputs only + stored `open_jugar`; everything else computed on read | `weaving_query.py:736-958` (`weaving_day_slice_sql`), `weaving_models.py:195-242` |
| `vw_weaving_daily` is oracle-only; no live router SELECTs it | guarded by `test_no_unbounded_view_readers.py` |
| Entry read `entry_inputs_by_date` is already inputs-only | `weaving_query.py:1034-1081`, `weaving_entry.py:608-649` |
| No process/lock/status column on any `jute_prod_*` daily table | grep-confirmed; `weaving_models.py:222-242` |
| Only lock precedent in codebase = accounting period lock | `acc_period_lock` columns `is_locked`/`locked_by`/`locked_date_time` at `accounting/models.py:161-172`; enforced at `voucher_service.py:60-78` |
| Permission = ordinal `access_type_id` on `role_menu_map`: 1 Read, 2 Print, 3 Write, 4 Edit | `menu.py:71-73,258-296`; FE `sidebarContext.tsx:176-226`, `portalPermissions.ts` |
| Permission enforced only on menu-permission endpoints + client — **NOT** on data-mutation endpoints | `menu.py:258-296`; business routers do not re-check |
| Attendance = 2 tables: `daily_ebmc_attendance(daily_atten_id, eb_id, mc_id)` → `daily_attendance(eb_id, attendance_date, spell, spell_id, branch_id, is_active)`; no ORM (raw SQL); no `co_id` on header | `add_daily_attendance_spell_id.sql`; spinning `operator_stamp_query()` `spinning_query.py:411-441` |
| Weaving `eb_id` always written NULL ("resolved via attendance later Q7") | `weaving_entry.py:791,1201,1693`, `weaving_models.py:231` |
| Weaving SQC = `jute_sqc_weaving_pick` captures **picks + width only — NO oz/yds** | `weaving_sqc_query.py:26-61`; columns `entry_date, weaving_quality_id, machine_id, width, picks` |
| `std_picks` = exact-day `AVG(picks)` (R-08-21); `act_picks` = last-date `AVG(picks)` | `weaving_query.py:868-872,923-941` |
| oz/yds is a **static quality-master** attribute, not SQC | `jute_prod_weaving_quality.ozs_yds/std_ozs_yds`, `weaving_models.py:59-60`; kg formula `weaving_query.py:815,820-822` |
| **Parity trap:** `services/weaving_standards.py` resolves `std_picks` from the target map (qid/standard/picks); the SQL slice resolves it from SQC exact-day AVG — they diverge | `services/weaving_standards.py:220-222` vs `weaving_query.py:923-928` |
| `open_jugar` is a stored, write-time-resolved carry-forward with same-day + prior-day chain repair | `weaving_query.py:693-733,1189-1237`; `backfill_weaving_open_jugar.sql` (set-based LAG) |
| **Stoppage** = `jute_prod_stoppage_hours` event log, grain `(machine, tran_date, spell_id)` **non-unique** (`stoppage_hours`, `reason_code`); entered on its own standalone page `/stoppageProd` (FE `stoppageHours/`), NOT the weaving page. Already consumed by the slice `stp = SUM(stoppage_hours)` → `working_hours = GREATEST(0, spell_hours − stoppage)` | `stoppage_models.py:39-63`, `stoppage_entry.py`; slice `weaving_query.py:942-947,876-877` |

---

## 3. Resolved decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Storage model | **Approach A** — separate frozen LOG table + lock header. (Rejected B = pollute lean daily table; C = lock over live recompute, can't detect drift.) |
| D2 | Process/lock grain | Per `(co_id, branch_id, tran_date, spell_id)`; frozen rows per `(…, machine_id, weaving_quality_id)` |
| D3 | SQC aggregation | Picks aggregated **full-day per quality** (`entry_date = tran_date`), not per-spell |
| D4 | SQC drift watches | `AVG(picks)`; oz/yds formula unchanged (quality master) |
| D5 | `eb_id` | **WARN-only v1** — best-effort spinning-stamp resolve, never blocks |
| D6 | Missing standards / SQC picks | **WARN**, process proceeds (`COALESCE → 0`) |
| D7 | Quality unmapped | **BLOCK** the process |
| D8 | Adjustment (`less_production`) null | Silent 0 (already `COALESCE(…,0)`) |
| D8b | **Stoppage (input #6)** | Optional; silent-default-0 (no stoppage = ran full spell). Entered on the existing standalone `/stoppageProd` page; weaving **consumes** it via `working_hours` (already frozen into the log). Also a **drift source** for reprocess (D11) |
| D9 | Lock unit | Header table per `(date, spell)` |
| D10 | Entry key | Drop quality → `(co, date, spell, machine)`; `weaving_quality_id` nullable |
| D11 | Reprocess flag | On-read compare in v1; stamp-on-SQC-save = fast-follow |
| D12 | Process execution | **Set-based SQL** (`INSERT … SELECT`), synchronous |

---

## 4. Data model

### 4.1 `jute_prod_weaving_daily` (modify)
- `weaving_quality_id` → **NULLABLE** (entry allowed before mapping).
- Entry app-uniqueness key → `(co_id, tran_date, spell_id, machine_id, active=1)`; quality no longer in the key.
- No new columns; still inputs (`cuts, close_jugar, less_production`) + stored `open_jugar`.
- Migration: `ALTER TABLE jute_prod_weaving_daily MODIFY weaving_quality_id INT NULL;` (rollback comment inline).

### 4.2 `jute_prod_weaving_log` (new — frozen snapshot)
Grain: `(co_id, branch_id, tran_date, spell_id, machine_id, weaving_quality_id)`. Columns = the day-slice outer SELECT set (`weaving_query.py:802-822`), materialized:

`weaving_log_id` (PK), `weaving_daily_id` (FK source row), `co_id`, `branch_id`, `tran_date`, `spell_id`, `spell_code`, `shift_bucket`, `spell_rank`, `machine_id`, `mech_code`, `machine_name`, `line_no`, `weaving_quality_id`, `item_id`, `item_code`, `item_name`, `weaving_quality_code`, `weaving_quality_name`, `is_composite`, `eb_id`, `beam_no`, `cuts`, `close_jugar`, `less_production`, `open_jugar`, `jugar`, `finished_length`, `ozs_yds`, `std_ozs_yds`, `no_of_jugar_per_cut`, `std_speed`, `act_speed`, `std_picks`, `act_picks`, `std_eff`, `target_eff`, `eff_speed`, `eff_picks`, `working_hours`, `production_yds`, `production_kg`, `production_mt`, `std_prod_yds`, `target_prod_yds`, `efficiency`, `std_prod_kg`, `target_kg`,
— drift fingerprint — `sqc_pick_avg`, `sqc_pick_maxdate` (per-`(co,quality)` value, repeated across that quality's machine rows — redundant but fine for the §8 on-read compare),
— audit — `active`, `updated_by`, `updated_date_time`.

- Index: `(co_id, tran_date, spell_id)`.
- Reprocess = soft-delete existing active rows for the unit + `INSERT … SELECT` fresh (idempotent).

### 4.3 `jute_prod_weaving_process_lock` (new — lock header)
One row per `(co_id, branch_id, tran_date, spell_id)`: `weaving_process_lock_id` (PK), `is_locked`, `processed_by`, `processed_date_time`, `reprocess_needed`, `active`, `updated_by`, `updated_date_time`. Precedent: `acc_period_lock`.

### 4.4 ORM
Add `WeavingLog` + `WeavingProcessLock` to `weaving_models.py`. `daily_attendance` / `daily_ebmc_attendance` stay raw-SQL (no ORM — consistent with existing usage).

---

## 5. Entry tab — capture (always allowed)

### Backend (`weaving_entry.py`)
- `entry_create` / `entry_edit` / `planning_grid_save`:
  - Remove the `NO_MAPPED_QUALITY_MSG` 400 block. Resolve quality from the active map if present, else store **NULL**.
  - Run `close_jugar` range validation only when a quality is known (jpc available); skip otherwise.
  - Upsert by `(co, date, spell, machine)`.
  - `open_jugar` chain sync runs only when quality is set; deferred to Process when quality is NULL.
  - **If the `(date, spell)` is locked** and the caller lacks Edit → 403 (see §7).

### Frontend (`WeavingEntryGrid.tsx`, `utils/weavingCalc.ts`)
- Remove the Total-Jugar preview column and `totalJugar()` usage.
- Enable `cuts` / `close_jugar` inputs for **all** looms (drop `disabled={!mapped}`); Save always enabled.
- Quality stays a read-only display (blank when unmapped).

---

## 6. Process engine (new)

`POST /api/weavingProd/process` — body `{co_id, branch_id, tran_date, spell}`. Sync `def` handler, `get_tenant_db`. **All steps set-based, one transaction:**

1. Resolve `spell_id` (branch-scoped).
2. **BLOCK check** — produced looms (daily rows for date+spell with input) `LEFT JOIN` active quality map `WHERE quality IS NULL`. If any → `400` with the unmapped-loom list; nothing written.
3. **WARN collectors** (set-based `LEFT JOIN … IS NULL`): `no_standard`, `no_picks`, `no_worker`.
4. Resolve `open_jugar` for the unit's rows. **⚠ The chain is cross-spell AND cross-day** — partition `(co_id, machine_id, weaving_quality_id)` ordered by `(tran_date, spell_rank, weaving_daily_id)`, over a frame that **includes prior history** (the `backfill_weaving_open_jugar.sql` LAG form, NOT a window reset at the `(date,spell)` edge). Simplest correct path: reuse the existing per-row probe `resolve_weaving_open_jugar_for_row_query` (`weaving_query.py:1189+`) for each of the unit's rows whose stored `open_jugar` is stale (quality was NULL at entry). A `LAG … PARTITION BY (tran_date, spell_id)` would drop the carry-in from the prior spell/day and freeze the first row of each chain wrong — and the slice reads the *stored* `open_jugar`, so that error flows straight into the frozen log.
5. Soft-delete existing active `jute_prod_weaving_log` rows for `(co, date, spell)` (reprocess idempotency).
6. **`INSERT INTO jute_prod_weaving_log (<explicit column list>) SELECT … FROM (weaving_day_slice_sql :co,:date,:spell)`** — freeze all looms in one statement. Name columns **explicitly** (the slice emits `spell_rank` too; no positional / `SELECT *` insert or every column after `shift_bucket` misaligns). **Compute strictly from the SQL slice, never `services/weaving_standards.py`** (parity trap).
7. `UPDATE jute_prod_weaving_log … JOIN` spinning-style attendance stamp → `eb_id` (best-effort).
8. Freeze SQC fingerprint per quality (`sqc_pick_avg`, `sqc_pick_maxdate`) into the log rows.
9. Upsert `jute_prod_weaving_process_lock`: `is_locked=1`, `processed_by`, `processed_date_time`, `reprocess_needed=0`.

Response: `{processed, warnings: {no_worker: [...], no_standard: [...], no_picks: [...]}}`.

**Stoppage needs no dedicated step** — it enters the slice as the `stp` derived table (`SUM(stoppage_hours)` → `working_hours`) inside step 6's `INSERT … SELECT`, so it is frozen automatically. Stoppage is entered on the standalone `/stoppageProd` page; the weaving lock does **not** hard-block that page (cross-module) — a post-lock stoppage (or SQC) edit instead raises `reprocess_needed` (§8). Only the weaving-page mutations are permission-locked (§7).

**Scale:** cost is independent of loom count — ~5 set-based statements, one txn, whether 5 looms or 5,000. `ponytail:` synchronous until proven necessary; if a single unit ever exceeds a few thousand rows and the request times out, move Process to a background task then (not before).

---

## 7. Lock + permissions

- **New server-side dependency** (must be built — data endpoints don't check today): resolve the current user's `access_type_id` for the weaving menu (via `user_role_map → role_menu_map`, mirroring `menu.py:258-296`). E.g. `require_menu_access(request, menu_path, min_level)`.
- When `(date, spell)` is **locked**: `entry_create/edit/delete`, `planning_grid_save`, `adjustment_save`, **and re-Process** require level **≥ 4 (Edit)**; Write-only (3) → `403`. When unlocked: level ≥ 3 (Write), as today.
- FE gates the Process-rerun + edit affordances by `hasMenuAccess(path, 'edit')` when locked; server is the source of truth.

---

## 8. Reprocess detection

Two drift sources feed the frozen numbers after processing: **SQC picks** (append-only → `std/act_picks`) and **stoppage** (event log → `working_hours`). Both are watched.

- At process time, freeze the per-quality `AVG(picks)` + `MAX(entry_date)` into the **log rows** (`sqc_pick_avg`, `sqc_pick_maxdate`). Stoppage needs **no new fingerprint column** — the net `working_hours` is already a frozen log column, so comparing frozen vs recomputed `working_hours` catches stoppage adds/edits (and any spell-hours master change) directly. The unit-level `reprocess_needed` flag lives on the **lock header**.
- Check endpoint `GET /api/weavingProd/process_status` `{co, branch, date, spell}` → recompute current `AVG(picks)` **and** `working_hours` for the unit; if either differs from frozen → `reprocess_needed = 1`. FE shows "SQC / stoppage changed since processing — reprocess?" beside the Process button. (Robust alternative: recompute the whole day-slice for the unit and diff the drift-sensitive columns — catches standards / quality-master edits too; heavier, deferred.)
- **Fast-follow:** stamp `reprocess_needed` on weaving SQC pick save **and stoppage save** when processed weaving rows exist for that date/(quality|machine).

---

## 9. Reads / reports

- `planning_grid` + entries read: if `(date, spell)` is **locked** → serve frozen `jute_prod_weaving_log` rows; else live day-slice preview.
- Preserve the `planning_grid` 504 tripwire (`weaving_query.py:1168`) — keep `co_id`/`tran_date` filters inside the derived table when switching live-vs-log reads.
- No existing weaving report to migrate; the computed `entries_by_date` endpoint is FE-dead today.

---

## 10. Risks / edge cases

- **open_jugar chain across days:** locking day N feeds day N+1's `open_jugar`. Editing a locked row (Edit user) must re-sync the successor and mark affected downstream processed units `reprocess_needed`.
- **Exact-day `std_picks` no-fallback:** processing before the day's SQC reading is entered freezes `efficiency = 0`; the reprocess flag recovers it (expected behavior).
- **Parity trap:** compute the log only from `weaving_day_slice_sql`, never the Python resolvers.
- **Sparse attendance:** `daily_ebmc_attendance` may be thinly populated → the `no_worker` WARN list may be large early. Acceptable (eb_id non-load-bearing for the math).
- **Concurrency:** two users processing the same unit — lock-header upsert + txn; last write wins, idempotent (soft-delete + re-insert).

---

## 11. Out of scope (v1)

- Weaving eb attendance stamp as a **hard** input (WARN + best-effort only now).
- Per-day actual oz/yds SQC capture (oz/yds stays a quality-master attribute).
- Background/async processing (synchronous until proven necessary).
- Stamp-on-SQC-save / stamp-on-stoppage-save reprocess trigger (on-read compare in v1).
- **Stoppage entry UI on the weaving page** — consume-only; operators enter stoppage on the existing standalone `/stoppageProd` page (user decision: no UI change to the weaving page).

---

## 12. Testing

- Entry allowed with no quality map (unit).
- Process **BLOCK** on any unmapped produced loom; WARN lists correct.
- **Parity:** log rows equal `weaving_day_slice_sql` output for a fixture `(co, date, spell)`.
- Lock: Write-user `403` on locked mutation; Edit-user allowed.
- Reprocess flag flips when a pick is added post-process.
- Set-based process: bounded query count (assert no per-row loop).
