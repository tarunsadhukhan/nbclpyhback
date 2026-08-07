"""Regression tests for consumption-issue numbering (src/inventory/issue.py).

Bug: create_issue() numbered issue_pass_no from a GLOBAL MAX per branch, with no
financial-year scope, so a stale prior-FY maximum (branch 29 reached 8900 in
FY2023-24) poisoned the current year and the number jumped to 8901 instead of 35.

Fix: the next number is now MAX(issue_pass_no) + 1 scoped to the Indian financial
year (1 Apr .. 31 Mar) of the new issue's issue_date, via get_fy_boundaries().

Portal persona: DB + auth mocked. get_tenant_db / get_current_user_with_refresh are
overridden via app.dependency_overrides keyed by the symbols imported into the
router module. db.execute is given a side_effect that returns the mocked MAX row
and captures the bind params passed to the FY-scoped MAX query.
"""

from datetime import date
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.inventory.issue import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


class _IssueCreateHarness:
    """Drives create_issue with a mocked session and a configurable MAX value."""

    def __init__(self, max_no: int):
        self.max_no = max_no
        self.captured_max_params = None
        self.session = MagicMock()
        self.session.execute.side_effect = self._execute

    def _execute(self, query, params=None):
        sql = str(query)
        result = MagicMock()
        if "MAX(ih.issue_pass_no)" in sql:
            self.captured_max_params = params
            row = MagicMock()
            row.max_issue_no = self.max_no
            result.fetchone.return_value = row
        elif "LAST_INSERT_ID" in sql:
            row = MagicMock()
            row.issue_id = 999
            result.fetchone.return_value = row
        else:
            result.fetchone.return_value = None
        return result


def _post(harness, *, issue_date="2026-05-26", branch_id=29):
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
    app.dependency_overrides[get_tenant_db] = lambda: harness.session
    try:
        return client.post(
            "/api/inventoryIssue/create_issue",
            json={
                "branch_id": branch_id,
                "dept_id": 1,
                "issue_date": issue_date,
                "line_items": [{"item_id": 1, "uom_id": 2, "qty": 5}],
            },
        )
    finally:
        app.dependency_overrides.clear()


class TestIssueNumberingFinancialYear:
    def test_next_number_is_fy_max_plus_one(self):
        """The regression: same-FY max is 34 -> next is 35 (prior-FY 8900 ignored)."""
        h = _IssueCreateHarness(max_no=34)
        resp = _post(h, issue_date="2026-05-26", branch_id=29)
        assert resp.status_code == 200, resp.text
        assert resp.json()["issue_no"] == 35

    def test_fy_window_bound_to_issue_date(self):
        """MAX query is scoped to the Indian FY of issue_date (2026-05-26 -> FY26-27)."""
        h = _IssueCreateHarness(max_no=34)
        _post(h, issue_date="2026-05-26")
        assert h.captured_max_params["fy_start"] == date(2026, 4, 1)
        assert h.captured_max_params["fy_end"] == date(2027, 3, 31)
        assert h.captured_max_params["branch_id"] == 29

    def test_fy_boundary_mar31_is_prior_fy(self):
        """31 Mar 2026 belongs to FY2025-26."""
        h = _IssueCreateHarness(max_no=0)
        _post(h, issue_date="2026-03-31")
        assert h.captured_max_params["fy_start"] == date(2025, 4, 1)
        assert h.captured_max_params["fy_end"] == date(2026, 3, 31)

    def test_fy_boundary_apr1_is_new_fy(self):
        """1 Apr 2026 belongs to FY2026-27 (proves Mar 31 / Apr 1 split FYs)."""
        h = _IssueCreateHarness(max_no=0)
        _post(h, issue_date="2026-04-01")
        assert h.captured_max_params["fy_start"] == date(2026, 4, 1)
        assert h.captured_max_params["fy_end"] == date(2027, 3, 31)

    def test_fresh_fy_starts_at_one(self):
        """No rows in this branch+FY (COALESCE -> 0) -> first issue is 1."""
        h = _IssueCreateHarness(max_no=0)
        resp = _post(h, issue_date="2026-05-26")
        assert resp.status_code == 200, resp.text
        assert resp.json()["issue_no"] == 1

    def test_missing_issue_date_returns_400(self):
        h = _IssueCreateHarness(max_no=34)
        resp = _post(h, issue_date="")
        assert resp.status_code == 400
        assert "issue_date" in resp.json()["detail"].lower()
