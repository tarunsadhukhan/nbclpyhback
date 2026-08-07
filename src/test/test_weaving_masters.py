"""Tests for Weaving Quality Master endpoints (Page A).

Tests for src/juteProduction/weaving_masters.py (prefix /api/weavingMasters).

Portal persona: DB + auth are mocked (no real DB). The router imports
get_tenant_db / get_current_user_with_refresh into its own namespace; FastAPI
resolves them via Depends, so we override them through app.dependency_overrides
keyed by those exact symbols.

Covered:
  * setup (items + yarns) happy path + missing co_id -> 400
  * list happy path / empty / missing co_id -> 400
  * create happy path, duplicate-guard (co_id,item_id,weaving_quality_code) -> 400,
    blank code -> 400, missing-ends (simple) -> 400
  * composite create: is_composite=1, >=2 components -> parent ends=SUM, _dtl inserts;
    missing/short components -> 400
  * edit (rename + 404 + missing co_id)
  * delete soft (active=0) + 404 + missing co_id
  * detail returns parent + nested components (404, empty, missing co_id)
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteProduction.weaving_masters import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestWeavingQualitySetup:
    """GET /api/weavingMasters/weaving_quality_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_items_and_yarns(self):
        item_rows = [
            _mock_row({"item_id": 10, "item_code": "WC-RED", "item_name": "Woven Cloth Red"}),
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

        response = client.get("/api/weavingMasters/weaving_quality_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items"][0]["item_code"] == "WC-RED"
        assert data["yarns"][0]["jute_yarn_count"] == 8.0

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingMasters/weaving_quality_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestWeavingQualityList:
    """GET /api/weavingMasters/weaving_quality_list"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_rows(self):
        rows = [
            _mock_row({
                "weaving_quality_id": 1, "co_id": 1, "item_id": 10, "item_code": "WC-RED",
                "item_name": "Woven Cloth Red", "weaving_quality_code": "10oz",
                "weaving_quality_name": "Red", "ends": 272, "ozs_yds": 10.0, "active": 1,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/weavingMasters/weaving_quality_list?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["weaving_quality_code"] == "10oz"

    def test_success_with_filters_binds_params(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get(
            "/api/weavingMasters/weaving_quality_list?co_id=1&branch_id=2&item_id=10&search=red"
        )
        assert response.status_code == 200
        params = self._mock_session.execute.call_args.args[1]
        assert params["co_id"] == 1
        assert params["branch_id"] == 2
        assert params["item_id"] == 10
        assert params["search"] == "%red%"

    def test_empty_results(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/weavingMasters/weaving_quality_list?co_id=1")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingMasters/weaving_quality_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestWeavingQualityCreate:
    """POST /api/weavingMasters/weaving_quality_create"""

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
            "weaving_quality_code": "10oz",
            "weaving_quality_name": "Red",
            "ends": 272,
            "finished_length": 100.0,
            "ozs_yds": 10.0,
            "no_of_jugar_per_cut": 4.0,
        }

    def test_success_creates_row(self):
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = None
        insert_exec = MagicMock()
        insert_exec.lastrowid = 99
        self._mock_session.execute.side_effect = [dup_exec, insert_exec]

        response = client.post(
            "/api/weavingMasters/weaving_quality_create", json=self._payload()
        )

        assert response.status_code == 200
        assert response.json()["data"]["weaving_quality_id"] == 99
        self._mock_session.commit.assert_called_once()
        # Parent INSERT (2nd execute) carries co_id, simple ends, is_composite=0, updated_by.
        parent_params = self._mock_session.execute.call_args_list[1].args[1]
        assert parent_params["co_id"] == 1
        assert parent_params["ends"] == 272
        assert parent_params["is_composite"] == 0
        assert parent_params["updated_by"] == 1

    def test_duplicate_returns_400(self):
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = _mock_row({"weaving_quality_id": 5})
        self._mock_session.execute.return_value = dup_exec

        response = client.post(
            "/api/weavingMasters/weaving_quality_create", json=self._payload()
        )

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_blank_code_returns_400(self):
        payload = self._payload()
        payload["weaving_quality_code"] = "   "
        response = client.post("/api/weavingMasters/weaving_quality_create", json=payload)
        assert response.status_code == 400
        self._mock_session.commit.assert_not_called()

    def test_simple_missing_ends_returns_400(self):
        """Non-composite create with no `ends` -> 400 before any DB write."""
        payload = self._payload()
        del payload["ends"]
        response = client.post("/api/weavingMasters/weaving_quality_create", json=payload)
        assert response.status_code == 400
        assert "ends" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def _composite_payload(self):
        return {
            "co_id": 1,
            "item_id": 10,
            "weaving_quality_code": "COMP-1",
            "weaving_quality_name": "Composite Red",
            "finished_length": 100.0,
            "ozs_yds": 10.0,
            "no_of_jugar_per_cut": 4.0,
            "is_composite": 1,
            "components": [
                {"component_no": 1, "ends": 120, "yarn_item_id": 50, "count": 8.0},
                {"component_no": 2, "ends": 160, "yarn_item_id": 51, "count": 10.0},
            ],
        }

    def test_composite_create_sums_ends_and_inserts_components(self):
        """is_composite=1 with 2 components -> parent ends = SUM(120+160)=280 and one
        _dtl insert per component bound to the new parent id."""
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
            "/api/weavingMasters/weaving_quality_create", json=self._composite_payload()
        )

        assert response.status_code == 200
        assert response.json()["data"]["weaving_quality_id"] == 77
        self._mock_session.commit.assert_called_once()

        parent_params = self._mock_session.execute.call_args_list[1].args[1]
        assert parent_params["ends"] == 280  # 120 + 160
        assert parent_params["is_composite"] == 1

        comp1_params = self._mock_session.execute.call_args_list[2].args[1]
        comp2_params = self._mock_session.execute.call_args_list[3].args[1]
        assert comp1_params["weaving_quality_id"] == 77
        assert comp1_params["ends"] == 120
        assert comp1_params["count"] == 8.0
        assert comp2_params["ends"] == 160
        assert comp2_params["count"] == 10.0

    def test_composite_missing_components_returns_400(self):
        payload = self._composite_payload()
        payload["components"] = None
        response = client.post("/api/weavingMasters/weaving_quality_create", json=payload)
        assert response.status_code == 400
        assert "component" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_composite_single_component_returns_400(self):
        payload = self._composite_payload()
        payload["components"] = [
            {"component_no": 1, "ends": 120, "yarn_item_id": 50, "count": 8.0},
        ]
        response = client.post("/api/weavingMasters/weaving_quality_create", json=payload)
        assert response.status_code == 400
        assert "component" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


class TestWeavingQualityEdit:
    """PUT /api/weavingMasters/weaving_quality_edit/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _existing(self):
        return _mock_row({
            "weaving_quality_id": 5, "co_id": 1, "item_id": 10,
            "weaving_quality_code": "10oz", "is_composite": 0,
        })

    def test_rename_success(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = self._existing()
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = None  # new code not taken
        update_exec = MagicMock()
        # Execute order: fetch existing, dup-check (code changed), UPDATE.
        self._mock_session.execute.side_effect = [existing_exec, dup_exec, update_exec]

        response = client.put(
            "/api/weavingMasters/weaving_quality_edit/5?co_id=1",
            json={"weaving_quality_code": "12oz", "weaving_quality_name": "Blue"},
        )

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Updated"
        self._mock_session.commit.assert_called_once()

    def test_not_found_returns_404(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = existing_exec

        response = client.put(
            "/api/weavingMasters/weaving_quality_edit/999?co_id=1",
            json={"weaving_quality_name": "X"},
        )
        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_wrong_company_returns_404(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = _mock_row({
            "weaving_quality_id": 5, "co_id": 2, "item_id": 10,
            "weaving_quality_code": "10oz", "is_composite": 0,
        })
        self._mock_session.execute.return_value = existing_exec

        response = client.put(
            "/api/weavingMasters/weaving_quality_edit/5?co_id=1",
            json={"weaving_quality_name": "X"},
        )
        assert response.status_code == 404

    def test_duplicate_code_returns_400(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = self._existing()
        dup_exec = MagicMock()
        dup_exec.fetchone.return_value = _mock_row({"weaving_quality_id": 9})
        self._mock_session.execute.side_effect = [existing_exec, dup_exec]

        response = client.put(
            "/api/weavingMasters/weaving_quality_edit/5?co_id=1",
            json={"weaving_quality_code": "12oz"},
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_missing_co_id_returns_400(self):
        response = client.put(
            "/api/weavingMasters/weaving_quality_edit/5",
            json={"weaving_quality_name": "X"},
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestWeavingQualityDelete:
    """DELETE /api/weavingMasters/weaving_quality_delete/{id} (soft active=0)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_soft_delete_success(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = _mock_row({
            "weaving_quality_id": 5, "co_id": 1, "item_id": 10,
            "weaving_quality_code": "10oz", "is_composite": 0,
        })
        delete_exec = MagicMock()
        self._mock_session.execute.side_effect = [existing_exec, delete_exec]

        response = client.delete("/api/weavingMasters/weaving_quality_delete/5?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()
        # Soft-delete params carry the row id + updated_by (active=0 lives in the SQL).
        del_params = self._mock_session.execute.call_args_list[1].args[1]
        assert del_params["weaving_quality_id"] == 5
        assert del_params["updated_by"] == 1

    def test_not_found_returns_404(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = existing_exec

        response = client.delete("/api/weavingMasters/weaving_quality_delete/999?co_id=1")
        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_wrong_company_returns_404(self):
        existing_exec = MagicMock()
        existing_exec.fetchone.return_value = _mock_row({
            "weaving_quality_id": 5, "co_id": 2, "item_id": 10,
            "weaving_quality_code": "10oz", "is_composite": 0,
        })
        self._mock_session.execute.return_value = existing_exec

        response = client.delete("/api/weavingMasters/weaving_quality_delete/5?co_id=1")
        assert response.status_code == 404

    def test_missing_co_id_returns_400(self):
        response = client.delete("/api/weavingMasters/weaving_quality_delete/5")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestWeavingQualityDetail:
    """GET /api/weavingMasters/weaving_quality_detail/{id} (edit-dialog source)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_composite_detail_returns_parent_and_components(self):
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = _mock_row({
            "weaving_quality_id": 77, "co_id": 1, "branch_id": 2, "item_id": 10,
            "weaving_quality_code": "COMP-1", "weaving_quality_name": "Composite Red",
            "ends": 280, "is_composite": 1, "active": 1,
        })
        comp_exec = MagicMock()
        comp_exec.fetchall.return_value = [
            _mock_row({
                "weaving_quality_dtl_id": 1, "component_no": 1, "ends": 120,
                "yarn_item_id": 50, "count": 8.0,
            }),
            _mock_row({
                "weaving_quality_dtl_id": 2, "component_no": 2, "ends": 160,
                "yarn_item_id": 51, "count": 10.0,
            }),
        ]
        # Execute order: parent fetch, then component fetch.
        self._mock_session.execute.side_effect = [parent_exec, comp_exec]

        response = client.get("/api/weavingMasters/weaving_quality_detail/77?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["weaving_quality_id"] == 77
        assert data["is_composite"] == 1
        assert data["ends"] == 280
        assert len(data["components"]) == 2
        assert data["components"][0]["component_no"] == 1
        assert data["components"][0]["ends"] == 120
        assert data["components"][1]["count"] == 10.0

    def test_simple_detail_returns_empty_components(self):
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = _mock_row({
            "weaving_quality_id": 5, "co_id": 1, "branch_id": 2, "item_id": 10,
            "weaving_quality_code": "10oz", "weaving_quality_name": "Red",
            "ends": 272, "is_composite": 0, "active": 1,
        })
        comp_exec = MagicMock()
        comp_exec.fetchall.return_value = []
        self._mock_session.execute.side_effect = [parent_exec, comp_exec]

        response = client.get("/api/weavingMasters/weaving_quality_detail/5?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["is_composite"] == 0
        assert data["components"] == []

    def test_detail_not_found_returns_404(self):
        parent_exec = MagicMock()
        parent_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = parent_exec

        response = client.get("/api/weavingMasters/weaving_quality_detail/999?co_id=1")
        assert response.status_code == 404

    def test_detail_missing_co_id_returns_400(self):
        response = client.get("/api/weavingMasters/weaving_quality_detail/77")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
