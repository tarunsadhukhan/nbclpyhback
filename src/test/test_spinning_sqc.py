"""Tests for Spinning SQC capture endpoints.

Tests for src/juteSQC/spinning_sqc.py (prefix /api/juteSQC).

Portal persona: DB + auth are mocked via FastAPI dependency overrides, mirroring
the pattern in src/test/test_yarn_quality.py. The MagicMock session returns rows
whose ``._mapping`` is a plain dict, matching how the endpoints read results.

NOTE: spinning_sqc.py has no planning-grid endpoint (no "rows"/"shift_rollup"
response). That surface lives in src/juteProduction/spinning_entry.py
(planning_grid). The planning-grid assertion in the task brief does not apply to
this file.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.spinning_sqc import _observed_count, _corrected_count

client = TestClient(app)

ENTRY_DATE = "2026-06-13"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _machine_row():
    return _mock_row(
        {
            "machine_id": 1,
            "machine_name": "Spin-1",
            "mech_code": "SP1",
            "branch_id": 1,
            "no_of_spindle": 200,
        }
    )


def _quality_row():
    return _mock_row(
        {
            "item_id": 1,
            "item_code": "Q1",
            "item_name": "Quality One",
            "std_count": 10.0,
            "std_mr_pct": 13.75,
        }
    )


def _spell_row():
    return _mock_row(
        {
            "spell_id": 1,
            "spell_code": "A1",
            "spell_name": "Spell A1",
            "working_hours": 8.0,
        }
    )


def _entry_data_row():
    return _mock_row(
        {
            "spinning_sqc_entry_id": 10,
            "co_id": 1,
            "branch_id": 1,
            "entry_date": "2026-06-13",
            "mc_id": 1,
            "mech_code": "SP1",
            "machine_name": "Spin-1",
            "item_id": 1,
            "item_code": "Q1",
            "item_name": "Quality One",
            "actual_speed": 120.5,
            "actual_tpi": 4.25,
        }
    )


def _count_data_row():
    return _mock_row(
        {
            "spinning_sqc_count_id": 50,
            "co_id": 1,
            "branch_id": 1,
            "entry_date": "2026-06-13",
            "spell_id": 1,
            "spell_code": "A1",
            "mc_id": 1,
            "mech_code": "SP1",
            "machine_name": "Spin-1",
            "item_id": 1,
            "item_code": "Q1",
            "item_name": "Quality One",
            "observed_count": 18.5,
        }
    )


def _avg_row():
    return _mock_row(
        {
            "item_id": 1,
            "item_code": "Q1",
            "item_name": "Quality One",
            "avg_count": 18.5,
            "obs_count": 2,
        }
    )


class TestSpinningSqcEntryEndpoints:
    """jute_sqc_spinning_entry — single-value actual Speed / TPI."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ---- GET /sqc_entry_setup ----------------------------------------------

    def test_sqc_entry_setup_success(self):
        # _fetch_machines, _fetch_qualities, then entries-by-date: 3 fetchall calls
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_machine_row()],
            [_quality_row()],
            [_entry_data_row()],
        ]

        response = client.get(
            f"/api/juteSQC/sqc_entry_setup?co_id=1&entry_date={ENTRY_DATE}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" in data
        assert "yarn_items" in data
        assert "entries" in data
        assert data["machines"][0]["machine_id"] == 1
        assert data["entries"][0]["spinning_sqc_entry_id"] == 10

    def test_sqc_entry_setup_missing_co_id(self):
        response = client.get(f"/api/juteSQC/sqc_entry_setup?entry_date={ENTRY_DATE}")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_sqc_entry_setup_missing_entry_date(self):
        response = client.get("/api/juteSQC/sqc_entry_setup?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json().get("detail", "").lower()

    def test_sqc_entry_setup_db_error(self):
        self._mock_session.execute.side_effect = Exception("DB connection failed")
        response = client.get(
            f"/api/juteSQC/sqc_entry_setup?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 500

    # ---- POST /sqc_entry_save ----------------------------------------------

    def test_sqc_entry_save_insert_success(self):
        # No existing active row -> insert path
        self._mock_session.execute.return_value.fetchone.return_value = None

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {
                    "mc_id": 1,
                    "item_id": 1,
                    "actual_speed": 120.5,
                    "actual_tpi": 4.25,
                }
            ],
        }

        response = client.post("/api/juteSQC/sqc_entry_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1
        self._mock_session.commit.assert_called_once()

    def test_sqc_entry_save_update_success(self):
        # Existing active row -> update path
        existing = MagicMock()
        existing.spinning_sqc_entry_id = 10
        self._mock_session.execute.return_value.fetchone.return_value = existing

        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {"mc_id": 1, "item_id": 1, "actual_speed": 99.0}
            ],
        }

        response = client.post("/api/juteSQC/sqc_entry_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1

    def test_sqc_entry_save_empty_entries(self):
        payload = {"co_id": 1, "entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/sqc_entry_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 0

    def test_sqc_entry_save_missing_co_id_in_body(self):
        # co_id is a required field on SqcEntrySave -> pydantic 422
        payload = {"entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/sqc_entry_save", json=payload)
        assert response.status_code == 422

    def test_sqc_entry_save_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("insert failed")
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [{"mc_id": 1, "item_id": 1, "actual_speed": 1.0}],
        }
        response = client.post("/api/juteSQC/sqc_entry_save", json=payload)
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()

    # ---- GET /sqc_entry_by_date --------------------------------------------

    def test_sqc_entry_by_date_success(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _entry_data_row()
        ]
        response = client.get(
            f"/api/juteSQC/sqc_entry_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert data[0]["mc_id"] == 1

    def test_sqc_entry_by_date_empty(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get(
            f"/api/juteSQC/sqc_entry_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_sqc_entry_by_date_missing_co_id(self):
        response = client.get(f"/api/juteSQC/sqc_entry_by_date?entry_date={ENTRY_DATE}")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()


class TestSpinningSqcCountEndpoints:
    """jute_sqc_spinning_count — multi-observation count."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ---- GET /sqc_count_setup ----------------------------------------------

    def test_sqc_count_setup_success(self):
        # _fetch_machines, _fetch_qualities, _fetch_spells, then entries: 4 calls
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_machine_row()],
            [_quality_row()],
            [_spell_row()],
            [_count_data_row()],
        ]

        response = client.get(
            f"/api/juteSQC/sqc_count_setup?co_id=1&entry_date={ENTRY_DATE}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" in data
        assert "yarn_items" in data
        assert "spells" in data
        assert "entries" in data
        assert data["spells"][0]["spell_code"] == "A1"
        assert data["entries"][0]["spinning_sqc_count_id"] == 50

    def test_sqc_count_setup_missing_co_id(self):
        response = client.get(f"/api/juteSQC/sqc_count_setup?entry_date={ENTRY_DATE}")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_sqc_count_setup_missing_entry_date(self):
        response = client.get("/api/juteSQC/sqc_count_setup?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json().get("detail", "").lower()

    # ---- POST /sqc_count_save ----------------------------------------------

    def test_sqc_count_save_success(self):
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {
                    "spell_id": 1,
                    "mc_id": 1,
                    "item_id": 1,
                    "observed_count": 18.5,
                },
                {
                    "spell_id": 1,
                    "mc_id": 1,
                    "item_id": 1,
                    "observed_count": 19.0,
                },
            ],
        }

        response = client.post("/api/juteSQC/sqc_count_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 2
        self._mock_session.commit.assert_called_once()

    def test_sqc_count_save_empty_entries(self):
        payload = {"co_id": 1, "entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/sqc_count_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 0

    def test_sqc_count_save_missing_co_id_in_body(self):
        payload = {"entry_date": ENTRY_DATE, "entries": []}
        response = client.post("/api/juteSQC/sqc_count_save", json=payload)
        assert response.status_code == 422

    def test_sqc_count_save_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("insert failed")
        payload = {
            "co_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [{"item_id": 1, "observed_count": 1.0}],
        }
        response = client.post("/api/juteSQC/sqc_count_save", json=payload)
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()

    # ---- GET /sqc_count_by_date --------------------------------------------

    def test_sqc_count_by_date_success(self):
        # readings then averages: 2 fetchall calls
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_count_data_row()],
            [_avg_row()],
        ]

        response = client.get(
            f"/api/juteSQC/sqc_count_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "readings" in data
        assert "averages" in data
        assert data["readings"][0]["spinning_sqc_count_id"] == 50
        assert data["averages"][0]["avg_count"] == 18.5
        assert data["averages"][0]["obs_count"] == 2

    def test_sqc_count_by_date_empty(self):
        self._mock_session.execute.return_value.fetchall.side_effect = [[], []]
        response = client.get(
            f"/api/juteSQC/sqc_count_by_date?co_id=1&entry_date={ENTRY_DATE}"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["readings"] == []
        assert data["averages"] == []

    def test_sqc_count_by_date_missing_co_id(self):
        response = client.get(f"/api/juteSQC/sqc_count_by_date?entry_date={ENTRY_DATE}")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    # ---- DELETE /sqc_count_delete/{count_id} -------------------------------

    def test_sqc_count_delete_success(self):
        existing = MagicMock()
        existing.spinning_sqc_count_id = 50
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.delete("/api/juteSQC/sqc_count_delete/50")

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()

    def test_sqc_count_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/sqc_count_delete/999")

        assert response.status_code == 404
        assert "not found" in response.json().get("detail", "").lower()

    def test_sqc_count_delete_db_error_rolls_back(self):
        self._mock_session.execute.side_effect = Exception("delete failed")
        response = client.delete("/api/juteSQC/sqc_count_delete/50")
        assert response.status_code == 500
        self._mock_session.rollback.assert_called_once()

    # ---- R-08-16 count save with raw inputs (server recompute) -------------

    def test_sqc_count_save_computes_observed_and_corrected(self):
        # std_mr_pct lookup returns 13.75; insert should receive computed counts.
        std_mr_row = _mock_row({"std_mr_pct": 13.75})
        self._mock_session.execute.return_value.fetchone.return_value = std_mr_row

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "entry_date": ENTRY_DATE,
            "entries": [
                {
                    "spell_id": 1,
                    "mc_id": 1,
                    "item_id": 1,
                    "dp": 2.0,
                    "tp": 3.0,
                    "wt_450_gms": 450.0,
                    "mr_pct": 10.0,
                }
            ],
        }

        response = client.post("/api/juteSQC/sqc_count_save", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["saved"] == 1

        # Find the INSERT execute call and check the computed bind params.
        insert_params = None
        for call in self._mock_session.execute.call_args_list:
            params = call.args[1] if len(call.args) > 1 else None
            if isinstance(params, dict) and "observed_count" in params:
                insert_params = params
                break
        assert insert_params is not None
        assert insert_params["observed_count"] == 31.72       # round(450/450*14400/454, 2)
        assert insert_params["corrected_count"] == 32.8        # round(31.72/110*113.75, 2)
        assert insert_params["dp"] == 2.0
        assert insert_params["tp"] == 3.0


class TestSqcCountCalc:
    """Pure formula checks for R-08-16 observed / corrected count."""

    def test_observed_count_basic(self):
        # 450 gms -> (450/450) * (14400/454) = 31.7180... -> 31.72
        assert _observed_count(450.0) == 31.72

    def test_observed_count_none_or_zero(self):
        assert _observed_count(None) is None
        assert _observed_count(0) is None

    def test_corrected_count_basic(self):
        # 31.72 / (100+10) * (100+13.75) = 32.80
        assert _corrected_count(31.72, 10.0, 13.75) == 32.8

    def test_corrected_count_missing_inputs(self):
        assert _corrected_count(None, 10.0, 13.75) is None
        assert _corrected_count(31.72, None, 13.75) is None
        assert _corrected_count(31.72, 10.0, None) is None
