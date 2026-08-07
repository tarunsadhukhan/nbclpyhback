"""Tests for Beaming Quality Master endpoints (Page A).

Tests for src/juteProduction/beaming_masters.py (prefix /api/beamingMasters).

Portal persona: DB + auth are mocked (no real DB). The router imports
get_tenant_db / get_current_user_with_refresh into its own namespace; FastAPI
resolves them via Depends, so we override them through app.dependency_overrides
keyed by those exact symbols.

Covered:
  * happy path (create_setup + create)
  * missing co_id -> 400
  * duplicate-guard on (co_id, item_id, bm_quality_code) -> 400
  * composite create (is_composite=1, >=2 components -> parent ends=SUM, _dtl inserts) (§Q3)
  * composite create missing/short components -> 400 (§Q3)
  * bm_quality_detail returns the parent + nested components (§Q3)
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteProduction.beaming_masters import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestBmQualityCreateSetup:
    """GET /api/beamingMasters/bm_quality_create_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_items_and_yarns(self):
        item_rows = [
            _mock_row({"item_id": 10, "item_code": "JC-RED", "item_name": "Jute Cloth Red"}),
        ]
        yarn_rows = [
            _mock_row({
                "item_id": 50, "item_code": "8LB", "item_name": "8 LB Yarn",
                "jute_yarn_count": 8.0,
            }),
        ]
        exec_items = MagicMock()
        exec_items.fetchall.return_value = item_rows
        exec_yarns = MagicMock()
        exec_yarns.fetchall.return_value = yarn_rows
        self._mock_session.execute.side_effect = [exec_items, exec_yarns]

        response = client.get("/api/beamingMasters/bm_quality_create_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items"][0]["item_code"] == "JC-RED"
        assert data["yarns"][0]["jute_yarn_count"] == 8.0

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/beamingMasters/bm_quality_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestBmQualityList:
    """GET /api/beamingMasters/bm_quality_list"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_rows(self):
        rows = [
            _mock_row({
                "bm_quality_id": 1, "co_id": 1, "item_id": 10, "item_code": "JC-RED",
                "item_name": "Jute Cloth Red", "bm_quality_code": "272-13/272",
                "bm_quality_name": "Red", "ends": 272, "std_count": 13.0, "active": 1,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/beamingMasters/bm_quality_list?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["bm_quality_code"] == "272-13/272"

    def test_empty_results(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/beamingMasters/bm_quality_list?co_id=1")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/beamingMasters/bm_quality_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestBmQualityCreate:
    """POST /api/beamingMasters/bm_quality_create"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _payload(self):
        return {
            "co_id": 1,
            "item_id": 10,
            "bm_quality_code": "272-13/272",
            "bm_quality_name": "Red",
            "ends": 272,
            "std_count": 13.0,
        }

    def test_success_creates_row(self):
        # First execute = duplicate check -> None; second execute = insert.
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = None
        insert_exec = MagicMock()
        insert_exec.lastrowid = 99
        self._mock_session.execute.side_effect = [dup_exec, insert_exec]

        response = client.post("/api/beamingMasters/bm_quality_create", json=self._payload())

        assert response.status_code == 200
        assert response.json()["data"]["bm_quality_id"] == 99
        self._mock_session.commit.assert_called_once()

    def test_duplicate_returns_400(self):
        # Duplicate check returns a row -> 400 guard.
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = _mock_row({"bm_quality_id": 5})
        self._mock_session.execute.return_value = dup_exec

        response = client.post("/api/beamingMasters/bm_quality_create", json=self._payload())

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_blank_code_returns_400(self):
        payload = self._payload()
        payload["bm_quality_code"] = "   "
        response = client.post("/api/beamingMasters/bm_quality_create", json=payload)
        assert response.status_code == 400

    def _composite_payload(self):
        """Composite quality (is_composite=1): the real (ends, count) pairs live in
        `components` (>=2); parent ends/std_count/yarn_item_id are derived/NULL (§Q3)."""
        return {
            "co_id": 1,
            "item_id": 10,
            "bm_quality_code": "COMP-1",
            "bm_quality_name": "Composite Red",
            "is_composite": 1,
            "components": [
                {"component_no": 1, "ends": 120, "yarn_item_id": 50, "count": 8.0},
                {"component_no": 2, "ends": 160, "yarn_item_id": 51, "count": 10.0},
            ],
        }

    def test_composite_create_sums_ends_and_inserts_components(self):
        """is_composite=1 with 2 components -> parent ends = SUM(120+160)=280,
        std_count/yarn_item_id NULL, and one _dtl insert per component (§Q3)."""
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = None
        parent_insert = MagicMock()
        parent_insert.lastrowid = 77
        comp1_insert = MagicMock()
        comp2_insert = MagicMock()
        # Execute order: duplicate-check, parent INSERT, then one INSERT per component.
        self._mock_session.execute.side_effect = [
            dup_exec, parent_insert, comp1_insert, comp2_insert,
        ]

        response = client.post(
            "/api/beamingMasters/bm_quality_create", json=self._composite_payload()
        )

        assert response.status_code == 200
        assert response.json()["data"]["bm_quality_id"] == 77
        self._mock_session.commit.assert_called_once()

        # Parent INSERT (2nd execute) carries SUM(ends) and NULL std_count/yarn_item_id.
        parent_params = self._mock_session.execute.call_args_list[1].args[1]
        assert parent_params["ends"] == 280            # 120 + 160
        assert parent_params["std_count"] is None      # composite parent std_count NULL
        assert parent_params["yarn_item_id"] is None    # composite parent yarn_item_id NULL
        assert parent_params["is_composite"] == 1

        # Two component INSERTs (executes 3 and 4), bound to the new parent id.
        comp1_params = self._mock_session.execute.call_args_list[2].args[1]
        comp2_params = self._mock_session.execute.call_args_list[3].args[1]
        assert comp1_params["bm_quality_id"] == 77
        assert comp1_params["ends"] == 120
        assert comp1_params["count"] == 8.0
        assert comp2_params["ends"] == 160
        assert comp2_params["count"] == 10.0

    def test_composite_missing_components_returns_400(self):
        """is_composite=1 with no components -> 400 before any DB write (§Q3)."""
        payload = self._composite_payload()
        payload["components"] = None
        response = client.post("/api/beamingMasters/bm_quality_create", json=payload)
        assert response.status_code == 400
        assert "component" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_composite_single_component_returns_400(self):
        """is_composite=1 requires >=2 components -> a single component 400s (§Q3)."""
        payload = self._composite_payload()
        payload["components"] = [
            {"component_no": 1, "ends": 120, "yarn_item_id": 50, "count": 8.0},
        ]
        response = client.post("/api/beamingMasters/bm_quality_create", json=payload)
        assert response.status_code == 400
        assert "component" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


class TestBmQualityDetail:
    """GET /api/beamingMasters/bm_quality_detail/{id} (§Q3 edit-dialog source)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_composite_detail_returns_parent_and_components(self):
        """Returns the parent row plus its nested active components ordered by
        component_no (the edit dialog hydrates the composite grid from this)."""
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = _mock_row({
            "bm_quality_id": 77, "co_id": 1, "branch_id": 2, "item_id": 10,
            "bm_quality_code": "COMP-1", "bm_quality_name": "Composite Red",
            "ends": 280, "std_count": None, "yarn_item_id": None,
            "is_composite": 1, "active": 1,
        })
        comp_exec = MagicMock()
        comp_exec.fetchall.return_value = [
            _mock_row({
                "bm_quality_dtl_id": 1, "component_no": 1, "ends": 120,
                "yarn_item_id": 50, "count": 8.0,
            }),
            _mock_row({
                "bm_quality_dtl_id": 2, "component_no": 2, "ends": 160,
                "yarn_item_id": 51, "count": 10.0,
            }),
        ]
        # Execute order: parent fetch, then component fetch.
        self._mock_session.execute.side_effect = [parent_exec, comp_exec]

        response = client.get("/api/beamingMasters/bm_quality_detail/77?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["bm_quality_id"] == 77
        assert data["is_composite"] == 1
        assert data["ends"] == 280
        assert len(data["components"]) == 2
        assert data["components"][0]["component_no"] == 1
        assert data["components"][0]["ends"] == 120
        assert data["components"][1]["count"] == 10.0

    def test_simple_detail_returns_empty_components(self):
        """A simple (non-composite) quality has no _dtl rows -> components == []."""
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = _mock_row({
            "bm_quality_id": 5, "co_id": 1, "branch_id": 2, "item_id": 10,
            "bm_quality_code": "272-13/272", "bm_quality_name": "Red",
            "ends": 272, "std_count": 13.0, "yarn_item_id": 50,
            "is_composite": 0, "active": 1,
        })
        comp_exec = MagicMock()
        comp_exec.fetchall.return_value = []
        self._mock_session.execute.side_effect = [parent_exec, comp_exec]

        response = client.get("/api/beamingMasters/bm_quality_detail/5?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_composite"] == 0
        assert data["components"] == []

    def test_detail_not_found_returns_404(self):
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = parent_exec

        response = client.get("/api/beamingMasters/bm_quality_detail/999?co_id=1")
        assert response.status_code == 404

    def test_detail_missing_co_id_returns_400(self):
        response = client.get("/api/beamingMasters/bm_quality_detail/77")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
