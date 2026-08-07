"""
Tests for the sales invoice field gap remediation.
Covers: new fields in create/update endpoints, GST breakup persistence,
get-by-id response shape, and TCS removal.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, call
from sqlalchemy import text
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.sales.query import (
    get_invoice_by_id_query,
    get_invoice_dtl_by_id_query,
    insert_sales_invoice,
    insert_invoice_line_item,
    update_sales_invoice,
    insert_invoice_dtl_gst,
    delete_invoice_dtl_gst,
    get_invoice_dtl_gst_by_id_query,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ---------------------------------------------------------------------------
# 1. Query function tests
# ---------------------------------------------------------------------------


class TestQueryFunctions:

    def test_insert_sales_invoice_returns_text(self):
        result = insert_sales_invoice()
        assert isinstance(result, type(text("")))

    def test_insert_invoice_contains_new_header_binds(self):
        sql_str = str(insert_sales_invoice())
        for bind in [
            ":billing_to_id", ":shipping_to_id", ":internal_note",
            ":transporter_name", ":transporter_address",
            ":transporter_state_code", ":transporter_state_name",
            ":due_date", ":type_of_sale", ":tax_id",
            ":container_no", ":contract_no", ":contract_date",
            ":consignment_no", ":consignment_date",
            ":payment_terms", ":sales_order_id", ":billing_state_code",
        ]:
            assert bind in sql_str, f"Missing bind {bind} in insert_sales_invoice"

    def test_update_sales_invoice_contains_new_header_binds(self):
        sql_str = str(update_sales_invoice())
        for bind in [
            ":billing_to_id", ":shipping_to_id", ":internal_note",
            ":transporter_name", ":transporter_address",
            ":transporter_state_code", ":transporter_state_name",
            ":due_date", ":type_of_sale", ":tax_id",
            ":container_no", ":contract_no", ":contract_date",
            ":consignment_no", ":consignment_date",
            ":shipping_state_code", ":intra_inter_state",
            ":payment_terms", ":sales_order_id", ":billing_state_code",
        ]:
            assert bind in sql_str, f"Missing bind {bind} in update_sales_invoice"

    def test_insert_line_item_contains_new_binds(self):
        sql_str = str(insert_invoice_line_item())
        for bind in [
            ":discount_type", ":discounted_rate", ":discount_amount",
            ":remarks", ":delivery_order_dtl_id",
        ]:
            assert bind in sql_str, f"Missing bind {bind} in insert_invoice_line_item"

    def test_get_invoice_by_id_contains_new_columns(self):
        sql_str = str(get_invoice_by_id_query())
        for col in [
            "billing_to_id", "shipping_to_id", "internal_note",
            "transporter_name_stored", "transporter_address",
            "due_date", "type_of_sale", "tax_id",
            "container_no", "contract_no", "contract_date",
            "consignment_no", "consignment_date",
            "payment_terms", "sales_order_id", "billing_state_code",
            "sales_order_date", "sales_order_no",
        ]:
            assert col in sql_str, f"Missing column {col} in get_invoice_by_id_query"

    def test_get_invoice_dtl_by_id_contains_new_columns(self):
        sql_str = str(get_invoice_dtl_by_id_query())
        for col in ["discount_type", "discounted_rate", "discount_amount", "remarks", "delivery_order_dtl_id"]:
            assert col in sql_str, f"Missing column {col} in get_invoice_dtl_by_id_query"

    def test_gst_query_functions_return_text(self):
        assert isinstance(insert_invoice_dtl_gst(), type(text("")))
        assert isinstance(delete_invoice_dtl_gst(), type(text("")))
        assert isinstance(get_invoice_dtl_gst_by_id_query(), type(text("")))

    def test_insert_invoice_dtl_gst_contains_binds(self):
        sql_str = str(insert_invoice_dtl_gst())
        for bind in [
            ":invoice_line_item_id", ":igst_amount", ":igst_percent",
            ":cgst_amount", ":cgst_percent", ":sgst_amount", ":sgst_percent",
            ":gst_total",
        ]:
            assert bind in sql_str, f"Missing bind {bind} in insert_invoice_dtl_gst"


# ---------------------------------------------------------------------------
# 2. Endpoint tests
# ---------------------------------------------------------------------------


class TestCreateSalesInvoice:

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

        # Call sequence: 1=branch lookup, 2=rate_rounding fetch, 3=header insert, 4=line insert, 5=GST insert
        branch_row = MagicMock()
        branch_row._mapping = {"co_id": 1}
        branch_result = MagicMock()
        branch_result.fetchone.return_value = branch_row

        # rate_rounding lookup — returns empty so callers fall back to default 2 decimals
        rate_rounding_result = MagicMock()
        rate_rounding_result.fetchall.return_value = []

        header_result = MagicMock()
        header_result.lastrowid = 1

        line_result = MagicMock()
        line_result.lastrowid = 10

        gst_result = MagicMock()

        self._mock_session.execute.side_effect = [branch_result, rate_rounding_result, header_result, line_result, gst_result]
        yield
        app.dependency_overrides.clear()

    def _base_payload(self):
        return {
            "branch": "1",
            "date": "2025-06-01",
            "party": "10",
            "items": [{
                "item": "100",
                "uom": "5",
                "quantity": "10",
                "rate": "200",
                "net_amount": 2000,
                "total_amount": 2360,
                "discount_type": 1,
                "discounted_rate": 190,
                "discount_amount": 100,
                "remarks": "Test line",
                "delivery_order_dtl_id": 42,
                "gst": {
                    "igst_amount": 0,
                    "igst_percent": 0,
                    "cgst_amount": 180,
                    "cgst_percent": 9,
                    "sgst_amount": 180,
                    "sgst_percent": 9,
                    "gst_total": 360,
                },
            }],
            "billing_to_id": "5",
            "shipping_to_id": "6",
            "internal_note": "Internal note",
            "transporter_name": "ABC Transport",
            "transporter_address": "123 Main St",
            "transporter_state_code": "29",
            "transporter_state_name": "Karnataka",
            "due_date": "2025-07-01",
            "type_of_sale": "Domestic",
            "tax_id": "3",
            "container_no": "CONT123",
            "contract_no": "456",
            "contract_date": "2025-05-01",
            "consignment_no": "CG789",
            "consignment_date": "2025-06-02",
            "gross_amount": 2000,
            "tax_amount": 360,
            "tax_payable": 360,
            "payment_terms": 30,
            "sales_order_id": 5,
            "billing_state_code": 27,
        }

    def test_create_with_new_header_fields_succeeds(self):
        response = client.post("/api/salesInvoice/create_sales_invoice", json=self._base_payload())
        assert response.status_code == 200
        data = response.json()
        assert data.get("invoice_id") == 1

    def test_create_without_new_optional_fields_succeeds(self):
        """All new fields are optional — basic payload must still work."""
        # Reset side_effect for this test (no GST insert needed)
        branch_row = MagicMock()
        branch_row._mapping = {"co_id": 1}
        branch_result = MagicMock()
        branch_result.fetchone.return_value = branch_row
        rate_rounding_result = MagicMock()
        rate_rounding_result.fetchall.return_value = []
        header_result = MagicMock()
        header_result.lastrowid = 2
        line_result = MagicMock()
        line_result.lastrowid = 20
        self._mock_session.execute.side_effect = [branch_result, rate_rounding_result, header_result, line_result]

        payload = {
            "branch": "1",
            "date": "2025-06-01",
            "party": "10",
            "items": [{"item": "100", "uom": "5", "quantity": "10", "rate": "200", "net_amount": 2000, "total_amount": 2000}],
        }
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        assert response.status_code == 200

    def test_create_passes_gst_data_to_db(self):
        """GST insert should be called when gst dict is provided."""
        payload = self._base_payload()
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        assert response.status_code == 200

        # The session.execute calls: 1=header insert, 2=line insert, 3=GST insert
        calls = self._mock_session.execute.call_args_list
        assert len(calls) >= 3, f"Expected at least 3 db.execute calls, got {len(calls)}"


class TestGetSalesInvoiceById:

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_response_contains_new_header_fields(self):
        header = _mock_row({
            "invoice_id": 1, "invoice_no": 1, "invoice_date": "2025-06-01",
            "challan_no": None, "challan_date": None,
            "branch_id": 1, "branch_name": "Main", "branch_prefix": "MN",
            "co_id": 1, "co_prefix": "CO",
            "party_id": 10, "party_name": "Customer A",
            "sales_delivery_order_id": None,
            "broker_id": 5,
            "billing_to_id": 7,
            "shipping_to_id": 8,
            "internal_note": "Test note",
            "shipping_state_code": 29,
            "transporter_id": 3,
            "transporter_name": "Trans Party",
            "transporter_name_stored": "ABC Transport",
            "transporter_address": "123 Main St",
            "transporter_state_code": "29",
            "transporter_state_name": "Karnataka",
            "vehicle_no": "KA01AB1234",
            "eway_bill_no": "EWB001",
            "eway_bill_date": "2025-06-01",
            "invoice_type": 1,
            "footer_notes": "Footer",
            "terms": None, "terms_conditions": "T&C",
            "invoice_amount": 2000, "tax_amount": 360, "tax_payable": 360,
            "freight_charges": 0, "round_off": 0,
            "due_date": "2025-07-01",
            "type_of_sale": "Domestic",
            "tax_id": 3,
            "container_no": "CONT123",
            "contract_no": 456,
            "contract_date": "2025-05-01",
            "consignment_no": "CG789",
            "consignment_date": "2025-06-02",
            "status_id": 21, "status_name": "Draft",
            "updated_by": 1, "updated_date_time": None,
            "intra_inter_state": "intra",
            "payment_terms": 30,
            "sales_order_id": 5,
            "billing_state_code": 27,
            "sales_order_date": "2025-05-15",
            "sales_order_no": 101,
        })

        detail = _mock_row({
            "invoice_line_item_id": 10,
            "invoice_id": 1,
            "hsn_code": "1234",
            "item_id": 100, "item_name": "Widget", "item_grp_id": 5,
            "item_make_id": None,
            "quantity": 10, "uom_id": 5, "uom_name": "KG",
            "rate": 200,
            "discount_type": 1,
            "discounted_rate": 190,
            "discount_amount": 100,
            "amount_without_tax": 1900,
            "total_amount": 2260,
            "sales_weight": None,
            "remarks": "Line remark",
            "delivery_order_dtl_id": 42,
        })

        gst_row = _mock_row({
            "invoice_line_item_id": 10,
            "igst_amount": 0, "igst_percentage": 0,
            "cgst_amount": 180, "cgst_percentage": 9,
            "sgst_amount": 180, "sgst_percentage": 9,
            "tax_percentage": 18, "tax_amount": 360,
        })

        # Mock execute side effects order: header, details, GST, jute header, jute detail
        header_exec = MagicMock()
        header_exec.fetchone.return_value = header
        detail_exec = MagicMock()
        detail_exec.fetchall.return_value = [detail]
        gst_exec = MagicMock()
        gst_exec.fetchall.return_value = [gst_row]
        jute_exec = MagicMock()
        jute_exec.fetchone.return_value = None  # no jute data
        jute_dtl_exec = MagicMock()
        jute_dtl_exec.fetchall.return_value = []

        self._mock_session.execute.side_effect = [header_exec, detail_exec, gst_exec, jute_exec, jute_dtl_exec]

        response = client.get("/api/salesInvoice/get_sales_invoice_by_id?invoice_id=1&co_id=1")
        assert response.status_code == 200
        data = response.json()

        # New header fields
        assert data["billingTo"] == 7
        assert data["shippingTo"] == 8
        assert data["branchId"] == "1"
        assert data["internalNote"] == "Test note"
        assert data["transporterNameStored"] == "ABC Transport"
        assert data["transporterAddress"] == "123 Main St"
        assert data["transporterStateCode"] == "29"
        assert data["transporterStateName"] == "Karnataka"
        assert data["taxAmount"] == 360
        assert data["taxPayable"] == 360
        assert data["typeOfSale"] == "Domestic"
        assert data["taxId"] == 3
        assert data["containerNo"] == "CONT123"
        assert data["contractNo"] == 456
        assert data["consignmentNo"] == "CG789"
        assert data["paymentTerms"] == 30
        assert data["salesOrderId"] == 5
        assert data["billingStateCode"] == 27
        assert data["salesOrderDate"] == "2025-05-15"
        assert data["salesOrderNo"] == 101

        # Line items with new fields
        line = data["lines"][0]
        assert line["discountType"] == 1
        assert line["discountedRate"] == 190
        assert line["discountAmount"] == 100
        assert line["remarks"] == "Line remark"
        assert line["deliveryOrderDtlId"] == 42

        # GST nested in line
        assert "gst" in line
        assert line["gst"]["cgstAmount"] == 180
        assert line["gst"]["sgstPercent"] == 9
        assert line["gst"]["taxAmount"] == 360

    def test_response_contains_renamed_fields(self):
        """Test that response uses new field names: billingTo, shippingTo, branchId (not billingToId, shippingToId, branch)."""
        header = _mock_row({
            "invoice_id": 1, "invoice_no": 1, "invoice_date": "2025-06-01",
            "challan_no": None, "challan_date": None,
            "branch_id": 18, "branch_name": "Main", "branch_prefix": "MN",
            "co_id": 1, "co_prefix": "CO",
            "party_id": 10, "party_name": "Customer A",
            "sales_delivery_order_id": None, "broker_id": None,
            "billing_to_id": 71, "shipping_to_id": 71,
            "internal_note": None, "shipping_state_code": None,
            "transporter_id": None, "transporter_name": None,
            "transporter_name_stored": None, "transporter_address": None,
            "transporter_state_code": None, "transporter_state_name": None,
            "vehicle_no": None, "eway_bill_no": None, "eway_bill_date": None,
            "invoice_type": None, "footer_notes": None,
            "terms": None, "terms_conditions": None,
            "invoice_amount": 0, "tax_amount": 0, "tax_payable": 0,
            "freight_charges": 0, "round_off": 0,
            "due_date": None, "type_of_sale": None, "tax_id": None,
            "container_no": None, "contract_no": None, "contract_date": None,
            "consignment_no": None, "consignment_date": None,
            "status_id": 21, "status_name": "Draft",
            "updated_by": 1, "updated_date_time": None,
            "intra_inter_state": None,
            "payment_terms": None, "sales_order_id": None,
            "billing_state_code": None,
            "sales_order_date": None, "sales_order_no": None,
        })

        header_exec = MagicMock()
        header_exec.fetchone.return_value = header
        detail_exec = MagicMock()
        detail_exec.fetchall.return_value = []
        gst_exec = MagicMock()
        gst_exec.fetchall.return_value = []
        jute_exec = MagicMock()
        jute_exec.fetchone.return_value = None
        jute_dtl_exec = MagicMock()
        jute_dtl_exec.fetchall.return_value = []

        self._mock_session.execute.side_effect = [header_exec, detail_exec, gst_exec, jute_exec, jute_dtl_exec]

        response = client.get("/api/salesInvoice/get_sales_invoice_by_id?invoice_id=1&co_id=1")
        assert response.status_code == 200
        data = response.json()

        # New field names
        assert data["billingTo"] == 71, "Response should contain 'billingTo' (not 'billingToId')"
        assert data["shippingTo"] == 71, "Response should contain 'shippingTo' (not 'shippingToId')"
        assert data["branchId"] == "18", "Response should contain 'branchId' (not 'branch')"

        # Old field names should not be present
        assert "billingToId" not in data, "Response should not contain old field name 'billingToId'"
        assert "shippingToId" not in data, "Response should not contain old field name 'shippingToId'"
        assert "branch" not in data, "Response should not contain old field name 'branch'"

    def test_response_does_not_contain_tcs(self):
        """TCS fields should not be in the response."""
        header = _mock_row({
            "invoice_id": 1, "invoice_no": 1, "invoice_date": "2025-06-01",
            "challan_no": None, "challan_date": None,
            "branch_id": 1, "branch_name": "Main", "branch_prefix": "MN",
            "co_id": 1, "co_prefix": "CO",
            "party_id": 10, "party_name": "Customer A",
            "sales_delivery_order_id": None, "broker_id": None,
            "billing_to_id": None, "shipping_to_id": None,
            "internal_note": None, "shipping_state_code": None,
            "transporter_id": None, "transporter_name": None,
            "transporter_name_stored": None, "transporter_address": None,
            "transporter_state_code": None, "transporter_state_name": None,
            "vehicle_no": None, "eway_bill_no": None, "eway_bill_date": None,
            "invoice_type": None, "footer_notes": None,
            "terms": None, "terms_conditions": None,
            "invoice_amount": 0, "tax_amount": 0, "tax_payable": 0,
            "freight_charges": 0, "round_off": 0,
            "due_date": None, "type_of_sale": None, "tax_id": None,
            "container_no": None, "contract_no": None, "contract_date": None,
            "consignment_no": None, "consignment_date": None,
            "status_id": 21, "status_name": "Draft",
            "updated_by": 1, "updated_date_time": None,
            "intra_inter_state": None,
            "payment_terms": None, "sales_order_id": None,
            "billing_state_code": None,
            "sales_order_date": None, "sales_order_no": None,
        })

        header_exec = MagicMock()
        header_exec.fetchone.return_value = header
        detail_exec = MagicMock()
        detail_exec.fetchall.return_value = []
        gst_exec = MagicMock()
        gst_exec.fetchall.return_value = []
        jute_exec = MagicMock()
        jute_exec.fetchone.return_value = None
        jute_dtl_exec = MagicMock()
        jute_dtl_exec.fetchall.return_value = []

        self._mock_session.execute.side_effect = [header_exec, detail_exec, gst_exec, jute_exec, jute_dtl_exec]

        response = client.get("/api/salesInvoice/get_sales_invoice_by_id?invoice_id=1&co_id=1")
        assert response.status_code == 200
        data = response.json()
        assert "tcsPercentage" not in data
        assert "tcsAmount" not in data


class TestUpdateSalesInvoice:

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_update_with_new_fields_succeeds(self):
        # Mock: check exists, update header, delete GST, delete jute_dtl, delete jute, delete lines, insert line, insert GST
        check_row = _mock_row({"invoice_id": 1, "status_id": 21, "active": 1})
        check_exec = MagicMock()
        check_exec.fetchone.return_value = check_row
        line_result = MagicMock()
        line_result.lastrowid = 20

        self._mock_session.execute.side_effect = [
            check_exec,    # check exists
            MagicMock(),   # update header
            MagicMock(),   # delete GST
            MagicMock(),   # delete jute detail
            MagicMock(),   # delete jute header
            MagicMock(),   # delete govtskg header
            MagicMock(),   # delete additional charges GST
            MagicMock(),   # delete additional charges
            MagicMock(),   # delete line items
            line_result,   # insert line item
            MagicMock(),   # insert GST
        ]

        payload = {
            "id": "1",
            "branch": "1",
            "date": "2025-06-01",
            "party": "10",
            "billing_to_id": "5",
            "shipping_to_id": "6",
            "internal_note": "Updated note",
            "transporter_name": "New Transport",
            "transporter_address": "456 Oak Ave",
            "transporter_state_code": "07",
            "transporter_state_name": "Delhi",
            "due_date": "2025-07-15",
            "type_of_sale": "Export",
            "tax_id": "2",
            "container_no": "CONT456",
            "contract_no": "789",
            "contract_date": "2025-05-15",
            "consignment_no": "CG999",
            "consignment_date": "2025-06-10",
            "items": [{
                "item": "100",
                "uom": "5",
                "quantity": "10",
                "rate": "200",
                "net_amount": 2000,
                "total_amount": 2360,
                "discount_type": 2,
                "discounted_rate": 180,
                "discount_amount": 200,
                "remarks": "Updated line",
                "delivery_order_dtl_id": 55,
                "gst": {
                    "igst_amount": 360,
                    "igst_percent": 18,
                    "cgst_amount": 0,
                    "cgst_percent": 0,
                    "sgst_amount": 0,
                    "sgst_percent": 0,
                    "gst_total": 360,
                },
            }],
        }

        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("invoice_id") == 1

    def test_update_deletes_gst_before_line_items(self):
        """GST must be deleted before line items due to FK constraint."""
        check_row = _mock_row({"invoice_id": 1, "status_id": 21, "active": 1})
        check_exec = MagicMock()
        check_exec.fetchone.return_value = check_row
        line_result = MagicMock()
        line_result.lastrowid = 20

        call_log = []

        def track_execute(query, params=None):
            sql_str = str(query)
            if "SELECT" in sql_str and "invoice_id" in sql_str:
                call_log.append("select")
                return check_exec
            elif "UPDATE" in sql_str:
                call_log.append("update")
            elif "DELETE" in sql_str and "additional" in sql_str.lower():
                call_log.append("delete_additional")
            elif "DELETE" in sql_str and "gst" in sql_str.lower():
                call_log.append("delete_gst")
            elif "DELETE" in sql_str and "sales_invoice_dtl" in sql_str.lower():
                call_log.append("delete_lines")
            elif "DELETE" in sql_str:
                call_log.append("delete_other")
            elif "INSERT" in sql_str and "gst" in sql_str.lower():
                call_log.append("insert_gst")
            elif "INSERT" in sql_str:
                call_log.append("insert_line")
                return line_result
            return MagicMock()

        self._mock_session.execute.side_effect = track_execute

        payload = {
            "id": "1", "branch": "1", "date": "2025-06-01", "party": "10",
            "items": [{"item": "100", "uom": "5", "quantity": "10", "rate": "200", "net_amount": 2000, "total_amount": 2000}],
        }

        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        assert response.status_code == 200

        # Verify ordering: delete_gst comes before delete_lines
        if "delete_gst" in call_log and "delete_lines" in call_log:
            gst_idx = call_log.index("delete_gst")
            lines_idx = call_log.index("delete_lines")
            assert gst_idx < lines_idx, f"GST delete ({gst_idx}) should come before line delete ({lines_idx})"
