"""
Tests for accounting party dropdown endpoint.
"""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


class TestPartiesDropdown:
    @patch("src.accounting.routers.get_tenant_db")
    @patch("src.accounting.routers.get_current_user_with_refresh")
    def test_parties_dropdown_success(self, mock_auth, mock_db):
        """Test fetching parties dropdown list with search."""
        mock_session = MagicMock()
        mock_row1 = MagicMock()
        mock_row1._mapping = {"party_id": 1, "supp_name": "ABC Enterprises", "supp_code": "ABC001"}
        mock_row2 = MagicMock()
        mock_row2._mapping = {"party_id": 2, "supp_name": "XYZ Suppliers", "supp_code": "XYZ002"}

        mock_session.execute.return_value.fetchall.return_value = [mock_row1, mock_row2]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        response = client.get("/api/accounting/parties_dropdown?co_id=1")

        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 2
        assert data["data"][0]["party_id"] == 1
        assert data["data"][0]["supp_name"] == "ABC Enterprises"
        assert data["data"][1]["party_id"] == 2

    @patch("src.accounting.routers.get_tenant_db")
    def test_parties_dropdown_missing_co_id(self, mock_db):
        """Test missing co_id parameter."""
        response = client.get("/api/accounting/parties_dropdown")

        assert response.status_code == 400
        data = response.json()
        assert "co_id" in data["detail"].lower()

    @patch("src.accounting.routers.get_tenant_db")
    @patch("src.accounting.routers.get_current_user_with_refresh")
    def test_parties_dropdown_with_search(self, mock_auth, mock_db):
        """Test parties dropdown with search filter."""
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {"party_id": 1, "supp_name": "ABC Corp", "supp_code": "ABC"}

        mock_session.execute.return_value.fetchall.return_value = [mock_row]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        response = client.get("/api/accounting/parties_dropdown?co_id=1&search=ABC")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["supp_name"] == "ABC Corp"

    @patch("src.accounting.routers.get_tenant_db")
    @patch("src.accounting.routers.get_current_user_with_refresh")
    def test_parties_dropdown_empty_result(self, mock_auth, mock_db):
        """Test parties dropdown with no matching results."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        response = client.get("/api/accounting/parties_dropdown?co_id=1&search=NONEXISTENT")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
