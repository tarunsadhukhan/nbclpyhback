"""
Tests for R-08-22 Stitch SQC endpoints.
Tests for src/juteSQC/stitch.py
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.stitch import _flag

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ---------------------------------------------------------------------------
# Math lock — the flag rule is EXACT equality (not rounded): OK only when avg == std,
# else LOW (avg < std) or HIGH (avg > std). A stitch QC must surface any drift off the
# 9/dm standard, so 9.4 is HIGH (not absorbed as OK). Matches the FE rule exactly so the
# server and client never disagree on the flag.
# ---------------------------------------------------------------------------
def test_flag_rule_math_lock():
    # [9,9,9,9,9] std 9 -> avg 9.0 -> OK
    assert _flag(9.0, 9.0) == "OK"
    # [8,8,8,8,8] std 9 -> avg 8.0 -> LOW
    assert _flag(8.0, 9.0) == "LOW"
    # [9,10,9,10,9] std 9 -> avg 9.4 -> HIGH (any value above std)
    assert _flag(9.4, 9.0) == "HIGH"
    assert _flag(10.0, 9.0) == "HIGH"
    assert _flag(None, 9.0) is None


class TestStitchEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        machine_row = _mock_row(
            {"machine_id": 5, "machine_name": "HEMMING 1", "mech_code": "H1",
             "dept_id": 3, "dept_name": "Finishing", "branch_id": 1}
        )
        self._mock_session.execute.return_value.fetchall.return_value = [machine_row]

        response = client.get(
            "/api/juteSQC/stitch_create_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" in data
        assert data["readings_count"] == 5
        assert data["default_std_stitch"] == 9.0
        assert len(data["machines"]) == 1
        assert data["machines"][0]["machine_name"] == "HEMMING 1"
        assert data["machines"][0]["mech_code"] == "H1"

    def test_create_setup_dedup_machines(self):
        dup = _mock_row(
            {"machine_id": 5, "machine_name": "HEMMING 1", "mech_code": "H1",
             "dept_id": 3, "dept_name": "Finishing", "branch_id": 1}
        )
        self._mock_session.execute.return_value.fetchall.return_value = [dup, dup]
        response = client.get(
            "/api/juteSQC/stitch_create_setup?co_id=1&branch_id=1"
        )
        assert response.status_code == 200
        assert len(response.json()["data"]["machines"]) == 1

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/stitch_create_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_create_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/stitch_create_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "stitch_id", 7)
        )

        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "std_stitch": 9,
                "readings": [9, 9, 9, 9, 9],
                "inspector_name": "QC John",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Stitch QC log created successfully"
        assert body["stitch_id"] == 7
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg == 9.0
        assert record.std_stitch == 9
        assert record.inspector_name == "QC John"

    def test_create_std_defaults_when_absent(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "stitch_id", 8)
        )
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "readings": [9, 10, 9, 10, 9],
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.std_stitch == 9.0          # default
        assert record.calc_avg == 9.4            # mean of [9,10,9,10,9]

    def test_create_missing_co_id(self):
        # co_id is a required body field -> 422 from pydantic (not a 400 guard)
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "readings": [9, 9, 9, 9, 9],
            },
        )
        assert response.status_code == 422

    def test_create_wrong_reading_count(self):
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "readings": [9, 9, 9],
            },
        )
        assert response.status_code == 400
        assert "5" in response.json()["detail"]

    def test_create_non_positive_reading(self):
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "readings": [9, 0, 9, 9, 9],
            },
        )
        assert response.status_code == 400
        assert "positive" in response.json()["detail"].lower()

    def test_create_non_positive_std(self):
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "mc_id": 5,
                "std_stitch": 0,
                "readings": [9, 9, 9, 9, 9],
            },
        )
        assert response.status_code == 400
        assert "std_stitch" in response.json()["detail"].lower()

    def test_create_missing_machine(self):
        # Regression: a row with no sewing machine must be rejected (not persisted).
        response = client.post(
            "/api/juteSQC/create_stitch",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "readings": [9, 9, 9, 9, 9],
            },
        )
        assert response.status_code == 400
        assert "machine" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_flag(self):
        # Three machines locking the OK / LOW / HIGH branches of the flag rule.
        rows = [
            _mock_row({
                "stitch_id": 1, "mc_id": 5, "machine_name": "HEMMING 1",
                "mech_code": "H1", "std_stitch": 9.0,
                "readings": "[9, 9, 9, 9, 9]", "calc_avg": 9.0,
                "inspector_name": "A",
            }),
            _mock_row({
                "stitch_id": 2, "mc_id": 6, "machine_name": "HEMMING 2",
                "mech_code": "H2", "std_stitch": 9.0,
                "readings": "[8, 8, 8, 8, 8]", "calc_avg": 8.0,
                "inspector_name": "B",
            }),
            _mock_row({
                "stitch_id": 3, "mc_id": 7, "machine_name": "HEMMING 3",
                "mech_code": "H3", "std_stitch": 9.0,
                "readings": "[10, 10, 10, 10, 10]", "calc_avg": 10.0,
                "inspector_name": "C",
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/juteSQC/get_stitch_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["rows"]) == 3

        first = data["rows"][0]
        assert isinstance(first["readings"], list) and len(first["readings"]) == 5
        assert first["avg"] == 9.0
        assert first["flag"] == "OK"
        assert data["rows"][1]["flag"] == "LOW"    # 8 < 9
        assert data["rows"][2]["flag"] == "HIGH"   # round(10) > round(9)

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_stitch_by_date?co_id=1&branch_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_stitch_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "stitch_id": 1, "entry_date": "2026-06-28", "mc_id": 5,
            "machine_name": "HEMMING 1", "mech_code": "H1",
            "std_stitch": 9.0, "calc_avg": 9.0, "inspector_name": "A",
            "branch_id": 1, "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_stitch_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1
        # The history (trend) row must carry the derived avg + flag (calc_avg -> avg,
        # flag from avg vs std) so the FE trend table renders them, matching by_date.
        row = body["data"][0]
        assert row["avg"] == 9.0
        assert row["flag"] == "OK"

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_stitch_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"stitch_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_stitch",
            json={"stitch_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_stitch",
            json={"stitch_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
