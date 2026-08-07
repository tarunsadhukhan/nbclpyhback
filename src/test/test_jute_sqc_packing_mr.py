"""
Tests for R-08-25 Packing MR% QC endpoints.
Tests for src/juteSQC/packing_mr.py
"""

import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

# VERIFIED example (lock). Three HESSIAN columns + one SACKING column.
HES_1 = [21, 18, 19, 17, 20, 18, 22, 22, 17, 18]   # avg 19.2 (192/10)
HES_2 = [21, 16, 19, 19, 18, 21, 18, 20, 21, 22]   # avg 19.5 (195/10)
HES_3 = [21, 18, 17, 20, 20, 18, 19, 21, 20, 21]   # avg 19.5 (195/10)
SAC_1 = [20, 19, 19, 18, 22, 19, 21, 20, 20, 19]   # avg 19.7 (197/10)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestPackingMrEndpoints:
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

        response = client.get("/api/juteSQC/packing_mr_create_setup?co_id=1&branch_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["readings_count"] == 10
        assert data["quality_groups"] == ["HESSIAN", "SACKING"]
        assert len(data["qualities"]) == 1
        assert data["qualities"][0]["item_name"] == "Hessian 10oz"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/packing_mr_create_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "packing_mr_id", 7)
        )

        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "item_id": 10,
                "quality_label": "Hessian 10oz",
                "construction_code": "10x10x40",
                "readings": HES_1,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Packing MR% QC log created successfully"
        assert body["packing_mr_id"] == 7
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()
        # avg of the 10 readings, rounded to 3dp
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_mr == 19.2
        assert json.loads(record.readings) == HES_1

    def test_create_optional_links_omitted(self):
        # item_id / quality_label / construction_code are all optional.
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "packing_mr_id", 8)
        )
        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "SACKING",
                "readings": SAC_1,
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.item_id is None
        assert record.construction_code is None
        assert record.calc_avg_mr == 19.7

    def test_create_empty_readings_rejected(self):
        # At least one reading is required; an empty array is the only invalid count now.
        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "readings": [],
            },
        )
        assert response.status_code == 400
        assert "at least one" in response.json()["detail"].lower()

    def test_create_variable_reading_count(self):
        # Any count >= 1 is accepted; avg = mean(readings) regardless of length.
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "packing_mr_id", 9)
        )
        readings = [18, 20, 22, 19, 21, 20, 18, 19, 20, 21, 22, 20]  # 12 readings, avg 20.0
        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "readings": readings,
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert json.loads(record.readings) == readings
        assert record.calc_avg_mr == round(sum(readings) / len(readings), 3)

    def test_create_non_positive_reading(self):
        bad = list(HES_1)
        bad[3] = 0
        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "readings": bad,
            },
        )
        assert response.status_code == 400
        assert "positive" in response.json()["detail"].lower()

    def test_create_bad_quality_group(self):
        response = client.post(
            "/api/juteSQC/create_packing_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "NYLON",
                "readings": HES_1,
            },
        )
        assert response.status_code == 400
        assert "quality_group" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_math_lock(self):
        # The four VERIFIED columns -> per-column avgs 19.2/19.5/19.5/19.7;
        # group roll-up HESSIAN 19.4 (582/30), SACKING 19.7 (197/10).
        rows = [
            _mock_row({
                "packing_mr_id": 1, "quality_group": "HESSIAN", "item_id": 10,
                "item_name": "H10", "quality_label": "Hessian 10oz",
                "construction_code": "C1", "readings": json.dumps(HES_1),
                "calc_avg_mr": 19.2,
            }),
            _mock_row({
                "packing_mr_id": 2, "quality_group": "HESSIAN", "item_id": 10,
                "item_name": "H10", "quality_label": "Hessian 10oz",
                "construction_code": "C2", "readings": json.dumps(HES_2),
                "calc_avg_mr": 19.5,
            }),
            _mock_row({
                "packing_mr_id": 3, "quality_group": "HESSIAN", "item_id": 10,
                "item_name": "H10", "quality_label": "Hessian 10oz",
                "construction_code": "C3", "readings": json.dumps(HES_3),
                "calc_avg_mr": 19.5,
            }),
            _mock_row({
                "packing_mr_id": 4, "quality_group": "SACKING", "item_id": 11,
                "item_name": "S5", "quality_label": "Sacking", "construction_code": "C4",
                "readings": json.dumps(SAC_1), "calc_avg_mr": 19.7,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/juteSQC/get_packing_mr_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        data = response.json()["data"]

        cols = data["columns"]
        assert len(cols) == 4
        assert [c["avg_mr"] for c in cols] == [19.2, 19.5, 19.5, 19.7]
        # readings parsed back to a 10-element list
        assert isinstance(cols[0]["readings"], list) and len(cols[0]["readings"]) == 10

        summaries = {s["quality_group"]: s for s in data["group_summaries"]}
        # WEIGHTED mean: HESSIAN = (192+195+195)/30 = 582/30 = 19.4
        assert summaries["HESSIAN"]["group_avg_mr"] == 19.4
        assert summaries["HESSIAN"]["column_count"] == 3
        assert summaries["HESSIAN"]["reading_count"] == 30
        # SACKING = 197/10 = 19.7
        assert summaries["SACKING"]["group_avg_mr"] == 19.7
        assert summaries["SACKING"]["column_count"] == 1
        assert summaries["SACKING"]["reading_count"] == 10

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_packing_mr_by_date?co_id=1&branch_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_packing_mr_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "packing_mr_id": 1, "entry_date": "2026-06-28", "quality_group": "HESSIAN",
            "item_id": 10, "item_name": "H10", "quality_label": "Hessian 10oz",
            "construction_code": "C1", "calc_avg_mr": 19.2, "branch_id": 1,
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_packing_mr_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_packing_mr_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"packing_mr_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_packing_mr",
            json={"packing_mr_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_packing_mr",
            json={"packing_mr_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
