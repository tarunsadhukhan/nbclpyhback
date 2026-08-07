"""
Tests for procurement report endpoints.
Tests GET /procurementReports/indent-itemwise endpoint and download endpoints.
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from datetime import date

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestIndentItemwiseReport:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_outstanding_filter_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&outstanding_filter=invalid")
        assert response.status_code == 400
        assert "outstanding_filter" in response.json()["detail"]

    def test_invalid_indent_type_returns_400(self):
        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&indent_type=Invalid")
        assert response.status_code == 400
        assert "indent_type" in response.json()["detail"]

    def test_success_returns_data_and_total(self):
        mock_row = _mock_row({
            "indent_dtl_id": 10,
            "indent_id": 5,
            "indent_no": 1,
            "indent_date": date(2026, 3, 1),
            "branch_name": "Main Branch",
            "branch_prefix": "MAIN",
            "co_prefix": "ABC",
            "item_name": "Bolt M8",
            "item_grp_name": "Fasteners",
            "uom_name": "NOS",
            "indent_qty": 100.0,
            "outstanding_qty": 40.0,
            "po_consumed_qty": 60.0,
            "indent_type_id": "Regular",
            "expense_type_name": "General",
            "status_name": "Approved",
        })
        self.mock_session.execute.return_value.fetchall.return_value = [mock_row]
        self.mock_session.execute.return_value.scalar.return_value = 1

        response = client.get("/api/procurementReports/indent-itemwise?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body
        assert len(body["data"]) == 1
        assert body["data"][0]["item_name"] == "Bolt M8"
        assert body["data"][0]["indent_qty"] == 100.0
        assert body["data"][0]["outstanding_qty"] == 40.0

    def test_empty_result(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get("/api/procurementReports/indent-itemwise?co_id=1")
        assert response.status_code == 200
        body = response.json()
        assert body["data"] == []
        assert body["total"] == 0

    def test_with_all_filters(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get(
            "/api/procurementReports/indent-itemwise"
            "?co_id=1&branch_id=2&date_from=2026-01-01&date_to=2026-03-06"
            "&indent_type=Regular&outstanding_filter=outstanding&search=bolt"
            "&page=1&limit=20"
        )
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert "total" in body


# =============================================================================
# Sample mapping factories for download tests
# =============================================================================

def _sample_indent_row(indent_dtl_id=1):
    return _mock_row({
        "indent_dtl_id": indent_dtl_id,
        "indent_id": 5,
        "indent_no": 7,
        "indent_date": date(2026, 3, 1),
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_prefix": "ABC",
        "item_name": "Bolt M8",
        "item_grp_name": "Fasteners",
        "uom_name": "NOS",
        "indent_qty": 100.0,
        "outstanding_qty": 40.0,
        "po_consumed_qty": 60.0,
        "indent_type_id": "Regular",
        "expense_type_name": "General",
        "status_name": "Approved",
    })


def _sample_po_row(po_dtl_id=1):
    return _mock_row({
        "po_dtl_id": po_dtl_id,
        "po_id": 11,
        "po_no": 21,
        "po_date": date(2026, 3, 5),
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_prefix": "ABC",
        "supplier_name": "Acme Co",
        "item_name": "Bolt M8",
        "item_grp_name": "Fasteners",
        "uom_name": "NOS",
        "po_qty": 50.0,
        "rate": 12.5,
        "inward_consumed_qty": 20.0,
        "outstanding_qty": 30.0,
        "po_type": "Regular",
        "expense_type_name": "General",
        "status_name": "Approved",
    })


def _sample_sr_row(inward_dtl_id=1):
    return _mock_row({
        "inward_dtl_id": inward_dtl_id,
        "inward_id": 14,
        "inward_sequence_no": 42,
        "inward_date": date(2026, 3, 6),
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_prefix": "ABC",
        "supplier_name": "Acme Co",
        "item_name": "Bolt M8",
        "item_grp_name": "Fasteners",
        "uom_name": "NOS",
        "approved_qty": 30.0,
        "rejected_qty": 0.0,
        "rate": 12.5,
        "amount": 375.0,
        "status_name": "Approved",
    })


def _sample_bill_pass_row():
    return _mock_row({
        "inward_id": 14,
        "inward_sequence_no": 42,
        "inward_date": date(2026, 3, 6),
        "bill_pass_no": "BP-001",
        "bill_pass_date": date(2026, 3, 7),
        "invoice_date": date(2026, 3, 6),
        "invoice_amount": 1000.0,
        "invoice_no": "INV-1",
        "supplier_id": 9,
        "supplier_name": "Acme Co",
        "branch_id": 1,
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_id": 1,
        "co_prefix": "ABC",
        "sr_status": 3,
        "billpass_status": 0,
        "sr_status_name": "Approved",
        "sr_total": 1000.0,
        "sr_taxable": 900.0,
        "sr_tax": 100.0,
        "dr_total": 0.0,
        "dr_count": 0,
        "cr_total": 0.0,
        "cr_count": 0,
        "net_payable": 1000.0,
    })


def _sample_po_table_row():
    return _mock_row({
        "po_id": 11,
        "po_no": 21,
        "po_date": date(2026, 3, 5),
        "supp_name": "Acme Co",
        "po_value": 1250.0,
        "branch_id": 1,
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_id": 1,
        "co_prefix": "ABC",
        "project_name": "Project X",
        "status_name": "Approved",
    })


def _sample_indent_table_row():
    return _mock_row({
        "indent_id": 5,
        "indent_no": 7,
        "indent_date": date(2026, 3, 1),
        "branch_name": "Main Branch",
        "branch_prefix": "MAIN",
        "co_id": 1,
        "co_prefix": "ABC",
        "expense_type_name": "General",
        "status_name": "Approved",
    })


# =============================================================================
# status_id filter
# =============================================================================

class TestIndentItemwiseStatusFilter:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_status_id_3_passed_to_query(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get(
            "/api/procurementReports/indent-itemwise?co_id=1&status_id=3"
        )
        assert response.status_code == 200

        # Inspect the bound params passed to the first execute() call (list query).
        first_call = self.mock_session.execute.call_args_list[0]
        bound = first_call.args[1] if len(first_call.args) > 1 else first_call.kwargs.get("params")
        assert bound is not None, "Expected bound params on execute() call"
        assert bound.get("status_id") == 3

    def test_status_id_omitted_passes_none(self):
        self.mock_session.execute.return_value.fetchall.return_value = []
        self.mock_session.execute.return_value.scalar.return_value = 0

        response = client.get("/api/procurementReports/indent-itemwise?co_id=1")
        assert response.status_code == 200

        first_call = self.mock_session.execute.call_args_list[0]
        bound = first_call.args[1] if len(first_call.args) > 1 else first_call.kwargs.get("params")
        assert bound is not None
        assert bound.get("status_id") is None


# =============================================================================
# Download endpoint tests — procurementReports/*
# =============================================================================

class _DownloadTestBase:
    """Common setup/teardown for download endpoint test classes."""

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)


class TestIndentItemwiseDownload(_DownloadTestBase):
    BASE = "/api/procurementReports/indent-itemwise/download"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_indent_row(1),
            _sample_indent_row(2),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower()

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400
        assert "format" in r.json()["detail"].lower()

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400
        assert "co_id" in r.json()["detail"].lower()


class TestPoItemwiseDownload(_DownloadTestBase):
    BASE = "/api/procurementReports/po-itemwise/download"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_po_row(1),
            _sample_po_row(2),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400


class TestSrItemwiseDownload(_DownloadTestBase):
    BASE = "/api/procurementReports/sr-itemwise/download"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_sr_row(1),
            _sample_sr_row(2),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400


# =============================================================================
# Download endpoint tests — billPass / procurementPO / procurementIndent
# =============================================================================

class TestBillPassDownload(_DownloadTestBase):
    BASE = "/api/billPass/download_bill_pass_list"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_bill_pass_row(),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400


class TestPoTableDownload(_DownloadTestBase):
    BASE = "/api/procurementPO/download_po_table"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_po_table_row(),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400


class TestIndentTableDownload(_DownloadTestBase):
    BASE = "/api/procurementIndent/download_indent_table"

    def _setup_rows(self):
        self.mock_session.execute.return_value.fetchall.return_value = [
            _sample_indent_table_row(),
        ]

    def test_xlsx_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=xlsx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(XLSX_MEDIA_TYPE)

    def test_pdf_success(self):
        self._setup_rows()
        r = client.get(f"{self.BASE}?co_id=1&format=pdf")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(PDF_MEDIA_TYPE)

    def test_missing_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1")
        assert r.status_code == 400

    def test_invalid_format_returns_400(self):
        r = client.get(f"{self.BASE}?co_id=1&format=csv")
        assert r.status_code == 400

    def test_missing_co_id_returns_400(self):
        r = client.get(f"{self.BASE}?format=xlsx")
        assert r.status_code == 400
