"""
Tests for R-08-20 Cutting Length QC endpoints.
Tests for src/juteSQC/cutting_length.py
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


# The VERIFIED EXAMPLE — locks the math (sample stdev n-1, NOT pstdev).
VERIFIED_READINGS = [78, 78, 79, 78, 78, 78, 78, 78, 78, 78, 78, 79, 77, 78, 78, 78, 78, 78, 78, 78]
VERIFIED_STD = 78
VERIFIED_AVG = 78.05
VERIFIED_STDEV = 0.394   # == 0.3940, round(..., 4) drops the trailing zero
VERIFIED_CV = 0.5048
VERIFIED_DEVIATION = 0.05


class TestCuttingLengthEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        cloth_row = _mock_row({"item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz"})
        self._mock_session.execute.return_value.fetchall.return_value = [cloth_row]

        response = client.get(
            "/api/juteSQC/cutting_length_create_setup?co_id=1&branch_id=1"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["readings_count"] == 20
        assert data["default_std_length"] == 78.0
        assert len(data["cloth_qualities"]) == 1
        assert data["cloth_qualities"][0]["item_name"] == "Hessian 10oz"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/cutting_length_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_math_lock(self):
        """Locks avg=78.05, sample stdev=0.3940, cv_pct=0.5048, deviation=0.05."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "cutting_length_id", 42)
        )
        response = client.post(
            "/api/juteSQC/create_cutting_length",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-06-28",
                "item_id": 10,
                "std_length": VERIFIED_STD,
                "readings": VERIFIED_READINGS,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Cutting length QC log created successfully"
        assert body["cutting_length_id"] == 42
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg == VERIFIED_AVG
        assert record.calc_stdev == VERIFIED_STDEV
        assert record.calc_cv_pct == VERIFIED_CV
        assert record.calc_deviation == VERIFIED_DEVIATION

    def test_create_optional_item_id(self):
        # Entry allowed without a cloth quality.
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "cutting_length_id", 43)
        )
        response = client.post(
            "/api/juteSQC/create_cutting_length",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_length": 78,
                "readings": VERIFIED_READINGS,
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.item_id is None

    def test_create_wrong_reading_count(self):
        response = client.post(
            "/api/juteSQC/create_cutting_length",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_length": 78,
                "readings": [78, 78, 78],
            },
        )
        assert response.status_code == 400
        assert "20" in response.json()["detail"]

    def test_create_non_positive_reading(self):
        readings = list(VERIFIED_READINGS)
        readings[5] = 0
        response = client.post(
            "/api/juteSQC/create_cutting_length",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_length": 78,
                "readings": readings,
            },
        )
        assert response.status_code == 400
        assert "positive" in response.json()["detail"].lower()

    def test_create_non_positive_std(self):
        response = client.post(
            "/api/juteSQC/create_cutting_length",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_length": 0,
                "readings": VERIFIED_READINGS,
            },
        )
        assert response.status_code == 400
        assert "std_length" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_success(self):
        row = _mock_row({
            "cutting_length_id": 1,
            "item_id": 10,
            "item_name": "H10",
            "item_code": "H10",
            "std_length": 78.0,
            "readings": "[78, 78, 79, 78, 78, 78, 78, 78, 78, 78, 78, 79, 77, 78, 78, 78, 78, 78, 78, 78]",
            "avg": 78.05,
            "stdev": 0.394,
            "cv_pct": 0.5048,
            "deviation": 0.05,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get(
            "/api/juteSQC/get_cutting_length_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        rows = response.json()["data"]["rows"]
        assert len(rows) == 1
        first = rows[0]
        assert isinstance(first["readings"], list) and len(first["readings"]) == 20
        assert first["avg"] == 78.05
        assert first["deviation"] == 0.05

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_cutting_length_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_cutting_length_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "cutting_length_id": 1,
            "entry_date": "2026-06-28",
            "branch_id": 1,
            "item_id": 10,
            "item_name": "H10",
            "item_code": "H10",
            "std_length": 78.0,
            "avg": 78.05,
            "stdev": 0.394,
            "cv_pct": 0.5048,
            "deviation": 0.05,
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_cutting_length_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_cutting_length_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"cutting_length_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_cutting_length",
            json={"cutting_length_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_cutting_length",
            json={"cutting_length_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
