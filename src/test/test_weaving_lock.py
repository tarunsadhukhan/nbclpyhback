"""Locked-unit permission gate: helper unit tests + endpoint 403."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction import weaving_lock as wl

client = TestClient(app)


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


class TestLockedEntryEndpoint:
    def test_locked_unit_write_user_gets_403(self):
        session = MagicMock()
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        try:
            with patch("src.juteProduction.weaving_entry._derive_branch_id", return_value=2), \
                 patch("src.juteProduction.weaving_entry._derive_co_id", return_value=1), \
                 patch("src.juteProduction.weaving_entry._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_lock.is_unit_locked", return_value=True), \
                 patch("src.juteProduction.weaving_lock.user_menu_access_level", return_value=3):
                resp = client.post("/api/weavingProd/entry_create", json={
                    "tran_date": "2026-07-07", "spell": "A1", "machine_id": 42,
                    "cuts": 3, "close_jugar": 1.0,
                })
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403, resp.text


class TestLockedBatchEndpoints:
    """quality_map_save / beam_map_save gate the whole batch on the (co, date, spell)
    unit lock — a Write-only user must get 403 on a locked unit."""

    def _post_locked(self, path, payload):
        session = MagicMock()
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        try:
            with patch("src.juteProduction.weaving_entry._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_lock.is_unit_locked", return_value=True), \
                 patch("src.juteProduction.weaving_lock.user_menu_access_level", return_value=3):
                return client.post(path, json=payload)
        finally:
            app.dependency_overrides.clear()

    def test_quality_map_save_locked_write_user_gets_403(self):
        resp = self._post_locked("/api/weavingProd/quality_map_save", {
            "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell": "A1",
            "entries": [{"machine_id": 42, "weaving_quality_id": 5}],
        })
        assert resp.status_code == 403, resp.text

    def test_beam_map_save_locked_write_user_gets_403(self):
        resp = self._post_locked("/api/weavingProd/beam_map_save", {
            "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell": "A1",
            "entries": [{"machine_id": 42, "beam_no": "BEAM-9"}],
        })
        assert resp.status_code == 403, resp.text


class TestEntryEditUnitMoveGate:
    def test_moving_row_out_of_locked_old_unit_gets_403(self):
        """entry_edit changing spell_id must also gate on the OLD (date, spell) unit:
        new unit unlocked, old unit locked + Write-only user -> 403."""
        existing = MagicMock()
        existing.weaving_daily_id = 5
        existing.co_id = 1
        existing.branch_id = 2
        existing.tran_date = "2026-07-07"
        existing.spell_id = 91
        existing.machine_id = 42
        existing.weaving_quality_id = 5
        existing.eb_id = None
        existing.beam_no = "B1"
        existing.cuts = 3
        existing.close_jugar = 1.0
        existing.less_production = 0.0
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = existing
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        try:
            # 1st is_unit_locked = NEW unit (spell 92, unlocked); 2nd = OLD unit (locked).
            with patch("src.juteProduction.weaving_lock.is_unit_locked",
                       side_effect=[False, True]), \
                 patch("src.juteProduction.weaving_lock.user_menu_access_level",
                       return_value=3):
                resp = client.put(
                    "/api/weavingProd/entry_edit/5?co_id=1",
                    json={"spell_id": 92},
                )
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 403, resp.text
