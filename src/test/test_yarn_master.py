"""
Tests for Yarn Master endpoints.
Tests for src/masters/yarnMaster.py

Yarn masters are stored in jute_yarn_mst with corresponding item_mst records.
On create, item_mst is created first, then jute_yarn_mst references it via item_id.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch, PropertyMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    """Create a mock row with _mapping attribute."""
    row = MagicMock()
    row._mapping = mapping
    return row


# ============================================================================
# GET /api/yarnMaster/get_yarn_table
# ============================================================================

class TestGetYarnTable:
    """Tests for GET /api/yarnMaster/get_yarn_table"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_paginated_data(self):
        """Should return paginated yarn list with item details."""
        rows = [
            _mock_row({
                "jute_yarn_id": 1, "item_id": 100, "jute_yarn_name": "10-SKWP-Gold",
                "item_code": "10-SKWP-Gold", "jute_yarn_count": 10.0, "std_mr_pct": 13.75,
                "item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP",
                "jute_yarn_remarks": "Gold", "co_id": 1,
                "updated_by": 1, "updated_date_time": None,
            }),
            _mock_row({
                "jute_yarn_id": 2, "item_id": 101, "jute_yarn_name": "12-HSWT",
                "item_code": "12-HSWT", "jute_yarn_count": 12.0, "std_mr_pct": None,
                "item_grp_id": 1672, "item_grp_name": "HSWT", "item_grp_code": "HSWT",
                "jute_yarn_remarks": None, "co_id": 1,
                "updated_by": 1, "updated_date_time": None,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/yarnMaster/get_yarn_table?co_id=1&page=1&limit=10")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["data"]) == 2
        assert body["data"][0]["jute_yarn_name"] == "10-SKWP-Gold"
        assert body["data"][0]["item_id"] == 100
        assert body["data"][0]["item_code"] == "10-SKWP-Gold"
        assert body["data"][0]["std_mr_pct"] == 13.75

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnMaster/get_yarn_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_search_filter(self):
        """Should work with search parameter."""
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get("/api/yarnMaster/get_yarn_table?co_id=1&search=SKWP")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_pagination_limits_results(self):
        """Should respect page and limit parameters."""
        rows = [
            _mock_row({
                "jute_yarn_id": i, "item_id": 100 + i, "jute_yarn_name": f"Yarn{i}",
                "item_code": f"Yarn{i}", "jute_yarn_count": float(i),
                "item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP",
                "jute_yarn_remarks": None, "co_id": 1,
                "updated_by": 1, "updated_date_time": None,
            })
            for i in range(1, 6)
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/yarnMaster/get_yarn_table?co_id=1&page=2&limit=2")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert len(body["data"]) == 2
        assert body["page"] == 2


# ============================================================================
# GET /api/yarnMaster/get_yarn_by_id/{yarn_id}
# ============================================================================

class TestGetYarnById:
    """Tests for GET /api/yarnMaster/get_yarn_by_id/{yarn_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_yarn_with_item_details(self):
        """Should return yarn record with item_id and item_code."""
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({
            "jute_yarn_id": 1, "item_id": 100, "jute_yarn_name": "10-SKWP-Gold",
            "item_code": "10-SKWP-Gold", "jute_yarn_count": 10.0,
            "item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP",
            "jute_yarn_remarks": "Gold", "co_id": 1,
            "updated_by": 1, "updated_date_time": None,
        })

        response = client.get("/api/yarnMaster/get_yarn_by_id/1?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["jute_yarn_id"] == 1
        assert data["item_id"] == 100
        assert data["item_code"] == "10-SKWP-Gold"

    def test_not_found_returns_404(self):
        """Should return 404 when yarn record doesn't exist."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/yarnMaster/get_yarn_by_id/999?co_id=1")

        assert response.status_code == 404

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnMaster/get_yarn_by_id/1")
        assert response.status_code == 400


# ============================================================================
# GET /api/yarnMaster/yarn_create_setup
# ============================================================================

class TestYarnCreateSetup:
    """Tests for GET /api/yarnMaster/yarn_create_setup"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_yarn_types(self):
        """Should return yarn types for dropdown."""
        rows = [
            _mock_row({"item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP"}),
            _mock_row({"item_grp_id": 1672, "item_grp_name": "HSWT", "item_grp_code": "HSWT"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/yarnMaster/yarn_create_setup?co_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "yarn_types" in body
        assert len(body["yarn_types"]) == 2
        assert body["yarn_types"][0]["item_grp_name"] == "SKWP"

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/yarnMaster/yarn_create_setup")
        assert response.status_code == 400


# ============================================================================
# GET /api/yarnMaster/yarn_edit_setup/{yarn_id}
# ============================================================================

class TestYarnEditSetup:
    """Tests for GET /api/yarnMaster/yarn_edit_setup/{yarn_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_details_and_types(self):
        """Should return yarn details with item info and yarn types."""
        # First call = yarn details, second call = yarn types
        detail_row = _mock_row({
            "jute_yarn_id": 1, "item_id": 100, "jute_yarn_name": "10-SKWP-Gold",
            "item_code": "10-SKWP-Gold", "jute_yarn_count": 10.0,
            "item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP",
            "jute_yarn_remarks": "Gold", "co_id": 1,
            "updated_by": 1, "updated_date_time": None,
        })
        type_rows = [
            _mock_row({"item_grp_id": 1671, "item_grp_name": "SKWP", "item_grp_code": "SKWP"}),
        ]

        # Mock: first execute -> fetchone (details), second execute -> fetchall (types)
        mock_exec_1 = MagicMock()
        mock_exec_1.fetchone.return_value = detail_row
        mock_exec_2 = MagicMock()
        mock_exec_2.fetchall.return_value = type_rows
        self._mock_session.execute.side_effect = [mock_exec_1, mock_exec_2]

        response = client.get("/api/yarnMaster/yarn_edit_setup/1?co_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "yarn_details" in body
        assert "yarn_types" in body
        assert body["yarn_details"]["item_id"] == 100
        assert body["yarn_details"]["jute_yarn_name"] == "10-SKWP-Gold"

    def test_not_found_returns_404(self):
        """Should return 404 when yarn record doesn't exist."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/yarnMaster/yarn_edit_setup/999?co_id=1")

        assert response.status_code == 404


# ============================================================================
# POST /api/yarnMaster/yarn_create
# ============================================================================

class TestYarnCreate:
    """Tests for POST /api/yarnMaster/yarn_create"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        # uom_mst lookup for the tenant's KG unit (resolved at runtime, not hardcoded)
        self._mock_session.execute.return_value.fetchone.return_value = (163,)
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    @patch("src.masters.yarnMaster._resolve_yarn_uom_id")
    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_success_creates_item_and_yarn(self, mock_uniqueness, mock_uom):
        """Should create item_mst first, then jute_yarn_mst with item_id FK."""
        mock_uniqueness.return_value = None  # no conflicts
        mock_uom.return_value = 163  # tenant's KG uom

        # Mock db.add to capture the objects being added
        added_objects = []
        def track_add(obj):
            added_objects.append(obj)
        self._mock_session.add.side_effect = track_add

        # Mock flush to set item_id on the ItemMst object
        def mock_flush():
            for obj in added_objects:
                if hasattr(obj, 'item_id') and not hasattr(obj, 'jute_yarn_id'):
                    # This is ItemMst — set the auto-generated id
                    obj.item_id = 999
        self._mock_session.flush.side_effect = mock_flush

        # Mock refresh to set jute_yarn_id
        def mock_refresh(obj):
            if hasattr(obj, 'jute_yarn_id'):
                obj.jute_yarn_id = 42
        self._mock_session.refresh.side_effect = mock_refresh

        payload = {
            "jute_yarn_name": "10-SKWP-Gold",
            "jute_yarn_count": 10,
            "std_mr_pct": 13.75,
            "item_grp_id": 1671,
            "jute_yarn_remarks": "Gold quality",
            "co_id": "1",
        }

        response = client.post("/api/yarnMaster/yarn_create", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Yarn master created successfully"
        assert body["jute_yarn_id"] == 42
        assert body["item_id"] == 999

        # Verify both objects were added
        assert len(added_objects) == 2
        # First should be ItemMst
        item_obj = added_objects[0]
        assert item_obj.item_name == "10-SKWP-Gold"
        assert item_obj.item_code == "10-SKWP-Gold"
        assert item_obj.item_grp_id == 1671
        assert item_obj.hsn_code == "5304"
        assert item_obj.uom_id == 163
        assert item_obj.tax_percentage == 5.0
        # Second should be JuteYarnMst
        yarn_obj = added_objects[1]
        assert yarn_obj.jute_yarn_name == "10-SKWP-Gold"
        assert yarn_obj.item_id == 999
        assert yarn_obj.co_id == 1
        assert yarn_obj.std_mr_pct == 13.75

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        payload = {"jute_yarn_name": "Test"}
        response = client.post("/api/yarnMaster/yarn_create", json=payload)
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_yarn_name_returns_400(self):
        """Should return 400 when yarn name is missing."""
        payload = {"co_id": "1"}
        response = client.post("/api/yarnMaster/yarn_create", json=payload)
        assert response.status_code == 400
        assert "yarn name" in response.json()["detail"].lower()

    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_duplicate_name_returns_409(self, mock_uniqueness):
        """Should return 409 when item name already exists."""
        mock_uniqueness.side_effect = HTTPException(
            status_code=409, detail="Item with name '10-SKWP-Gold' already exists"
        )

        payload = {
            "jute_yarn_name": "10-SKWP-Gold",
            "co_id": "1",
            "item_grp_id": 1671,
        }

        response = client.post("/api/yarnMaster/yarn_create", json=payload)
        assert response.status_code == 409

    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_create_without_optional_fields(self, mock_uniqueness):
        """Should work with only required fields (name and co_id)."""
        mock_uniqueness.return_value = None

        added_objects = []
        self._mock_session.add.side_effect = lambda obj: added_objects.append(obj)
        def mock_flush():
            for obj in added_objects:
                if hasattr(obj, 'item_id') and not hasattr(obj, 'jute_yarn_id'):
                    obj.item_id = 500
        self._mock_session.flush.side_effect = mock_flush
        self._mock_session.refresh.side_effect = lambda obj: setattr(obj, 'jute_yarn_id', 10)

        payload = {
            "jute_yarn_name": "Simple-Yarn",
            "co_id": "1",
        }

        response = client.post("/api/yarnMaster/yarn_create", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["item_id"] == 500

    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_no_kg_uom_returns_400(self, mock_uniqueness):
        """Should return 400 when the tenant has no active KG/KGS row in uom_mst."""
        mock_uniqueness.return_value = None
        self._mock_session.execute.return_value.fetchone.return_value = None

        payload = {
            "jute_yarn_name": "Simple-Yarn",
            "co_id": "1",
        }

        response = client.post("/api/yarnMaster/yarn_create", json=payload)

        assert response.status_code == 400
        assert "kg" in response.json()["detail"].lower()


# ============================================================================
# PUT /api/yarnMaster/yarn_edit/{yarn_id}
# ============================================================================

class TestYarnEdit:
    """Tests for PUT /api/yarnMaster/yarn_edit/{yarn_id}"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_success_updates_item_and_yarn(self, mock_uniqueness):
        """Should update item_mst and jute_yarn_mst when item_id exists."""
        mock_uniqueness.return_value = None

        # Mock existing yarn record with item_id
        existing_yarn = MagicMock()
        existing_yarn.jute_yarn_id = 1
        existing_yarn.item_id = 100
        existing_yarn.co_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing_yarn

        # Mock existing item record
        existing_item = MagicMock()
        existing_item.item_id = 100
        existing_item.item_name = "Old-Name"
        existing_item.item_code = "Old-Name"
        existing_item.updated_by = 1

        # query(JuteYarnMst).filter -> first -> existing_yarn
        # query(ItemMst).filter -> first -> existing_item
        def mock_query(model):
            mock_q = MagicMock()
            if model.__tablename__ == "jute_yarn_mst":
                mock_q.filter.return_value.first.return_value = existing_yarn
            elif model.__tablename__ == "item_mst":
                mock_q.filter.return_value.first.return_value = existing_item
            return mock_q
        self._mock_session.query.side_effect = mock_query

        payload = {
            "jute_yarn_name": "12-HSWT-Silver",
            "jute_yarn_count": 12,
            "item_grp_id": 1672,
            "jute_yarn_remarks": "Silver quality",
            "co_id": "1",
        }

        response = client.put("/api/yarnMaster/yarn_edit/1", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Yarn master updated successfully"
        assert body["jute_yarn_id"] == 1
        assert body["item_id"] == 100

        # Verify item was updated
        assert existing_item.item_name == "12-HSWT-Silver"
        assert existing_item.item_code == "12-HSWT-Silver"
        assert existing_item.item_grp_id == 1672

        # Verify yarn was updated
        assert existing_yarn.jute_yarn_name == "12-HSWT-Silver"
        assert existing_yarn.jute_yarn_count == 12.0
        assert existing_yarn.item_grp_id == 1672

    @patch("src.masters.yarnMaster._check_item_uniqueness")
    def test_edit_creates_item_for_pre_migration_row(self, mock_uniqueness):
        """Should create item_mst when editing a pre-migration yarn with no item_id."""
        mock_uniqueness.return_value = None
        # uom_mst lookup for the tenant's KG unit
        self._mock_session.execute.return_value.fetchone.return_value = (163,)

        # Mock existing yarn without item_id (pre-migration)
        existing_yarn = MagicMock()
        existing_yarn.jute_yarn_id = 5
        existing_yarn.item_id = None  # no item yet
        existing_yarn.co_id = 1

        self._mock_session.query.return_value.filter.return_value.first.return_value = existing_yarn

        added_objects = []
        self._mock_session.add.side_effect = lambda obj: added_objects.append(obj)
        def mock_flush():
            for obj in added_objects:
                if hasattr(obj, 'item_id'):
                    obj.item_id = 777
        self._mock_session.flush.side_effect = mock_flush

        payload = {
            "jute_yarn_name": "8-SLYN",
            "jute_yarn_count": 8,
            "item_grp_id": 1675,
            "co_id": "1",
        }

        response = client.put("/api/yarnMaster/yarn_edit/5", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["item_id"] == 777

        # A new ItemMst should have been added
        assert len(added_objects) == 1
        assert added_objects[0].item_name == "8-SLYN"

    def test_not_found_returns_404(self):
        """Should return 404 when yarn record doesn't exist."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        payload = {
            "jute_yarn_name": "Test",
            "co_id": "1",
        }

        response = client.put("/api/yarnMaster/yarn_edit/999", json=payload)
        assert response.status_code == 404

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        payload = {"jute_yarn_name": "Test"}
        response = client.put("/api/yarnMaster/yarn_edit/1", json=payload)
        assert response.status_code == 400

    def test_missing_yarn_name_returns_400(self):
        """Should return 400 when yarn name is missing."""
        payload = {"co_id": "1"}
        response = client.put("/api/yarnMaster/yarn_edit/1", json=payload)
        assert response.status_code == 400


# ============================================================================
# HELPER FUNCTION TESTS
# ============================================================================

class TestHelperFunctions:
    """Tests for helper functions in yarnMaster.py"""

    def test_generate_item_code_from_name(self):
        """Should return trimmed yarn name as item code."""
        from src.masters.yarnMaster import _generate_item_code
        assert _generate_item_code("10-SKWP-Gold") == "10-SKWP-Gold"
        assert _generate_item_code("  12-HSWT  ") == "12-HSWT"
        assert _generate_item_code("") == ""
        assert _generate_item_code(None) == ""

    def test_yarn_item_defaults(self):
        """YARN_ITEM_DEFAULTS should have all required fields."""
        from src.masters.yarnMaster import YARN_ITEM_DEFAULTS
        assert YARN_ITEM_DEFAULTS["active"] == 1
        assert YARN_ITEM_DEFAULTS["tangible"] is True
        assert YARN_ITEM_DEFAULTS["hsn_code"] == "5304"
        assert YARN_ITEM_DEFAULTS["tax_percentage"] == 5.0
        # uom_id must NOT be in defaults — resolved per tenant at runtime
        # (hardcoded 163 broke sls, which has no uom_id 163; regression 2026-07-24)
        assert "uom_id" not in YARN_ITEM_DEFAULTS
        assert YARN_ITEM_DEFAULTS["uom_rounding"] == 0
        assert YARN_ITEM_DEFAULTS["rate_rounding"] == 2

    def test_yarn_item_type_id(self):
        """YARN_ITEM_TYPE_ID should be 4."""
        from src.masters.yarnMaster import YARN_ITEM_TYPE_ID
        assert YARN_ITEM_TYPE_ID == 4

    def test_resolve_yarn_uom_id_found(self):
        """Should return the tenant's KG uom_id from uom_mst."""
        from src.masters.yarnMaster import _resolve_yarn_uom_id
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (132,)
        assert _resolve_yarn_uom_id(mock_db) == 132

    def test_resolve_yarn_uom_id_missing_raises_400(self):
        """Should raise 400 (not FK 500) when tenant has no KG/KGS uom."""
        from src.masters.yarnMaster import _resolve_yarn_uom_id
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None
        with pytest.raises(HTTPException) as exc:
            _resolve_yarn_uom_id(mock_db)
        assert exc.value.status_code == 400


# ============================================================================
# SQL QUERY FUNCTION TESTS
# ============================================================================

class TestQueryFunctions:
    """Tests for SQL query functions."""

    def test_get_yarn_list_query_returns_text(self):
        """Query function should return sqlalchemy text object."""
        from src.masters.yarnMaster import get_yarn_list_query
        from sqlalchemy import text
        result = get_yarn_list_query()
        assert isinstance(result, type(text("")))

    def test_get_yarn_list_query_contains_item_join(self):
        """List query should JOIN item_mst for name resolution."""
        from src.masters.yarnMaster import get_yarn_list_query
        sql_str = str(get_yarn_list_query())
        assert "item_mst im" in sql_str
        assert "COALESCE(im.item_name, ym.jute_yarn_name)" in sql_str
        assert "im.item_code" in sql_str
        assert ":co_id" in sql_str

    def test_get_yarn_list_with_search_contains_item_code_search(self):
        """Search query should include item_code in search criteria."""
        from src.masters.yarnMaster import get_yarn_list_with_search_query
        sql_str = str(get_yarn_list_with_search_query())
        assert "im.item_code LIKE :search" in sql_str

    def test_get_yarn_types_for_company_filters_by_item_type(self):
        """Yarn types query should filter by item_type_id."""
        from src.masters.yarnMaster import get_yarn_types_for_company
        sql_str = str(get_yarn_types_for_company())
        assert ":item_type_id" in sql_str
        assert ":co_id" in sql_str


# Need HTTPException for test_duplicate_name_returns_409
from fastapi import HTTPException
