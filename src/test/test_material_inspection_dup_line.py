"""
Regression test for the duplicate jute_mr_li row bug on QC Complete / Save.

Bug: the FE PO auto-fill rebuilds line items with a null primary key (serialized
as jute_mr_li_id = 0). A PO re-fill / double-submit therefore re-sends an
already-saved, PO-linked line as "new", and complete_material_inspection() used
to INSERT it unconditionally -> a second identical jute_mr_li row.

Guard (materialInspection.py): when a line arrives with id <= 0 AND a
jute_po_li_id, first look up an existing active line for the same
(jute_mr_id, jute_po_li_id); if found, adopt its id and UPDATE instead of INSERT.

These tests exercise the endpoint with a SQL-dispatching mock session and assert
the INSERT-vs-UPDATE decision. No DB required.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

COMPLETE_URL = "/api/juteMaterialInspection/complete_inspection?co_id=1"


def _make_execute(existing_li_id):
    """Return a db.execute side_effect that records SQL and routes results.

    - the per-line match SELECT returns `existing_li_id` from .scalar()
    - the header lookup returns a not-yet-QC row from .fetchone()
    - INSERTs expose a fake .lastrowid
    """
    calls = []

    def _exec(sql, params=None):
        s = " ".join(str(sql).split()).upper()
        calls.append((s, params or {}))
        res = MagicMock()

        header_row = MagicMock()
        header_row._mapping = {"qc_check": 0}
        res.fetchone.return_value = header_row
        res.fetchall.return_value = []

        if s.startswith("SELECT JUTE_MR_LI_ID FROM JUTE_MR_LI"):
            res.scalar.return_value = existing_li_id
        else:
            res.scalar.return_value = None

        res.lastrowid = 999
        return res

    _exec.calls = calls
    return _exec


def _override(session):
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
    app.dependency_overrides[get_tenant_db] = lambda: session


def _teardown():
    app.dependency_overrides.clear()


def _body(**line_overrides):
    line = {
        "jute_mr_li_id": 0,
        "jute_po_li_id": 42,
        "actual_item_id": 7,
        "actual_qty": 650,
        "actual_weight": 100,
    }
    line.update(line_overrides)
    # No header fields -> no jute_mr UPDATE noise. save_only -> skip qc-complete query.
    return {"jute_mr_id": 100, "save_only": True, "line_items": [line]}


def _li_inserts(calls):
    return [c for c in calls if c[0].startswith("INSERT INTO JUTE_MR_LI")]


def _li_updates(calls):
    # line-content updates only — the reconcile pass has its own SET ACTIVE = 0 shape
    return [
        c for c in calls
        if c[0].startswith("UPDATE JUTE_MR_LI") and "SET ACTIVE = 0" not in c[0]
    ]


def _li_deactivations(calls):
    return [c for c in calls if c[0].startswith("UPDATE JUTE_MR_LI SET ACTIVE = 0")]


def _li_matches(calls):
    return [c for c in calls if c[0].startswith("SELECT JUTE_MR_LI_ID FROM JUTE_MR_LI")]


def test_po_line_with_existing_row_updates_not_inserts():
    """id=0 + jute_po_li_id that already exists -> UPDATE the existing row, no duplicate."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=555)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(COMPLETE_URL, json=_body())
        assert resp.status_code == 200, resp.text

        assert not _li_inserts(exec_fn.calls), "must NOT insert a duplicate when the PO line already exists"
        updates = _li_updates(exec_fn.calls)
        assert updates, "should UPDATE the matched existing line"
        assert any(c[1].get("jute_mr_li_id") == 555 for c in updates), "UPDATE must target the adopted existing id"
    finally:
        _teardown()


def test_po_line_without_existing_row_inserts():
    """id=0 + jute_po_li_id with no existing match -> genuine new line, INSERT."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(COMPLETE_URL, json=_body())
        assert resp.status_code == 200, resp.text

        assert _li_inserts(exec_fn.calls), "no match -> should INSERT the new line"
        assert not _li_updates(exec_fn.calls)
        assert _li_matches(exec_fn.calls), "guard should have run the match lookup for a PO-linked line"
    finally:
        _teardown()


def test_manual_line_without_po_link_skips_guard_and_inserts():
    """id=0 + jute_po_li_id=None -> manual new line: guard skipped, INSERT (no merge)."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=555)  # would be adopted IF the guard ran
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(COMPLETE_URL, json=_body(jute_po_li_id=None))
        assert resp.status_code == 200, resp.text

        assert not _li_matches(exec_fn.calls), "guard must NOT query for lines with no PO link"
        assert _li_inserts(exec_fn.calls), "manual line stays an INSERT"
        assert not _li_updates(exec_fn.calls)
    finally:
        _teardown()


# ---------------------------------------------------------------------------
# Reconcile-to-payload: rows the FE did not send back get soft-deactivated
# ---------------------------------------------------------------------------


def test_reconcile_deactivates_rows_absent_from_payload():
    """Payload keeps id 555 -> deactivation runs, excluding exactly that id."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(COMPLETE_URL, json=_body(jute_mr_li_id=555))
        assert resp.status_code == 200, resp.text

        deact = _li_deactivations(exec_fn.calls)
        assert deact, "reconcile pass must run when the payload has lines"
        sql, params = deact[0]
        assert "NOT IN" in sql
        assert params["jute_mr_id"] == 100
        assert 555 in [v for k, v in params.items() if k.startswith("keep_")]
    finally:
        _teardown()


def test_reconcile_keeps_freshly_inserted_row():
    """A new id=0 line INSERTs (lastrowid 999) and 999 must be excluded from deactivation."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(COMPLETE_URL, json=_body(jute_po_li_id=None))
        assert resp.status_code == 200, resp.text

        assert _li_inserts(exec_fn.calls)
        deact = _li_deactivations(exec_fn.calls)
        assert deact
        _, params = deact[0]
        assert 999 in [v for k, v in params.items() if k.startswith("keep_")]
    finally:
        _teardown()


def test_reconcile_skipped_for_empty_line_items():
    """Empty line_items (legacy/defective caller) must NOT wipe the record's lines."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(
            COMPLETE_URL,
            json={"jute_mr_id": 100, "save_only": True, "line_items": []},
        )
        assert resp.status_code == 200, resp.text

        assert not _li_deactivations(exec_fn.calls), "no lines sent -> reconcile must be skipped"
    finally:
        _teardown()


def test_reconcile_runs_for_explicit_lines_cleared():
    """lines_cleared=True with an empty set -> intentional wipe: deactivate ALL rows."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(
            COMPLETE_URL,
            json={"jute_mr_id": 100, "save_only": True, "line_items": [], "lines_cleared": True},
        )
        assert resp.status_code == 200, resp.text

        deact = _li_deactivations(exec_fn.calls)
        assert deact, "explicit lines_cleared must trigger the reconcile"
        sql, params = deact[0]
        assert "NOT IN" not in sql, "empty kept set -> no NOT IN clause, all rows deactivate"
        assert params["jute_mr_id"] == 100
    finally:
        _teardown()


def test_po_detach_with_zero_clears_header_po():
    """po_id=0 -> explicit detach: header UPDATE binds po_id as NULL."""
    session = MagicMock()
    exec_fn = _make_execute(existing_li_id=None)
    session.execute.side_effect = exec_fn
    _override(session)
    try:
        resp = client.post(
            COMPLETE_URL,
            json={"jute_mr_id": 100, "save_only": True, "po_id": 0, "line_items": [], "lines_cleared": True},
        )
        assert resp.status_code == 200, resp.text

        header_updates = [c for c in exec_fn.calls if c[0].startswith("UPDATE JUTE_MR SET")]
        assert header_updates, "po_id=0 must produce a header update"
        assert any("PO_ID = :PO_ID" in c[0] and c[1].get("po_id") is None for c in header_updates), \
            "po_id 0 must be stored as NULL (detach)"
    finally:
        _teardown()
