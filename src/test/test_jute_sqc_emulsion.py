"""
Tests for R-08-02 Emulsion SQC endpoints.
Tests for src/juteSQC/emulsion.py

R-08-02 is a daily recipe log (ONE flat row per date, no readings array, no StDev/CV). The
only computed bits are theoretical_oil_pct (= oil_used/tank*100) and oil_pct_status
(OK/LOW/HIGH vs the snapshotted band) — both derived on READ.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# VERIFIED EXAMPLE (lock): oil_used 170, tank 1000, oil_pct 16.5, band 16-17
# -> theoretical_oil_pct 17.0, status OK.
VERIFIED_OIL_USED = 170
VERIFIED_TANK = 1000
VERIFIED_OIL_PCT = 16.5
VERIFIED_BAND_LOW = 16
VERIFIED_BAND_HIGH = 17
VERIFIED_THEORETICAL = 17.0


def _base_body(**overrides):
    body = {
        "co_id": 1,
        "branch_id": 1,
        "entry_date": "2026-06-28",
        "mc_id": 5,
        "oil_used_ltr": VERIFIED_OIL_USED,
        "tank_capacity_ltr": VERIFIED_TANK,
        "oil_pct_in_emulsion": VERIFIED_OIL_PCT,
        "std_oil_pct_low": VERIFIED_BAND_LOW,
        "std_oil_pct_high": VERIFIED_BAND_HIGH,
        "prepared_by": "QC Lab",
    }
    body.update(overrides)
    return body


def _by_date_row(**overrides):
    """A by_date result row matching get_emulsion_by_date_query's projection."""
    row = {
        "emulsion_id": 1,
        "co_id": 1,
        "branch_id": 1,
        "entry_date": "2026-06-28",
        "mc_id": 5,
        "machine_name": "SPREADER 1",
        "oil_used_ltr": VERIFIED_OIL_USED,
        "tank_capacity_ltr": VERIFIED_TANK,
        "oil_pct_in_emulsion": VERIFIED_OIL_PCT,
        "std_oil_pct_low": VERIFIED_BAND_LOW,
        "std_oil_pct_high": VERIFIED_BAND_HIGH,
        "adco_used_ml": 20.0,
        "spreader_rolls_made": 42,
        "others": None,
        "prepared_by": "QC Lab",
        "updated_date_time": "2026-06-28 10:00:00",
    }
    row.update(overrides)
    return row


class TestEmulsionMath:
    """Pure-function locks — no HTTP, no DB."""

    def test_theoretical_oil_pct_lock(self):
        from src.juteSQC.emulsion import theoretical_oil_pct
        assert theoretical_oil_pct(170, 1000) == 17.0

    def test_theoretical_oil_pct_div_guard(self):
        from src.juteSQC.emulsion import theoretical_oil_pct
        assert theoretical_oil_pct(170, 0) is None
        assert theoretical_oil_pct(170, None) is None
        assert theoretical_oil_pct(None, 1000) is None

    def test_oil_pct_status_lock(self):
        from src.juteSQC.emulsion import oil_pct_status
        # 16.5 in 16-17 -> OK; 15 -> LOW; 18 -> HIGH (the verified band)
        assert oil_pct_status(16.5, 16, 17) == "OK"
        assert oil_pct_status(15, 16, 17) == "LOW"
        assert oil_pct_status(18, 16, 17) == "HIGH"
        # band edges are inclusive
        assert oil_pct_status(16, 16, 17) == "OK"
        assert oil_pct_status(17, 16, 17) == "OK"

    def test_oil_pct_status_null_guard(self):
        from src.juteSQC.emulsion import oil_pct_status
        assert oil_pct_status(None, 16, 17) is None
        assert oil_pct_status(16.5, None, 17) is None
        assert oil_pct_status(16.5, 16, None) is None


class TestEmulsionEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        mc_row = _mock_row(
            {"machine_id": 5, "machine_name": "SPREADER 1", "mech_code": "SP1"}
        )
        # duplicate machine_id row must be de-duped
        mc_dup = _mock_row(
            {"machine_id": 5, "machine_name": "SPREADER 1", "mech_code": "SP1"}
        )
        self._mock_session.execute.return_value.fetchall.return_value = [mc_row, mc_dup]

        response = client.get("/api/juteSQC/emulsion_create_setup?co_id=1&branch_id=1")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["default_oil_pct_low"] == 16.0
        assert data["default_oil_pct_high"] == 17.0
        assert data["default_tank_capacity"] == 1000.0
        assert len(data["machines"]) == 1
        assert data["machines"][0]["machine_name"] == "SPREADER 1"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/emulsion_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "emulsion_id", 7)
        )
        response = client.post("/api/juteSQC/create_emulsion", json=_base_body())
        assert response.status_code == 200
        body = response.json()
        assert body["emulsion_id"] == 7
        assert "created" in body["message"].lower()
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

        record = self._mock_session.add.call_args[0][0]
        # band edges snapshotted, additives copied through
        assert float(record.std_oil_pct_low) == 16
        assert float(record.std_oil_pct_high) == 17
        assert record.prepared_by == "QC Lab"

    def test_create_optional_mc_id(self):
        """mc_id is OPTIONAL — omitting it still saves."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "emulsion_id", 8)
        )
        body = _base_body()
        body.pop("mc_id")
        response = client.post("/api/juteSQC/create_emulsion", json=body)
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.mc_id is None

    def test_create_non_positive_oil_used(self):
        response = client.post(
            "/api/juteSQC/create_emulsion", json=_base_body(oil_used_ltr=0)
        )
        assert response.status_code == 400
        assert "oil_used_ltr" in response.json()["detail"].lower()

    def test_create_non_positive_tank(self):
        response = client.post(
            "/api/juteSQC/create_emulsion", json=_base_body(tank_capacity_ltr=0)
        )
        assert response.status_code == 400
        assert "tank_capacity_ltr" in response.json()["detail"].lower()

    def test_create_non_positive_oil_pct(self):
        response = client.post(
            "/api/juteSQC/create_emulsion", json=_base_body(oil_pct_in_emulsion=0)
        )
        assert response.status_code == 400
        assert "oil_pct_in_emulsion" in response.json()["detail"].lower()

    def test_create_non_positive_band_low(self):
        response = client.post(
            "/api/juteSQC/create_emulsion", json=_base_body(std_oil_pct_low=0)
        )
        assert response.status_code == 400
        assert "std_oil_pct_low" in response.json()["detail"].lower()

    def test_create_band_high_below_low(self):
        response = client.post(
            "/api/juteSQC/create_emulsion",
            json=_base_body(std_oil_pct_low=17, std_oil_pct_high=16),
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "std_oil_pct_high" in detail and "std_oil_pct_low" in detail

    # ---------------------------------------------------------------- by_date
    def test_by_date_status_ok(self):
        """The verified example over the wire: theoretical 17.0, status OK."""
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row(_by_date_row())
        ]
        response = client.get(
            "/api/juteSQC/get_emulsion_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        rows = response.json()["data"]["rows"]
        assert len(rows) == 1
        first = rows[0]
        assert first["theoretical_oil_pct"] == VERIFIED_THEORETICAL
        assert first["oil_pct_status"] == "OK"
        assert first["machine_name"] == "SPREADER 1"

    def test_by_date_status_low(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row(_by_date_row(oil_pct_in_emulsion=15))
        ]
        response = client.get(
            "/api/juteSQC/get_emulsion_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        assert response.json()["data"]["rows"][0]["oil_pct_status"] == "LOW"

    def test_by_date_status_high(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row(_by_date_row(oil_pct_in_emulsion=18))
        ]
        response = client.get(
            "/api/juteSQC/get_emulsion_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        assert response.json()["data"]["rows"][0]["oil_pct_status"] == "HIGH"

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_emulsion_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_emulsion_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row(
            {
                "emulsion_id": 1,
                "entry_date": "2026-06-28",
                "branch_id": 1,
                "mc_id": 5,
                "machine_name": "SPREADER 1",
                "oil_used_ltr": VERIFIED_OIL_USED,
                "tank_capacity_ltr": VERIFIED_TANK,
                "oil_pct_in_emulsion": VERIFIED_OIL_PCT,
                "std_oil_pct_low": VERIFIED_BAND_LOW,
                "std_oil_pct_high": VERIFIED_BAND_HIGH,
                "updated_date_time": "2026-06-28 10:00:00",
            }
        )
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_emulsion_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1
        # status derived on the table row too
        assert body["data"][0]["oil_pct_status"] == "OK"

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_emulsion_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"emulsion_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_emulsion", json={"emulsion_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_emulsion", json={"emulsion_id": 999, "co_id": 1}
        )
        assert response.status_code == 404
