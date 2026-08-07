"""
Tests for R-08-18 Beam MR% QC endpoints.
Tests for src/juteSQC/beam_mr.py
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


class TestBeamMrEndpoints:
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
            {"machine_id": 5, "machine_name": "BEAM 1", "mech_code": "B1",
             "dept_id": 3, "dept_name": "Beaming", "branch_id": 1}
        )
        cloth_row = _mock_row({"item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz"})
        spell_row = _mock_row(
            {"spell_id": 1, "spell_code": "A1", "spell_name": "Morning",
             "working_hours": 8, "starting_time": "06:00", "is_overnight": 0, "shift_id": 1}
        )

        # Order: machines, cloth items, spells
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [machine_row],
            [cloth_row],
            [spell_row],
        ]

        response = client.get(
            "/api/juteSQC/get_beam_mr_create_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "spells" in data
        assert "machines" in data
        assert "cloth_qualities" in data
        assert data["readings_per_set"] == 5
        assert data["std_mr_by_group"]["HESSIAN"] == 16.0
        assert data["std_mr_by_group"]["SACKING"] == 20.0
        assert len(data["machines"]) == 1
        assert data["machines"][0]["machine_name"] == "BEAM 1"

    def test_create_setup_dedup_machines(self):
        dup = _mock_row(
            {"machine_id": 5, "machine_name": "BEAM 1", "mech_code": "B1",
             "dept_id": 3, "dept_name": "Beaming", "branch_id": 1}
        )
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [dup, dup],   # two rows, same machine_id
            [],
            [],
        ]
        response = client.get(
            "/api/juteSQC/get_beam_mr_create_setup?co_id=1&branch_id=1"
        )
        assert response.status_code == 200
        assert len(response.json()["data"]["machines"]) == 1

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_beam_mr_create_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_create_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/get_beam_mr_create_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "beam_mr_id", 7)
        )

        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "spell_id": 1,
                "item_id": 10,
                "mc_id": 5,
                "readings": [16.2, 15.8, 16.5, 16.0, 15.9],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Beam MR% QC log created successfully"
        assert body["beam_mr_id"] == 7
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()
        # avg of the 5 readings, rounded to 2dp; std snapshot from group default
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_mr == round(sum([16.2, 15.8, 16.5, 16.0, 15.9]) / 5, 2)
        assert record.std_mr_pct == 16.0

    def test_create_std_override(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "beam_mr_id", 8)
        )
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "SACKING",
                "item_id": 10,
                "mc_id": 5,
                "readings": [21.0, 20.0, 19.5, 20.5, 20.0],
                "std_mr_pct": 18.5,
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.std_mr_pct == 18.5

    def test_create_variable_reading_count(self):
        # Readings are no longer fixed at 5 — any count >= 1 is accepted and the
        # average is taken over however many were supplied.
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "beam_mr_id", 9)
        )
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "item_id": 10,
                "mc_id": 5,
                "readings": [16.0, 17.0, 18.0],
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_mr == round((16.0 + 17.0 + 18.0) / 3, 2)

    def test_create_empty_readings(self):
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "item_id": 10,
                "mc_id": 5,
                "readings": [],
            },
        )
        assert response.status_code == 400
        assert "at least one" in response.json()["detail"].lower()

    def test_create_non_positive_reading(self):
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "readings": [16.0, 0, 16.0, 16.0, 16.0],
            },
        )
        assert response.status_code == 400
        assert "positive" in response.json()["detail"].lower()

    def test_create_bad_quality_group(self):
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "NYLON",
                "readings": [16.0, 16.0, 16.0, 16.0, 16.0],
            },
        )
        assert response.status_code == 400
        assert "quality_group" in response.json()["detail"].lower()

    def test_create_missing_machine(self):
        # Regression: a row with no beam machine must be rejected (not persisted).
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "item_id": 10,
                "readings": [16.0, 16.0, 16.0, 16.0, 16.0],
            },
        )
        assert response.status_code == 400
        assert "machine" in response.json()["detail"].lower()

    def test_create_missing_item(self):
        # Regression: a row with no cloth quality must be rejected (not persisted).
        response = client.post(
            "/api/juteSQC/create_beam_mr",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "quality_group": "HESSIAN",
                "mc_id": 5,
                "readings": [16.0, 16.0, 16.0, 16.0, 16.0],
            },
        )
        assert response.status_code == 400
        assert "cloth quality" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_grouping_and_avg(self):
        # Two HESSIAN machines (avg 16, 18 -> overall 17) + one SACKING (avg 20).
        rows = [
            _mock_row({
                "beam_mr_id": 1, "quality_group": "HESSIAN", "mc_id": 5,
                "machine_name": "BEAM 1", "mech_code": "B1", "item_id": 10,
                "item_name": "H10", "spell_id": 1, "spell_code": "A1",
                "readings": "[16.0, 16.0, 16.0, 16.0, 16.0]",
                "calc_avg_mr": 16.0, "std_mr_pct": 16.0,
            }),
            _mock_row({
                "beam_mr_id": 2, "quality_group": "HESSIAN", "mc_id": 6,
                "machine_name": "BEAM 2", "mech_code": "B2", "item_id": 10,
                "item_name": "H10", "spell_id": 1, "spell_code": "A1",
                "readings": "[18.0, 18.0, 18.0, 18.0, 18.0]",
                "calc_avg_mr": 18.0, "std_mr_pct": 16.0,
            }),
            _mock_row({
                "beam_mr_id": 3, "quality_group": "SACKING", "mc_id": 7,
                "machine_name": "BEAM 3", "mech_code": "B3", "item_id": 11,
                "item_name": "S5", "spell_id": 1, "spell_code": "A1",
                "readings": "[20.0, 20.0, 20.0, 20.0, 20.0]",
                "calc_avg_mr": 20.0, "std_mr_pct": 20.0,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/juteSQC/get_beam_mr_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["rows"]) == 3
        # readings parsed to list; deviation computed
        first = data["rows"][0]
        assert isinstance(first["readings"], list) and len(first["readings"]) == 5
        assert first["avg_mr"] == 16.0
        assert first["deviation"] == 0.0
        assert data["rows"][1]["deviation"] == 2.0  # 18 - 16

        summaries = {s["quality_group"]: s for s in data["group_summaries"]}
        assert summaries["HESSIAN"]["overall_avg_mr"] == 17.0  # mean(16, 18)
        assert summaries["HESSIAN"]["machine_count"] == 2
        assert summaries["SACKING"]["overall_avg_mr"] == 20.0
        assert summaries["SACKING"]["machine_count"] == 1

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_beam_mr_by_date?co_id=1&branch_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_beam_mr_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "beam_mr_id": 1, "entry_date": "2026-06-28", "quality_group": "HESSIAN",
            "spell_id": 1, "spell_code": "A1", "mc_id": 5, "machine_name": "BEAM 1",
            "mech_code": "B1", "item_id": 10, "item_name": "H10",
            "calc_avg_mr": 16.0, "std_mr_pct": 16.0, "branch_id": 1,
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_beam_mr_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_beam_mr_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"beam_mr_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_beam_mr",
            json={"beam_mr_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_beam_mr",
            json={"beam_mr_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
