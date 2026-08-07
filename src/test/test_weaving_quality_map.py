"""Tests for the Weaving Loom->Quality map + Beam map endpoints.

Tests for src/juteProduction/weaving_entry.py (prefix /api/weavingProd):
  * GET  /api/weavingProd/quality_map_get   (carry-forward prefill grid)
  * POST /api/weavingProd/quality_map_save  (one active row per key, upsert)
  * POST /api/weavingProd/quality_map_mapped (saved/mapped view back-stamp)
  * GET  /api/weavingProd/beam_map_get
  * POST /api/weavingProd/beam_map_save

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through app.dependency_overrides
keyed by those exact symbols. Mock rows expose ._mapping dicts.

The GET grids take the spell *code* ('A1', ...) and resolve it to spell_id via spell_mst
(mirrors spinning's frame_map_get), so each grid success path issues a resolve lookup
first (mocked by _resolve_spell_exec).

Covered: success + missing-co_id (400) + key edge cases (carry-forward prefill,
update-vs-insert upsert, malformed-id skip, missing tran_date/spell, unknown spell code).
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteProduction.weaving_entry import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


import pytest as _pytest
from unittest.mock import patch as _patch


@_pytest.fixture(autouse=True)
def _bypass_weaving_lock():
    """Locking is tested in test_weaving_lock.py; bypass the batch gate here so the
    legacy execute-order mocks (which predate the Process lock gate) stay aligned."""
    with _patch("src.juteProduction.weaving_entry.require_edit_if_locked"), \
         _patch("src.juteProduction.weaving_entry.flag_reprocess_if_locked"), \
         _patch("src.juteProduction.weaving_entry._lock_co_for_batch",
                return_value=None):
        yield


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _resolve_spell_exec(spell_id=1):
    """Mock the db.execute(...) for _resolve_spell_id: .fetchone() -> row.spell_id.

    The weaving GET grids now receive the spell *code* and resolve it to spell_id via
    spell_mst (mirrors spinning), so every grid success path issues this lookup first.
    Pass spell_id=None to simulate an unknown spell code (resolver raises 400).
    """
    row = MagicMock()
    row.spell_id = spell_id
    exec_mock = MagicMock()
    exec_mock.fetchone.return_value = row
    return exec_mock


# =============================================================================
# GET /api/weavingProd/quality_map_get
# =============================================================================


class TestQualityMapGet:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_grid_with_carry_forward_prefill(self):
        """Each loom row carries today's saved mapping plus the loom's most-recent
        prior mapping (prev_quality_*) so the client can prefill a never-mapped cell."""
        grid_rows = [
            _mock_row({
                "machine_id": 11,
                "mech_code": "LM01",
                "machine_name": "Loom-1",
                "line_no": "L1",
                "branch_id": 2,
                # No saved mapping for THIS cell yet -> carry-forward prefill from prev.
                "weaving_quality_map_id": None,
                "weaving_quality_id": None,
                "weaving_quality_code": None,
                "weaving_quality_name": None,
                "prev_quality_id": 5,
                "prev_quality_code": "WQ-272",
                "prev_quality_name": "272 Sacking",
                "prev_date": "2026-06-20",
            }),
            _mock_row({
                "machine_id": 12,
                "mech_code": "LM02",
                "machine_name": "Loom-2",
                "line_no": "L1",
                "branch_id": 2,
                # Saved mapping present for this cell.
                "weaving_quality_map_id": 99,
                "weaving_quality_id": 6,
                "weaving_quality_code": "WQ-300",
                "weaving_quality_name": "300 Hessian",
                "prev_quality_id": 6,
                "prev_quality_code": "WQ-300",
                "prev_quality_name": "300 Hessian",
                "prev_date": "2026-06-22",
            }),
        ]
        grid_exec = MagicMock()
        grid_exec.fetchall.return_value = grid_rows
        last_updated_exec = MagicMock()
        last_updated_exec.scalar.return_value = "2026-06-22 10:30:00"
        # Execute order: spell-code resolve, grid query, then last_updated scalar.
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),
            grid_exec,
            last_updated_exec,
        ]

        response = client.get(
            "/api/weavingProd/quality_map_get"
            "?co_id=1&tran_date=2026-06-23&spell=A1"
        )

        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        assert len(data) == 2
        # Row 0: unmapped cell, prev_* prefill present.
        assert data[0]["machine_id"] == 11
        assert data[0]["weaving_quality_id"] is None
        assert data[0]["prev_quality_id"] == 5
        assert data[0]["prev_quality_code"] == "WQ-272"
        assert data[0]["prev_date"] == "2026-06-20"
        # Row 1: saved mapping for the cell.
        assert data[1]["weaving_quality_map_id"] == 99
        assert data[1]["weaving_quality_id"] == 6
        assert body["last_updated"] == "2026-06-22 10:30:00"

    def test_null_last_updated_serializes_to_none(self):
        grid_exec = MagicMock()
        grid_exec.fetchall.return_value = []
        last_updated_exec = MagicMock()
        last_updated_exec.scalar.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),
            grid_exec,
            last_updated_exec,
        ]

        response = client.get(
            "/api/weavingProd/quality_map_get"
            "?co_id=1&tran_date=2026-06-23&spell=A1"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["last_updated"] is None

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingProd/quality_map_get?tran_date=2026-06-23&spell=A1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/quality_map_get?co_id=1&spell=A1")
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "tran_date" in detail and "spell" in detail

    def test_missing_spell_returns_400(self):
        response = client.get(
            "/api/weavingProd/quality_map_get?co_id=1&tran_date=2026-06-23"
        )
        assert response.status_code == 400
        assert "spell" in response.json()["detail"].lower()

    def test_unknown_spell_returns_400(self):
        """An unrecognised spell code resolves to no spell_id -> 400 Unknown spell."""
        self._mock_session.execute.side_effect = [_resolve_spell_exec(None)]
        response = client.get(
            "/api/weavingProd/quality_map_get"
            "?co_id=1&tran_date=2026-06-23&spell=ZZ"
        )
        assert response.status_code == 400
        assert "unknown spell" in response.json()["detail"].lower()

    def test_invalid_tran_date_returns_400(self):
        response = client.get(
            "/api/weavingProd/quality_map_get"
            "?co_id=1&tran_date=not-a-date&spell=A1"
        )
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()


# =============================================================================
# GET /api/weavingProd/quality_map_saved  (cheap read, no carry-forward)
# =============================================================================


class TestQualityMapSaved:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_grid_with_prev_forced_null(self):
        """Same loom set + saved-mapping columns as quality_map_get, but the four
        prev_quality_* subqueries are dropped — the endpoint always returns prev_* = None
        (the SAVED_ONLY query never selects them)."""
        grid_rows = [
            _mock_row({
                "machine_id": 12,
                "mech_code": "LM02",
                "mech_posting_code": 2002,
                "machine_name": "Loom-2",
                "line_no": "L1",
                "branch_id": 2,
                "weaving_quality_map_id": 99,
                "weaving_quality_id": 6,
                "weaving_quality_code": "WQ-300",
                "weaving_quality_name": "300 Hessian",
                "no_of_jugar_per_cut": 4,
            }),
        ]
        grid_exec = MagicMock()
        grid_exec.fetchall.return_value = grid_rows
        last_updated_exec = MagicMock()
        last_updated_exec.scalar.return_value = "2026-06-22 10:30:00"
        # Execute order: spell-code resolve, saved grid query, last_updated scalar.
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),
            grid_exec,
            last_updated_exec,
        ]

        response = client.get(
            "/api/weavingProd/quality_map_saved?co_id=1&tran_date=2026-06-23&spell=A1"
        )

        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        assert len(data) == 1
        assert data[0]["machine_id"] == 12
        assert data[0]["weaving_quality_map_id"] == 99
        assert data[0]["weaving_quality_id"] == 6
        assert data[0]["no_of_jugar_per_cut"] == 4
        # Carry-forward is NOT computed on this cheap read.
        assert data[0]["prev_quality_id"] is None
        assert data[0]["prev_quality_code"] is None
        assert data[0]["prev_quality_name"] is None
        assert data[0]["prev_date"] is None
        assert body["last_updated"] == "2026-06-22 10:30:00"

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingProd/quality_map_saved?tran_date=2026-06-23&spell=A1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_unknown_spell_returns_400(self):
        self._mock_session.execute.side_effect = [_resolve_spell_exec(None)]
        response = client.get(
            "/api/weavingProd/quality_map_saved?co_id=1&tran_date=2026-06-23&spell=ZZ"
        )
        assert response.status_code == 400
        assert "unknown spell" in response.json()["detail"].lower()


# =============================================================================
# POST /api/weavingProd/quality_map_save
# =============================================================================


class TestQualityMapSave:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_upsert_updates_existing_and_inserts_new(self):
        """One active row per (co_id, tran_date, spell_id, machine_id): an existing
        active row is UPDATED in place, a never-mapped loom is INSERTED."""
        existing_row = MagicMock()
        existing_row.weaving_quality_map_id = 77
        # machine 11 -> existing (find returns row, then update);
        # machine 12 -> none (find returns None, then insert).
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_restamp = MagicMock()
        no_restamp.fetchall.return_value = []  # no stale daily rows to re-stamp
        # The handler resolves the spell CODE -> spell_id first (one extra execute).
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),       # spell 'A1' -> spell_id 1
            find_existing, MagicMock(),  # machine 11 -> update
            no_restamp,                  # machine 11 daily-row restamp probe (empty)
            find_none, MagicMock(),      # machine 12 -> insert
            no_restamp,                  # machine 12 daily-row restamp probe (empty)
            MagicMock(), MagicMock(),    # Layer 3: current-quality pointer upserts (both non-null)
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "weaving_quality_id": 5},
                {"machine_id": 12, "weaving_quality_id": 6},
            ],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 2
        assert data["skipped"] == 0
        self._mock_session.commit.assert_called_once()

        # Update bind params carry the existing row id + new quality (index +1 for resolve).
        update_params = self._mock_session.execute.call_args_list[2].args[1]
        assert update_params["id"] == 77
        assert update_params["weaving_quality_id"] == 5
        assert update_params["updated_by"] == 1
        # Insert bind params carry the full new row (machine 12; index 4 = restamp probe).
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["machine_id"] == 12
        assert insert_params["weaving_quality_id"] == 6
        assert insert_params["spell_id"] == 1
        assert insert_params["branch_id"] == 2
        # Layer 3: after the map rows, both looms sync the current-quality pointer.
        sync1 = self._mock_session.execute.call_args_list[7].args[1]
        sync2 = self._mock_session.execute.call_args_list[8].args[1]
        assert sync1["machine_id"] == 11 and sync1["weaving_quality_id"] == 5 and sync1["spell_id"] == 1
        assert sync2["machine_id"] == 12 and sync2["weaving_quality_id"] == 6

    def test_remap_restamps_stale_daily_row_and_syncs_chain(self):
        """A created/changed mapping re-stamps the cell's active daily rows whose stored
        quality is NULL/stale, then re-syncs the row's jugar chain (and the OLD chain's
        successor when the row had a different quality)."""
        existing_row = MagicMock()
        existing_row.weaving_quality_map_id = 77
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        stale_daily = MagicMock()
        stale_daily.weaving_daily_id = 301
        stale_daily.weaving_quality_id = 4  # old quality -> old-chain repair too
        restamp_probe = MagicMock()
        restamp_probe.fetchall.return_value = [stale_daily]
        open_jugar_resolved = MagicMock()
        open_jugar_resolved.fetchone.return_value = MagicMock(open_jugar=2.0)
        no_successor = MagicMock()
        no_successor.scalar.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),   # spell 'A1' -> spell_id 1
            find_existing,            # active map row -> update path
            MagicMock(),              # map row UPDATE
            restamp_probe,            # stale daily rows for the cell -> [301]
            MagicMock(),              # daily-row quality re-stamp UPDATE
            open_jugar_resolved,      # chain sync: resolve row 301's open_jugar
            MagicMock(),              # chain sync: store open_jugar
            no_successor,             # NEW-chain successor probe -> none
            no_successor,             # OLD-chain (quality 4) successor probe -> none
            MagicMock(),              # Layer 3 current-quality pointer upsert
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [{"machine_id": 11, "weaving_quality_id": 5}],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["saved"] == 1
        stamp_params = self._mock_session.execute.call_args_list[4].args[1]
        assert stamp_params == {"id": 301, "weaving_quality_id": 5, "updated_by": 1}

    def test_restamps_null_quality_daily_row(self):
        """Regression: a daily row saved BEFORE any mapping (stored quality NULL) is
        re-stamped with the newly mapped quality; with no old quality there is no
        OLD-chain successor repair (one fewer probe than the stale-remap path)."""
        existing_row = MagicMock()
        existing_row.weaving_quality_map_id = 77
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        null_daily = MagicMock()
        null_daily.weaving_daily_id = 301
        null_daily.weaving_quality_id = None  # capture-before-map row
        restamp_probe = MagicMock()
        restamp_probe.fetchall.return_value = [null_daily]
        open_jugar_resolved = MagicMock()
        open_jugar_resolved.fetchone.return_value = MagicMock(open_jugar=2.0)
        no_successor = MagicMock()
        no_successor.scalar.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),   # spell 'A1' -> spell_id 1
            find_existing,            # active map row -> update path
            MagicMock(),              # map row UPDATE
            restamp_probe,            # NULL-quality daily row for the cell -> [301]
            MagicMock(),              # daily-row quality re-stamp UPDATE
            open_jugar_resolved,      # chain sync: resolve row 301's open_jugar
            MagicMock(),              # chain sync: store open_jugar
            no_successor,             # NEW-chain successor probe -> none
            MagicMock(),              # Layer 3 current-quality pointer upsert
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [{"machine_id": 11, "weaving_quality_id": 5}],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["data"]["saved"] == 1
        stamp_params = self._mock_session.execute.call_args_list[4].args[1]
        assert stamp_params == {"id": 301, "weaving_quality_id": 5, "updated_by": 1}
        # NULL old quality -> exactly 9 executes: NO old-chain successor probe.
        assert self._mock_session.execute.call_count == 9

    def test_null_quality_clears_mapping_on_update(self):
        """A None weaving_quality_id is bound as SQL NULL (not the string 'null')."""
        existing_row = MagicMock()
        existing_row.weaving_quality_map_id = 50
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), find_existing, MagicMock(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "weaving_quality_id": None},
            ],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        update_params = self._mock_session.execute.call_args_list[2].args[1]
        assert update_params["weaving_quality_id"] is None
        # Layer 3: a NULL quality does NOT sync the pointer (keeps the last known non-null) —
        # so only resolve + find + update ran, no trailing upsert.
        assert self._mock_session.execute.call_count == 3

    def test_branch_id_derived_when_omitted(self):
        """When the body omits branch_id, the server derives it from the machine."""
        derived = MagicMock()
        derived.branch_id = 9
        derive_exec = MagicMock()
        derive_exec.fetchone.return_value = derived
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_restamp = MagicMock()
        no_restamp.fetchall.return_value = []
        # spell resolve, then per entry: _derive_branch_id, find(active)=None, insert,
        # restamp probe (no daily rows), then the Layer 3 current-quality pointer upsert.
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), derive_exec, find_none, MagicMock(),
            no_restamp, MagicMock(),
        ]

        payload = {
            "co_id": 1,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "weaving_quality_id": 5},
            ],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        insert_params = self._mock_session.execute.call_args_list[3].args[1]
        assert insert_params["branch_id"] == 9

    def test_co_id_derived_from_branch_when_omitted(self):
        """co_id is no longer required: when omitted it is derived from branch_id
        (branch_mst.co_id) and still stored on the inserted row."""
        co_row = MagicMock()
        co_row.co_id = 1
        derive_co_exec = MagicMock()
        derive_co_exec.fetchone.return_value = co_row
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_restamp = MagicMock()
        no_restamp.fetchall.return_value = []
        # spell resolve, then per entry: _derive_co_id (branch given), find=None, insert,
        # restamp probe (no daily rows), then the Layer 3 current-quality pointer upsert.
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), derive_co_exec, find_none, MagicMock(),
            no_restamp, MagicMock(),
        ]

        payload = {
            "branch_id": 2,  # NO co_id
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "weaving_quality_id": 5},
            ],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        insert_params = self._mock_session.execute.call_args_list[3].args[1]
        assert insert_params["co_id"] == 1
        assert insert_params["branch_id"] == 2

    def test_non_positive_machine_id_is_skipped(self):
        """A loom set that changed since the grid loaded -> malformed ids are skipped,
        not errored. Here machine_id 0 is skipped; the valid one is inserted."""
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_restamp = MagicMock()
        no_restamp.fetchall.return_value = []
        # spell resolve, then only the valid entry hits the DB: find(active)=None, insert,
        # restamp probe (no daily rows), then the Layer 3 current-quality pointer upsert.
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), find_none, MagicMock(), no_restamp, MagicMock(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 0, "weaving_quality_id": 5},   # skipped
                {"machine_id": 12, "weaving_quality_id": 6},  # inserted
            ],
        }

        response = client.post("/api/weavingProd/quality_map_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 1
        assert data["skipped"] == 1
        self._mock_session.commit.assert_called_once()

    def test_empty_entries_saves_nothing(self):
        # The spell still resolves (before the loop) even with no entries.
        self._mock_session.execute.return_value = _resolve_spell_exec(1)
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [],
        }
        response = client.post("/api/weavingProd/quality_map_save", json=payload)
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 0
        assert data["skipped"] == 0
        self._mock_session.commit.assert_called_once()

    def test_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("boom")
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "weaving_quality_id": 5},
            ],
        }
        response = client.post("/api/weavingProd/quality_map_save", json=payload)
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()
        self._mock_session.commit.assert_not_called()


# =============================================================================
# POST /api/weavingProd/quality_map_mapped
# =============================================================================


class TestQualityMapMapped:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_returns_only_mapped_looms_with_labels(self):
        """Only looms with an active mapping for the cell are returned, with machine +
        quality + item labels; updated_date_time is stringified for JSON safety."""
        mapped_rows = [
            _mock_row({
                "weaving_quality_map_id": 99,
                "machine_id": 12,
                "mech_code": "LM02",
                "machine_name": "Loom-2",
                "weaving_quality_id": 6,
                "weaving_quality_code": "WQ-300",
                "weaving_quality_name": "300 Hessian",
                "item_id": 555,
                "item_code": "ITM-300",
                "item_name": "Hessian Cloth",
                "updated_date_time": "2026-06-22 10:30:00",
            }),
        ]
        exec_m = MagicMock()
        exec_m.fetchall.return_value = mapped_rows
        # spell 'A1' resolves first, then the mapped-view query runs.
        self._mock_session.execute.side_effect = [_resolve_spell_exec(1), exec_m]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
        }

        response = client.post("/api/weavingProd/quality_map_mapped", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["machine_id"] == 12
        assert data[0]["weaving_quality_id"] == 6
        assert data[0]["weaving_quality_code"] == "WQ-300"
        assert data[0]["updated_date_time"] == "2026-06-22 10:30:00"

    def test_optional_spell_and_machine_bind_as_none(self):
        """spell_id / machine_id are optional — when omitted they bind as SQL NULL,
        widening the mapped view to the whole date."""
        exec_m = MagicMock()
        exec_m.fetchall.return_value = []
        self._mock_session.execute.return_value = exec_m

        payload = {"co_id": 1, "tran_date": "2026-06-23"}

        response = client.post("/api/weavingProd/quality_map_mapped", json=payload)

        assert response.status_code == 200
        assert response.json()["data"] == []
        params = self._mock_session.execute.call_args.args[1]
        assert params["spell_id"] is None
        assert params["machine_id"] is None
        assert params["branch_id"] is None
        assert params["co_id"] == 1

    def test_missing_co_id_and_branch_returns_400(self):
        """co_id is no longer required, but without co_id AND branch_id there is nothing
        to scope/derive from -> 400."""
        response = client.post(
            "/api/weavingProd/quality_map_mapped",
            json={"tran_date": "2026-06-23"},
        )
        assert response.status_code == 400
        assert "co_id or branch_id" in response.json()["detail"].lower()


# =============================================================================
# GET /api/weavingProd/beam_map_get
# =============================================================================


class TestBeamMapGet:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_looms_with_latest_beam_no(self):
        beam_rows = [
            _mock_row({
                "machine_id": 11,
                "mech_code": "LM01",
                "machine_name": "Loom-1",
                "line_no": "L1",
                "branch_id": 2,
                "weaving_beam_map_id": 7,
                "beam_no": "BEAM-1001",
            }),
            _mock_row({
                "machine_id": 12,
                "mech_code": "LM02",
                "machine_name": "Loom-2",
                "line_no": "L1",
                "branch_id": 2,
                "weaving_beam_map_id": None,
                "beam_no": None,
            }),
        ]
        exec_m = MagicMock()
        exec_m.fetchall.return_value = beam_rows
        # Execute order: spell-code resolve, then the beam-map grid query.
        self._mock_session.execute.side_effect = [_resolve_spell_exec(1), exec_m]

        response = client.get(
            "/api/weavingProd/beam_map_get?co_id=1&tran_date=2026-06-23&spell=A1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 2
        assert data[0]["machine_id"] == 11
        assert data[0]["beam_no"] == "BEAM-1001"
        assert data[1]["beam_no"] is None

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingProd/beam_map_get?tran_date=2026-06-23&spell=A1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_or_spell_returns_400(self):
        response = client.get("/api/weavingProd/beam_map_get?co_id=1")
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "tran_date" in detail and "spell" in detail

    def test_unknown_spell_returns_400(self):
        self._mock_session.execute.side_effect = [_resolve_spell_exec(None)]
        response = client.get(
            "/api/weavingProd/beam_map_get"
            "?co_id=1&tran_date=2026-06-23&spell=ZZ"
        )
        assert response.status_code == 400
        assert "unknown spell" in response.json()["detail"].lower()


# =============================================================================
# POST /api/weavingProd/beam_map_save
# =============================================================================


class TestBeamMapSave:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_upsert_updates_existing_and_inserts_new(self):
        """One active row per (co_id, tran_date, spell_id, machine_id): existing row
        is UPDATED in place, a new loom is INSERTED."""
        existing_row = MagicMock()
        existing_row.weaving_beam_map_id = 7
        existing_row.beam_no = "BEAM-2001"  # unchanged -> no jugar reset probe
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_daily = MagicMock()
        no_daily.fetchone.return_value = None
        # The handler resolves the spell CODE -> spell_id first (one extra execute).
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),       # spell 'A1' -> spell_id 1
            find_existing, MagicMock(),  # machine 11 -> update (beam unchanged)
            find_none, MagicMock(),      # machine 12 -> insert (fresh beam)
            no_daily,                    # machine 12 beam change: no daily row -> no reset
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "beam_no": "BEAM-2001"},
                {"machine_id": 12, "beam_no": "BEAM-2002"},
            ],
        }

        response = client.post("/api/weavingProd/beam_map_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 2
        assert data["skipped"] == 0
        self._mock_session.commit.assert_called_once()

        update_params = self._mock_session.execute.call_args_list[2].args[1]
        assert update_params["id"] == 7
        assert update_params["beam_no"] == "BEAM-2001"
        insert_params = self._mock_session.execute.call_args_list[4].args[1]
        assert insert_params["machine_id"] == 12
        assert insert_params["beam_no"] == "BEAM-2002"
        assert insert_params["spell_id"] == 1

    def test_empty_beam_no_binds_as_none(self):
        """An empty-string beam_no is normalized to SQL NULL (clears the mounted beam)."""
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), find_none, MagicMock(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "beam_no": ""},
            ],
        }

        response = client.post("/api/weavingProd/beam_map_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        insert_params = self._mock_session.execute.call_args_list[2].args[1]
        assert insert_params["beam_no"] is None

    def test_non_positive_machine_id_is_skipped(self):
        find_none = MagicMock()
        find_none.fetchone.return_value = None
        no_daily = MagicMock()
        no_daily.fetchone.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), find_none, MagicMock(), no_daily,
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": -1, "beam_no": "BEAM-X"},     # skipped
                {"machine_id": 12, "beam_no": "BEAM-2002"},  # inserted
            ],
        }

        response = client.post("/api/weavingProd/beam_map_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 1
        assert data["skipped"] == 1

    def test_beam_change_zeroes_daily_open_jugar(self):
        """A recorded beam change on a cell WITH an active daily row zeroes that row's
        stored open_jugar (fresh beam = fresh jugar count) and probes the chain
        successor. A re-save with the same beam_no must NOT touch the chain."""
        existing_row = MagicMock()
        existing_row.weaving_beam_map_id = 7
        existing_row.beam_no = "BEAM-OLD"  # differs from payload -> beam change
        find_existing = MagicMock()
        find_existing.fetchone.return_value = existing_row
        daily_row = MagicMock()
        daily_row.weaving_daily_id = 301
        daily_row.weaving_quality_id = 5
        find_daily = MagicMock()
        find_daily.fetchone.return_value = daily_row
        no_successor = MagicMock()
        no_successor.scalar.return_value = None
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1),      # spell 'A1' -> spell_id 1
            find_existing, MagicMock(),  # machine 11 -> update (beam CHANGED)
            find_daily,                  # active daily row for the cell
            MagicMock(),                 # zero the stored open_jugar
            no_successor,                # chain successor probe -> none
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "beam_no": "BEAM-NEW"},
            ],
        }

        response = client.post("/api/weavingProd/beam_map_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        zero_params = self._mock_session.execute.call_args_list[4].args[1]
        assert zero_params == {"row_id": 301, "open_jugar": 0.0}

    def test_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("boom")
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-23",
            "spell": "A1",
            "entries": [
                {"machine_id": 11, "beam_no": "BEAM-2001"},
            ],
        }
        response = client.post("/api/weavingProd/beam_map_save", json=payload)
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()
        self._mock_session.commit.assert_not_called()
