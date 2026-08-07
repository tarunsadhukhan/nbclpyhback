"""
Tests for Item BOM Master endpoints.
Tests for src/masters/itemBom.py
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestItemBomEndpoints:
    """Tests for Item BOM Master API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI dependencies for all endpoint tests."""
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_get_bom_list_success(self):
        """Should return list of items with BOM definitions."""
        mock_row = _mock_row({
            "item_id": 1,
            "item_code": "ASM-001",
            "item_name": "Assembly A",
            "item_group_name": "Assemblies",
            "component_count": 3,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [mock_row]

        response = client.get("/api/itemBomMaster/get_bom_list?co_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["item_code"] == "ASM-001"

    def test_get_bom_list_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/itemBomMaster/get_bom_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_get_bom_tree_success(self):
        """Should return recursive tree structure."""
        # First call: children of root item (item_id=1)
        child_row = _mock_row({
            "bom_id": 1,
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 3.0,
            "uom_id": 1,
            "uom_name": "NOS",
            "sequence_no": 0,
            "child_item_code": "ITM-002",
            "child_item_name": "Item B",
            "child_is_assembly": False,
            "has_children": 0,
        })
        # First call returns one child, second call (recursive) returns empty
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [child_row],  # children of item 1
            [],           # children of item 2 (leaf)
        ]

        response = client.get("/api/itemBomMaster/get_bom_tree?co_id=1&item_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["child_item_code"] == "ITM-002"
        assert body["data"][0]["is_leaf"] is True

    def test_get_bom_tree_empty_for_leaf(self):
        """Should return empty tree for an item with no children."""
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get("/api/itemBomMaster/get_bom_tree?co_id=1&item_id=99")

        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_get_bom_tree_missing_item_id(self):
        """Should return 400 when item_id is missing."""
        response = client.get("/api/itemBomMaster/get_bom_tree?co_id=1")
        assert response.status_code == 400
        assert "item_id" in response.json()["detail"].lower()

    def test_get_bom_children_success(self):
        """Should return direct children of a parent item."""
        child_row = _mock_row({
            "bom_id": 1,
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 5.0,
            "uom_id": 1,
            "uom_name": "KG",
            "sequence_no": 0,
            "child_item_code": "ITM-002",
            "child_item_name": "Item B",
            "child_is_assembly": False,
            "has_children": 0,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [child_row]

        response = client.get("/api/itemBomMaster/get_bom_children?co_id=1&parent_item_id=1")

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1

    def test_get_bom_parents_success(self):
        """Should return parent assemblies containing the given item."""
        parent_row = _mock_row({
            "bom_id": 1,
            "parent_item_id": 10,
            "parent_item_code": "ASM-010",
            "parent_item_name": "Assembly X",
            "qty": 2.0,
            "uom_id": 1,
            "uom_name": "NOS",
        })
        self._mock_session.execute.return_value.fetchall.return_value = [parent_row]

        response = client.get("/api/itemBomMaster/get_bom_parents?co_id=1&child_item_id=2")

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["parent_item_code"] == "ASM-010"

    def test_bom_add_component_success(self):
        """Should add a new BOM component and ensure BOM header exists."""
        # No existing BomHdr or ItemBom row found
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None
        # Circular ref check: no children for child item
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 3,
            "uom_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 201
        assert "bom_id" in response.json()
        # add called twice: once for BomHdr, once for ItemBom
        assert self._mock_session.add.call_count == 2
        self._mock_session.commit.assert_called()

    def test_bom_add_component_self_reference(self):
        """Should reject self-referencing BOM."""
        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 1,
            "qty": 1,
            "uom_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 400
        assert "itself" in response.json()["detail"].lower()

    def test_bom_add_component_duplicate_allowed(self):
        """Duplicate (parent,child,co_id) now inserts a new row.

        BOMs double as production/assembly flows, so the same item may appear
        multiple times under one parent with distinct sequence_no values.
        """
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 3,
            "uom_id": 1,
            "co_id": 1,
            "sequence_no": 2,
        })

        assert response.status_code == 201
        assert "bom_id" in response.json()

    @patch("src.masters.itemBom.has_circular_reference", return_value=True)
    def test_bom_add_component_circular_reference(self, mock_circ):
        """Should reject circular BOM reference."""
        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 1,
            "uom_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 400
        assert "circular" in response.json()["detail"].lower()

    def test_bom_edit_component_success(self):
        """Should update qty/uom of an existing component."""
        existing = MagicMock()
        existing.qty = 3.0
        existing.uom_id = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        response = client.post("/api/itemBomMaster/bom_edit_component", json={
            "bom_id": 1,
            "co_id": 1,
            "qty": 5,
            "uom_id": 2,
        })

        assert response.status_code == 200
        assert existing.qty == 5.0
        assert existing.uom_id == 2
        self._mock_session.commit.assert_called()

    def test_bom_edit_component_not_found(self):
        """Should return 404 when bom_id not found."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/api/itemBomMaster/bom_edit_component", json={
            "bom_id": 999,
            "co_id": 1,
            "qty": 5,
        })

        assert response.status_code == 404

    def test_bom_remove_component_success(self):
        """Should soft-delete a component."""
        existing = MagicMock()
        existing.active = 1
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        response = client.post("/api/itemBomMaster/bom_remove_component", json={
            "bom_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 200
        assert existing.active == 0
        self._mock_session.commit.assert_called()

    def test_bom_remove_component_not_found(self):
        """Should return 404 for non-existent bom_id."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/api/itemBomMaster/bom_remove_component", json={
            "bom_id": 999,
            "co_id": 1,
        })

        assert response.status_code == 404

    def test_bom_add_component_with_additional_description(self):
        """Should persist additional_description when provided."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 3,
            "uom_id": 1,
            "co_id": 1,
            "additional_description": "left-twist, dyed indigo",
        })

        assert response.status_code == 201
        added_objs = [c.args[0] for c in self._mock_session.add.call_args_list]
        item_boms = [o for o in added_objs if hasattr(o, "additional_description")]
        assert any(getattr(o, "additional_description", None) == "left-twist, dyed indigo" for o in item_boms)

    def test_bom_add_component_omits_description_stores_none(self):
        """Should store None when additional_description is omitted from payload."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
            "child_item_id": 2,
            "qty": 3,
            "uom_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 201
        added_objs = [c.args[0] for c in self._mock_session.add.call_args_list]
        item_boms = [o for o in added_objs if hasattr(o, "additional_description")]
        assert all(getattr(o, "additional_description", None) is None for o in item_boms)

    def test_bom_edit_component_updates_additional_description(self):
        """Should update additional_description when present in payload."""
        existing = MagicMock()
        existing.additional_description = None
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        response = client.post("/api/itemBomMaster/bom_edit_component", json={
            "bom_id": 1,
            "co_id": 1,
            "additional_description": "left-twist, dyed indigo",
        })

        assert response.status_code == 200
        assert existing.additional_description == "left-twist, dyed indigo"
        self._mock_session.commit.assert_called()

    def test_bom_edit_component_clears_additional_description_when_empty(self):
        """Empty string in payload should clear field to None."""
        existing = MagicMock()
        existing.additional_description = "old note"
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing

        response = client.post("/api/itemBomMaster/bom_edit_component", json={
            "bom_id": 1,
            "co_id": 1,
            "additional_description": "",
        })

        assert response.status_code == 200
        assert existing.additional_description is None

    def test_bom_add_component_missing_fields(self):
        """Should return 400 when required fields are missing."""
        response = client.post("/api/itemBomMaster/bom_add_component", json={
            "parent_item_id": 1,
        })

        assert response.status_code == 400


class TestBulkAddComponents:
    """Tests for POST /bom_add_components_bulk."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _baseline_mocks(self):
        """Configure the mock session for the happy path:
        - No existing BomHdr (so ensure_bom_hdr_exists creates one)
        - has_circular_reference returns False (empty children rows)
        """
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        self._mock_session.execute.return_value.fetchall.return_value = []

    def test_bulk_add_success(self):
        """Should insert N components and return N bom_ids in order."""
        self._baseline_mocks()

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [
                {"child_item_id": 2, "qty": 3, "uom_id": 1, "sequence_no": 1},
                {"child_item_id": 3, "qty": 1.5, "uom_id": 1, "sequence_no": 2},
                {"child_item_id": 4, "qty": 7, "uom_id": 2, "sequence_no": 3,
                 "additional_description": "spool A"},
            ],
        })

        assert response.status_code == 201
        body = response.json()
        assert "bom_ids" in body
        assert len(body["bom_ids"]) == 3
        # 1 BomHdr + 3 ItemBom rows
        assert self._mock_session.add.call_count == 4
        self._mock_session.commit.assert_called()

        added_objs = [c.args[0] for c in self._mock_session.add.call_args_list]
        item_boms = [o for o in added_objs if hasattr(o, "child_item_id")]
        assert [o.child_item_id for o in item_boms] == [2, 3, 4]
        assert item_boms[2].additional_description == "spool A"
        assert item_boms[0].additional_description is None

    def test_bulk_add_empty_components_list(self):
        """Empty components list should 400, no commit."""
        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [],
        })

        assert response.status_code == 400
        assert "non-empty" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_bulk_add_missing_components_key(self):
        """Missing components key should 400."""
        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
        })

        assert response.status_code == 400

    def test_bulk_add_missing_parent_item_id(self):
        """Missing parent_item_id should 400."""
        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "co_id": 1,
            "components": [{"child_item_id": 2, "qty": 1, "uom_id": 1}],
        })

        assert response.status_code == 400
        assert "parent_item_id" in response.json()["detail"].lower()

    def test_bulk_add_allows_duplicate_child_ids(self):
        """Same child_item_id repeated in one payload is allowed (rows differentiated
        by sequence_no / additional_description). Both rows get inserted."""
        self._baseline_mocks()

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [
                {"child_item_id": 2, "qty": 1, "uom_id": 1, "sequence_no": 1},
                {"child_item_id": 2, "qty": 2, "uom_id": 1, "sequence_no": 2,
                 "additional_description": "second copy"},
            ],
        })

        assert response.status_code == 201
        body = response.json()
        assert len(body["bom_ids"]) == 2

        added_objs = [c.args[0] for c in self._mock_session.add.call_args_list]
        item_boms = [o for o in added_objs if hasattr(o, "child_item_id")]
        assert [o.child_item_id for o in item_boms] == [2, 2]
        assert [o.sequence_no for o in item_boms] == [1, 2]
        assert item_boms[1].additional_description == "second copy"
        self._mock_session.commit.assert_called()
        self._mock_session.rollback.assert_not_called()

    @patch("src.masters.itemBom.has_circular_reference", return_value=False)
    def test_bulk_add_circular_check_runs_once_per_unique_child(self, mock_circ):
        """3 rows of the same child should call has_circular_reference exactly once."""
        self._baseline_mocks()

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [
                {"child_item_id": 2, "qty": 1, "uom_id": 1, "sequence_no": 1},
                {"child_item_id": 2, "qty": 2, "uom_id": 1, "sequence_no": 2},
                {"child_item_id": 2, "qty": 3, "uom_id": 1, "sequence_no": 3},
            ],
        })

        assert response.status_code == 201
        assert mock_circ.call_count == 1

    def test_bulk_add_self_reference_rolls_back(self):
        """A component whose child_item_id equals parent_item_id should 400 and rollback."""
        self._baseline_mocks()

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [
                {"child_item_id": 2, "qty": 1, "uom_id": 1},
                {"child_item_id": 1, "qty": 1, "uom_id": 1},
            ],
        })

        assert response.status_code == 400
        assert "itself" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()
        self._mock_session.rollback.assert_called()

    @patch("src.masters.itemBom.has_circular_reference", return_value=True)
    def test_bulk_add_circular_reference_rolls_back(self, mock_circ):
        """Circular reference should 400 and rollback."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [{"child_item_id": 2, "qty": 1, "uom_id": 1}],
        })

        assert response.status_code == 400
        assert "circular" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()
        self._mock_session.rollback.assert_called()

    def test_bulk_add_invalid_component_missing_qty(self):
        """A component missing qty should 400 and rollback."""
        self._baseline_mocks()

        response = client.post("/api/itemBomMaster/bom_add_components_bulk", json={
            "parent_item_id": 1,
            "co_id": 1,
            "components": [
                {"child_item_id": 2, "qty": 1, "uom_id": 1},
                {"child_item_id": 3, "uom_id": 1},
            ],
        })

        assert response.status_code == 400
        self._mock_session.commit.assert_not_called()
