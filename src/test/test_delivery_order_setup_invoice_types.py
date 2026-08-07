"""
Tests for invoice_types in GET /api/salesDeliveryOrder/get_delivery_order_setup_1.
Verifies that the setup endpoint returns invoice types mapped to the company.
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


class TestDeliveryOrderSetupInvoiceTypes:

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_setup_returns_invoice_types(self):
        """Setup response should include invoice_types array."""
        # Mock all DB calls in order:
        # 1. branches, 2. customers, 3. customer_branches, 4. brokers,
        # 5. transporters, 6. approved_sales_orders, 7. item_groups, 8. invoice_types
        branches = [_mock_row({"branch_id": 1, "branch_name": "Main"})]
        customers = [_mock_row({"party_id": 1, "party_name": "Cust A"})]
        cust_branches = []
        brokers = []
        transporters = []
        approved_orders = [_mock_row({
            "sales_order_id": 1,
            "sales_no": 1,
            "sales_order_date": "2026-01-01",
            "party_name": "Cust A",
            "net_amount": 1000,
            "co_prefix": "CO",
            "branch_prefix": "BR",
        })]
        item_groups = [_mock_row({"item_grp_id": 1, "item_grp_name": "Group A"})]
        invoice_types = [
            _mock_row({"invoice_type_id": 1, "invoice_type_name": "Regular"}),
            _mock_row({"invoice_type_id": 2, "invoice_type_name": "Hessian"}),
        ]

        self._mock_session.execute.side_effect = [
            MagicMock(fetchall=lambda: branches),
            MagicMock(fetchall=lambda: customers),
            MagicMock(fetchall=lambda: cust_branches),
            MagicMock(fetchall=lambda: brokers),
            MagicMock(fetchall=lambda: transporters),
            MagicMock(fetchall=lambda: approved_orders),
            MagicMock(fetchall=lambda: item_groups),
            MagicMock(fetchall=lambda: invoice_types),
        ]

        response = client.get("/api/salesDeliveryOrder/get_delivery_order_setup_1?co_id=1&branch_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "invoice_types" in body
        assert len(body["invoice_types"]) == 2
        assert body["invoice_types"][0]["invoice_type_id"] == 1
        assert body["invoice_types"][0]["invoice_type_name"] == "Regular"
        assert body["invoice_types"][1]["invoice_type_id"] == 2
        assert body["invoice_types"][1]["invoice_type_name"] == "Hessian"

    def test_setup_returns_empty_invoice_types_when_none_mapped(self):
        """Should return empty invoice_types when company has no mappings."""
        branches = [_mock_row({"branch_id": 1, "branch_name": "Main"})]
        customers = []
        cust_branches = []
        brokers = []
        transporters = []
        approved_orders = []
        item_groups = []
        invoice_types = []

        self._mock_session.execute.side_effect = [
            MagicMock(fetchall=lambda: branches),
            MagicMock(fetchall=lambda: customers),
            MagicMock(fetchall=lambda: cust_branches),
            MagicMock(fetchall=lambda: brokers),
            MagicMock(fetchall=lambda: transporters),
            MagicMock(fetchall=lambda: approved_orders),
            MagicMock(fetchall=lambda: item_groups),
            MagicMock(fetchall=lambda: invoice_types),
        ]

        response = client.get("/api/salesDeliveryOrder/get_delivery_order_setup_1?co_id=1&branch_id=1")

        assert response.status_code == 200
        body = response.json()
        assert "invoice_types" in body
        assert body["invoice_types"] == []
