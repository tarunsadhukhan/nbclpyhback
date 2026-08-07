# src/test/test_password_reset_change.py
"""
Tests for the password reset (admin) and self-service change-password endpoints.

Covers:
- POST /api/admin/PortalData/reset_user_password
    * success (resets to default, clears refresh_token, records acting admin)
    * missing user_id (422 from pydantic) / invalid user_id (400)
    * user not found (404)
- POST /api/authRoutes/change-password
    * success for a portal token
    * current password wrong (400)
    * new/confirm mismatch (400)
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh


client = TestClient(app)


def _override_auth_factory(token_data):
    def _override():
        return token_data
    return _override


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


class _SessionContextManager:
    """Mimics `with Session(engine) as session:`."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


# ---------------------------------------------------------------------------
# reset_user_password (admin) endpoint tests
# ---------------------------------------------------------------------------

class TestResetUserPassword:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth_factory({"user_id": 99})
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    @patch("src.common.portal.users.get_password_hash", return_value="hashed-default")
    def test_reset_user_password_success(self, mock_hash):
        target_user = MagicMock()
        self.mock_session.query.return_value.filter.return_value.first.return_value = target_user

        response = client.post(
            "/api/admin/PortalData/reset_user_password",
            json={"user_id": 42},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data"]["message"] == "Password reset to default"
        assert body["data"]["default_password"] == "Vow@123"

        # Target user mutated correctly
        assert target_user.password == "hashed-default"
        assert target_user.refresh_token is None
        assert target_user.updated_by_con_user == 99
        self.mock_session.commit.assert_called_once()

    def test_reset_user_password_user_not_found(self):
        self.mock_session.query.return_value.filter.return_value.first.return_value = None

        response = client.post(
            "/api/admin/PortalData/reset_user_password",
            json={"user_id": 9999},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_reset_user_password_missing_user_id(self):
        # Pydantic rejects missing required field with 422
        response = client.post(
            "/api/admin/PortalData/reset_user_password",
            json={},
        )
        assert response.status_code == 422

    def test_reset_user_password_invalid_user_id(self):
        # Non-coercible user_id -> pydantic 422 (string that isn't an int)
        response = client.post(
            "/api/admin/PortalData/reset_user_password",
            json={"user_id": "abc"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# change-password (self-service) endpoint tests
# ---------------------------------------------------------------------------

class TestChangePasswordPortal:

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)

    def _override_portal_auth(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth_factory(
            {"user_id": 7, "type": "portal"}
        )

    @patch("src.authorization.routers.get_password_hash", return_value="new-hash")
    @patch("src.authorization.routers.verify_password", return_value=True)
    @patch("src.authorization.routers.create_engine")
    @patch("src.authorization.routers.Session")
    @patch("src.authorization.routers.extract_subdomain_from_request", return_value="dev3")
    def test_change_password_portal_success(
        self, mock_sub, mock_session_cls, mock_engine, mock_verify, mock_hash
    ):
        self._override_portal_auth()

        mock_session = MagicMock()
        # SELECT returns a row with user_id + password
        row = MagicMock()
        row.password = "old-hash"
        mock_session.execute.return_value.fetchone.return_value = row
        mock_session_cls.return_value = _SessionContextManager(mock_session)

        response = client.post(
            "/api/authRoutes/change-password",
            json={
                "current_password": "OldPass1",
                "new_password": "NewPass1",
                "confirm_password": "NewPass1",
            },
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["message"] == "Password changed successfully"
        mock_session.commit.assert_called_once()

    @patch("src.authorization.routers.verify_password", return_value=False)
    @patch("src.authorization.routers.create_engine")
    @patch("src.authorization.routers.Session")
    @patch("src.authorization.routers.extract_subdomain_from_request", return_value="dev3")
    def test_change_password_current_wrong(
        self, mock_sub, mock_session_cls, mock_engine, mock_verify
    ):
        self._override_portal_auth()

        mock_session = MagicMock()
        row = MagicMock()
        row.password = "old-hash"
        mock_session.execute.return_value.fetchone.return_value = row
        mock_session_cls.return_value = _SessionContextManager(mock_session)

        response = client.post(
            "/api/authRoutes/change-password",
            json={
                "current_password": "WrongPass",
                "new_password": "NewPass1",
                "confirm_password": "NewPass1",
            },
        )

        assert response.status_code == 400
        assert "current password is incorrect" in response.json()["detail"].lower()

    def test_change_password_mismatch(self):
        self._override_portal_auth()

        response = client.post(
            "/api/authRoutes/change-password",
            json={
                "current_password": "OldPass1",
                "new_password": "NewPass1",
                "confirm_password": "Different1",
            },
        )

        assert response.status_code == 400
        assert "do not match" in response.json()["detail"].lower()
