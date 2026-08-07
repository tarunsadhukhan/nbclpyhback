"""
Tests for HRMS Employee endpoints.
Tests for src/hrms/employee.py
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


class TestEmployeeEndpoints:
    """Tests for HRMS Employee API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI dependencies for all endpoint tests."""
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── employee_list ────────────────────────────────────────────────

    def test_employee_list_success(self):
        """Should return employee list for valid co_id and branch_id."""
        emp_row = _mock_row({
            "eb_id": 1,
            "first_name": "John",
            "last_name": "Doe",
            "emp_code": "E001",
            "sub_dept_name": "Engineering",
            "designation_name": "Developer",
            "status_id": 21,
        })
        count_row = _mock_row({"total": 1})
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [emp_row],
        ]
        self._mock_session.execute.return_value.fetchone.return_value = count_row

        response = client.get("/api/hrms/employee_list?co_id=1&branch_id=10")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body

    def test_employee_list_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/employee_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_employee_list_missing_branch_id(self):
        """Should return 400 when branch_id is missing."""
        response = client.get("/api/hrms/employee_list?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ── employee_create_setup ────────────────────────────────────────

    def test_employee_create_setup_success(self):
        """Should return setup dropdown data."""
        bg_row = _mock_row({"source": "blood_groups", "id": 1, "name": "A+"})
        dept_row = _mock_row({"source": "sub_departments", "id": 10, "name": "Engineering (Tech)"})
        reporting_row = _mock_row({"id": 2, "name": "Jane Smith", "emp_code": "E002"})

        self._mock_session.execute.return_value.fetchall.side_effect = [
            [bg_row, dept_row],
            [reporting_row],
        ]

        response = client.get("/api/hrms/employee_create_setup?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body

    def test_employee_create_setup_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/employee_create_setup")
        assert response.status_code == 400

    # ── get_designations_by_branch ───────────────────────────────────

    def test_get_designations_by_branch_success(self):
        """Should return designation list for a given branch."""
        desig_row = _mock_row({"designation_id": 5, "desig": "Manager"})
        self._mock_session.execute.return_value.fetchall.return_value = [desig_row]

        response = client.get("/api/hrms/get_designations_by_branch?co_id=1&branch_id=10")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["label"] == "Manager"
        assert body["data"][0]["value"] == "5"

    def test_get_designations_by_branch_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/get_designations_by_branch?branch_id=10")
        assert response.status_code == 400

    def test_get_designations_by_branch_missing_branch_id(self):
        """Should return 400 when branch_id is missing."""
        response = client.get("/api/hrms/get_designations_by_branch?co_id=1")
        assert response.status_code == 400

    # ── employee_create ──────────────────────────────────────────────

    def test_employee_create_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.post("/api/hrms/employee_create", json={"first_name": "John"})
        assert response.status_code == 400

    def test_employee_create_missing_branch_id(self):
        """Should return 400 when branch_id is missing."""
        response = client.post("/api/hrms/employee_create?co_id=1", json={"first_name": "John"})
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ── employee_by_id ──────────────────────────────────────────────

    def test_employee_by_id_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/employee_by_id/1")
        assert response.status_code == 400

    def test_employee_by_id_missing_branch_id(self):
        """Should return 400 when branch_id is missing."""
        response = client.get("/api/hrms/employee_by_id/1?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # ── employee_section_save ───────────────────────────────────────

    def test_employee_section_save_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.post("/api/hrms/employee_section_save", json={
            "eb_id": 1,
            "section": "contact",
            "data": {"mobile_no": "9876543210"},
        })
        assert response.status_code == 400

    # ── employee_progress ───────────────────────────────────────────

    def test_employee_progress_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/employee_progress/1")
        assert response.status_code == 400

    def test_employee_progress_missing_branch_id(self):
        """Should return 400 when branch_id is missing."""
        response = client.get("/api/hrms/employee_progress/1?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()


class TestPaySchemeEndpoints:
    """Tests for HRMS Pay Scheme API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── pay_scheme_list ──────────────────────────────────────────────

    def test_pay_scheme_list_success(self):
        """Should return pay scheme list for valid co_id."""
        row = _mock_row({"id": 1, "code": "PS001", "name": "Basic Scheme", "type": 0, "status_id": 1})
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get("/api/hrms/pay_scheme_list?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body

    def test_pay_scheme_list_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/pay_scheme_list")
        assert response.status_code == 400

    # ── pay_scheme_by_id ─────────────────────────────────────────────

    def test_pay_scheme_by_id_not_found(self):
        """Should return 404 when scheme doesn't exist."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/hrms/pay_scheme_by_id/999?co_id=1")
        assert response.status_code == 404

    def test_pay_scheme_by_id_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/pay_scheme_by_id/1")
        assert response.status_code == 400

    # ── pay_scheme_create_setup ──────────────────────────────────────

    def test_pay_scheme_create_setup_success(self):
        """Should return component types grouped by category."""
        comp_row = _mock_row({"id": 1, "code": "BASIC", "name": "Basic", "type": 1})
        self._mock_session.execute.return_value.fetchall.return_value = [comp_row]

        response = client.get("/api/hrms/pay_scheme_create_setup?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        data = body["data"]
        assert "earnings" in data
        assert "deductions" in data

    def test_pay_scheme_create_setup_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/pay_scheme_create_setup")
        assert response.status_code == 400

    # ── pay_scheme_create ────────────────────────────────────────────

    def test_pay_scheme_create_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.post("/api/hrms/pay_scheme_create", json={"code": "PS1", "name": "Test"})
        assert response.status_code == 400

    # ── pay_scheme_update ────────────────────────────────────────────

    def test_pay_scheme_update_not_found(self):
        """Should return 404 when scheme doesn't exist."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put("/api/hrms/pay_scheme_update/999?co_id=1", json={"name": "Updated"})
        assert response.status_code == 404

    def test_pay_scheme_update_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.put("/api/hrms/pay_scheme_update/1", json={"name": "Updated"})
        assert response.status_code == 400


class TestPayParamEndpoints:
    """Tests for HRMS Pay Period / Pay Param API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── pay_param_list ───────────────────────────────────────────────

    def test_pay_param_list_success(self):
        """Should return pay period list for valid co_id."""
        row = _mock_row({"id": 1, "from_date": "2025-01-01", "to_date": "2025-01-31", "status_id": 1})
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get("/api/hrms/pay_param_list?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body

    def test_pay_param_list_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/pay_param_list")
        assert response.status_code == 400


class TestEmployeePhotoEndpoints:
    """Tests for HRMS Employee Photo API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── employee_photo_upload ────────────────────────────────────────

    def test_photo_upload_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.post(
            "/api/hrms/employee_photo_upload",
            data={"eb_id": "1"},
            files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0test", "image/jpeg")},
        )
        assert response.status_code == 400

    def test_photo_upload_invalid_type(self):
        """Should return 400 for non-image file types."""
        response = client.post(
            "/api/hrms/employee_photo_upload?co_id=1",
            data={"eb_id": "1"},
            files={"file": ("doc.pdf", b"pdf content", "application/pdf")},
        )
        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]

    def test_photo_upload_success(self):
        """Should update personal details row with photo data."""
        response = client.post(
            "/api/hrms/employee_photo_upload?co_id=1",
            data={"eb_id": "42"},
            files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0testdata", "image/jpeg")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["eb_id"] == 42
        self._mock_session.commit.assert_called_once()

    # ── employee_photo (GET) ─────────────────────────────────────────

    def test_photo_get_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/employee_photo/1")
        assert response.status_code == 400

    def test_photo_get_not_found(self):
        """Should return 404 when no photo exists for employee."""
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.get("/api/hrms/employee_photo/999?co_id=1")
        assert response.status_code == 404

    def test_photo_get_success_jpeg(self):
        """Should return image/jpeg response for jpeg photo."""
        photo_bytes = b"\xff\xd8\xff\xe0test-image-data"
        row = _mock_row({
            "eb_id": 42,
            "face_image": photo_bytes,
            "file_extension": "jpg",
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/hrms/employee_photo/42?co_id=1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == photo_bytes

    def test_photo_get_success_png(self):
        """Should return image/png response for png photo."""
        photo_bytes = b"\x89PNG\r\n\x1a\ntest-png"
        row = _mock_row({
            "eb_id": 42,
            "face_image": photo_bytes,
            "file_extension": "png",
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/hrms/employee_photo/42?co_id=1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    # ── employee_photo (DELETE) ──────────────────────────────────────

    def test_photo_delete_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.delete("/api/hrms/employee_photo/1")
        assert response.status_code == 400

    def test_photo_delete_success(self):
        """Should delete photo and return success message."""
        response = client.delete("/api/hrms/employee_photo/10?co_id=1")
        assert response.status_code == 200
        assert "deleted" in response.json()["data"]["message"].lower()
        self._mock_session.commit.assert_called_once()

    # ── pay_param_create_setup ───────────────────────────────────────

    def test_pay_param_create_setup_success(self):
        """Should return schemes and branches for dropdowns."""
        scheme_row = _mock_row({"id": 1, "name": "Basic"})
        branch_row = _mock_row({"branch_id": 1, "branch_name": "Main"})
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [scheme_row],
            [branch_row],
        ]

        response = client.get("/api/hrms/pay_param_create_setup?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        data = body["data"]
        assert "pay_schemes" in data
        assert "branches" in data

    def test_pay_param_create_setup_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.get("/api/hrms/pay_param_create_setup")
        assert response.status_code == 400

    # ── pay_param_create ─────────────────────────────────────────────

    def test_pay_param_create_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.post("/api/hrms/pay_param_create", json={
            "from_date": "2025-01-01",
            "to_date": "2025-01-31",
            "payscheme_id": 1,
        })
        assert response.status_code == 400

    # ── pay_param_update ─────────────────────────────────────────────

    def test_pay_param_update_not_found(self):
        """Should return 404 when period doesn't exist."""
        self._mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.put("/api/hrms/pay_param_update/999?co_id=1", json={
            "from_date": "2025-01-01",
            "to_date": "2025-01-31",
        })
        assert response.status_code == 404

    def test_pay_param_update_missing_co_id(self):
        """Should return 400 when co_id is missing."""
        response = client.put("/api/hrms/pay_param_update/1", json={"from_date": "2025-01-01"})
        assert response.status_code == 400
