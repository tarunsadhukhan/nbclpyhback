"""Tests for subdepartment master create endpoint — order_by validation."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.departments import optional_auth

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestSubDeptMasterCreate:
    """Tests for POST /api/deptMaster/subdept_master_create."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI dependencies for all tests."""
        self._mock_session = MagicMock()
        # stub refresh so db.refresh(obj) sets sub_dept_id
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: setattr(obj, "sub_dept_id", 42)
        )
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[optional_auth] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_create_missing_order_by_returns_400(self):
        """Should return 400 when order_by is missing."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 400
        assert "order_by" in response.json()["detail"].lower()

    def test_create_empty_string_order_by_returns_400(self):
        """Should return 400 when order_by is empty string."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": "",
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 400
        assert "order_by" in response.json()["detail"].lower()

    def test_create_non_integer_order_by_returns_400(self):
        """Should return 400 when order_by is not a valid integer."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": "abc",
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 400
        assert "order_by" in response.json()["detail"].lower()

    def test_create_negative_order_by_returns_400(self):
        """Should return 400 when order_by is negative."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": -5,
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 400
        assert "order_by" in response.json()["detail"].lower()

    def test_create_missing_required_fields_returns_400(self):
        """Should return 400 when branch_id is missing."""
        payload = {
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": 1,
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 400

    def test_create_valid_order_by_succeeds(self):
        """Should return 201 when all fields including order_by are valid."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": 5,
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["message"] == "Subdepartment created successfully"
        assert "subdept_master_id" in data

    def test_create_zero_order_by_succeeds(self):
        """Should accept order_by=0 (non-negative)."""
        payload = {
            "branch_id": 1,
            "subdept_name": "Test Subdept",
            "subdept_code": "TST",
            "dept_id": 1,
            "order_by": 0,
        }
        response = client.post("/api/deptMaster/subdept_master_create", json=payload)
        assert response.status_code == 201
