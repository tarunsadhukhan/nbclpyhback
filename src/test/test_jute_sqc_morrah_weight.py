"""
Tests for Morrah Weight QC endpoints.
Tests for src/juteSQC/morrahWeight.py
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.morrahWeight import compute_morrah_stats

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestComputeMorrahStats:
    """Unit tests for the compute_morrah_stats function."""

    def test_basic_calculation(self):
        weights = [1350, 1280, 1410, 1200, 1150, 1300, 1450, 1380, 1220, 1260]
        stats = compute_morrah_stats(weights)

        assert stats["calc_avg_weight"] == 1300.0
        assert stats["calc_max_weight"] == 1450
        assert stats["calc_min_weight"] == 1150
        assert stats["calc_range"] == 300
        assert stats["count_lt"] == 1   # 1150
        assert stats["count_ok"] == 7   # 1200, 1220, 1260, 1280, 1300, 1350, 1380
        assert stats["count_hy"] == 2   # 1410, 1450
        assert stats["calc_cv_pct"] > 0

    def test_all_ok(self):
        weights = [1300] * 10
        stats = compute_morrah_stats(weights)

        assert stats["calc_avg_weight"] == 1300.0
        assert stats["calc_range"] == 0
        assert stats["calc_cv_pct"] == 0.0
        assert stats["count_lt"] == 0
        assert stats["count_ok"] == 10
        assert stats["count_hy"] == 0

    def test_boundary_values(self):
        weights = [1200, 1400, 1199, 1401, 1200, 1400, 1200, 1400, 1200, 1400]
        stats = compute_morrah_stats(weights)

        assert stats["count_lt"] == 1   # 1199
        assert stats["count_hy"] == 1   # 1401
        assert stats["count_ok"] == 8

    def test_all_light(self):
        weights = [1000, 1050, 1100, 1150, 1199, 1000, 1050, 1100, 1150, 1199]
        stats = compute_morrah_stats(weights)

        assert stats["count_lt"] == 10
        assert stats["count_ok"] == 0
        assert stats["count_hy"] == 0


class TestMorrahWeightEndpoints:
    """Tests for Morrah Weight QC API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_create_setup_success(self):
        dept_row = _mock_row({"dept_id": 1, "dept_desc": "SQC", "dept_code": "SQC"})
        quality_row = _mock_row({"item_id": 10, "item_name": "D/4", "item_code": "D4"})

        self._mock_session.execute.return_value.fetchall.side_effect = [
            [dept_row],
            [quality_row],
        ]

        response = client.get(
            "/api/juteSQC/get_morrah_wt_create_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "departments" in data
        assert "jute_qualities" in data
        assert len(data["departments"]) == 1
        assert data["departments"][0]["dept_desc"] == "SQC"

    def test_create_setup_missing_co_id(self):
        response = client.get(
            "/api/juteSQC/get_morrah_wt_create_setup?branch_id=1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_create_setup_missing_branch_id(self):
        response = client.get(
            "/api/juteSQC/get_morrah_wt_create_setup?co_id=1"
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_success(self):
        self._mock_session.add = MagicMock()
        self._mock_session.commit = MagicMock()

        mock_record = MagicMock()
        mock_record.morrah_wt_id = 42
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "morrah_wt_id", 42)
        )

        response = client.post(
            "/api/juteSQC/create_morrah_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-02-24",
                "inspector_name": "John Doe",
                "dept_id": 1,
                "item_id": 10,
                "trolley_no": "T-001",
                "avg_mr_pct": 17.5,
                "weights": [1350, 1280, 1410, 1200, 1150, 1300, 1450, 1380, 1220, 1260],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Morrah weight QC log created successfully"
        assert "morrah_wt_id" in body
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

    def test_create_wrong_weight_count(self):
        response = client.post(
            "/api/juteSQC/create_morrah_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-02-24",
                "weights": [1300, 1300, 1300],
            },
        )
        assert response.status_code == 400
        assert "10" in response.json()["detail"]

    def test_create_negative_weight(self):
        response = client.post(
            "/api/juteSQC/create_morrah_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-02-24",
                "weights": [1300, -100, 1300, 1300, 1300, 1300, 1300, 1300, 1300, 1300],
            },
        )
        assert response.status_code == 400
        assert "positive" in response.json()["detail"].lower()

    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1

        data_row = _mock_row({
            "morrah_wt_id": 1,
            "entry_date": "2026-02-24",
            "trolley_no": "T-001",
            "inspector_name": "John",
            "avg_mr_pct": 17.5,
            "calc_avg_weight": 1300.0,
            "calc_max_weight": 1450,
            "calc_min_weight": 1150,
            "calc_range": 300,
            "calc_cv_pct": 7.5,
            "count_lt": 1,
            "count_ok": 7,
            "count_hy": 2,
            "branch_id": 1,
            "department": "SQC",
            "jute_quality": "D/4",
            "updated_date_time": "2026-02-24 10:00:00",
        })

        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_morrah_wt_table?co_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
        assert body["total"] == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_morrah_wt_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_view_by_id_success(self):
        data_row = MagicMock()
        data_row._mapping = {
            "morrah_wt_id": 1,
            "co_id": 1,
            "branch_id": 1,
            "entry_date": "2026-02-24",
            "inspector_name": "John",
            "dept_id": 1,
            "item_id": 10,
            "trolley_no": "T-001",
            "avg_mr_pct": 17.5,
            "weights": "[1350, 1280, 1410, 1200, 1150, 1300, 1450, 1380, 1220, 1260]",
            "calc_avg_weight": 1300.0,
            "calc_max_weight": 1450,
            "calc_min_weight": 1150,
            "calc_range": 300,
            "calc_cv_pct": 7.5,
            "count_lt": 1,
            "count_ok": 7,
            "count_hy": 2,
            "updated_date_time": "2026-02-24 10:00:00",
            "department": "SQC",
            "jute_quality": "D/4",
        }
        self._mock_session.execute.return_value.fetchone.return_value = data_row

        response = client.get("/api/juteSQC/get_morrah_wt_by_id?id=1")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert body["data"]["morrah_wt_id"] == 1
        assert isinstance(body["data"]["weights"], list)
        assert len(body["data"]["weights"]) == 10

    def test_view_by_id_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/juteSQC/get_morrah_wt_by_id?id=99999")
        assert response.status_code == 404

    def test_view_by_id_missing_id(self):
        response = client.get("/api/juteSQC/get_morrah_wt_by_id")
        assert response.status_code == 400
        assert "id" in response.json()["detail"].lower()
