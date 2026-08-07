"""POST /api/accounting/voucher_types — manual voucher-type setup for companies
that never ran activate_company (acc_voucher_type rows were seeder-only before)."""
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_db(duplicate_category=None):
    """duplicate_category: None = no existing row; a string = dup row with that category."""
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = (
        None if duplicate_category is None
        else MagicMock(_mapping={"type_category": duplicate_category})
    )
    session.execute.return_value.lastrowid = 77
    return session


def _override(session):
    app.dependency_overrides[get_tenant_db] = lambda: session
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}


class TestCreateVoucherType:
    def teardown_method(self):
        app.dependency_overrides = {}

    def test_create_success(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "voucher_type_name": "Journal", "type_category": "JOURNAL"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["acc_voucher_type_id"] == 77
        # seeder row shape: type_code == prefix == category code; manual => is_system_type 0
        assert data["type_code"] == "JRN"
        assert data["prefix"] == "JRN"
        assert data["type_category"] == "JOURNAL"
        assert data["requires_bank_cash"] == 0
        assert data["is_system_type"] == 0
        assert data["auto_numbering"] == 1

    def test_create_bank_cash_category_and_custom_prefix(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={
                "co_id": 1,
                "voucher_type_name": "Bank Payment",
                "type_category": "payment",  # case-insensitive
                "prefix": "BPY",
            },
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["type_category"] == "PAYMENT"
        assert data["type_code"] == "PAY"
        assert data["prefix"] == "BPY"
        assert data["requires_bank_cash"] == 1

    def test_missing_co_id_400(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"voucher_type_name": "Journal", "type_category": "JOURNAL"},
        )
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"]

    def test_missing_name_400(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "type_category": "JOURNAL"},
        )
        assert resp.status_code == 400
        assert "voucher_type_name" in resp.json()["detail"]

    def test_missing_category_400(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "voucher_type_name": "Journal"},
        )
        assert resp.status_code == 400
        assert "type_category is required" in resp.json()["detail"]

    def test_invalid_category_400(self):
        _override(_mock_db())
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "voucher_type_name": "Weird", "type_category": "NONSENSE"},
        )
        assert resp.status_code == 400
        assert "Invalid type_category" in resp.json()["detail"]

    def test_duplicate_category_400(self):
        _override(_mock_db(duplicate_category="JOURNAL"))
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "voucher_type_name": "Journal 2", "type_category": "JOURNAL"},
        )
        assert resp.status_code == 400
        assert "type_category already exists" in resp.json()["detail"]

    def test_duplicate_name_400(self):
        # existing row matched on name, not category
        _override(_mock_db(duplicate_category="SALES"))
        resp = client.post(
            "/api/accounting/voucher_types",
            json={"co_id": 1, "voucher_type_name": "Journal", "type_category": "JOURNAL"},
        )
        assert resp.status_code == 400
        assert "type_name already exists" in resp.json()["detail"]
