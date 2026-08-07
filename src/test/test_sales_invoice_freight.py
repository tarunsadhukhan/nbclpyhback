"""
Tests for Govt Sacking Freight Invoice (invoice_type_id = 7).

Covers:
- GET /api/salesInvoice/govt_sacking_source_list — list dropdown source invoices
- GET /api/salesInvoice/govt_sacking_source/{invoice_id} — detail pre-fill
- POST /api/salesInvoice/create_sales_invoice — type-7 (GOVT_SKG_FREIGHT) branch

All tests are fully mock-based. Because of a pre-existing typo in
src/models/sales.py (SaleInvoiceJute vs SalesInvoiceJute), we never touch
actual ORM models — all DB interactions are MagicMock.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh


client = TestClient(app)


def _mock_row(mapping: dict):
    """Return a MagicMock whose _mapping is the given dict (SQLAlchemy row fake)."""
    row = MagicMock()
    row._mapping = mapping
    return row


class TestGovtSackingFreightInvoice:
    """Tests for the Govt Sacking Freight (invoice_type=7) feature."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        """Override FastAPI deps; capture the mock session per-test."""
        self._mock_session = MagicMock()
        # commit/flush/add/refresh no-ops
        self._mock_session.commit = MagicMock()
        self._mock_session.flush = MagicMock()
        self._mock_session.add = MagicMock()
        self._mock_session.rollback = MagicMock()

        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _source_header_mapping(self, invoice_type: int = 3, intra_inter_state: int = 0):
        """A plausible source Govt Sacking (type-3) header mapping."""
        return {
            "invoice_id": 12345,
            "invoice_no": 452,
            "invoice_date": "2025-12-15",
            "invoice_type": invoice_type,
            "party_id": 77,
            "party_name": "Bihar State Cooperative Marketing Union",
            "billing_to_id": 77,
            "billing_address": "Gandhi Maidan Road",
            "billing_address_additional": "Near Collectorate",
            "billing_zip_code": "800001",
            "billing_gst_no": "10AAAPB0000A1Z5",
            "billing_state_name": "Bihar",
            "shipping_to_id": 77,
            "shipping_address": "Warehouse 12, Industrial Area",
            "shipping_address_additional": "Sector 4",
            "shipping_zip_code": "800002",
            "shipping_gst_no": "10AAAPB0000A1Z5",
            "shipping_state_name": "Bihar",
            "billing_state_code": "10",
            "shipping_state_code": "10",
            "intra_inter_state": intra_inter_state,  # 0=inter, 1=intra
            "branch_id": 5,
            "co_id": 1,
            "branch_prefix": "KOL",
            "co_prefix": "VOW",
            "sales_order_id": 169,
            "sales_order_no": 169,
            "sales_order_date": "2025-06-10",
            "sales_delivery_order_id": 329,
            "delivery_order_no": "DO/25/329",
            "transporter_id": 99,
            "transporter_name": "XYZ Transporters",
            "transporter_address": "Kolkata",
            "transporter_state_code": "19",
            "transporter_state_name": "West Bengal",
            "transporter_branch_id": 42,
            "transporter_gst_no": "19AAACT0000B1Z9",
            "transporter_doc_no": "TD/99/2025",
            "transporter_doc_date": "2025-12-14",
            "buyer_order_no": "BO/169",
            "buyer_order_date": "2025-12-10",
            "vehicle_no": "WB19G5455",
            "container_no": None,
            "eway_bill_no": "EWB1234567890",
            "eway_bill_date": "2025-12-15",
            "pcso_no": "BRFCK/25/7890",
            "pcso_date": "2025-12-15",
            "administrative_office_address": "Patna",
            "destination_rail_head": "Katihar",
            "loading_point": "Kolkata",
            "mode_of_transport": "Road",
        }

    def _source_line_mapping(self):
        return {
            "invoice_line_item_id": 5001,
            "invoice_id": 12345,
            "item_id": 201,
            "item_name": "PRINTED TYPE-A JUTE BAG(580GMS)",
            "hsn_code": "63051040",
            "quantity": 500,
            "uom_id": 17,
            "uom_name": "Bale",
            "rate": 850,
            "amount_without_tax": 425000,
            "total_amount": 501500,
            "remarks": None,
            "pack_sheet": None,
            "net_weight": None,
            "total_weight": None,
        }

    # ------------------------------------------------------------------
    # 1. GET /govt_sacking_source_list
    # ------------------------------------------------------------------

    def test_govt_sacking_source_list_happy_path(self):
        """Returns list of type-3 invoices + total count."""
        row1 = _mock_row({
            "invoice_id": 12345,
            "invoice_no": 452,
            "invoice_date": "2025-12-15",
            "party_id": 77,
            "party_name": "Bihar State",
            "sales_order_id": 169,
            "sales_order_no": "SO/25/169",
            "sales_delivery_order_id": 329,
            "delivery_order_no": "DO/25/329",
            "pcso_no": "BRFCK/25/7890",
            "status_id": 3,
        })
        row2 = _mock_row({
            "invoice_id": 12346,
            "invoice_no": 453,
            "invoice_date": "2025-12-16",
            "party_id": 78,
            "party_name": "Odisha State",
            "sales_order_id": 170,
            "sales_order_no": "SO/25/170",
            "sales_delivery_order_id": 330,
            "delivery_order_no": "DO/25/330",
            "pcso_no": "BRFCK/25/7891",
            "status_id": 3,
        })

        list_result = MagicMock()
        list_result.fetchall.return_value = [row1, row2]
        count_result = MagicMock()
        count_result.scalar.return_value = 2

        # First execute call -> list query; second -> count query
        self._mock_session.execute.side_effect = [list_result, count_result]

        response = client.get(
            "/api/salesInvoice/govt_sacking_source_list?co_id=1&branch_id=5"
        )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
        assert len(body["data"]) == 2
        assert body["total"] == 2
        assert body["data"][0]["invoice_no"] == 452
        assert body["data"][1]["party_name"] == "Odisha State"

    def test_govt_sacking_source_list_missing_params(self):
        """Returns 422 (FastAPI validation) when co_id is missing."""
        response = client.get("/api/salesInvoice/govt_sacking_source_list?branch_id=5")
        # FastAPI's Query(...) raises 422 validation error
        assert response.status_code in (400, 422)

    # ------------------------------------------------------------------
    # 2. GET /govt_sacking_source/{invoice_id}
    # ------------------------------------------------------------------

    def test_govt_sacking_source_detail_happy_path(self):
        """Type-3 source with 1 line -> header + lines returned."""
        header_mapping = self._source_header_mapping(invoice_type=3)
        header_row = _mock_row(header_mapping)
        line_row = _mock_row(self._source_line_mapping())

        header_exec = MagicMock()
        header_exec.fetchone.return_value = header_row
        lines_exec = MagicMock()
        lines_exec.fetchall.return_value = [line_row]

        # First execute -> header; second -> lines
        self._mock_session.execute.side_effect = [header_exec, lines_exec]

        response = client.get(
            "/api/salesInvoice/govt_sacking_source/12345?co_id=1"
        )

        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "header" in body["data"]
        assert "lines" in body["data"]
        assert body["data"]["header"]["invoice_no"] == 452
        assert body["data"]["header"]["pcso_no"] == "BRFCK/25/7890"
        assert len(body["data"]["lines"]) == 1
        assert body["data"]["lines"][0]["item_name"] == "PRINTED TYPE-A JUTE BAG(580GMS)"

    def test_govt_sacking_source_detail_exposes_enriched_header_fields(self):
        """Source detail exposes billing/shipping addresses, transporter GST,
        mode of transport, eway bill, and the FY-formatted sales order number."""
        header_mapping = self._source_header_mapping(invoice_type=3)
        header_row = _mock_row(header_mapping)
        line_row = _mock_row(self._source_line_mapping())

        header_exec = MagicMock()
        header_exec.fetchone.return_value = header_row
        lines_exec = MagicMock()
        lines_exec.fetchall.return_value = [line_row]
        self._mock_session.execute.side_effect = [header_exec, lines_exec]

        response = client.get(
            "/api/salesInvoice/govt_sacking_source/12345?co_id=1"
        )

        assert response.status_code == 200
        header = response.json()["data"]["header"]

        # Party branch addresses (used by freight preview to show billing/shipping addresses)
        assert header["billing_address"] == "Gandhi Maidan Road"
        assert header["billing_address_additional"] == "Near Collectorate"
        assert header["billing_zip_code"] == "800001"
        assert header["billing_state_name"] == "Bihar"
        assert header["billing_gst_no"] == "10AAAPB0000A1Z5"
        assert header["shipping_address"] == "Warehouse 12, Industrial Area"
        assert header["shipping_state_name"] == "Bihar"

        # Transporter + transport details (must surface on the freight invoice preview)
        assert header["transporter_gst_no"] == "19AAACT0000B1Z9"
        assert header["transporter_doc_no"] == "TD/99/2025"
        assert header["mode_of_transport"] == "Road"
        assert header["eway_bill_no"] == "EWB1234567890"

        # Sales order number is FY-prefixed (format_indent_no applied on the endpoint)
        # Date 2025-06-10 → FY 25-26 → "VOW/KOL/SO/25-26/169"
        assert header["sales_order_no_formatted"] == "VOW/KOL/SO/25-26/169"

        # Invoice number is also FY-prefixed so the freight remarks builder can cite
        # the source invoice using the standard formatter (e.g. "VOW/KOL/SI/25-26/452").
        # Date 2025-12-15 → FY 25-26.
        assert header["invoice_no_formatted"] == "VOW/KOL/SI/25-26/452"

    def test_govt_sacking_source_detail_wrong_type(self):
        """Source invoice_type != 3 -> 400 with 'Govt Sacking' in error."""
        header_mapping = self._source_header_mapping(invoice_type=2)  # Hessian
        header_row = _mock_row(header_mapping)
        header_exec = MagicMock()
        header_exec.fetchone.return_value = header_row

        self._mock_session.execute.side_effect = [header_exec]

        response = client.get(
            "/api/salesInvoice/govt_sacking_source/12345?co_id=1"
        )

        assert response.status_code == 400
        detail = response.json().get("detail", "")
        assert "Govt Sacking" in detail or "govt sacking" in detail.lower()

    def test_govt_sacking_source_detail_not_found(self):
        """Source row not found -> 404."""
        header_exec = MagicMock()
        header_exec.fetchone.return_value = None
        self._mock_session.execute.side_effect = [header_exec]

        response = client.get(
            "/api/salesInvoice/govt_sacking_source/99999?co_id=1"
        )

        assert response.status_code == 404

    # ------------------------------------------------------------------
    # 3. POST /create_sales_invoice (invoice_type=7)
    # ------------------------------------------------------------------

    def _make_create_execute_side_effect(
        self,
        src_header_mapping=None,
        src_lines_mappings=None,
        calls_log=None,
    ):
        """
        Build a side_effect callable for db.execute(...) that mimics the
        type-7 create flow's call sequence:
          1. source header fetchone
          2. source lines fetchall
          3. (optional) co_id lookup from branch_mst SELECT
          4. insert_sales_invoice  -> result.lastrowid
          5. insert_invoice_line_item -> result.lastrowid
          6. insert_sales_invoice_dtl_gst
          7. insert_sales_invoice_govtskg
          8. insert_sales_invoice_freight

        The calls_log is a list we append each (sql_str, params) tuple to so
        tests can inspect exact params passed.
        """
        if src_header_mapping is None:
            src_header_mapping = self._source_header_mapping()
        if src_lines_mappings is None:
            src_lines_mappings = [self._source_line_mapping()]

        state = {"n": 0}

        def side_effect(stmt, params=None):
            sql_str = str(stmt).lower() if stmt is not None else ""
            if calls_log is not None:
                calls_log.append({"sql": sql_str, "params": params})
            rv = MagicMock()

            # Identify by SQL substring (robust to call ordering)
            if "from sales_invoice as si" in sql_str and "where si.invoice_id = :invoice_id" in sql_str:
                # source header fetch
                if src_header_mapping is None:
                    rv.fetchone.return_value = None
                else:
                    rv.fetchone.return_value = _mock_row(src_header_mapping)
                return rv
            if "from sales_invoice_dtl as ili" in sql_str:
                # source lines fetch
                rv.fetchall.return_value = [_mock_row(m) for m in src_lines_mappings]
                return rv
            if "from branch_mst where branch_id" in sql_str:
                rv.fetchone.return_value = _mock_row({"co_id": 1})
                return rv
            if "insert into sales_invoice " in sql_str or sql_str.strip().startswith("insert into sales_invoice\n") or "insert into sales_invoice\n" in sql_str or (
                "insert into sales_invoice" in sql_str
                and "sales_invoice_dtl_gst" not in sql_str
                and "sales_invoice_govtskg" not in sql_str
                and "sales_invoice_freight" not in sql_str
                and "sales_invoice_dtl" not in sql_str
                and "sales_invoice_jute" not in sql_str
                and "sales_invoice_hessian" not in sql_str
            ):
                rv.lastrowid = 55555
                return rv
            if "insert into sales_invoice_dtl " in sql_str or (
                "insert into sales_invoice_dtl" in sql_str
                and "sales_invoice_dtl_gst" not in sql_str
            ):
                rv.lastrowid = 77777
                return rv
            if "insert into sales_invoice_dtl_gst" in sql_str:
                rv.lastrowid = 88888
                return rv
            if "insert into sales_invoice_govtskg" in sql_str:
                rv.lastrowid = 99999
                return rv
            if "insert into sales_invoice_freight" in sql_str:
                rv.lastrowid = 111111
                return rv

            # Fallback
            rv.fetchone.return_value = None
            rv.fetchall.return_value = []
            rv.lastrowid = 1
            return rv

        return side_effect

    def test_freight_invoice_create_happy_path(self):
        """Happy path: type-7 create with valid source returns invoice_id."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            calls_log=calls_log
        )

        # Patch find_or_create_freight_item (it uses ORM which we avoid)
        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)) as mock_focf:
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "vehicle_no": "WB19G5455",
                    "freight_amount": 78879.00,
                    "bales_qty": 48,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert "invoice_id" in body
        assert body["invoice_id"] == 55555

        # Verify find_or_create_freight_item was called with co_id=1
        assert mock_focf.called
        args, kwargs = mock_focf.call_args
        # signature: find_or_create_freight_item(db, co_id, user_id)
        assert args[1] == 1  # co_id
        assert args[2] == 1  # user_id (from token)

        # Verify sales_invoice_freight insert params contain source_invoice_id=12345
        freight_insert = None
        for c in calls_log:
            if "insert into sales_invoice_freight" in c["sql"]:
                freight_insert = c
                break
        assert freight_insert is not None, "Expected an INSERT into sales_invoice_freight"
        params = freight_insert["params"]
        assert params is not None
        assert params.get("source_invoice_id") == 12345
        assert params.get("iw_bill_no") == "CTKR2601480"

    def test_freight_invoice_create_stores_invoice_amount_pretax(self):
        """sales_invoice.invoice_amount must be stored PRE-TAX for type 7 (consistent
        with types 1-6). Tax-only fields go into tax_amount / tax_payable."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            calls_log=calls_log
        )

        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)):
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "vehicle_no": "WB19G5455",
                    "freight_amount": 78879.00,
                    "bales_qty": 48,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text

        hdr_insert = next((c for c in calls_log if "insert into sales_invoice" in c["sql"] and "invoice_amount" in c["sql"]), None)
        assert hdr_insert is not None, "Expected header INSERT call"
        # Pre-tax: invoice_amount equals freight_amount, NOT freight + tax
        assert hdr_insert["params"]["invoice_amount"] == 78879.00
        # Tax tracked separately (78879 * 0.18 = 14198.22)
        assert hdr_insert["params"]["tax_amount"] == 14198.22
        assert hdr_insert["params"]["tax_payable"] == 14198.22

    def test_freight_invoice_create_missing_source(self):
        """Missing freight.source_invoice_id -> 400."""
        payload = {
            "invoice_type": 7,
            "co_id": 1,
            "date": "2026-01-19",
            "freight": {
                # no source_invoice_id
                "iw_bill_no": "CTKR2601480",
                "freight_amount": 78879.00,
                "bales_qty": 48,
            },
            "items": [],
        }
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        assert response.status_code == 400
        assert "source_invoice_id" in response.json().get("detail", "")

    def test_freight_invoice_create_source_wrong_type(self):
        """Source invoice not found (fetchone None) -> 400."""
        exec_header_none = MagicMock()
        exec_header_none.fetchone.return_value = None
        self._mock_session.execute.side_effect = [exec_header_none]

        payload = {
            "invoice_type": 7,
            "co_id": 1,
            "date": "2026-01-19",
            "freight": {
                "source_invoice_id": 99999,
                "freight_amount": 78879.00,
                "bales_qty": 48,
            },
            "items": [],
        }
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        assert response.status_code == 400
        detail = response.json().get("detail", "")
        assert "Source" in detail or "type 3" in detail or "not found" in detail.lower()

    def test_freight_invoice_footer_notes_format(self):
        """footer_notes should follow pattern 'PCSO No.<x> Date:<y> | IW Bill No.<x> Date:<y> | Container No.<x>'."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            calls_log=calls_log
        )

        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)):
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "vehicle_no": "WB19G5455",
                    "freight_amount": 78879.00,
                    "bales_qty": 48,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text

        # Find the header insert (into sales_invoice, not dtl/gst/govtskg/freight)
        header_insert = None
        for c in calls_log:
            sql = c["sql"]
            if ("insert into sales_invoice" in sql
                and "sales_invoice_dtl" not in sql
                and "sales_invoice_govtskg" not in sql
                and "sales_invoice_freight" not in sql
                and "sales_invoice_jute" not in sql
                and "sales_invoice_hessian" not in sql
                and "sales_invoice_dtl_gst" not in sql):
                header_insert = c
                break
        assert header_insert is not None, "Expected an INSERT into sales_invoice header"
        footer = header_insert["params"].get("footer_notes", "")
        # Expect the PCSO segment, IW Bill segment, and Container segment separated by |
        assert "PCSO No." in footer, f"footer_notes missing PCSO segment: {footer!r}"
        assert "IW Bill No.CTKR2601480" in footer, f"footer_notes missing IW Bill segment: {footer!r}"
        assert "Container No.CXNU1315111" in footer, f"footer_notes missing Container segment: {footer!r}"
        assert " | " in footer, f"footer_notes missing pipe separator: {footer!r}"

    def test_freight_invoice_line_remarks_format(self):
        """Line remarks should be '<source item name> — <qty> bales'."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            calls_log=calls_log
        )

        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)):
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "freight_amount": 78879.00,
                    "bales_qty": 48,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text

        # Find the line insert
        line_insert = None
        for c in calls_log:
            if ("insert into sales_invoice_dtl" in c["sql"]
                and "sales_invoice_dtl_gst" not in c["sql"]):
                line_insert = c
                break
        assert line_insert is not None, "Expected an INSERT into sales_invoice_dtl line"
        remarks = line_insert["params"].get("remarks") or ""
        # The source item name was "PRINTED TYPE-A JUTE BAG(580GMS)"
        assert remarks.startswith("PRINTED TYPE-A"), f"line remarks should start with source item name: {remarks!r}"
        assert "bales" in remarks, f"line remarks should contain 'bales': {remarks!r}"

    def test_freight_invoice_gst_interstate(self):
        """intra_inter_state=0 (interstate) -> IGST non-zero, CGST=0, SGST=0."""
        calls_log = []
        src_hdr = self._source_header_mapping(intra_inter_state=0)
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            src_header_mapping=src_hdr, calls_log=calls_log
        )

        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)):
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "freight_amount": 78879.00,
                    "bales_qty": 48,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text

        gst_insert = None
        for c in calls_log:
            if "insert into sales_invoice_dtl_gst" in c["sql"]:
                gst_insert = c
                break
        assert gst_insert is not None, "Expected GST insert"
        p = gst_insert["params"]
        assert p["igst_amount"] > 0, f"IGST should be positive for interstate: {p}"
        assert p["cgst_amount"] == 0 or p["cgst_amount"] == 0.0
        assert p["sgst_amount"] == 0 or p["sgst_amount"] == 0.0
        # 18% of 78879 = 14198.22
        assert round(p["igst_amount"], 2) == round(78879.00 * 0.18, 2)

    def test_freight_invoice_gst_intrastate(self):
        """intra_inter_state=1 (intrastate) -> CGST+SGST each half of total tax, IGST=0."""
        calls_log = []
        src_hdr = self._source_header_mapping(intra_inter_state=1)
        self._mock_session.execute.side_effect = self._make_create_execute_side_effect(
            src_header_mapping=src_hdr, calls_log=calls_log
        )

        with patch("src.sales.salesInvoice.find_or_create_freight_item", return_value=(999, 888)):
            payload = {
                "invoice_type": 7,
                "co_id": 1,
                "date": "2026-01-19",
                "freight": {
                    "source_invoice_id": 12345,
                    "iw_bill_no": "CTKR2601480",
                    "iw_bill_date": "2026-01-19",
                    "container_no": "CXNU1315111",
                    "freight_amount": 100000.00,
                    "bales_qty": 50,
                },
                "items": [],
            }
            response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)

        assert response.status_code == 200, response.text

        gst_insert = None
        for c in calls_log:
            if "insert into sales_invoice_dtl_gst" in c["sql"]:
                gst_insert = c
                break
        assert gst_insert is not None, "Expected GST insert"
        p = gst_insert["params"]
        total_tax = round(100000.00 * 0.18, 2)  # 18000.00
        assert p["igst_amount"] == 0 or p["igst_amount"] == 0.0
        # CGST & SGST should sum to total_tax, each roughly half
        assert round(p["cgst_amount"] + p["sgst_amount"], 2) == total_tax
        assert abs(p["cgst_amount"] - total_tax / 2) < 0.01
        assert abs(p["sgst_amount"] - total_tax / 2) < 0.01

    # ------------------------------------------------------------------
    # PUT /update_sales_invoice (type-7 branch)
    # ------------------------------------------------------------------

    def _make_update_execute_side_effect(
        self,
        existing_status: int = 21,
        existing_invoice_type: int = 7,
        existing_freight_id: int | None = 999,
        existing_source_id: int = 12345,
        existing_intra_inter: int = 0,
        existing_line_id: int | None = 77777,
        calls_log=None,
    ):
        """Mimics the type-7 update flow's call sequence."""

        def side_effect(stmt, params=None):
            sql_str = str(stmt).lower() if stmt is not None else ""
            if calls_log is not None:
                calls_log.append({"sql": sql_str, "params": params})
            rv = MagicMock()

            # 1. Existing-row check (joins sales_invoice + sales_invoice_freight)
            if "from sales_invoice si" in sql_str and "left join sales_invoice_freight" in sql_str:
                rv.fetchone.return_value = _mock_row({
                    "invoice_id": params["id"] if params else 1,
                    "status_id": existing_status,
                    "invoice_type": existing_invoice_type,
                    "intra_inter_state": existing_intra_inter,
                    "sales_invoice_freight_id": existing_freight_id,
                    "source_invoice_id": existing_source_id,
                })
                return rv
            # 2. get_govt_sacking_source_by_id (for footer recompute)
            if "from sales_invoice as si" in sql_str and "where si.invoice_id = :invoice_id" in sql_str:
                rv.fetchone.return_value = _mock_row(self._source_header_mapping(intra_inter_state=existing_intra_inter))
                return rv
            # 3. SELECT line id
            if "select invoice_line_item_id" in sql_str and "from sales_invoice_dtl" in sql_str:
                if existing_line_id is None:
                    rv.fetchone.return_value = None
                else:
                    rv.fetchone.return_value = _mock_row({"invoice_line_item_id": existing_line_id})
                return rv
            # 4. get_govt_sacking_source_lines
            if "from sales_invoice_dtl as ili" in sql_str:
                rv.fetchone.return_value = _mock_row(self._source_line_mapping())
                return rv
            # All UPDATEs
            return rv

        return side_effect

    def test_freight_invoice_update_happy_path(self):
        """Type-7 update against a Draft freight invoice succeeds and recomputes totals."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_update_execute_side_effect(calls_log=calls_log)

        payload = {
            "id": 55555,
            "invoice_type": 7,
            "date": "2026-01-20",
            "freight": {
                "source_invoice_id": 12345,  # same as existing — allowed
                "iw_bill_no": "CTKR2601999",
                "iw_bill_date": "2026-01-20",
                "container_no": "CXNU9999999",
                "vehicle_no": "WB19G5455",
                "freight_amount": 50000.0,
                "bales_qty": 40,
            },
            "items": [],
        }
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["invoice_id"] == 55555
        assert body["status_id"] == 21

        # Verify the header UPDATE stores invoice_amount PRE-TAX (= freight_amount, 50000)
        # consistent with types 1-6. Tax goes only into tax_amount/tax_payable.
        # Post-tax total is reconstructable as invoice_amount + tax_amount = 59000.
        hdr_update = next((c for c in calls_log if "update sales_invoice" in c["sql"] and "footer_notes" in c["sql"]), None)
        assert hdr_update is not None, "Expected header UPDATE call"
        assert hdr_update["params"]["invoice_amount"] == 50000.0
        assert hdr_update["params"]["tax_amount"] == 9000.0
        assert hdr_update["params"]["container_no"] == "CXNU9999999"

        # Verify line UPDATE
        line_update = next((c for c in calls_log if "update sales_invoice_dtl" in c["sql"] and "amount_without_tax" in c["sql"]), None)
        assert line_update is not None
        assert line_update["params"]["quantity"] == 40.0
        assert line_update["params"]["amount_without_tax"] == 50000.0

        # Verify GST UPDATE — interstate (intra_inter_state=0) → IGST 18% only
        gst_update = next((c for c in calls_log if "update sales_invoice_dtl_gst" in c["sql"]), None)
        assert gst_update is not None
        assert gst_update["params"]["igst_amount"] == 9000.0
        assert gst_update["params"]["cgst_amount"] == 0.0

        # Verify freight UPDATE
        freight_update = next((c for c in calls_log if "update sales_invoice_freight" in c["sql"]), None)
        assert freight_update is not None
        assert freight_update["params"]["iw_bill_no"] == "CTKR2601999"

    def test_freight_invoice_update_rejects_non_draft(self):
        """Type-7 update against a Pending Approval (status=20) invoice is rejected."""
        self._mock_session.execute.side_effect = self._make_update_execute_side_effect(existing_status=20)

        payload = {
            "id": 55555,
            "invoice_type": 7,
            "freight": {
                "source_invoice_id": 12345,
                "iw_bill_no": "X",
                "iw_bill_date": "2026-01-20",
                "container_no": "C",
                "vehicle_no": "V",
                "freight_amount": 100,
                "bales_qty": 1,
            },
        }
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 400
        assert "draft" in response.json()["detail"].lower()

    def test_freight_invoice_update_rejects_source_change(self):
        """Repointing source_invoice_id to a different value is rejected."""
        self._mock_session.execute.side_effect = self._make_update_execute_side_effect(existing_source_id=12345)

        payload = {
            "id": 55555,
            "invoice_type": 7,
            "freight": {
                "source_invoice_id": 99999,  # different from existing
                "iw_bill_no": "X",
                "iw_bill_date": "2026-01-20",
                "container_no": "C",
                "vehicle_no": "V",
                "freight_amount": 100,
                "bales_qty": 1,
            },
        }
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 400
        assert "immutable" in response.json()["detail"].lower()

    def test_freight_invoice_update_rejects_wrong_existing_type(self):
        """Trying to PUT with invoice_type=7 against a non-freight invoice is rejected."""
        self._mock_session.execute.side_effect = self._make_update_execute_side_effect(existing_invoice_type=3)

        payload = {
            "id": 55555,
            "invoice_type": 7,
            "freight": {
                "source_invoice_id": 12345,
                "iw_bill_no": "X",
                "iw_bill_date": "2026-01-20",
                "container_no": "C",
                "vehicle_no": "V",
                "freight_amount": 100,
                "bales_qty": 1,
            },
        }
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 400
        assert "freight" in response.json()["detail"].lower() or "standard update" in response.json()["detail"].lower()

    def test_freight_invoice_update_intrastate_gst(self):
        """Intra-state freight update splits 18% GST into CGST 9% + SGST 9%."""
        calls_log = []
        self._mock_session.execute.side_effect = self._make_update_execute_side_effect(
            existing_intra_inter=1,
            calls_log=calls_log,
        )

        payload = {
            "id": 55555,
            "invoice_type": 7,
            "date": "2026-01-20",
            "freight": {
                "source_invoice_id": 12345,
                "iw_bill_no": "X",
                "iw_bill_date": "2026-01-20",
                "container_no": "C",
                "vehicle_no": "V",
                "freight_amount": 10000.0,
                "bales_qty": 10,
            },
        }
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 200, response.text

        gst_update = next((c for c in calls_log if "update sales_invoice_dtl_gst" in c["sql"]), None)
        assert gst_update is not None
        # intra-state: total tax = 1800, split 900/900
        assert gst_update["params"]["cgst_amount"] == 900.0
        assert gst_update["params"]["sgst_amount"] == 900.0
        assert gst_update["params"]["igst_amount"] == 0.0
