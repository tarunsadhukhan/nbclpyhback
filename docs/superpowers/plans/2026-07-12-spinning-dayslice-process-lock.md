# Spinning Day-Slice + Process→Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill the spinning planning grid's ~11-queries-per-row N+1 and its unbounded `vw_winding_daily_reconciled` reads with one day-sliced SQL, and clone weaving's Entry→Process→Lock so `jute_prod_spinning_daily` becomes a frozen posting table written only by a set-based Process.

**Architecture:** New `spinning_day_slice_sql()` fragment (weaving `weaving_day_slice_sql` pattern) drives both the live `GET /planning_grid` read and the `POST /process` `INSERT...SELECT` freeze. New `jute_prod_spinning_process_lock` header locks a (co, branch, date, spell) unit; all spinning mutations gate on it; drift (doff/count/winding edits after lock) is detected on read and flips `reprocess_needed`. `planning_grid_save` and the FE Save button are removed.

**Tech Stack:** FastAPI (sync `def` handlers), SQLAlchemy `text()` raw SQL, MySQL 8 (window functions), pytest + TestClient + unittest.mock, Next.js FE (`../vowerp3ui`).

**Spec:** `docs/superpowers/specs/2026-07-12-spinning-dayslice-process-lock-design.md`

## Global Constraints

- Handlers are plain `def`, never `async def`; JSON bodies via Pydantic models (existing pattern).
- All responses `{"data": ...}`; SQL NULL = Python `None`; named binds match exactly; params type-cast.
- DB dependency: `Depends(get_tenant_db)` (Portal business route).
- Doctrine: "views may format, never accumulate" — no app code may read `vw_winding_daily_reconciled` / `vw_spinning_planning_grid` / `vw_weaving_daily` (`src/test/test_no_unbounded_view_readers.py` enforces; this plan removes its last ALLOWLIST entry).
- Migration runner splits on `;` — NO semicolons inside SQL comment prose.
- Deploy order: migrations BEFORE code on every tenant (dev3 first, parity-verify, then sls).
- Do NOT stage or commit the pre-existing uncommitted changes in `weaving_entry.py`, `weaving_process.py`, `weaving_query.py`, or `src/test/test_weaving_*.py` — another effort owns them. `git add` explicit paths only, never `git add -A`.
- Known column facts: `jute_prod_spinning_daily.item_id` (renamed from `yarn_quality_id` by `rename_yarn_quality_id_to_item_id.sql`); `daily_doff_tbl` stores spell_id in `spell`, machine_id in `mc_id`, active is `(active = 1 OR active IS NULL)`; `item_mst` has NO `co_id` (scope via `item_grp_mst.co_id`); `daily_doff_tbl` is legacy and has NO reliable co scoping — keep existing machine-scoped semantics.
- Constants (from `src/juteProduction/constants.py`): `SPINNING_MACHINE_TYPE_NAME = "Spinning"`, `ID_TYPE_MC = "mcid"`, `ID_TYPE_QLTY = "qid"`, `VALUE_ROLE_STANDARD/TARGET/ACTUAL = "standard"/"target"/"actual"`, `PARAM_SPEED/TPI/EFF/SPINDLES/BOBBIN_WT = "speed"/"tpi"/"eff"/"spindles"/"bobbin_wt"`, `SPELL_MINUTES = {"A1": 300, "A2": 180}`.

---

### Task 1: Migrations + ORM (lock table, unit index)

**Files:**
- Create: `dbqueries/migrations/create_jute_prod_spinning_process_lock.sql`
- Create: `dbqueries/migrations/add_spinning_daily_unit_index.sql`
- Modify: `src/juteProduction/spinning_models.py` (add lock model; add `__table_args__` unit index to `JuteProdSpinningDaily` at line ~61)

**Interfaces:**
- Produces: table `jute_prod_spinning_process_lock` (columns exactly as DDL below) and index `idx_jpsd_unit` — consumed by Tasks 3, 4, 6.

- [ ] **Step 1: Write `create_jute_prod_spinning_process_lock.sql`**

```sql
-- Migration: jute_prod_spinning_process_lock — one lock header per (co, branch, date, spell).
-- Mirror of jute_prod_weaving_process_lock (see create_jute_prod_weaving_process_lock.sql).
-- Rollback: DROP TABLE jute_prod_spinning_process_lock;
CREATE TABLE jute_prod_spinning_process_lock (
  spinning_process_lock_id INT PRIMARY KEY AUTO_INCREMENT,
  co_id                INT NOT NULL,
  branch_id            INT NULL,
  tran_date            DATE NOT NULL,
  spell_id             INT NOT NULL,
  is_locked            TINYINT NOT NULL DEFAULT 1,
  reprocess_needed     TINYINT NOT NULL DEFAULT 0,
  processed_by         INT NULL,
  processed_date_time  TIMESTAMP NULL,
  active               TINYINT NOT NULL DEFAULT 1,
  updated_by           INT NULL,
  updated_date_time    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_slock_unit (co_id, tran_date, spell_id)
);
```

- [ ] **Step 2: Write `add_spinning_daily_unit_index.sql`**

```sql
-- Migration: composite unit index on jute_prod_spinning_daily.
-- Serves the Process freeze soft-delete, the frozen-read unit scan, and the drift
-- compare — the old per-column singles (idx_jpsd_co_date etc) cannot serve a
-- 5-column unit lookup efficiently.
-- Rollback: ALTER TABLE jute_prod_spinning_daily DROP INDEX idx_jpsd_unit;
ALTER TABLE jute_prod_spinning_daily
  ADD INDEX idx_jpsd_unit (co_id, tran_date, spell_id, machine_id, item_id);
```

- [ ] **Step 3: Add ORM model + index in `spinning_models.py`**

Append after `JuteProdSpinningDaily` (import `Index` from sqlalchemy at top if missing; the file already imports `Column, Integer, Date, DECIMAL, TIMESTAMP, func`):

```python
class JuteProdSpinningProcessLock(Base):
    """One lock header per (co, branch, tran_date, spell) spinning unit.

    Mirror of jute_prod_weaving_process_lock. is_locked gates mutations via
    spinning_lock.require_edit_if_locked; reprocess_needed is raised by
    flag_reprocess_if_locked and by on-read drift detection (process_status)."""

    __tablename__ = "jute_prod_spinning_process_lock"

    spinning_process_lock_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False)
    spell_id = Column(Integer, nullable=False)
    is_locked = Column(Integer, nullable=False, default=1, server_default="1")
    reprocess_needed = Column(Integer, nullable=False, default=0, server_default="0")
    processed_by = Column(Integer, nullable=True)
    processed_date_time = Column(TIMESTAMP, nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    __table_args__ = (Index("idx_slock_unit", "co_id", "tran_date", "spell_id"),)
```

And on `JuteProdSpinningDaily` add (after `updated_date_time`):

```python
    __table_args__ = (
        Index("idx_jpsd_unit", "co_id", "tran_date", "spell_id", "machine_id", "item_id"),
    )
```

- [ ] **Step 4: Sanity-run model import**

Run: `cd c:/code/vowerp3be && .venv/Scripts/python -c "from src.juteProduction import spinning_models; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add dbqueries/migrations/create_jute_prod_spinning_process_lock.sql dbqueries/migrations/add_spinning_daily_unit_index.sql src/juteProduction/spinning_models.py
git commit -m "feat(spinning): schema for process lock + unit index (migrations + ORM)"
```

---

### Task 2: Apply migrations to dev3

**Files:** none (DB operation). Read credentials from `env/database.env`.

- [ ] **Step 1: Apply both migrations to dev3 via pymysql**

Run (adapt HOST/USER/PASS from `env/database.env`):

```bash
cd c:/code/vowerp3be && .venv/Scripts/python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='dev3')
cur = conn.cursor()
for f in ['dbqueries/migrations/create_jute_prod_spinning_process_lock.sql',
          'dbqueries/migrations/add_spinning_daily_unit_index.sql']:
    for stmt in open(f).read().split(';'):
        s = '\n'.join(l for l in stmt.splitlines() if not l.strip().startswith('--')).strip()
        if s:
            cur.execute(s)
conn.commit()
cur.execute('SHOW INDEX FROM jute_prod_spinning_daily')
print([r[2] for r in cur.fetchall()])
cur.execute('SHOW TABLES LIKE \"jute_prod_spinning_process_lock\"')
print(cur.fetchall())
conn.close()
"
```

Expected: index list contains `idx_jpsd_unit`; tables result shows `jute_prod_spinning_process_lock`.

- [ ] **Step 2: EXPLAIN audit for the two legacy scans** (informational — add DDL only if a full scan shows)

Run against dev3:
- `EXPLAIN SELECT ref_id, value_role, param, value FROM jute_prod_spng_target_map WHERE co_id=1 AND id_type='mcid' AND value_role IN ('standard','target','actual') AND param IN ('speed','spindles') AND active=1 AND effective_date <= '2026-07-01'` — existing `idx_jpstm_lookup (co_id, ref_id, ...)` gives only a co_id prefix range; this table is standards (small). Record the row estimate; only if it exceeds ~100k rows on sls, add `KEY idx_jpstm_slice (co_id, id_type, param, value_role, effective_date)` as a new migration.
- `SHOW INDEX FROM daily_doff_tbl` and `EXPLAIN SELECT mc_id, spell, SUM(net_weight) FROM daily_doff_tbl WHERE doff_date='2026-07-01' GROUP BY mc_id, spell` — if no index leads on `doff_date`, create migration `add_daily_doff_day_index.sql` with `ALTER TABLE daily_doff_tbl ADD INDEX idx_ddt_day (doff_date, spell, mc_id);` (rollback comment: DROP INDEX) and apply it the same way.

---

### Task 3: `spinning_day_slice_sql()` + all new query builders

**Files:**
- Modify: `src/juteProduction/spinning_query.py` (append new section; delete `get_winding_total_query` at lines 515-540)
- Test: `src/test/test_spinning_dayslice.py` (new)

**Interfaces:**
- Produces (all in `spinning_query.py`, consumed by Tasks 4-6):
  - `spinning_day_slice_sql() -> str` — SQL fragment, binds `:co_id :tran_date :spell_id :branch_id :spinning_type` (spell/branch null-tolerant)
  - `get_spinning_planning_slice_query()` — `text()` of the slice ordered by `mech_code, spell_id`
  - `get_spinning_unmapped_produced_machines_query()` — BLOCK probe, binds `:tran_date :spell_id`
  - `get_spinning_process_no_standard_query()`, `get_spinning_process_no_count_query()` — WARN probes, binds `:co_id :tran_date :spell_id`
  - `soft_delete_spinning_log_for_unit_query()` — binds `:co_id :tran_date :spell_id :updated_by`
  - `insert_spinning_log_from_slice_query()` — binds slice binds + `:updated_by`
  - `get_spinning_process_lock_row_query()`, `insert_spinning_process_lock_query()`, `update_spinning_process_lock_query()`, `update_spinning_process_lock_reprocess_query()`, `flag_spinning_unit_reprocess_query()` — lock CRUD, weaving-identical shapes
  - `get_spinning_drift_query()` — binds `:co_id :tran_date :spell_id`
  - `get_spinning_log_rows_query()` — binds `:co_id :tran_date :spell_id :branch_id`
  - `get_machine_bobbin_batch_query()` — binds `:co_id :on_date`
- Consumes: table/columns from Task 1.

- [ ] **Step 1: Write failing tests** (`src/test/test_spinning_dayslice.py`)

```python
"""Slice + process query construction tests (no DB — string assertions only)."""

from src.juteProduction.spinning_query import (
    spinning_day_slice_sql,
    get_spinning_planning_slice_query,
    insert_spinning_log_from_slice_query,
    get_spinning_drift_query,
    get_spinning_log_rows_query,
    get_machine_bobbin_batch_query,
)


class TestSpinningDaySlice:
    def test_slice_filters_driver_by_day_first(self):
        sql = spinning_day_slice_sql()
        assert "f.tran_date = :tran_date" in sql
        assert "f.spg_wdg = 'S'" in sql
        assert "bm.co_id = :co_id" in sql  # tenant-safety: driver co-scoped

    def test_slice_has_no_view_reads(self):
        sql = spinning_day_slice_sql()
        assert "vw_winding_daily_reconciled" not in sql
        assert "vw_spinning_planning_grid" not in sql

    def test_slice_uses_set_based_probes(self):
        sql = spinning_day_slice_sql()
        assert "ROW_NUMBER() OVER" in sql          # target-map pivot
        assert "PARTITION BY t2.ref_id, t2.value_role, t2.param" in sql
        assert "jute_prod_winding_doff" in sql      # inline winding reconciliation
        assert "GROUP BY" in sql

    def test_slice_windowed_allocation_is_day_bounded(self):
        sql = spinning_day_slice_sql()
        assert "SUM(calc.act_prod_doff) OVER" in sql
        assert "PARTITION BY calc.co_id, calc.tran_date, calc.item_id, calc.shift_bucket" in sql

    def test_planning_slice_query_orders_by_mech_code(self):
        assert "ORDER BY" in str(get_spinning_planning_slice_query())

    def test_log_insert_selects_from_slice(self):
        sql = str(insert_spinning_log_from_slice_query())
        assert "INSERT INTO jute_prod_spinning_daily" in sql
        assert "SELECT" in sql and "ROW_NUMBER() OVER" in sql

    def test_drift_query_compares_three_sources(self):
        sql = str(get_spinning_drift_query())
        for col in ("act_count", "act_prod_doff", "winding_total"):
            assert col in sql

    def test_log_rows_query_is_unit_scoped(self):
        sql = str(get_spinning_log_rows_query())
        assert "jute_prod_spinning_daily" in sql
        assert "co_id = :co_id" in sql and "tran_date = :tran_date" in sql

    def test_bobbin_batch_query_pivots_by_machine(self):
        sql = str(get_machine_bobbin_batch_query())
        assert "bobbin_wt" in sql and "ROW_NUMBER() OVER" in sql
```

- [ ] **Step 2: Run tests, verify failure**

Run: `cd c:/code/vowerp3be && .venv/Scripts/python -m pytest src/test/test_spinning_dayslice.py -v`
Expected: FAIL — `ImportError: cannot import name 'spinning_day_slice_sql'`

- [ ] **Step 3: Implement in `spinning_query.py`**

Delete `get_winding_total_query()` (lines 515-540) entirely. Append this new section. Formulas are byte-matched to `vw_spinning_planning_grid` in `dbqueries/migrations/repoint_vw_spinning_planning_grid_actuals.sql` (which mirrors the Python handler) — keep every COALESCE/ROUND/NULLIF identical:

```python
# =============================================================================
# Day-slice + Process/Lock builders (weaving Phase-1 pattern)
# =============================================================================


def spinning_day_slice_sql() -> str:
    """Day-sliced planning-grid compute — the request-path replacement for BOTH the
    per-row resolver N+1 and the unbounded vw_winding_daily_reconciled read.

    Structure mirrors vw_spinning_planning_grid (the REFERENCE ORACLE — never read
    it in app code) with two deliberate changes:
      1. The driver (daily_doff_frames_winding, spg_wdg='S') is filtered to
         (:co_id, :tran_date [, :spell_id, :branch_id]) FIRST, so nothing
         accumulates over history. TRIPWIRE: moving :tran_date out of the driver
         WHERE re-materializes full history — do not "optimize" it away.
      2. Correlated per-row probes become once-per-request derived tables:
         tmm/tmq (ROW_NUMBER rn=1 last-date target-map pivots, keyed machine/item),
         cnt (count AVG), dff (doff SUM), wnd (day-scoped winding reconciliation
         with set-based jugar MAX lookups instead of correlated subqueries).
    The window allocation (act_prod_wind) is day-bounded — the partition only ever
    contains this slice's rows, which is why a window function is allowed here.
    Binds: :co_id :tran_date :spell_id (nullable) :branch_id (nullable)
    :spinning_type.
    """
    return """
        SELECT
            eff.co_id, eff.branch_id, eff.tran_date, eff.spell_id, eff.spell_code,
            eff.shift_bucket, eff.machine_id, eff.mech_code, eff.machine_name,
            eff.item_id, eff.item_code, eff.item_name,
            eff.spindles, eff.minutes, eff.act_count, eff.std_count,
            eff.std_speed, eff.actual_speed, eff.target_speed,
            eff.std_tpi, eff.actual_tpi, eff.target_tpi,
            eff.std_eff, eff.target_eff,
            eff.p100prod, eff.std_prod, eff.target_prod,
            eff.act_prod_doff, eff.winding_total, eff.act_prod_wind, eff.eff_doff,
            COALESCE(ROUND(eff.act_prod_wind / NULLIF(eff.p100prod, 0) * 100, 2), 0) AS eff_winding
        FROM (
            SELECT
                calc.*,
                COALESCE(
                    ROUND(
                        calc.winding_total * calc.act_prod_doff
                        / NULLIF(SUM(calc.act_prod_doff) OVER (
                            PARTITION BY calc.co_id, calc.tran_date, calc.item_id, calc.shift_bucket
                          ), 0),
                        3
                    ), 0
                ) AS act_prod_wind
            FROM (
                SELECT
                    r.*,
                    ROUND(r.p100prod * r.std_eff / 100, 3) AS std_prod,
                    ROUND(r.p100prod * r.target_eff / 100, 3) AS target_prod,
                    COALESCE(ROUND(r.act_prod_doff / NULLIF(r.p100prod, 0) * 100, 2), 0) AS eff_doff
                FROM (
                    SELECT
                        b.*,
                        COALESCE(
                            ROUND(
                                (b.std_speed * b.minutes * b.act_count * b.spindles)
                                / (36 * 14400 * 2.2046 * NULLIF(b.std_tpi, 0)),
                                0
                            ), 0
                        ) AS p100prod
                    FROM (
                        SELECT
                            bm.co_id AS co_id,
                            d.branch_id AS branch_id,
                            f.tran_date AS tran_date,
                            f.spell_id AS spell_id,
                            sp.spell_code AS spell_code,
                            LEFT(sp.spell_code, 1) AS shift_bucket,
                            f.mc_eb_id AS machine_id,
                            m.mech_code AS mech_code,
                            m.machine_name AS machine_name,
                            f.item_id AS item_id,
                            im.item_code AS item_code,
                            im.item_name AS item_name,
                            CAST(COALESCE(tmm.spindles_raw, 0) AS SIGNED) AS spindles,
                            CASE
                                WHEN sp.working_hours IS NOT NULL THEN ROUND(sp.working_hours * 60)
                                WHEN sp.spell_code = 'A1' THEN 300
                                WHEN sp.spell_code = 'A2' THEN 180
                                ELSE 0
                            END AS minutes,
                            COALESCE(cnt.act_count, 0) AS act_count,
                            COALESCE(ym.jute_yarn_count, 0) AS std_count,
                            COALESCE(tmm.std_speed_raw, 0) AS std_speed,
                            COALESCE(tmm.actual_speed_raw, 0) AS actual_speed,
                            COALESCE(tmm.target_speed_raw, 0) AS target_speed,
                            COALESCE(tmq.std_tpi_raw, 0) AS std_tpi,
                            COALESCE(tmq.actual_tpi_raw, 0) AS actual_tpi,
                            COALESCE(tmq.target_tpi_raw, 0) AS target_tpi,
                            COALESCE(tmq.std_eff_raw, 0) AS std_eff,
                            COALESCE(tmq.target_eff_raw, 0) AS target_eff,
                            COALESCE(dff.act_prod_doff, 0) AS act_prod_doff,
                            COALESCE(wnd.winding_total, 0) AS winding_total
                        FROM daily_doff_frames_winding f
                        INNER JOIN machine_mst m ON m.machine_id = f.mc_eb_id
                        INNER JOIN machine_type_mst mt
                                ON mt.machine_type_id = m.machine_type_id
                               AND mt.active = 1
                               AND mt.machine_type_name = :spinning_type
                        INNER JOIN dept_mst d ON d.dept_id = m.dept_id
                        INNER JOIN branch_mst bm ON bm.branch_id = d.branch_id
                        LEFT JOIN (
                            SELECT spell_id, spell_code, working_hours
                            FROM spell_mst WHERE status = 1
                        ) sp ON sp.spell_id = f.spell_id
                        LEFT JOIN item_mst im ON im.item_id = f.item_id
                        LEFT JOIN jute_yarn_mst ym ON ym.item_id = f.item_id
                        LEFT JOIN (
                            SELECT t.ref_id,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'spindles' THEN t.value END) AS spindles_raw,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'speed' THEN t.value END) AS std_speed_raw,
                                   MAX(CASE WHEN t.value_role = 'actual'   AND t.param = 'speed' THEN t.value END) AS actual_speed_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'speed' THEN t.value END) AS target_speed_raw
                            FROM (
                                SELECT t2.ref_id, t2.value_role, t2.param, t2.value,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY t2.ref_id, t2.value_role, t2.param
                                           ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                                       ) AS rn
                                FROM jute_prod_spng_target_map t2
                                WHERE t2.co_id = :co_id AND t2.id_type = 'mcid'
                                  AND t2.param IN ('speed', 'spindles')
                                  AND t2.value_role IN ('standard', 'target', 'actual')
                                  AND t2.active = 1 AND t2.effective_date <= :tran_date
                            ) t
                            WHERE t.rn = 1
                            GROUP BY t.ref_id
                        ) tmm ON tmm.ref_id = f.mc_eb_id
                        LEFT JOIN (
                            SELECT t.ref_id,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'tpi' THEN t.value END) AS std_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'actual'   AND t.param = 'tpi' THEN t.value END) AS actual_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'tpi' THEN t.value END) AS target_tpi_raw,
                                   MAX(CASE WHEN t.value_role = 'standard' AND t.param = 'eff' THEN t.value END) AS std_eff_raw,
                                   MAX(CASE WHEN t.value_role = 'target'   AND t.param = 'eff' THEN t.value END) AS target_eff_raw
                            FROM (
                                SELECT t2.ref_id, t2.value_role, t2.param, t2.value,
                                       ROW_NUMBER() OVER (
                                           PARTITION BY t2.ref_id, t2.value_role, t2.param
                                           ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                                       ) AS rn
                                FROM jute_prod_spng_target_map t2
                                WHERE t2.co_id = :co_id AND t2.id_type = 'qid'
                                  AND t2.param IN ('tpi', 'eff')
                                  AND t2.value_role IN ('standard', 'target', 'actual')
                                  AND t2.active = 1 AND t2.effective_date <= :tran_date
                            ) t
                            WHERE t.rn = 1
                            GROUP BY t.ref_id
                        ) tmq ON tmq.ref_id = f.item_id
                        LEFT JOIN (
                            SELECT item_id, AVG(observed_count) AS act_count
                            FROM jute_sqc_spinning_count
                            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
                            GROUP BY item_id
                        ) cnt ON cnt.item_id = f.item_id
                        LEFT JOIN (
                            SELECT mc_id, spell, SUM(net_weight) AS act_prod_doff
                            FROM daily_doff_tbl
                            WHERE doff_date = :tran_date
                              AND (active = 1 OR active IS NULL)
                            GROUP BY mc_id, spell
                        ) dff ON dff.mc_id = f.mc_eb_id AND dff.spell = f.spell_id
                        LEFT JOIN (
                            SELECT wdr.item_id,
                                   LEFT(wsp.spell_code, 1) AS shift_bucket,
                                   SUM(wdr.reconciled_qty) AS winding_total
                            FROM (
                                SELECT wbm.co_id, wdp.branch_id AS branch_id,
                                       wd.spell_id, wd.machine_id, wd.item_id,
                                       SUM(wd.production_qty)
                                       - COALESCE(MAX(jo.open_w), 0)
                                       + COALESCE(MAX(jc.close_w), 0) AS reconciled_qty
                                FROM jute_prod_winding_doff wd
                                INNER JOIN machine_mst wm ON wm.machine_id = wd.machine_id
                                INNER JOIN dept_mst wdp ON wdp.dept_id = wm.dept_id
                                INNER JOIN branch_mst wbm ON wbm.branch_id = wdp.branch_id
                                LEFT JOIN (
                                    SELECT spell_id, machine_id, MAX(weight) AS open_w
                                    FROM jute_prod_winding_jugar
                                    WHERE tran_date = :tran_date AND open_close = 'O' AND active = 1
                                    GROUP BY spell_id, machine_id
                                ) jo ON jo.spell_id = wd.spell_id AND jo.machine_id = wd.machine_id
                                LEFT JOIN (
                                    SELECT spell_id, machine_id, MAX(weight) AS close_w
                                    FROM jute_prod_winding_jugar
                                    WHERE tran_date = :tran_date AND open_close = 'C' AND active = 1
                                    GROUP BY spell_id, machine_id
                                ) jc ON jc.spell_id = wd.spell_id AND jc.machine_id = wd.machine_id
                                WHERE wd.active = 1
                                  AND wd.tran_date = :tran_date
                                  AND wbm.co_id = :co_id
                                GROUP BY wbm.co_id, wdp.branch_id, wd.spell_id, wd.machine_id, wd.item_id
                            ) wdr
                            INNER JOIN spell_mst wsp ON wsp.spell_id = wdr.spell_id
                            WHERE (:branch_id IS NULL OR wdr.branch_id = :branch_id OR wdr.branch_id IS NULL)
                            GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)
                        ) wnd ON wnd.item_id = f.item_id AND wnd.shift_bucket = LEFT(sp.spell_code, 1)
                        WHERE f.spg_wdg = 'S'
                          AND f.tran_date = :tran_date
                          AND f.item_id IS NOT NULL
                          AND (f.active = 1 OR f.active IS NULL)
                          AND bm.co_id = :co_id
                          AND (:spell_id IS NULL OR f.spell_id = :spell_id)
                          AND (:branch_id IS NULL OR d.branch_id = :branch_id)
                    ) b
                ) r
            ) calc
        ) eff
    """


def get_spinning_planning_slice_query():
    """The slice as an executable, ordered like the old driver (mech_code, spell)."""
    return text(spinning_day_slice_sql() + "\n        ORDER BY eff.mech_code, eff.spell_id")


def get_spinning_unmapped_produced_machines_query():
    """BLOCK probe: machines with doff production in the unit but no active mapped
    frame (item) for the same (tran_date, spell) — set-based, weaving pattern."""
    return text(
        """
        SELECT dd.mc_id AS machine_id, m.mech_code
        FROM daily_doff_tbl dd
        LEFT JOIN machine_mst m ON m.machine_id = dd.mc_id
        LEFT JOIN daily_doff_frames_winding f
               ON f.mc_eb_id = dd.mc_id
              AND f.spg_wdg = 'S'
              AND f.tran_date = :tran_date
              AND f.spell_id = :spell_id
              AND f.item_id IS NOT NULL
              AND (f.active = 1 OR f.active IS NULL)
        WHERE dd.doff_date = :tran_date
          AND dd.spell = :spell_id
          AND (dd.active = 1 OR dd.active IS NULL)
        GROUP BY dd.mc_id, m.mech_code
        HAVING COUNT(f.daily_doff_frm_wdg_id) = 0
        """
    )


def get_spinning_process_no_standard_query():
    """WARN probe: mapped frames in the unit missing a std speed (machine) or a std
    tpi (item) as of the tran_date."""
    return text(
        """
        SELECT f.mc_eb_id AS machine_id, m.mech_code, f.item_id
        FROM daily_doff_frames_winding f
        LEFT JOIN machine_mst m ON m.machine_id = f.mc_eb_id
        LEFT JOIN jute_prod_spng_target_map spd
               ON spd.co_id = :co_id AND spd.id_type = 'mcid' AND spd.param = 'speed'
              AND spd.value_role = 'standard' AND spd.ref_id = f.mc_eb_id
              AND spd.active = 1 AND spd.effective_date <= :tran_date
        LEFT JOIN jute_prod_spng_target_map tpi
               ON tpi.co_id = :co_id AND tpi.id_type = 'qid' AND tpi.param = 'tpi'
              AND tpi.value_role = 'standard' AND tpi.ref_id = f.item_id
              AND tpi.active = 1 AND tpi.effective_date <= :tran_date
        WHERE f.spg_wdg = 'S'
          AND f.tran_date = :tran_date
          AND f.spell_id = :spell_id
          AND f.item_id IS NOT NULL
          AND (f.active = 1 OR f.active IS NULL)
        GROUP BY f.mc_eb_id, m.mech_code, f.item_id
        HAVING COUNT(spd.spng_target_map_id) = 0 OR COUNT(tpi.spng_target_map_id) = 0
        """
    )


def get_spinning_process_no_count_query():
    """WARN probe: mapped items in the unit with no SQC count observation for the day."""
    return text(
        """
        SELECT f.item_id, MIN(m.mech_code) AS mech_code
        FROM daily_doff_frames_winding f
        LEFT JOIN machine_mst m ON m.machine_id = f.mc_eb_id
        LEFT JOIN jute_sqc_spinning_count c
               ON c.co_id = :co_id AND c.item_id = f.item_id
              AND c.entry_date = :tran_date AND c.active = 1
        WHERE f.spg_wdg = 'S'
          AND f.tran_date = :tran_date
          AND f.spell_id = :spell_id
          AND f.item_id IS NOT NULL
          AND (f.active = 1 OR f.active IS NULL)
        GROUP BY f.item_id
        HAVING COUNT(c.spinning_sqc_count_id) = 0
        """
    )


def soft_delete_spinning_log_for_unit_query():
    """Soft-delete existing active frozen rows for the unit (reprocess idempotency)."""
    return text(
        """
        UPDATE jute_prod_spinning_daily
        SET active = 0, updated_by = :updated_by, updated_date_time = CURRENT_TIMESTAMP
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        """
    )


def insert_spinning_log_from_slice_query():
    """Freeze the unit's computed rows into jute_prod_spinning_daily in ONE statement.

    SELECT source = spinning_day_slice_sql() — the same SQL the live grid serves, so
    frozen == last-rendered. Explicit column list (slice emits display columns the
    table does not store)."""
    slice_sql = spinning_day_slice_sql()
    return text(
        f"""
        INSERT INTO jute_prod_spinning_daily (
            co_id, branch_id, tran_date, spell_id, machine_id, item_id,
            spindles, minutes, act_count, std_count,
            std_speed, actual_speed, target_speed,
            std_tpi, actual_tpi, target_tpi,
            std_eff, target_eff,
            p100prod, std_prod, target_prod,
            act_prod_doff, winding_total, act_prod_wind,
            eff_doff, eff_winding, active, updated_by
        )
        SELECT
            v.co_id, v.branch_id, v.tran_date, v.spell_id, v.machine_id, v.item_id,
            v.spindles, v.minutes, v.act_count, v.std_count,
            v.std_speed, v.actual_speed, v.target_speed,
            v.std_tpi, v.actual_tpi, v.target_tpi,
            v.std_eff, v.target_eff,
            v.p100prod, v.std_prod, v.target_prod,
            v.act_prod_doff, v.winding_total, v.act_prod_wind,
            v.eff_doff, v.eff_winding, 1, :updated_by
        FROM (
        {slice_sql}
        ) v
        """
    )


def get_spinning_process_lock_row_query():
    """Active lock header id for the unit (upsert probe)."""
    return text(
        """
        SELECT spinning_process_lock_id FROM jute_prod_spinning_process_lock
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        ORDER BY spinning_process_lock_id DESC LIMIT 1
        """
    )


def insert_spinning_process_lock_query():
    """Insert a fresh locked header for the unit."""
    return text(
        """
        INSERT INTO jute_prod_spinning_process_lock
            (co_id, branch_id, tran_date, spell_id, is_locked, reprocess_needed,
             processed_by, processed_date_time, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, 1, 0,
             :processed_by, CURRENT_TIMESTAMP, 1, :processed_by)
        """
    )


def update_spinning_process_lock_query():
    """Re-lock + clear reprocess on an existing header (reprocess run)."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET is_locked = 1, reprocess_needed = 0, processed_by = :processed_by,
            processed_date_time = CURRENT_TIMESTAMP, updated_by = :processed_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE spinning_process_lock_id = :id
        """
    )


def update_spinning_process_lock_reprocess_query():
    """Raise reprocess_needed on a lock header (drift detected on read)."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET reprocess_needed = 1, updated_date_time = CURRENT_TIMESTAMP
        WHERE spinning_process_lock_id = :id
        """
    )


def flag_spinning_unit_reprocess_query():
    """Raise reprocess_needed on the ACTIVE locked header for a (co, date, spell)
    unit — called after any Edit-user mutation of a processed unit. No-op unlocked."""
    return text(
        """
        UPDATE jute_prod_spinning_process_lock
        SET reprocess_needed = 1, updated_date_time = CURRENT_TIMESTAMP
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND is_locked = 1 AND active = 1
        """
    )


def get_spinning_drift_query():
    """One row when the frozen unit disagrees with a fresh recompute of any drift
    source: SQC count AVG (per item), doff SUM (per machine/spell), or the winding
    total (per item/shift). All three are frozen as ordinary snapshot columns, so
    the compare needs no extra fingerprint columns. Round both sides to the stored
    DECIMAL scale so an unchanged value never trips."""
    return text(
        """
        SELECT sd.spinning_daily_id
        FROM jute_prod_spinning_daily sd
        LEFT JOIN spell_mst sp ON sp.spell_id = sd.spell_id
        LEFT JOIN (
            SELECT item_id, AVG(observed_count) AS act_count
            FROM jute_sqc_spinning_count
            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
            GROUP BY item_id
        ) cnt ON cnt.item_id = sd.item_id
        LEFT JOIN (
            SELECT mc_id, spell, SUM(net_weight) AS act_prod_doff
            FROM daily_doff_tbl
            WHERE doff_date = :tran_date
              AND (active = 1 OR active IS NULL)
            GROUP BY mc_id, spell
        ) dff ON dff.mc_id = sd.machine_id AND dff.spell = sd.spell_id
        LEFT JOIN (
            SELECT wdr.item_id, LEFT(wsp.spell_code, 1) AS shift_bucket,
                   SUM(wdr.reconciled_qty) AS winding_total
            FROM (
                SELECT wbm.co_id, wd.spell_id, wd.machine_id, wd.item_id,
                       SUM(wd.production_qty)
                       - COALESCE(MAX(jo.open_w), 0)
                       + COALESCE(MAX(jc.close_w), 0) AS reconciled_qty
                FROM jute_prod_winding_doff wd
                INNER JOIN machine_mst wm ON wm.machine_id = wd.machine_id
                INNER JOIN dept_mst wdp ON wdp.dept_id = wm.dept_id
                INNER JOIN branch_mst wbm ON wbm.branch_id = wdp.branch_id
                LEFT JOIN (
                    SELECT spell_id, machine_id, MAX(weight) AS open_w
                    FROM jute_prod_winding_jugar
                    WHERE tran_date = :tran_date AND open_close = 'O' AND active = 1
                    GROUP BY spell_id, machine_id
                ) jo ON jo.spell_id = wd.spell_id AND jo.machine_id = wd.machine_id
                LEFT JOIN (
                    SELECT spell_id, machine_id, MAX(weight) AS close_w
                    FROM jute_prod_winding_jugar
                    WHERE tran_date = :tran_date AND open_close = 'C' AND active = 1
                    GROUP BY spell_id, machine_id
                ) jc ON jc.spell_id = wd.spell_id AND jc.machine_id = wd.machine_id
                WHERE wd.active = 1
                  AND wd.tran_date = :tran_date
                  AND wbm.co_id = :co_id
                GROUP BY wbm.co_id, wd.spell_id, wd.machine_id, wd.item_id
            ) wdr
            INNER JOIN spell_mst wsp ON wsp.spell_id = wdr.spell_id
            GROUP BY wdr.item_id, LEFT(wsp.spell_code, 1)
        ) wnd ON wnd.item_id = sd.item_id AND wnd.shift_bucket = LEFT(sp.spell_code, 1)
        WHERE sd.co_id = :co_id AND sd.tran_date = :tran_date AND sd.spell_id = :spell_id
          AND sd.active = 1
          AND (
            ROUND(COALESCE(sd.act_count, 0), 3) <> ROUND(COALESCE(cnt.act_count, 0), 3)
            OR ROUND(COALESCE(sd.act_prod_doff, 0), 3) <> ROUND(COALESCE(dff.act_prod_doff, 0), 3)
            OR ROUND(COALESCE(sd.winding_total, 0), 3) <> ROUND(COALESCE(wnd.winding_total, 0), 3)
          )
        LIMIT 1
        """
    )


def get_spinning_log_rows_query():
    """Frozen unit rows projected with the SAME aliases as the slice so the
    planning-grid read is source-agnostic (display names joined live — masters may
    format, never accumulate)."""
    return text(
        """
        SELECT sd.co_id, sd.branch_id, sd.tran_date, sd.spell_id, sp.spell_code,
               LEFT(sp.spell_code, 1) AS shift_bucket,
               sd.machine_id, m.mech_code, m.machine_name,
               sd.item_id, im.item_code, im.item_name,
               sd.spindles, sd.minutes, sd.act_count, sd.std_count,
               sd.std_speed, sd.actual_speed, sd.target_speed,
               sd.std_tpi, sd.actual_tpi, sd.target_tpi,
               sd.std_eff, sd.target_eff,
               sd.p100prod, sd.std_prod, sd.target_prod,
               sd.act_prod_doff, sd.winding_total, sd.act_prod_wind,
               sd.eff_doff, sd.eff_winding
        FROM jute_prod_spinning_daily sd
        LEFT JOIN spell_mst sp ON sp.spell_id = sd.spell_id
        LEFT JOIN machine_mst m ON m.machine_id = sd.machine_id
        LEFT JOIN item_mst im ON im.item_id = sd.item_id
        WHERE sd.co_id = :co_id AND sd.tran_date = :tran_date AND sd.spell_id = :spell_id
          AND (:branch_id IS NULL OR sd.branch_id = :branch_id OR sd.branch_id IS NULL)
          AND sd.active = 1
        ORDER BY m.mech_code, sd.spinning_daily_id
        """
    )


def get_machine_bobbin_batch_query():
    """Last-date standard bobbin_wt for ALL machines of a company in one pass
    (replaces the per-machine resolve_param loop in doff_entry_create_setup)."""
    return text(
        """
        SELECT t.ref_id AS machine_id, t.value AS bobbin_weight
        FROM (
            SELECT t2.ref_id, t2.value,
                   ROW_NUMBER() OVER (
                       PARTITION BY t2.ref_id
                       ORDER BY t2.effective_date DESC, t2.spng_target_map_id DESC
                   ) AS rn
            FROM jute_prod_spng_target_map t2
            WHERE t2.co_id = :co_id AND t2.id_type = 'mcid'
              AND t2.value_role = 'standard' AND t2.param = 'bobbin_wt'
              AND t2.active = 1 AND t2.effective_date <= :on_date
        ) t
        WHERE t.rn = 1
        """
    )
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/Scripts/python -m pytest src/test/test_spinning_dayslice.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/juteProduction/spinning_query.py src/test/test_spinning_dayslice.py
git commit -m "feat(spinning): day-slice SQL + process/lock/drift query builders, drop view reader"
```

Note: `spinning_entry.py` still imports `get_winding_total_query` at this point — full-suite collection fails until Task 5 lands. Tasks 3-5 are one logical unit; run only the new test file in between.

---

### Task 4: `spinning_lock.py` (lock lookups + permission gate)

**Files:**
- Create: `src/juteProduction/spinning_lock.py`
- Test: `src/test/test_spinning_lock.py` (new)

**Interfaces:**
- Produces: `get_process_lock(db, co_id, branch_id, tran_date, spell_id)`, `is_unit_locked(...) -> bool`, `require_edit_if_locked(db, token_data, co_id, branch_id, tran_date, spell_id)` (raises 403), `flag_reprocess_if_locked(db, co_id, tran_date, spell_id)` — consumed by Tasks 5-6.
- Consumes: `flag_spinning_unit_reprocess_query` (Task 3), `get_user_menu_access_level_query` from `src/common/portal/query.py`.

- [ ] **Step 1: Write failing test** (`src/test/test_spinning_lock.py`)

```python
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.juteProduction.spinning_lock import (
    SPINNING_MENU_PATH,
    is_unit_locked,
    require_edit_if_locked,
    flag_reprocess_if_locked,
)


class TestSpinningLock:
    def test_menu_path(self):
        assert SPINNING_MENU_PATH == "juteProduction/spinning"

    def test_unlocked_unit_passes_gate(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)  # no raise

    def test_locked_unit_without_edit_403(self):
        db = MagicMock()
        lock_row = MagicMock(is_locked=1)
        db.execute.return_value.fetchone.return_value = lock_row
        db.execute.return_value.scalar.return_value = 3  # Write, not Edit
        with pytest.raises(HTTPException) as exc:
            require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)
        assert exc.value.status_code == 403

    def test_locked_unit_with_edit_passes(self):
        db = MagicMock()
        lock_row = MagicMock(is_locked=1)
        db.execute.return_value.fetchone.return_value = lock_row
        db.execute.return_value.scalar.return_value = 4
        require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)  # no raise

    def test_flag_reprocess_noops_on_missing_ids(self):
        db = MagicMock()
        flag_reprocess_if_locked(db, None, "2026-07-01", 5)
        db.execute.assert_not_called()

    def test_is_unit_locked_false_when_no_row(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        assert is_unit_locked(db, 1, None, "2026-07-01", 5) is False
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/Scripts/python -m pytest src/test/test_spinning_lock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.juteProduction.spinning_lock'`

- [ ] **Step 3: Implement `src/juteProduction/spinning_lock.py`**

Before writing, confirm the menu path string: grep how weaving's `WEAVING_MENU_PATH = "juteProduction/weaving"` is consumed by `get_user_menu_access_level_query` (`src/common/portal/query.py`) and check `menu_mst` on dev3 for the spinning menu's equivalent value — use the same form transposed to spinning.

```python
"""Spinning Process lock lookups + the locked-unit permission gate.

A (co, branch, tran_date, spell) unit is locked once Processed. While locked,
spinning-page mutations require Edit (access_type_id >= 4); Write-only (3) is
rejected 403. Reads use is_unit_locked to choose frozen-log vs live slice.
Mirror of weaving_lock.py."""

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.portal.query import get_user_menu_access_level_query
from src.juteProduction.spinning_query import flag_spinning_unit_reprocess_query

SPINNING_MENU_PATH = "juteProduction/spinning"
EDIT_LEVEL = 4
LOCKED_EDIT_ONLY_MSG = (
    "This day/spell is processed and locked. Editing a locked spinning entry "
    "requires Edit permission for the Spinning Production menu."
)


def get_process_lock(db: Session, co_id, branch_id, tran_date, spell_id):
    """Active lock header for the unit (or None)."""
    return db.execute(
        text(
            """
            SELECT spinning_process_lock_id, is_locked, reprocess_needed
            FROM jute_prod_spinning_process_lock
            WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
              AND (:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)
              AND active = 1
            ORDER BY spinning_process_lock_id DESC
            LIMIT 1
            """
        ),
        {"co_id": int(co_id), "tran_date": tran_date, "spell_id": int(spell_id),
         "branch_id": None if branch_id is None else int(branch_id)},
    ).fetchone()


def is_unit_locked(db: Session, co_id, branch_id, tran_date, spell_id) -> bool:
    row = get_process_lock(db, co_id, branch_id, tran_date, spell_id)
    return bool(row and row.is_locked)


def user_menu_access_level(db: Session, user_id, co_id, branch_id, menu_path) -> int:
    lvl = db.execute(
        get_user_menu_access_level_query(),
        {"user_id": int(user_id), "co_id": int(co_id),
         "branch_id": None if branch_id is None else int(branch_id),
         "menu_path": menu_path},
    ).scalar()
    return int(lvl) if lvl is not None else 0


def require_edit_if_locked(db: Session, token_data: dict, co_id, branch_id,
                           tran_date, spell_id) -> None:
    """Raise 403 when the unit is locked and the user lacks Edit (>= 4)."""
    if not is_unit_locked(db, co_id, branch_id, tran_date, spell_id):
        return
    level = user_menu_access_level(
        db, token_data.get("user_id"), co_id, branch_id, SPINNING_MENU_PATH
    )
    if level < EDIT_LEVEL:
        raise HTTPException(status_code=403, detail=LOCKED_EDIT_ONLY_MSG)


def flag_reprocess_if_locked(db: Session, co_id, tran_date, spell_id) -> None:
    """Raise reprocess_needed on the unit's lock header when it is locked (no-op else)."""
    if co_id is None or spell_id is None:
        return
    db.execute(
        flag_spinning_unit_reprocess_query(),
        {"co_id": int(co_id), "tran_date": tran_date, "spell_id": int(spell_id)},
    )
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python -m pytest src/test/test_spinning_lock.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/juteProduction/spinning_lock.py src/test/test_spinning_lock.py
git commit -m "feat(spinning): process-lock lookups + locked-unit permission gate"
```

---

### Task 5: Rewire `spinning_entry.py` — slice-driven grid, lock gates, remove save, batch bobbin

**Files:**
- Modify: `src/juteProduction/spinning_entry.py`
- Modify: existing spinning test files (find with `grep -l "planning_grid" src/test/`)
- Modify: `src/test/test_no_unbounded_view_readers.py` (remove the ALLOWLIST entry)

**Interfaces:**
- Consumes: Task 3 queries, Task 4 gate functions.
- Produces: `GET /planning_grid` response shape UNCHANGED plus two additive booleans: `{"data": {"rows": [...], "shift_rollup": [...], "locked": bool, "reprocess_needed": bool}}`. `POST /planning_grid_save` REMOVED (404 after this task).

- [ ] **Step 1: Update imports**

Remove from the `spinning_query` import block: `get_winding_total_query`, `get_spinning_daily_active_row_query`, `insert_spinning_daily_query`, `update_spinning_daily_query`, `get_spinning_plan_driver_query`. Add:

```python
from src.juteProduction.spinning_lock import (
    flag_reprocess_if_locked,
    get_process_lock,
    require_edit_if_locked,
)
```
and to the `spinning_query` import block: `get_machine_bobbin_batch_query`, `get_spinning_log_rows_query`, `get_spinning_planning_slice_query`.

Then delete now-dead imports ONLY after a per-name grep confirms zero remaining uses in the file: `allocate_winding`, `p100_prod_spell`, `resolve_act_count`, `ID_TYPE_QLTY`, `PARAM_SPINDLES`, `PARAM_EFF`, `PARAM_TPI`, `VALUE_ROLE_TARGET`, `VALUE_ROLE_ACTUAL`, `SPELL_MINUTES` (keep `resolve_param`, `ID_TYPE_MC`, `VALUE_ROLE_STANDARD`, `PARAM_BOBBIN_WT` — `_resolve_bobbin` still uses them for doff create/edit tare). `_resolve_minutes` and `_shift_bucket` may keep uses — grep before deleting.

- [ ] **Step 2: Replace the `planning_grid` handler (lines 877-1072)**

```python
@router.get("/planning_grid")
def planning_grid(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Per-frame-per-spell planning grid for a tran_date (optional spell).

    Source-agnostic read: a Processed+locked (co, branch, date, spell) unit serves
    its frozen jute_prod_spinning_daily rows; otherwise ONE execution of the
    day-slice computes the grid live (no per-row resolvers, no view reads).
    Spell-less calls always serve the live slice — the lock switch needs the spell."""
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("tran_date")
    if not d:
        raise HTTPException(status_code=400, detail="tran_date is required")
    spell = request.query_params.get("spell") or None
    try:
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell_id(db, spell) if spell else None

        locked = False
        reprocess_needed = False
        if spell_id is not None:
            lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
            locked = bool(lock and lock.is_locked)
            reprocess_needed = bool(lock and lock.reprocess_needed)

        if locked:
            raw = db.execute(
                get_spinning_log_rows_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "branch_id": branch_id},
            ).fetchall()
        else:
            raw = db.execute(
                get_spinning_planning_slice_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "branch_id": branch_id,
                 "spinning_type": SPINNING_MACHINE_TYPE_NAME},
            ).fetchall()

        rows: List[Dict[str, Any]] = []
        for r in raw:
            m = dict(r._mapping)
            rows.append(
                {
                    "spell_id": _i(m.get("spell_id")),
                    "spell_code": m.get("spell_code"),
                    "shift_bucket": m.get("shift_bucket") or _shift_bucket(m.get("spell_code")),
                    "machine_id": _i(m.get("machine_id")),
                    "mech_code": m.get("mech_code"),
                    "machine_name": m.get("machine_name"),
                    "branch_id": m.get("branch_id"),
                    "item_id": _i(m.get("item_id")),
                    "item_code": m.get("item_code"),
                    "item_name": m.get("item_name"),
                    "spindles": int(m.get("spindles") or 0),
                    "minutes": int(m.get("minutes") or 0),
                    "act_count": _f(m.get("act_count")),
                    "std_count": _f(m.get("std_count")),
                    "std_speed": _f(m.get("std_speed")),
                    "actual_speed": _f(m.get("actual_speed")),
                    "target_speed": _f(m.get("target_speed")),
                    "std_tpi": _f(m.get("std_tpi")),
                    "actual_tpi": _f(m.get("actual_tpi")),
                    "target_tpi": _f(m.get("target_tpi")),
                    "std_eff": _f(m.get("std_eff")),
                    "target_eff": _f(m.get("target_eff")),
                    "p100prod": _f(m.get("p100prod")),
                    "std_prod": _f(m.get("std_prod")),
                    "target_prod": _f(m.get("target_prod")),
                    "act_prod_doff": _f(m.get("act_prod_doff")),
                    "winding_total": _f(m.get("winding_total")),
                    "act_prod_wind": _f(m.get("act_prod_wind")),
                    "eff_doff": _f(m.get("eff_doff")),
                    "eff_winding": _f(m.get("eff_winding")),
                }
            )

        # Shift rollup per (machine, yarn item, shift_bucket): SUM(num)/SUM(denom) —
        # unchanged from the pre-slice implementation.
        roll: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (row["machine_id"], row["item_id"], row["shift_bucket"])
            agg = roll.setdefault(
                key,
                {
                    "machine_id": row["machine_id"],
                    "mech_code": row.get("mech_code"),
                    "machine_name": row.get("machine_name"),
                    "item_id": row["item_id"],
                    "item_code": row.get("item_code"),
                    "shift_bucket": row["shift_bucket"],
                    "prod_doff": 0.0,
                    "prod_wind": 0.0,
                    "_p100": 0.0,
                },
            )
            agg["prod_doff"] += row["act_prod_doff"]
            agg["prod_wind"] += row["act_prod_wind"]
            agg["_p100"] += row["p100prod"]

        shift_rollup = []
        for agg in roll.values():
            p100 = agg.pop("_p100")
            agg["prod_doff"] = round(agg["prod_doff"], 3)
            agg["prod_wind"] = round(agg["prod_wind"], 3)
            agg["doff_eff"] = round(agg["prod_doff"] / p100 * 100, 2) if p100 else 0.0
            agg["wind_eff"] = round(agg["prod_wind"] / p100 * 100, 2) if p100 else 0.0
            shift_rollup.append(agg)

        return {"data": {"rows": rows, "shift_rollup": shift_rollup,
                         "locked": locked, "reprocess_needed": reprocess_needed}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: Delete `planning_grid_save` (lines 1075-1143) and the `PlanningGridRow` / `PlanningGridSave` Pydantic models.**

- [ ] **Step 4: Lock-gate every mutation endpoint** (weaving-review lesson: map endpoints gated too; gate BEFORE writing, flag AFTER writing, same try block)

`doff_entry_create` — after `spell_id = _resolve_spell_id(...)` and the branch derivation:
```python
        require_edit_if_locked(db, token_data, body.co_id, branch_id, body.tran_date, spell_id)
```
immediately before `db.commit()`:
```python
        flag_reprocess_if_locked(db, body.co_id, body.tran_date, spell_id)
```

`doff_entry_edit` — extend the existing lookup SELECT column list to `daily_doff_tbl_id, mc_id, trolly_id, gross_weight, item_id, doff_date, spell, branch_id`; after the 404 check:
```python
        require_edit_if_locked(db, token_data, co_id, existing.branch_id,
                               existing.doff_date, int(existing.spell))
```
before `db.commit()`:
```python
        flag_reprocess_if_locked(db, co_id, existing.doff_date, int(existing.spell))
```

`doff_entry_delete` — same as edit: extend lookup to `daily_doff_tbl_id, doff_date, spell, branch_id`, gate after 404 check, flag before commit.

`doff_dedup_run` — after `spell_id = _resolve_spell_id(...)`:
```python
        require_edit_if_locked(db, token_data, body.co_id, None, body.tran_date, spell_id)
```
flag before commit with `(body.co_id, body.tran_date, spell_id)`.

`frame_map_save` and `frame_map_mapped` — after their `spell_id = _resolve_spell_id(...)`:
```python
        require_edit_if_locked(db, token_data, body.co_id, body.branch_id, body.tran_date, spell_id)
```
flag before commit with `(body.co_id, body.tran_date, spell_id)`.

- [ ] **Step 5: Batch the setup bobbin resolve**

In `doff_entry_create_setup`, before the machines loop:

```python
        bobbin_by_mc = {
            int(r.machine_id): _f(r.bobbin_weight)
            for r in db.execute(
                get_machine_bobbin_batch_query(), {"co_id": co_id, "on_date": today}
            ).fetchall()
        }
```

and inside the loop replace the `_resolve_bobbin` call with `"bobbin_weight": bobbin_by_mc.get(int(m["machine_id"]), 0.0)`. Keep `_resolve_bobbin` itself — doff create/edit still resolve per tran_date.

- [ ] **Step 6: Remove the CI allowlist entry**

In `src/test/test_no_unbounded_view_readers.py` delete the line:
```python
    ("juteProduction/spinning_query.py", "vw_winding_daily_reconciled"),  # Phase 2: remove
```
so the allowlist is empty (adjust the surrounding comment: Phase 2 landed).

- [ ] **Step 7: Update existing spinning tests**

Find affected files: `grep -rl "planning_grid\|get_winding_total_query\|resolve_param" src/test/ --include="test_spinning*.py"`. Update: planning_grid success tests mock ONE slice execute result (rows whose `_mapping` dicts carry the slice aliases) preceded by a lock probe returning `None`; delete `planning_grid_save` tests; setup tests mock the batch bobbin result instead of per-machine resolve calls. Assert the new `locked`/`reprocess_needed` keys exist and are `False` in the unlocked path.

- [ ] **Step 8: Run the spinning + tripwire suites**

Run: `.venv/Scripts/python -m pytest src/test/ -k "spinning or unbounded" -v`
Expected: PASS, clean collection (all dead imports removed).

- [ ] **Step 9: Commit**

```bash
git add src/juteProduction/spinning_entry.py src/test/test_no_unbounded_view_readers.py src/test/test_spinning*.py
git commit -m "feat(spinning): slice-driven planning grid, lock gates on all mutations, drop planning_grid_save + last unbounded view reader"
```

---

### Task 6: `spinning_process.py` — Process + status endpoints

**Files:**
- Create: `src/juteProduction/spinning_process.py`
- Modify: `src/main.py` (import near line 97, register after line 259)
- Test: `src/test/test_spinning_process.py` (new)

**Interfaces:**
- Consumes: Task 3 queries, Task 4 lock functions, `_resolve_spell_id` from `spinning_entry`.
- Produces: `POST /api/spinningProd/process` → `{"data": {"processed": int, "warnings": {"no_standard": [...], "no_count": [...]}}}`; `GET /api/spinningProd/process_status` → `{"data": {"locked": bool, "reprocess_needed": bool}}`.

- [ ] **Step 1: Write failing tests** (`src/test/test_spinning_process.py`)

Read `src/test/test_weaving_process.py` FIRST and transpose its mock plumbing exactly (dependency overrides / patches, MagicMock execute-side-effect sequencing). Required cases, fully written out with payload `{"co_id": 1, "branch_id": 2, "tran_date": "2026-07-01", "spell": "A1"}` against `/api/spinningProd/process`:

1. `test_process_blocks_on_unmapped_produced_machine` — unmapped probe returns one row → 400, `detail["unmapped"]` non-empty, no INSERT executed.
2. `test_process_freezes_and_locks` — unmapped empty, WARN probes empty, freeze rowcount 7, no prior lock → 200 `processed == 7`, soft-delete executed before insert, lock INSERT executed.
3. `test_process_reprocess_updates_existing_lock` — lock probe returns a row → lock UPDATE, not INSERT.
4. `test_process_unknown_spell_400` — `_resolve_spell_id` path (spell not in spell_mst mock) → 400.
5. `test_process_status_unlocked` — lock lookup None → `{"locked": False, "reprocess_needed": False}`.
6. `test_process_status_drift_flags_reprocess` — locked row with `reprocess_needed=0`, drift query returns a row → reprocess UPDATE executed, response `reprocess_needed` True.
7. `test_process_status_missing_params_400` — no tran_date → 400.

- [ ] **Step 2: Run, verify fail** — `ModuleNotFoundError: No module named 'src.juteProduction.spinning_process'`.

- [ ] **Step 3: Implement `src/juteProduction/spinning_process.py`**

```python
"""Spinning Process + status endpoints. Prefix /api/spinningProd.

Process is set-based, one transaction: BLOCK on produced-but-unmapped machines,
collect WARN lists, soft-delete + INSERT...SELECT freeze from
spinning_day_slice_sql (the same SQL the live grid serves), lock header upsert.
process_status recomputes count/doff/winding drift for a locked unit.
Mirror of weaving_process.py."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPINNING_MACHINE_TYPE_NAME
from src.juteProduction.spinning_entry import _resolve_spell_id
from src.juteProduction.spinning_lock import get_process_lock, require_edit_if_locked
from src.juteProduction.spinning_query import (
    get_spinning_drift_query,
    get_spinning_process_lock_row_query,
    get_spinning_process_no_count_query,
    get_spinning_process_no_standard_query,
    get_spinning_unmapped_produced_machines_query,
    insert_spinning_log_from_slice_query,
    insert_spinning_process_lock_query,
    soft_delete_spinning_log_for_unit_query,
    update_spinning_process_lock_query,
    update_spinning_process_lock_reprocess_query,
)

router = APIRouter()

BLOCK_MSG = "Cannot process: these machines have doff production but no mapped quality."


class ProcessRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    tran_date: date
    spell: str


def _rows(res):
    return [dict(r._mapping) for r in res.fetchall()]


@router.post("/process")
def process_spinning(
    body: ProcessRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        spell_id = _resolve_spell_id(db, body.spell)
        user_id = token_data.get("user_id")
        binds = {"co_id": int(body.co_id), "tran_date": body.tran_date,
                 "spell_id": int(spell_id)}

        # Re-processing a locked unit requires Edit.
        require_edit_if_locked(db, token_data, body.co_id, body.branch_id,
                               body.tran_date, spell_id)

        # BLOCK: any produced machine without a mapped quality.
        unmapped = _rows(db.execute(
            get_spinning_unmapped_produced_machines_query(),
            {"tran_date": body.tran_date, "spell_id": int(spell_id)},
        ))
        if unmapped:
            raise HTTPException(status_code=400,
                                detail={"message": BLOCK_MSG, "unmapped": unmapped})

        # WARN collectors (set-based).
        warnings = {
            "no_standard": _rows(db.execute(get_spinning_process_no_standard_query(), binds)),
            "no_count": _rows(db.execute(get_spinning_process_no_count_query(), binds)),
        }

        # Soft-delete prior frozen rows (idempotent reprocess).
        db.execute(soft_delete_spinning_log_for_unit_query(),
                   {**binds, "updated_by": user_id})

        # Freeze: INSERT ... SELECT from the day-slice — one statement, cost
        # independent of frame count. Branch-UNfiltered so the frozen unit is
        # complete; branch scoping applies on read.
        slice_binds = {**binds, "branch_id": None, "updated_by": user_id,
                       "spinning_type": SPINNING_MACHINE_TYPE_NAME}
        result = db.execute(insert_spinning_log_from_slice_query(), slice_binds)
        processed = int(result.rowcount)

        # Lock header upsert.
        lock = db.execute(get_spinning_process_lock_row_query(), binds).fetchone()
        if lock:
            db.execute(update_spinning_process_lock_query(),
                       {"id": lock.spinning_process_lock_id, "processed_by": user_id})
        else:
            db.execute(insert_spinning_process_lock_query(),
                       {**binds,
                        "branch_id": None if body.branch_id is None else int(body.branch_id),
                        "processed_by": user_id})

        db.commit()
        return {"data": {"processed": processed, "warnings": warnings}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/process_status")
def process_status(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_raw = request.query_params.get("co_id")
        if not co_raw:
            raise HTTPException(status_code=400, detail="co_id is required")
        d = request.query_params.get("tran_date")
        spell_raw = request.query_params.get("spell")
        if not d or not spell_raw:
            raise HTTPException(status_code=400, detail="tran_date and spell are required")
        branch_raw = request.query_params.get("branch_id")
        branch_id = int(branch_raw) if branch_raw else None
        co_id = int(co_raw)
        d_val = date.fromisoformat(d)
        spell_id = _resolve_spell_id(db, spell_raw)

        lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
        if not lock or not lock.is_locked:
            return {"data": {"locked": False, "reprocess_needed": False}}

        drift = db.execute(
            get_spinning_drift_query(),
            {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id},
        ).fetchone()
        needed = drift is not None
        if needed and not lock.reprocess_needed:
            db.execute(update_spinning_process_lock_reprocess_query(),
                       {"id": lock.spinning_process_lock_id})
            db.commit()
        return {"data": {"locked": True,
                         "reprocess_needed": bool(needed or lock.reprocess_needed)}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Register in `src/main.py`**

Next to the existing spinning imports (line ~96-97):
```python
from src.juteProduction.spinning_process import router as spinning_process_router
```
After the `spinning_entry_router` registration (line ~259):
```python
app.include_router(spinning_process_router, prefix="/api/spinningProd", tags=["jute-production-spinning-entry"])
```

- [ ] **Step 5: Run, verify pass**

Run: `.venv/Scripts/python -m pytest src/test/test_spinning_process.py src/test/test_spinning_dayslice.py src/test/test_spinning_lock.py -v` → PASS

- [ ] **Step 6: Run whole backend suite**

Run: `.venv/Scripts/python -m pytest src/test/ -q`
Expected: no NEW failures vs branch baseline (record the before-count first; weaving test files are mid-edit by another effort — exclude them from judgment).

- [ ] **Step 7: Commit**

```bash
git add src/juteProduction/spinning_process.py src/main.py src/test/test_spinning_process.py
git commit -m "feat(spinning): set-based Process freeze + lock + drift status endpoints"
```

---

### Task 7: Parity harness + dev3 verification

**Files:**
- Create: `dbqueries/verify_spinning_dayslice_parity.py`

**Interfaces:**
- Consumes: `get_spinning_planning_slice_query()` and `vw_spinning_planning_grid` (oracle); row key `(spell_id, machine_id, item_id)`.

- [ ] **Step 1: Clone the weaving harness**

Read `dbqueries/verify_weaving_dayslice_parity.py` and produce the spinning variant with these exact substitutions: slice source = `get_spinning_planning_slice_query()` executed with `{"co_id": <co>, "tran_date": <d>, "spell_id": None, "branch_id": None, "spinning_type": "Spinning"}`; oracle = `SELECT <same column list as the slice outer SELECT> FROM vw_spinning_planning_grid WHERE co_id = %s AND tran_date = %s`; row key `(spell_id, machine_id, item_id)`; numeric tolerance `0.011`; same CLI (`--database`, `--dates`, `--limit`) and exit codes 0/1/2. Keep the DECIMAL/str normalization helpers verbatim.

Document in the module docstring the one deliberate slice-vs-view delta: the slice adds `AND bm.co_id = :co_id` on the driver (tenant safety) — the oracle side is equally co-filtered by its outer WHERE, so keys align.

- [ ] **Step 2: Run on dev3**

Run: `.venv/Scripts/python dbqueries/verify_spinning_dayslice_parity.py --database dev3`
Expected: exit 0, 0 mismatches. If mismatches: diff column-by-column; usual suspects are ROUND scale, the `spindles` CAST, and the target-map tie-break (`spng_target_map_id DESC` vs the view's LIMIT 1 without tie-break — a same-effective-date duplicate makes the oracle nondeterministic; verify against `resolve_param` semantics, document, don't chase).

- [ ] **Step 3: Commit**

```bash
git add dbqueries/verify_spinning_dayslice_parity.py
git commit -m "test(spinning): day-slice parity harness vs vw_spinning_planning_grid oracle"
```

---

### Task 8: Frontend — Process bar replaces Save (vowerp3ui)

**Files (all under `c:/code/vowerp3ui`):**
- Modify: `src/utils/api.ts` (spinning block ~lines 811-823: add `SPINNING_PROCESS`, `SPINNING_PROCESS_STATUS`; delete the planning-grid-save constant — grep its exact name first)
- Create: `src/app/dashboardportal/juteProduction/spinning/_components/SpinningProcessBar.tsx`
- Create: `src/app/dashboardportal/juteProduction/spinning/hooks/useSpinningProcessStatus.ts`
- Modify: `src/app/dashboardportal/juteProduction/spinning/_components/PlanningGrid.tsx` (remove Save button + save call; accept `locked` prop, render lock banner)
- Modify: `src/app/dashboardportal/juteProduction/spinning/hooks/usePlanningGrid.ts` (surface `locked` / `reprocess_needed`)
- Modify: `src/app/dashboardportal/juteProduction/spinning/page.tsx` (mount the bar on the planning tab)

**Interfaces:**
- Consumes: `POST /api/spinningProd/process` (body `{co_id, branch_id, tran_date, spell}`), `GET /api/spinningProd/process_status?co_id&branch_id&tran_date&spell`, planning_grid's `locked`/`reprocess_needed`.
- Templates to clone 1:1 (READ them first): `src/app/dashboardportal/juteProduction/weaving/_components/WeavingProcessBar.tsx`, `src/app/dashboardportal/juteProduction/weaving/hooks/useWeavingProcessStatus.ts`, and how `weaving/page.tsx` mounts the bar.

- [ ] **Step 1: api.ts** — add to the spinning constants block, matching the existing naming style:
```ts
SPINNING_PROCESS: "/spinningProd/process",
SPINNING_PROCESS_STATUS: "/spinningProd/process_status",
```
Delete the planning-grid-save constant (verify with grep it is only referenced by PlanningGrid.tsx).

- [ ] **Step 2: Clone `WeavingProcessBar.tsx` → `SpinningProcessBar.tsx`** — renames: `Weaving→Spinning` identifiers, route constants from Step 1, warning keys `no_worker/no_standard/no_picks` → `no_standard/no_count`, BLOCK payload key stays `unmapped`. Keep the mounted-guard hydration pattern if present (repo norm).

- [ ] **Step 3: Clone `useWeavingProcessStatus.ts` → `useSpinningProcessStatus.ts`** (same renames).

- [ ] **Step 4: PlanningGrid.tsx + usePlanningGrid.ts** — delete Save button, handler, and payload assembly; accept `locked: boolean`, render the locked banner (copy weaving grid's locked styling); hook passes through `locked`/`reprocess_needed`.

- [ ] **Step 5: page.tsx** — mount `<SpinningProcessBar/>` above the planning grid exactly as `weaving/page.tsx` mounts its bar (same props: co/branch/date/spell + refetch callback reloading grid and status after Process).

- [ ] **Step 6: Typecheck**

Run: `cd c:/code/vowerp3ui && npx tsc --noEmit`
Expected: clean; `grep -r "<deleted save constant name>" src/` returns nothing.

- [ ] **Step 7: Commit (vowerp3ui repo)**

```bash
cd c:/code/vowerp3ui
git add src/utils/api.ts src/app/dashboardportal/juteProduction/spinning
git commit -m "feat(spinning): Process/Lock bar replaces planning-grid Save"
```

- [ ] **Step 8: Browser QA on dev3** (portal-ui-flow-tester agent) — full flow: doff entry → frame map → planning grid live → Process (WARN lists render, grid flips frozen/locked) → mutate a doff as Edit user (reprocess badge appears on next status poll) → re-Process clears it.

---

### Task 9: sls rollout

- [ ] **Step 1: Apply Task-1 (+ any Task-2 EXPLAIN-mandated) migrations to sls** — same pymysql runner, `database='sls'`. Additive DDL only, no backfills. Check `SELECT COUNT(*) FROM daily_doff_tbl` first; large-table index adds run in low-traffic hours (online DDL, still IO-heavy).
- [ ] **Step 2: Parity on sls**: `.venv/Scripts/python dbqueries/verify_spinning_dayslice_parity.py --database sls` — expect exit 0. sls standards may be sparse (target_map import pending, same as weaving) — zero-standard days still parity-0 because both sides COALESCE to 0.
- [ ] **Step 3: PR body notes**: deploy order = migrations (done) → backend → frontend, per tenant.

---

### Task 10: Review + wrap-up

- [ ] **Step 1:** Run reviewer agent (repo conventions) + tenant-auditor agent (new queries carry co_id scoping; `daily_doff_tbl` machine-scoping assumption documented) over the branch diff.
- [ ] **Step 2:** Fix findings; rerun `pytest src/test/ -q` (no new failures) and `npx tsc --noEmit`.
- [ ] **Step 3:** Final summary for the user (do NOT push/PR unless asked).

## Self-review notes (already applied)

- Spec §2.2 fingerprint columns (`sqc_count_avg`, `sqc_count_maxdate`, `winding_total_fp`) DROPPED deliberately: `act_count`, `act_prod_doff`, `winding_total` are already ordinary snapshot columns on `jute_prod_spinning_daily`, so drift compares frozen-vs-fresh directly — the only schema addition needed is the unit index. (Weaving needed `sqc_pick_avg` because its log stores derived picks, not the raw AVG.)
- Spell-less `planning_grid` reads serve the LIVE slice even when some spells are locked (the lock switch requires the spell param); the FE planning tab always passes spell.
- BLOCK probe binds only `:tran_date`/`:spell_id` (daily_doff_tbl has no co scoping) — matches existing dedup/doff-net semantics; documented.
- Type consistency: `spinning_process_lock_id` PK used consistently across DDL, ORM, lock lookup, and process upsert; `_resolve_spell_id(db, spell)` signature (spinning's takes no branch arg, unlike weaving's).
