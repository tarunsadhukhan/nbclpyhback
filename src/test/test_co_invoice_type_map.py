"""
Tests for company invoice type mapping endpoints.
Tests for src/common/companyAdmin/company.py endpoints:
- GET /api/companyAdmin/co_invoice_type_map_setup
- POST /api/companyAdmin/co_invoice_type_map_save
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import verify_access_token

client = TestClient(app)


def _mock_row(mapping: dict):
    """Create a mock row with _mapping attribute."""
    row = MagicMock()
    row._mapping = mapping
    return row


class TestCoInvoiceTypeMapSetup:
    """Tests for GET /api/companyAdmin/co_invoice_type_map_setup"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_returns_companies_types_mappings(self):
        """Should return companies, invoice types, and current mappings."""
        companies = [
            _mock_row({"co_id": 1, "co_name": "Company A"}),
            _mock_row({"co_id": 2, "co_name": "Company B"}),
        ]
        types = [
            _mock_row({"invoice_type_id": 1, "invoice_type_name": "GST Invoice"}),
            _mock_row({"invoice_type_id": 2, "invoice_type_name": "Bill of Supply"}),
        ]
        mappings = [
            _mock_row({"co_id": 1, "invoice_type_id": 1}),
            _mock_row({"co_id": 2, "invoice_type_id": 2}),
        ]

        # execute() is called 3 times: for companies, types, mappings
        self._mock_session.execute.side_effect = [
            MagicMock(fetchall=lambda: companies),
            MagicMock(fetchall=lambda: types),
            MagicMock(fetchall=lambda: mappings),
        ]

        response = client.get("/api/companyAdmin/co_invoice_type_map_setup")

        assert response.status_code == 200
        body = response.json()
        assert "companies" in body
        assert "invoice_types" in body
        assert "mappings" in body
        assert len(body["companies"]) == 2
        assert len(body["invoice_types"]) == 2
        assert len(body["mappings"]) == 2

    def test_empty_setup_returns_empty_lists(self):
        """Should return empty lists when no data exists."""
        self._mock_session.execute.side_effect = [
            MagicMock(fetchall=lambda: []),
            MagicMock(fetchall=lambda: []),
            MagicMock(fetchall=lambda: []),
        ]

        response = client.get("/api/companyAdmin/co_invoice_type_map_setup")

        assert response.status_code == 200
        body = response.json()
        assert body["companies"] == []
        assert body["invoice_types"] == []
        assert body["mappings"] == []


class TestCoInvoiceTypeMapSave:
    """Tests for POST /api/companyAdmin/co_invoice_type_map_save"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_success_saves_mappings(self):
        """Should save company-to-invoice-type mappings successfully."""
        # First execute: check company exists
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"co_id": 1}
        )
        # Second execute: get valid invoice types
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"invoice_type_id": 1}),
            _mock_row({"invoice_type_id": 2}),
        ]

        payload = {"co_id": 1, "invoice_type_ids": [1, 2]}
        response = client.post("/api/companyAdmin/co_invoice_type_map_save", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert "message" in body
        assert body["co_id"] == 1
        assert body["invoice_type_ids"] == [1, 2]

    def test_company_not_found_returns_404(self):
        """Should return 404 when company doesn't exist."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        payload = {"co_id": 999, "invoice_type_ids": [1]}
        response = client.post("/api/companyAdmin/co_invoice_type_map_save", json=payload)

        assert response.status_code == 404
        assert "Company not found" in response.json()["detail"]

    def test_invalid_invoice_type_returns_400(self):
        """Should return 400 when invoice_type_id is invalid."""
        # Company exists
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"co_id": 1}
        )
        # Only invoice_type_id 1 is valid
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"invoice_type_id": 1}),
        ]

        payload = {"co_id": 1, "invoice_type_ids": [1, 999]}
        response = client.post("/api/companyAdmin/co_invoice_type_map_save", json=payload)

        assert response.status_code == 400
        assert "Invalid invoice_type_ids" in response.json()["detail"]

    def test_empty_invoice_types_accepted(self):
        """Should accept empty invoice_type_ids list to unmap all."""
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"co_id": 1}
        )
        self._mock_session.execute.return_value.fetchall.return_value = []

        payload = {"co_id": 1, "invoice_type_ids": []}
        response = client.post("/api/companyAdmin/co_invoice_type_map_save", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["invoice_type_ids"] == []
