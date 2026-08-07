"""Regression: POST/PUT /api/accounting/ledgers with a ledger group that doesn't
belong to the company must 400 with a readable message — not 500 with a raw
IntegrityError/SQL dump (found during dev3 browser QA, 2026-07-27)."""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_db(group_exists: bool):
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = (1,) if group_exists else None
    session.execute.return_value.lastrowid = 42
    return session


def _override(session):
    app.dependency_overrides[get_tenant_db] = lambda: session
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}


class TestLedgerGroupGuard:
    def teardown_method(self):
        app.dependency_overrides = {}

    def test_create_ledger_bogus_group_400(self):
        _override(_mock_db(group_exists=False))
        resp = client.post(
            "/api/accounting/ledgers",
            json={"co_id": 1, "ledger_name": "QA", "acc_ledger_group_id": 999999},
        )
        assert resp.status_code == 400
        assert "does not exist for this company" in resp.json()["detail"]

    def test_update_ledger_bogus_group_400(self):
        _override(_mock_db(group_exists=False))
        resp = client.put(
            "/api/accounting/ledgers/5",
            json={"co_id": 1, "acc_ledger_group_id": 999999},
        )
        assert resp.status_code == 400
        assert "does not exist for this company" in resp.json()["detail"]

    def test_create_ledger_valid_group_inserts(self):
        _override(_mock_db(group_exists=True))
        resp = client.post(
            "/api/accounting/ledgers",
            json={"co_id": 1, "ledger_name": "QA", "acc_ledger_group_id": 3},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["acc_ledger_id"] == 42

    def test_create_group_inherits_parent_nature(self):
        """A child group ignores the posted nature and takes the parent's ('L')."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = ("L",)
        session.execute.return_value.lastrowid = 77
        _override(session)

        resp = client.post(
            "/api/accounting/ledger_groups",
            json={
                "co_id": 1,
                "group_name": "QA Child",
                "parent_group_id": 12,
                "nature": "A",  # wrong on purpose — parent wins
            },
        )
        assert resp.status_code == 200
        params = session.execute.call_args_list[-1][0][1]
        assert params["nature"] == "L"
        assert params["normal_balance"] == "C"

    def test_create_group_bad_parent_400(self):
        _override(_mock_db(group_exists=False))
        resp = client.post(
            "/api/accounting/ledger_groups",
            json={"co_id": 1, "group_name": "QA", "parent_group_id": 999999, "nature": "A"},
        )
        assert resp.status_code == 400
        assert "Invalid parent_group_id" in resp.json()["detail"]
