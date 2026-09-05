"""Smallest checks for GET /api/hrmsReports/employee-face (row shaping + flags)
and /employee-face-photo/{id} (base64 -> image bytes)."""
import base64
from datetime import datetime
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _override(session):
    app.dependency_overrides[get_tenant_db] = lambda: session
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}


def test_employee_face_report_shapes_rows():
    session = MagicMock()
    session.execute.return_value.fetchall.return_value = [_row({
        "emp_face_id": 1503, "eb_id": 18, "emp_code": "E018", "emp_name": "A B",
        "dept_desc": "SPINNING", "sub_dept_desc": "SPG-1", "active": 0,
        "has_face": 1, "has_mobile_face": 1, "has_photo": 0,
        "mobile_model_ver": "mobilefacenet-v2",
        "mobile_embed_updated": datetime(2026, 9, 3, 5, 46, 26),
        "updated_by": 0, "updated_date_time": datetime(2026, 9, 3, 5, 46, 26),
    })]
    _override(session)
    try:
        res = client.get("/api/hrmsReports/employee-face",
                         params={"co_id": 1, "branch_id": 87, "active": 0})
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 200, res.text
    row = res.json()["data"][0]
    assert (row["id"], row["emp_code"], row["department"]) == (1503, "E018", "SPINNING")
    assert (row["active"], row["has_face"], row["has_photo"]) == ("No", "Yes", "No")
    assert row["updated_date_time"] == "2026-09-03 05:46"
    # active=0 must reach the query as 0, not be dropped as falsy
    assert session.execute.call_args.args[1] == {"co_id": 1, "branch_id": 87, "active": 0}


def test_employee_face_report_requires_co_id():
    _override(MagicMock())
    try:
        assert client.get("/api/hrmsReports/employee-face").status_code == 400
    finally:
        app.dependency_overrides = {}


def test_employee_face_photo_decodes_base64():
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = _row(
        {"photo_html": base64.b64encode(jpeg).decode()})
    _override(session)
    try:
        res = client.get("/api/hrmsReports/employee-face-photo/1503", params={"co_id": 1})
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content == jpeg
    assert session.execute.call_args.args[1] == {"emp_face_id": 1503, "co_id": 1}


def test_employee_face_photo_404_when_missing():
    session = MagicMock()
    session.execute.return_value.fetchone.return_value = None
    _override(session)
    try:
        res = client.get("/api/hrmsReports/employee-face-photo/1", params={"co_id": 1})
    finally:
        app.dependency_overrides = {}
    assert res.status_code == 404
