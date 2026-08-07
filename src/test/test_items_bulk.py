"""
Tests for item bulk create endpoints (src/masters/items.py).
Covers /item_bulk_validate, /item_bulk_create, and regression for /item_create
after refactor.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _good_row(code="BULK001", name="Test Item 1"):
    return {
        "itemGroupId": 10,
        "itemCode": code,
        "itemName": name,
        "uomId": 100,
        "hsnCode": "HSN1",
        "taxPercent": 5.0,
        "goodOrService": "Good",
        "saleable": True,
    }


class _DummyItem:
    """Stand-in for a fetched ItemMst row used in dup checks."""
    pass


class TestItemBulkEndpoints:

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        self._mock_session.query.return_value.filter.return_value.first.return_value = None
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _patch_lookups(self, group_ids=None, uom_ids=None):
        return patch(
            "src.masters.items._load_company_lookups",
            return_value=(set(group_ids or [10]), set(uom_ids or [100])),
        )

    # ------------------------------------------------------------------
    # /item_bulk_validate
    # ------------------------------------------------------------------

    def test_bulk_validate_success_clean_batch(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={"co_id": 1, "rows": [_good_row("A1", "Alpha"), _good_row("A2", "Beta")]},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True
        assert body["row_count"] == 2
        assert body["error_count"] == 0
        assert body["errors"] == []

    def test_bulk_validate_within_batch_duplicate_code(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={
                    "co_id": 1,
                    "rows": [
                        _good_row("DUPCODE", "Name A"),
                        _good_row("DUPCODE", "Name B"),
                    ],
                },
            )
        body = resp.json()
        assert body["valid"] is False
        codes = [e["code"] for e in body["errors"]]
        assert "DUP_IN_BATCH" in codes
        dup_err = next(e for e in body["errors"] if e["code"] == "DUP_IN_BATCH")
        assert dup_err["row_idx"] == 1
        assert dup_err["field"] == "itemCode"

    def test_bulk_validate_unknown_group_id(self):
        with self._patch_lookups(group_ids=[10]):
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={"co_id": 1, "rows": [{**_good_row(), "itemGroupId": 999}]},
            )
        body = resp.json()
        assert body["valid"] is False
        assert any(
            e["code"] == "FK_NOT_FOUND" and e["field"] == "itemGroupId"
            for e in body["errors"]
        )

    def test_bulk_validate_unknown_uom_id(self):
        with self._patch_lookups(uom_ids=[100]):
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={"co_id": 1, "rows": [{**_good_row(), "uomId": 999}]},
            )
        body = resp.json()
        assert body["valid"] is False
        assert any(
            e["code"] == "FK_NOT_FOUND" and e["field"] == "uomId" for e in body["errors"]
        )

    def test_bulk_validate_dup_against_existing_db_row(self):
        existing = _DummyItem()
        self._mock_session.query.return_value.filter.return_value.first.side_effect = [
            existing,  # code dup hit
            None,      # name dup miss
        ]
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={"co_id": 1, "rows": [_good_row("EXISTS", "Some Name")]},
            )
        body = resp.json()
        assert body["valid"] is False
        assert any(e["code"] == "DUP_IN_DB" for e in body["errors"])

    def test_bulk_validate_required_fields_missing(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_validate",
                json={"co_id": 1, "rows": [{"itemCode": "X"}]},
            )
        body = resp.json()
        codes = [e["code"] for e in body["errors"]]
        assert codes.count("REQUIRED") >= 3
        fields = {e["field"] for e in body["errors"] if e["code"] == "REQUIRED"}
        assert {"itemGroupId", "itemName", "uomId"}.issubset(fields)

    def test_bulk_validate_missing_co_id(self):
        resp = client.post("/api/itemMaster/item_bulk_validate", json={"rows": []})
        assert resp.status_code == 400

    # ------------------------------------------------------------------
    # /item_bulk_create
    # ------------------------------------------------------------------

    def test_bulk_create_success_inserts_all(self):
        self._next_id = [501, 502]

        def fake_add(obj):
            obj.item_id = self._next_id.pop(0)
        self._mock_session.add.side_effect = fake_add

        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_create",
                json={"co_id": 1, "rows": [_good_row("A1", "Alpha"), _good_row("A2", "Beta")]},
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["created_count"] == 2
        assert body["item_ids"] == [501, 502]
        self._mock_session.commit.assert_called_once()

    def test_bulk_create_revalidates_and_rejects_400(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_create",
                json={
                    "co_id": 1,
                    "rows": [_good_row("DUP", "A"), _good_row("DUP", "B")],
                },
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["valid"] is False
        assert detail["error_count"] >= 1
        self._mock_session.commit.assert_not_called()

    def test_bulk_create_rolls_back_on_db_error(self):
        self._call_idx = 0

        def fake_add(obj):
            self._call_idx += 1
            if self._call_idx == 2:
                raise RuntimeError("simulated db failure")
            obj.item_id = 901
        self._mock_session.add.side_effect = fake_add

        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_create",
                json={"co_id": 1, "rows": [_good_row("X1", "Xa"), _good_row("X2", "Xb")]},
            )
        assert resp.status_code == 500
        self._mock_session.rollback.assert_called()
        self._mock_session.commit.assert_not_called()

    def test_bulk_create_empty_rows_400(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_bulk_create", json={"co_id": 1, "rows": []}
            )
        assert resp.status_code == 400

    # ------------------------------------------------------------------
    # /item_create regression after refactor
    # ------------------------------------------------------------------

    def test_single_create_still_works(self):
        def fake_add(obj):
            obj.item_id = 777
        self._mock_session.add.side_effect = fake_add

        with self._patch_lookups():
            resp = client.post("/api/itemMaster/item_create", json={"co_id": 1, **_good_row()})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["item_id"] == 777
        assert body["message"] == "Item created successfully"

    def test_single_create_dup_returns_409(self):
        existing = _DummyItem()
        self._mock_session.query.return_value.filter.return_value.first.side_effect = [
            existing,
            None,
        ]
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_create", json={"co_id": 1, **_good_row()}
            )
        assert resp.status_code == 409

    def test_single_create_missing_required_returns_400(self):
        with self._patch_lookups():
            resp = client.post(
                "/api/itemMaster/item_create",
                json={"co_id": 1, "itemCode": "OnlyCode"},
            )
        assert resp.status_code == 400
