"""Tests for the Weaving Pick-SQC capture endpoints.

Tests for src/juteSQC/weaving_sqc.py (prefix /api/juteSQC, tags=["jute-sqc-weaving"]).

Portal persona: DB + auth are mocked. ``get_tenant_db`` and
``get_current_user_with_refresh`` are resolved by FastAPI via ``Depends``, so we
override them through ``app.dependency_overrides`` keyed by those exact symbols --
mirroring the sibling Spinning SQC suite (src/test/test_spinning_sqc.py) and the
Weaving Production Entry suite (src/test/test_weaving_entry.py). The MagicMock
session returns rows whose ``._mapping`` is a plain dict, matching how the router
serializes results (``[dict(r._mapping) for r in ...]``).

Shapes follow the SHARED CONTRACT:
  setup   -> {"data": {"qualities": [...], "looms": [...], "readings": [...], "summary": [...]}}
  by_date -> {"data": {"readings": [...], "summary": [...]}}
  save    -> {"data": {"saved": <int>}}   (insert-only, one execute per row)
  delete  -> {"data": {"message": "Deleted"}}

The production-wiring resolver resolve_act_picks(...) in
src/juteProduction/services/weaving_standards.py is unit-tested directly against a
mocked Session at the bottom.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteSQC.weaving_sqc import (
    get_tenant_db,
    get_current_user_with_refresh,
)
from src.juteProduction.services.weaving_standards import resolve_act_picks

client = TestClient(app)

ENTRY_DATE = "2026-06-23"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# --- option rows (reused queries) -------------------------------------------

def _quality_option_row():
    """get_weaving_entry_qualities_query option row."""
    return _mock_row(
        {
            "weaving_quality_id": 5,
            "item_id": 10,
            "item_code": "JC",
            "item_name": "Jute Cloth",
            "weaving_quality_code": "Q5",
            "weaving_quality_name": "Red",
        }
    )


def _loom_option_row():
    """get_weaving_entry_machines_query option row."""
    return _mock_row(
        {
            "machine_id": 7,
            "machine_name": "Loom-1",
            "mech_code": "L01",
            "line_no": "1",
            "branch_id": 2,
        }
    )


# --- reading / summary rows --------------------------------------------------

def _reading_row(pick_id=11, picks=18.0, width=48.0):
    return _mock_row(
        {
            "weaving_sqc_pick_id": pick_id,
            "co_id": 1,
            "branch_id": 2,
            "entry_date": ENTRY_DATE,
            "weaving_quality_id": 5,
            "weaving_quality_code": "Q5",
            "weaving_quality_name": "Red",
            "item_code": "JC",
            "item_name": "Jute Cloth",
            "machine_id": 7,
            "mech_code": "L01",
            "machine_name": "Loom-1",
            "line_no": "1",
            "width": width,
            "picks": picks,
        }
    )


def _summary_row():
    return _mock_row(
        {
            "weaving_quality_id": 5,
            "weaving_quality_code": "Q5",
            "weaving_quality_name": "Red",
            "avg_picks": 18.5,
            "std_picks": 0.7071,
            "min_picks": 18.0,
            "max_picks": 19.0,
            "avg_width": 48.0,
            "min_width": 48.0,
            "max_width": 48.0,
            "n_obs": 2,
        }
    )


class TestWeavingSqcPickSetup:
    """GET /weaving_sqc_pick_setup -> qualities + looms + readings + summary."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_setup_success(self):
        # qualities, looms, readings, summary -> 4 fetchall calls in order.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_quality_option_row()],
            [_loom_option_row()],
            [_reading_row()],
            [_summary_row()],
        ]

        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_setup?co_id=1&entry_date={ENTRY_DATE}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "qualities" in data
        assert "looms" in data
        assert "readings" in data
        assert "summary" in data
        assert data["qualities"][0]["weaving_quality_id"] == 5
        assert data["qualities"][0]["item_id"] == 10
        assert data["looms"][0]["machine_id"] == 7
        assert data["readings"][0]["weaving_sqc_pick_id"] == 11
        assert data["readings"][0]["picks"] == 18.0
        assert data["summary"][0]["avg_picks"] == 18.5
        assert data["summary"][0]["n_obs"] == 2

    def test_setup_missing_co_id(self):
        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_setup?entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_setup_missing_entry_date(self):
        response = client.get("/api/juteSQC/weaving_sqc_pick_setup?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json().get("detail", "").lower()

    def test_setup_with_branch_id(self):
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_quality_option_row()],
            [_loom_option_row()],
            [_reading_row()],
            [_summary_row()],
        ]
        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_setup?co_id=1&entry_date={ENTRY_DATE}&branch_id=2"
        )
        assert response.status_code == 200
        assert response.json()["data"]["looms"][0]["branch_id"] == 2

    def test_setup_db_error(self):
        self._mock_session.execute.side_effect = Exception("DB connection failed")
        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_setup?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 500


class TestWeavingSqcPickSave:
    """POST /weaving_sqc_pick_save -> insert-only, one execute per row."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_save_two_entries(self):
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "entry_date": ENTRY_DATE,
            "entries": [
                {"weaving_quality_id": 5, "machine_id": 7, "width": 48.0, "picks": 18.0},
                {"weaving_quality_id": 5, "machine_id": 7, "width": 48.0, "picks": 19.0},
            ],
        }

        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 2
        # Insert-only: exactly one execute() per reading row (no select/upsert).
        assert self._mock_session.execute.call_count == 2
        self._mock_session.commit.assert_called_once()

    def test_save_null_width_allowed(self):
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {"weaving_quality_id": 5, "machine_id": 7, "picks": 20.0},
            ],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        assert self._mock_session.execute.call_count == 1

    def test_save_empty_entries(self):
        payload = {"co_id": 1, "entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 0
        self._mock_session.execute.assert_not_called()

    def test_save_with_spell_stamps_spell_id(self):
        """Optional body.spell resolves branch-aware ONCE and stamps spell_id on
        every inserted reading (Phase 1c join-key hygiene)."""
        spell_row = MagicMock()
        spell_row.spell_id = 3
        resolve_exec = MagicMock()
        resolve_exec.fetchone.return_value = spell_row
        insert_exec = MagicMock()
        self._mock_session.execute.side_effect = [resolve_exec, insert_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "entry_date": ENTRY_DATE,
            "spell": "A1",
            "entries": [{"weaving_quality_id": 5, "machine_id": 7, "picks": 18.0}],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        # Execute order: spell resolve, then the insert with spell_id stamped.
        insert_params = self._mock_session.execute.call_args_list[1][0][1]
        assert insert_params["spell_id"] == 3

    def test_save_without_spell_inserts_null_spell_id(self):
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [{"weaving_quality_id": 5, "machine_id": 7, "picks": 18.0}],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 200
        # No spell -> no resolve execute, single insert with spell_id None.
        assert self._mock_session.execute.call_count == 1
        insert_params = self._mock_session.execute.call_args_list[0][0][1]
        assert insert_params["spell_id"] is None

    def test_save_unknown_spell_returns_400(self):
        no_row = MagicMock()
        no_row.fetchone.return_value = None
        # branch_id None -> single resolve attempt, no branch fallback.
        self._mock_session.execute.return_value = no_row
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "spell": "ZZ",
            "entries": [{"weaving_quality_id": 5, "machine_id": 7, "picks": 18.0}],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 400
        assert "spell" in response.json()["detail"].lower()
        self._mock_session.rollback.assert_called_once()

    def test_save_missing_co_id_in_body(self):
        # co_id required on WeavingPickSave -> pydantic 422.
        payload = {"entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 422

    def test_save_negative_picks_rejected(self):
        # picks has ge=0 constraint -> pydantic 422.
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {"weaving_quality_id": 5, "machine_id": 7, "picks": -1.0},
            ],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 422

    def test_save_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("insert failed")
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {"weaving_quality_id": 5, "machine_id": 7, "picks": 18.0},
            ],
        }
        response = client.post("/api/juteSQC/weaving_sqc_pick_save", json=payload)
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()


class TestWeavingSqcPickByDate:
    """GET /weaving_sqc_pick_by_date -> {readings, summary}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_by_date_success(self):
        # readings then summary -> 2 fetchall calls.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_reading_row(pick_id=11, picks=18.0), _reading_row(pick_id=12, picks=19.0)],
            [_summary_row()],
        ]

        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "readings" in data
        assert "summary" in data
        assert len(data["readings"]) == 2
        assert data["readings"][0]["weaving_sqc_pick_id"] == 11
        # summary row carries the vw_weaving_pick_act aggregate columns.
        s = data["summary"][0]
        assert s["avg_picks"] == 18.5
        assert s["std_picks"] == 0.7071
        assert s["min_picks"] == 18.0
        assert s["max_picks"] == 19.0
        assert s["n_obs"] == 2

    def test_by_date_empty(self):
        self._mock_session.execute.return_value.fetchall.side_effect = [[], []]
        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["readings"] == []
        assert data["summary"] == []

    def test_by_date_missing_co_id(self):
        response = client.get(
            f"/api/juteSQC/weaving_sqc_pick_by_date?entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/weaving_sqc_pick_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json().get("detail", "").lower()


class TestWeavingSqcPickDelete:
    """DELETE /weaving_sqc_pick_delete/{pick_id} -> soft delete with active-row guard."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_delete_success(self):
        existing = MagicMock()
        existing.weaving_sqc_pick_id = 5
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.delete("/api/juteSQC/weaving_sqc_pick_delete/5")

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        # active-row guard returns None -> 404, no commit.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/weaving_sqc_pick_delete/999")

        assert response.status_code == 404
        assert "not found" in response.json().get("detail", "").lower()
        self._mock_session.commit.assert_not_called()

    def test_delete_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("delete failed")
        response = client.delete("/api/juteSQC/weaving_sqc_pick_delete/5")
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()


class TestResolveActPicks:
    """Unit test for resolve_act_picks (production wiring into weaving_standards)."""

    def test_returns_avg_picks(self):
        row = MagicMock()
        row.avg_picks = 18.5
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row

        result = resolve_act_picks(db, co_id=1, weaving_quality_id=5, on_date=ENTRY_DATE)

        assert result == 18.5
        assert isinstance(result, float)

    def test_returns_zero_when_no_row(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None

        result = resolve_act_picks(db, co_id=1, weaving_quality_id=5, on_date=ENTRY_DATE)

        assert result == 0.0

    def test_returns_zero_when_quality_falsy(self):
        db = MagicMock()
        result = resolve_act_picks(db, co_id=1, weaving_quality_id=None, on_date=ENTRY_DATE)
        assert result == 0.0
        # Falsy quality short-circuits before any DB hit.
        db.execute.assert_not_called()

    def test_returns_zero_when_avg_picks_null(self):
        row = MagicMock()
        row.avg_picks = None
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = row

        result = resolve_act_picks(db, co_id=1, weaving_quality_id=5, on_date=ENTRY_DATE)
        assert result == 0.0
