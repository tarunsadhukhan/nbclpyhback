"""
Tests for the new Jute index-page excel download endpoints + date_from/date_to
filtering on their list endpoints.

Covers:
- /api/jutePO/download_po_table
- /api/juteBillPass/download_bill_pass_list
- /api/juteGateEntry/download_gate_entry_table
- /api/juteMaterialInspection/download_inspection_table
- /api/juteIssue/download_issue_table
- /api/batchDailyAssign/download_assign_table
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh


client = TestClient(app)

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    # for endpoints that read .total via attribute access
    for k, v in mapping.items():
        setattr(row, k, v)
    # subscript access for endpoints that use count_result[0]
    row.__getitem__.side_effect = lambda i: list(mapping.values())[i]
    return row


@pytest.fixture
def mock_session():
    session = MagicMock()
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
    app.dependency_overrides[get_tenant_db] = lambda: session
    yield session
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Required-param validation: each download endpoint requires co_id (or
# branch_id for batchDailyAssign).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,required_param", [
    ("/api/jutePO/download_po_table", "co_id"),
    ("/api/juteBillPass/download_bill_pass_list", "co_id"),
    ("/api/juteGateEntry/download_gate_entry_table", "co_id"),
    ("/api/juteMaterialInspection/download_inspection_table", "co_id"),
    ("/api/juteIssue/download_issue_table", "co_id"),
    ("/api/batchDailyAssign/download_assign_table", "branch_id"),
])
def test_download_requires_id(mock_session, url, required_param):
    response = client.get(url)
    assert response.status_code == 400
    assert required_param in response.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Invalid date format returns 400 on every download endpoint.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,id_qs", [
    ("/api/jutePO/download_po_table", "co_id=1"),
    ("/api/juteBillPass/download_bill_pass_list", "co_id=1"),
    ("/api/juteGateEntry/download_gate_entry_table", "co_id=1"),
    ("/api/juteMaterialInspection/download_inspection_table", "co_id=1"),
    ("/api/juteIssue/download_issue_table", "co_id=1"),
    ("/api/batchDailyAssign/download_assign_table", "branch_id=1"),
])
def test_download_invalid_date_format(mock_session, url, id_qs):
    response = client.get(f"{url}?{id_qs}&from_date=2025-13-99")
    assert response.status_code == 400
    assert "from_date" in response.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Happy path: successful empty-result download returns 200 + xlsx content-type.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,id_qs", [
    ("/api/jutePO/download_po_table", "co_id=1"),
    ("/api/juteBillPass/download_bill_pass_list", "co_id=1"),
    ("/api/juteGateEntry/download_gate_entry_table", "co_id=1"),
    ("/api/juteMaterialInspection/download_inspection_table", "co_id=1"),
    ("/api/juteIssue/download_issue_table", "co_id=1"),
    ("/api/batchDailyAssign/download_assign_table", "branch_id=1"),
])
def test_download_empty_set_returns_xlsx(mock_session, url, id_qs):
    count_row = _mock_row({"total": 0})
    mock_session.execute.return_value.fetchone.return_value = count_row
    mock_session.execute.return_value.fetchall.return_value = []

    response = client.get(f"{url}?{id_qs}")
    assert response.status_code == 200
    assert response.headers.get("content-type") == XLSX_CT
    assert response.headers.get("content-disposition", "").startswith("attachment;")
    # openpyxl-built xlsx is non-empty even with header-only content
    assert len(response.content) > 0


# ---------------------------------------------------------------------------
# Row-cap enforcement: a count exceeding 50_000 should 400 before workbook build.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,id_qs", [
    ("/api/jutePO/download_po_table", "co_id=1"),
    ("/api/juteBillPass/download_bill_pass_list", "co_id=1"),
    ("/api/juteGateEntry/download_gate_entry_table", "co_id=1"),
    ("/api/juteMaterialInspection/download_inspection_table", "co_id=1"),
    ("/api/juteIssue/download_issue_table", "co_id=1"),
    ("/api/batchDailyAssign/download_assign_table", "branch_id=1"),
])
def test_download_row_cap_exceeded(mock_session, url, id_qs):
    count_row = _mock_row({"total": 60_000})
    mock_session.execute.return_value.fetchone.return_value = count_row

    response = client.get(f"{url}?{id_qs}")
    assert response.status_code == 400
    assert "max" in response.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Date-filter param plumbing: list endpoints accept from_date/to_date and
# pass them to query bind params (regression check that nothing 500s).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,id_qs", [
    ("/api/jutePO/get_jute_po_table", "co_id=1"),
    ("/api/juteBillPass/get_bill_pass_list", "co_id=1"),
    ("/api/juteGateEntry/get_jute_gate_entry_table", "co_id=1"),
    ("/api/juteMaterialInspection/get_inspection_table", "co_id=1"),
    ("/api/juteIssue/get_issue_table", "co_id=1"),
    ("/api/batchDailyAssign/get_assign_table", "branch_id=1"),
])
def test_list_endpoint_accepts_date_range(mock_session, url, id_qs):
    count_row = _mock_row({"total": 0})
    mock_session.execute.return_value.fetchone.return_value = count_row
    mock_session.execute.return_value.fetchall.return_value = []

    response = client.get(f"{url}?{id_qs}&from_date=2025-01-01&to_date=2025-12-31")
    assert response.status_code == 200


@pytest.mark.parametrize("url,id_qs", [
    ("/api/jutePO/get_jute_po_table", "co_id=1"),
    ("/api/juteBillPass/get_bill_pass_list", "co_id=1"),
    ("/api/juteGateEntry/get_jute_gate_entry_table", "co_id=1"),
    ("/api/juteMaterialInspection/get_inspection_table", "co_id=1"),
    ("/api/juteIssue/get_issue_table", "co_id=1"),
    ("/api/batchDailyAssign/get_assign_table", "branch_id=1"),
])
def test_list_endpoint_invalid_date_400(mock_session, url, id_qs):
    response = client.get(f"{url}?{id_qs}&from_date=not-a-date")
    assert response.status_code == 400
