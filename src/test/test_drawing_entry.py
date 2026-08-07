"""
Tests for Drawing production entry (jute production module).
Covers src/juteProduction/drawing_entry.py, drawing_masters.py,
services/drawing_rules.py.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.drawing_entry import (
    DUPLICATE_MSG,
    NEGATIVE_DIFF_MSG,
    NO_ATTR_MSG,
)
from src.juteProduction.services.drawing_rules import compute_diff_meter, compute_eff

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _exec_params(mock_session, call_index: int) -> dict:
    return mock_session.execute.call_args_list[call_index][0][1]


def _spell_rows():
    return [
        _mock_row(
            {
                "spell_code": "A1",
                "spell_name": "A1",
                "working_hours": 5.0,
                "starting_time": "06:00:00",
                "is_overnight": 0,
            }
        ),
        _mock_row(
            {
                "spell_code": "A1",  # duplicate (sls branch 29) — must be deduped
                "spell_name": "A1",
                "working_hours": 5.0,
                "starting_time": "06:00:00",
                "is_overnight": 0,
            }
        ),
        _mock_row(
            {
                "spell_code": "C",
                "spell_name": "C",
                "working_hours": 8.0,
                "starting_time": "22:00:00",
                "is_overnight": 1,
            }
        ),
    ]


def _attr_row(const_meter=8000.0, wrap=10000):
    row = MagicMock()
    row.drawing_machine_attr_id = 1
    row.const_meter = const_meter
    row.meter_wrap_limit = wrap
    return row


# =============================================================================
# Pure business rules
# =============================================================================


class TestDrawingRules:
    def test_diff_normal(self):
        assert compute_diff_meter(1000, 2500, 10000) == 1500

    def test_diff_rollover_default_wrap(self):
        # legacy example: open=9900, close=100 -> (100+10000)-9900 = 200
        assert compute_diff_meter(9900, 100, 10000) == 200

    def test_diff_rollover_custom_wrap(self):
        assert compute_diff_meter(999900, 50, 1000000) == 150

    def test_diff_negative_when_wrap_too_small(self):
        assert compute_diff_meter(5000, 1000, 1000) == -3000

    def test_eff_legacy_example(self):
        # diff=1000, const=8000, hrs=5 -> 1000/(8000/8*5)*100 = 20.00
        assert compute_eff(1000, 8000, 5) == 20.00

    def test_eff_zero_when_no_diff(self):
        assert compute_eff(0, 8000, 5) == 0.0

    def test_eff_zero_when_no_const(self):
        assert compute_eff(1000, 0, 5) == 0.0

    def test_eff_zero_when_no_hours(self):
        assert compute_eff(1000, 8000, 0) == 0.0


# =============================================================================
# Endpoint tests
# =============================================================================


class TestDrawingBase:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


class TestEntryCreateSetup(TestDrawingBase):
    def test_setup_returns_machines_and_deduped_spells(self):
        machine = _mock_row(
            {
                "machine_id": 61,
                "machine_name": "1st Drawing - 1",
                "mech_code": "21001",
                "dept_id": 16,
                "dept_name": "Drawing",
                "branch_id": 4,
                "const_meter": 8000.0,
                "meter_wrap_limit": 10000,
                "mc_group": "DRG-A",
                "drawing_machine_attr_id": 1,
            }
        )
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [machine],
            _spell_rows(),
        ]
        resp = client.get("/api/drawingProd/entry_create_setup?co_id=1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["machines"]) == 1
        assert data["machines"][0]["const_meter"] == 8000.0
        codes = [s["spell_code"] for s in data["spells"]]
        assert codes == ["A1", "C"]  # duplicate A1 removed
        assert data["spells"][1]["working_hours"] == 8.0

    def test_setup_missing_co_id(self):
        resp = client.get("/api/drawingProd/entry_create_setup")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_setup_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.side_effect = [[], []]
        resp = client.get("/api/drawingProd/entry_create_setup?co_id=1&branch_id=4")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 4


class TestMachinePrevState(TestDrawingBase):
    def test_missing_params_rejected(self):
        resp = client.get("/api/drawingProd/machine_prev_state?co_id=1&machine_id=61")
        assert resp.status_code == 400

    def test_prev_state_happy_path(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row()
        prev_result = MagicMock()
        prev_row = MagicMock()
        prev_row.close_meter = 4321.0
        prev_result.fetchone.return_value = prev_row
        self._mock_session.execute.side_effect = [dup_result, attr_result, prev_result]

        resp = client.get(
            "/api/drawingProd/machine_prev_state?co_id=1&machine_id=61&tran_date=2026-06-11&spell=A1"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["already_entered"] is False
        assert data["const_meter"] == 8000.0
        assert data["open_meter"] == 4321.0
        assert data["meter_wrap_limit"] == 10000
        assert data["attr_configured"] is True

    def test_prev_state_flags_duplicate(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 1
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row()
        prev_result = MagicMock()
        prev_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [dup_result, attr_result, prev_result]

        resp = client.get(
            "/api/drawingProd/machine_prev_state?co_id=1&machine_id=61&tran_date=2026-06-11&spell=A1"
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["already_entered"] is True

    def test_prev_state_exclude_entry_id_binds(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = None
        prev_result = MagicMock()
        prev_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [dup_result, attr_result, prev_result]

        resp = client.get(
            "/api/drawingProd/machine_prev_state"
            "?co_id=1&machine_id=61&tran_date=2026-06-11&spell=A1&exclude_entry_id=9"
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["exclude_id"] == 9


class TestEntryCreate(TestDrawingBase):
    BODY = {
        "co_id": 1,
        "tran_date": "2026-06-11",
        "spell": "A1",
        "machine_id": 61,
        "open_meter": 1000.0,
        "close_meter": 2000.0,
        "wrk_hours": 5.0,
    }

    def _spells_result(self):
        spells_result = MagicMock()
        spells_result.fetchall.return_value = _spell_rows()
        return spells_result

    def test_create_duplicate_rejected(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 1
        self._mock_session.execute.side_effect = [self._spells_result(), dup_result]
        resp = client.post("/api/drawingProd/entry_create", json=self.BODY)
        assert resp.status_code == 400
        assert resp.json()["detail"] == DUPLICATE_MSG

    def test_create_missing_attr_rejected(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [self._spells_result(), dup_result, attr_result]
        resp = client.post("/api/drawingProd/entry_create", json=self.BODY)
        assert resp.status_code == 400
        assert resp.json()["detail"] == NO_ATTR_MSG

    def test_create_negative_diff_rejected(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row(const_meter=8000.0, wrap=1000)
        self._mock_session.execute.side_effect = [self._spells_result(), dup_result, attr_result]
        body = dict(self.BODY, open_meter=5000.0, close_meter=1000.0)  # wrap 1000 -> -3000
        resp = client.post("/api/drawingProd/entry_create", json=body)
        assert resp.status_code == 400
        assert resp.json()["detail"] == NEGATIVE_DIFF_MSG

    def test_create_unknown_spell_rejected(self):
        self._mock_session.execute.side_effect = [self._spells_result()]
        resp = client.post("/api/drawingProd/entry_create", json=dict(self.BODY, spell="ZZ"))
        assert resp.status_code == 400
        assert "spell" in resp.json()["detail"].lower()

    def test_create_success_server_computes_diff_and_eff(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row()
        derive_result = MagicMock()
        derive_row = MagicMock()
        derive_row.branch_id = 4
        derive_result.fetchone.return_value = derive_row
        insert_result = MagicMock()
        insert_result.lastrowid = 77
        self._mock_session.execute.side_effect = [
            self._spells_result(),
            dup_result,
            attr_result,
            derive_result,
            insert_result,
        ]
        resp = client.post("/api/drawingProd/entry_create", json=self.BODY)
        assert resp.status_code == 200
        assert resp.json()["data"]["drawing_entry_id"] == 77
        ins = _exec_params(self._mock_session, 4)
        assert ins["diff_meter"] == 1000.0
        assert ins["actual_eff"] == 20.00  # 1000/(8000/8*5)*100
        assert ins["const_meter"] == 8000.0
        assert ins["branch_id"] == 4

    def test_create_rollover(self):
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row()
        insert_result = MagicMock()
        insert_result.lastrowid = 78
        self._mock_session.execute.side_effect = [
            self._spells_result(),
            dup_result,
            attr_result,
            insert_result,
        ]
        body = dict(self.BODY, branch_id=4, open_meter=9900.0, close_meter=100.0)
        resp = client.post("/api/drawingProd/entry_create", json=body)
        assert resp.status_code == 200
        ins = _exec_params(self._mock_session, 3)
        assert ins["diff_meter"] == 200.0  # (100+10000)-9900


class TestEntriesByDate(TestDrawingBase):
    def test_requires_tran_date(self):
        resp = client.get("/api/drawingProd/entries_by_date?co_id=1")
        assert resp.status_code == 400

    def test_binds_filters(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get(
            "/api/drawingProd/entries_by_date?co_id=1&tran_date=2026-06-11&spell=A1&branch_id=4"
        )
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 0)
        assert params["spell"] == "A1"
        assert params["branch_id"] == 4


class TestEntryEdit(TestDrawingBase):
    def test_edit_not_found(self):
        found_result = MagicMock()
        found_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [found_result]
        resp = client.put("/api/drawingProd/entry_edit/5?co_id=1", json={"close_meter": 3000})
        assert resp.status_code == 404

    def _existing_row(self):
        row = MagicMock()
        row.drawing_entry_id = 5
        row.co_id = 1
        row.tran_date = "2026-06-11"
        row.spell = "A1"
        row.machine_id = 61
        row.open_meter = 1000.0
        row.close_meter = 2000.0
        row.const_meter = 8000.0
        row.wrk_hours = 5.0
        row.remarks = "old"
        return row

    def test_edit_recomputes_eff(self):
        found_result = MagicMock()
        found_result.fetchone.return_value = self._existing_row()
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row()
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [found_result, attr_result, update_result]
        resp = client.put("/api/drawingProd/entry_edit/5?co_id=1", json={"close_meter": 3000.0})
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 2)
        assert params["diff_meter"] == 2000.0
        assert params["actual_eff"] == 40.00

    def test_edit_machine_change_resnapshots_attr(self):
        found_result = MagicMock()
        found_result.fetchone.return_value = self._existing_row()
        dup_result = MagicMock()
        dup_result.scalar.return_value = 0
        attr_result = MagicMock()
        attr_result.fetchone.return_value = _attr_row(const_meter=4000.0, wrap=10000)
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [
            found_result,
            dup_result,
            attr_result,
            update_result,
        ]
        resp = client.put("/api/drawingProd/entry_edit/5?co_id=1", json={"machine_id": 62})
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 3)
        assert params["const_meter"] == 4000.0
        assert params["actual_eff"] == 40.00  # 1000/(4000/8*5)*100


class TestEntryDelete(TestDrawingBase):
    def test_delete_soft(self):
        found_result = MagicMock()
        found_row = MagicMock()
        found_row.drawing_entry_id = 5
        found_result.fetchone.return_value = found_row
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [found_result, update_result]
        resp = client.delete("/api/drawingProd/entry_delete/5?co_id=1")
        assert resp.status_code == 200
        sql = str(self._mock_session.execute.call_args_list[1][0][0])
        assert "active = 0" in sql

    def test_delete_not_found(self):
        found_result = MagicMock()
        found_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [found_result]
        resp = client.delete("/api/drawingProd/entry_delete/5?co_id=1")
        assert resp.status_code == 404


class TestDrawingMachineAttrMaster(TestDrawingBase):
    def test_list_returns_all_machines(self):
        row = _mock_row(
            {
                "drawing_machine_attr_id": None,
                "machine_id": 61,
                "mech_code": "21001",
                "machine_name": "1st Drawing - 1",
                "dept_name": "Drawing",
                "branch_id": 4,
                "const_meter": None,
                "mc_group": None,
                "meter_wrap_limit": None,
                "active": None,
            }
        )
        self._mock_session.execute.return_value.fetchall.return_value = [row]
        resp = client.get("/api/drawingMasters/drawing_machine_attr_list?co_id=1")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["drawing_machine_attr_id"] is None

    def test_create_duplicate_rejected_even_inactive(self):
        dup_result = MagicMock()
        dup_row = MagicMock()
        dup_row.drawing_machine_attr_id = 3
        dup_result.fetchone.return_value = dup_row
        self._mock_session.execute.side_effect = [dup_result]
        resp = client.post(
            "/api/drawingMasters/drawing_machine_attr_create",
            json={"co_id": 1, "machine_id": 61, "const_meter": 8000.0},
        )
        assert resp.status_code == 400
        assert "already configured" in resp.json()["detail"]

    def test_create_success(self):
        dup_result = MagicMock()
        dup_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.lastrowid = 11
        self._mock_session.execute.side_effect = [dup_result, insert_result]
        resp = client.post(
            "/api/drawingMasters/drawing_machine_attr_create",
            json={"co_id": 1, "machine_id": 61, "const_meter": 8000.0, "mc_group": "DRG-A"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["drawing_machine_attr_id"] == 11
        params = _exec_params(self._mock_session, 1)
        assert params["meter_wrap_limit"] == 10000  # default

    def test_edit_updates_fields(self):
        found_result = MagicMock()
        found_row = MagicMock()
        found_row.drawing_machine_attr_id = 11
        found_result.fetchone.return_value = found_row
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [found_result, update_result]
        resp = client.put(
            "/api/drawingMasters/drawing_machine_attr_edit/11?co_id=1",
            json={"const_meter": 9000.0, "active": 0},
        )
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 1)
        assert params["const_meter"] == 9000.0
        assert params["active"] == 0
