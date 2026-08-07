"""Tests for HRMS Leave Type Master API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from sqlalchemy import text
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.hrms.leaveType import get_leave_type_list_query, get_leave_type_by_id_query

client = TestClient(app)

PREFIX = "/api/hrmsMasters"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    row.cnt = mapping.get("cnt", 0)
    return row


# ─── Query function tests ───────────────────────────────────────────


class TestLeaveTypeQueries:
    """Tests for leave type SQL query functions."""

    def test_get_leave_type_list_query_returns_text(self):
        result = get_leave_type_list_query()
        assert isinstance(result, type(text("")))

    def test_get_leave_type_list_query_has_binds(self):
        sql_str = str(get_leave_type_list_query())
        assert ":company_id" in sql_str
        assert ":search" in sql_str

    def test_get_leave_type_by_id_query_returns_text(self):
        result = get_leave_type_by_id_query()
        assert isinstance(result, type(text("")))

    def test_get_leave_type_by_id_query_has_bind(self):
        sql_str = str(get_leave_type_by_id_query())
        assert ":leave_type_id" in sql_str


# ─── GET /get_leave_type_table ──────────────────────────────────────


class TestGetLeaveTypeTable:
    """Tests for GET /get_leave_type_table."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id_returns_400(self):
        response = client.get(f"{PREFIX}/get_leave_type_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_success_returns_paginated(self):
        rows = [
            _mock_row({
                "leave_type_id": 1,
                "leave_type_code": "CL",
                "leave_type_description": "Casual Leave",
                "payable": "Y",
                "company_id": 1,
                "is_active": 1,
                "updated_by": 1,
                "updated_date_time": None,
                "Leave_hours": None,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{PREFIX}/get_leave_type_table?co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["data"][0]["leave_type_code"] == "CL"

    def test_empty_result(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(f"{PREFIX}/get_leave_type_table?co_id=1")
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["data"] == []

    def test_pagination_limits(self):
        rows = [
            _mock_row({"leave_type_id": i, "leave_type_code": f"LT{i}", "leave_type_description": f"Desc {i}",
                        "payable": "N", "company_id": 1, "is_active": 1,
                        "updated_by": 1, "updated_date_time": None, "Leave_hours": None})
            for i in range(5)
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{PREFIX}/get_leave_type_table?co_id=1&page=1&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["data"]) == 2


# ─── GET /get_leave_type_by_id ──────────────────────────────────────


class TestGetLeaveTypeById:
    """Tests for GET /get_leave_type_by_id/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_not_found_returns_404(self):
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get(f"{PREFIX}/get_leave_type_by_id/999")
        assert response.status_code == 404

    def test_found_returns_data(self):
        row = _mock_row({
            "leave_type_id": 1,
            "leave_type_code": "SL",
            "leave_type_description": "Sick Leave",
            "payable": "N",
            "company_id": 1,
            "is_active": 1,
            "updated_by": 1,
            "updated_date_time": None,
            "Leave_hours": None,
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get(f"{PREFIX}/get_leave_type_by_id/1")
        assert response.status_code == 200
        assert response.json()["data"]["leave_type_code"] == "SL"


# ─── POST /leave_type_create ────────────────────────────────────────


class TestLeaveTypeCreate:
    """Tests for POST /leave_type_create."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id_returns_400(self):
        response = client.post(f"{PREFIX}/leave_type_create", json={
            "leave_type_code": "CL",
            "leave_type_description": "Casual Leave",
        })
        assert response.status_code == 400

    def test_missing_code_returns_400(self):
        response = client.post(f"{PREFIX}/leave_type_create", json={
            "co_id": 1,
            "leave_type_description": "Casual Leave",
        })
        assert response.status_code == 400

    def test_missing_desc_returns_400(self):
        response = client.post(f"{PREFIX}/leave_type_create", json={
            "co_id": 1,
            "leave_type_code": "CL",
        })
        assert response.status_code == 400

    def test_duplicate_code_returns_400(self):
        dup_row = _mock_row({"cnt": 1})
        self._mock_session.execute.return_value.fetchone.return_value = dup_row

        response = client.post(f"{PREFIX}/leave_type_create", json={
            "co_id": 1,
            "leave_type_code": "CL",
            "leave_type_description": "Casual Leave",
            "payable": "Y",
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()


# ─── PUT /leave_type_edit ────────────────────────────────────────────


class TestLeaveTypeEdit:
    """Tests for PUT /leave_type_edit/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_code_returns_400(self):
        response = client.put(f"{PREFIX}/leave_type_edit/1", json={
            "co_id": 1,
            "leave_type_description": "Some desc",
        })
        assert response.status_code == 400

    def test_not_found_returns_404(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put(f"{PREFIX}/leave_type_edit/999", json={
            "co_id": 1,
            "leave_type_code": "CL",
            "leave_type_description": "Casual Leave",
        })
        assert response.status_code == 404

    def test_duplicate_on_edit_returns_400(self):
        existing = MagicMock()
        existing.company_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        dup_row = _mock_row({"cnt": 1})
        self._mock_session.execute.return_value.fetchone.return_value = dup_row

        response = client.put(f"{PREFIX}/leave_type_edit/1", json={
            "co_id": 1,
            "leave_type_code": "EXISTING",
            "leave_type_description": "Existing Leave",
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
