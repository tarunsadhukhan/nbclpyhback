"""
Tests for Portal Admin User Management endpoints.
Tests for src/common/ctrldskAdmin/users.py — portal user creation endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.authorization.utils import verify_access_token

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestGetOrgsDropdownPortalUser:
    """Tests for GET /api/ctrldskAdmin/get_orgs_dropdown_portal_user"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override auth dependency."""
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}
        yield
        app.dependency_overrides.clear()

    @patch("src.common.ctrldskAdmin.users.default_engine")
    def test_returns_org_list(self, mock_engine):
        """Should return list of active organisations."""
        mock_session = MagicMock()
        mock_row = _mock_row({
            "con_org_id": 1,
            "con_org_shortname": "dev3",
            "con_org_name": "Dev Organisation"
        })
        mock_session.execute.return_value.fetchall.return_value = [mock_row]
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("src.common.ctrldskAdmin.users.Session", return_value=mock_session):
            response = client.get("/api/ctrldskAdmin/get_orgs_dropdown_portal_user")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["con_org_shortname"] == "dev3"


class TestCreatePortalAdminUser:
    """Tests for POST /api/ctrldskAdmin/create_portal_admin_user"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override auth dependency."""
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}
        yield
        app.dependency_overrides.clear()

    @patch("src.common.ctrldskAdmin.users.get_password_hash")
    @patch("src.common.ctrldskAdmin.users.Session")
    def test_create_user_success(self, mock_session_cls, mock_hash):
        """Should create user, role, and menu mappings successfully."""
        mock_hash.return_value = "hashed_password"
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session

        # Mock org query
        mock_org = MagicMock()
        mock_org.con_org_id = 1
        mock_org.con_org_shortname = "dev3"
        mock_org.active = 1

        # Mock no existing user (duplicate check)
        # Mock no existing superadmin role
        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_org,  # org exists
            None,      # no duplicate user
            None,      # no existing superadmin role
        ]

        # Mock menu list for all menus
        mock_menu = MagicMock()
        mock_menu.con_menu_id = 1
        mock_session.query.return_value.filter.return_value.all.return_value = [mock_menu]

        # Mock flush to set IDs
        def set_role_id(*args, **kwargs):
            pass
        mock_session.flush.side_effect = set_role_id

        payload = {
            "org_id": 1,
            "email": "admin@test.com",
            "name": "Admin User",
            "password": "vowjute@1234"
        }

        response = client.post("/api/ctrldskAdmin/create_portal_admin_user", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Portal admin user created successfully"
        assert "data" in body
        mock_session.commit.assert_called_once()

    @patch("src.common.ctrldskAdmin.users.Session")
    def test_create_user_missing_org(self, mock_session_cls):
        """Should return 404 when org doesn't exist."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session

        # Mock org not found
        mock_session.query.return_value.filter.return_value.first.return_value = None

        payload = {
            "org_id": 999,
            "email": "admin@test.com",
            "name": "Admin User",
            "password": "vowjute@1234"
        }

        response = client.post("/api/ctrldskAdmin/create_portal_admin_user", json=payload)

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("src.common.ctrldskAdmin.users.Session")
    def test_create_user_duplicate_email(self, mock_session_cls):
        """Should return 400 when email already exists for the org."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session

        # Mock org found, then duplicate user found
        mock_org = MagicMock()
        mock_org.con_org_id = 1
        mock_org.active = 1

        mock_existing_user = MagicMock()
        mock_existing_user.con_user_id = 5

        mock_session.query.return_value.filter.return_value.first.side_effect = [
            mock_org,           # org found
            mock_existing_user  # duplicate user
        ]

        payload = {
            "org_id": 1,
            "email": "existing@test.com",
            "name": "Admin User",
            "password": "vowjute@1234"
        }

        response = client.post("/api/ctrldskAdmin/create_portal_admin_user", json=payload)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_user_missing_email(self):
        """Should return 422 when email is missing from payload."""
        payload = {
            "org_id": 1,
            "name": "Admin User"
        }

        response = client.post("/api/ctrldskAdmin/create_portal_admin_user", json=payload)

        assert response.status_code == 422

    def test_create_user_default_password_used(self):
        """Should accept payload without password and apply default."""
        from src.common.ctrldskAdmin.users import CreatePortalAdminUser

        model = CreatePortalAdminUser(
            org_id=1,
            email="admin@test.com",
            name="Admin User"
            # password omitted — should use default
        )
        assert model.password == "vowjute@1234"


class TestGetPortalAdminUsers:
    """Tests for GET /api/ctrldskAdmin/get_portal_admin_users"""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override auth dependency."""
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}
        yield
        app.dependency_overrides.clear()

    @patch("src.common.ctrldskAdmin.users.Session")
    def test_list_users_success(self, mock_session_cls):
        """Should return paginated list of portal admin users."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session

        # Mock count
        mock_session.execute.return_value.scalar.return_value = 1

        # Mock data rows
        mock_row = _mock_row({
            "con_user_id": 1,
            "con_user_name": "Admin",
            "con_user_login_email_id": "admin@test.com",
            "con_org_id": 1,
            "con_org_shortname": "dev3",
            "con_org_name": "Dev Org",
            "active": 1,
            "con_role_id": 10,
            "con_role_name": "superadmin"
        })
        mock_session.execute.return_value.fetchall.return_value = [mock_row]

        response = client.get("/api/ctrldskAdmin/get_portal_admin_users?page=1&limit=10")

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body

    @patch("src.common.ctrldskAdmin.users.Session")
    def test_list_users_with_search(self, mock_session_cls):
        """Should accept search parameter."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session_cls.return_value = mock_session

        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.fetchall.return_value = []

        response = client.get(
            "/api/ctrldskAdmin/get_portal_admin_users?page=1&limit=10&search=admin"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["total"] == 0
