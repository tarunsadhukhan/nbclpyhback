"""
Tests for the dynamic report-menu tree endpoint.
GET /api/admin/PortalData/report_menu_tree?root_path=...

Returns menu_mst rows flagged report = 1 that descend from the page identified
by root_path. Used by report-type pages to build a menu -> submenu -> sub-submenu
selector. Independent of the left sidebar menu loading.
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.common.portal.menu import get_portal_token_payload

client = TestClient(app)

ENDPOINT = "/api/admin/PortalData/report_menu_tree"


def _override_token():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session

    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestReportMenuTree:
    def setup_method(self):
        app.dependency_overrides[get_portal_token_payload] = _override_token
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_portal_token_payload, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_missing_root_path_returns_422(self):
        response = client.get(ENDPOINT)
        assert response.status_code == 422

    def test_unknown_root_path_returns_empty(self):
        root_result = MagicMock()
        root_result.fetchone.return_value = None
        self.mock_session.execute.return_value = root_result

        response = client.get(f"{ENDPOINT}?root_path=does/not/exist")
        assert response.status_code == 200
        body = response.json()
        assert body == {"root_menu_id": None, "data": []}

    def test_success_returns_report_subtree(self):
        root_result = MagicMock()
        root_result.fetchone.return_value = (10,)

        tree_result = MagicMock()
        tree_result.fetchall.return_value = [
            _mock_row(
                {
                    "menu_id": 799,
                    "menu_name": "Jute Purchase Report 1",
                    "menu_path": "jutereport/rep1",
                    "menu_parent_id": 10,
                    "order_by": 30,
                }
            ),
            _mock_row(
                {
                    "menu_id": 805,
                    "menu_name": "Jute Purchase sub repo1",
                    "menu_path": "jutereport/subrep1",
                    "menu_parent_id": 799,
                    "order_by": 30,
                }
            ),
            _mock_row(
                {
                    "menu_id": 804,
                    "menu_name": "Jute Purchase Report 2",
                    "menu_path": "jutereport/rep2",
                    "menu_parent_id": 10,
                    "order_by": 30,
                }
            ),
        ]
        # First execute() resolves the root menu_id, second fetches the subtree.
        self.mock_session.execute.side_effect = [root_result, tree_result]

        response = client.get(f"{ENDPOINT}?root_path=jutePurchase/reports")
        assert response.status_code == 200
        body = response.json()
        assert body["root_menu_id"] == 10
        assert len(body["data"]) == 3
        ids = [r["menu_id"] for r in body["data"]]
        assert ids == [799, 805, 804]
        # The sub-submenu node nests under report 1.
        sub = next(r for r in body["data"] if r["menu_id"] == 805)
        assert sub["menu_parent_id"] == 799
