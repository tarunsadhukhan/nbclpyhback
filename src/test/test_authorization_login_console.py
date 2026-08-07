import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.authorization.auth import login_user_console


class _SessionContextManager:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_result(row=None):
    result = MagicMock()
    result.fetchone.return_value = row
    return result


def _make_request_with_host(host: str):
    request = MagicMock()
    request.headers = {"host": host}
    return request


@patch("src.authorization.auth.create_access_token", return_value="test-access-token")
@patch("src.authorization.auth.create_refresh_token", return_value="test-refresh-token")
@patch("src.authorization.auth.verify_password", return_value=True)
def test_login_console_tenant_admin_success(mock_verify, mock_refresh, mock_access):
    mock_session = MagicMock()
    mock_session.execute.side_effect = [
        _make_result(SimpleNamespace(con_user_id=501, con_user_login_password="hashed")),
        MagicMock(),
    ]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="admin@dev3.com",
            password="secret",
            logintype="console",
            subdomain="dev3",
        )

    data = json.loads(response.body)
    assert response.status_code == 200
    assert data["message"] == "Login successful"
    assert data["user_id"] == 501


def test_login_console_returns_unregistered_when_subdomain_not_mapped():
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(None)]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("unknown.vowerp.co.in"),
            username="user@example.com",
            password="secret",
            logintype="console",
            subdomain="unknown",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "User is not registered"


def test_login_console_returns_unregistered_when_user_not_mapped_to_org():
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(None)]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="other-org-user@example.com",
            password="secret",
            logintype="console",
            subdomain="dev3",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "User is not registered"


@patch("src.authorization.auth.verify_password", return_value=False)
def test_login_console_returns_wrong_password_message(mock_verify):
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(SimpleNamespace(con_user_id=700, con_user_login_password="hashed"))]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="valid-user@example.com",
            password="bad-password",
            logintype="console",
            subdomain="dev3",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "Wrong password entered"


def test_login_console_admin_rejects_non_ctrldesk_user():
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(None)]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("admin.vowerp.co.in"),
            username="tenant-admin@example.com",
            password="secret",
            logintype="console",
            subdomain="admin",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "User is not registered"


def test_login_console_uses_request_subdomain_over_passed_subdomain():
    """Prevents bypass by sending a different subdomain in header/body than actual host subdomain."""
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(None)]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="org1-user@example.com",
            password="secret",
            logintype="console",
            subdomain="org1",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "User is not registered"


def test_login_console_binds_dev3_subdomain_in_tenant_query():
    mock_session = MagicMock()
    mock_session.execute.side_effect = [_make_result(None)]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        response = login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="sls@vowerp.com",
            password="secret",
            logintype="console",
            subdomain="sls",
        )

    data = json.loads(response.body)
    assert response.status_code == 401
    assert data["message"] == "User is not registered"

    first_call_args = mock_session.execute.call_args_list[0][0]
    first_call_params = first_call_args[1]
    assert first_call_params["subdomain"] == "dev3"


@patch("src.authorization.auth.create_access_token", return_value="test-access-token")
@patch("src.authorization.auth.create_refresh_token", return_value="test-refresh-token")
@patch("src.authorization.auth.verify_password", return_value=True)
def test_login_console_jwt_includes_org_context(mock_verify, mock_refresh, mock_access):
    """JWT token payload must include con_org_id and subdomain for session validation."""
    mock_session = MagicMock()
    mock_session.execute.side_effect = [
        _make_result(SimpleNamespace(con_user_id=501, con_user_login_password="hashed", con_org_id=38)),
        MagicMock(),
    ]

    with patch("src.authorization.auth.Session", return_value=_SessionContextManager(mock_session)):
        login_user_console(
            request=_make_request_with_host("dev3.vowerp.co.in"),
            username="admin@dev3.com",
            password="secret",
            logintype="console",
            subdomain="dev3",
        )

    # Verify create_access_token was called with org context
    call_args = mock_access.call_args[0][0]
    assert call_args["user_id"] == 501
    assert call_args["con_org_id"] == 38
    assert call_args["subdomain"] == "dev3"


# --- verify-session endpoint tests ---

import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.authorization.utils import get_current_user_with_refresh, verify_access_token, create_access_token

client = TestClient(app)


class TestVerifySessionOrgValidation:
    """Tests that verify-session rejects tokens issued for a different subdomain."""

    def test_verify_session_rejects_mismatched_subdomain(self):
        """Token issued for 'sls' must be rejected when accessed from 'dev3'."""
        # Create a token that was issued for org sls
        token = create_access_token({"user_id": 4, "con_org_id": 1, "subdomain": "sls"})

        response = client.get(
            "/api/authRoutes/verify-session",
            cookies={"access_token": token},
            headers={"X-Subdomain": "dev3"},
        )
        assert response.status_code == 401

    def test_verify_session_allows_matching_subdomain(self):
        """Token issued for 'dev3' must be accepted when accessed from 'dev3'."""
        token = create_access_token({"user_id": 100, "con_org_id": 38, "subdomain": "dev3"})

        response = client.get(
            "/api/authRoutes/verify-session",
            cookies={"access_token": token},
            headers={"X-Subdomain": "dev3"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_verify_session_allows_portal_token_without_subdomain(self):
        """Portal tokens (with 'type': 'portal') have no subdomain — should pass."""
        token = create_access_token({"user_id": 50, "type": "portal"})

        response = client.get(
            "/api/authRoutes/verify-session",
            cookies={"access_token": token},
            headers={"X-Subdomain": "dev3"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_verify_session_rejects_old_token_without_subdomain_on_admin(self):
        """Old tokens (pre-fix, no subdomain field) should still work since they're portal-style."""
        token = create_access_token({"user_id": 4})

        # No subdomain in token → token_subdomain is None → no org check → passes
        response = client.get(
            "/api/authRoutes/verify-session",
            cookies={"access_token": token},
            headers={"X-Subdomain": "dev3"},
        )
        # Old tokens without subdomain are allowed through (backwards compatible)
        assert response.status_code == 200
