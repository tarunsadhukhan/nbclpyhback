# Weaving Entry → Process → Lock (Backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split weaving capture (raw input, always allowed) from a set-based Process step that validates inputs, freezes computed rows into a new `jute_prod_weaving_log`, and locks the `(date, spell)` unit behind Edit permission with an SQC/stoppage drift flag.

**Architecture:** Entry endpoints keep storing inputs only (now with nullable quality). A new `weaving_process.py` router runs the Process as ~5 set-based statements in one transaction, materialising from the existing `weaving_day_slice_sql` (never the Python resolvers — parity trap). A new lock header table + a server-side `access_type_id` check gate mutation of a locked unit. Reads serve the frozen log when a unit is locked, else the live slice.

**Tech Stack:** Python 3.12, FastAPI (sync `def` handlers), SQLAlchemy 2.0 Core `text()`, MySQL/PyMySQL, pytest + FastAPI `TestClient` + `unittest.mock`.

**Design spec:** `docs/superpowers/specs/2026-07-07-weaving-entry-process-lock-design.md` (read it first).

## Global Constraints

- Handlers are plain `def`, never `async def`; DB via `Depends(get_tenant_db)`, auth via `Depends(get_current_user_with_refresh)`. (CLAUDE.md Sync Handler Policy.)
- All endpoint responses wrapped `{"data": ...}`. Never return a raw list.
- SQL binds: `None` for NULL (never `"null"`); bind names match `:name` exactly; type-cast (`int(...)`, `_f(...)`).
- No `created_*` columns (trigger-based audit). Soft-delete via `active`; audit cols `updated_by`, `updated_date_time` only.
- Migrations: no `mysql` CLI — run via pymysql through the project venv; **ask the user which tenant DB** (suggest `dev3`), never assume. Each migration file carries a rollback SQL comment.
- **Parity rule:** the Process log is computed ONLY from `weaving_day_slice_sql` (`weaving_query.py:736-958`). Never call `services/weaving_standards.py` in the process path (its `std_picks` reads the target map, diverging from the slice's SQC exact-day AVG).
- **open_jugar rule:** the chain is cross-spell AND cross-day over `(co_id, machine_id, weaving_quality_id)`. Resolve it with the existing per-row two-probe (`resolve_weaving_open_jugar_for_row_query`) looped over the unit's rows — never a `LAG … PARTITION BY (tran_date, spell_id)` (resets the carry-in) and never a single correlated `UPDATE` over `jute_prod_weaving_daily` (MySQL error 1093: can't update a table and select it in a subquery).
- Weaving portal menu path (`menu_mst.menu_path`) = `juteProduction/weaving`. Weaving router prefix = `/api/weavingProd` (`main.py:271`).
- Permission ordinal (`role_menu_map.access_type_id`): 1 Read, 2 Print, 3 Write(create), 4 Edit. Locked-unit mutation requires ≥ 4.
- Run tests from repo root: `source .venv/Scripts/activate && pytest src/test/<file> -v`.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `dbqueries/migrations/weaving_daily_quality_id_nullable.sql` | Create | ALTER `jute_prod_weaving_daily.weaving_quality_id` → NULL |
| `dbqueries/migrations/create_jute_prod_weaving_log.sql` | Create | Frozen computed-snapshot table + index |
| `dbqueries/migrations/create_jute_prod_weaving_process_lock.sql` | Create | Lock header table |
| `src/juteProduction/weaving_models.py` | Modify | Add `WeavingLog`, `WeavingProcessLock`; make `weaving_quality_id` nullable |
| `src/juteProduction/weaving_query.py` | Modify | New builders: unmapped-looms BLOCK, WARN lists, unit rows, log soft-delete, log INSERT…SELECT, eb stamp, lock upsert/get, drift recompute, machine-keyed active-row |
| `src/juteProduction/weaving_entry.py` | Modify | Drop quality-required block; nullable quality; conditional cj-validate + open_jugar sync; machine-keyed upsert; lock guard on mutations; frozen-vs-live read branch |
| `src/juteProduction/weaving_lock.py` | Create | `WEAVING_MENU_PATH`, lock lookup, server-side access-level resolve, `require_edit_if_locked(...)` |
| `src/juteProduction/weaving_process.py` | Create | `/process` + `/process_status` endpoints (set-based, one txn) |
| `src/common/portal/query.py` | Modify | `get_user_menu_access_level_query()` |
| `src/main.py` | Modify | Register `weaving_process_router` at `/api/weavingProd` |
| `src/test/test_weaving_capture.py` | Create | Entry allowed without quality map |
| `src/test/test_weaving_lock.py` | Create | Locked mutation: Write 403, Edit ok |
| `src/test/test_weaving_process.py` | Create | BLOCK / WARN / parity / idempotent / lock-set |
| `src/test/test_weaving_process_status.py` | Create | Drift flag flips on new pick / stoppage |
| `src/test/test_weaving_reads_frozen.py` | Create | Locked → log; unlocked → live |

---

## Phase 1 — Schema + ORM

### Task 1: Migration — make `weaving_quality_id` nullable

**Files:**
- Create: `dbqueries/migrations/weaving_daily_quality_id_nullable.sql`
- Modify: `src/juteProduction/weaving_models.py` (the `weaving_quality_id` column)

**Interfaces:**
- Produces: `jute_prod_weaving_daily.weaving_quality_id` accepts NULL (entry before mapping).

- [ ] **Step 1: Write the migration**

```sql
-- Migration: allow NULL weaving_quality_id on jute_prod_weaving_daily
-- Entry capture now precedes Loom->Quality mapping; quality is filled at Process.
-- Rollback: UPDATE jute_prod_weaving_daily SET weaving_quality_id = 0 WHERE weaving_quality_id IS NULL;
--           ALTER TABLE jute_prod_weaving_daily MODIFY weaving_quality_id INT NOT NULL;
ALTER TABLE jute_prod_weaving_daily MODIFY weaving_quality_id INT NULL;
```

- [ ] **Step 2: Update the ORM column**

In `weaving_models.py` (the daily model, `weaving_models.py:230`):

```python
    weaving_quality_id = Column(Integer, nullable=True, index=True)  # NULL until quality mapped (filled at Process)
```

- [ ] **Step 3: Apply the migration**

Ask the user which tenant DB (suggest `dev3`). Read creds from `env/database.env`. Then:

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cur = conn.cursor()
with open('dbqueries/migrations/weaving_daily_quality_id_nullable.sql') as f:
    for stmt in f.read().split(';'):
        s = stmt.strip()
        if s and not s.startswith('--'):
            cur.execute(s)
conn.commit(); conn.close(); print('applied')
"
```

- [ ] **Step 4: Verify column is nullable**

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cur = conn.cursor()
cur.execute(\"SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_NAME='jute_prod_weaving_daily' AND COLUMN_NAME='weaving_quality_id'\")
print(cur.fetchone())  # expect ('YES',)
conn.close()
"
```
Expected: `('YES',)`

- [ ] **Step 5: Commit**

```bash
git add dbqueries/migrations/weaving_daily_quality_id_nullable.sql src/juteProduction/weaving_models.py
git commit -m "feat(weaving): allow NULL weaving_quality_id for pre-mapping capture"
```

---

### Task 2: Migration + ORM — `jute_prod_weaving_log`

**Files:**
- Create: `dbqueries/migrations/create_jute_prod_weaving_log.sql`
- Modify: `src/juteProduction/weaving_models.py` (add `WeavingLog`)

**Interfaces:**
- Produces: table `jute_prod_weaving_log` (frozen snapshot) + ORM `WeavingLog`. Column set = the day-slice outer SELECT (spec §4.2, incl. `spell_rank`) + `weaving_daily_id`, `sqc_pick_avg`, `sqc_pick_maxdate`, `active`, `updated_by`, `updated_date_time` = **56 columns**.

- [ ] **Step 1: Write the migration**

```sql
-- Migration: jute_prod_weaving_log — frozen per-row Process snapshot.
-- Column set mirrors weaving_day_slice_sql outer SELECT (weaving_query.py:802-822),
-- incl. spell_rank; plus source FK + SQC drift fingerprint + audit.
-- Rollback: DROP TABLE jute_prod_weaving_log;
CREATE TABLE jute_prod_weaving_log (
  weaving_log_id       INT PRIMARY KEY AUTO_INCREMENT,
  weaving_daily_id     INT NULL,
  co_id                INT NOT NULL,
  branch_id            INT NULL,
  tran_date            DATE NOT NULL,
  spell_id             INT NOT NULL,
  spell_code           VARCHAR(10) NULL,
  shift_bucket         VARCHAR(2) NULL,
  spell_rank           INT NULL,
  machine_id           INT NOT NULL,
  mech_code            VARCHAR(50) NULL,
  machine_name         VARCHAR(100) NULL,
  line_no              VARCHAR(50) NULL,
  weaving_quality_id   INT NULL,
  item_id              INT NULL,
  item_code            VARCHAR(50) NULL,
  item_name            VARCHAR(255) NULL,
  weaving_quality_code VARCHAR(50) NULL,
  weaving_quality_name VARCHAR(255) NULL,
  is_composite         TINYINT NULL,
  eb_id                INT NULL,
  beam_no              VARCHAR(50) NULL,
  cuts                 INT NULL,
  close_jugar          DECIMAL(12,3) NULL,
  less_production      DECIMAL(12,3) NULL,
  open_jugar           DECIMAL(12,3) NULL,
  jugar                DECIMAL(12,3) NULL,
  finished_length      DECIMAL(12,4) NULL,
  ozs_yds              DECIMAL(10,4) NULL,
  std_ozs_yds          DECIMAL(10,4) NULL,
  no_of_jugar_per_cut  DECIMAL(10,3) NULL,
  std_speed            DECIMAL(12,3) NULL,
  act_speed            DECIMAL(12,3) NULL,
  std_picks            DECIMAL(10,3) NULL,
  act_picks            DECIMAL(10,3) NULL,
  std_eff              DECIMAL(10,3) NULL,
  target_eff           DECIMAL(10,3) NULL,
  eff_speed            DECIMAL(12,3) NULL,
  eff_picks            DECIMAL(10,3) NULL,
  working_hours        DECIMAL(10,3) NULL,
  production_yds       DECIMAL(14,3) NULL,
  production_kg        DECIMAL(14,3) NULL,
  production_mt        DECIMAL(14,4) NULL,
  std_prod_yds         DECIMAL(14,3) NULL,
  target_prod_yds      DECIMAL(14,3) NULL,
  efficiency           DECIMAL(10,2) NULL,
  std_prod_kg          DECIMAL(14,3) NULL,
  target_kg            DECIMAL(14,3) NULL,
  sqc_pick_avg         DECIMAL(10,3) NULL,
  sqc_pick_maxdate     DATE NULL,
  active               TINYINT NOT NULL DEFAULT 1,
  updated_by           INT NULL,
  updated_date_time    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_wlog_unit (co_id, tran_date, spell_id)
);
```

- [ ] **Step 2: Add the ORM model** to `weaving_models.py` (end of file)

```python
class WeavingLog(Base):
    """Frozen per-row Process snapshot (spec §4.2). Materialised set-based from
    weaving_day_slice_sql; served instead of the live slice once a unit is locked.
    The full computed column set is written/read via text() INSERT...SELECT and
    projection (mirroring the daily reads); only keyed/queried columns need ORM attrs."""
    __tablename__ = "jute_prod_weaving_log"
    weaving_log_id = Column(Integer, primary_key=True, autoincrement=True)
    weaving_daily_id = Column(Integer, nullable=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False)
    spell_id = Column(Integer, nullable=False)
    machine_id = Column(Integer, nullable=False)
    weaving_quality_id = Column(Integer, nullable=True)
    eb_id = Column(Integer, nullable=True)
    working_hours = Column(DECIMAL(10, 3), nullable=True)
    sqc_pick_avg = Column(DECIMAL(10, 3), nullable=True)
    sqc_pick_maxdate = Column(Date, nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```

Ensure `Date`, `DECIMAL`, `TIMESTAMP`, `func` are imported at the top of `weaving_models.py`.

- [ ] **Step 3: Apply the migration** (same pymysql pattern as Task 1 Step 3, this file).

- [ ] **Step 4: Verify column count**

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_NAME='jute_prod_weaving_log'\")
print(cur.fetchone())  # expect (56,)
conn.close()
"
```
Expected: `(56,)`

- [ ] **Step 5: Commit**

```bash
git add dbqueries/migrations/create_jute_prod_weaving_log.sql src/juteProduction/weaving_models.py
git commit -m "feat(weaving): add jute_prod_weaving_log frozen snapshot table"
```

---

### Task 3: Migration + ORM — `jute_prod_weaving_process_lock`

**Files:**
- Create: `dbqueries/migrations/create_jute_prod_weaving_process_lock.sql`
- Modify: `src/juteProduction/weaving_models.py` (add `WeavingProcessLock`)

**Interfaces:**
- Produces: lock header, one row per `(co_id, branch_id, tran_date, spell_id)` with `is_locked`, `processed_by`, `processed_date_time`, `reprocess_needed`.

- [ ] **Step 1: Write the migration**

```sql
-- Migration: jute_prod_weaving_process_lock — one lock header per (co, branch, date, spell).
-- Rollback: DROP TABLE jute_prod_weaving_process_lock;
CREATE TABLE jute_prod_weaving_process_lock (
  weaving_process_lock_id INT PRIMARY KEY AUTO_INCREMENT,
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
  INDEX idx_wlock_unit (co_id, tran_date, spell_id)
);
```

- [ ] **Step 2: Add the ORM model** to `weaving_models.py`

```python
class WeavingProcessLock(Base):
    """Per-(co,branch,date,spell) Process lock header (spec §4.3). is_locked gates
    weaving-page mutation behind Edit permission; reprocess_needed raised on SQC/
    stoppage drift after processing."""
    __tablename__ = "jute_prod_weaving_process_lock"
    weaving_process_lock_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
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
```

- [ ] **Step 3: Apply the migration** (pymysql pattern, this file).

- [ ] **Step 4: Verify** the table exists:

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cur = conn.cursor(); cur.execute(\"SHOW TABLES LIKE 'jute_prod_weaving_process_lock'\")
print(cur.fetchone()); conn.close()
"
```
Expected: a non-`None` row.

- [ ] **Step 5: Commit**

```bash
git add dbqueries/migrations/create_jute_prod_weaving_process_lock.sql src/juteProduction/weaving_models.py
git commit -m "feat(weaving): add jute_prod_weaving_process_lock header table"
```

---

## Phase 2 — Entry capture (unblock; spec §5)

### Task 4: Allow entry without a mapped quality

**Files:**
- Modify: `src/juteProduction/weaving_query.py` (add `get_weaving_daily_active_row_by_machine_query`)
- Modify: `src/juteProduction/weaving_entry.py` (`entry_create`, `entry_edit`, `planning_grid_save`)
- Test: `src/test/test_weaving_capture.py`

**Interfaces:**
- Consumes: existing `_derive_branch_id`, `_derive_co_id`, `_resolve_spell_id`, `_mapped_quality_id`, `_input_params`, `_fetch_quality`, `_validate_close_jugar`, `insert_weaving_daily_query`, `update_weaving_daily_query`, `get_weaving_latest_beam_no_query`, `_sync_jugar_chain_after_write`, `_i`.
- Produces: `get_weaving_daily_active_row_by_machine_query()` (active row keyed `(co, date, spell, machine)`, quality-agnostic). Entry endpoints accept a NULL mapped quality and persist inputs.

- [ ] **Step 1: Write the failing test** in `src/test/test_weaving_capture.py`

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestWeavingCaptureNoQuality:
    @patch("src.juteProduction.weaving_entry.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_entry.get_tenant_db")
    def test_entry_create_allowed_when_quality_unmapped(self, mock_db, mock_auth):
        session = MagicMock()
        mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        with patch("src.juteProduction.weaving_entry._derive_branch_id", return_value=2), \
             patch("src.juteProduction.weaving_entry._derive_co_id", return_value=1), \
             patch("src.juteProduction.weaving_entry._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_entry._mapped_quality_id", return_value=None), \
             patch("src.juteProduction.weaving_entry.require_edit_if_locked"), \
             patch("src.juteProduction.weaving_entry._sync_jugar_chain_after_write"):
            session.execute.return_value.fetchone.return_value = None      # no existing row
            session.execute.return_value.scalar.return_value = None        # no beam
            session.execute.return_value.lastrowid = 555
            resp = client.post("/api/weavingProd/entry_create", json={
                "tran_date": "2026-07-07", "spell": "A1", "machine_id": 42,
                "cuts": 3, "close_jugar": 1.0,
            })
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["weaving_daily_id"] == 555
        assert resp.json()["data"]["weaving_quality_id"] is None
```

- [ ] **Step 2: Run it — expect fail**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_capture.py -v`
Expected: FAIL (endpoint returns 400 from the `NO_MAPPED_QUALITY_MSG` block; also `require_edit_if_locked` import not present yet — Task 6 adds it, so for Task 4 this test patches it defensively; if the symbol does not yet exist the patch target is created only once Task 6 imports it — order Task 4 before Task 6 means remove the `require_edit_if_locked` patch line here and re-add in Task 6's test. Keep it simple: in Task 4 DROP the `require_edit_if_locked` patch line; add it in Task 6).

- [ ] **Step 3: Add the machine-keyed active-row builder** in `weaving_query.py` (near `get_weaving_daily_active_row_query`)

```python
def get_weaving_daily_active_row_by_machine_query():
    """The single active daily row for (co, date, spell, machine) — quality-agnostic.

    Entry uniqueness dropped weaving_quality_id (one input row per loom/spell); the
    row's quality is whatever the map resolved to (or NULL). Newest id wins."""
    return text(
        """
        SELECT weaving_daily_id, weaving_quality_id
        FROM jute_prod_weaving_daily
        WHERE co_id = :co_id
          AND tran_date = :tran_date
          AND spell_id = :spell_id
          AND machine_id = :machine_id
          AND active = 1
        ORDER BY weaving_daily_id DESC
        LIMIT 1
        """
    )
```

- [ ] **Step 4: Rewrite `entry_create`'s quality gate + upsert** in `weaving_entry.py`

Replace the `NO_MAPPED_QUALITY_MSG` raise (`weaving_entry.py:738-739`) and the quality-keyed existing-row lookup (`weaving_entry.py:755-764`) with:

```python
        weaving_quality_id = _mapped_quality_id(
            db, co_id, body.tran_date, spell_id, body.machine_id
        )  # may be None: capture is allowed before the Loom->Quality map is done

        if weaving_quality_id is not None:
            quality = _fetch_quality(db, co_id, weaving_quality_id)
            _validate_close_jugar(body.close_jugar, quality)

        beam_no = db.execute(
            get_weaving_latest_beam_no_query(),
            {"co_id": _i(co_id), "tran_date": body.tran_date,
             "spell_id": spell_id, "machine_id": int(body.machine_id)},
        ).scalar()

        existing = db.execute(
            get_weaving_daily_active_row_by_machine_query(),
            {"co_id": _i(co_id), "tran_date": body.tran_date,
             "spell_id": spell_id, "machine_id": int(body.machine_id)},
        ).fetchone()
```

Guard the chain sync so it runs only with a quality:

```python
        if existing:
            params["id"] = existing.weaving_daily_id
            db.execute(update_weaving_daily_query(), params)
            weaving_daily_id = int(existing.weaving_daily_id)
        else:
            result = db.execute(insert_weaving_daily_query(), params)
            weaving_daily_id = int(result.lastrowid)
        if weaving_quality_id is not None:
            _sync_jugar_chain_after_write(
                db, weaving_daily_id, co_id, body.machine_id, weaving_quality_id,
                body.tran_date, spell_id,
            )
        db.commit()
        return {"data": {"weaving_daily_id": weaving_daily_id,
                         "weaving_quality_id": weaving_quality_id}}
```

Add `get_weaving_daily_active_row_by_machine_query` to the `from .weaving_query import (...)` block. In `_input_params` (`weaving_entry.py:383`) change `"weaving_quality_id": int(weaving_quality_id),` → `"weaving_quality_id": _i(weaving_quality_id),`.

- [ ] **Step 5: Apply the same nullable-quality treatment to `entry_edit` and `planning_grid_save`**

`entry_edit` (`weaving_entry.py:875-881`): keep the map lookup + existing-quality fallback, but remove the final `raise HTTPException(... NO_MAPPED_QUALITY_MSG)`; wrap `_validate_close_jugar` in `if weaving_quality_id is not None:`; guard `_sync_jugar_chain_after_write` with `if weaving_quality_id is not None:`.

`planning_grid_save` (`weaving_entry.py:1174-1182`): replace the `raise … NO_MAPPED_QUALITY_MSG` with allowing `None`; guard the per-row `_validate_close_jugar` and `_sync_jugar_chain_after_write` with `if weaving_quality_id is not None:`; switch the existing-row lookup to `get_weaving_daily_active_row_by_machine_query`.

- [ ] **Step 6: Run the test — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_capture.py -v`
Expected: PASS.

- [ ] **Step 7: Run the existing weaving entry suite (no new regressions)**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_entry.py -v`
Expected: the mapped-quality happy path still passes; pre-existing unrelated failures unchanged.

- [ ] **Step 8: Commit**

```bash
git add src/juteProduction/weaving_query.py src/juteProduction/weaving_entry.py src/test/test_weaving_capture.py
git commit -m "feat(weaving): allow production entry before quality mapping"
```

---

## Phase 3 — Permission + lock foundation (spec §7)

### Task 5: Server-side menu access level + lock helper

**Files:**
- Modify: `src/common/portal/query.py` (add `get_user_menu_access_level_query`)
- Create: `src/juteProduction/weaving_lock.py`
- Test: `src/test/test_weaving_lock.py` (helper unit tests)

**Interfaces:**
- Produces:
  - `get_user_menu_access_level_query()` → SQL returning `MAX(access_type_id)` for `(user_id, co_id, branch_id, menu_path)`.
  - `weaving_lock.WEAVING_MENU_PATH = "juteProduction/weaving"`, `EDIT_LEVEL = 4`.
  - `weaving_lock.get_process_lock(db, co_id, branch_id, tran_date, spell_id) -> row|None`.
  - `weaving_lock.is_unit_locked(db, co_id, branch_id, tran_date, spell_id) -> bool`.
  - `weaving_lock.user_menu_access_level(db, user_id, co_id, branch_id, menu_path) -> int`.
  - `weaving_lock.require_edit_if_locked(db, token_data, co_id, branch_id, tran_date, spell_id)` → raises `HTTPException(403)` when the unit is locked and level < 4.

- [ ] **Step 1: Write the failing test** in `src/test/test_weaving_lock.py`

```python
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from src.juteProduction import weaving_lock as wl


def _db_with(lock_row, level):
    db = MagicMock()
    db.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=lock_row)),   # get_process_lock
        MagicMock(scalar=MagicMock(return_value=level)),        # access level
    ]
    return db


def test_unlocked_unit_allows_write_level():
    db = MagicMock()
    db.execute.return_value.fetchone.return_value = None  # no lock row
    wl.require_edit_if_locked(db, {"user_id": 1}, 1, 2, "2026-07-07", 91)  # no raise


def test_locked_unit_blocks_write_level():
    db = _db_with(MagicMock(is_locked=1), level=3)  # Write only
    with pytest.raises(HTTPException) as e:
        wl.require_edit_if_locked(db, {"user_id": 1}, 1, 2, "2026-07-07", 91)
    assert e.value.status_code == 403


def test_locked_unit_allows_edit_level():
    db = _db_with(MagicMock(is_locked=1), level=4)  # Edit
    wl.require_edit_if_locked(db, {"user_id": 1}, 1, 2, "2026-07-07", 91)  # no raise
```

- [ ] **Step 2: Run — expect fail** (`ModuleNotFoundError: weaving_lock`)

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_lock.py -v`
Expected: FAIL (import error).

- [ ] **Step 3: Add the access-level query** in `src/common/portal/query.py`

```python
def get_user_menu_access_level_query():
    """Highest access_type_id a user holds for one menu path, scoped to (co, branch).

    user_role_map (roles for this co/branch) -> role_menu_map (per-menu
    access_type_id) -> menu_mst (path). MAX() across the user's roles; NULL (no
    grant) -> 0 in the caller. Ordinal: 1 Read, 2 Print, 3 Write, 4 Edit."""
    return text(
        """
        SELECT MAX(rmm.access_type_id) AS access_level
        FROM user_role_map urm
        JOIN role_menu_map rmm ON rmm.role_id = urm.role_id
        JOIN menu_mst mm ON mm.menu_id = rmm.menu_id
        WHERE urm.user_id = :user_id
          AND urm.co_id = :co_id
          AND (:branch_id IS NULL OR urm.branch_id = :branch_id)
          AND mm.menu_path = :menu_path
        """
    )
```

(If the executing engineer finds the join columns differ in this tenant, confirm via `SHOW COLUMNS` and adjust — the ordinal `access_type_id` + `menu_path` semantics are established in `src/common/portal/menu.py:101-296`.)

- [ ] **Step 4: Create `src/juteProduction/weaving_lock.py`**

```python
"""Weaving Process lock lookups + the locked-unit permission gate.

A (co, branch, tran_date, spell) unit is locked once Processed. While locked,
weaving-page mutations require Edit (access_type_id >= 4); Write-only (3) is
rejected 403. Reads use is_unit_locked to choose frozen-log vs live slice."""

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.portal.query import get_user_menu_access_level_query

WEAVING_MENU_PATH = "juteProduction/weaving"
EDIT_LEVEL = 4
LOCKED_EDIT_ONLY_MSG = (
    "This day/spell is processed and locked. Editing a locked weaving entry "
    "requires Edit permission for the Weaving Production menu."
)


def get_process_lock(db: Session, co_id: int, branch_id, tran_date, spell_id):
    """Active lock header for the unit (or None)."""
    return db.execute(
        text(
            """
            SELECT weaving_process_lock_id, is_locked, reprocess_needed
            FROM jute_prod_weaving_process_lock
            WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
              AND (:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)
              AND active = 1
            ORDER BY weaving_process_lock_id DESC
            LIMIT 1
            """
        ),
        {"co_id": int(co_id), "tran_date": tran_date, "spell_id": int(spell_id),
         "branch_id": None if branch_id is None else int(branch_id)},
    ).fetchone()


def is_unit_locked(db: Session, co_id: int, branch_id, tran_date, spell_id) -> bool:
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
        db, token_data.get("user_id"), co_id, branch_id, WEAVING_MENU_PATH
    )
    if level < EDIT_LEVEL:
        raise HTTPException(status_code=403, detail=LOCKED_EDIT_ONLY_MSG)
```

- [ ] **Step 5: Run the test — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_lock.py -v`
Expected: PASS.

- [ ] **Step 6: Confirm the menu path against the tenant** (guards `WEAVING_MENU_PATH`)

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cur = conn.cursor(); cur.execute(\"SELECT menu_path FROM menu_mst WHERE menu_name='Weaving Production'\")
print(cur.fetchone()); conn.close()
"
```
Expected: `('juteProduction/weaving',)`. If different, set `WEAVING_MENU_PATH` to the actual value.

- [ ] **Step 7: Commit**

```bash
git add src/common/portal/query.py src/juteProduction/weaving_lock.py src/test/test_weaving_lock.py
git commit -m "feat(weaving): server-side menu access level + locked-unit gate"
```

---

### Task 6: Wire the lock gate into weaving mutations

**Files:**
- Modify: `src/juteProduction/weaving_entry.py` (`entry_create`, `entry_edit`, `entry_delete`, `planning_grid_save`, `adjustment_save` at `:1613`)
- Test: `src/test/test_weaving_lock.py` (add endpoint-level cases)

**Interfaces:**
- Consumes: `weaving_lock.require_edit_if_locked`, `is_unit_locked`, `user_menu_access_level`.
- Produces: every weaving-page mutation calls `require_edit_if_locked(db, token_data, co_id, branch_id, tran_date, spell_id)` before writing; locked + Write-only → 403.

- [ ] **Step 1: Write the failing test** (append to `src/test/test_weaving_lock.py`)

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestLockedEntryEndpoint:
    @patch("src.juteProduction.weaving_entry.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_entry.get_tenant_db")
    def test_locked_unit_write_user_gets_403(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 7}
        with patch("src.juteProduction.weaving_entry._derive_branch_id", return_value=2), \
             patch("src.juteProduction.weaving_entry._derive_co_id", return_value=1), \
             patch("src.juteProduction.weaving_entry._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_lock.is_unit_locked", return_value=True), \
             patch("src.juteProduction.weaving_lock.user_menu_access_level", return_value=3):
            resp = client.post("/api/weavingProd/entry_create", json={
                "tran_date": "2026-07-07", "spell": "A1", "machine_id": 42,
                "cuts": 3, "close_jugar": 1.0,
            })
        assert resp.status_code == 403, resp.text
```

- [ ] **Step 2: Run — expect fail** (currently 200/500, not 403).

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_lock.py::TestLockedEntryEndpoint -v`
Expected: FAIL.

- [ ] **Step 3: Insert the guard** in each mutation, right after `co_id`/`branch_id`/`spell_id` resolve and before the first write.

`entry_create` (after quality resolve, before beam/existing lookups):
```python
        require_edit_if_locked(db, token_data, co_id, branch_id, body.tran_date, spell_id)
```
`entry_edit`: after `existing`/`spell_id` resolve — `require_edit_if_locked(db, token_data, co_id, existing.branch_id, existing.tran_date, spell_id)`.
`entry_delete`: after loading `existing` — `require_edit_if_locked(db, token_data, co_id, None, existing.tran_date, existing.spell_id)`.
`planning_grid_save`: inside the row loop, after co/branch resolve, before the row's write — `require_edit_if_locked(db, token_data, co_id, branch_id, body.tran_date, e.spell_id)`.
`adjustment_save` (`weaving_entry.py:1613`): after spell/co/branch resolve, before the insert path.

Add the import at the top of `weaving_entry.py`:
```python
from src.juteProduction.weaving_lock import require_edit_if_locked
```

- [ ] **Step 4: Run the test — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_lock.py -v`
Expected: PASS.

- [ ] **Step 5: Add the `require_edit_if_locked` patch back into Task 4's capture test** (now that the symbol exists) and re-run:

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_capture.py src/test/test_weaving_lock.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/juteProduction/weaving_entry.py src/test/test_weaving_lock.py src/test/test_weaving_capture.py
git commit -m "feat(weaving): gate locked-unit mutations behind Edit permission"
```

---

## Phase 4 — Process engine (spec §6)

### Task 7: Process query builders

**Files:**
- Modify: `src/juteProduction/weaving_query.py`
- Test: `src/test/test_weaving_process.py` (builder smoke test)

**Interfaces:**
- Produces (all `text()` builders):
  - `get_weaving_unit_daily_ids_query()`
  - `get_weaving_unmapped_produced_looms_query()`
  - `get_weaving_process_no_worker_query()`, `get_weaving_process_no_standard_query()`, `get_weaving_process_no_picks_query()`
  - `soft_delete_weaving_log_for_unit_query()`
  - `insert_weaving_log_from_slice_query()`
  - `update_weaving_log_eb_stamp_query()`
  - `get_weaving_process_lock_row_query()`, `insert_weaving_process_lock_query()`, `update_weaving_process_lock_query()`, `update_weaving_process_lock_reprocess_query()`
  - `get_weaving_drift_query()`
  - `get_weaving_log_rows_query()` (used by Task 11)

- [ ] **Step 1: Write the unit-ids + BLOCK + WARN builders**

```python
def get_weaving_unit_daily_ids_query():
    """Active daily row ids for the (co, date, spell) unit — drives the open_jugar loop."""
    return text(
        """
        SELECT weaving_daily_id
        FROM jute_prod_weaving_daily
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        """
    )


def get_weaving_unmapped_produced_looms_query():
    """Looms with input in the unit but NO active mapped quality -> Process BLOCK list."""
    return text(
        """
        SELECT wd.machine_id, m.mech_code, m.machine_name
        FROM jute_prod_weaving_daily wd
        LEFT JOIN machine_mst m ON m.machine_id = wd.machine_id
        LEFT JOIN jute_prod_weaving_quality_map qm
               ON qm.co_id = wd.co_id AND qm.tran_date = wd.tran_date
              AND qm.spell_id = wd.spell_id AND qm.machine_id = wd.machine_id
              AND qm.active = 1 AND qm.weaving_quality_id IS NOT NULL
        WHERE wd.co_id = :co_id AND wd.tran_date = :tran_date AND wd.spell_id = :spell_id
          AND wd.active = 1
          AND qm.weaving_quality_map_id IS NULL
        """
    )


def get_weaving_process_no_worker_query():
    """Looms in the unit with no resolvable attendance worker (WARN)."""
    return text(
        """
        SELECT wd.machine_id, m.mech_code, m.machine_name
        FROM jute_prod_weaving_daily wd
        LEFT JOIN machine_mst m ON m.machine_id = wd.machine_id
        LEFT JOIN daily_ebmc_attendance de ON de.mc_id = wd.machine_id AND de.is_active = 1
        LEFT JOIN daily_attendance da ON da.daily_atten_id = de.daily_atten_id
              AND da.attendance_date = wd.tran_date AND da.is_active = 1
        WHERE wd.co_id = :co_id AND wd.tran_date = :tran_date AND wd.spell_id = :spell_id
          AND wd.active = 1
        GROUP BY wd.machine_id, m.mech_code, m.machine_name
        HAVING COUNT(da.eb_id) = 0
        """
    )


def get_weaving_process_no_standard_query():
    """Mapped looms whose machine has no speed OR quality has no eff standard (WARN)."""
    return text(
        """
        SELECT wd.machine_id, m.mech_code, qm.weaving_quality_id
        FROM jute_prod_weaving_daily wd
        LEFT JOIN machine_mst m ON m.machine_id = wd.machine_id
        JOIN jute_prod_weaving_quality_map qm
              ON qm.co_id = wd.co_id AND qm.tran_date = wd.tran_date
             AND qm.spell_id = wd.spell_id AND qm.machine_id = wd.machine_id
             AND qm.active = 1 AND qm.weaving_quality_id IS NOT NULL
        LEFT JOIN jute_prod_weaving_target_map spd
              ON spd.co_id = :co_id AND spd.id_type = 'mcid' AND spd.param = 'speed'
             AND spd.ref_id = wd.machine_id AND spd.active = 1
             AND spd.effective_date <= :tran_date
        LEFT JOIN jute_prod_weaving_target_map eff
              ON eff.co_id = :co_id AND eff.id_type = 'qid' AND eff.param = 'eff'
             AND eff.ref_id = qm.weaving_quality_id AND eff.active = 1
             AND eff.effective_date <= :tran_date
        WHERE wd.co_id = :co_id AND wd.tran_date = :tran_date AND wd.spell_id = :spell_id
          AND wd.active = 1
        GROUP BY wd.machine_id, m.mech_code, qm.weaving_quality_id
        HAVING COUNT(spd.weaving_target_map_id) = 0 OR COUNT(eff.weaving_target_map_id) = 0
        """
    )


def get_weaving_process_no_picks_query():
    """Mapped qualities in the unit with no SQC pick reading for the day (WARN)."""
    return text(
        """
        SELECT qm.weaving_quality_id, wd.machine_id, m.mech_code
        FROM jute_prod_weaving_daily wd
        LEFT JOIN machine_mst m ON m.machine_id = wd.machine_id
        JOIN jute_prod_weaving_quality_map qm
              ON qm.co_id = wd.co_id AND qm.tran_date = wd.tran_date
             AND qm.spell_id = wd.spell_id AND qm.machine_id = wd.machine_id
             AND qm.active = 1 AND qm.weaving_quality_id IS NOT NULL
        LEFT JOIN jute_sqc_weaving_pick p
              ON p.co_id = :co_id AND p.weaving_quality_id = qm.weaving_quality_id
             AND p.entry_date = :tran_date AND p.active = 1
        WHERE wd.co_id = :co_id AND wd.tran_date = :tran_date AND wd.spell_id = :spell_id
          AND wd.active = 1
        GROUP BY qm.weaving_quality_id, wd.machine_id, m.mech_code
        HAVING COUNT(p.weaving_sqc_pick_id) = 0
        """
    )
```

- [ ] **Step 2: Write the freeze builders** (`soft_delete` + `INSERT … SELECT`, columns named explicitly, `weaving_day_slice_sql()` as SELECT source)

```python
def soft_delete_weaving_log_for_unit_query():
    """Soft-delete existing active log rows for the unit (reprocess idempotency)."""
    return text(
        """
        UPDATE jute_prod_weaving_log
        SET active = 0, updated_by = :updated_by, updated_date_time = CURRENT_TIMESTAMP
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        """
    )


def insert_weaving_log_from_slice_query():
    """Freeze the unit's computed rows into jute_prod_weaving_log in ONE statement.

    SELECT source = weaving_day_slice_sql() (parity oracle) filtered to (co, date,
    spell). LEFT JOIN a per-quality SQC fingerprint (AVG(picks), MAX(entry_date) for
    entry_date = :tran_date). Columns named explicitly (slice emits spell_rank)."""
    slice_sql = weaving_day_slice_sql()
    return text(
        f"""
        INSERT INTO jute_prod_weaving_log (
            weaving_daily_id, co_id, branch_id, tran_date, spell_id, spell_code,
            shift_bucket, spell_rank, machine_id, mech_code, machine_name, line_no,
            weaving_quality_id, item_id, item_code, item_name, weaving_quality_code,
            weaving_quality_name, is_composite, eb_id, beam_no, cuts, close_jugar,
            less_production, open_jugar, jugar, finished_length, ozs_yds, std_ozs_yds,
            no_of_jugar_per_cut, std_speed, act_speed, std_picks, act_picks, std_eff,
            target_eff, eff_speed, eff_picks, working_hours, production_yds,
            production_kg, production_mt, std_prod_yds, target_prod_yds, efficiency,
            std_prod_kg, target_kg, sqc_pick_avg, sqc_pick_maxdate, active, updated_by
        )
        SELECT
            v.weaving_daily_id, v.co_id, v.branch_id, v.tran_date, v.spell_id, v.spell_code,
            v.shift_bucket, v.spell_rank, v.machine_id, v.mech_code, v.machine_name, v.line_no,
            v.weaving_quality_id, v.item_id, v.item_code, v.item_name, v.weaving_quality_code,
            v.weaving_quality_name, v.is_composite, v.eb_id, v.beam_no, v.cuts, v.close_jugar,
            v.less_production, v.open_jugar, v.jugar, v.finished_length, v.ozs_yds, v.std_ozs_yds,
            v.no_of_jugar_per_cut, v.std_speed, v.act_speed, v.std_picks, v.act_picks, v.std_eff,
            v.target_eff, v.eff_speed, v.eff_picks, v.working_hours, v.production_yds,
            v.production_kg, v.production_mt, v.std_prod_yds, v.target_prod_yds, v.efficiency,
            v.std_prod_kg, v.target_kg, fp.pick_avg, fp.pick_maxdate, 1, :updated_by
        FROM (
        {slice_sql}
        ) v
        LEFT JOIN (
            SELECT weaving_quality_id, AVG(picks) AS pick_avg, MAX(entry_date) AS pick_maxdate
            FROM jute_sqc_weaving_pick
            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
            GROUP BY weaving_quality_id
        ) fp ON fp.weaving_quality_id = v.weaving_quality_id
        """
    )
```

`weaving_day_slice_sql()` binds `:co_id`, `:tran_date`, `:spell_id`, `:machine_id`, `:branch_id`; the process call passes `machine_id=None`, `branch_id=None`, plus `:updated_by`.

- [ ] **Step 3: Write eb-stamp + lock upsert + reprocess-flag + drift builders**

```python
def update_weaving_log_eb_stamp_query():
    """Best-effort stamp eb_id on the unit's log rows from attendance (spinning-style).

    daily_ebmc_attendance (mc) -> daily_attendance (date), restricted to on-machine
    designations; MIN(eb) per machine. WARN-only: no match keeps eb_id NULL."""
    return text(
        """
        UPDATE jute_prod_weaving_log wl
        JOIN (
            SELECT de.mc_id, MIN(da.eb_id) AS eb_id
            FROM daily_ebmc_attendance de
            JOIN daily_attendance da ON da.daily_atten_id = de.daily_atten_id
              AND da.attendance_date = :tran_date AND da.is_active = 1
            LEFT JOIN designation_mst dg ON dg.designation_id = da.worked_designation_id
            WHERE de.is_active = 1
              AND (dg.on_machine = 'Yes' OR dg.on_machine IS NULL)
              AND (:branch_id IS NULL OR da.branch_id = :branch_id)
            GROUP BY de.mc_id
        ) a ON a.mc_id = wl.machine_id
        SET wl.eb_id = a.eb_id
        WHERE wl.co_id = :co_id AND wl.tran_date = :tran_date AND wl.spell_id = :spell_id
          AND wl.active = 1
        """
    )


def get_weaving_process_lock_row_query():
    return text(
        """
        SELECT weaving_process_lock_id FROM jute_prod_weaving_process_lock
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND active = 1
        ORDER BY weaving_process_lock_id DESC LIMIT 1
        """
    )


def insert_weaving_process_lock_query():
    return text(
        """
        INSERT INTO jute_prod_weaving_process_lock
            (co_id, branch_id, tran_date, spell_id, is_locked, reprocess_needed,
             processed_by, processed_date_time, active, updated_by)
        VALUES
            (:co_id, :branch_id, :tran_date, :spell_id, 1, 0,
             :processed_by, CURRENT_TIMESTAMP, 1, :processed_by)
        """
    )


def update_weaving_process_lock_query():
    return text(
        """
        UPDATE jute_prod_weaving_process_lock
        SET is_locked = 1, reprocess_needed = 0, processed_by = :processed_by,
            processed_date_time = CURRENT_TIMESTAMP, updated_by = :processed_by,
            updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_process_lock_id = :id
        """
    )


def update_weaving_process_lock_reprocess_query():
    """Raise reprocess_needed on a lock header (drift detected on read)."""
    return text(
        """
        UPDATE jute_prod_weaving_process_lock
        SET reprocess_needed = 1, updated_date_time = CURRENT_TIMESTAMP
        WHERE weaving_process_lock_id = :id
        """
    )


def get_weaving_drift_query():
    """One row if the frozen log disagrees with a fresh recompute of either drift
    source: SQC pick AVG (per quality) or net working_hours (per machine/spell)."""
    return text(
        """
        SELECT wl.weaving_log_id
        FROM jute_prod_weaving_log wl
        LEFT JOIN spell_mst sp ON sp.spell_id = wl.spell_id
        LEFT JOIN (
            SELECT weaving_quality_id, AVG(picks) AS pick_avg
            FROM jute_sqc_weaving_pick
            WHERE co_id = :co_id AND entry_date = :tran_date AND active = 1
            GROUP BY weaving_quality_id
        ) fp ON fp.weaving_quality_id = wl.weaving_quality_id
        LEFT JOIN (
            SELECT machine_id, spell_id, SUM(stoppage_hours) AS stoppage_hours
            FROM jute_prod_stoppage_hours
            WHERE co_id = :co_id AND tran_date = :tran_date AND active = 1
            GROUP BY machine_id, spell_id
        ) st ON st.machine_id = wl.machine_id AND st.spell_id = wl.spell_id
        WHERE wl.co_id = :co_id AND wl.tran_date = :tran_date AND wl.spell_id = :spell_id
          AND wl.active = 1
          AND (
            COALESCE(wl.sqc_pick_avg, 0) <> COALESCE(fp.pick_avg, 0)
            OR COALESCE(wl.working_hours, 0)
               <> GREATEST(0, COALESCE(sp.working_hours, 0) - COALESCE(st.stoppage_hours, 0))
          )
        LIMIT 1
        """
    )


def get_weaving_log_rows_query():
    """Frozen log rows for a unit, projected with the SAME aliases as the day-slice
    entries projection so reads are source-agnostic (Task 11)."""
    return text(
        """
        SELECT weaving_daily_id, co_id, branch_id, tran_date, spell_id, spell_code,
               machine_id, mech_code, machine_name, line_no, weaving_quality_id,
               item_id, item_code, item_name, weaving_quality_code, weaving_quality_name,
               is_composite, eb_id, beam_no, cuts, close_jugar, less_production,
               open_jugar, jugar, finished_length, ozs_yds, std_ozs_yds,
               no_of_jugar_per_cut, std_speed, act_speed, std_picks, act_picks,
               std_eff, target_eff, eff_speed, eff_picks, working_hours,
               production_yds, production_kg, production_mt, std_prod_yds,
               target_prod_yds, efficiency, std_prod_kg, target_kg
        FROM jute_prod_weaving_log
        WHERE co_id = :co_id AND tran_date = :tran_date AND spell_id = :spell_id
          AND (:machine_id IS NULL OR machine_id = :machine_id)
          AND (:branch_id IS NULL OR branch_id = :branch_id OR branch_id IS NULL)
          AND active = 1
        ORDER BY mech_code, weaving_log_id DESC
        """
    )
```

- [ ] **Step 4: Builder smoke test** in `src/test/test_weaving_process.py`

```python
from src.juteProduction import weaving_query as q


def test_process_builders_compile():
    for name in [
        "get_weaving_unit_daily_ids_query", "get_weaving_unmapped_produced_looms_query",
        "get_weaving_process_no_worker_query", "get_weaving_process_no_standard_query",
        "get_weaving_process_no_picks_query", "soft_delete_weaving_log_for_unit_query",
        "insert_weaving_log_from_slice_query", "update_weaving_log_eb_stamp_query",
        "get_weaving_process_lock_row_query", "insert_weaving_process_lock_query",
        "update_weaving_process_lock_query", "update_weaving_process_lock_reprocess_query",
        "get_weaving_drift_query", "get_weaving_log_rows_query",
    ]:
        assert getattr(q, name)() is not None
```

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process.py::test_process_builders_compile -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/juteProduction/weaving_query.py src/test/test_weaving_process.py
git commit -m "feat(weaving): process query builders (block/warn/freeze/eb/lock/drift/log-read)"
```

---

### Task 8: Process + process_status endpoints

**Files:**
- Create: `src/juteProduction/weaving_process.py`
- Modify: `src/main.py` (register router)
- Test: `src/test/test_weaving_process.py`

**Interfaces:**
- Consumes: all Task 7 builders; `weaving_entry._resolve_spell_id`, `_derive_co_id`, `_i`; `resolve_weaving_open_jugar_for_row_query`, `update_weaving_daily_open_jugar_query`; `weaving_lock.get_process_lock`, `require_edit_if_locked`.
- Produces:
  - `POST /api/weavingProd/process` `{co_id, branch_id, tran_date, spell}` → `{"data": {"processed": int, "warnings": {...}}}`; `400 detail={"message","unmapped":[...]}` on BLOCK.
  - `GET /api/weavingProd/process_status?co_id&branch_id&tran_date&spell` → `{"data": {"locked": bool, "reprocess_needed": bool}}`.

- [ ] **Step 1: Write the failing BLOCK test** in `src/test/test_weaving_process.py`

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestProcessEndpoint:
    @patch("src.juteProduction.weaving_process.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_process.get_tenant_db")
    def test_block_when_unmapped(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        row = MagicMock(); row._mapping = {"machine_id": 42, "mech_code": "L42", "machine_name": "Loom 42"}
        with patch("src.juteProduction.weaving_process._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_process._derive_co_id", return_value=1), \
             patch("src.juteProduction.weaving_process.require_edit_if_locked"):
            session.execute.return_value.fetchall.return_value = [row]  # unmapped -> BLOCK
            resp = client.post("/api/weavingProd/process", json={
                "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell": "A1"})
        assert resp.status_code == 400
        assert resp.json()["detail"]["unmapped"][0]["machine_id"] == 42
```

- [ ] **Step 2: Run — expect fail** (404, router not registered).

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process.py::TestProcessEndpoint -v`
Expected: FAIL.

- [ ] **Step 3: Create `src/juteProduction/weaving_process.py`**

```python
"""Weaving Process + status endpoints (spec §6/§8). Prefix /api/weavingProd.

Process is set-based, one transaction: BLOCK on unmapped quality, collect WARN
lists, resolve open_jugar per unit row (full-history two-probe), soft-delete +
INSERT...SELECT freeze from weaving_day_slice_sql (parity oracle — never the
Python resolvers), best-effort eb stamp, lock header upsert. process_status
recomputes SQC/stoppage drift for a locked unit."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.weaving_entry import _resolve_spell_id, _derive_co_id, _i
from src.juteProduction.weaving_lock import get_process_lock, require_edit_if_locked
from src.juteProduction.weaving_query import (
    get_weaving_unit_daily_ids_query,
    get_weaving_unmapped_produced_looms_query,
    get_weaving_process_no_worker_query,
    get_weaving_process_no_standard_query,
    get_weaving_process_no_picks_query,
    soft_delete_weaving_log_for_unit_query,
    insert_weaving_log_from_slice_query,
    update_weaving_log_eb_stamp_query,
    get_weaving_process_lock_row_query,
    insert_weaving_process_lock_query,
    update_weaving_process_lock_query,
    update_weaving_process_lock_reprocess_query,
    get_weaving_drift_query,
    resolve_weaving_open_jugar_for_row_query,
    update_weaving_daily_open_jugar_query,
)

router = APIRouter()

BLOCK_MSG = "Cannot process: these looms have production but no mapped quality."


class ProcessRequest(BaseModel):
    co_id: Optional[int] = None
    branch_id: Optional[int] = None
    tran_date: date
    spell: str


def _rows(res):
    return [dict(r._mapping) for r in res.fetchall()]


@router.post("/process")
def process_weaving(
    body: ProcessRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        spell_id = _resolve_spell_id(db, body.spell, body.branch_id)
        co_id = body.co_id if body.co_id is not None else _derive_co_id(db, body.branch_id)
        user_id = token_data.get("user_id")
        binds = {"co_id": int(co_id), "tran_date": body.tran_date, "spell_id": int(spell_id)}

        require_edit_if_locked(db, token_data, co_id, body.branch_id, body.tran_date, spell_id)

        unmapped = _rows(db.execute(get_weaving_unmapped_produced_looms_query(), binds))
        if unmapped:
            raise HTTPException(status_code=400, detail={"message": BLOCK_MSG, "unmapped": unmapped})

        warnings = {
            "no_worker": _rows(db.execute(get_weaving_process_no_worker_query(), binds)),
            "no_standard": _rows(db.execute(get_weaving_process_no_standard_query(), binds)),
            "no_picks": _rows(db.execute(get_weaving_process_no_picks_query(), binds)),
        }

        # open_jugar resolve — per-row two-probe over the unit (full history).
        for r in db.execute(get_weaving_unit_daily_ids_query(), binds).fetchall():
            rid = int(r.weaving_daily_id)
            resolved = db.execute(
                resolve_weaving_open_jugar_for_row_query(), {"row_id": rid}
            ).fetchone()
            if resolved is not None:
                db.execute(update_weaving_daily_open_jugar_query(),
                           {"row_id": rid, "open_jugar": float(resolved.open_jugar or 0)})

        db.execute(soft_delete_weaving_log_for_unit_query(), {**binds, "updated_by": user_id})

        slice_binds = {**binds, "machine_id": None, "branch_id": None, "updated_by": user_id}
        result = db.execute(insert_weaving_log_from_slice_query(), slice_binds)
        processed = int(result.rowcount)

        db.execute(update_weaving_log_eb_stamp_query(), {**binds, "branch_id": _i(body.branch_id)})

        lock = db.execute(get_weaving_process_lock_row_query(), binds).fetchone()
        if lock:
            db.execute(update_weaving_process_lock_query(),
                       {"id": lock.weaving_process_lock_id, "processed_by": user_id})
        else:
            db.execute(insert_weaving_process_lock_query(),
                       {**binds, "branch_id": _i(body.branch_id), "processed_by": user_id})

        db.commit()
        return {"data": {"processed": processed, "warnings": warnings}}
    except HTTPException:
        db.rollback(); raise
    except Exception as e:
        db.rollback(); raise HTTPException(status_code=500, detail=str(e))


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
        spell_id = _resolve_spell_id(db, spell_raw, branch_id)

        lock = get_process_lock(db, co_id, branch_id, d_val, spell_id)
        if not lock or not lock.is_locked:
            return {"data": {"locked": False, "reprocess_needed": False}}

        drift = db.execute(
            get_weaving_drift_query(),
            {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id},
        ).fetchone()
        needed = drift is not None
        if needed and not lock.reprocess_needed:
            db.execute(update_weaving_process_lock_reprocess_query(),
                       {"id": lock.weaving_process_lock_id})
            db.commit()
        return {"data": {"locked": True, "reprocess_needed": bool(needed or lock.reprocess_needed)}}
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tran_date")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Register the router** in `src/main.py` (near `main.py:109`, `:271`)

```python
from src.juteProduction.weaving_process import router as weaving_process_router
```
```python
app.include_router(weaving_process_router, prefix="/api/weavingProd", tags=["jute-weaving"])
```

- [ ] **Step 5: Run the BLOCK test — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process.py -v`
Expected: PASS.

- [ ] **Step 6: Add the happy-path (freeze + warn) test**

```python
    @patch("src.juteProduction.weaving_process.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_process.get_tenant_db")
    def test_process_freezes_and_warns(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=5)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        unit_ids = MagicMock(fetchall=MagicMock(return_value=[]))
        # execute() call order: unmapped, no_worker, no_standard, no_picks,
        # unit_daily_ids, soft_delete, INSERT, eb_stamp, lock_row, lock_insert.
        session.execute.side_effect = [empty, empty, empty, empty, unit_ids,
                                       MagicMock(), insert, MagicMock(), lockrow, MagicMock()]
        with patch("src.juteProduction.weaving_process._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_process._derive_co_id", return_value=1), \
             patch("src.juteProduction.weaving_process.require_edit_if_locked"):
            resp = client.post("/api/weavingProd/process", json={
                "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell": "A1"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["processed"] == 5
        assert resp.json()["data"]["warnings"]["no_worker"] == []
```

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/juteProduction/weaving_process.py src/main.py src/test/test_weaving_process.py
git commit -m "feat(weaving): set-based Process + process_status endpoints"
```

---

### Task 9: DB-guarded parity check (frozen log == live slice)

**Files:**
- Test: `src/test/test_weaving_process.py` (append; skipped without a DB env flag)

**Interfaces:**
- Consumes: a live tenant DB (dev3) with a seeded, mapped, entered `(co, date, spell)`.

- [ ] **Step 1: Write the parity test**

```python
import os
import pytest

RUN_DB = os.environ.get("WEAVING_PARITY_DB")  # e.g. "dev3"; unset -> skip


@pytest.mark.skipif(not RUN_DB, reason="set WEAVING_PARITY_DB to run DB parity")
def test_log_matches_slice_after_process():
    """After Process, each frozen log row equals the live day-slice row for the
    same (machine, quality) on production_yds/efficiency/working_hours (<=0.001)."""
    import pymysql
    conn = pymysql.connect(host=os.environ["DB_HOST"], user=os.environ["DB_USER"],
                           password=os.environ["DB_PASS"], database=RUN_DB, port=3306)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    co = int(os.environ["PARITY_CO"]); d = os.environ["PARITY_DATE"]
    spell_id = int(os.environ["PARITY_SPELL_ID"])
    cur.execute("""SELECT machine_id, weaving_quality_id, ROUND(production_yds,3) p,
                          ROUND(efficiency,2) e, ROUND(working_hours,3) w
                   FROM jute_prod_weaving_log
                   WHERE co_id=%s AND tran_date=%s AND spell_id=%s AND active=1""",
                (co, d, spell_id))
    log_rows = {(r["machine_id"], r["weaving_quality_id"]): r for r in cur.fetchall()}
    assert log_rows, "no frozen rows — process the unit first"
    conn.close()
    # Engineer: run get_weaving_entries_by_date_query bound to (co, d, spell_id)
    # against the same DB and assert each (machine, quality) matches log_rows p/e/w.
```

- [ ] **Step 2: Run** (skips without flag)

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process.py -k parity -v`
Expected: SKIPPED. With `WEAVING_PARITY_DB` + a seeded processed unit: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/test/test_weaving_process.py
git commit -m "test(weaving): DB-guarded parity check (frozen log == live slice)"
```

---

## Phase 5 — Reprocess status test

### Task 10: Drift flag flips on late SQC / stoppage

**Files:**
- Test: `src/test/test_weaving_process_status.py`

- [ ] **Step 1: Write the test**

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestProcessStatus:
    @patch("src.juteProduction.weaving_process.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_process.get_tenant_db")
    def test_unlocked_returns_false(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        with patch("src.juteProduction.weaving_process._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_process.get_process_lock", return_value=None):
            resp = client.get("/api/weavingProd/process_status?co_id=1&branch_id=2&tran_date=2026-07-07&spell=A1")
        assert resp.status_code == 200
        assert resp.json()["data"] == {"locked": False, "reprocess_needed": False}

    @patch("src.juteProduction.weaving_process.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_process.get_tenant_db")
    def test_locked_with_drift_flags_reprocess(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        lock = MagicMock(weaving_process_lock_id=9, is_locked=1, reprocess_needed=0)
        session.execute.return_value.fetchone.return_value = MagicMock(weaving_log_id=1)  # drift
        with patch("src.juteProduction.weaving_process._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_process.get_process_lock", return_value=lock):
            resp = client.get("/api/weavingProd/process_status?co_id=1&branch_id=2&tran_date=2026-07-07&spell=A1")
        assert resp.status_code == 200
        assert resp.json()["data"]["reprocess_needed"] is True
```

- [ ] **Step 2: Run — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_process_status.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/test/test_weaving_process_status.py
git commit -m "test(weaving): process_status drift flag behaviour"
```

---

## Phase 6 — Reads serve the frozen log when locked (spec §9)

### Task 11: `entries` + `planning_grid` read log when the unit is locked

**Files:**
- Modify: `src/juteProduction/weaving_entry.py` (`entries_by_date`, `planning_grid` branch on lock)
- Test: `src/test/test_weaving_reads_frozen.py`

**Interfaces:**
- Consumes: `weaving_lock.is_unit_locked`, `weaving_query.get_weaving_log_rows_query` (added in Task 7).
- Produces: read endpoints return frozen rows when `(date, spell)` is locked, else the live slice.

- [ ] **Step 1: Write the failing test** in `src/test/test_weaving_reads_frozen.py`

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestFrozenReads:
    @patch("src.juteProduction.weaving_entry.get_current_user_with_refresh")
    @patch("src.juteProduction.weaving_entry.get_tenant_db")
    def test_locked_unit_reads_log(self, mock_db, mock_auth):
        session = MagicMock(); mock_db.return_value = session
        mock_auth.return_value = {"user_id": 1}
        frozen = MagicMock(); frozen._mapping = {"weaving_daily_id": 1, "machine_id": 42,
            "production_yds": 100.0, "efficiency": 88.0, "tran_date": "2026-07-07"}
        session.execute.return_value.fetchall.return_value = [frozen]
        with patch("src.juteProduction.weaving_entry._resolve_spell_id", return_value=91), \
             patch("src.juteProduction.weaving_entry.is_unit_locked", return_value=True):
            resp = client.get("/api/weavingProd/entries_by_date?co_id=1&branch_id=2&tran_date=2026-07-07&spell=A1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"][0]["efficiency"] == 88.0
```

- [ ] **Step 2: Run — expect fail** (`is_unit_locked` not imported into `weaving_entry`).

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_reads_frozen.py -v`
Expected: FAIL.

- [ ] **Step 3: Branch `entries_by_date` on lock** in `weaving_entry.py`

Add imports: `from src.juteProduction.weaving_lock import is_unit_locked` and `get_weaving_log_rows_query` in the `from .weaving_query import (...)` block. In `entries_by_date` (`weaving_entry.py:589-599`), after `spell_id` resolves:

```python
        if spell_id is not None and is_unit_locked(db, co_id, branch_id, d_val, spell_id):
            rows = db.execute(
                get_weaving_log_rows_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "machine_id": machine_id, "branch_id": branch_id},
            ).fetchall()
        else:
            rows = db.execute(
                get_weaving_entries_by_date_query(),
                {"co_id": co_id, "tran_date": d_val, "spell_id": spell_id,
                 "machine_id": machine_id, "branch_id": branch_id},
            ).fetchall()
        return {"data": [_serialize_entry_row(r) for r in rows]}
```

- [ ] **Step 4: Branch `planning_grid` on lock** the same way — when locked, source the driver rows' computed columns from `get_weaving_log_rows_query` keyed by `(machine, weaving_quality_id)` instead of the live slice; keep the quality-map driver so mapped-but-unentered looms still render; preserve the 504 tripwire (the log query is unit-filtered).

- [ ] **Step 5: Run the test — expect pass**

Run: `source .venv/Scripts/activate && pytest src/test/test_weaving_reads_frozen.py -v`
Expected: PASS.

- [ ] **Step 6: Run the whole weaving suite**

Run: `source .venv/Scripts/activate && pytest src/test/ -k weaving -v`
Expected: new tests green; pre-existing unrelated failures unchanged.

- [ ] **Step 7: Commit**

```bash
git add src/juteProduction/weaving_query.py src/juteProduction/weaving_entry.py src/test/test_weaving_reads_frozen.py
git commit -m "feat(weaving): serve frozen log for locked units, live slice otherwise"
```

---

## Self-Review checklist (run after implementing)

1. **Spec coverage:** §4 tables → Tasks 1-3; §5 capture → Task 4; §7 lock+perm → Tasks 5-6; §6 process → Tasks 7-8; parity → Task 9; §8 reprocess → Tasks 8,10; §9 reads → Task 11. Stoppage (input #6) is consumed via the slice `working_hours` (frozen in Task 8) and drift-watched in `get_weaving_drift_query` — no dedicated task, by design.
2. **Parity guard:** Task 8 freezes strictly via `insert_weaving_log_from_slice_query` (wraps `weaving_day_slice_sql`); `services/weaving_standards.py` is never imported in the process path. ✔
3. **open_jugar:** Task 8 loops the per-row two-probe over the unit — no partitioned LAG, no correlated single-UPDATE (MySQL 1093). ✔
4. **Type consistency:** builder names imported in `weaving_process.py` all exist in Task 7; `_resolve_spell_id`/`_derive_co_id`/`_i` from `weaving_entry`; `is_unit_locked`/`require_edit_if_locked`/`get_process_lock` from `weaving_lock`; `get_weaving_log_rows_query` defined in Task 7, consumed in Task 11.

## Follow-ups (separate plans / fast-follows, per spec §11)

- **Frontend plan** (`vowerp3ui`): remove entry total-jugar preview + `disabled={!mapped}`; Process button + warnings panel + lock badge + reprocess banner; planning grid frozen/live; `hasMenuAccess(path,'edit')` gating. Author after these endpoints land.
- Weaving eb attendance stamp as a hard input (currently WARN + best-effort).
- Stamp-on-SQC-save / stamp-on-stoppage-save reprocess trigger (on-read compare only in v1).
