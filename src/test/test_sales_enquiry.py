"""Endpoint tests for src/sales/enquiry.py (AMCL enquiry flow, Phase 1).

The enquiry router is not (yet) mounted on the main app, so we build a local
FastAPI app, include the router under its production prefix /api/salesEnquiry,
and use dependency_overrides for get_tenant_db + get_current_user_with_refresh
— the same override style as test_spinning_entry.py / test_sales_reports_lists.py.

DB access is fully mocked: the MagicMock session dispatches on distinctive SQL
substrings so multi-query handlers (flow-state fetch + stage-master lookup +
stage-log insert + header update) each get the right result. The approval-chain
endpoints patch process_approval / process_rejection at the router module path
(src.sales.enquiry.*).

Covers:
- get_enquiry_table / get_enquiry_setup / get_enquiry_by_id success + missing
  co_id 400
- create_enquiry (draft 21) + payload validation
- open_enquiry: mints the ENQ number (max+1 per branch+FY) + stage ENQ_NOTED
- approve/reject delegate to process_approval / process_rejection; reject
  persists the reason into flow_stage_log as a stage-preserving AUTO entry
- move_stage matrix: FORWARD ENQ_NOTED->COSTING_REVIEW gated on status 3 (403);
  SEND_BACK feedback mandatory; MARK_LOST blocked past sequence 50; HOLD/RESUME
- close_enquiry (won -> CLOSED; lost blocked from a late stage)
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.sales.enquiry import router as enquiry_router
from src.sales.enquiry_constants import (
    ENQUIRY_STAGE_CODES,
    ENQUIRY_STATUS_IDS,
    STAGE_SEQUENCE,
    TERMINAL_STAGES,
)

app = FastAPI()
app.include_router(enquiry_router, prefix="/api/salesEnquiry")
client = TestClient(app)

BASE = "/api/salesEnquiry"

# Deterministic flow_stage_mst.stage_id per stage code for the mocks.
STAGE_IDS = {code: 100 + i for i, code in enumerate(ENQUIRY_STAGE_CODES, start=1)}


# =============================================================================
# MOCK HELPERS
# =============================================================================

def _row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _result(fetchall=None, fetchone=None, scalar=None, lastrowid=0):
    """A MagicMock standing in for a SQLAlchemy CursorResult."""
    result = MagicMock()
    result.fetchall.return_value = fetchall if fetchall is not None else []
    result.fetchone.return_value = fetchone
    result.scalar.return_value = scalar
    result.lastrowid = lastrowid
    return result


_EMPTY = None  # sentinel doc: unmatched SQL falls through to an empty result


def _stage_lookup_result(params: dict):
    """flow_stage_mst row for the get_stage_by_code_query bind params."""
    stage_code = params["stage_code"]
    if stage_code not in STAGE_IDS:
        return _result(fetchone=None)
    return _result(fetchone=_row({
        "stage_id": STAGE_IDS[stage_code],
        "stage_code": stage_code,
        "stage_name": stage_code.replace("_", " ").title(),
        "dept_hint": None,
        "sequence_no": STAGE_SEQUENCE[stage_code],
        "is_terminal": 1 if stage_code in TERMINAL_STAGES else 0,
    }))


def make_session(handlers=()):
    """MagicMock session whose execute() dispatches on SQL substrings.

    handlers: ordered iterable of (sql_marker, result_or_callable). The first
    marker found in str(query) wins; a callable receives the bind params and
    returns the result. Unmatched SQL gets an empty result (fetchall [],
    fetchone None) so incidental queries never crash a test.
    """
    session = MagicMock()

    def _execute(query, params=None):
        sql = str(query)
        for marker, result in handlers:
            if marker in sql:
                if isinstance(result, MagicMock):
                    return result
                if callable(result):  # param-aware handler (e.g. stage lookup)
                    return result(params or {})
                return result
        return _result()

    session.execute.side_effect = _execute
    return session


def _params_for(session, marker):
    """Bind-param dicts of every execute() call whose SQL contains marker."""
    out = []
    for call in session.execute.call_args_list:
        sql = str(call.args[0])
        if marker in sql:
            out.append(call.args[1] if len(call.args) > 1 else call.kwargs.get("params"))
    return out


def _flow_state(**overrides):
    """A get_enquiry_flow_state_query row mapping (opened enquiry defaults)."""
    stage_code = overrides.pop("stage_code", "ENQ_NOTED")
    state = {
        "sales_enquiry_id": 5,
        "enquiry_no": "42",
        "enquiry_date": date(2026, 5, 1),
        "branch_id": 4,
        "co_id": 1,
        "party_id": 9,
        "status_id": ENQUIRY_STATUS_IDS["OPEN"],
        "approval_level": None,
        "current_stage_id": STAGE_IDS[stage_code] if stage_code else None,
        "stage_code": stage_code,
        "sequence_no": STAGE_SEQUENCE[stage_code] if stage_code else None,
        "is_terminal": 0,
        "stage_since": date(2026, 5, 1),
        "hold_flag": 0,
        "close_reason": None,
        "project_id": None,
        "active": 1,
    }
    state.update(overrides)
    return state


# SQL markers (distinctive substrings of the statements in enquiry.py /
# enquiry_query.py — dispatch keys for make_session and _params_for).
M_FLOW_STATE = "se.stage_since,"                             # get_enquiry_flow_state_query
M_STAGE_BY_CODE = "fsm.stage_code = :stage_code"             # get_stage_by_code_query
M_INSERT_LOG = "INSERT INTO flow_stage_log"                  # insert_flow_stage_log
M_UPDATE_STAGE_PTR = "current_stage_id = :current_stage_id"  # update_enquiry_current_stage
M_UPDATE_STATUS = "enquiry_no = CASE"                        # update_enquiry_status
M_UPDATE_HOLD = "hold_flag = :hold_flag"                     # update_enquiry_hold_flag
M_UPDATE_CLOSE = "close_reason = :close_reason"              # update_enquiry_close
M_MAX_NO = "MAX(CAST(se.enquiry_no AS UNSIGNED))"            # get_max_enquiry_no_for_branch_fy
M_INSERT_HDR = "INSERT INTO sales_enquiry ("                 # insert_sales_enquiry
M_INSERT_DTL = "INSERT INTO sales_enquiry_dtl"               # insert_sales_enquiry_dtl
M_TABLE_COUNT = "COUNT(1) AS total"                          # get_enquiry_table_count_query
M_TABLE = "FROM sales_enquiry AS se"                         # get_enquiry_table_query (+by_id)
M_BY_ID_HDR = "LEFT JOIN co_mst AS cm"                       # get_enquiry_by_id_query
M_DTL_BY_ID = "FROM sales_enquiry_dtl AS sed"                # get_enquiry_dtl_by_id_query
M_STAGE_LOG = "FROM flow_stage_log AS fsl"                   # get_enquiry_stage_log_query
M_LINKED = "FROM sales_quotation AS sq"                      # get_enquiry_linked_docs_query
M_CUSTOMERS = "FROM party_mst pm"                            # get_customers_for_sales
M_UOMS = "FROM uom_mst um\nWHERE"                            # get_uom_list
M_ITEMS = "FROM item_mst im"                                 # get_items_with_group_query
M_STAGES_LIST = "ORDER BY fsm.sequence_no"                   # get_stages_by_module_query
M_MENU_BY_PATH = "menu_path = :menu_path"                    # get_menu_id_by_path_query
PENDING_MARKER = "OR sed.overhead_pct IS NULL"                # get_enquiry_costing_pending_query
                                                               # (unique — only this query tests
                                                               #  overhead_pct IS NULL at all)

# Common handler: canonical Customer Enquiry menu resolution (menu_mst row).
H_CANONICAL_MENU = (M_MENU_BY_PATH, _result(fetchone=_row({"menu_id": 961})))

# Common handler: stage-master lookup by code (used by log_stage_transition).
H_STAGE_BY_CODE = (M_STAGE_BY_CODE, _stage_lookup_result)


def _state_handler(state: dict):
    return (M_FLOW_STATE, _result(fetchone=_row(state)))


class EnquiryTestBase:
    """Installs dependency overrides; subclasses set self.session per test."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self.session = make_session()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self.session
        yield
        app.dependency_overrides.clear()

    def use_session(self, handlers):
        self.session = make_session(handlers)
        app.dependency_overrides[get_tenant_db] = lambda: self.session
        return self.session


# =============================================================================
# get_enquiry_table
# =============================================================================

class TestEnquiryTable(EnquiryTestBase):
    URL = f"{BASE}/get_enquiry_table"

    def test_missing_co_id_returns_400(self):
        resp = client.get(self.URL)
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_table_success(self):
        table_row = _row({
            "sales_enquiry_id": 5,
            "enquiry_no": 42,
            "enquiry_date": date(2026, 5, 1),
            "received_via": "email",
            "branch_id": 4,
            "branch_name": "HQ",
            "party_id": 9,
            "party_name": "TEST PARTY",
            "contact_person": "Mr. X",
            "customer_ref_no": "REF-1",
            "expected_delivery_date": None,
            "current_stage_id": STAGE_IDS["ENQ_NOTED"],
            "stage_code": "ENQ_NOTED",
            "stage_name": "Enquiry Noted",
            "dept_hint": "SALES",
            "days_in_stage": 3,
            "hold_flag": 0,
            "status_id": 1,
            "status_name": "Open",
            "close_reason": None,
            "project_id": None,
        })
        session = self.use_session([
            (M_TABLE_COUNT, _result(scalar=1)),   # count first: shares FROM marker
            (M_TABLE, _result(fetchall=[table_row])),
        ])

        resp = client.get(f"{self.URL}?co_id=1&branch_id=4")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["data"]) == 1
        first = body["data"][0]
        assert first["sales_enquiry_id"] == 5
        assert first["enquiry_no_raw"] == 42
        assert "ENQ" in first["enquiry_no"]  # formatted document number
        assert first["stage_code"] == "ENQ_NOTED"
        assert first["status"] == "Open"

        # co_id / branch_id are bound as ints on both queries.
        list_params = _params_for(session, M_TABLE)[0]
        assert list_params["co_id"] == 1
        assert list_params["branch_id"] == 4


# =============================================================================
# get_enquiry_setup
# =============================================================================

class TestEnquirySetup(EnquiryTestBase):
    URL = f"{BASE}/get_enquiry_setup"

    def test_missing_co_id_returns_400(self):
        resp = client.get(self.URL)
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_setup_success(self):
        self.use_session([
            (M_CUSTOMERS, _result(fetchall=[_row({"party_id": 9, "party_name": "TEST PARTY"})])),
            (M_ITEMS, _result(fetchall=[_row({"item_id": 3, "item_name": "Bag", "uom_id": 1})])),
            (M_UOMS, _result(fetchall=[_row({"uom_id": 1, "uom_name": "PCS"})])),
            (M_STAGES_LIST, _result(fetchall=[_row({
                "stage_id": STAGE_IDS["ENQ_NOTED"], "stage_code": "ENQ_NOTED",
                "stage_name": "Enquiry Noted", "dept_hint": "SALES",
                "sequence_no": 10, "is_terminal": 0,
            })])),
        ])

        resp = client.get(f"{self.URL}?co_id=1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["customers"][0]["party_id"] == 9
        assert data["uoms"][0]["uom_name"] == "PCS"
        assert data["items"][0]["item_id"] == 3
        assert data["stages"][0]["stage_code"] == "ENQ_NOTED"
        assert "email" in data["received_via_options"]
        assert data["iso_doc_no"] is None  # no menu_id passed


# =============================================================================
# get_enquiry_by_id
# =============================================================================

class TestEnquiryById(EnquiryTestBase):
    URL = f"{BASE}/get_enquiry_by_id"

    def test_missing_co_id_returns_400(self):
        resp = client.get(f"{self.URL}?sales_enquiry_id=5")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_sales_enquiry_id_returns_400(self):
        resp = client.get(f"{self.URL}?co_id=1")
        assert resp.status_code == 400
        assert "sales_enquiry_id" in resp.json()["detail"].lower()

    def test_not_found_returns_404(self):
        self.use_session([(M_BY_ID_HDR, _result(fetchone=None))])
        resp = client.get(f"{self.URL}?sales_enquiry_id=999&co_id=1")
        assert resp.status_code == 404

    def test_by_id_success(self):
        header = _row({
            "sales_enquiry_id": 5,
            "enquiry_no": 42,
            "enquiry_date": date(2026, 5, 1),
            "received_via": "email",
            "branch_id": 4,
            "branch_name": "HQ",
            "branch_prefix": "HQ",
            "co_id": 1,
            "co_prefix": "ABC",
            "co_name": "ABC Mills",
            "party_id": 9,
            "party_name": "TEST PARTY",
            "contact_person": None,
            "contact_detail": None,
            "customer_ref_no": None,
            "expected_delivery_date": None,
            "enquiry_desc": "10k bags",
            "internal_note": None,
            "current_stage_id": STAGE_IDS["ENQ_NOTED"],
            "stage_code": "ENQ_NOTED",
            "stage_name": "Enquiry Noted",
            "dept_hint": "SALES",
            "sequence_no": 10,
            "is_terminal": 0,
            "stage_since": date(2026, 5, 1),
            "days_in_stage": 3,
            "hold_flag": 0,
            "status_id": 1,
            "status_name": "Open",
            "close_reason": None,
            "lost_remarks": None,
            "project_id": None,
            "project_name": None,
            "updated_by": 1,
            "updated_date_time": None,
            "approval_level": None,
        })
        line = _row({
            "enquiry_dtl_id": 51, "sales_enquiry_id": 5, "item_id": 3,
            "item_desc_freetext": None, "qty": 10000.0, "uom_id": 1,
        })
        log_entry = _row({
            "stage_log_id": 1, "action": "CREATE",
            "to_stage_code": "ENQ_NOTED", "feedback": None,
        })
        session = self.use_session([
            (M_DTL_BY_ID, _result(fetchall=[line])),
            (M_STAGE_LOG, _result(fetchall=[log_entry])),
            (M_LINKED, _result(fetchall=[])),
            (M_BY_ID_HDR, _result(fetchone=header)),
        ])

        # No menu_id -> permissions block skipped (no approval query needed).
        resp = client.get(f"{self.URL}?sales_enquiry_id=5&co_id=1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["sales_enquiry_id"] == 5
        assert data["enquiry_no_raw"] == 42
        assert "ENQ" in data["enquiry_no"]
        assert data["enquiry_date"] == "2026-05-01"
        assert data["lines"][0]["enquiry_dtl_id"] == 51
        assert data["timeline"][0]["action"] == "CREATE"
        assert data["linked_docs"] == []
        assert "permissions" not in data

        hdr_params = _params_for(session, M_BY_ID_HDR)[0]
        assert hdr_params == {"sales_enquiry_id": 5, "co_id": 1}


# =============================================================================
# create_enquiry (draft)
# =============================================================================

class TestCreateEnquiry(EnquiryTestBase):
    URL = f"{BASE}/create_enquiry"

    PAYLOAD = {
        "branch_id": 4,
        "enquiry_date": "2026-05-01",
        "party_id": 9,
        "received_via": "email",
        "lines": [
            {"item_id": 3, "qty": 100, "uom_id": 1},
            {"item_desc_freetext": "New jumbo bag, 4-loop", "is_new_item": True},
        ],
    }

    def test_create_draft_success(self):
        session = self.use_session([(M_INSERT_HDR, _result(lastrowid=77))])

        resp = client.post(self.URL, json=self.PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["data"]["sales_enquiry_id"] == 77

        hdr_params = _params_for(session, M_INSERT_HDR)[0]
        assert hdr_params["status_id"] == ENQUIRY_STATUS_IDS["DRAFT"]  # 21
        assert hdr_params["approval_level"] == 0
        assert hdr_params["branch_id"] == 4
        assert hdr_params["updated_by"] == 1

        dtl_calls = _params_for(session, M_INSERT_DTL)
        assert len(dtl_calls) == 2
        assert dtl_calls[0]["item_id"] == 3
        assert dtl_calls[0]["sales_enquiry_id"] == 77
        assert dtl_calls[1]["item_id"] is None
        assert dtl_calls[1]["item_desc_freetext"] == "New jumbo bag, 4-loop"
        assert dtl_calls[1]["is_new_item"] == 1
        session.commit.assert_called_once()

    def test_create_missing_branch_returns_400(self):
        payload = {k: v for k, v in self.PAYLOAD.items() if k != "branch_id"}
        resp = client.post(self.URL, json=payload)
        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()

    def test_create_without_lines_returns_400(self):
        resp = client.post(self.URL, json={**self.PAYLOAD, "lines": []})
        assert resp.status_code == 400
        assert "line" in resp.json()["detail"].lower()

    def test_create_line_needs_item_or_freetext_400(self):
        payload = {**self.PAYLOAD, "lines": [{"qty": 5}]}
        resp = client.post(self.URL, json=payload)
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "item_id" in detail and "item_desc_freetext" in detail


# =============================================================================
# open_enquiry (21 -> 1: mint ENQ number + stage ENQ_NOTED)
# =============================================================================

class TestOpenEnquiry(EnquiryTestBase):
    URL = f"{BASE}/open_enquiry"

    def test_open_mints_number_and_sets_enq_noted(self):
        state = _flow_state(
            status_id=ENQUIRY_STATUS_IDS["DRAFT"],
            enquiry_no=None, stage_code=None, current_stage_id=None,
        )
        session = self.use_session([
            _state_handler(state),
            (M_MAX_NO, _result(fetchone=_row({"max_doc_no": 42}))),
            H_STAGE_BY_CODE,
        ])

        resp = client.post(self.URL, json={"sales_enquiry_id": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_status_id"] == ENQUIRY_STATUS_IDS["OPEN"]  # 1
        assert body["enquiry_no"] == "43"  # max 42 + 1 within branch+FY
        assert body["stage_code"] == "ENQ_NOTED"

        # FY boundaries derived from the enquiry date (2026-05-01 -> FY 26-27).
        max_params = _params_for(session, M_MAX_NO)[0]
        assert max_params["branch_id"] == 4
        assert max_params["fy_start_date"] == date(2026, 4, 1)
        assert max_params["fy_end_date"] == date(2027, 3, 31)

        status_params = _params_for(session, M_UPDATE_STATUS)[0]
        assert status_params["status_id"] == ENQUIRY_STATUS_IDS["OPEN"]
        assert status_params["enquiry_no"] == "43"

        # CREATE stage-log entry: NULL -> ENQ_NOTED, header pointer synced.
        log_params = _params_for(session, M_INSERT_LOG)[0]
        assert log_params["action"] == "CREATE"
        assert log_params["from_stage_id"] is None
        assert log_params["to_stage_id"] == STAGE_IDS["ENQ_NOTED"]
        ptr_params = _params_for(session, M_UPDATE_STAGE_PTR)[0]
        assert ptr_params["current_stage_id"] == STAGE_IDS["ENQ_NOTED"]
        session.commit.assert_called_once()

    def test_open_missing_sales_enquiry_id_returns_400(self):
        resp = client.post(self.URL, json={})
        assert resp.status_code == 400
        assert "sales_enquiry_id" in resp.json()["detail"].lower()

    def test_open_rejects_non_draft_status_400(self):
        self.use_session([_state_handler(_flow_state(status_id=ENQUIRY_STATUS_IDS["OPEN"]))])
        resp = client.post(self.URL, json={"sales_enquiry_id": 5})
        assert resp.status_code == 400
        assert "21" in resp.json()["detail"]

    def test_open_requires_party_400(self):
        state = _flow_state(
            status_id=ENQUIRY_STATUS_IDS["DRAFT"], party_id=None,
            stage_code=None, current_stage_id=None,
        )
        self.use_session([_state_handler(state)])
        resp = client.post(self.URL, json={"sales_enquiry_id": 5})
        assert resp.status_code == 400
        assert "party" in resp.json()["detail"].lower()


# =============================================================================
# APPROVAL CHAIN (delegates to src.common.approval_utils, patched here)
# =============================================================================

class TestApprovalChain(EnquiryTestBase):
    @patch("src.sales.enquiry.process_approval")
    def test_approve_delegates_to_process_approval(self, mock_approve):
        sentinel = {"status": "success", "new_status_id": 3, "message": "Enquiry approved."}
        mock_approve.return_value = sentinel

        resp = client.post(f"{BASE}/approve_enquiry", json={"sales_enquiry_id": 5, "menu_id": 7})
        assert resp.status_code == 200
        assert resp.json() == sentinel

        mock_approve.assert_called_once()
        kwargs = mock_approve.call_args.kwargs
        assert kwargs["doc_id"] == 5
        assert kwargs["menu_id"] == 7
        assert kwargs["id_param_name"] == "sales_enquiry_id"
        # Amount-less document: None skips value-based limit checks entirely.
        assert kwargs["document_amount"] is None

    @patch("src.sales.enquiry.process_approval")
    def test_approve_missing_menu_id_returns_400(self, mock_approve):
        # No canonical menu_mst row in the mock AND no client menu_id -> 400.
        resp = client.post(f"{BASE}/approve_enquiry", json={"sales_enquiry_id": 5})
        assert resp.status_code == 400
        assert "menu_id" in resp.json()["detail"].lower()
        mock_approve.assert_not_called()

    @patch("src.sales.enquiry.process_approval")
    def test_approve_canonical_menu_overrides_client_menu_id(self, mock_approve):
        # Entry points carry their own menu_id (Flow Board = 962, BOM review);
        # the approval check must always run against the Customer Enquiry menu.
        mock_approve.return_value = {"status": "success", "new_status_id": 3}
        self.use_session([H_CANONICAL_MENU])

        resp = client.post(f"{BASE}/approve_enquiry", json={"sales_enquiry_id": 5, "menu_id": 962})
        assert resp.status_code == 200
        assert mock_approve.call_args.kwargs["menu_id"] == 961

    @patch("src.sales.enquiry.process_approval")
    def test_approve_without_menu_id_uses_canonical_menu(self, mock_approve):
        # Direct-URL entry sends no menu_id; canonical resolution supplies it.
        mock_approve.return_value = {"status": "success", "new_status_id": 3}
        self.use_session([H_CANONICAL_MENU])

        resp = client.post(f"{BASE}/approve_enquiry", json={"sales_enquiry_id": 5})
        assert resp.status_code == 200
        assert mock_approve.call_args.kwargs["menu_id"] == 961

    @patch("src.sales.enquiry.process_rejection")
    def test_reject_delegates_and_persists_reason_to_flow_stage_log(self, mock_reject):
        sentinel = {"status": "success", "new_status_id": 4, "message": "Enquiry rejected."}
        mock_reject.return_value = sentinel
        # After process_rejection, the handler re-reads state and appends a
        # stage-preserving AUTO entry carrying the reason.
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW",
                                       status_id=ENQUIRY_STATUS_IDS["REJECTED"])),
            H_STAGE_BY_CODE,
        ])

        resp = client.post(
            f"{BASE}/reject_enquiry",
            json={"sales_enquiry_id": 5, "menu_id": 7, "reason": "Costing not viable"},
        )
        assert resp.status_code == 200
        assert resp.json() == sentinel

        mock_reject.assert_called_once()
        assert mock_reject.call_args.kwargs["reason"] == "Costing not viable"

        log_params = _params_for(session, M_INSERT_LOG)
        assert len(log_params) == 1
        assert log_params[0]["action"] == "AUTO"
        assert log_params[0]["feedback"] == "Costing not viable"
        assert log_params[0]["from_stage_id"] == STAGE_IDS["COSTING_REVIEW"]
        assert log_params[0]["to_stage_id"] == STAGE_IDS["COSTING_REVIEW"]
        # Stage unchanged -> header stage pointer must NOT be rewritten
        # (stage_since keeps its aging anchor).
        assert _params_for(session, M_UPDATE_STAGE_PTR) == []
        session.commit.assert_called_once()

    @patch("src.sales.enquiry.process_rejection")
    def test_reject_without_reason_writes_no_stage_log(self, mock_reject):
        mock_reject.return_value = {"status": "success", "new_status_id": 4}
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW")),
            H_STAGE_BY_CODE,
        ])

        resp = client.post(f"{BASE}/reject_enquiry", json={"sales_enquiry_id": 5, "menu_id": 7})
        assert resp.status_code == 200
        assert mock_reject.call_args.kwargs["reason"] is None
        assert _params_for(session, M_INSERT_LOG) == []


# =============================================================================
# move_stage matrix
# =============================================================================

class TestMoveStage(EnquiryTestBase):
    URL = f"{BASE}/move_stage"

    def _session_for_stage(self, stage_code, **state_overrides):
        return self.use_session([
            _state_handler(_flow_state(stage_code=stage_code, **state_overrides)),
            H_STAGE_BY_CODE,
        ])

    def test_missing_action_returns_400(self):
        resp = client.post(self.URL, json={"sales_enquiry_id": 5})
        assert resp.status_code == 400
        assert "action" in resp.json()["detail"].lower()

    # ---- FORWARD: ENQ_NOTED -> COSTING_REVIEW approval gate (design Q4) ----

    def test_forward_out_of_enq_noted_blocked_without_status_3(self):
        session = self._session_for_stage("ENQ_NOTED", status_id=ENQUIRY_STATUS_IDS["OPEN"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "COSTING_REVIEW",
        })
        assert resp.status_code == 403
        assert "approved" in resp.json()["detail"].lower()
        assert _params_for(session, M_INSERT_LOG) == []  # nothing written
        session.commit.assert_not_called()

    def test_forward_out_of_enq_noted_allowed_when_approved(self):
        session = self._session_for_stage("ENQ_NOTED", status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "COSTING_REVIEW",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["stage_code"] == "COSTING_REVIEW"
        assert body["hold_flag"] == 0

        log_params = _params_for(session, M_INSERT_LOG)[0]
        assert log_params["action"] == "FORWARD"
        assert log_params["from_stage_id"] == STAGE_IDS["ENQ_NOTED"]
        assert log_params["to_stage_id"] == STAGE_IDS["COSTING_REVIEW"]
        ptr_params = _params_for(session, M_UPDATE_STAGE_PTR)[0]
        assert ptr_params["current_stage_id"] == STAGE_IDS["COSTING_REVIEW"]
        session.commit.assert_called_once()

    def test_forward_to_illegal_stage_returns_400(self):
        self._session_for_stage("ENQ_NOTED", status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "PRODUCTION",
        })
        assert resp.status_code == 400
        assert "cannot forward" in resp.json()["detail"].lower()

    # ---- SEND_BACK: feedback mandatory ----

    def test_send_back_without_feedback_returns_400(self):
        session = self._session_for_stage("COSTING_REVIEW")
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "SEND_BACK", "to_stage_code": "ENQ_NOTED",
        })
        assert resp.status_code == 400
        assert "feedback" in resp.json()["detail"].lower()
        assert _params_for(session, M_INSERT_LOG) == []

    def test_send_back_with_feedback_succeeds(self):
        session = self._session_for_stage("COSTING_REVIEW")
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "SEND_BACK", "to_stage_code": "ENQ_NOTED",
            "feedback": "Costing inputs incomplete — need fabric spec",
        })
        assert resp.status_code == 200
        assert resp.json()["stage_code"] == "ENQ_NOTED"

        log_params = _params_for(session, M_INSERT_LOG)[0]
        assert log_params["action"] == "SEND_BACK"
        assert log_params["feedback"] == "Costing inputs incomplete — need fabric spec"
        assert log_params["to_stage_id"] == STAGE_IDS["ENQ_NOTED"]
        session.commit.assert_called_once()

    # ---- MARK_LOST: only up to sequence 50 (before order confirmation) ----

    def test_mark_lost_past_order_confirmed_returns_400(self):
        # DESIGN_RELEASE has sequence 60 > MARK_LOST_MAX_SEQUENCE (50).
        session = self._session_for_stage("DESIGN_RELEASE", status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "action": "MARK_LOST"})
        assert resp.status_code == 400
        assert "mark_lost" in resp.json()["detail"].lower()
        assert _params_for(session, M_UPDATE_CLOSE) == []
        session.commit.assert_not_called()

    def test_mark_lost_from_early_stage_closes_as_lost(self):
        session = self._session_for_stage("COSTING_REVIEW", status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "MARK_LOST", "lost_remarks": "Competitor undercut",
        })
        assert resp.status_code == 200
        assert resp.json()["stage_code"] == "LOST"

        close_params = _params_for(session, M_UPDATE_CLOSE)[0]
        assert close_params["status_id"] == ENQUIRY_STATUS_IDS["CLOSED"]  # 5
        assert close_params["close_reason"] == "lost"
        assert close_params["lost_remarks"] == "Competitor undercut"
        log_params = _params_for(session, M_INSERT_LOG)[0]
        assert log_params["action"] == "MARK_LOST"
        assert log_params["to_stage_id"] == STAGE_IDS["LOST"]
        session.commit.assert_called_once()

    # ---- HOLD / RESUME: toggle hold_flag, stage preserved ----

    def test_hold_sets_flag_and_preserves_stage(self):
        session = self._session_for_stage("COSTING_REVIEW", hold_flag=0)
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "action": "HOLD"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["hold_flag"] == 1
        assert body["stage_code"] == "COSTING_REVIEW"

        hold_params = _params_for(session, M_UPDATE_HOLD)[0]
        assert hold_params["hold_flag"] == 1
        assert _params_for(session, M_INSERT_LOG)[0]["action"] == "HOLD"
        # Stage-preserving: header stage pointer untouched (aging anchor kept).
        assert _params_for(session, M_UPDATE_STAGE_PTR) == []
        session.commit.assert_called_once()

    def test_hold_when_already_on_hold_returns_400(self):
        self._session_for_stage("COSTING_REVIEW", hold_flag=1)
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "action": "HOLD"})
        assert resp.status_code == 400
        assert "already on hold" in resp.json()["detail"].lower()

    def test_resume_clears_flag(self):
        session = self._session_for_stage("COSTING_REVIEW", hold_flag=1)
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "action": "RESUME"})
        assert resp.status_code == 200
        assert resp.json()["hold_flag"] == 0
        assert _params_for(session, M_UPDATE_HOLD)[0]["hold_flag"] == 0
        assert _params_for(session, M_INSERT_LOG)[0]["action"] == "RESUME"

    def test_resume_when_not_on_hold_returns_400(self):
        self._session_for_stage("COSTING_REVIEW", hold_flag=0)
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "action": "RESUME"})
        assert resp.status_code == 400
        assert "not on hold" in resp.json()["detail"].lower()

    def test_forward_blocked_while_on_hold_returns_400(self):
        self._session_for_stage("COSTING_REVIEW", hold_flag=1,
                                status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "QUOTATION",
        })
        assert resp.status_code == 400
        assert "hold" in resp.json()["detail"].lower()

    # ---- FORWARD: COSTING_REVIEW -> QUOTATION costing-completeness gate (D5) ----

    def test_forward_from_costing_review_blocked_when_lines_pending(self):
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW",
                                       status_id=ENQUIRY_STATUS_IDS["APPROVED"])),
            (PENDING_MARKER, _result(fetchall=[_row({"enquiry_dtl_id": 5, "item_id": 3})])),
            H_STAGE_BY_CODE,
        ])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "QUOTATION",
        })
        assert resp.status_code == 400
        assert "Costing is not complete" in resp.json()["detail"]
        assert _params_for(session, M_INSERT_LOG) == []
        session.commit.assert_not_called()

    def test_forward_from_costing_review_allowed_when_all_done(self):
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW",
                                       status_id=ENQUIRY_STATUS_IDS["APPROVED"])),
            (PENDING_MARKER, _result(fetchall=[])),
            H_STAGE_BY_CODE,
        ])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "QUOTATION",
        })
        assert resp.status_code == 200
        assert resp.json()["stage_code"] == "QUOTATION"
        session.commit.assert_called_once()

    def test_forward_costing_review_to_price_check_not_blocked(self):
        # PRICE_CHECK is the escape hatch to get prices WHILE costing is
        # incomplete — must proceed even with pending lines (gate is scoped to
        # priced-document destinations only).
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW",
                                       status_id=ENQUIRY_STATUS_IDS["APPROVED"])),
            (PENDING_MARKER, _result(fetchall=[_row({"enquiry_dtl_id": 5, "item_id": 3})])),
            H_STAGE_BY_CODE,
        ])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "PRICE_CHECK",
        })
        assert resp.status_code == 200
        assert resp.json()["stage_code"] == "PRICE_CHECK"
        assert _params_for(session, PENDING_MARKER) == []  # gate never even queries
        session.commit.assert_called_once()

    def test_forward_from_costing_review_to_order_confirmed_blocked_when_pending(self):
        session = self.use_session([
            _state_handler(_flow_state(stage_code="COSTING_REVIEW",
                                       status_id=ENQUIRY_STATUS_IDS["APPROVED"])),
            (PENDING_MARKER, _result(fetchall=[_row({"enquiry_dtl_id": 5, "item_id": 3})])),
            H_STAGE_BY_CODE,
        ])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "action": "FORWARD", "to_stage_code": "ORDER_CONFIRMED",
        })
        assert resp.status_code == 400
        assert "Costing is not complete" in resp.json()["detail"]
        session.commit.assert_not_called()


# =============================================================================
# close_enquiry
# =============================================================================

class TestCloseEnquiry(EnquiryTestBase):
    URL = f"{BASE}/close_enquiry"

    def _session_for_stage(self, stage_code, **state_overrides):
        return self.use_session([
            _state_handler(_flow_state(stage_code=stage_code, **state_overrides)),
            H_STAGE_BY_CODE,
        ])

    def test_missing_close_reason_returns_400(self):
        resp = client.post(self.URL, json={"sales_enquiry_id": 5})
        assert resp.status_code == 400
        assert "close_reason" in resp.json()["detail"].lower()

    def test_invalid_close_reason_returns_400(self):
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "close_reason": "abandoned"})
        assert resp.status_code == 400
        assert "close_reason" in resp.json()["detail"].lower()

    def test_close_won_sets_status_5_and_stage_closed(self):
        session = self._session_for_stage("READY_FOR_DELIVERY",
                                          status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "close_reason": "won", "remarks": "Order delivered",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["new_status_id"] == ENQUIRY_STATUS_IDS["CLOSED"]  # 5
        assert body["stage_code"] == "CLOSED"
        assert body["close_reason"] == "won"

        close_params = _params_for(session, M_UPDATE_CLOSE)[0]
        assert close_params["close_reason"] == "won"
        assert close_params["lost_remarks"] is None  # only kept for 'lost'
        log_params = _params_for(session, M_INSERT_LOG)[0]
        assert log_params["action"] == "CLOSE"
        assert log_params["to_stage_id"] == STAGE_IDS["CLOSED"]
        assert log_params["feedback"] == "Order delivered"
        session.commit.assert_called_once()

    def test_close_lost_from_late_stage_returns_400(self):
        # 'lost' routes through MARK_LOST — blocked past sequence 50.
        session = self._session_for_stage("PRODUCTION",
                                          status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "close_reason": "lost", "remarks": "too late",
        })
        assert resp.status_code == 400
        assert "mark_lost" in resp.json()["detail"].lower()
        assert _params_for(session, M_UPDATE_CLOSE) == []
        session.commit.assert_not_called()

    def test_close_lost_from_early_stage_records_lost_remarks(self):
        session = self._session_for_stage("QUOTATION",
                                          status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={
            "sales_enquiry_id": 5, "close_reason": "lost", "remarks": "Lost on price",
        })
        assert resp.status_code == 200
        assert resp.json()["stage_code"] == "LOST"

        close_params = _params_for(session, M_UPDATE_CLOSE)[0]
        assert close_params["close_reason"] == "lost"
        assert close_params["lost_remarks"] == "Lost on price"
        assert _params_for(session, M_INSERT_LOG)[0]["to_stage_id"] == STAGE_IDS["LOST"]

    def test_close_blocked_while_on_hold_returns_400(self):
        self._session_for_stage("QUOTATION", hold_flag=1,
                                status_id=ENQUIRY_STATUS_IDS["APPROVED"])
        resp = client.post(self.URL, json={"sales_enquiry_id": 5, "close_reason": "won"})
        assert resp.status_code == 400
        assert "hold" in resp.json()["detail"].lower()


# =============================================================================
# confirm_line_costing — overhead_pct / margin_pct (Task 3)
# =============================================================================

M_LINE_STATE = "fsm.stage_code"                                       # get_enquiry_dtl_state_query
M_BOM_HDR_CONFIRM = "FROM item_bom_hdr_mst bh"                        # get_bom_hdr_for_confirm_query
M_COST_SNAPSHOT = "FROM bom_cost_snapshot bcs"                        # get_current_bom_cost_snapshot_query
M_APPROVE_SNAPSHOT = "status = 'approved'"                            # approve_bom_cost_snapshot
M_UPDATE_COSTING = "costing_confirmed_date = :costing_confirmed_date"  # update_enquiry_dtl_costing


class TestConfirmLineCosting(EnquiryTestBase):
    URL = f"{BASE}/confirm_line_costing"

    def _base_session(self):
        return self.use_session([
            (M_LINE_STATE, _result(fetchone=_row({
                "enquiry_dtl_id": 5, "sales_enquiry_id": 9, "item_id": 3,
                "status_id": 3, "hold_flag": 0, "active": 1,
                "stage_code": "COSTING_REVIEW",
            }))),
            (M_BOM_HDR_CONFIRM, _result(fetchone=_row({"item_id": 3}))),
            (M_COST_SNAPSHOT, _result(fetchone=_row({
                "bom_cost_snapshot_id": 77, "cost_per_unit": 140.0,
            }))),
            (M_APPROVE_SNAPSHOT, _result()),
            (M_UPDATE_COSTING, _result()),
        ])

    def test_persists_overhead_and_margin_pct(self):
        session = self._base_session()
        resp = client.post(self.URL, json={
            "enquiry_dtl_id": 5, "bom_hdr_id": 12,
            "overhead_pct": 10, "margin_pct": 20,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["overhead_pct"] == 10.0
        assert data["margin_pct"] == 20.0

        update_params = _params_for(session, M_UPDATE_COSTING)[0]
        assert update_params["overhead_pct"] == 10.0
        assert update_params["margin_pct"] == 20.0
        session.commit.assert_called_once()

    def test_omitted_pcts_persist_as_none(self):
        session = self._base_session()
        resp = client.post(self.URL, json={"enquiry_dtl_id": 5, "bom_hdr_id": 12})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["overhead_pct"] is None
        assert data["margin_pct"] is None

        update_params = _params_for(session, M_UPDATE_COSTING)[0]
        assert update_params["overhead_pct"] is None
        assert update_params["margin_pct"] is None
