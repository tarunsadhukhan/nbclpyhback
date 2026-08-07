"""
Tests for the Jute MR List report endpoint.
Tests for src/juteProcurement/reports.py @ GET /api/juteReports/mr-list
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


class TestJuteMrListReport:
    """Tests for GET /api/juteReports/mr-list."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI dependencies for all endpoint tests."""
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_missing_co_id_returns_400(self):
        """Should return 400 when co_id is missing."""
        response = client.get(
            "/api/juteReports/mr-list"
            "?date_from=2026-01-01&date_to=2026-01-31"
        )
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_missing_date_from_returns_400(self):
        """Should return 400 when date_from is missing."""
        response = client.get(
            "/api/juteReports/mr-list?co_id=1&date_to=2026-01-31"
        )
        assert response.status_code == 400
        assert "date_from" in response.json().get("detail", "").lower()

    def test_missing_date_to_returns_400(self):
        """Should return 400 when date_to is missing."""
        response = client.get(
            "/api/juteReports/mr-list?co_id=1&date_from=2026-01-01"
        )
        assert response.status_code == 400
        assert "date_to" in response.json().get("detail", "").lower()

    def test_bad_date_format_returns_400(self):
        """Should return 400 when date_from is not in YYYY-MM-DD format."""
        response = client.get(
            "/api/juteReports/mr-list"
            "?co_id=1&date_from=01-01-2026&date_to=2026-01-31"
        )
        assert response.status_code == 400
        assert "date_from" in response.json().get("detail", "").lower()

    def test_bad_date_to_format_returns_400(self):
        """Should return 400 when date_to is not in YYYY-MM-DD format."""
        response = client.get(
            "/api/juteReports/mr-list"
            "?co_id=1&date_from=2026-01-01&date_to=31/01/2026"
        )
        assert response.status_code == 400
        assert "date_to" in response.json().get("detail", "").lower()

    def test_invalid_co_id_returns_400(self):
        """Should return 400 when co_id is not an integer."""
        response = client.get(
            "/api/juteReports/mr-list"
            "?co_id=abc&date_from=2026-01-01&date_to=2026-01-31"
        )
        assert response.status_code == 400

    def test_happy_path_returns_200_with_data_and_total(self):
        """Should return 200 with a data list and total when the query succeeds."""
        row = _mock_row({
            "jute_mr_id": 101,
            "mr_number": "ABC/FAC/JMR/25-26/00001",
            "jute_mr_date": "2026-01-15",
            "branch_id": 1,
            "branch_name": "Main Factory",
            "party_id": 55,
            "party_name": "Acme Jute Traders",
            "vehicle_no": "WB12AB1234",
            "challan_no": "CH/001",
            "challan_date": "2026-01-14",
            "gross_weight": 5000.0,
            "net_weight": 4800.0,
            "actual_weight": 4750.0,
            "total_amount": 120000.0,
            "net_total": 118500.0,
            "status_id": 3,
            "status_name": "Approved",
        })

        # Sequence of execute() calls in the handler:
        #   1) list query  -> .fetchall() returns rows
        #   2) count query -> .scalar() returns total count
        list_execute_result = MagicMock()
        list_execute_result.fetchall.return_value = [row]

        count_execute_result = MagicMock()
        count_execute_result.scalar.return_value = 1

        self._mock_session.execute.side_effect = [
            list_execute_result,
            count_execute_result,
        ]

        response = client.get(
            "/api/juteReports/mr-list"
            "?co_id=1&branch_id=1"
            "&date_from=2026-01-01&date_to=2026-01-31"
            "&search=Acme&page=1&limit=50"
        )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
        assert body["total"] == 1
        assert isinstance(body["data"], list)
        assert len(body["data"]) == 1

        first = body["data"][0]
        # Verify all expected aliased columns are present
        expected_keys = {
            "jute_mr_id", "mr_number", "jute_mr_date", "branch_id", "branch_name",
            "party_id", "party_name", "vehicle_no", "challan_no", "challan_date",
            "gross_weight", "net_weight", "actual_weight", "total_amount",
            "net_total", "status_id", "status_name",
        }
        assert expected_keys.issubset(set(first.keys()))
        assert first["jute_mr_id"] == 101
        assert first["mr_number"] == "ABC/FAC/JMR/25-26/00001"
        assert first["status_id"] == 3

    def test_happy_path_without_branch_and_search(self):
        """Should return 200 with empty data when no rows match; optional params omitted."""
        list_execute_result = MagicMock()
        list_execute_result.fetchall.return_value = []

        count_execute_result = MagicMock()
        count_execute_result.scalar.return_value = 0

        self._mock_session.execute.side_effect = [
            list_execute_result,
            count_execute_result,
        ]

        response = client.get(
            "/api/juteReports/mr-list"
            "?co_id=1&date_from=2026-01-01&date_to=2026-01-31"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["total"] == 0
