"""
Tests for Worker Category Master API endpoints.
Tests for src/masters/category.py
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

CATEGORY_PREFIX = "/api/categoryMaster"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    row.cnt = mapping.get("cnt", 0)
    return row


class TestGetCategoryTable:
    """Tests for GET /get_category_table."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_paginated(self):
        rows = [
            _mock_row({"cata_id": 1, "cata_code": "CAT01", "cata_desc": "Skilled", "branch_name": "Main"}),
            _mock_row({"cata_id": 2, "cata_code": "CAT02", "cata_desc": "Unskilled", "branch_name": "Factory"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{CATEGORY_PREFIX}/get_category_table?page=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["data"]) == 2
        assert data["data"][0]["cata_code"] == "CAT01"

    def test_pagination_limits(self):
        rows = [_mock_row({"cata_id": i, "cata_code": f"C{i}"}) for i in range(5)]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(f"{CATEGORY_PREFIX}/get_category_table?page=1&limit=2")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert len(data["data"]) == 2

    def test_empty_result(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(f"{CATEGORY_PREFIX}/get_category_table")
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["data"] == []

    def test_search_param_passed(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(f"{CATEGORY_PREFIX}/get_category_table?search=skilled")
        assert response.status_code == 200
        call_args = self._mock_session.execute.call_args
        params = call_args[0][1]
        assert params["search"] == "%skilled%"


class TestGetCategoryById:
    """Tests for GET /get_category_by_id/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.get(f"{CATEGORY_PREFIX}/get_category_by_id/999")
        assert response.status_code == 404

    def test_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({
            "cata_id": 1, "cata_code": "CAT01", "cata_desc": "Skilled",
            "branch_id": 5, "branch_name": "Main",
        })

        response = client.get(f"{CATEGORY_PREFIX}/get_category_by_id/1")
        assert response.status_code == 200
        assert response.json()["data"]["cata_code"] == "CAT01"


class TestCategoryCreateSetup:
    """Tests for GET /category_create_setup."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id(self):
        response = client.get(f"{CATEGORY_PREFIX}/category_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_success(self):
        branches = [
            _mock_row({"branch_id": 10, "branch_name": "Main"}),
            _mock_row({"branch_id": 20, "branch_name": "Factory"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = branches

        response = client.get(f"{CATEGORY_PREFIX}/category_create_setup?co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "branches" in data
        assert len(data["branches"]) == 2


class TestCategoryCreate:
    """Tests for POST /category_create."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_cata_code(self):
        response = client.post(f"{CATEGORY_PREFIX}/category_create", json={
            "cata_desc": "Skilled",
        })
        assert response.status_code == 400
        assert "cata_code" in response.json()["detail"].lower()

    def test_missing_cata_desc(self):
        response = client.post(f"{CATEGORY_PREFIX}/category_create", json={
            "cata_code": "CAT01",
        })
        assert response.status_code == 400
        assert "cata_desc" in response.json()["detail"].lower()

    def test_duplicate_code(self):
        dup_row = MagicMock()
        dup_row._mapping = {"cnt": 1}
        dup_row.cnt = 1
        self._mock_session.execute.return_value.fetchone.return_value = dup_row

        response = client.post(f"{CATEGORY_PREFIX}/category_create", json={
            "cata_code": "CAT01",
            "cata_desc": "Skilled",
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_success(self):
        no_dup = MagicMock()
        no_dup._mapping = {"cnt": 0}
        no_dup.cnt = 0
        self._mock_session.execute.return_value.fetchone.return_value = no_dup

        mock_cat = MagicMock()
        mock_cat.cata_id = 99
        self._mock_session.add = MagicMock()
        self._mock_session.commit = MagicMock()
        self._mock_session.refresh = MagicMock(side_effect=lambda x: setattr(x, "cata_id", 99))

        response = client.post(f"{CATEGORY_PREFIX}/category_create", json={
            "cata_code": "CAT01",
            "cata_desc": "Skilled",
            "branch_id": "10",
        })
        assert response.status_code == 200
        assert "cata_id" in response.json()


class TestCategoryEdit:
    """Tests for PUT /category_edit/{id}."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_cata_code(self):
        response = client.put(f"{CATEGORY_PREFIX}/category_edit/1", json={
            "cata_desc": "Updated",
        })
        assert response.status_code == 400

    def test_not_found(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put(f"{CATEGORY_PREFIX}/category_edit/999", json={
            "cata_code": "CAT01",
            "cata_desc": "Updated",
        })
        assert response.status_code == 404

    def test_duplicate_code_on_edit(self):
        existing = MagicMock()
        existing.cata_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        dup_row = MagicMock()
        dup_row._mapping = {"cnt": 1}
        dup_row.cnt = 1
        self._mock_session.execute.return_value.fetchone.return_value = dup_row

        response = client.put(f"{CATEGORY_PREFIX}/category_edit/1", json={
            "cata_code": "CAT02",
            "cata_desc": "Updated",
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_success(self):
        existing = MagicMock()
        existing.cata_id = 1
        existing.cata_code = "CAT01"
        existing.cata_desc = "Skilled"
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        no_dup = MagicMock()
        no_dup._mapping = {"cnt": 0}
        no_dup.cnt = 0
        self._mock_session.execute.return_value.fetchone.return_value = no_dup

        response = client.put(f"{CATEGORY_PREFIX}/category_edit/1", json={
            "cata_code": "CAT01",
            "cata_desc": "Skilled Updated",
        })
        assert response.status_code == 200
        assert response.json()["cata_id"] == 1
