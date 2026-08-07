"""Tests for src/masters/isoMenuMap.py — ISO document-number map master.

Design: docs/amcl-enquiry-flow-design.md §5.1 (co_menu_iso_map) + §6 (Q2/Q7).
The isoMenuMap router is not (yet) mounted on the main app — registration is
owned by src/main.py — so we build a local FastAPI app, include the router
under its production prefix /api/isoMenuMap, and use dependency_overrides for
get_tenant_db + get_current_user_with_refresh (same style as
test_sales_enquiry.py).

DB access is fully mocked: the MagicMock session dispatches on distinctive SQL
substrings so the multi-query save handler (existing-row fetch + menu check +
insert/update/soft-delete) gets the right result per statement.

Covers:
- get_iso_map_table: success (data + master dropdown), co_id/search binds,
  missing co_id 400, invalid co_id 400, empty results, DB error 500
- iso_map_save upsert: insert path (lastrowid, action "created"), update path
  (action "updated", reactivates inactive rows), trimming, empty string
  clears the mapping (soft-deactivate / idempotent no-op), missing co_id /
  menu_id 400, invalid formats 400, >50-char iso_doc_no 400 (50 exactly OK),
  non-string iso_doc_no 400, unknown/inactive menu 400
- iso_map_delete: soft delete success, 404 when missing, idempotent no-op when
  already inactive, missing/invalid iso_map_id 400, DB error 500
- get_iso_doc_no helper: returns value, returns None (unmapped, blank value,
  None/garbage ids, DB failure), coerces string ids
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.masters.isoMenuMap import ISO_DOC_NO_MAX_LEN, get_iso_doc_no
from src.masters.isoMenuMap import router as iso_router

app = FastAPI()
app.include_router(iso_router, prefix="/api/isoMenuMap")
client = TestClient(app)

BASE = "/api/isoMenuMap"

# SQL markers — distinctive substrings of the statements in isoMenuMap.py,
# used as dispatch keys for make_session and _params_for. Order matters when
# passed to make_session (first match wins), so UPDATE markers must precede
# the generic ":iso_map_id" SELECT marker in handler lists.
M_TABLE = "JOIN menu_mst AS mm"              # get_iso_map_table_query
M_DROPDOWN = "TRIM(mm.menu_path)"            # get_menu_dropdown_query
M_BY_CO_MENU = "iso_map_id,\n        iso_doc_no"  # get_iso_map_by_co_menu_query
M_BY_ID = "iso_map_id,\n        co_id"       # get_iso_map_by_id_query
M_MENU_EXISTS = "SELECT menu_id"             # menu_exists_query
M_INSERT = "INSERT INTO co_menu_iso_map"     # insert_iso_map_query
M_UPDATE = "SET iso_doc_no = :iso_doc_no"    # update_iso_map_query
M_SOFT_DELETE = "SET active = 0"             # soft_delete_iso_map_query
M_DOC_NO = "SELECT iso_doc_no"               # get_iso_doc_no_query


# =============================================================================
# MOCK HELPERS
# =============================================================================

def _row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _result(fetchall=None, fetchone=None, lastrowid=0):
    """A MagicMock standing in for a SQLAlchemy CursorResult."""
    result = MagicMock()
    result.fetchall.return_value = fetchall if fetchall is not None else []
    result.fetchone.return_value = fetchone
    result.lastrowid = lastrowid
    return result


def make_session(handlers=()):
    """MagicMock session whose execute() dispatches on SQL substrings.

    handlers: ordered iterable of (sql_marker, result). The first marker found
    in str(query) wins. Unmatched SQL gets an empty result (fetchall [],
    fetchone None) so incidental queries never crash a test.
    """
    session = MagicMock()

    def _execute(query, params=None):
        sql = str(query)
        for marker, result in handlers:
            if marker in sql:
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


def _install(session):
    app.dependency_overrides[get_tenant_db] = lambda: session


MENU_ROWS = [
    _row({"menu_id": 10, "menu_name": "Purchase Order", "menu_path": "/dashboardportal/procurement/po"}),
    _row({"menu_id": 11, "menu_name": "Sales Enquiry", "menu_path": "/dashboardportal/sales/enquiry"}),
]

TABLE_ROW = {
    "iso_map_id": 1,
    "co_id": 1,
    "menu_id": 10,
    "menu_name": "Purchase Order",
    "menu_path": "/dashboardportal/procurement/po",
    "iso_doc_no": "AMCL/PO/F-01",
    "active": 1,
    "updated_by": 1,
    "updated_date_time": None,
}


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
    app.dependency_overrides[get_tenant_db] = lambda: MagicMock()
    yield
    app.dependency_overrides.clear()


# =============================================================================
# GET /get_iso_map_table
# =============================================================================

class TestGetIsoMapTable:
    def test_success_returns_rows_and_menu_master(self):
        session = make_session([
            (M_TABLE, _result(fetchall=[_row(TABLE_ROW)])),
            (M_DROPDOWN, _result(fetchall=MENU_ROWS)),
        ])
        _install(session)

        response = client.get(f"{BASE}/get_iso_map_table?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["iso_doc_no"] == "AMCL/PO/F-01"
        assert body["data"][0]["menu_name"] == "Purchase Order"
        assert len(body["master"]) == 2
        assert body["master"][0]["menu_id"] == 10

    def test_co_id_and_search_binds(self):
        session = make_session([
            (M_TABLE, _result(fetchall=[])),
            (M_DROPDOWN, _result(fetchall=[])),
        ])
        _install(session)

        response = client.get(f"{BASE}/get_iso_map_table?co_id=2&search=Indent")
        assert response.status_code == 200
        params = _params_for(session, M_TABLE)
        assert params == [{"co_id": 2, "search": "%Indent%"}]

    def test_search_absent_binds_none(self):
        session = make_session([
            (M_TABLE, _result(fetchall=[])),
            (M_DROPDOWN, _result(fetchall=[])),
        ])
        _install(session)

        response = client.get(f"{BASE}/get_iso_map_table?co_id=1")
        assert response.status_code == 200
        params = _params_for(session, M_TABLE)
        assert params == [{"co_id": 1, "search": None}]

    def test_empty_results(self):
        session = make_session([
            (M_TABLE, _result(fetchall=[])),
            (M_DROPDOWN, _result(fetchall=MENU_ROWS)),
        ])
        _install(session)

        response = client.get(f"{BASE}/get_iso_map_table?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert len(body["master"]) == 2

    def test_missing_co_id_400(self):
        response = client.get(f"{BASE}/get_iso_map_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_co_id_400(self):
        response = client.get(f"{BASE}/get_iso_map_table?co_id=abc")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_db_error_500(self):
        session = MagicMock()
        session.execute.side_effect = Exception("DB connection failed")
        _install(session)

        response = client.get(f"{BASE}/get_iso_map_table?co_id=1")
        assert response.status_code == 500


# =============================================================================
# POST /iso_map_save — upsert
# =============================================================================

class TestIsoMapSaveInsert:
    def test_insert_when_no_existing_row(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_INSERT, _result(lastrowid=77)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "AMCL/PO/F-01",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "created"
        assert data["iso_map_id"] == 77
        assert data["iso_doc_no"] == "AMCL/PO/F-01"

        insert_params = _params_for(session, M_INSERT)
        assert len(insert_params) == 1
        assert insert_params[0]["co_id"] == 1
        assert insert_params[0]["menu_id"] == 10
        assert insert_params[0]["iso_doc_no"] == "AMCL/PO/F-01"
        assert insert_params[0]["updated_by"] == 1
        assert insert_params[0]["updated_date_time"] is not None
        session.commit.assert_called_once()

    def test_iso_doc_no_trimmed_before_insert(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_INSERT, _result(lastrowid=5)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "  ISO-9001  ",
        })
        assert response.status_code == 200
        assert response.json()["data"]["iso_doc_no"] == "ISO-9001"
        assert _params_for(session, M_INSERT)[0]["iso_doc_no"] == "ISO-9001"

    def test_iso_doc_no_exactly_max_len_ok(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_INSERT, _result(lastrowid=6)),
        ])
        _install(session)

        doc_no = "X" * ISO_DOC_NO_MAX_LEN
        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": doc_no,
        })
        assert response.status_code == 200
        assert response.json()["data"]["iso_doc_no"] == doc_no

    def test_string_ids_coerced(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_INSERT, _result(lastrowid=8)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": "1", "menu_id": "10", "iso_doc_no": "ISO",
        })
        assert response.status_code == 200
        params = _params_for(session, M_INSERT)[0]
        assert params["co_id"] == 1
        assert params["menu_id"] == 10


class TestIsoMapSaveUpdate:
    def test_update_when_existing_row(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=_row({"iso_map_id": 5, "iso_doc_no": "OLD", "active": 1}))),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_UPDATE, _result()),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "NEW/ISO/01",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "updated"
        assert data["iso_map_id"] == 5
        assert data["iso_doc_no"] == "NEW/ISO/01"

        update_params = _params_for(session, M_UPDATE)
        assert update_params == [{
            "iso_map_id": 5,
            "iso_doc_no": "NEW/ISO/01",
            "updated_by": 1,
            "updated_date_time": update_params[0]["updated_date_time"],
        }]
        assert _params_for(session, M_INSERT) == []
        session.commit.assert_called_once()

    def test_update_reactivates_soft_deleted_row(self):
        """Saving over an inactive (co_id, menu_id) row reuses it — the UPDATE
        statement itself sets active = 1 (unique-key upsert, not a new row)."""
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=_row({"iso_map_id": 5, "iso_doc_no": "OLD", "active": 0}))),
            (M_MENU_EXISTS, _result(fetchone=_row({"menu_id": 10}))),
            (M_UPDATE, _result()),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "BACK",
        })
        assert response.status_code == 200
        assert response.json()["data"]["action"] == "updated"
        update_calls = [str(c.args[0]) for c in session.execute.call_args_list if M_UPDATE in str(c.args[0])]
        assert len(update_calls) == 1
        assert "active = 1" in update_calls[0]
        assert _params_for(session, M_INSERT) == []


class TestIsoMapSaveClear:
    """Empty iso_doc_no clears the mapping (design: header goes back blank)."""

    def test_empty_string_deactivates_active_row(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=_row({"iso_map_id": 5, "iso_doc_no": "OLD", "active": 1}))),
            (M_SOFT_DELETE, _result()),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "deactivated"
        assert data["iso_map_id"] == 5
        assert data["iso_doc_no"] is None

        delete_params = _params_for(session, M_SOFT_DELETE)
        assert len(delete_params) == 1
        assert delete_params[0]["iso_map_id"] == 5
        assert delete_params[0]["updated_by"] == 1
        session.commit.assert_called_once()

    def test_whitespace_only_trims_to_clear(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=_row({"iso_map_id": 5, "iso_doc_no": "OLD", "active": 1}))),
            (M_SOFT_DELETE, _result()),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "   ",
        })
        assert response.status_code == 200
        assert response.json()["data"]["action"] == "deactivated"

    def test_clear_with_no_existing_row_is_noop(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "unchanged"
        assert data["iso_map_id"] is None
        assert data["iso_doc_no"] is None
        assert _params_for(session, M_SOFT_DELETE) == []
        session.commit.assert_not_called()

    def test_clear_with_inactive_row_is_noop(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=_row({"iso_map_id": 5, "iso_doc_no": "OLD", "active": 0}))),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "",
        })
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "unchanged"
        assert data["iso_map_id"] == 5
        assert _params_for(session, M_SOFT_DELETE) == []

    def test_missing_iso_doc_no_treated_as_clear(self):
        """Payload without iso_doc_no behaves like an empty string (clear)."""
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={"co_id": 1, "menu_id": 10})
        assert response.status_code == 200
        assert response.json()["data"]["action"] == "unchanged"


class TestIsoMapSaveValidation:
    def test_missing_co_id_400(self):
        response = client.post(f"{BASE}/iso_map_save", json={
            "menu_id": 10, "iso_doc_no": "ISO",
        })
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_menu_id_400(self):
        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "iso_doc_no": "ISO",
        })
        assert response.status_code == 400
        assert "menu_id" in response.json()["detail"].lower()

    def test_invalid_co_id_format_400(self):
        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": "abc", "menu_id": 10, "iso_doc_no": "ISO",
        })
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_iso_doc_no_over_max_len_400(self):
        session = make_session([])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "X" * (ISO_DOC_NO_MAX_LEN + 1),
        })
        assert response.status_code == 400
        assert str(ISO_DOC_NO_MAX_LEN) in response.json()["detail"]
        # Rejected before any lookup or write.
        assert _params_for(session, M_INSERT) == []
        assert _params_for(session, M_UPDATE) == []
        session.commit.assert_not_called()

    def test_iso_doc_no_non_string_400(self):
        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": 12345,
        })
        assert response.status_code == 400
        assert "string" in response.json()["detail"].lower()

    def test_unknown_or_inactive_menu_400(self):
        session = make_session([
            (M_BY_CO_MENU, _result(fetchone=None)),
            (M_MENU_EXISTS, _result(fetchone=None)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 999, "iso_doc_no": "ISO",
        })
        assert response.status_code == 400
        assert "menu_id" in response.json()["detail"].lower()
        assert _params_for(session, M_INSERT) == []
        session.commit.assert_not_called()

    def test_db_error_500_rolls_back(self):
        session = MagicMock()
        session.execute.side_effect = Exception("DB connection failed")
        _install(session)

        response = client.post(f"{BASE}/iso_map_save", json={
            "co_id": 1, "menu_id": 10, "iso_doc_no": "ISO",
        })
        assert response.status_code == 500
        session.rollback.assert_called_once()


# =============================================================================
# POST /iso_map_delete — soft delete
# =============================================================================

class TestIsoMapDelete:
    def test_soft_delete_success(self):
        session = make_session([
            (M_SOFT_DELETE, _result()),
            (M_BY_ID, _result(fetchone=_row({
                "iso_map_id": 9, "co_id": 1, "menu_id": 10,
                "iso_doc_no": "ISO", "active": 1,
            }))),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_delete", json={"iso_map_id": 9})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["action"] == "deactivated"
        assert data["iso_map_id"] == 9

        delete_params = _params_for(session, M_SOFT_DELETE)
        assert len(delete_params) == 1
        assert delete_params[0]["iso_map_id"] == 9
        assert delete_params[0]["updated_by"] == 1
        session.commit.assert_called_once()

    def test_not_found_404(self):
        session = make_session([
            (M_BY_ID, _result(fetchone=None)),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_delete", json={"iso_map_id": 999})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_already_inactive_is_noop(self):
        session = make_session([
            (M_SOFT_DELETE, _result()),
            (M_BY_ID, _result(fetchone=_row({
                "iso_map_id": 9, "co_id": 1, "menu_id": 10,
                "iso_doc_no": "ISO", "active": 0,
            }))),
        ])
        _install(session)

        response = client.post(f"{BASE}/iso_map_delete", json={"iso_map_id": 9})
        assert response.status_code == 200
        assert response.json()["data"]["action"] == "unchanged"
        assert _params_for(session, M_SOFT_DELETE) == []
        session.commit.assert_not_called()

    def test_missing_iso_map_id_400(self):
        response = client.post(f"{BASE}/iso_map_delete", json={})
        assert response.status_code == 400
        assert "iso_map_id" in response.json()["detail"].lower()

    def test_invalid_iso_map_id_400(self):
        response = client.post(f"{BASE}/iso_map_delete", json={"iso_map_id": "abc"})
        assert response.status_code == 400
        assert "iso_map_id" in response.json()["detail"].lower()

    def test_db_error_500_rolls_back(self):
        session = MagicMock()
        session.execute.side_effect = Exception("DB connection failed")
        _install(session)

        response = client.post(f"{BASE}/iso_map_delete", json={"iso_map_id": 9})
        assert response.status_code == 500
        session.rollback.assert_called_once()


# =============================================================================
# get_iso_doc_no shared helper (called directly — no HTTP)
# =============================================================================

class TestGetIsoDocNoHelper:
    def test_returns_value_when_mapped(self):
        db = make_session([
            (M_DOC_NO, _result(fetchone=_row({"iso_doc_no": "AMCL/PO/F-01"}))),
        ])
        assert get_iso_doc_no(db, 1, 10) == "AMCL/PO/F-01"
        params = _params_for(db, M_DOC_NO)
        assert params == [{"co_id": 1, "menu_id": 10}]

    def test_coerces_string_ids(self):
        db = make_session([
            (M_DOC_NO, _result(fetchone=_row({"iso_doc_no": "ISO-X"}))),
        ])
        assert get_iso_doc_no(db, "1", "10") == "ISO-X"
        assert _params_for(db, M_DOC_NO) == [{"co_id": 1, "menu_id": 10}]

    def test_returns_none_when_unmapped(self):
        db = make_session([
            (M_DOC_NO, _result(fetchone=None)),
        ])
        assert get_iso_doc_no(db, 1, 10) is None

    def test_returns_none_when_value_blank(self):
        db = make_session([
            (M_DOC_NO, _result(fetchone=_row({"iso_doc_no": ""}))),
        ])
        assert get_iso_doc_no(db, 1, 10) is None

    def test_returns_none_for_none_ids(self):
        db = MagicMock()
        assert get_iso_doc_no(db, None, 10) is None
        assert get_iso_doc_no(db, 1, None) is None
        db.execute.assert_not_called()

    def test_returns_none_for_garbage_ids(self):
        db = MagicMock()
        assert get_iso_doc_no(db, "abc", 10) is None
        assert get_iso_doc_no(db, 1, "xyz") is None
        db.execute.assert_not_called()

    def test_returns_none_on_db_failure(self):
        """The helper must never break a document view/print — lookup errors
        degrade to None (blank ISO space)."""
        db = MagicMock()
        db.execute.side_effect = Exception("DB connection failed")
        assert get_iso_doc_no(db, 1, 10) is None
