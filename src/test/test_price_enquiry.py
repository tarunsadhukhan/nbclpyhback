"""
Regression tests for the Price Enquiry module.
Tests for src/procurement/price_enquiry.py (endpoints under /api/priceEnquiry).

These tests focus on recently-fixed bugs (priority regression coverage):
  1. create_enquiry resolves co_id from branch_mst and threads it into the insert.
  2. add_response computes gross/net totals from item lines into the header insert.
  3. select_response is gated on the parent enquiry being Approved (status 3),
     and validates enquiry/response linkage + existence.
  4. cancel_enquiry / reopen_enquiry status-transition gating.
  5. Required-param validation across GET endpoints.

Mocking style mirrors src/test/test_yarn_quality.py: a MagicMock session is
injected via FastAPI dependency_overrides, and rows expose ._mapping dicts
(and [0] indexing where the endpoint indexes the row positionally).
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    """A row whose ._mapping is `mapping` and whose positional indexing
    (row[0], row[1], ...) reflects the dict's values in insertion order."""
    row = MagicMock()
    row._mapping = mapping
    values = list(mapping.values())

    def _getitem(idx):
        return values[idx]

    row.__getitem__.side_effect = _getitem
    return row


def _result(fetchone=None, fetchall=None, lastrowid=None):
    """Build a mock object emulating the return of db.execute(...)."""
    res = MagicMock()
    res.fetchone.return_value = fetchone
    res.fetchall.return_value = fetchall if fetchall is not None else []
    if lastrowid is not None:
        res.lastrowid = lastrowid
    return res


def _bind_checking_execute(side_results):
    """Return an execute() side_effect that also validates bind-parameter
    completeness for text() statements.

    SQLAlchemy parses `:name` params out of text() at construction time, so a
    call site that omits one (e.g. the historical missing :enquiry_no on
    update_enquiry_status) raises StatementError in production while a plain
    MagicMock session lets it pass. This harness restores that safety net.
    """
    iterator = iter(side_results)

    def _execute(stmt, params=None, *args, **kwargs):
        binds = getattr(stmt, "_bindparams", None)
        if binds:
            supplied = set((params or {}).keys())
            required = {name for name, bp in binds.items() if bp.required}
            missing = required - supplied
            assert not missing, (
                f"Missing bind params {sorted(missing)} for SQL: {str(stmt)[:120]!r}"
            )
        return next(iterator)

    return _execute


class _BaseEnquiryTest:
    """Shared dependency overrides for all price enquiry endpoint tests."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


# =============================================================================
# CREATE ENQUIRY
# =============================================================================


class TestCreateEnquiry(_BaseEnquiryTest):
    """create_enquiry: co_id resolution regression + validation."""

    def _valid_payload(self):
        return {
            "branch_id": "5",
            "date": "2026-06-01",
            "expense_type_id": "2",
            "enquiry_type": "Regular",
            "remarks": "test",
            "items": [{"item_id": "10", "qty": "3", "uom_id": "1"}],
            "suppliers": [{"supplier_id": "100", "supplier_branch_id": "200"}],
        }

    def test_create_enquiry_success_returns_enquiry_id(self):
        """Happy path: branch_mst lookup resolves co_id + prefixes, header
        insert returns lastrowid as enquiry_id."""
        branch_row = _mock_row({"co_id": 77, "co_prefix": "ABC", "branch_prefix": "MAIN"})
        max_no_row = _mock_row({"max_enquiry_no": 4})  # max enquiry no -> row[0]

        # execute() is called many times; route by sequence:
        #  1) branch_mst SELECT (fetchone -> co_id/prefixes)
        #  2) max enquiry no SELECT (fetchone -> 4)
        #  3) header INSERT (lastrowid)
        #  4..) dtl INSERT, supplier INSERT
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=branch_row),
            _result(fetchone=max_no_row),
            _result(lastrowid=999),
            _result(),  # dtl insert
            _result(),  # supplier insert
        ])

        resp = client.post("/api/priceEnquiry/create_enquiry", json=self._valid_payload())

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["enquiry_id"] == 999
        assert body["enquiry_no"] == 5  # 4 + 1
        # Document number carries company/branch prefixes like other txns.
        assert body["sequence_no"].startswith("ABC/MAIN/PE/")

    def test_create_enquiry_resolves_co_id_from_branch(self):
        """REGRESSION: co_id must be looked up from branch_mst and flow into the
        header insert params (not trusted from client)."""
        branch_row = _mock_row({"co_id": 77, "co_prefix": None, "branch_prefix": None})
        max_no_row = _mock_row({"max_enquiry_no": 0})
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=branch_row),
            _result(fetchone=max_no_row),
            _result(lastrowid=1),
            _result(),
            _result(),
        ])

        resp = client.post("/api/priceEnquiry/create_enquiry", json=self._valid_payload())
        assert resp.status_code == 200, resp.text

        calls = self._mock_session.execute.call_args_list

        # First execute is the branch_mst lookup with the branch_id we sent.
        first_sql = str(calls[0].args[0]).lower()
        assert "branch_mst" in first_sql
        assert calls[0].args[1]["branch_id"] == 5

        # The header INSERT (3rd execute) must carry co_id resolved from branch.
        header_params = calls[2].args[1]
        assert header_params["co_id"] == 77
        assert header_params["branch_id"] == 5
        assert header_params["status_id"] == 21

    def test_create_enquiry_missing_date(self):
        resp = client.post(
            "/api/priceEnquiry/create_enquiry",
            json={
                "branch_id": "5",
                "items": [{"item_id": "1"}],
                "suppliers": [{"supplier_id": "1"}],
            },
        )
        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    def test_create_enquiry_empty_items(self):
        payload = self._valid_payload()
        payload["items"] = []
        resp = client.post("/api/priceEnquiry/create_enquiry", json=payload)
        assert resp.status_code == 400
        assert "item" in resp.json()["detail"].lower()

    def test_create_enquiry_empty_suppliers(self):
        payload = self._valid_payload()
        payload["suppliers"] = []
        resp = client.post("/api/priceEnquiry/create_enquiry", json=payload)
        assert resp.status_code == 400
        assert "supplier" in resp.json()["detail"].lower()


# =============================================================================
# ADD RESPONSE
# =============================================================================


class TestAddResponse(_BaseEnquiryTest):
    """add_response: workflow guards + gross/net totals computed and persisted."""

    def _guard_row(self, status_id=3, invited=1, existing_responses=0):
        return _mock_row({
            "status_id": status_id,
            "invited": invited,
            "existing_responses": existing_responses,
        })

    def _valid_payload(self):
        return {
            "enquiry_id": "10",
            "supplier_id": "100",
            "response_date": "2026-06-02",
            "items": [
                {"item_id": "1", "qty": "2", "rate": "50", "gross_amount": "100", "net_amount": "90"},
                {"item_id": "2", "qty": "1", "rate": "25", "gross_amount": "25", "net_amount": "20"},
            ],
        }

    def test_add_response_totals_summed_into_header(self):
        """REGRESSION: gross_amount/net_amount on the response header insert must
        equal the sum of the item gross/net amounts."""
        # guard SELECT, header insert -> lastrowid, then one dtl insert per item.
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=self._guard_row()),
            _result(lastrowid=555),  # header
            _result(),               # dtl 1
            _result(),               # dtl 2
        ])

        resp = client.post("/api/priceEnquiry/add_response", json=self._valid_payload())
        assert resp.status_code == 200, resp.text
        assert resp.json()["response_id"] == 555

        calls = self._mock_session.execute.call_args_list
        header_params = calls[1].args[1]
        # 100 + 25 = 125 gross; 90 + 20 = 110 net
        assert header_params["gross_amount"] == 125.0
        assert header_params["net_amount"] == 110.0

    def test_add_response_empty_items(self):
        resp = client.post(
            "/api/priceEnquiry/add_response",
            json={"enquiry_id": "10", "supplier_id": "100", "items": []},
        )
        assert resp.status_code == 400
        assert "item" in resp.json()["detail"].lower()

    def test_add_response_rejected_when_enquiry_not_approved(self):
        """REGRESSION: quotes can only be recorded once the enquiry is Approved."""
        self._mock_session.execute.side_effect = [
            _result(fetchone=self._guard_row(status_id=21)),
        ]
        resp = client.post("/api/priceEnquiry/add_response", json=self._valid_payload())
        assert resp.status_code == 400
        assert "approved" in resp.json()["detail"].lower()

    def test_add_response_rejected_when_supplier_not_invited(self):
        """REGRESSION: only invited suppliers can quote."""
        self._mock_session.execute.side_effect = [
            _result(fetchone=self._guard_row(invited=0)),
        ]
        resp = client.post("/api/priceEnquiry/add_response", json=self._valid_payload())
        assert resp.status_code == 400
        assert "not part of this enquiry" in resp.json()["detail"].lower()

    def test_add_response_conflict_when_duplicate(self):
        """REGRESSION: one active response per (enquiry, supplier)."""
        self._mock_session.execute.side_effect = [
            _result(fetchone=self._guard_row(existing_responses=1)),
        ]
        resp = client.post("/api/priceEnquiry/add_response", json=self._valid_payload())
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_add_response_invalid_date_rejected(self):
        """REGRESSION: invalid response_date must 400, not silently coerce."""
        payload = self._valid_payload()
        payload["response_date"] = "02-06-2026"
        resp = client.post("/api/priceEnquiry/add_response", json=payload)
        assert resp.status_code == 400
        assert "response_date" in resp.json()["detail"].lower()


# =============================================================================
# SELECT RESPONSE
# =============================================================================


class TestSelectResponse(_BaseEnquiryTest):
    """select_response: gated on enquiry being Approved (status 3)."""

    def test_select_response_rejected_when_not_approved(self):
        """REGRESSION: must be 400 when parent enquiry status_id != 3."""
        status_row = _mock_row({
            "proc_price_enquiry_response_id": 1,
            "enquiry_id": 10,
            "status_id": 1,  # Open, not Approved
        })
        self._mock_session.execute.side_effect = [_result(fetchone=status_row)]

        resp = client.post(
            "/api/priceEnquiry/select_response",
            json={"response_id": "1", "enquiry_id": "10"},
        )
        assert resp.status_code == 400
        assert "approved" in resp.json()["detail"].lower()

    def test_select_response_success_when_approved(self):
        """200 when parent enquiry status_id == 3 (Approved)."""
        status_row = _mock_row({
            "proc_price_enquiry_response_id": 1,
            "enquiry_id": 10,
            "status_id": 3,  # Approved
        })
        self._mock_session.execute.side_effect = [
            _result(fetchone=status_row),  # status gate
            _result(),                     # atomic select update
        ]

        resp = client.post(
            "/api/priceEnquiry/select_response",
            json={"response_id": "1", "enquiry_id": "10"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["response_id"] == 1

    def test_select_response_enquiry_mismatch(self):
        """REGRESSION: 400 when the response belongs to a different enquiry."""
        status_row = _mock_row({
            "proc_price_enquiry_response_id": 1,
            "enquiry_id": 999,  # mismatch vs payload enquiry_id=10
            "status_id": 3,
        })
        self._mock_session.execute.side_effect = [_result(fetchone=status_row)]

        resp = client.post(
            "/api/priceEnquiry/select_response",
            json={"response_id": "1", "enquiry_id": "10"},
        )
        assert resp.status_code == 400
        assert "does not belong" in resp.json()["detail"].lower()

    def test_select_response_not_found(self):
        """404 when no matching response row."""
        self._mock_session.execute.side_effect = [_result(fetchone=None)]

        resp = client.post(
            "/api/priceEnquiry/select_response",
            json={"response_id": "1", "enquiry_id": "10"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# =============================================================================
# CANCEL ENQUIRY
# =============================================================================


class TestCancelEnquiry(_BaseEnquiryTest):
    """cancel_enquiry: allowed from Draft (21) or Open (1) only — Approved
    enquiries cannot be cancelled (matches the frontend gating)."""

    @pytest.mark.parametrize("current_status", [21, 1])
    def test_cancel_success_from_draft_or_open(self, current_status):
        info_row = _mock_row({"enquiry_id": 10, "status_id": current_status})
        self._mock_session.execute.side_effect = [
            _result(fetchone=info_row),  # info lookup
            _result(),                   # status update -> 6
        ]

        resp = client.post("/api/priceEnquiry/cancel_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status_id"] == 6

    @pytest.mark.parametrize("current_status", [20, 5, 6, 3])
    def test_cancel_rejected_when_pending_closed_cancelled_or_approved(self, current_status):
        info_row = _mock_row({"enquiry_id": 10, "status_id": current_status})
        self._mock_session.execute.side_effect = [_result(fetchone=info_row)]

        resp = client.post("/api/priceEnquiry/cancel_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 400
        assert "cancelled" in resp.json()["detail"].lower()

    def test_cancel_not_found(self):
        self._mock_session.execute.side_effect = [_result(fetchone=None)]
        resp = client.post("/api/priceEnquiry/cancel_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# =============================================================================
# REOPEN ENQUIRY
# =============================================================================


class TestReopenEnquiry(_BaseEnquiryTest):
    """reopen_enquiry: allowed only from Cancelled (6) or Rejected (4)."""

    @pytest.mark.parametrize("current_status", [6, 4])
    def test_reopen_success_from_cancelled_or_rejected(self, current_status):
        info_row = _mock_row({"enquiry_id": 10, "status_id": current_status})
        self._mock_session.execute.side_effect = [
            _result(fetchone=info_row),  # info lookup
            _result(),                   # status update -> 21
        ]

        resp = client.post("/api/priceEnquiry/reopen_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status_id"] == 21

    def test_reopen_rejected_when_open(self):
        info_row = _mock_row({"enquiry_id": 10, "status_id": 1})  # Open
        self._mock_session.execute.side_effect = [_result(fetchone=info_row)]

        resp = client.post("/api/priceEnquiry/reopen_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 400
        assert "cancelled or rejected" in resp.json()["detail"].lower()

    def test_reopen_not_found(self):
        self._mock_session.execute.side_effect = [_result(fetchone=None)]
        resp = client.post("/api/priceEnquiry/reopen_enquiry", json={"enquiry_id": "10"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# =============================================================================
# REQUIRED PARAM VALIDATION
# =============================================================================


class TestRequiredParams(_BaseEnquiryTest):
    """Missing required query params -> 400."""

    def test_get_enquiry_table_missing_branch_ids(self):
        resp = client.get("/api/priceEnquiry/get_enquiry_table")
        assert resp.status_code == 400
        assert "branch_ids" in resp.json()["detail"].lower()

    def test_get_enquiry_by_id_missing_enquiry_id(self):
        resp = client.get("/api/priceEnquiry/get_enquiry_by_id")
        assert resp.status_code == 400
        assert "enquiry_id" in resp.json()["detail"].lower()

    def test_get_approved_indent_items_missing_branch_id(self):
        resp = client.get("/api/priceEnquiry/get_approved_indent_items")
        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()

    def test_get_response_by_id_missing_response_id(self):
        resp = client.get("/api/priceEnquiry/get_response_by_id")
        assert resp.status_code == 400
        assert "response_id" in resp.json()["detail"].lower()


# =============================================================================
# APPROVAL ENDPOINTS (process_approval / process_rejection patched)
# =============================================================================


class TestApprovalEndpoints(_BaseEnquiryTest):
    """send_for_approval / approve / reject with the approval util patched."""

    def test_approve_enquiry_success(self):
        with patch(
            "src.procurement.price_enquiry.process_approval",
            return_value={"status": "success", "new_status_id": 3},
        ):
            resp = client.post(
                "/api/priceEnquiry/approve_enquiry",
                json={"enquiry_id": "10", "menu_id": "5"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status_id"] == 3

    def test_reject_enquiry_success(self):
        with patch(
            "src.procurement.price_enquiry.process_rejection",
            return_value={"status": "success", "new_status_id": 4},
        ):
            resp = client.post(
                "/api/priceEnquiry/reject_enquiry",
                json={"enquiry_id": "10", "menu_id": "5", "reason": "too costly"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["new_status_id"] == 4

    def test_send_for_approval_wrong_status(self):
        """400 when enquiry not in Draft/Open."""
        info_row = _mock_row({
            "enquiry_id": 10,
            "status_id": 3,  # Approved -> cannot send for approval
            "approval_level": None,
            "branch_id": 5,
        })
        self._mock_session.execute.side_effect = [_result(fetchone=info_row)]

        resp = client.post(
            "/api/priceEnquiry/send_for_approval",
            json={"enquiry_id": "10", "menu_id": "5"},
        )
        assert resp.status_code == 400
        assert "draft or open" in resp.json()["detail"].lower()

    def test_send_for_approval_not_found(self):
        self._mock_session.execute.side_effect = [_result(fetchone=None)]
        resp = client.post(
            "/api/priceEnquiry/send_for_approval",
            json={"enquiry_id": "10", "menu_id": "5"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.parametrize("current_status", [21, 1])
    def test_send_for_approval_moves_to_pending(self, current_status):
        """Draft/Open -> 20 Pending Approval (level 1). Approval is a separate
        /approve_enquiry click even with no hierarchy configured, so Reject
        stays reachable. The status UPDATE runs update_enquiry_status(),
        whose SQL references :enquiry_no — the call site must supply it (as
        None) or SQLAlchemy raises StatementError at runtime."""
        info_row = _mock_row({
            "enquiry_id": 10,
            "status_id": current_status,
            "approval_level": None,
            "branch_id": 5,
        })
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=info_row),  # approval info lookup
            _result(),                   # status UPDATE -> 20
        ])

        resp = client.post(
            "/api/priceEnquiry/send_for_approval",
            json={"enquiry_id": "10", "menu_id": "5"},
        )

        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["new_status_id"] == 20
        assert body["new_approval_level"] == 1


# =============================================================================
# UPDATE ENQUIRY (draft-only guard + bind completeness)
# =============================================================================


class TestUpdateEnquiry(_BaseEnquiryTest):
    """update_enquiry: draft-only, complete binds, supplier upsert."""

    def _valid_payload(self):
        return {
            "enquiry_id": "10",
            "branch_id": "5",
            "date": "2026-06-01",
            "items": [{"item_id": "10", "qty": "3", "uom_id": "1"}],
            "suppliers": [{"supplier_id": "100"}],
        }

    def test_update_enquiry_success_supplies_all_binds(self):
        """REGRESSION: update_proc_enquiry() references :enquiry_no/:active/
        :status_id — the endpoint must supply them (as None passthroughs)."""
        status_row = _mock_row({"enquiry_id": 10, "status_id": 21, "approval_level": None, "branch_id": 5})
        branch_row = _mock_row({"co_id": 77})
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=status_row),  # draft-status guard
            _result(fetchone=branch_row),  # co_id from branch
            _result(),                     # header UPDATE
            _result(),                     # dtl soft-delete
            _result(),                     # dtl insert
            _result(),                     # supplier soft-delete
            _result(),                     # supplier upsert
        ])

        resp = client.put("/api/priceEnquiry/update_enquiry", json=self._valid_payload())
        assert resp.status_code == 200, resp.text

        # The supplier re-insert must be an upsert so re-adding a kept supplier
        # doesn't violate uk_enquiry_supplier on the soft-deleted row.
        supplier_sql = str(self._mock_session.execute.call_args_list[-1].args[0]).lower()
        assert "on duplicate key update" in supplier_sql

    def test_update_enquiry_rejected_when_not_draft(self):
        """REGRESSION: only Draft (21) enquiries may be rewritten."""
        status_row = _mock_row({"enquiry_id": 10, "status_id": 3, "approval_level": None, "branch_id": 5})
        self._mock_session.execute.side_effect = [_result(fetchone=status_row)]

        resp = client.put("/api/priceEnquiry/update_enquiry", json=self._valid_payload())
        assert resp.status_code == 400
        assert "draft" in resp.json()["detail"].lower()

    def test_update_enquiry_not_found(self):
        self._mock_session.execute.side_effect = [_result(fetchone=None)]
        resp = client.put("/api/priceEnquiry/update_enquiry", json=self._valid_payload())
        assert resp.status_code == 404


# =============================================================================
# UPDATE RESPONSE (guards)
# =============================================================================


class TestUpdateResponse(_BaseEnquiryTest):
    """update_response: items required, frozen after award/closure."""

    def _valid_payload(self):
        return {
            "response_id": "7",
            "supplier_id": "100",
            "response_date": "2026-06-03",
            "items": [
                {"item_id": "1", "qty": "2", "rate": "45", "gross_amount": "90", "net_amount": "90"},
            ],
        }

    def _guard_row(self, status_id=3, is_selected=0):
        return _mock_row({
            "proc_price_enquiry_response_id": 7,
            "enquiry_id": 10,
            "is_selected": is_selected,
            "status_id": status_id,
        })

    def test_update_response_success(self):
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=self._guard_row()),  # guard lookup
            _result(),                            # header UPDATE
            _result(),                            # dtl soft-delete
            _result(),                            # dtl insert
        ])
        resp = client.put("/api/priceEnquiry/update_response", json=self._valid_payload())
        assert resp.status_code == 200, resp.text

    def test_update_response_requires_items(self):
        """REGRESSION: omitting items used to zero the header totals."""
        payload = self._valid_payload()
        del payload["items"]
        resp = client.put("/api/priceEnquiry/update_response", json=payload)
        assert resp.status_code == 400
        assert "item" in resp.json()["detail"].lower()

    def test_update_response_frozen_after_award(self):
        self._mock_session.execute.side_effect = [
            _result(fetchone=self._guard_row(is_selected=1)),
        ]
        resp = client.put("/api/priceEnquiry/update_response", json=self._valid_payload())
        assert resp.status_code == 400
        assert "awarded" in resp.json()["detail"].lower()

    @pytest.mark.parametrize("status_id", [5, 6])
    def test_update_response_blocked_on_closed_or_cancelled(self, status_id):
        self._mock_session.execute.side_effect = [
            _result(fetchone=self._guard_row(status_id=status_id)),
        ]
        resp = client.put("/api/priceEnquiry/update_response", json=self._valid_payload())
        assert resp.status_code == 400

    def test_update_response_not_found(self):
        self._mock_session.execute.side_effect = [_result(fetchone=None)]
        resp = client.put("/api/priceEnquiry/update_response", json=self._valid_payload())
        assert resp.status_code == 404


# =============================================================================
# SETUP / COMPARISON SUCCESS PATHS
# =============================================================================


class TestSetupAndComparison(_BaseEnquiryTest):
    """Success-path coverage for get_enquiry_setup and comparison grouping."""

    def test_get_enquiry_setup_success(self):
        branch_row = _mock_row({"branch_id": 5, "branch_name": "Main"})
        supp_row = _mock_row({"party_id": 100, "supplier_name": "Acme", "supplier_code": "AC01"})
        exp_row = _mock_row({"expense_type_id": 2, "expense_type_name": "Stores"})
        self._mock_session.execute.side_effect = [
            _result(fetchall=[branch_row]),
            _result(fetchall=[supp_row]),
            _result(fetchall=[exp_row]),
        ]

        resp = client.get("/api/priceEnquiry/get_enquiry_setup?co_id=1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["branches"][0]["branch_id"] == 5
        # Supplier aliases are remapped to the supp_name/supp_code contract.
        assert body["suppliers"][0] == {"party_id": 100, "supp_name": "Acme", "supp_code": "AC01"}
        assert body["expense_types"][0]["expense_type_id"] == 2
        assert body["projects"] == []

    def test_get_responses_for_comparison_groups_lines_by_response(self):
        def _row(rid, dtl, item):
            return _mock_row({
                "proc_price_enquiry_response_id": rid,
                "supplier_id": 100 + rid,
                "supp_name": f"Supplier {rid}",
                "supp_code": f"S{rid}",
                "date": "2026-06-02",
                "credit_days": 30,
                "delivery_days": 10,
                "payment_terms": None,
                "terms_conditions": None,
                "resp_gross_amount": 100.0,
                "resp_net_amount": 90.0,
                "is_selected": 0,
                "enquiry_dtl_id": dtl,
                "item_id": item,
                "item_code": f"IT-{item}",
                "item_name": f"Item {item}",
                "uom_name": "PCS",
                "qty": 2.0,
                "rate": 50.0,
                "discount_mode": None,
                "discount_value": None,
                "discount_amount": None,
                "dtl_gross_amount": 100.0,
                "dtl_net_amount": 90.0,
            })

        self._mock_session.execute.side_effect = [
            _result(fetchall=[_row(1, 11, 1), _row(1, 12, 2), _row(2, 11, 1)]),
        ]

        resp = client.get("/api/priceEnquiry/get_responses_for_comparison?enquiry_id=10")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) == 2
        by_id = {r["proc_price_enquiry_response_id"]: r for r in data}
        assert len(by_id[1]["items"]) == 2
        assert len(by_id[2]["items"]) == 1
        assert by_id[1]["supp_name"] == "Supplier 1"


# =============================================================================
# MARK RFQ SENT
# =============================================================================


class TestMarkRfqSent(_BaseEnquiryTest):
    """mark_rfq_sent: approved-only gate + sent flags update."""

    def test_mark_sent_success_all_suppliers(self):
        info_row = _mock_row({"enquiry_id": 10, "status_id": 3, "approval_level": None, "branch_id": 5})
        update_result = _result()
        update_result.rowcount = 3
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=info_row),
            update_result,
        ])

        resp = client.post("/api/priceEnquiry/mark_rfq_sent", json={"enquiry_id": "10"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["updated"] == 3

        sent_sql = str(self._mock_session.execute.call_args_list[-1].args[0]).lower()
        assert "sent_status = 1" in sent_sql
        assert "supplier_id in" not in sent_sql

    def test_mark_sent_subset_of_suppliers(self):
        info_row = _mock_row({"enquiry_id": 10, "status_id": 3, "approval_level": None, "branch_id": 5})
        update_result = _result()
        update_result.rowcount = 1
        self._mock_session.execute.side_effect = _bind_checking_execute([
            _result(fetchone=info_row),
            update_result,
        ])

        resp = client.post(
            "/api/priceEnquiry/mark_rfq_sent",
            json={"enquiry_id": "10", "supplier_ids": ["100"]},
        )
        assert resp.status_code == 200, resp.text
        sent_sql = str(self._mock_session.execute.call_args_list[-1].args[0]).lower()
        assert "supplier_id in" in sent_sql

    def test_mark_sent_rejected_when_not_approved(self):
        info_row = _mock_row({"enquiry_id": 10, "status_id": 21, "approval_level": None, "branch_id": 5})
        self._mock_session.execute.side_effect = [_result(fetchone=info_row)]

        resp = client.post("/api/priceEnquiry/mark_rfq_sent", json={"enquiry_id": "10"})
        assert resp.status_code == 400
        assert "approved" in resp.json()["detail"].lower()


# =============================================================================
# PO PREFILL (award gate)
# =============================================================================


class TestPOPrefillGate(_BaseEnquiryTest):
    """get_po_prefill_data: only the awarded response can seed a PO."""

    def _prefill_row(self, is_selected):
        return _mock_row({
            "supplier_id": 100,
            "supplier_branch_id": 200,
            "credit_days": 30,
            "delivery_days": 10,
            "terms_conditions": None,
            "payment_terms": None,
            "enquiry_id": 10,
            "is_selected": is_selected,
            "branch_id": 5,
            "expense_type_id": 2,
            "project_id": None,
            "enquiry_dtl_id": 1,
            "item_id": 1,
            "item_make_id": None,
            "uom_id": 1,
            "qty": 2.0,
            "rate": 50.0,
            "discount_mode": None,
            "discount_value": None,
            "discount_amount": None,
            "indent_dtl_id": None,
            "item_code": "IT-1",
            "item_name": "Item 1",
            "hsn_code": None,
            "uom_name": "PCS",
            "item_make_name": None,
        })

    def test_prefill_rejected_for_unselected_response(self):
        self._mock_session.execute.side_effect = [
            _result(fetchall=[self._prefill_row(is_selected=0)]),
        ]
        resp = client.get("/api/priceEnquiry/get_po_prefill_data?response_id=7")
        assert resp.status_code == 400
        assert "selected" in resp.json()["detail"].lower()

    def test_prefill_success_for_selected_response(self):
        self._mock_session.execute.side_effect = [
            _result(fetchall=[self._prefill_row(is_selected=1)]),
        ]
        resp = client.get("/api/priceEnquiry/get_po_prefill_data?response_id=7")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["supplier_id"] == 100
        assert len(data["items"]) == 1
        assert data["items"][0]["qty"] == 2.0
