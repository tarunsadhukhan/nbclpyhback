"""Regression tests for three accounting gaps (2026-07-27):

1. GET /api/accounting/vouchers ignored `search` — the param is now bound
   identically into the list and the count query so the total matches the rows.
2. update_draft_voucher only allowed status 21, but /reopen returns rejected and
   cancelled vouchers to 1 (Open) — a rejected voucher was uncorrectable.
   Editing is now allowed at 21 and 1, and still blocked from 20 onward.
3. POST /api/accounting/ledger_groups stored normal_balance = NULL whenever the
   FE omitted it; it is now derived from nature (A/E -> D, L/I -> C).
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.accounting import voucher_service
from src.accounting.voucher_service import (
    STATUS_APPROVED,
    STATUS_CANCELLED,
    STATUS_DRAFT,
    STATUS_OPEN,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
)

client = TestClient(app)


def _row(mapping: dict):
    """A stand-in for a SQLAlchemy Row (code does dict(row._mapping))."""
    row = MagicMock()
    row._mapping = mapping
    return row


def _override(session):
    app.dependency_overrides[get_tenant_db] = lambda: session
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}


def _params_of(session, key: str) -> dict:
    """First execute() params dict carrying `key` (identifies a statement)."""
    for call in session.execute.call_args_list:
        if len(call.args) > 1 and isinstance(call.args[1], dict) and key in call.args[1]:
            return call.args[1]
    raise AssertionError(f"no execute() call bound {key!r}")


# =============================================================================
# 1. Voucher list search
# =============================================================================

class TestVoucherListSearch:
    def teardown_method(self):
        app.dependency_overrides = {}

    def _call(self, url):
        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []
        session.execute.return_value.scalar.return_value = 0
        _override(session)
        resp = client.get(url)
        assert resp.status_code == 200, resp.text
        # call 0 = list (has limit/offset), call 1 = count
        list_sql, list_params = session.execute.call_args_list[0].args
        count_sql, count_params = session.execute.call_args_list[1].args
        return str(list_sql), list_params, str(count_sql), count_params

    def test_search_bound_as_like_pattern(self):
        list_sql, list_params, count_sql, count_params = self._call(
            "/api/accounting/vouchers?co_id=1&search=JV/0001"
        )
        assert list_params["search"] == "%JV/0001%"
        assert count_params["search"] == "%JV/0001%"
        # the clause must actually exist in both SQL bodies
        for sql in (list_sql, count_sql):
            assert ":search IS NULL" in sql
            assert "av.voucher_no LIKE :search" in sql
            assert "pm.supp_name LIKE :search" in sql
            assert "avt.type_name LIKE :search" in sql

    def test_no_search_binds_none_not_the_string_null(self):
        _, list_params, _, count_params = self._call(
            "/api/accounting/vouchers?co_id=1"
        )
        assert list_params["search"] is None
        assert count_params["search"] is None

    def test_blank_search_binds_none(self):
        _, list_params, _, _ = self._call(
            "/api/accounting/vouchers?co_id=1&search=%20%20"
        )
        assert list_params["search"] is None

    def test_count_filters_identical_to_list_filters(self):
        """If these ever drift, `total` stops matching the page rows."""
        _, list_params, _, count_params = self._call(
            "/api/accounting/vouchers?co_id=1&search=ACME&branch_id=2&status_id=3"
        )
        assert count_params == {
            k: v for k, v in list_params.items() if k not in ("limit", "offset")
        }


# =============================================================================
# 2. Editing allowed at Draft (21) and Open (1)
# =============================================================================

BALANCED_LINES = [
    {"acc_ledger_id": 11, "debit_amount": 1000},
    {"acc_ledger_id": 22, "credit_amount": 1000},
]


def _editable_db():
    """MagicMock session where no period lock row exists."""
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = None
    return session


def _patch_header(monkeypatch, status_id: int):
    monkeypatch.setattr(
        voucher_service, "_get_voucher_header",
        lambda db, vid: {
            "acc_voucher_id": vid, "co_id": 1, "branch_id": 2, "party_id": None,
            "voucher_date": "2026-04-15", "ref_no": None, "ref_date": None,
            "narration": None, "status_id": status_id, "approval_level": None,
            "type_category": "JOURNAL",
        },
    )
    monkeypatch.setattr(
        voucher_service, "_resolve_financial_year",
        lambda db, co_id, vdate: {"acc_financial_year_id": 7, "fy_label": "2026-27"},
    )


class TestUpdateVoucherStatusGuard:
    @pytest.mark.parametrize(
        "status_id,remarks",
        [(STATUS_DRAFT, "Draft voucher updated"), (STATUS_OPEN, "Open voucher updated")],
    )
    def test_update_allowed(self, monkeypatch, status_id, remarks):
        _patch_header(monkeypatch, status_id)
        db = _editable_db()

        result = voucher_service.update_draft_voucher(
            db, 55, {"lines": BALANCED_LINES}, 1
        )

        assert result == {
            "voucher_id": 55, "status_id": status_id, "total_amount": 1000.0
        }
        # status is preserved, and the approval log says so
        log = _params_of(db, "action")
        assert log["action"] == "UPDATE"
        assert log["from_status_id"] == status_id
        assert log["to_status_id"] == status_id
        assert log["remarks"] == remarks
        db.commit.assert_called_once()

    def test_update_rebuilds_lines_at_open(self, monkeypatch):
        """The line/GST/bill-ref rebuild must still run for an Open voucher."""
        _patch_header(monkeypatch, STATUS_OPEN)
        db = _editable_db()

        voucher_service.update_draft_voucher(db, 55, {"lines": BALANCED_LINES}, 1)

        sqls = [str(c.args[0]) for c in db.execute.call_args_list]
        assert any("DELETE FROM acc_voucher_line" in s for s in sqls)
        assert any("DELETE FROM acc_voucher_gst" in s for s in sqls)
        assert any("DELETE FROM acc_bill_ref" in s for s in sqls)
        assert _params_of(db, "dr_cr")["acc_ledger_id"] == 11  # lines re-inserted

    @pytest.mark.parametrize(
        "status_id",
        [STATUS_PENDING_APPROVAL, STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED],
    )
    def test_update_blocked_from_pending_approval_onward(self, monkeypatch, status_id):
        _patch_header(monkeypatch, status_id)
        db = _editable_db()

        with pytest.raises(HTTPException) as exc:
            voucher_service.update_draft_voucher(
                db, 55, {"lines": BALANCED_LINES}, 1
            )

        assert exc.value.status_code == 400
        assert exc.value.detail == "Only draft or open vouchers can be edited."
        db.commit.assert_not_called()

    def test_put_endpoint_returns_400_when_locked(self):
        """Same guard, through PUT /api/accounting/vouchers/{id}."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = _row(
            {"acc_voucher_id": 55, "co_id": 1, "status_id": STATUS_APPROVED,
             "type_category": "JOURNAL"}
        )
        _override(session)
        try:
            resp = client.put(
                "/api/accounting/vouchers/55", json={"lines": BALANCED_LINES}
            )
            assert resp.status_code == 400
            assert resp.json()["detail"] == (
                "Only draft or open vouchers can be edited."
            )
        finally:
            app.dependency_overrides = {}


# =============================================================================
# 3. normal_balance derived from nature
# =============================================================================

class TestLedgerGroupNormalBalance:
    def teardown_method(self):
        app.dependency_overrides = {}

    def _create(self, body):
        session = MagicMock()
        session.execute.return_value.lastrowid = 9
        _override(session)
        resp = client.post("/api/accounting/ledger_groups", json=body)
        assert resp.status_code == 200, resp.text
        return _params_of(session, "normal_balance")

    @pytest.mark.parametrize(
        "nature,expected",
        [("A", "D"), ("E", "D"), ("L", "C"), ("I", "C"), ("a", "D"), ("l", "C")],
    )
    def test_derived_from_nature(self, nature, expected):
        params = self._create(
            {"co_id": 1, "group_name": "QA Group", "nature": nature}
        )
        assert params["normal_balance"] == expected

    def test_explicit_body_value_wins(self):
        params = self._create(
            {"co_id": 1, "group_name": "QA Group", "nature": "A",
             "normal_balance": "C"}
        )
        assert params["normal_balance"] == "C"

    def test_unknown_nature_stays_null(self):
        params = self._create({"co_id": 1, "group_name": "QA Group"})
        assert params["normal_balance"] is None
