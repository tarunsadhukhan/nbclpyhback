"""
Tests for Humidity Recording SQC endpoints.
Tests for src/juteSQC/humidity.py
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


class TestHumidityEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        dept_row = _mock_row({"dept_id": 5, "dept_desc": "BATCHING", "dept_code": "BAT"})
        self._mock_session.execute.return_value.fetchall.return_value = [dept_row]

        response = client.get("/api/juteSQC/humidity_create_setup?co_id=1&branch_id=2")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["spots_per_round"] == 3
        # exactly 3 rounds, Morning/Noon/Evening
        assert len(data["rounds"]) == 3
        assert [r["round_no"] for r in data["rounds"]] == [1, 2, 3]
        assert [r["label"] for r in data["rounds"]] == ["Morning", "Noon", "Evening"]
        assert len(data["departments"]) == 1
        assert data["departments"][0]["dept_desc"] == "BATCHING"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/humidity_create_setup?branch_id=2")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_create_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/humidity_create_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ------------------------------------------------------- avg math-lock
    def test_compute_avgs_locks(self):
        """Locked verified examples: mean(temp_c), mean(rh_pct), 2dp."""
        from src.juteSQC.humidity import compute_humidity_avgs

        a = compute_humidity_avgs(
            [
                {"temp_c": 17, "rh_pct": 81},
                {"temp_c": 17, "rh_pct": 80},
                {"temp_c": 17, "rh_pct": 81},
            ]
        )
        assert a["calc_avg_temp"] == 17.0
        assert a["calc_avg_rh"] == 80.67

        b = compute_humidity_avgs(
            [
                {"temp_c": 18.2, "rh_pct": 69},
                {"temp_c": 18.2, "rh_pct": 68},
                {"temp_c": 18.1, "rh_pct": 68},
            ]
        )
        assert b["calc_avg_temp"] == 18.17
        assert b["calc_avg_rh"] == 68.33

        c = compute_humidity_avgs(
            [
                {"temp_c": 17, "rh_pct": 75},
                {"temp_c": 16, "rh_pct": 78},
                {"temp_c": 17, "rh_pct": 76},
            ]
        )
        assert c["calc_avg_temp"] == 16.67
        assert c["calc_avg_rh"] == 76.33

    def test_create_math_lock_stored(self):
        """create stores the computed avg_temp / avg_rh on the record (17.0 / 80.67)."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "humidity_id", 7)
        )
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "branch_id": 2,
                "report_date": "2026-06-28",
                "dept_id": 5,
                "round_no": 1,
                "prepared_by": "QC1",
                "spots": [
                    {"spot_label": "A", "reading_time": "08:30", "temp_c": 17, "rh_pct": 81},
                    {"spot_label": "B", "reading_time": "08:35", "temp_c": 17, "rh_pct": 80},
                    {"spot_label": "C", "reading_time": "08:40", "temp_c": 17, "rh_pct": 81},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["humidity_id"] == 7
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_temp == 17.0
        assert record.calc_avg_rh == 80.67
        assert record.round_no == 1

    def test_create_batching_morning_lock(self):
        """BATCHING morning [17/75,16/78,17/76] -> 16.67 / 76.33."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "humidity_id", 8)
        )
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "dept_id": 5,
                "round_no": 1,
                "spots": [
                    {"temp_c": 17, "rh_pct": 75},
                    {"temp_c": 16, "rh_pct": 78},
                    {"temp_c": 17, "rh_pct": 76},
                ],
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_temp == 16.67
        assert record.calc_avg_rh == 76.33

    # ----------------------------------------------------------- validation
    def test_create_zero_spots(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 1,
                "spots": [],
            },
        )
        assert response.status_code == 400
        assert "at least 1" in response.json()["detail"].lower()

    def test_create_too_many_spots(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 1,
                "spots": [{"temp_c": 17, "rh_pct": 80}] * 4,
            },
        )
        assert response.status_code == 400
        assert "3" in response.json()["detail"]

    def test_create_non_positive_temp(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 1,
                "spots": [{"temp_c": 0, "rh_pct": 80}],
            },
        )
        assert response.status_code == 400
        assert "temp_c" in response.json()["detail"].lower()

    def test_create_rh_zero(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 1,
                "spots": [{"temp_c": 17, "rh_pct": 0}],
            },
        )
        assert response.status_code == 400
        assert "rh_pct" in response.json()["detail"].lower()

    def test_create_rh_over_100(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 1,
                "spots": [{"temp_c": 17, "rh_pct": 101}],
            },
        )
        assert response.status_code == 400
        assert "rh_pct" in response.json()["detail"].lower()

    def test_create_bad_round_no(self):
        response = client.post(
            "/api/juteSQC/create_humidity",
            json={
                "co_id": 1,
                "report_date": "2026-06-28",
                "round_no": 4,
                "spots": [{"temp_c": 17, "rh_pct": 80}],
            },
        )
        assert response.status_code == 400
        assert "round_no" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_grouping(self):
        """Rows grouped by dept then round; spots parsed; round_label + avgs returned."""
        rows = [
            _mock_row({
                "humidity_id": 1,
                "dept_id": 5,
                "dept_desc": "BATCHING",
                "round_no": 1,
                "spots": '[{"spot_label": "A", "reading_time": "08:30", "temp_c": 17, "rh_pct": 81}]',
                "avg_temp": 17.0,
                "avg_rh": 81.0,
                "prepared_by": "QC1",
            }),
            _mock_row({
                "humidity_id": 2,
                "dept_id": 5,
                "dept_desc": "BATCHING",
                "round_no": 2,
                "spots": '[{"spot_label": "A", "reading_time": "13:00", "temp_c": 18, "rh_pct": 70}]',
                "avg_temp": 18.0,
                "avg_rh": 70.0,
                "prepared_by": "QC1",
            }),
            _mock_row({
                "humidity_id": 3,
                "dept_id": 9,
                "dept_desc": "SPINNING",
                "round_no": 1,
                "spots": '[{"spot_label": "A", "reading_time": "08:30", "temp_c": 20, "rh_pct": 65}]',
                "avg_temp": 20.0,
                "avg_rh": 65.0,
                "prepared_by": "QC2",
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/juteSQC/get_humidity_by_date?co_id=1&branch_id=2&report_date=2026-06-28"
        )
        assert response.status_code == 200
        depts = response.json()["data"]["departments"]
        assert len(depts) == 2  # BATCHING + SPINNING
        batching = depts[0]
        assert batching["dept_desc"] == "BATCHING"
        assert len(batching["rounds"]) == 2  # morning + noon
        first = batching["rounds"][0]
        assert first["round_no"] == 1
        assert first["round_label"] == "Morning"
        assert isinstance(first["spots"], list) and len(first["spots"]) == 1
        assert first["avg_temp"] == 17.0
        assert first["avg_rh"] == 81.0
        assert batching["rounds"][1]["round_label"] == "Noon"

    def test_by_date_missing_report_date(self):
        response = client.get("/api/juteSQC/get_humidity_by_date?co_id=1")
        assert response.status_code == 400
        assert "report_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_humidity_by_date?report_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "humidity_id": 1,
            "report_date": "2026-06-28",
            "branch_id": 2,
            "dept_id": 5,
            "dept_desc": "BATCHING",
            "round_no": 1,
            "avg_temp": 17.0,
            "avg_rh": 80.67,
            "prepared_by": "QC1",
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_humidity_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1
        assert body["data"][0]["avg_rh"] == 80.67

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_humidity_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"humidity_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_humidity",
            json={"humidity_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_humidity",
            json={"humidity_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
