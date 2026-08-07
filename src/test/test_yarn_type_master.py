"""
Tests for Yarn Type Master endpoints.
Tests for src/masters/yarnTypeMaster.py

Yarn types are stored in item_grp_mst with item_type_id=4.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    """Create a mock row with _mapping attribute."""
    row = MagicMock()
    row._mapping = mapping
    return row


class TestGetYarnTypeTable:
    """Tests for GET /api/yarnTypeMaster/get_yarn_type_table"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_paginated_data(self):
        """Should return paginated yarn type list."""
        rows = [
            _mock_row({"item_grp_id": 1, "item_grp_name": "Polyester", "item_grp_code": "PLY",
                        "co_id": 1, "active": "1", "updated_by": 1, "updated_date_time": None}),
            _mock_row({"item_grp_id": 2, "item_grp_name": "Cotton", "item_grp_code": "CTN",
                        "co_id": 1, "active": "1", "updated_by": 1, "updated_date_time": None}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/yarnTypeMaster/get_yarn_type_table?co_id=1&page=1&limit=10")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["data"]) == 2
        assert body["data"][0]["item_grp_name"] == "Polyester"

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnTypeMaster/get_yarn_type_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_search_filter(self):
        """Should work with search parameter."""
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get("/api/yarnTypeMaster/get_yarn_type_table?co_id=1&search=poly")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_pagination_limits_results(self):
        """Should respect page and limit parameters."""
        rows = [
            _mock_row({"item_grp_id": i, "item_grp_name": f"Type{i}", "item_grp_code": f"T{i}",
                        "co_id": 1, "active": "1", "updated_by": 1, "updated_date_time": None})
            for i in range(1, 6)
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/yarnTypeMaster/get_yarn_type_table?co_id=1&page=2&limit=2")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert len(body["data"]) == 2
        assert body["page"] == 2


class TestGetYarnTypeById:
    """Tests for GET /api/yarnTypeMaster/get_yarn_type_by_id/{yarn_type_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success(self):
        """Should return yarn type details."""
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({
            "item_grp_id": 1, "item_grp_name": "Polyester", "item_grp_code": "PLY",
            "co_id": 1, "active": "1", "updated_by": 1, "updated_date_time": None
        })

        response = client.get("/api/yarnTypeMaster/get_yarn_type_by_id/1?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"]["item_grp_code"] == "PLY"

    def test_not_found(self):
        """Should return 404 when yarn type doesn't exist."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/yarnTypeMaster/get_yarn_type_by_id/999?co_id=1")
        assert response.status_code == 404

    def test_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnTypeMaster/get_yarn_type_by_id/1")
        assert response.status_code == 400


class TestYarnTypeCreate:
    """Tests for POST /api/yarnTypeMaster/yarn_type_create"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_create_success(self):
        """Should create yarn type in item_grp_mst with item_type_id=4."""
        name_check = MagicMock()
        name_check.cnt = 0
        code_check = MagicMock()
        code_check.cnt = 0
        self._mock_session.execute.return_value.fetchone.side_effect = [name_check, code_check]

        def set_id(obj):
            obj.item_grp_id = 99
        self._mock_session.refresh.side_effect = set_id

        payload = {"co_id": "1", "item_grp_name": "New Yarn Type", "item_grp_code": "NYT"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["item_grp_id"] == 99
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

    def test_create_missing_name(self):
        """Should return 400 when item_grp_name is missing."""
        payload = {"co_id": "1", "item_grp_code": "NYT"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 400
        assert "name" in response.json()["detail"].lower()

    def test_create_missing_code(self):
        """Should return 400 when item_grp_code is missing."""
        payload = {"co_id": "1", "item_grp_name": "Some Type"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 400
        assert "code" in response.json()["detail"].lower()

    def test_create_duplicate_name(self):
        """Should return 400 when yarn type name already exists."""
        dup_name = MagicMock()
        dup_name.cnt = 1
        self._mock_session.execute.return_value.fetchone.return_value = dup_name

        payload = {"co_id": "1", "item_grp_name": "Existing", "item_grp_code": "UNIQ"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 400
        assert "name already exists" in response.json()["detail"].lower()

    def test_create_duplicate_code(self):
        """Should return 400 when item_grp_code already exists."""
        name_ok = MagicMock()
        name_ok.cnt = 0
        code_dup = MagicMock()
        code_dup.cnt = 1
        self._mock_session.execute.return_value.fetchone.side_effect = [name_ok, code_dup]

        payload = {"co_id": "1", "item_grp_name": "New Type", "item_grp_code": "EXISTING"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 400
        assert "code already exists" in response.json()["detail"].lower()

    def test_create_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        payload = {"item_grp_name": "Type", "item_grp_code": "T1"}
        response = client.post("/api/yarnTypeMaster/yarn_type_create", json=payload)

        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestYarnTypeEditSetup:
    """Tests for GET /api/yarnTypeMaster/yarn_type_edit_setup/{yarn_type_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success(self):
        """Should return yarn type details for editing."""
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({
            "item_grp_id": 1, "item_grp_name": "Polyester", "item_grp_code": "PLY",
            "co_id": 1, "active": "1", "updated_by": 1, "updated_date_time": None
        })

        response = client.get("/api/yarnTypeMaster/yarn_type_edit_setup/1?co_id=1")

        assert response.status_code == 200
        assert "yarn_type_details" in response.json()
        assert response.json()["yarn_type_details"]["item_grp_code"] == "PLY"

    def test_not_found(self):
        """Should return 404 when yarn type not found."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/yarnTypeMaster/yarn_type_edit_setup/999?co_id=1")
        assert response.status_code == 404


class TestYarnTypeEdit:
    """Tests for PUT /api/yarnTypeMaster/yarn_type_edit/{yarn_type_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_edit_success(self):
        """Should update an existing yarn type record."""
        existing = MagicMock()
        existing.item_grp_id = 1
        existing.item_grp_name = "Old Name"
        existing.item_grp_code = "OLD"
        existing.co_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        name_ok = MagicMock()
        name_ok.cnt = 0
        code_ok = MagicMock()
        code_ok.cnt = 0
        self._mock_session.execute.return_value.fetchone.side_effect = [name_ok, code_ok]

        payload = {"co_id": "1", "item_grp_name": "Updated Name", "item_grp_code": "UPD"}
        response = client.put("/api/yarnTypeMaster/yarn_type_edit/1", json=payload)

        assert response.status_code == 200
        assert "message" in response.json()
        self._mock_session.commit.assert_called_once()

    def test_edit_not_found(self):
        """Should return 404 when yarn type to edit doesn't exist."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        payload = {"co_id": "1", "item_grp_name": "X", "item_grp_code": "X"}
        response = client.put("/api/yarnTypeMaster/yarn_type_edit/999", json=payload)

        assert response.status_code == 404


class TestQueryFunctions:
    """Tests for SQL query helper functions."""

    def test_get_yarn_type_list_query_returns_text(self):
        from src.masters.yarnTypeMaster import get_yarn_type_list_query
        result = get_yarn_type_list_query()
        assert "item_grp_mst" in str(result)
        assert "item_type_id" in str(result)

    def test_get_yarn_type_list_with_search_query_has_like(self):
        from src.masters.yarnTypeMaster import get_yarn_type_list_with_search_query
        result = get_yarn_type_list_with_search_query()
        sql = str(result)
        assert "LIKE" in sql
        assert ":search" in sql

    def test_yarn_item_type_id_is_4(self):
        from src.masters.yarnTypeMaster import YARN_ITEM_TYPE_ID
        assert YARN_ITEM_TYPE_ID == 4
