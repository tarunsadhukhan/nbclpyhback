"""Tests for Wages Quality Master API endpoints (production/qualitymaster)."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.masters.quality import get_quality_list_query, get_quality_by_id_query

client = TestClient(app)

PREFIX = "/api/productionMasters"

VALID = {"dept_id": 5, "quality_code": "Q1", "quality_desc": "Hessian", "quality_rate": "1.25", "conv_factor": "0.5"}


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    row.cnt = mapping.get("cnt", 0)
    return row


class TestQualityQueries:
    def test_list_query_has_search_bind(self):
        assert ":search" in str(get_quality_list_query())

    def test_by_id_query_has_bind(self):
        assert ":quality_id" in str(get_quality_by_id_query())


class _Base:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


class TestGetQualityTable(_Base):
    def test_pagination(self):
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"quality_id": i, "dept_id": 1, "dept_name": "JUTE", "quality_code": f"Q{i}",
                       "quality_desc": f"Quality {i}", "quality_rate": 1.0, "conv_factor": 1.0})
            for i in range(5)
        ]
        response = client.get(f"{PREFIX}/get_quality_table?page=1&limit=2")
        assert response.status_code == 200
        assert response.json()["total"] == 5
        assert len(response.json()["data"]) == 2


class TestGetQualityById(_Base):
    def test_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        assert client.get(f"{PREFIX}/get_quality_by_id/99").status_code == 404


class TestQualityCreate(_Base):
    def test_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})

        def _refresh(obj):
            obj.quality_id = 7

        self._mock_session.refresh.side_effect = _refresh
        response = client.post(f"{PREFIX}/quality_create", json=VALID)
        assert response.status_code == 200, response.text
        assert response.json()["quality_id"] == 7
        added = self._mock_session.add.call_args[0][0]
        assert added.dept_id == 5 and str(added.quality_rate) == "1.25"
        assert added.active == 1  # default when omitted
        assert added.status_id == 1  # created as Open

    def test_inactive_flag(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})
        self._mock_session.refresh.side_effect = lambda obj: setattr(obj, "quality_id", 8)
        response = client.post(f"{PREFIX}/quality_create", json={**VALID, "active": False})
        assert response.status_code == 200, response.text
        assert self._mock_session.add.call_args[0][0].active == 0

    def test_bad_active(self):
        response = client.post(f"{PREFIX}/quality_create", json={**VALID, "active": 5})
        assert response.status_code == 400

    def test_missing_dept(self):
        response = client.post(f"{PREFIX}/quality_create", json={**VALID, "dept_id": ""})
        assert response.status_code == 400
        assert "Department" in response.json()["detail"]

    def test_code_too_long(self):
        response = client.post(f"{PREFIX}/quality_create", json={**VALID, "quality_code": "X" * 11})
        assert response.status_code == 400

    def test_rate_out_of_range(self):
        response = client.post(f"{PREFIX}/quality_create", json={**VALID, "quality_rate": "1000"})
        assert response.status_code == 400

    def test_duplicate(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 1})
        response = client.post(f"{PREFIX}/quality_create", json=VALID)
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"]


class TestQualityEdit(_Base):
    def test_not_found(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        assert client.put(f"{PREFIX}/quality_edit/1", json=VALID).status_code == 404

    def test_success(self):
        existing = MagicMock(status_id=1)
        self._mock_session.query.return_value.filter.return_value.first.return_value = existing
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row({"cnt": 0})
        response = client.put(f"{PREFIX}/quality_edit/1", json=VALID)
        assert response.status_code == 200, response.text
        assert existing.quality_code == "Q1"
        assert existing.dept_id == 5

    def test_approved_is_read_only(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = MagicMock(status_id=3)
        response = client.put(f"{PREFIX}/quality_edit/1", json=VALID)
        assert response.status_code == 400
        assert "Approved" in response.json()["detail"]


class TestQualityStatus(_Base):
    def _existing(self, status_id):
        row = MagicMock(status_id=status_id)
        self._mock_session.query.return_value.filter.return_value.first.return_value = row
        return row

    @pytest.mark.parametrize("action,from_status,to_status", [
        ("approve", 1, 3), ("reject", 1, 4), ("reopen", 4, 1), ("approve", None, 3),
    ])
    def test_valid_transitions(self, action, from_status, to_status):
        row = self._existing(from_status)
        response = client.put(f"{PREFIX}/quality_status/1", json={"action": action})
        assert response.status_code == 200, response.text
        assert row.status_id == to_status
        assert response.json()["status_id"] == to_status

    @pytest.mark.parametrize("action,from_status", [
        ("approve", 3), ("reject", 4), ("reopen", 1), ("reopen", 3),
    ])
    def test_invalid_transitions(self, action, from_status):
        row = self._existing(from_status)
        response = client.put(f"{PREFIX}/quality_status/1", json={"action": action})
        assert response.status_code == 400
        assert row.status_id == from_status

    def test_bad_action(self):
        self._existing(1)
        assert client.put(f"{PREFIX}/quality_status/1", json={"action": "close"}).status_code == 400

    def test_not_found(self):
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        assert client.put(f"{PREFIX}/quality_status/1", json={"action": "approve"}).status_code == 404
