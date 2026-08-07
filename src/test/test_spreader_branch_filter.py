"""
Tests for branch filtering on Spreader (jute production) endpoints.
Covers src/juteProduction/spreader_entry.py, spreader_issue.py,
spreader_stock.py, spreader_masters.py.
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _exec_params(mock_session, call_index: int) -> dict:
    """Bound params of the Nth db.execute call."""
    return mock_session.execute.call_args_list[call_index][0][1]


class TestSpreaderBranchFilterBase:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


class TestEntrySetupBranchFilter(TestSpreaderBranchFilterBase):
    def _stub_setup_results(self):
        # entry_create_setup executes: machines, bins, items, maturity
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [],  # machines
            [],  # bins
            [],  # items
            [],  # maturity
        ]

    def test_setup_passes_branch_id(self):
        self._stub_setup_results()
        resp = client.get("/api/spreaderProd/entry_create_setup?co_id=1&branch_id=2")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2  # machines
        assert _exec_params(self._mock_session, 1)["branch_id"] == 2  # bins

    def test_setup_without_branch_id_binds_none(self):
        self._stub_setup_results()
        resp = client.get("/api/spreaderProd/entry_create_setup?co_id=1")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] is None
        assert _exec_params(self._mock_session, 1)["branch_id"] is None

    def test_setup_invalid_branch_id(self):
        resp = client.get("/api/spreaderProd/entry_create_setup?co_id=1&branch_id=abc")
        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()


class TestEntriesByDateBranchFilter(TestSpreaderBranchFilterBase):
    def test_entries_by_date_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get(
            "/api/spreaderProd/entries_by_date?co_id=1&entry_date=2026-06-11&branch_id=3"
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 3

    def test_entries_by_date_without_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderProd/entries_by_date?co_id=1&entry_date=2026-06-11")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] is None


class TestEntryCreateBranchDerivation(TestSpreaderBranchFilterBase):
    @patch("src.juteProduction.spreader_entry.assign_or_reuse_entry_id_grp")
    def test_entry_create_derives_branch_from_machine(self, mock_grp):
        mock_grp.return_value = (101, False)
        derive_row = MagicMock()
        derive_row.branch_id = 5
        derive_result = MagicMock()
        derive_result.fetchone.return_value = derive_row
        insert_result = MagicMock()
        insert_result.lastrowid = 9
        self._mock_session.execute.side_effect = [derive_result, insert_result]

        resp = client.post(
            "/api/spreaderProd/entry_create",
            json={
                "co_id": 1,
                "entry_date": "2026-06-11",
                "entry_time": 8,
                "spell": "A1",
                "machine_id": 4,
                "item_id": 10,
                "bin_id": 2,
                "no_of_rolls": 3,
                "wt_per_roll": 50.0,
            },
        )
        assert resp.status_code == 200
        insert_params = _exec_params(self._mock_session, 1)
        assert insert_params["branch_id"] == 5

    @patch("src.juteProduction.spreader_entry.assign_or_reuse_entry_id_grp")
    def test_entry_create_uses_body_branch_when_given(self, mock_grp):
        mock_grp.return_value = (101, False)
        insert_result = MagicMock()
        insert_result.lastrowid = 9
        self._mock_session.execute.side_effect = [insert_result]

        resp = client.post(
            "/api/spreaderProd/entry_create",
            json={
                "co_id": 1,
                "branch_id": 7,
                "entry_date": "2026-06-11",
                "entry_time": 8,
                "spell": "A1",
                "machine_id": 4,
                "item_id": 10,
                "bin_id": 2,
                "no_of_rolls": 3,
                "wt_per_roll": 50.0,
            },
        )
        assert resp.status_code == 200
        insert_params = _exec_params(self._mock_session, 0)
        assert insert_params["branch_id"] == 7


class TestIssueEndpointsBranchFilter(TestSpreaderBranchFilterBase):
    def test_issue_setup_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderProd/issue_create_setup?co_id=1&branch_id=2")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2

    def test_issue_setup_without_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderProd/issue_create_setup?co_id=1")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] is None

    def test_issues_by_date_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get(
            "/api/spreaderProd/issues_by_date?co_id=1&issue_date=2026-06-11&branch_id=4"
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 4

    def test_issue_create_binds_group_derived_branch(self):
        # call order: group details fetchone, produced scalar, issued scalar, INSERT
        details_result = MagicMock()
        details_result.fetchone.return_value = _mock_row(
            {
                "item_id": 10,
                "bin_id": 2,
                "bin_code": "B1",
                "item_name": "Jute",
                "first_entry_dt": datetime(2026, 6, 10, 6, 0),
                "branch_id": 7,
            }
        )
        produced_result = MagicMock()
        produced_result.scalar.return_value = 10
        issued_result = MagicMock()
        issued_result.scalar.return_value = 0
        insert_result = MagicMock()
        insert_result.lastrowid = 55
        self._mock_session.execute.side_effect = [
            details_result,
            produced_result,
            issued_result,
            insert_result,
        ]

        resp = client.post(
            "/api/spreaderProd/issue_create",
            json={
                "co_id": 1,
                "branch_id": 99,  # stale FE value — must be overridden by derived 7
                "issue_date": "2026-06-11",
                "issue_time": 9,
                "spell": "A1",
                "entry_id_grp": 101,
                "wt_per_roll": 50.0,
                "no_of_rolls": 2,
            },
        )
        assert resp.status_code == 200
        insert_params = _exec_params(self._mock_session, 3)
        assert insert_params["branch_id"] == 7


class TestStockBranchFilter(TestSpreaderBranchFilterBase):
    def test_roll_stock_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.side_effect = [[], []]
        resp = client.get("/api/spreaderProd/roll_stock?co_id=1&branch_id=2")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2

    def test_quality_summary_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderProd/roll_stock_quality_summary?co_id=1&branch_id=2")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2

    def test_roll_stock_invalid_branch_id(self):
        resp = client.get("/api/spreaderProd/roll_stock?co_id=1&branch_id=xyz")
        assert resp.status_code == 400


class TestMachineWtSetupBranchFilter(TestSpreaderBranchFilterBase):
    def test_wt_setup_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get(
            "/api/spreaderMasters/spreader_machine_wt_create_setup?co_id=1&branch_id=2"
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2

    def test_wt_setup_without_branch_id_binds_none(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get(
            "/api/spreaderMasters/spreader_machine_wt_create_setup?co_id=1"
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] is None

    def test_wt_setup_invalid_branch_id(self):
        resp = client.get(
            "/api/spreaderMasters/spreader_machine_wt_create_setup?co_id=1&branch_id=xyz"
        )
        assert resp.status_code == 400


class TestMachineWtListBranchFilter(TestSpreaderBranchFilterBase):
    def test_wt_list_passes_branch_id(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderMasters/spreader_machine_wt_list?co_id=1&branch_id=2")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] == 2

    def test_wt_list_without_branch_binds_none(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spreaderMasters/spreader_machine_wt_list?co_id=1")
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 0)["branch_id"] is None


class TestMachineWtCreateBranchScoped(TestSpreaderBranchFilterBase):
    def _owner_result(self, branch_id, co_id):
        owner = MagicMock()
        owner.branch_id = branch_id
        owner.co_id = co_id
        res = MagicMock()
        res.fetchone.return_value = owner
        return res

    def test_wt_create_requires_branch_id(self):
        resp = client.post(
            "/api/spreaderMasters/spreader_machine_wt_create",
            json={"co_id": 1, "machine_id": 5, "wt_per_roll": 100.0},
        )
        assert resp.status_code == 422

    def test_wt_create_unknown_machine_404(self):
        missing = MagicMock()
        missing.fetchone.return_value = None
        self._mock_session.execute.side_effect = [missing]
        resp = client.post(
            "/api/spreaderMasters/spreader_machine_wt_create",
            json={"co_id": 1, "branch_id": 2, "machine_id": 999, "wt_per_roll": 100.0},
        )
        assert resp.status_code == 404

    def test_wt_create_rejects_machine_from_other_branch(self):
        # machine owned by branch 29 (co 2); caller tries to save under branch 87 (co 106)
        self._mock_session.execute.side_effect = [self._owner_result(29, 2)]
        resp = client.post(
            "/api/spreaderMasters/spreader_machine_wt_create",
            json={"co_id": 106, "branch_id": 87, "machine_id": 665, "wt_per_roll": 100.0},
        )
        assert resp.status_code == 400
        assert "branch" in resp.json()["detail"].lower()

    def test_wt_create_saves_branch_and_owner_co(self):
        owner = self._owner_result(87, 106)
        dup = MagicMock()
        dup.fetchone.return_value = None
        ins = MagicMock()
        ins.lastrowid = 20
        self._mock_session.execute.side_effect = [owner, dup, ins]
        resp = client.post(
            "/api/spreaderMasters/spreader_machine_wt_create",
            json={"co_id": 999, "branch_id": 87, "machine_id": 2930, "wt_per_roll": 100.0},
        )
        assert resp.status_code == 200
        insert_params = _exec_params(self._mock_session, 2)
        assert insert_params["branch_id"] == 87
        assert insert_params["co_id"] == 106  # derived from the machine's owning branch, not the body

    def test_wt_create_duplicate_machine_rejected(self):
        owner = self._owner_result(87, 106)
        dup = MagicMock()
        dup.fetchone.return_value = _mock_row({"spreader_machine_attr_id": 8})
        self._mock_session.execute.side_effect = [owner, dup]
        resp = client.post(
            "/api/spreaderMasters/spreader_machine_wt_create",
            json={"co_id": 106, "branch_id": 87, "machine_id": 2930, "wt_per_roll": 100.0},
        )
        assert resp.status_code == 400
        assert "already" in resp.json()["detail"].lower()


class TestBinCreateRequiresBranch(TestSpreaderBranchFilterBase):
    def test_bin_create_without_branch_rejected(self):
        resp = client.post(
            "/api/spreaderMasters/bin_create",
            json={"co_id": 1, "bin_code": "BIN-01"},
        )
        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()

    def test_bin_create_with_branch_ok(self):
        dup_result = MagicMock()
        dup_result.fetchone.return_value = None
        insert_result = MagicMock()
        insert_result.lastrowid = 3
        self._mock_session.execute.side_effect = [dup_result, insert_result]
        resp = client.post(
            "/api/spreaderMasters/bin_create",
            json={"co_id": 1, "branch_id": 2, "bin_code": "BIN-01"},
        )
        assert resp.status_code == 200
        assert _exec_params(self._mock_session, 1)["branch_id"] == 2
