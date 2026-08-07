"""Tests for the Finishing Quality Master endpoints (restructured).

Tests for src/juteProduction/finishing_masters.py (prefix /api/finishingMasters).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through app.dependency_overrides
keyed by those EXACT symbols (mirrors test_beaming_masters / test_beaming_target_map).

New shape: the ITEM is the identity (one active row per co_id, item_id, quality_type).
quality_type=1 -> Hessian, =2 -> Sacking (display labels only; stored INT 1/2). The
separate quality code/name and all structural params are gone; three OPTIONAL params
attach to the item: packsheet_wt (kg), std_bale_weight (kg), no_of_bags (pcs).

Covered:
  * quality_setup happy path returns {"items": [...]} (no cloth_qualities) + missing co_id 400
  * quality_list happy path (item_code/item_name + 3 params) + empty + missing co_id 400
    + invalid quality_type 400
  * quality_detail happy path + 404 missing + missing co_id 400
  * quality_create hessian (type 1) success returns finishing_quality_id
  * quality_create sacking (type 2) success; params omitted (all None) still succeeds
  * quality_create duplicate (co_id, quality_type, item_id) 400 + invalid quality_type 400
  * quality_edit updates item/params + 404 missing + 404 foreign co_id + missing co_id 400
  * quality_delete soft-delete + 404 + 404 foreign co_id + missing co_id 400
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.finishing_masters import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _fetchall_exec(rows):
    ex = MagicMock()
    ex.fetchall.return_value = rows
    return ex


def _fetchone_exec(row):
    ex = MagicMock()
    ex.fetchone.return_value = row
    return ex


# =============================================================================
# quality_setup
# =============================================================================


class TestQualitySetup:
    """GET /api/finishingMasters/quality_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_items_only(self):
        item_rows = [_mock_row({"item_id": 100, "item_name": "Hessian Cloth"})]
        self._mock_session.execute.return_value.fetchall.return_value = item_rows

        response = client.get("/api/finishingMasters/quality_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items"][0]["item_id"] == 100
        # cloth_qualities is gone — the item is the identity now.
        assert "cloth_qualities" not in data

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/finishingMasters/quality_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# quality_list
# =============================================================================


class TestQualityList:
    """GET /api/finishingMasters/quality_list"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_item_label_and_params(self):
        rows = [
            _mock_row(
                {
                    "finishing_quality_id": 5,
                    "co_id": 1,
                    "branch_id": 2,
                    "quality_type": 1,
                    "item_id": 100,
                    "item_code": "HC-10",
                    "item_name": "Hessian-10",
                    "packsheet_wt": 1.250,
                    "std_bale_weight": 180.000,
                    "no_of_bags": 500,
                    "active": 1,
                }
            ),
            _mock_row(
                {
                    "finishing_quality_id": 6,
                    "co_id": 1,
                    "branch_id": 2,
                    "quality_type": 2,
                    "item_id": 101,
                    "item_code": "BAG-A",
                    "item_name": "BagA",
                    "packsheet_wt": None,
                    "std_bale_weight": None,
                    "no_of_bags": None,
                    "active": 1,
                }
            ),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/finishingMasters/quality_list?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 2
        assert data[0]["item_code"] == "HC-10"
        assert data[0]["item_name"] == "Hessian-10"
        assert data[0]["packsheet_wt"] == 1.250
        assert data[0]["std_bale_weight"] == 180.000
        assert data[0]["no_of_bags"] == 500
        assert data[1]["quality_type"] == 2

    def test_empty(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/finishingMasters/quality_list?co_id=1")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/finishingMasters/quality_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_quality_type_returns_400(self):
        response = client.get(
            "/api/finishingMasters/quality_list?co_id=1&quality_type=9"
        )
        assert response.status_code == 400
        assert "quality_type" in response.json()["detail"].lower()


# =============================================================================
# quality_detail
# =============================================================================


class TestQualityDetail:
    """GET /api/finishingMasters/quality_detail/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success(self):
        row = _mock_row(
            {
                "finishing_quality_id": 5,
                "co_id": 1,
                "branch_id": 2,
                "quality_type": 1,
                "item_id": 100,
                "item_code": "HC-10",
                "item_name": "Hessian-10",
                "packsheet_wt": 1.250,
                "std_bale_weight": 180.000,
                "no_of_bags": 500,
                "active": 1,
            }
        )
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/finishingMasters/quality_detail/5?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["finishing_quality_id"] == 5
        assert data["item_code"] == "HC-10"
        assert data["packsheet_wt"] == 1.250

    def test_not_found_returns_404(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.get("/api/finishingMasters/quality_detail/999?co_id=1")
        assert response.status_code == 404

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/finishingMasters/quality_detail/5")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# quality_create
# =============================================================================


class TestQualityCreate:
    """POST /api/finishingMasters/quality_create"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_hessian_success(self):
        """quality_type=1 (Hessian). Execute order: duplicate-check (None), insert."""
        insert_result = MagicMock()
        insert_result.lastrowid = 42
        self._mock_session.execute.side_effect = [
            _fetchone_exec(None),  # no duplicate
            insert_result,
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "quality_type": 1,
            "item_id": 100,
            "packsheet_wt": 1.250,
            "std_bale_weight": 180.000,
            "no_of_bags": 500,
        }
        response = client.post("/api/finishingMasters/quality_create", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["finishing_quality_id"] == 42
        self._mock_session.commit.assert_called_once()
        # INSERT bind carries quality_type=1 and the item identity + params.
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["quality_type"] == 1
        assert insert_params["item_id"] == 100
        assert insert_params["packsheet_wt"] == 1.250
        assert insert_params["no_of_bags"] == 500

    def test_create_sacking_params_omitted_success(self):
        """quality_type=2 (Sacking). All three params omitted -> they bind as None
        (optional), insert still succeeds."""
        insert_result = MagicMock()
        insert_result.lastrowid = 43
        self._mock_session.execute.side_effect = [
            _fetchone_exec(None),  # no duplicate
            insert_result,
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "quality_type": 2,
            "item_id": 101,
        }
        response = client.post("/api/finishingMasters/quality_create", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["finishing_quality_id"] == 43
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["quality_type"] == 2
        assert insert_params["packsheet_wt"] is None
        assert insert_params["std_bale_weight"] is None
        assert insert_params["no_of_bags"] is None

    def test_create_duplicate_returns_400(self):
        self._mock_session.execute.return_value = _fetchone_exec(
            _mock_row({"finishing_quality_id": 99})
        )

        payload = {
            "co_id": 1,
            "quality_type": 1,
            "item_id": 100,
        }
        response = client.post("/api/finishingMasters/quality_create", json=payload)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_create_invalid_quality_type_returns_400(self):
        payload = {
            "co_id": 1,
            "quality_type": 9,
            "item_id": 100,
        }
        response = client.post("/api/finishingMasters/quality_create", json=payload)
        assert response.status_code == 400
        assert "quality_type" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


# =============================================================================
# quality_edit
# =============================================================================


class TestQualityEdit:
    """PUT /api/finishingMasters/quality_edit/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_edit_params_only_success(self):
        """Editing only params (no item_id change) skips the duplicate re-check.
        Execute order: find(existing), UPDATE."""
        existing = _mock_row(
            {"finishing_quality_id": 5, "co_id": 1, "quality_type": 1, "item_id": 100}
        )
        self._mock_session.execute.side_effect = [
            _fetchone_exec(existing),
            MagicMock(),
        ]

        response = client.put(
            "/api/finishingMasters/quality_edit/5?co_id=1",
            json={"packsheet_wt": 2.000, "no_of_bags": 600},
        )

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Updated"
        self._mock_session.commit.assert_called_once()
        update_params = self._mock_session.execute.call_args_list[1].args[1]
        assert update_params["packsheet_wt"] == 2.000
        assert update_params["no_of_bags"] == 600

    def test_edit_item_change_success(self):
        """Changing item_id triggers a duplicate re-check (None -> proceeds).
        Execute order: find(existing), dup-check(None), UPDATE."""
        existing = _mock_row(
            {"finishing_quality_id": 5, "co_id": 1, "quality_type": 1, "item_id": 100}
        )
        self._mock_session.execute.side_effect = [
            _fetchone_exec(existing),
            _fetchone_exec(None),  # no duplicate at new item
            MagicMock(),
        ]

        response = client.put(
            "/api/finishingMasters/quality_edit/5?co_id=1",
            json={"item_id": 200},
        )

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Updated"
        self._mock_session.commit.assert_called_once()
        update_params = self._mock_session.execute.call_args_list[2].args[1]
        assert update_params["item_id"] == 200

    def test_edit_not_found_returns_404(self):
        self._mock_session.execute.return_value = _fetchone_exec(None)

        response = client.put(
            "/api/finishingMasters/quality_edit/999?co_id=1",
            json={"packsheet_wt": 2.000},
        )

        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_edit_foreign_co_id_returns_404(self):
        existing = _mock_row(
            {"finishing_quality_id": 5, "co_id": 99, "quality_type": 1, "item_id": 100}
        )
        self._mock_session.execute.return_value = _fetchone_exec(existing)

        response = client.put(
            "/api/finishingMasters/quality_edit/5?co_id=1",
            json={"packsheet_wt": 2.000},
        )

        assert response.status_code == 404

    def test_edit_missing_co_id_returns_400(self):
        response = client.put(
            "/api/finishingMasters/quality_edit/5", json={"packsheet_wt": 2.000}
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# quality_delete
# =============================================================================


class TestQualityDelete:
    """DELETE /api/finishingMasters/quality_delete/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_success(self):
        existing = _mock_row({"finishing_quality_id": 5, "co_id": 1})
        self._mock_session.execute.side_effect = [
            _fetchone_exec(existing),
            MagicMock(),
        ]

        response = client.delete("/api/finishingMasters/quality_delete/5?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found_returns_404(self):
        self._mock_session.execute.return_value = _fetchone_exec(None)

        response = client.delete("/api/finishingMasters/quality_delete/999?co_id=1")

        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_delete_foreign_co_id_returns_404(self):
        existing = _mock_row({"finishing_quality_id": 5, "co_id": 99})
        self._mock_session.execute.return_value = _fetchone_exec(existing)

        response = client.delete("/api/finishingMasters/quality_delete/5?co_id=1")

        assert response.status_code == 404

    def test_delete_missing_co_id_returns_400(self):
        response = client.delete("/api/finishingMasters/quality_delete/5")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
