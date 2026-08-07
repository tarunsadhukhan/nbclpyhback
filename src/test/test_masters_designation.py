"""
Tests for Designation Master API endpoints.
Tests for src/masters/designation.py
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

DESIGNATION_PREFIX = "/api/designationMaster"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    row.cnt = mapping.get("cnt", 0)
    return row


class TestGetDesignationTable:
    """Tests for GET /get_designation_table."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_paginated(self):
        rows = [
            _mock_row({"designation_id": 1, "desig": "Manager", "sub_dept_name": "HR", "branch_name": "HQ"}),
            _mock_row({"designation_id": 2, "desig": "Engineer", "sub_dept_name": "IT", "branch_name": "HQ"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{DESIGNATION_PREFIX}/get_designation_table?page=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["data"]) == 2
        assert data["data"][0]["desig"] == "Manager"

    def test_pagination_limits(self):
        rows = [_mock_row({"designation_id": i, "desig": f"Desig{i}"}) for i in range(5)]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{DESIGNATION_PREFIX}/get_designation_table?page=1&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["data"]) == 2

    def test_empty_result(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(f"{DESIGNATION_PREFIX}/get_designation_table")
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["data"] == []


class TestGetDesignationById:
    """Tests for GET /get_designation_by_id/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.get(f"{DESIGNATION_PREFIX}/get_designation_by_id/999")
        assert response.status_code == 404

    def test_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({
            "designation_id": 1, "desig": "Manager", "sub_dept_id": 10,
            "branch_id": 5,
        })

        response = client.get(f"{DESIGNATION_PREFIX}/get_designation_by_id/1")
        assert response.status_code == 200
        assert response.json()["data"]["desig"] == "Manager"


class TestDesignationCreateSetup:
    """Tests for GET /designation_create_setup."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id(self):
        response = client.get(f"{DESIGNATION_PREFIX}/designation_create_setup")
        assert response.status_code == 400

    def test_success(self):
        sub_dept_rows = [_mock_row({"sub_dept_id": 1, "sub_dept_desc": "HR", "sub_dept_display": "HR (Human Resources)"})]
        branch_rows = [_mock_row({"branch_id": 1, "branch_name": "HQ"})]
        machine_type_rows = [_mock_row({"machine_type_id": 3, "machine_type_name": "Spreader"})]
        self._mock_session.execute.return_value.fetchall.side_effect = [sub_dept_rows, branch_rows, machine_type_rows]

        response = client.get(f"{DESIGNATION_PREFIX}/designation_create_setup?co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "sub_departments" in data
        assert "branches" in data
        assert "machine_types" in data
        assert len(data["sub_departments"]) == 1
        assert data["sub_departments"][0]["sub_dept_desc"] == "HR"
        assert len(data["machine_types"]) == 1
        assert data["machine_types"][0]["machine_type_name"] == "Spreader"


class TestDesignationCreate:
    """Tests for POST /designation_create."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_desig(self):
        response = client.post(f"{DESIGNATION_PREFIX}/designation_create", json={"sub_dept_id": 10})
        assert response.status_code == 400
        assert "desig" in response.json()["detail"].lower()

    def test_missing_sub_dept_id(self):
        response = client.post(f"{DESIGNATION_PREFIX}/designation_create", json={"desig": "Test"})
        assert response.status_code == 400
        assert "sub department" in response.json()["detail"].lower()

    def test_duplicate_rejected(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 1})

        response = client.post(f"{DESIGNATION_PREFIX}/designation_create", json={
            "desig": "Manager", "sub_dept_id": 10,
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})

        response = client.post(f"{DESIGNATION_PREFIX}/designation_create", json={
            "desig": "Manager", "sub_dept_id": 10,
            "branch_id": 5, "time_piece": "T", "direct_indirect": "D",
        })
        assert response.status_code == 200
        assert "message" in response.json()
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()


class TestDesignationEdit:
    """Tests for PUT /designation_edit/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_not_found(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put(f"{DESIGNATION_PREFIX}/designation_edit/999", json={
            "desig": "Test", "sub_dept_id": 10,
        })
        assert response.status_code == 404

    def test_success(self):
        existing = MagicMock()
        existing.designation_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})

        response = client.put(f"{DESIGNATION_PREFIX}/designation_edit/1", json={
            "desig": "Updated Name", "sub_dept_id": 10,
        })
        assert response.status_code == 200
        assert response.json()["designation_id"] == 1
        self._mock_session.commit.assert_called_once()

    def test_duplicate_rejected_on_edit(self):
        existing = MagicMock()
        existing.designation_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 1})

        response = client.put(f"{DESIGNATION_PREFIX}/designation_edit/1", json={
            "desig": "Manager", "sub_dept_id": 10,
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
