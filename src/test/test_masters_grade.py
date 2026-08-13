"""Tests for Grade Master API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from sqlalchemy import text
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.grade import get_grade_list_query, get_grade_by_id_query

client = TestClient(app)

PREFIX = "/api/hrmsMasters"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    row.cnt = mapping.get("cnt", 0)
    return row


# ─── Query function tests ───────────────────────────────────────────


class TestGradeQueries:
    """Tests for grade SQL query functions."""

    def test_list_query_returns_text(self):
        assert isinstance(get_grade_list_query(), type(text("")))

    def test_list_query_has_search_bind(self):
        assert ":search" in str(get_grade_list_query())

    def test_list_query_type_filter_only_when_requested(self):
        assert ":grade_type" not in str(get_grade_list_query())
        assert ":grade_type" in str(get_grade_list_query(grade_type=1))

    def test_by_id_query_has_bind(self):
        assert ":grade_id" in str(get_grade_by_id_query())


class _GradeEndpointBase:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


# ─── GET /get_grade_table ───────────────────────────────────────────


class TestGetGradeTable(_GradeEndpointBase):
    """Tests for GET /get_grade_table."""

    def test_success_maps_grade_type_name(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"grade_id": 1, "grade_code": "G1", "grade_name": "Grade 1", "grade_type": 0}),
            _mock_row({"grade_id": 2, "grade_code": "S1", "grade_name": "Staff 1", "grade_type": 1}),
        ]

        response = client.get(f"{PREFIX}/get_grade_table")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["data"][0]["grade_type_name"] == "Worker"
        assert data["data"][1]["grade_type_name"] == "Staff"

    def test_empty_result(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(f"{PREFIX}/get_grade_table")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    def test_pagination_limits(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"grade_id": i, "grade_code": f"G{i}", "grade_name": f"Grade {i}", "grade_type": 0})
            for i in range(5)
        ]

        response = client.get(f"{PREFIX}/get_grade_table?page=1&limit=2")
        assert response.status_code == 200
        assert response.json()["total"] == 5
        assert len(response.json()["data"]) == 2

    def test_invalid_grade_type_filter_returns_400(self):
        response = client.get(f"{PREFIX}/get_grade_table?grade_type=7")
        assert response.status_code == 400


# ─── GET /get_grade_by_id ───────────────────────────────────────────


class TestGetGradeById(_GradeEndpointBase):
    """Tests for GET /get_grade_by_id/{id}."""

    def test_not_found_returns_404(self):
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get(f"{PREFIX}/get_grade_by_id/999")
        assert response.status_code == 404

    def test_found_returns_data(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"grade_id": 1, "grade_code": "A", "grade_name": "Grade A", "grade_type": 1}
        )

        response = client.get(f"{PREFIX}/get_grade_by_id/1")
        assert response.status_code == 200
        assert response.json()["data"]["grade_type_name"] == "Staff"


# ─── POST /grade_create ─────────────────────────────────────────────


class TestGradeCreate(_GradeEndpointBase):
    """Tests for POST /grade_create."""

    def test_missing_code_returns_400(self):
        response = client.post(f"{PREFIX}/grade_create", json={"grade_name": "Grade A"})
        assert response.status_code == 400

    def test_missing_name_returns_400(self):
        response = client.post(f"{PREFIX}/grade_create", json={"grade_code": "A"})
        assert response.status_code == 400

    def test_code_longer_than_4_returns_400(self):
        response = client.post(f"{PREFIX}/grade_create", json={
            "grade_code": "TOOLONG",
            "grade_name": "Grade A",
        })
        assert response.status_code == 400
        assert "4 characters" in response.json()["detail"]

    def test_invalid_grade_type_returns_400(self):
        response = client.post(f"{PREFIX}/grade_create", json={
            "grade_code": "A",
            "grade_name": "Grade A",
            "grade_type": 5,
        })
        assert response.status_code == 400

    def test_duplicate_code_returns_400(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 1})

        response = client.post(f"{PREFIX}/grade_create", json={
            "grade_code": "A",
            "grade_name": "Grade A",
            "grade_type": 0,
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_success_returns_id(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})

        response = client.post(f"{PREFIX}/grade_create", json={
            "grade_code": "A",
            "grade_name": "Grade A",
            "grade_type": 1,
        })
        assert response.status_code == 200
        assert self._mock_session.add.called
        assert self._mock_session.commit.called


# ─── PUT /grade_edit ────────────────────────────────────────────────


class TestGradeEdit(_GradeEndpointBase):
    """Tests for PUT /grade_edit/{id}."""

    def test_missing_code_returns_400(self):
        response = client.put(f"{PREFIX}/grade_edit/1", json={"grade_name": "Grade A"})
        assert response.status_code == 400

    def test_not_found_returns_404(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put(f"{PREFIX}/grade_edit/999", json={
            "grade_code": "A",
            "grade_name": "Grade A",
        })
        assert response.status_code == 404

    def test_duplicate_on_edit_returns_400(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = MagicMock()
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 1})

        response = client.put(f"{PREFIX}/grade_edit/1", json={
            "grade_code": "A",
            "grade_name": "Grade A",
        })
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
