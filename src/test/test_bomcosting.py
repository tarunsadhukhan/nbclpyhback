"""
Tests for BOM Costing module endpoints.
Tests for src/bomcosting/costElement.py, bomCosting.py, stdRateCard.py
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


# ═══════════════════════════════════════════════════════════════
# COST ELEMENT ENDPOINTS
# ════���══════════════════════════════════════════════��═══════════


class TestCostElementEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_cost_element_tree_success(self):
        root_row = _mock_row({
            "cost_element_id": 1, "element_code": "MAT", "element_name": "Material",
            "parent_element_id": None, "element_level": 0, "element_type": "material",
            "default_basis": None, "is_leaf": 0, "sort_order": 100, "element_desc": None, "active": 1,
        })
        child_row = _mock_row({
            "cost_element_id": 2, "element_code": "MP_DIRECT", "element_name": "Direct Material",
            "parent_element_id": 1, "element_level": 1, "element_type": "material",
            "default_basis": "per_unit", "is_leaf": 1, "sort_order": 110, "element_desc": None, "active": 1,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [root_row, child_row]

        response = client.get("/api/bomCostElement/cost_element_tree?co_id=1")
        assert response.status_code == 200
        tree = response.json()["data"]
        assert len(tree) == 1
        assert tree[0]["element_code"] == "MAT"
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["element_code"] == "MP_DIRECT"

    def test_cost_element_tree_missing_co_id(self):
        response = client.get("/api/bomCostElement/cost_element_tree")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_cost_element_list_success(self):
        row = _mock_row({
            "cost_element_id": 1, "element_code": "MAT", "element_name": "Material",
            "parent_element_id": None, "element_level": 0, "element_type": "material",
            "default_basis": None, "is_leaf": 0, "sort_order": 100, "element_desc": None, "active": 1,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get("/api/bomCostElement/cost_element_list?co_id=1")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    def test_cost_element_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: setattr(obj, "cost_element_id", 99)
        )

        response = client.post("/api/bomCostElement/cost_element_create", json={
            "element_code": "TEST", "element_name": "Test Element",
            "element_type": "material", "co_id": 1, "is_leaf": 1, "sort_order": 999,
        })
        assert response.status_code == 201
        assert "cost_element_id" in response.json()

    def test_cost_element_create_missing_fields(self):
        response = client.post("/api/bomCostElement/cost_element_create", json={
            "element_code": "TEST", "co_id": 1,
        })
        assert response.status_code == 400

    def test_cost_element_seed_already_exists_returns_409(self):
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = MagicMock()

        response = client.post("/api/bomCostElement/cost_element_seed", json={"co_id": 1})
        assert response.status_code == 409


# ��══════════════════════��══════════════════════════════════���════
# BOM COSTING HEADER ENDPOINTS
# ���════════════════════════════════════════��═════════════════════


class TestBomCostingEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_bom_costing_list_success(self):
        row = _mock_row({
            "bom_hdr_id": 1, "item_id": 10, "item_code": "ITEM-001",
            "item_name": "Test Item", "bom_version": 1, "version_label": None,
            "status_id": 21, "status_name": "Draft", "effective_from": None,
            "effective_to": None, "is_current": 0, "remarks": None,
            "updated_date_time": "2026-03-30", "material_cost": 0,
            "conversion_cost": 0, "overhead_cost": 0, "total_cost": 0,
            "cost_per_unit": 0, "last_computed_at": None, "snapshot_status": None,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get("/api/bomCosting/bom_costing_list?co_id=1")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1

    def test_bom_costing_list_missing_co_id(self):
        response = client.get("/api/bomCosting/bom_costing_list")
        assert response.status_code == 400

    def test_bom_costing_create_success(self):
        version_row = _mock_row({"next_version": 1})
        self._mock_session.execute.return_value.fetchone.return_value = version_row
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: (
                setattr(obj, "bom_hdr_id", 42),
                setattr(obj, "bom_version", 1),
            )
        )

        response = client.post("/api/bomCosting/bom_costing_create", json={
            "item_id": 10, "co_id": 1,
        })
        assert response.status_code == 201
        data = response.json()
        assert "bom_hdr_id" in data
        assert "bom_version" in data

    def test_bom_costing_create_missing_item_id(self):
        response = client.post("/api/bomCosting/bom_costing_create", json={"co_id": 1})
        assert response.status_code == 400

    def test_bom_cost_entry_save_missing_fields(self):
        response = client.post("/api/bomCosting/bom_cost_entry_save", json={
            "bom_hdr_id": 1, "co_id": 1,
        })
        assert response.status_code == 400

    def test_bom_cost_entry_save_qty_rate_mismatch(self):
        # Mock BOM header exists
        mock_hdr = MagicMock()
        mock_hdr.active = 1
        # Mock cost element (leaf)
        mock_element = MagicMock()
        mock_element.is_leaf = 1

        self._mock_session.query.return_value.filter_by.return_value.first.side_effect = [
            mock_hdr, mock_element,
        ]

        response = client.post("/api/bomCosting/bom_cost_entry_save", json={
            "bom_hdr_id": 1, "cost_element_id": 2, "amount": 999,
            "qty": 10, "rate": 100,
            "effective_date": "2026-03-30", "co_id": 1,
        })
        assert response.status_code == 400
        assert "amount" in response.json()["detail"].lower()

    def test_bom_cost_entry_delete_missing_fields(self):
        response = client.post("/api/bomCosting/bom_cost_entry_delete", json={"co_id": 1})
        assert response.status_code == 400

    def test_bom_cost_snapshot_list_missing_fields(self):
        response = client.get("/api/bomCosting/bom_cost_snapshot_list?co_id=1")
        assert response.status_code == 400

    def test_bom_cost_summary_success(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/bomCosting/bom_cost_summary?co_id=1")
        assert response.status_code == 200
        assert response.json()["data"] == []


# ═══════════════════════════��════════════════════════════════���══
# STANDARD RATE CARD ENDPOINTS
# ═══════════════════════════════════════════════════════════════


class TestStdRateCardEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_rate_card_list_success(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/stdRateCard/std_rate_card_list?co_id=1")
        assert response.status_code == 200
        assert "data" in response.json()

    def test_rate_card_list_missing_co_id(self):
        response = client.get("/api/stdRateCard/std_rate_card_list")
        assert response.status_code == 400

    def test_rate_card_create_invalid_type(self):
        response = client.post("/api/stdRateCard/std_rate_card_create", json={
            "rate_type": "invalid_type", "rate": 100, "valid_from": "2026-03-30", "co_id": 1,
        })
        assert response.status_code == 400
        assert "rate_type" in response.json()["detail"].lower()

    def test_rate_card_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: setattr(obj, "std_rate_card_id", 5)
        )

        response = client.post("/api/stdRateCard/std_rate_card_create", json={
            "rate_type": "machine_hour", "rate": 350, "uom": "hr",
            "valid_from": "2026-03-30", "co_id": 1,
        })
        assert response.status_code == 201
        assert "std_rate_card_id" in response.json()

    def test_rate_card_create_missing_rate(self):
        response = client.post("/api/stdRateCard/std_rate_card_create", json={
            "rate_type": "machine_hour", "valid_from": "2026-03-30", "co_id": 1,
        })
        assert response.status_code == 400

    def test_rate_card_apply_missing_params(self):
        response = client.get("/api/stdRateCard/std_rate_card_apply?co_id=1")
        assert response.status_code == 400
