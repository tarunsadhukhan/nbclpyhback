# src/test/test_procurement_po_setup.py
"""
Tests for GET /procurementPO/get_po_setup_2 endpoint,
specifically the last purchase rate enrichment feature.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestPOSetup2LastPurchaseRate:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_items_include_last_purchase_rate_when_co_id_provided(self):
        """When co_id is passed, items should include last_purchase_rate fields."""
        # Mock responses for the 4 queries in order:
        # 1. item_grp_mst lookup
        grp_row = MagicMock()
        grp_row.item_grp_code = "GRP01"
        grp_row.item_grp_name = "Test Group"

        # 2. items query
        item_row = _mock_row({"item_id": 100, "item_code": "ITM01", "item_name": "Test Item", "uom_id": 1, "uom_name": "KG", "tax_percentage": 18.0})

        # 3. makes query
        make_row = _mock_row({"item_make_id": 1, "item_make_name": "Brand A"})

        # 4. uoms query
        uom_row = _mock_row({"item_id": 100, "map_from_id": 1, "map_from_name": "KG", "map_to_id": 2, "uom_name": "TON", "relation_value": 1000, "rounding": 2})

        # 5. last purchase rates query
        rate_row = _mock_row({"item_id": 100, "last_purchase_rate": 250.50, "last_purchase_date": "2026-02-15", "last_supplier_name": "Supplier ABC"})

        self.mock_session.execute.return_value.fetchone.return_value = grp_row
        self.mock_session.execute.return_value.fetchall.side_effect = [
            [item_row],   # items
            [make_row],   # makes
            [uom_row],    # uoms
            [rate_row],   # last purchase rates
        ]

        response = client.get("/api/procurementPO/get_po_setup_2?item_group=1&co_id=1")
        assert response.status_code == 200

        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["last_purchase_rate"] == 250.50
        assert item["last_purchase_date"] == "2026-02-15"
        assert item["last_supplier_name"] == "Supplier ABC"

    def test_items_without_purchase_history_get_null(self):
        """Items with no prior approved PO should have null rate fields."""
        grp_row = MagicMock()
        grp_row.item_grp_code = "GRP01"
        grp_row.item_grp_name = "Test Group"

        item_row = _mock_row({"item_id": 200, "item_code": "ITM02", "item_name": "New Item", "uom_id": 1, "uom_name": "KG", "tax_percentage": 12.0})

        self.mock_session.execute.return_value.fetchone.return_value = grp_row
        self.mock_session.execute.return_value.fetchall.side_effect = [
            [item_row],  # items
            [],          # makes
            [],          # uoms
            [],          # no purchase rates
        ]

        response = client.get("/api/procurementPO/get_po_setup_2?item_group=1&co_id=1")
        assert response.status_code == 200

        item = response.json()["items"][0]
        assert item["last_purchase_rate"] is None
        assert item["last_purchase_date"] is None
        assert item["last_supplier_name"] is None

    def test_no_rate_fields_when_co_id_not_provided(self):
        """Without co_id, the response should not include last_purchase_rate fields (backward compat)."""
        grp_row = MagicMock()
        grp_row.item_grp_code = "GRP01"
        grp_row.item_grp_name = "Test Group"

        item_row = _mock_row({"item_id": 100, "item_code": "ITM01", "item_name": "Test Item", "uom_id": 1, "uom_name": "KG", "tax_percentage": 18.0})

        self.mock_session.execute.return_value.fetchone.return_value = grp_row
        self.mock_session.execute.return_value.fetchall.side_effect = [
            [item_row],  # items
            [],          # makes
            [],          # uoms
        ]

        response = client.get("/api/procurementPO/get_po_setup_2?item_group=1")
        assert response.status_code == 200

        item = response.json()["items"][0]
        assert "last_purchase_rate" not in item
        assert "last_purchase_date" not in item
        assert "last_supplier_name" not in item

    def test_missing_item_group_returns_400(self):
        response = client.get("/api/procurementPO/get_po_setup_2")
        assert response.status_code == 400
        assert "item_group" in response.json()["detail"].lower()

    def test_invalid_item_group_returns_400(self):
        response = client.get("/api/procurementPO/get_po_setup_2?item_group=abc")
        assert response.status_code == 400
        assert "item_group" in response.json()["detail"].lower()
