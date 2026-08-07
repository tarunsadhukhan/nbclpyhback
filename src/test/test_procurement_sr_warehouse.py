# src/test/test_procurement_sr_warehouse.py
"""
Tests for warehouse hierarchy display in SR (Stores Receipt).

Validates that:
1. get_inward_dtl_for_sr_query() returns warehouse_path via recursive CTE
2. GET /storesReceipt/get_sr_by_inward_id/{id} returns warehouse_path in warehouses list
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import get_inward_dtl_for_sr_query

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


class TestWarehouseHierarchyQuery:
    """Tests for the get_inward_dtl_for_sr_query SQL function."""

    def test_returns_text_object(self):
        """Query function should return a sqlalchemy text object."""
        result = get_inward_dtl_for_sr_query()
        assert isinstance(result, type(text("")))

    def test_query_contains_recursive_cte(self):
        """Query should use a recursive CTE for warehouse hierarchy."""
        result = get_inward_dtl_for_sr_query()
        sql_str = str(result)
        assert "WITH RECURSIVE warehouse_hierarchy" in sql_str

    def test_query_selects_warehouse_path(self):
        """Query should return warehouse_path column."""
        result = get_inward_dtl_for_sr_query()
        sql_str = str(result)
        assert "warehouse_path" in sql_str

    def test_query_joins_warehouse_hierarchy(self):
        """Query should JOIN on warehouse_hierarchy instead of warehouse_mst directly."""
        result = get_inward_dtl_for_sr_query()
        sql_str = str(result)
        assert "warehouse_hierarchy AS wh_hier" in sql_str
        # Should NOT join directly on warehouse_mst for the main select
        assert "warehouse_mst AS wh ON" not in sql_str

    def test_query_builds_concat_path(self):
        """Recursive CTE should CONCAT parent path with '-' separator."""
        result = get_inward_dtl_for_sr_query()
        sql_str = str(result)
        assert "CONCAT(parent.warehouse_path, '-', child.warehouse_name)" in sql_str

    def test_query_has_required_bind_params(self):
        """Query should have :inward_id bind parameter."""
        result = get_inward_dtl_for_sr_query()
        sql_str = str(result)
        assert ":inward_id" in sql_str


class TestSREndpointWarehouseHierarchy:
    """Tests for warehouse hierarchy in GET /storesReceipt/get_sr_by_inward_id/{id}."""

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def _build_header_row(self):
        """Build a mock header row with all required fields."""
        return _mock_row({
            "inward_id": 10,
            "inward_sequence_no": 1,
            "inward_date": None,
            "branch_id": 1,
            "branch_name": "Main",
            "supplier_id": 5,
            "supplier_name": "Supplier A",
            "supplier_state_id": 1,
            "supplier_state_name": "Maharashtra",
            "bill_branch_id": 1,
            "billing_branch_name": "Main",
            "billing_state_id": 1,
            "billing_state_name": "Maharashtra",
            "ship_branch_id": 1,
            "shipping_branch_name": "Main",
            "shipping_state_id": 1,
            "shipping_state_name": "Maharashtra",
            "india_gst": 1,
            "inspection_check": True,
            "co_prefix": "CO",
            "branch_prefix": "BR",
            "sr_no": None,
            "sr_date": None,
            "sr_status": 21,
            "sr_status_name": "Draft",
            "inspection_date": None,
            "challan_no": None,
            "challan_date": None,
            "invoice_date": None,
            "invoice_amount": 0,
            "invoice_recvd_date": None,
            "vehicle_number": None,
            "driver_name": None,
            "driver_contact_no": None,
            "consignment_no": None,
            "consignment_date": None,
            "ewaybillno": None,
            "ewaybill_date": None,
            "despatch_remarks": None,
            "receipts_remarks": None,
            "sr_remarks": None,
            "gross_amount": 0,
            "net_amount": 0,
        })

    def test_warehouses_response_contains_warehouse_path(self):
        """The warehouses list in the response should include warehouse_path."""
        header_row = self._build_header_row()
        dtl_row = _mock_row({
            "inward_dtl_id": 100,
            "inward_id": 10,
            "po_dtl_id": 50,
            "po_id": 5,
            "item_id": 1,
            "item_code": "ITM001",
            "item_name": "Test Item",
            "item_grp_id": 1,
            "item_grp_code": "GRP1",
            "item_grp_name": "Group 1",
            "item_make_id": None,
            "item_make_name": None,
            "accepted_item_make_id": None,
            "accepted_item_make_name": None,
            "uom_id": 1,
            "uom_name": "KG",
            "approved_qty": 10,
            "rejected_qty": 0,
            "rate": 100,
            "accepted_rate": 100,
            "amount": 1000,
            "discount_mode": None,
            "discount_value": None,
            "discount_amount": None,
            "remarks": None,
            "warehouse_id": 3,
            "warehouse_name": "Shelf 1",
            "warehouse_path": "Main Store-Section A-Shelf 1",
            "po_rate": 100,
            "tax_percentage": 18,
        })
        warehouse_row = _mock_row({
            "warehouse_id": 3,
            "warehouse_name": "Shelf 1",
            "warehouse_path": "Main Store-Section A-Shelf 1",
            "branch_id": 1,
        })
        addl_charges_mst_row = []
        addl_charges_row = []

        # Configure mock session execute to return different results per call
        call_count = {"n": 0}
        def side_effect(query, params=None):
            call_count["n"] += 1
            result = MagicMock()
            n = call_count["n"]
            if n == 1:
                # header query
                result.fetchone.return_value = header_row
                result.fetchall.return_value = [header_row]
            elif n == 2:
                # detail query
                result.fetchone.return_value = dtl_row
                result.fetchall.return_value = [dtl_row]
            elif n == 3:
                # warehouse query
                result.fetchone.return_value = warehouse_row
                result.fetchall.return_value = [warehouse_row]
            elif n == 4:
                # additional charges master
                result.fetchone.return_value = None
                result.fetchall.return_value = addl_charges_mst_row
            elif n == 5:
                # existing additional charges
                result.fetchone.return_value = None
                result.fetchall.return_value = addl_charges_row
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
                result.scalar.return_value = 0
            return result

        self.mock_session.execute.side_effect = side_effect

        response = client.get("/api/storesReceipt/get_sr_by_inward_id/10?co_id=1")

        assert response.status_code == 200
        data = response.json()
        warehouses = data.get("warehouses", [])
        assert len(warehouses) > 0
        # Verify warehouse_path is present in the response
        assert "warehouse_path" in warehouses[0]
        assert warehouses[0]["warehouse_path"] == "Main Store-Section A-Shelf 1"

    def test_line_items_contain_warehouse_path(self):
        """Line items in the response should include warehouse_path from the recursive CTE."""
        header_row = self._build_header_row()
        dtl_row = _mock_row({
            "inward_dtl_id": 100,
            "inward_id": 10,
            "po_dtl_id": 50,
            "po_id": 5,
            "item_id": 1,
            "item_code": "ITM001",
            "item_name": "Test Item",
            "item_grp_id": 1,
            "item_grp_code": "GRP1",
            "item_grp_name": "Group 1",
            "item_make_id": None,
            "item_make_name": None,
            "accepted_item_make_id": None,
            "accepted_item_make_name": None,
            "uom_id": 1,
            "uom_name": "KG",
            "approved_qty": 10,
            "rejected_qty": 0,
            "rate": 100,
            "accepted_rate": 100,
            "amount": 1000,
            "discount_mode": None,
            "discount_value": None,
            "discount_amount": None,
            "remarks": None,
            "warehouse_id": 3,
            "warehouse_name": "Shelf 1",
            "warehouse_path": "Main Store-Section A-Shelf 1",
            "po_rate": 100,
            "tax_percentage": 18,
        })

        call_count = {"n": 0}
        def side_effect(query, params=None):
            call_count["n"] += 1
            result = MagicMock()
            n = call_count["n"]
            if n == 1:
                result.fetchone.return_value = header_row
                result.fetchall.return_value = [header_row]
            elif n == 2:
                result.fetchone.return_value = dtl_row
                result.fetchall.return_value = [dtl_row]
            elif n == 3:
                result.fetchone.return_value = None
                result.fetchall.return_value = []  # no warehouses
            elif n == 4:
                result.fetchone.return_value = None
                result.fetchall.return_value = []  # no addl charges master
            elif n == 5:
                result.fetchone.return_value = None
                result.fetchall.return_value = []  # no existing addl charges
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
                result.scalar.return_value = 0
            return result

        self.mock_session.execute.side_effect = side_effect

        response = client.get("/api/storesReceipt/get_sr_by_inward_id/10?co_id=1")

        assert response.status_code == 200
        data = response.json()
        line_items = data.get("line_items", [])
        assert len(line_items) > 0
        # Verify warehouse_path is present in line item data
        assert "warehouse_path" in line_items[0]
        assert line_items[0]["warehouse_path"] == "Main Store-Section A-Shelf 1"
