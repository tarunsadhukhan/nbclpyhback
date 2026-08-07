"""Tests for editable inward-level header fields on Stores Receipt save.

Covers:
1. update_inward_sr() SQL includes all editable inward-level columns.
2. POST /storesReceipt/save_sr accepts the new header fields and passes them
   through to the UPDATE statement, including empty-string → NULL normalization
   and 'YYYY-MM-DD' → date parsing.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.procurement.query import update_inward_sr


client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


EDITABLE_COLUMNS = [
    "invoice_no",
    "invoice_date",
    "invoice_amount",
    "invoice_recvd_date",
    "challan_no",
    "challan_date",
    "vehicle_number",
    "driver_name",
    "driver_contact_number",
    "inspection_date",
    "consignment_no",
    "consignment_date",
    "ewaybillno",
    "ewaybill_date",
    "despatch_remarks",
    "receipts_remarks",
]


class TestUpdateInwardSrQuery:
    """update_inward_sr() SQL must include every editable inward-level column."""

    def test_returns_text_object(self):
        result = update_inward_sr()
        assert isinstance(result, type(text("")))

    @pytest.mark.parametrize("column", EDITABLE_COLUMNS)
    def test_includes_column(self, column):
        sql_str = str(update_inward_sr())
        assert f"{column} = :{column}" in sql_str, f"Expected '{column} = :{column}' in UPDATE"


class TestSaveSrHeaderFields:
    """POST /storesReceipt/save_sr forwards editable header fields to the UPDATE."""

    def _make_mock_session_for_save(self):
        mock_session = MagicMock()

        def execute_side_effect(query, params=None):
            params = params or {}
            sql_str = str(query).upper()
            mock_result = MagicMock()

            if "SELECT APPROVED_QTY" in sql_str:
                row = MagicMock()
                row.approved_qty = 10
                mock_result.fetchone.return_value = row
                return mock_result

            if "SELECT BRANCH_ID, SR_NO, SR_STATUS" in sql_str:
                row = MagicMock()
                row.branch_id = 1
                row.sr_no = None
                row.sr_status = 0
                mock_result.fetchone.return_value = row
                return mock_result

            if "SELECT CO_ID FROM BRANCH_MST" in sql_str:
                row = MagicMock()
                row.__getitem__ = lambda self, idx: 1 if idx == 0 else None
                mock_result.fetchone.return_value = row
                return mock_result

            if "INDIA_GST" in sql_str and "CO_CONFIG" in sql_str:
                # Disable GST branch for this test so we focus on header UPDATE.
                mock_result.fetchone.return_value = None
                return mock_result

            # Capture the inward header UPDATE for assertions.
            if sql_str.startswith("UPDATE PROC_INWARD") and "SR_NO = :SR_NO" in sql_str:
                mock_session._captured_header_update = params

            mock_result.fetchone.return_value = None
            mock_result.fetchall.return_value = []
            mock_result.lastrowid = 1
            return mock_result

        mock_session.execute.side_effect = execute_side_effect
        mock_session.commit = MagicMock()
        return mock_session

    def test_save_persists_editable_header_fields(self):
        mock_session = self._make_mock_session_for_save()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

        try:
            payload = {
                "inward_id": 1,
                "sr_date": "2026-04-20",
                "sr_remarks": "test",
                "invoice_no": "INV-42",
                "invoice_date": "2026-04-15",
                "invoice_amount": 1234.56,
                "invoice_recvd_date": "2026-04-16",
                "challan_no": "CH-7",
                "challan_date": "2026-04-10",
                "vehicle_number": "MH12AB1234",
                "driver_name": "Ram",
                "driver_contact_no": "9999999999",
                "inspection_date": "2026-04-18",
                "consignment_no": "CN-9",
                "consignment_date": "2026-04-11",
                "ewaybillno": "EWB-5",
                "ewaybill_date": "2026-04-12",
                "despatch_remarks": "dispatch note",
                "receipts_remarks": "received ok",
                "line_items": [
                    {
                        "inward_dtl_id": 100,
                        "accepted_rate": 50.0,
                        "amount": 500.0,
                        "warehouse_id": 3,
                        "hsn_code": "1234",
                    }
                ],
                "additional_charges": [],
            }
            response = client.post("/api/storesReceipt/save_sr", json=payload)
            assert response.status_code == 200, response.text

            captured = getattr(mock_session, "_captured_header_update", None)
            assert captured is not None, "header UPDATE was not captured"

            assert captured["invoice_no"] == "INV-42"
            assert str(captured["invoice_date"]) == "2026-04-15"
            assert captured["invoice_amount"] == 1234.56
            assert str(captured["invoice_recvd_date"]) == "2026-04-16"
            assert captured["challan_no"] == "CH-7"
            assert str(captured["challan_date"]) == "2026-04-10"
            assert captured["vehicle_number"] == "MH12AB1234"
            assert captured["driver_name"] == "Ram"
            # Frontend sends driver_contact_no, bind param uses DB column name.
            assert captured["driver_contact_number"] == "9999999999"
            assert str(captured["inspection_date"]) == "2026-04-18"
            assert captured["consignment_no"] == "CN-9"
            assert str(captured["consignment_date"]) == "2026-04-11"
            assert captured["ewaybillno"] == "EWB-5"
            assert str(captured["ewaybill_date"]) == "2026-04-12"
            assert captured["despatch_remarks"] == "dispatch note"
            assert captured["receipts_remarks"] == "received ok"
        finally:
            app.dependency_overrides.clear()

    def test_save_normalizes_empty_strings_to_null(self):
        mock_session = self._make_mock_session_for_save()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

        try:
            payload = {
                "inward_id": 1,
                "sr_date": "2026-04-20",
                "invoice_no": "   ",
                "invoice_date": "",
                "challan_no": "",
                "vehicle_number": "",
                "driver_contact_no": "",
                "line_items": [
                    {
                        "inward_dtl_id": 100,
                        "accepted_rate": 50.0,
                        "amount": 500.0,
                        "warehouse_id": 3,
                        "hsn_code": "1234",
                    }
                ],
                "additional_charges": [],
            }
            response = client.post("/api/storesReceipt/save_sr", json=payload)
            assert response.status_code == 200, response.text

            captured = getattr(mock_session, "_captured_header_update", None)
            assert captured is not None

            assert captured["invoice_no"] is None
            assert captured["invoice_date"] is None
            assert captured["challan_no"] is None
            assert captured["vehicle_number"] is None
            assert captured["driver_contact_number"] is None
        finally:
            app.dependency_overrides.clear()
