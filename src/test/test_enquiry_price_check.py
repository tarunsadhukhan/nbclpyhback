"""
Tests for the price-check endpoints in src/sales/enquiry.py
(docs/amcl-enquiry-flow-design.md §6 — Design/Costing -> Procurement consult):

- POST /api/salesEnquiry/create_price_check
    prefills last_po_rate / last_po_date / last_supplier_id per item (mocked
    get_last_purchase_rates_by_item_ids result) and FORWARDs the enquiry
    COSTING_REVIEW -> PRICE_CHECK with a stage-log entry.
- GET  /api/salesEnquiry/get_price_check_pending_list (procurement worklist)
- GET  /api/salesEnquiry/get_price_check_by_id
- POST /api/salesEnquiry/respond_price_check
    writes confirmed rates, flips pc_status pending -> responded, and moves
    the enquiry back PRICE_CHECK -> COSTING_REVIEW with the response note as
    feedback (stage-preserving AUTO entry when the enquiry moved on / is held).
- missing-param 400s for all of the above.

House pattern: TestClient(app) + app.dependency_overrides for get_tenant_db /
get_current_user_with_refresh, MagicMock sessions with _mapping rows. The DB
is never touched: session.execute dispatches on SQL-text fingerprints so each
statement in the endpoint's transaction gets its own mocked result, and every
(sql, params) pair is recorded for write-side assertions.
"""

from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.sales.enquiry import router as enquiry_router
from src.sales.enquiry_constants import (
    PC_STATUS_PENDING,
    PC_STATUS_RESPONDED,
    STAGE_COSTING_REVIEW,
    STAGE_ENQ_NOTED,
    STAGE_PRICE_CHECK,
    STAGE_QUOTATION,
)

# The enquiry router ships before its src/main.py registration (added by a
# later change) — mount it here iff absent so these tests exercise the real
# prefix either way.
if not any(
    getattr(route, "path", "").startswith("/api/salesEnquiry/") for route in app.routes
):
    app.include_router(enquiry_router, prefix="/api/salesEnquiry", tags=["sales-enquiry"])

client = TestClient(app)

USER_ID = 7
ENQUIRY_ID = 5
PRICE_CHECK_ID = 77

# flow_stage_mst.stage_id values used by the mocked stage-by-code lookup.
STAGE_IDS = {
    STAGE_ENQ_NOTED: 11,
    STAGE_COSTING_REVIEW: 12,
    STAGE_PRICE_CHECK: 13,
    STAGE_QUOTATION: 14,
}


# =============================================================================
# MOCK PLUMBING
# =============================================================================

def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _result(fetchone=None, fetchall=None, lastrowid=None):
    res = MagicMock()
    res.fetchone.return_value = fetchone
    res.fetchall.return_value = fetchall if fetchall is not None else []
    if lastrowid is not None:
        res.lastrowid = lastrowid
    return res


def make_session(handlers):
    """MagicMock session whose execute() dispatches on SQL-text fingerprints.

    handlers: list of (fragments-tuple, factory) — the first entry whose
    fragments ALL appear in the whitespace-normalized SQL wins; factory is
    called with the bind params and must return a result mock. Unmatched
    statements (e.g. plain INSERTs whose result is unused) get a bare mock.
    Every (sql, params) pair is recorded on session.executed.
    """
    session = MagicMock()
    session.executed = []

    def _execute(query, params=None):
        sql = " ".join(str(query).split())
        session.executed.append((sql, params))
        for fragments, factory in handlers:
            if all(fragment in sql for fragment in fragments):
                return factory(params)
        return _result()

    session.execute.side_effect = _execute
    return session


def params_for(session, fragment):
    """All recorded bind-param dicts whose (normalized) SQL contains fragment."""
    return [p for (sql, p) in session.executed if fragment in sql]


# --- SQL fingerprints (whitespace-normalized) --------------------------------

FLOW_STATE = ("FROM sales_enquiry se", "fsm.is_terminal")
ACTIVE_LINES = ("SELECT sed.enquiry_dtl_id, sed.item_id",)
LAST_PO = ("FROM proc_po_dtl ppd",)
PC_HDR_INSERT = ("INSERT INTO enquiry_price_check ( sales_enquiry_id",)
PC_DTL_INSERT = ("INSERT INTO enquiry_price_check_dtl",)
STAGE_BY_CODE = ("WHERE fsm.module = :module AND fsm.stage_code = :stage_code",)
LOG_INSERT = ("INSERT INTO flow_stage_log",)
STAGE_PTR_UPDATE = ("SET current_stage_id = :current_stage_id",)
PC_STATE = ("SELECT epc.price_check_id, epc.sales_enquiry_id, epc.pc_status",)
PC_DTL_IDS = ("SELECT pcd.price_check_dtl_id FROM enquiry_price_check_dtl pcd",)
PC_DTL_UPDATE = ("UPDATE enquiry_price_check_dtl SET",)
PC_HDR_UPDATE = ("UPDATE enquiry_price_check SET",)
PC_LIST = ("FROM enquiry_price_check AS epc", "ORDER BY epc.price_check_id DESC")
PC_BY_ID = ("FROM enquiry_price_check AS epc", "WHERE epc.price_check_id = :price_check_id")
PC_BY_ID_DTL = ("FROM enquiry_price_check_dtl AS pcd",)


# --- row builders -------------------------------------------------------------

def flow_state_row(**overrides):
    base = {
        "sales_enquiry_id": ENQUIRY_ID,
        "enquiry_no": "12",
        "enquiry_date": date(2026, 5, 1),
        "branch_id": 2,
        "co_id": 1,
        "party_id": 9,
        "status_id": 3,
        "approval_level": None,
        "current_stage_id": STAGE_IDS[STAGE_COSTING_REVIEW],
        "stage_code": STAGE_COSTING_REVIEW,
        "sequence_no": 20,
        "is_terminal": 0,
        "stage_since": datetime(2026, 6, 1, 10, 0, 0),
        "hold_flag": 0,
        "close_reason": None,
        "project_id": None,
        "active": 1,
    }
    base.update(overrides)
    return _mock_row(base)


def stage_by_code_factory(params):
    code = params["stage_code"]
    return _result(fetchone=_mock_row({
        "stage_id": STAGE_IDS[code],
        "stage_code": code,
        "stage_name": code.replace("_", " ").title(),
        "dept_hint": None,
        "sequence_no": 0,
        "is_terminal": 0,
    }))


def active_line_rows():
    """Two active enquiry lines: one item-backed, one free-text (item_id None)."""
    return [
        _mock_row({"enquiry_dtl_id": 201, "item_id": 101}),
        _mock_row({"enquiry_dtl_id": 202, "item_id": None}),
    ]


def last_po_rows():
    return [_mock_row({
        "item_id": 101,
        "last_po_rate": 123.45,
        "last_po_date": date(2026, 4, 2),
        "last_supplier_id": 55,
        "last_supplier_name": "ACME Supplies",
    })]


# =============================================================================
# SHARED FIXTURE — auth override + safe default DB override on every test
# =============================================================================

@pytest.fixture(autouse=True)
def _default_overrides():
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": USER_ID}
    # Default harmless session so validation-only tests never touch a real DB.
    app.dependency_overrides[get_tenant_db] = lambda: MagicMock()
    yield
    app.dependency_overrides.clear()


def use_session(session):
    app.dependency_overrides[get_tenant_db] = lambda: session


# =============================================================================
# POST /create_price_check
# =============================================================================

class TestCreatePriceCheck:

    def _session(self, state_row=..., lines=None, last_po=None):
        if state_row is ...:
            state_row = flow_state_row()
        return make_session([
            (FLOW_STATE, lambda p: _result(fetchone=state_row)),
            (ACTIVE_LINES, lambda p: _result(fetchall=lines if lines is not None else active_line_rows())),
            (LAST_PO, lambda p: _result(fetchall=last_po if last_po is not None else last_po_rows())),
            (PC_HDR_INSERT, lambda p: _result(lastrowid=PRICE_CHECK_ID)),
            (STAGE_BY_CODE, stage_by_code_factory),
        ])

    def test_create_success_default_lines_prefills_last_po_and_moves_stage(self):
        session = self._session()
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
            "request_note": "Please reconfirm rates",
        })

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["price_check_id"] == PRICE_CHECK_ID
        assert body["data"]["sales_enquiry_id"] == ENQUIRY_ID
        assert body["stage_code"] == STAGE_PRICE_CHECK

        # Header written as pending, by the acting user.
        hdr = params_for(session, PC_HDR_INSERT[0])
        assert len(hdr) == 1
        assert hdr[0]["pc_status"] == PC_STATUS_PENDING
        assert hdr[0]["sales_enquiry_id"] == ENQUIRY_ID
        assert hdr[0]["requested_by"] == USER_ID
        assert hdr[0]["request_note"] == "Please reconfirm rates"

        # Only the item-backed line becomes a detail row — free-text skipped —
        # and last_po_rate / last_po_date / last_supplier_id are PREFILLED from
        # the mocked last-purchase-rate query result (evidence snapshot).
        dtls = params_for(session, PC_DTL_INSERT[0])
        assert len(dtls) == 1
        assert dtls[0]["price_check_id"] == PRICE_CHECK_ID
        assert dtls[0]["enquiry_dtl_id"] == 201
        assert dtls[0]["item_id"] == 101
        assert dtls[0]["last_po_rate"] == 123.45
        assert dtls[0]["last_po_date"] == date(2026, 4, 2)
        assert dtls[0]["last_supplier_id"] == 55

        # Stage log: FORWARD COSTING_REVIEW -> PRICE_CHECK linked to the new doc.
        logs = params_for(session, LOG_INSERT[0])
        assert len(logs) == 1
        assert logs[0]["action"] == "FORWARD"
        assert logs[0]["doc_id"] == ENQUIRY_ID
        assert logs[0]["from_stage_id"] == STAGE_IDS[STAGE_COSTING_REVIEW]
        assert logs[0]["to_stage_id"] == STAGE_IDS[STAGE_PRICE_CHECK]
        assert logs[0]["linked_doc_type"] == "PRICE_CHECK"
        assert logs[0]["linked_doc_id"] == PRICE_CHECK_ID
        assert logs[0]["feedback"] == "Please reconfirm rates"

        # Header stage pointer moved to PRICE_CHECK, one commit.
        ptr = params_for(session, STAGE_PTR_UPDATE[0])
        assert len(ptr) == 1
        assert ptr[0]["current_stage_id"] == STAGE_IDS[STAGE_PRICE_CHECK]
        session.commit.assert_called_once()

    def test_create_success_explicit_items_resolve_line_item(self):
        session = self._session()
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
            "items": [{"enquiry_dtl_id": 201, "remarks": "urgent"}],
        })

        assert response.status_code == 200
        dtls = params_for(session, PC_DTL_INSERT[0])
        assert len(dtls) == 1
        # item_id resolved from the enquiry line; remarks carried over.
        assert dtls[0]["item_id"] == 101
        assert dtls[0]["enquiry_dtl_id"] == 201
        assert dtls[0]["remarks"] == "urgent"
        assert dtls[0]["last_po_rate"] == 123.45

    def test_create_success_without_po_history_prefills_null(self):
        session = self._session(last_po=[])
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
        })

        assert response.status_code == 200
        dtls = params_for(session, PC_DTL_INSERT[0])
        assert len(dtls) == 1
        assert dtls[0]["last_po_rate"] is None
        assert dtls[0]["last_po_date"] is None
        assert dtls[0]["last_supplier_id"] is None

    def test_create_missing_sales_enquiry_id_returns_400(self):
        response = client.post("/api/salesEnquiry/create_price_check", json={})
        assert response.status_code == 400
        assert "sales_enquiry_id" in response.json()["detail"].lower()

    def test_create_enquiry_not_found_returns_404(self):
        session = make_session([(FLOW_STATE, lambda p: _result(fetchone=None))])
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": 9999,
        })
        assert response.status_code == 404

    def test_create_from_wrong_stage_returns_400_and_writes_nothing(self):
        session = self._session(
            state_row=flow_state_row(
                stage_code=STAGE_ENQ_NOTED,
                current_stage_id=STAGE_IDS[STAGE_ENQ_NOTED],
                sequence_no=10,
            )
        )
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
        })
        assert response.status_code == 400
        assert "cannot forward" in response.json()["detail"].lower()
        # Illegal request writes nothing.
        assert params_for(session, PC_HDR_INSERT[0]) == []
        assert params_for(session, LOG_INSERT[0]) == []
        session.commit.assert_not_called()

    def test_create_on_hold_returns_400(self):
        session = self._session(state_row=flow_state_row(hold_flag=1))
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
        })
        assert response.status_code == 400
        assert "hold" in response.json()["detail"].lower()

    def test_create_with_only_freetext_lines_returns_400(self):
        session = self._session(lines=[_mock_row({"enquiry_dtl_id": 202, "item_id": None})])
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
        })
        assert response.status_code == 400
        assert "no enquiry lines with an item" in response.json()["detail"].lower()

    def test_create_with_foreign_enquiry_dtl_id_returns_400(self):
        session = self._session()
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
            "items": [{"enquiry_dtl_id": 999}],
        })
        assert response.status_code == 400
        assert "does not belong to this enquiry" in response.json()["detail"]

    def test_create_item_without_item_id_returns_400(self):
        session = self._session()
        use_session(session)

        response = client.post("/api/salesEnquiry/create_price_check", json={
            "sales_enquiry_id": ENQUIRY_ID,
            "items": [{"remarks": "no item here"}],
        })
        assert response.status_code == 400
        assert "item_id is required" in response.json()["detail"]


# =============================================================================
# GET /get_price_check_pending_list
# =============================================================================

class TestPriceCheckPendingList:

    def _list_row(self):
        return _mock_row({
            "price_check_id": PRICE_CHECK_ID,
            "sales_enquiry_id": ENQUIRY_ID,
            "enquiry_no": "12",
            "enquiry_date": date(2026, 5, 1),
            "branch_id": 2,
            "branch_name": "Main",
            "co_id": 3,
            "party_id": 9,
            "party_name": "Customer A",
            "request_note": "Please reconfirm rates",
            "pc_status": PC_STATUS_PENDING,
            "requested_by": USER_ID,
            "requested_by_name": "Requester",
            "requested_date_time": datetime(2026, 6, 1, 10, 0, 0),
            "responded_by": None,
            "responded_by_name": None,
            "responded_date_time": None,
            "response_note": None,
            "line_count": 1,
        })

    def test_pending_list_success_defaults_to_pending(self):
        session = make_session([(PC_LIST, lambda p: _result(fetchall=[self._list_row()]))])
        use_session(session)

        response = client.get("/api/salesEnquiry/get_price_check_pending_list?co_id=3")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["price_check_id"] == PRICE_CHECK_ID
        assert data[0]["pc_status"] == PC_STATUS_PENDING
        assert data[0]["enquiry_no_raw"] == "12"
        assert data[0]["enquiry_date"] == "2026-05-01"

        list_params = params_for(session, PC_LIST[0])
        assert len(list_params) == 1
        assert list_params[0]["co_id"] == 3
        assert list_params[0]["branch_id"] is None
        assert list_params[0]["pc_status"] == PC_STATUS_PENDING

    def test_pending_list_pc_status_all_skips_filter(self):
        session = make_session([(PC_LIST, lambda p: _result(fetchall=[]))])
        use_session(session)

        response = client.get(
            "/api/salesEnquiry/get_price_check_pending_list?co_id=3&branch_id=2&pc_status=all"
        )
        assert response.status_code == 200
        assert response.json()["data"] == []
        list_params = params_for(session, PC_LIST[0])
        assert list_params[0]["pc_status"] is None
        assert list_params[0]["branch_id"] == 2

    def test_pending_list_missing_co_id_returns_400(self):
        response = client.get("/api/salesEnquiry/get_price_check_pending_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_pending_list_invalid_pc_status_returns_400(self):
        response = client.get(
            "/api/salesEnquiry/get_price_check_pending_list?co_id=3&pc_status=bogus"
        )
        assert response.status_code == 400
        assert "pc_status" in response.json()["detail"].lower()


# =============================================================================
# GET /get_price_check_by_id
# =============================================================================

class TestPriceCheckById:

    def _header_row(self):
        return _mock_row({
            "price_check_id": PRICE_CHECK_ID,
            "sales_enquiry_id": ENQUIRY_ID,
            "enquiry_no": "12",
            "enquiry_date": date(2026, 5, 1),
            "branch_id": 2,
            "branch_name": "Main",
            "co_id": 3,
            "party_id": 9,
            "party_name": "Customer A",
            "current_stage_id": STAGE_IDS[STAGE_PRICE_CHECK],
            "stage_code": STAGE_PRICE_CHECK,
            "request_note": "Please reconfirm rates",
            "pc_status": PC_STATUS_PENDING,
            "requested_by": USER_ID,
            "requested_by_name": "Requester",
            "requested_date_time": datetime(2026, 6, 1, 10, 0, 0),
            "responded_by": None,
            "responded_by_name": None,
            "responded_date_time": None,
            "response_note": None,
            "updated_by": USER_ID,
            "updated_date_time": datetime(2026, 6, 1, 10, 0, 0),
        })

    def _dtl_rows(self):
        return [
            _mock_row({
                "price_check_dtl_id": 301,
                "price_check_id": PRICE_CHECK_ID,
                "enquiry_dtl_id": 201,
                "item_id": 101,
                "item_code": "ITM-101",
                "item_name": "Widget",
                "full_item_code": "GRP/ITM-101",
                "last_po_rate": 123.45,
                "last_po_date": date(2026, 4, 2),
                "last_supplier_id": 55,
                "last_supplier_name": "ACME Supplies",
                "confirmed_rate": None,
                "rate_source": None,
                "supplier_id": None,
                "supplier_name": None,
                "remarks": None,
            }),
            _mock_row({
                "price_check_dtl_id": 302,
                "price_check_id": PRICE_CHECK_ID,
                "enquiry_dtl_id": 203,
                "item_id": 102,
                "item_code": "ITM-102",
                "item_name": "Gadget",
                "full_item_code": "GRP/ITM-102",
                "last_po_rate": None,
                "last_po_date": None,
                "last_supplier_id": None,
                "last_supplier_name": None,
                "confirmed_rate": None,
                "rate_source": None,
                "supplier_id": None,
                "supplier_name": None,
                "remarks": None,
            }),
        ]

    def test_by_id_success_returns_header_and_lines(self):
        session = make_session([
            (PC_BY_ID, lambda p: _result(fetchone=self._header_row())),
            (PC_BY_ID_DTL, lambda p: _result(fetchall=self._dtl_rows())),
        ])
        use_session(session)

        response = client.get(
            f"/api/salesEnquiry/get_price_check_by_id?price_check_id={PRICE_CHECK_ID}"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["price_check_id"] == PRICE_CHECK_ID
        assert data["pc_status"] == PC_STATUS_PENDING
        assert data["enquiry_date"] == "2026-05-01"
        assert len(data["lines"]) == 2
        # The last-PO prefill snapshot is exposed on each line, date formatted.
        assert data["lines"][0]["last_po_rate"] == 123.45
        assert data["lines"][0]["last_po_date"] == "2026-04-02"
        assert data["lines"][1]["last_po_rate"] is None

    def test_by_id_missing_price_check_id_returns_400(self):
        response = client.get("/api/salesEnquiry/get_price_check_by_id")
        assert response.status_code == 400
        assert "price_check_id" in response.json()["detail"].lower()

    def test_by_id_not_found_returns_404(self):
        session = make_session([(PC_BY_ID, lambda p: _result(fetchone=None))])
        use_session(session)

        response = client.get("/api/salesEnquiry/get_price_check_by_id?price_check_id=9999")
        assert response.status_code == 404


# =============================================================================
# POST /respond_price_check
# =============================================================================

class TestRespondPriceCheck:

    def _session(self, pc_status=PC_STATUS_PENDING, state_row=...):
        if state_row is ...:
            state_row = flow_state_row(
                stage_code=STAGE_PRICE_CHECK,
                current_stage_id=STAGE_IDS[STAGE_PRICE_CHECK],
                sequence_no=30,
            )
        pc_row = _mock_row({
            "price_check_id": PRICE_CHECK_ID,
            "sales_enquiry_id": ENQUIRY_ID,
            "pc_status": pc_status,
        })
        dtl_id_rows = [
            _mock_row({"price_check_dtl_id": 301}),
            _mock_row({"price_check_dtl_id": 302}),
        ]
        return make_session([
            (PC_STATE, lambda p: _result(fetchone=pc_row)),
            (PC_DTL_IDS, lambda p: _result(fetchall=dtl_id_rows)),
            (FLOW_STATE, lambda p: _result(fetchone=state_row)),
            (STAGE_BY_CODE, stage_by_code_factory),
        ])

    def _valid_body(self):
        return {
            "price_check_id": PRICE_CHECK_ID,
            "response_note": "Rates confirmed with supplier",
            "items": [
                {
                    "price_check_dtl_id": 301,
                    "confirmed_rate": 150.5,
                    "rate_source": "last_po",
                    "supplier_id": 55,
                    "remarks": "ok",
                },
                {"price_check_dtl_id": 302, "confirmed_rate": 12},
            ],
        }

    def test_respond_success_writes_rates_flips_status_and_returns_stage(self):
        session = self._session()
        use_session(session)

        response = client.post("/api/salesEnquiry/respond_price_check", json=self._valid_body())

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["price_check_id"] == PRICE_CHECK_ID
        assert body["data"]["sales_enquiry_id"] == ENQUIRY_ID
        assert body["stage_code"] == STAGE_COSTING_REVIEW

        # Confirmed rates written per detail row.
        dtl_updates = params_for(session, PC_DTL_UPDATE[0])
        assert len(dtl_updates) == 2
        assert dtl_updates[0]["price_check_dtl_id"] == 301
        assert dtl_updates[0]["price_check_id"] == PRICE_CHECK_ID
        assert dtl_updates[0]["confirmed_rate"] == 150.5
        assert dtl_updates[0]["rate_source"] == "last_po"
        assert dtl_updates[0]["supplier_id"] == 55
        assert dtl_updates[1]["price_check_dtl_id"] == 302
        assert dtl_updates[1]["confirmed_rate"] == 12.0
        assert dtl_updates[1]["rate_source"] is None

        # Header flipped pending -> responded with responder + note.
        hdr_updates = params_for(session, PC_HDR_UPDATE[0])
        assert len(hdr_updates) == 1
        assert hdr_updates[0]["pc_status"] == PC_STATUS_RESPONDED
        assert hdr_updates[0]["responded_by"] == USER_ID
        assert hdr_updates[0]["response_note"] == "Rates confirmed with supplier"

        # Return leg: FORWARD PRICE_CHECK -> COSTING_REVIEW, response note as
        # the feedback, linked back to this price check.
        logs = params_for(session, LOG_INSERT[0])
        assert len(logs) == 1
        assert logs[0]["action"] == "FORWARD"
        assert logs[0]["from_stage_id"] == STAGE_IDS[STAGE_PRICE_CHECK]
        assert logs[0]["to_stage_id"] == STAGE_IDS[STAGE_COSTING_REVIEW]
        assert logs[0]["feedback"] == "Rates confirmed with supplier"
        assert logs[0]["linked_doc_type"] == "PRICE_CHECK"
        assert logs[0]["linked_doc_id"] == PRICE_CHECK_ID

        ptr = params_for(session, STAGE_PTR_UPDATE[0])
        assert len(ptr) == 1
        assert ptr[0]["current_stage_id"] == STAGE_IDS[STAGE_COSTING_REVIEW]
        session.commit.assert_called_once()

    def test_respond_when_enquiry_moved_on_keeps_stage_with_auto_entry(self):
        session = self._session(state_row=flow_state_row(
            stage_code=STAGE_QUOTATION,
            current_stage_id=STAGE_IDS[STAGE_QUOTATION],
            sequence_no=40,
        ))
        use_session(session)

        response = client.post("/api/salesEnquiry/respond_price_check", json=self._valid_body())

        assert response.status_code == 200
        assert response.json()["stage_code"] == STAGE_QUOTATION

        # Response is still recorded...
        assert len(params_for(session, PC_HDR_UPDATE[0])) == 1
        # ...via a stage-preserving AUTO entry, without moving the pointer back.
        logs = params_for(session, LOG_INSERT[0])
        assert len(logs) == 1
        assert logs[0]["action"] == "AUTO"
        assert logs[0]["to_stage_id"] == STAGE_IDS[STAGE_QUOTATION]
        assert params_for(session, STAGE_PTR_UPDATE[0]) == []

    def test_respond_when_enquiry_on_hold_keeps_stage_with_auto_entry(self):
        session = self._session(state_row=flow_state_row(
            stage_code=STAGE_PRICE_CHECK,
            current_stage_id=STAGE_IDS[STAGE_PRICE_CHECK],
            sequence_no=30,
            hold_flag=1,
        ))
        use_session(session)

        response = client.post("/api/salesEnquiry/respond_price_check", json=self._valid_body())

        assert response.status_code == 200
        assert response.json()["stage_code"] == STAGE_PRICE_CHECK
        logs = params_for(session, LOG_INSERT[0])
        assert len(logs) == 1
        assert logs[0]["action"] == "AUTO"
        assert logs[0]["to_stage_id"] == STAGE_IDS[STAGE_PRICE_CHECK]
        assert params_for(session, STAGE_PTR_UPDATE[0]) == []

    def test_respond_missing_price_check_id_returns_400(self):
        response = client.post("/api/salesEnquiry/respond_price_check", json={
            "items": [{"price_check_dtl_id": 301}],
        })
        assert response.status_code == 400
        assert "price_check_id" in response.json()["detail"].lower()

    def test_respond_missing_items_returns_400(self):
        response = client.post("/api/salesEnquiry/respond_price_check", json={
            "price_check_id": PRICE_CHECK_ID,
        })
        assert response.status_code == 400
        assert "at least one item" in response.json()["detail"].lower()

    def test_respond_not_found_returns_404(self):
        session = make_session([(PC_STATE, lambda p: _result(fetchone=None))])
        use_session(session)

        response = client.post("/api/salesEnquiry/respond_price_check", json=self._valid_body())
        assert response.status_code == 404

    def test_respond_already_responded_returns_400(self):
        session = self._session(pc_status=PC_STATUS_RESPONDED)
        use_session(session)

        response = client.post("/api/salesEnquiry/respond_price_check", json=self._valid_body())
        assert response.status_code == 400
        assert "pending" in response.json()["detail"].lower()
        # Nothing written on an illegal respond.
        assert params_for(session, PC_DTL_UPDATE[0]) == []
        assert params_for(session, PC_HDR_UPDATE[0]) == []
        session.commit.assert_not_called()

    def test_respond_invalid_rate_source_returns_400(self):
        session = self._session()
        use_session(session)

        body = self._valid_body()
        body["items"][0]["rate_source"] = "gut_feeling"
        response = client.post("/api/salesEnquiry/respond_price_check", json=body)
        assert response.status_code == 400
        assert "rate_source" in response.json()["detail"]

    def test_respond_foreign_dtl_id_returns_400(self):
        session = self._session()
        use_session(session)

        body = self._valid_body()
        body["items"] = [{"price_check_dtl_id": 999, "confirmed_rate": 10}]
        response = client.post("/api/salesEnquiry/respond_price_check", json=body)
        assert response.status_code == 400
        assert "does not belong to this price check" in response.json()["detail"]

    def test_respond_item_missing_dtl_id_returns_400(self):
        session = self._session()
        use_session(session)

        body = self._valid_body()
        body["items"] = [{"confirmed_rate": 10}]
        response = client.post("/api/salesEnquiry/respond_price_check", json=body)
        assert response.status_code == 400
        assert "price_check_dtl_id" in response.json()["detail"]
