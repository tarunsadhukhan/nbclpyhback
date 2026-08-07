"""
Tests for Contractor Master API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app

client = TestClient(app)


# Patch paths for auth and db
AUTH_PATCH = "src.masters.contractor.get_current_user_with_refresh"
DB_PATCH = "src.masters.contractor.get_tenant_db"


def mock_db_session(rows=None, fetchone_result=None):
    """Create a mocked DB session."""
    mock_session = MagicMock()
    if rows is not None:
        mock_rows = []
        for r in rows:
            mock_row = MagicMock()
            mock_row._mapping = r
            mock_rows.append(mock_row)
        mock_session.execute.return_value.fetchall.return_value = mock_rows
    if fetchone_result is not None:
        mock_row = MagicMock()
        mock_row._mapping = fetchone_result
        # For duplicate check (cnt attribute)
        if "cnt" in fetchone_result:
            mock_row.cnt = fetchone_result["cnt"]
        mock_session.execute.return_value.fetchone.return_value = mock_row
    return mock_session


class TestGetContractorTable:
    """Tests for GET /get_contractor_table endpoint."""

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_returns_paginated_list(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = mock_db_session(rows=[
            {"cont_id": 1, "contractor_name": "ABC Contractors", "phone_no": "1234567890",
             "email_id": "abc@test.com", "pan_no": "ABCDE1234F", "branch_name": "Main", "branch_id": 1},
            {"cont_id": 2, "contractor_name": "XYZ Services", "phone_no": "9876543210",
             "email_id": "xyz@test.com", "pan_no": "XYZAB5678G", "branch_name": "Branch2", "branch_id": 2},
        ])
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/get_contractor_table?page=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "total" in data
        assert data["total"] == 2

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_search_filter(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = mock_db_session(rows=[
            {"cont_id": 1, "contractor_name": "ABC Contractors", "phone_no": "1234567890",
             "email_id": "abc@test.com", "pan_no": "ABCDE1234F", "branch_name": "Main", "branch_id": 1},
        ])
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/get_contractor_table?search=ABC")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1


class TestGetContractorById:
    """Tests for GET /get_contractor_by_id/{cont_id} endpoint."""

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_returns_contractor(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {
            "cont_id": 1, "contractor_name": "ABC Contractors",
            "phone_no": "1234567890", "email_id": "abc@test.com",
            "pan_no": "ABCDE1234F", "branch_name": "Main", "branch_id": 1,
        }
        mock_session.execute.return_value.fetchone.return_value = mock_row
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/get_contractor_by_id/1")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["contractor_name"] == "ABC Contractors"

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_not_found(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/get_contractor_by_id/999")
        assert response.status_code == 404


class TestContractorCreateSetup:
    """Tests for GET /contractor_create_setup endpoint."""

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_returns_branches(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = mock_db_session(rows=[
            {"branch_id": 1, "branch_name": "Main Branch"},
            {"branch_id": 2, "branch_name": "Sub Branch"},
        ])
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/contractor_create_setup?co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "branches" in data
        assert len(data["branches"]) == 2

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_missing_co_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.get("/api/contractorMaster/contractor_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestContractorCreate:
    """Tests for POST /contractor_create endpoint."""

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_missing_name(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.post(
            "/api/contractorMaster/contractor_create",
            json={"phone_no": "1234567890"},
        )
        assert response.status_code == 400
        assert "name" in response.json()["detail"].lower()


class TestContractorEdit:
    """Tests for PUT /contractor_edit/{cont_id} endpoint."""

    @patch(DB_PATCH)
    @patch(AUTH_PATCH)
    def test_missing_name_on_edit(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.return_value.__exit__ = MagicMock(return_value=False)

        response = client.put(
            "/api/contractorMaster/contractor_edit/1",
            json={"phone_no": "1234567890"},
        )
        assert response.status_code == 400
        assert "name" in response.json()["detail"].lower()
