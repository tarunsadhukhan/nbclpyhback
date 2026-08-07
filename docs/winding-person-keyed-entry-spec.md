# Winding — Person-Keyed Entry Spec (machine → EB no)

**Status:** built and verified (2026-07-30) — backend, frontend, spinning day-slice repair, and
tests are all in place; schema live on dev3 + sls. Uncommitted. See §10 for what remains.
**Supersedes:** the machine-keyed entry described in `docs/winding-production-design.md` §4
and the machine→quality reference table proposed in `docs/winding-quality-reference-spec.md` §5.
**Scope:** the Winding Production portal page (`../vowerp3ui/src/app/dashboardportal/juteProduction/winding/page.tsx`)
and its backend (`src/juteProduction/winding_entry.py`, `winding_query.py`, `winding_models.py`,
`services/winding_rules.py`), plus the winding block of the spinning day-slice
(`src/juteProduction/spinning_query.py`).

---

## 0. The one-paragraph version

Winding production stops being *machine* production and becomes *person* production. A doff is
one weighing by one winder: pick the EB no, pick (or inherit) the yarn quality, enter the gross
weight — no machine anywhere on the form. Quality is assigned per person for a date+spell on the
Quality tab (a **person → quality map**, carried forward from the previous spell), and the doff
form prefills from it. Jugar follows the same key. The person → machine relationship still exists
in `daily_ebmc_attendance`, but it is now used for other purposes (attendance, wages, machine
utilisation) and plays no part in production entry.

---

## 1. Why (evidence, live sls, 2026-07-30)

| Finding | Number | Consequence |
|---|---|---|
| EB → winding machine per date+spell | 91,164 cases with 1 machine, 12 with 2 | A person names a unique unit of work; a machine does not. |
| Winding machine → EB per date+spell | 90,582 with 1 EB, 288 with 2, 5 with 3, 3 with 5 | Machine-first entry cannot attribute a doff to an operator at all. |
| Legacy `vow-ui-1.2` winding entry | EB no typed on the form; `MACHINE_ID` back-filled in bulk afterwards | The mill has always thought of winding as person-first; the modern page was the outlier. |
| `daily_attendance.spell_id` on the newest rows | NULL for all 8 rows of 2026-07-23 (br 87) | Any attendance-driven resolver joining on `spell_id` alone silently drops the freshest day — one reason entry must not depend on attendance. |
| Winding designations | `WINDER SPOOL`, `SPOOL WINDER SWP`/`HWP`, `WINDER > 12 LBS`, `HESS WFT WINDER`, `P.W. WINDING`, `SACK WEFT WINDER`, `WINDER-COP`, `RE WINDER` | No single prefix gate is possible (unlike spinning's `spinner%`). The worker picker is therefore **not** designation-filtered — see §3.1. |
| `jute_prod_winding_doff.operator_id` | 0% populated on every tenant | Free to rename to `eb_id` rather than add a column. |

Live row counts before the change: dev3 19 doff / 8 jugar / 25 quality; sls 0 / 0 / 0. (An earlier
draft of this line said sls had "10 doff rows" — that was wrong, a misread of
`AUTO_INCREMENT=11` as a row count; sls had zero winding rows all along.) **All of these rows were
hard-deleted on 2026-07-30**, when `winding_person_keyed_entry.sql` landed: dev3's 19 doff / 8
jugar / 25 quality rows (every one, all `eb_id IS NULL`) were removed outright rather than kept as
legacy; the sls delete was a verified no-op since sls was already empty. Both tenants now carry the
new schema with zero winding rows — there is no legacy-row cohort anywhere anymore.

---

## 2. Decisions (locked with the user, 2026-07-30)

| # | Decision | Chosen |
|---|---|---|
| D1 | Worker list source | **HRMS masters**, not attendance: `hrms_ed_official_details` (emp_code) + `hrms_ed_personal_details` (name). Entry never depends on attendance being synced. |
| D2 | Quality source | **Person → quality map screen** (the Quality tab, re-keyed). Doff form prefills from it, editable inline. |
| D3 | Machine on the doff row | **Dropped entirely.** `machine_id` is never written by person-keyed entry. |
| D4 | Weight math | **One weighing = one person = one row.** `net = gross − trolly_wt − spool_wt`. No split, no `no_of_machines`. |
| D5 | Jugar key | **Person.** Jugar becomes per EB + spell + open/close. |
| D6 | Backfill of existing rows | **Deleted, not backfilled.** The existing machine-keyed rows (dev3: 19 doff / 8 jugar / 25 quality; sls: none) were hard-deleted on 2026-07-30 when the migration landed, rather than kept with `machine_id` and `eb_id = NULL` and read as legacy. No backfill and no sync were built — there is nothing left to backfill. |
| D7 | Spinning | **Document only** this pass — see §8. No spinning code changes beyond the day-slice repair in §7. |

---

## 3. Data model

Migration: `dbqueries/migrations/winding_person_keyed_entry.sql` (rollback SQL in the header).

| Table | Change |
|---|---|
| `jute_prod_winding_doff` | `operator_id` **renamed** `eb_id`; `machine_id` and `no_of_machines` become NULL-able and are no longer written; index `idx_jpwd_co_date_spell_eb (co_id, tran_date, spell_id, eb_id)`. |
| `jute_prod_winding_jugar` | `eb_id` added (NULL); `machine_id` NULL-able, no longer written; index `idx_jpwj_co_date_spell_eb_oc`. |
| `jute_prod_winding_daily_qlty` | `eb_id` added (NULL); `machine_id` NULL-able, no longer written; index `idx_jpwdq_co_date_spell_eb`. |

`eb_id` references `hrms_ed_personal_details.eb_id`. No FK is declared (consistent with the rest of
the jute-production tables). ORM in `src/juteProduction/winding_models.py` must be updated to match.

**Why reads still LEFT JOIN the worker:** there is no legacy-row cohort to tolerate any more — the
pre-change machine-keyed rows were hard-deleted on 2026-07-30 (§1, D6), and every row from here on
carries `eb_id`. The join stays LEFT, not `INNER`, purely defensively: an `eb_id` can reference an
HRMS row that is later deactivated or deleted, and a doff must never silently disappear from a grid
just because its worker's master record went away.

### 3.1 The worker list (no designation gate)

```sql
SELECT p.eb_id,
       o.emp_code,
       TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) AS worker_name,
       dm.desig AS designation,
       CONCAT(COALESCE(o.emp_code, p.eb_id), ' - ',
              TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name))) AS label
FROM hrms_ed_personal_details p
INNER JOIN hrms_ed_official_details o ON o.eb_id = p.eb_id AND o.active = 1
LEFT  JOIN designation_mst dm ON dm.designation_id = o.designation_id
WHERE p.active = 1
  AND (:branch_id IS NULL OR o.branch_id = :branch_id)
  AND (:search IS NULL OR o.emp_code LIKE :search
       OR TRIM(CONCAT_WS(' ', p.first_name, p.middle_name, p.last_name)) LIKE :search)
ORDER BY o.emp_code
LIMIT :limit
```

The `label` is **concatenated server-side** (same convention as spinning's `get_active_workers_query`)
so every screen shows the identical `"02413 - LAXMI DEBI"` string. Designation is returned for
display only and is **never** used as a filter — the mill's winding designations have no common
prefix or substring (§1), so a gate would silently hide real winders.

---

## 4. API contract (prefix `/api/windingProd`)

Handlers stay plain `def` with `Depends(get_tenant_db)` + `get_current_user_with_refresh`, and every
response is `{"data": ...}` (CLAUDE.md § Sync Handler Policy / Response Format).

### 4.1 New

| Method + path | Query / body | Returns |
|---|---|---|
| GET `/workers` | `co_id` (req), `branch_id?`, `search?`, `limit?` (default 200) | `{"data": [{eb_id, emp_code, worker_name, designation, label}]}` |
| POST `/quality_add` | `{co_id, branch_id?, tran_date, spell_id, eb_id, item_id?, no_of_spindle?}` | `{"data": {winding_daily_qlty_id}}` — adds a winder to the day's map; 400 on duplicate `(co_id, tran_date, spell_id, eb_id)` |
| DELETE `/quality_delete/{id}` | — | `{"data": {"deleted": id}}` — soft delete (`active = 0`); removes a carried-forward winder who is absent |

### 4.2 Changed

| Method + path | Change |
|---|---|
| GET `/doff_setup` | Drops `machines`. Returns `{workers, yarn_items, trollies, spools, spells}`. |
| GET `/doff_prev_state` | **Renamed** from `/doff_machine_prev_state`. Takes `eb_id` instead of `machine_id`; returns that person's latest active doff (trolly / spool / item prefill). |
| POST `/doff_create` | Body `{co_id, branch_id?, tran_date, spell_id, eb_id, trolly_id, spool_id, quality_id, gross_weight}` — `machine_ids` and `no_of_machines` are **gone**. Writes exactly one row (`machine_id`/`no_of_machines` left NULL). Returns `{"data": {winding_doff_id, net, row_gross_wt}}` (was `winding_doff_ids[]` + `net_per_mc`). |
| PUT `/doff_edit/{id}` | Same recompute on the single row; no split. |
| GET `/doff_by_date` | Optional filter `eb_id` replaces `machine_id`; rows carry `eb_id, emp_code, worker_name` instead of `mech_code, machine_name`; `no_of_machines` dropped from the payload. |
| GET `/jugar_setup` | Returns `{workers, spells}` (was `{machines, spells}`). |
| GET `/jugar_state` | **Superseded `/jugar_prev_state` (2026-08-02, §4.5).** Takes `{co_id, eb_id, tran_date, spell_id?, branch_id?}` and returns BOTH sides: `{spell_id, opening: {weight, winding_jugar_id, source}, closing: {…}}`. |
| POST `/jugar_save` | Body takes `eb_id` and `{opening?, closing?}` (at least one). **UPSERTS** each given side — no duplicate guard, a stored row is updated. Bands differ per side: opening `0 <= w <= JUGAR_MAX`, closing `0 < w <= JUGAR_MAX`. Returns `{"data": {opening?: {winding_jugar_id, weight}, closing?: {…}}}`. |
| GET `/jugar_by_date` | Worker columns replace machine columns. |
| GET `/quality_setup` | Auto-seeds one row **per person carried forward from the previous spell** instead of one row per winding machine. Returns `{rows, yarn_items, workers}` — `workers` feeds the "Add winder" picker. With no prior rows it seeds nothing (empty map, user adds winders). |
| PUT `/quality_save/{id}` | Body unchanged (`item_id`, `no_of_spindle`); duplicate guard re-keyed to `eb_id`. |
| GET `/quality_by_date` | Worker columns replace machine columns. |

### 4.2a Jugar as one two-field entry (2026-08-02)

The Opening/Closing **selector is gone**. One winder + spell = one entry with two weight fields,
both prefilled and both posted back. Per side the precedence is:

1. `saved` — the row already stored for this date/spell/winder. **A manual entry always wins.**
2. `carry` — the previous spell's CLOSING in **spell-sequence** order: an earlier
   `spell_mst.starting_time` on the same date, else the last spell of an earlier date, skipping
   spells the winder did not work. (The old lookup was `tran_date <` only, so A → B → C within a
   day never carried.) The closing field seeds from the same value as a starting point.
3. `carry_open` — opening side only: the winder's previous OPENING when no closing was ever
   recorded (legacy `OE`), so an openings-only mill still gets a number.
4. `none` — 0.

Because the carried opening is **posted back and persisted**, it now counts in reconciliation,
which reads stored rows only — previously a carry the operator never saved silently scored 0.

**Weight bands differ per side** (2026-08-02): opening `0 <= w <= JUGAR_MAX`, closing
`0 < w <= JUGAR_MAX`. A spell can genuinely start with an empty spindle, and rejecting 0 there
would force the operator to invent carryover — which inflates that spell's reconciled kg, since
production subtracts the opening. "Nothing left at the end" needs no such escape hatch: it is
expressed by leaving the closing blank. `jugar_update` gates on the stored row's own
`open_close`, so both write paths apply the identical band.

### 4.2b Branch is the scope key, not co_id (2026-08-02)

**Every winding read keys on `branch_id`, never `co_id`** — a branch belongs to exactly one
company, so the branch is the stricter key and `co_id` adds nothing. Applies across the module:
the jugar state / carry / upsert lookups, `jugar_by_date`, `doff_prev_state`, `doff_by_date`, the
whole quality map (`quality_exists`, the carry-forward seed source + its idempotency guard,
`quality_by_date`, the duplicate guard), `get_winding_reconciliation_query`, both winding reports,
and the jugar blocks of `spinning_day_slice_sql()` **and `get_spinning_drift_query()` (which must
stay equivalent to the slice, else every locked unit reads as permanently drifted)**. `co_id` is
still written on INSERT; it just no longer filters anywhere. One branch's leftover can therefore
never adjust another branch's doff for an eb_id present in both.

Consequences:

- `branch_id` is **required** on `doff_by_date`, `jugar_by_date`, `quality_by_date`,
  `quality_setup`, `winding_spell_report` and `winding_quality_wise` (400 when absent — no more
  implicit all-branch read). `jugar_state` and `doff_prev_state` derive it from the winder when the
  caller omits it. `quality_setup` still takes `co_id` as well: the seeded rows write it, and the
  yarn picker scopes items by `item_grp_mst.co_id`.
- `_worker_branch` now 400s when the winder's HRMS record carries **no branch**
  (`WORKER_NO_BRANCH_MSG`): a branchless row would be invisible to every winding read. Rejecting at
  the write boundary is what lets the queries use a plain `branch_id = :branch_id`.
- **No backfill was needed.** Verified 2026-08-02 across all row states (incl. soft-deleted):
  dev3's winding tables are empty; sls holds 4 doff / 1 jugar / 7 quality rows, every one
  branch-stamped; `daily_doff_tbl` and `daily_doff_frames_winding` likewise carry zero NULL
  branches on both tenants. Re-checked against the tenant's own mapping rule
  (**sls: co 2 → branch 29, co 1 → branch 4, co 106 → branch 87**) — every sls winding row already
  agrees with it (no co 1 winding rows exist), so no UPDATE was run.

### 4.3 Unchanged

`DELETE /doff_delete/{id}`, `PUT /jugar_update/{id}` (id-keyed, kept for direct row edits), and the
spell/trolly/spool/yarn lookups.
Spell resolution keeps using `spinning_entry._resolve_spell` (spell_id preferred, code fallback
branch-scoped) — winding tables store `spell_id`, never the code.

### 4.4 Branch derivation

`doff_create` / `jugar_save` / `quality_add` previously derived `branch_id` from the machine's
department. They now derive it from the worker: `hrms_ed_official_details.branch_id` for the given
`eb_id`. `derive_branch_for_machine_query` is replaced by `derive_branch_for_worker_query`.

---

## 5. Business rules (`services/winding_rules.py`)

```
net           = round(gross − trolly_wt − spool_wt, 3)      # save gate: net > 0
row_gross_wt  = round(net + trolly_wt + spool_wt, 3)
valid         = WINDING_NET_MIN <= net <= WINDING_NET_MAX   # 1..500 kg
```

`compute_winding_net` loses its `nomc` argument; `compute_winding_net_per_mc` is **deleted** (there
is no split). `compute_winding_row_gross_wt` keeps its signature but takes the single net.
`production_qty` on the row is the net; `gross_input_wt` is the weighed gross.

`reconcile_production(sum_production, opening, closing)` is unchanged in form — only its grouping
key moves from machine to person.

The frontend mirror `../vowerp3ui/.../winding/utils/windingCalc.ts` must be changed in lockstep
(preview only; the server value is authoritative).

---

## 6. Reconciliation

`get_winding_reconciliation_query` re-keys from `(tran_date, spell_id, machine_id)` to
`(tran_date, spell_id, eb_id)`:

```
production_kg = SUM(doff.production_qty) − opening_jugar + closing_jugar
              per (co_id, tran_date, spell_id, eb_id)
```

- The jugar sub-select groups by and joins on `eb_id` (was `machine_id`).
- The yarn is taken from the doff row itself, falling back to the person→quality map:
  `COALESCE(wd.item_id, qmap.item_id)` where `qmap` is `jute_prod_winding_daily_qlty` keyed on
  `(co_id, tran_date, spell_id, eb_id)`. Previously the item came only from the machine map and the
  doff row's own `item_id` was ignored.
- Worker identity columns (`emp_code`, `worker_name`) replace `mech_code` / `machine_name`.
- Shift bucket stays `LEFT(spell_code, 1)`.

---

## 7. Spinning day-slice — the read that must move with it

`spinning_query.py` embeds the winding reconciliation twice (the live day-slice
`spinning_day_slice_sql()` around lines 914-948, and the drift probe around lines 1210-1240). Both
currently do:

```sql
FROM jute_prod_winding_doff wd
INNER JOIN machine_mst wm  ON wm.machine_id = wd.machine_id
INNER JOIN dept_mst    wdp ON wdp.dept_id   = wm.dept_id
INNER JOIN branch_mst  wbm ON wbm.branch_id = wdp.branch_id
...
GROUP BY wbm.co_id, wdp.branch_id, wd.spell_id, wd.machine_id, wd.item_id
```

With `machine_id` no longer written those three `INNER JOIN`s drop every new row, `winding_total`
silently becomes 0, and spinning's `eff_winding` collapses to 0 with no error. **This is the highest-
risk part of the change.** Fix:

- Delete the `machine_mst` / `dept_mst` / `branch_mst` chain. `jute_prod_winding_doff` already
  carries `co_id` and `branch_id` — filter on `wd.co_id = :co_id` and `wd.branch_id` directly.
- Group by `wd.eb_id` in place of `wd.machine_id`.
- Join the jugar open/close sub-selects on `eb_id`.
- The outer rollup (`GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)` → joined to the frame's
  `item_id` and shift bucket) is unchanged, so `winding_total` keeps its meaning.

`src/test/test_spinning_dayslice.py:66` asserts `jute_prod_winding_doff` appears in the SQL; extend
it to assert the machine joins are gone and `eb_id` is present, so a regression is caught.

---

## 8. Spinning implications — documented, not built (D7)

The user's stated direction is that **quality becomes the main axis** for spinning too. Recording
the shape of that work without doing it:

- Spinning is machine-first by physical reality (a frame is fixed; the spinner is assigned to it) —
  the inverse of winding, where the winder moves. `daily_ebmc_attendance` fan-out confirms it: for
  spinning, machine → 1 eb resolves cleanly, which is why `POST /doff_sync` stamps `eb_id` **from**
  the machine. Flipping spinning to person-first is therefore not a mirror of this change.
- What "quality first" would mean concretely: `daily_doff_frames_winding` (`spg_wdg='S'`) is a
  frame→quality map; the `Mapped` button back-stamps `item_id` onto `daily_doff_tbl`. A quality-first
  model would make the map's target the *doff*, not the frame, and would need `daily_doff_tbl.quality_id`
  (currently always NULL) to stop being dead.
- Blast radius if attempted: `jute_prod_spinning_daily` (frozen at Process), the process lock, the
  day-slice, drift detection, and the planning grid all key on `(machine, item)`. None of them can be
  re-keyed without a freeze/refreeze plan.

**Open questions for that future pass** — (a) does spinning keep the frame as the entry key with
quality merely authoritative, or does the spinner become the key? (b) what happens to already-frozen
`jute_prod_spinning_daily` rows? (c) does `eff_doff` stay per-machine?

---

## 9. Test checklist

Backend (`src/test/test_winding_entry.py`, `test_winding_rules.py`):

- `net = gross − trolly − spool`; gate rejects `net <= 0` (400) and out-of-range net (400).
- `doff_create` writes exactly one row with `machine_id IS NULL`, `no_of_machines IS NULL`, `eb_id` set.
- `doff_create` with an unknown `eb_id` → 400; missing `eb_id` → 422 (pydantic).
- Branch derived from the worker when the body omits it.
- `doff_by_date` returns `emp_code` / `worker_name`, and never drops a row whose `eb_id` fails to
  resolve to an active HRMS worker (LEFT JOIN defensiveness) — not a legacy-row scenario, since no
  machine-keyed rows remain in dev3 or sls (all deleted 2026-07-30).
- `quality_setup` seeds one row per carried-forward person, is idempotent on re-run (NOT EXISTS
  guard on `eb_id`), and seeds nothing when there is no prior spell.
- `quality_add` duplicate on `(co, date, spell, eb)` → 400; `quality_delete` soft-deletes.
- `jugar_save` duplicate guard on `(co, date, spell, eb, open_close)` → 400.
- Reconciliation groups per person and applies opening/closing from the same person.
- `test_spinning_dayslice.py` — winding block references `eb_id` and no longer joins `machine_mst`.

Browser (dev3, per `.claude/test-credentials.md`): the worker picker must be populated on dev3 even
though dev3 has **zero winding attendance and zero winding designations** — this is exactly why the
list comes from HRMS masters (D1) rather than attendance.

---

## 10. Rollout order

1. `winding_person_keyed_entry.sql` is **already applied to dev3 and sls** (2026-07-30) — both
   tenants carry the new schema with zero winding rows (every pre-change row hard-deleted). Any
   tenant other than dev3/sls still needs the migration applied **before** the code deploy reaches
   it — the code stops writing `machine_id`, which is `NOT NULL` until the migration lands there.
2. Backend + ORM.
3. Frontend.
4. Spinning day-slice fix (§7) ships in the **same** deploy as the backend — a gap between them
   zeroes `eff_winding`.

---

## 11. References

- `docs/winding-production-design.md` — the machine-keyed original (§4 superseded here).
- `docs/winding-quality-reference-spec.md` — the earlier machine→quality proposal (§5 superseded here).
- `docs/spinning-doff-attendance-quality-spec.md` — spinning's attendance/quality pipeline, the
  reference for §8.
- Legacy: `c:\code\awscc-github\vow-ui-1.2\src\views\AppData\AppDataWindingDoffEntry.js` (EB-first
  form), `vow_backend_2.0` `WindingDoffEntryDAO.updateYarnIdInDoff` (the batch machine back-fill this
  design deliberately drops).
