"""
Tests for additional charges on GET /api/billPass/get_bill_pass_by_id/{inward_id}.

Covers:
- Response includes `additional_charges` array shaped from proc_inward_additional + proc_gst.
- Summary aggregates (additional_net / _tax / _total / _count) reflect backend rollup.
- `summary.net_payable` = sr_total - dr_total + cr_total + additional_net + additional_tax.
- Empty case returns an empty list and zero summary fields.
"""

from datetime import date
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh


client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


def _header_row(**overrides):
    base = {
        "inward_id": 101,
        "inward_sequence_no": 42,
        "inward_date": date(2025, 4, 15),
        "bill_pass_no": "SR/HO/IN/0042",
        "bill_pass_date": date(2025, 4, 16),
        "invoice_date": None,
        "invoice_amount": None,
        "invoice_no": None,
        "invoice_recvd_date": None,
        "invoice_due_date": None,
        "supplier_id": 77,
        "supplier_name": "Acme Suppliers",
        "branch_id": 1,
        "branch_name": "Head Office",
        "branch_prefix": "HO",
        "co_id": 1,
        "co_prefix": "ACME",
        "sr_status": 3,
        "billpass_status": 0,
        "sr_status_name": "Approved",
        "sr_remarks": None,
        "challan_no": "CH-1",
        "challan_date": date(2025, 4, 14),
        "round_off_value": 0,
        "gross_amount": 1000,
        "net_amount": 1180,
        # SR totals
        "sr_taxable": 1000.0,
        "sr_tax": 180.0,
        "sr_cgst": 90.0,
        "sr_sgst": 90.0,
        "sr_igst": 0.0,
        "sr_total": 1180.0,
        "sr_line_count": 1,
        # DR/CR totals
        "dr_total": 0.0,
        "dr_count": 0,
        "cr_total": 0.0,
        "cr_count": 0,
        # Additional charges totals (overridden per test)
        "additional_net": 0.0,
        "additional_cgst": 0.0,
        "additional_sgst": 0.0,
        "additional_igst": 0.0,
        "additional_tax": 0.0,
        "additional_total": 0.0,
        "additional_count": 0,
        # Net payable is computed by the query expression; mock it explicitly.
        "net_payable": 1180.0,
    }
    base.update(overrides)
    return _row(base)


class TestBillPassAdditionalCharges:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def _wire_execute_chain(self, header, sr_lines, drcr_notes, drcr_lines, additional):
        """Mock the 5 db.execute(...) calls in get_bill_pass_by_id, in order."""
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=header)),
            MagicMock(fetchall=MagicMock(return_value=sr_lines)),
            MagicMock(fetchall=MagicMock(return_value=drcr_notes)),
            MagicMock(fetchall=MagicMock(return_value=drcr_lines)),
            MagicMock(fetchall=MagicMock(return_value=additional)),
        ]

    def test_returns_additional_charges_when_present(self):
        header = _header_row(
            additional_net=500.0,
            additional_cgst=45.0,
            additional_sgst=45.0,
            additional_igst=0.0,
            additional_tax=90.0,
            additional_total=590.0,
            additional_count=2,
            net_payable=1770.0,  # 1180 + 500 + 90
        )
        additional_rows = [
            _row({
                "proc_inward_additional_id": 201,
                "inward_id": 101,
                "additional_charges_id": 1,
                "additional_charges_name": "Freight",
                "default_tax_pct": 18.0,
                "qty": 1,
                "rate": 300.0,
                "net_amount": 300.0,
                "remarks": "to-pay",
                "tax_pct": 18.0,
                "igst_amount": 0.0,
                "sgst_amount": 27.0,
                "cgst_amount": 27.0,
                "tax_amount": 54.0,
            }),
            _row({
                "proc_inward_additional_id": 202,
                "inward_id": 101,
                "additional_charges_id": 2,
                "additional_charges_name": "Insurance",
                "default_tax_pct": 18.0,
                "qty": 1,
                "rate": 200.0,
                "net_amount": 200.0,
                "remarks": None,
                "tax_pct": 18.0,
                "igst_amount": 0.0,
                "sgst_amount": 18.0,
                "cgst_amount": 18.0,
                "tax_amount": 36.0,
            }),
        ]

        self._wire_execute_chain(
            header=header, sr_lines=[], drcr_notes=[], drcr_lines=[], additional=additional_rows,
        )

        response = client.get("/api/billPass/get_bill_pass_by_id/101")

        assert response.status_code == 200, response.text
        data = response.json()

        # Top-level array
        assert "additional_charges" in data
        assert len(data["additional_charges"]) == 2
        freight = data["additional_charges"][0]
        assert freight["additional_charges_name"] == "Freight"
        assert freight["net_amount"] == 300.0
        assert freight["tax_amount"] == 54.0
        assert freight["remarks"] == "to-pay"

        # Summary rollup
        s = data["summary"]
        assert s["additional_count"] == 2
        assert s["additional_net"] == 500.0
        assert s["additional_tax"] == 90.0
        assert s["additional_total"] == 590.0

        # Net payable includes additional charges (from mocked query expression)
        assert s["net_payable"] == 1770.0

    def test_empty_additional_charges_defaults_to_zero(self):
        header = _header_row()  # all additional fields 0
        self._wire_execute_chain(
            header=header, sr_lines=[], drcr_notes=[], drcr_lines=[], additional=[],
        )

        response = client.get("/api/billPass/get_bill_pass_by_id/101")

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["additional_charges"] == []
        s = data["summary"]
        assert s["additional_count"] == 0
        assert s["additional_net"] == 0.0
        assert s["additional_tax"] == 0.0
        assert s["additional_total"] == 0.0
        # Net payable should match SR total when there are no adjustments.
        assert s["net_payable"] == 1180.0

    def test_net_payable_includes_additional_with_drcr(self):
        """Combined DR/CR + additional charges. Verifies the endpoint simply
        surfaces `net_payable` from the query (where the formula lives)."""
        header = _header_row(
            dr_total=100.0,
            dr_count=1,
            cr_total=50.0,
            cr_count=1,
            additional_net=200.0,
            additional_tax=36.0,
            additional_total=236.0,
            additional_count=1,
            net_payable=1366.0,  # 1180 - 100 + 50 + 200 + 36
        )
        self._wire_execute_chain(
            header=header,
            sr_lines=[],
            drcr_notes=[],
            drcr_lines=[],
            additional=[
                _row({
                    "proc_inward_additional_id": 301,
                    "inward_id": 101,
                    "additional_charges_id": 1,
                    "additional_charges_name": "Freight",
                    "default_tax_pct": 18.0,
                    "qty": 1,
                    "rate": 200.0,
                    "net_amount": 200.0,
                    "remarks": "",
                    "tax_pct": 18.0,
                    "igst_amount": 0.0,
                    "sgst_amount": 18.0,
                    "cgst_amount": 18.0,
                    "tax_amount": 36.0,
                }),
            ],
        )

        response = client.get("/api/billPass/get_bill_pass_by_id/101")

        assert response.status_code == 200, response.text
        s = response.json()["summary"]
        assert s["dr_total"] == 100.0
        assert s["cr_total"] == 50.0
        assert s["additional_total"] == 236.0
        assert s["net_payable"] == 1366.0
