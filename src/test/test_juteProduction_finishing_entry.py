"""Tests for the Finishing Production Entry endpoints.

Tests for src/juteProduction/finishing_entry.py (prefix /api/finishingProd).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through app.dependency_overrides
keyed by those EXACT symbols (mirrors test_beaming_entry / test_beaming_target_map).

Figure-only model: entry_save stores ONLY the production figure (prod_qty + prod_uom).
No spec-sheet std/target/eff resolution, no F1-F3 computation, no EAV params, no
eb/input/wastage. We route db.execute by inspecting the bound SQL so the quality lookup,
existing-row check, and insert each return what that handler step reads
(.quality_type, .finishing_daily_id, .lastrowid).

Covered:
  * entry_setup happy path (machines/qualities/spells, no param_tokens/eb_list) +
    missing co_id 400 + missing process 400 + invalid process 400
  * entry_save happy path stores prod_qty + returns finishing_daily_id
  * entry_save quality/process mismatch 400, balepress accepts BOTH quality types,
    quality not found 404, invalid process 400
  * entry_by_date happy path + empty + missing tran_date 400 + missing co_id 400
  * entry_delete happy path (soft delete) + 404 + missing co_id 400
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.finishing_entry import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _fetchall_exec(rows):
    ex = MagicMock()
    ex.fetchall.return_value = rows
    return ex


def _fetchone_exec(row):
    ex = MagicMock()
    ex.fetchone.return_value = row
    return ex


# =============================================================================
# entry_setup
# =============================================================================


class TestEntrySetup:
    """GET /api/finishingProd/entry_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_no_tran_date(self):
        """Without tran_date: machines, qualities, spells resolved; entries empty.

        Execute order: machines, qualities, spells (3 fetchall queries)."""
        machine_rows = [_mock_row({"machine_id": 9, "machine_name": "Cal-1"})]
        quality_rows = [
            _mock_row({"finishing_quality_id": 5, "fin_quality_code": "HC-10"})
        ]
        spell_rows = [
            _mock_row(
                {
                    "spell_id": 1,
                    "spell_code": "A1",
                    "spell_name": "A1",
                    "working_hours": 8.0,
                }
            ),
        ]
        self._mock_session.execute.side_effect = [
            _fetchall_exec(machine_rows),
            _fetchall_exec(quality_rows),
            _fetchall_exec(spell_rows),
        ]

        response = client.get(
            "/api/finishingProd/entry_setup?co_id=1&process=calendering"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["process"] == "calendering"
        assert data["machines"][0]["machine_id"] == 9
        assert data["qualities"][0]["finishing_quality_id"] == 5
        assert data["spells"][0]["spell_code"] == "A1"
        # param_tokens / eb_list were dropped from the simplified payload.
        assert "param_tokens" not in data
        assert "eb_list" not in data
        assert data["entries"] == []

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/finishingProd/entry_setup?process=calendering")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_process_returns_400(self):
        response = client.get("/api/finishingProd/entry_setup?co_id=1")
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()

    def test_invalid_process_returns_400(self):
        response = client.get(
            "/api/finishingProd/entry_setup?co_id=1&process=bogus"
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()


# =============================================================================
# entry_save
# =============================================================================


class TestEntrySave:
    """POST /api/finishingProd/entry_save"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _make_router(self, quality_row, existing_daily=None, insert_id=77):
        """Build a db.execute side-effect that routes by the bound SQL text.

        - quality lookup (jute_prod_finishing_quality SELECT) -> quality_row
        - existing active-row check (jute_prod_finishing_daily SELECT) -> existing_daily
        - insert -> result.lastrowid; update / branch-derive -> a benign MagicMock.
        """

        def _route(query, params=None):
            params = params or {}
            sql = str(query).lower()
            if "from jute_prod_finishing_quality" in sql:
                return _fetchone_exec(quality_row)
            if (
                "select finishing_daily_id" in sql
                and "from jute_prod_finishing_daily" in sql
            ):
                return _fetchone_exec(existing_daily)
            ins = MagicMock()
            ins.lastrowid = insert_id
            return ins

        return _route

    def test_save_success_stores_prod_qty(self):
        quality = MagicMock()
        quality.quality_type = 1  # hessian (matches calendering)
        self._mock_session.execute.side_effect = self._make_router(quality)

        payload = {
            "co_id": 1,
            "branch_id": 2,  # provided -> no branch-derive query
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "calendering",
            "machine_id": 9,
            "finishing_quality_id": 5,
            "prod_qty": 1000.0,
            "prod_uom": "m",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["finishing_daily_id"] == 77
        self._mock_session.commit.assert_called_once()

        # The insert bind dict carries the production figure; everything else is NULL.
        insert_params = self._mock_session.execute.call_args_list[-1].args[1]
        assert insert_params["prod_qty"] == 1000.0
        assert insert_params["prod_uom"] == "m"
        assert insert_params["input_qty"] is None
        assert insert_params["wastage_kg"] is None
        assert insert_params["std_speed"] is None
        assert insert_params["std_prod"] is None

    def test_save_quality_process_mismatch_returns_400(self):
        """A sacking quality (quality_type=2) under a cloth process (calendering) -> 400."""
        quality = MagicMock()
        quality.quality_type = 2  # sacking, but calendering expects hessian (1)
        self._mock_session.execute.side_effect = self._make_router(quality)

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "calendering",
            "machine_id": 9,
            "finishing_quality_id": 5,
            "prod_qty": 1000.0,
            "prod_uom": "m",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)

        assert response.status_code == 400
        assert "match" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_save_balepress_accepts_cloth_quality(self):
        """balepress has no quality_type filter -> a cloth quality (type 1) succeeds."""
        quality = MagicMock()
        quality.quality_type = 1
        self._mock_session.execute.side_effect = self._make_router(quality)

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "balepress",
            "machine_id": 9,
            "finishing_quality_id": 5,
            "prod_qty": 50.0,
            "prod_uom": "bales",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["finishing_daily_id"] == 77
        self._mock_session.commit.assert_called_once()

    def test_save_balepress_accepts_bag_quality(self):
        """balepress has no quality_type filter -> a bag quality (type 2) also succeeds."""
        quality = MagicMock()
        quality.quality_type = 2
        self._mock_session.execute.side_effect = self._make_router(quality)

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "balepress",
            "machine_id": 9,
            "finishing_quality_id": 5,
            "prod_qty": 50.0,
            "prod_uom": "bales",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["finishing_daily_id"] == 77
        self._mock_session.commit.assert_called_once()

    def test_save_quality_not_found_returns_404(self):
        self._mock_session.execute.side_effect = self._make_router(None)

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "calendering",
            "machine_id": 9,
            "finishing_quality_id": 999,
            "prod_qty": 1000.0,
            "prod_uom": "m",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)

        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_save_invalid_process_returns_400(self):
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "bogus",
            "machine_id": 9,
            "finishing_quality_id": 5,
            "prod_qty": 1000.0,
            "prod_uom": "m",
        }
        response = client.post("/api/finishingProd/entry_save", json=payload)
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


# =============================================================================
# entry_by_date
# =============================================================================


class TestEntryByDate:
    """GET /api/finishingProd/entry_by_date"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_rows(self):
        """entry_by_date -> _entries_for_date issues a single day-grid rows query."""
        entry_rows = [
            _mock_row(
                {
                    "finishing_daily_id": 50,
                    "co_id": 1,
                    "process": "calendering",
                    "tran_date": "2026-06-21",
                    "prod_qty": 1000.0,
                }
            ),
        ]
        self._mock_session.execute.side_effect = [_fetchall_exec(entry_rows)]

        response = client.get(
            "/api/finishingProd/entry_by_date?co_id=1&tran_date=2026-06-21"
            "&process=calendering"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["finishing_daily_id"] == 50
        assert data[0]["prod_qty"] == 1000.0

    def test_empty(self):
        self._mock_session.execute.side_effect = [_fetchall_exec([])]
        response = client.get(
            "/api/finishingProd/entry_by_date?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/finishingProd/entry_by_date?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/finishingProd/entry_by_date?tran_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# entry_delete
# =============================================================================


class TestEntryDelete:
    """DELETE /api/finishingProd/entry_delete/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_delete_success(self):
        existing = MagicMock()
        existing.finishing_daily_id = 50
        find_exec = MagicMock()
        find_exec.fetchone.return_value = existing
        # find(existing), soft-delete header.
        self._mock_session.execute.side_effect = [
            find_exec,
            MagicMock(),
        ]

        response = client.delete("/api/finishingProd/entry_delete/50?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found_returns_404(self):
        find_exec = MagicMock()
        find_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = find_exec

        response = client.delete("/api/finishingProd/entry_delete/999?co_id=1")

        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_delete_missing_co_id_returns_400(self):
        response = client.delete("/api/finishingProd/entry_delete/50")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# employee_lookup (labour processes — sacksewing)
# =============================================================================


class TestEmployeeLookup:
    """GET /api/finishingProd/employee_lookup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_lookup_found(self):
        emp = MagicMock()
        emp.eb_id = 42
        emp.emp_code = "E001"
        emp.employee_name = "E001 John Q Public"
        self._mock_session.execute.return_value = _fetchone_exec(emp)

        response = client.get(
            "/api/finishingProd/employee_lookup?co_id=1&branch_id=2&emp_code=E001"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["eb_id"] == 42
        assert data["emp_code"] == "E001"
        assert data["employee_name"] == "E001 John Q Public"
        # The bound query is branch-scoped on emp_code (eb_id bind NULL).
        params = self._mock_session.execute.call_args.args[1]
        assert params["branch_id"] == 2
        assert params["emp_code"] == "E001"
        assert params["eb_id"] is None

    def test_lookup_not_found_returns_404(self):
        self._mock_session.execute.return_value = _fetchone_exec(None)
        response = client.get(
            "/api/finishingProd/employee_lookup?co_id=1&branch_id=2&emp_code=NOPE"
        )
        assert response.status_code == 404
        assert "emp code not found" in response.json()["detail"].lower()

    def test_lookup_missing_branch_returns_400(self):
        response = client.get(
            "/api/finishingProd/employee_lookup?co_id=1&emp_code=E001"
        )
        assert response.status_code == 400
        assert "branch" in response.json()["detail"].lower()

    def test_lookup_missing_emp_code_returns_400(self):
        response = client.get(
            "/api/finishingProd/employee_lookup?co_id=1&branch_id=2"
        )
        assert response.status_code == 400
        assert "emp_code" in response.json()["detail"].lower()


# =============================================================================
# entry_save — labour (sacksewing): eb_id-keyed, no machine
# =============================================================================


class TestSackSewingSave:
    """POST /api/finishingProd/entry_save for process=sacksewing (labour, no machine)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _router(self, quality_row, emp_row, existing_daily=None, insert_id=88):
        """Route db.execute by bound SQL: quality lookup, hrms employee resolve,
        existing-row check, then insert -> lastrowid."""

        def _route(query, params=None):
            sql = str(query).lower()
            if "from jute_prod_finishing_quality" in sql:
                return _fetchone_exec(quality_row)
            if "from hrms_ed_official_details" in sql:
                return _fetchone_exec(emp_row)
            if (
                "select finishing_daily_id" in sql
                and "from jute_prod_finishing_daily" in sql
            ):
                return _fetchone_exec(existing_daily)
            ins = MagicMock()
            ins.lastrowid = insert_id
            return ins

        return _route

    def _payload(self, **over):
        p = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "process": "sacksewing",
            "eb_id": 42,
            "finishing_quality_id": 5,
            "prod_qty": 300.0,
            "prod_uom": "bag",
        }
        p.update(over)
        return p

    def test_save_success_stores_eb_id_null_machine(self):
        quality = MagicMock()
        quality.quality_type = 2  # sacking matches sacksewing
        emp = MagicMock()
        emp.eb_id = 42
        self._mock_session.execute.side_effect = self._router(quality, emp)

        response = client.post(
            "/api/finishingProd/entry_save", json=self._payload()
        )

        assert response.status_code == 200
        assert response.json()["data"]["finishing_daily_id"] == 88
        self._mock_session.commit.assert_called_once()
        insert_params = self._mock_session.execute.call_args_list[-1].args[1]
        assert insert_params["eb_id"] == 42
        assert insert_params["machine_id"] is None
        assert insert_params["prod_qty"] == 300.0

    def test_save_missing_eb_id_returns_400(self):
        quality = MagicMock()
        quality.quality_type = 2
        emp = MagicMock()
        self._mock_session.execute.side_effect = self._router(quality, emp)

        response = client.post(
            "/api/finishingProd/entry_save", json=self._payload(eb_id=None)
        )

        assert response.status_code == 400
        self._mock_session.commit.assert_not_called()

    def test_save_employee_not_in_branch_returns_404(self):
        quality = MagicMock()
        quality.quality_type = 2
        # emp resolve returns None -> employee not in this branch
        self._mock_session.execute.side_effect = self._router(quality, None)

        response = client.post(
            "/api/finishingProd/entry_save", json=self._payload()
        )

        assert response.status_code == 404
        assert "emp code not found" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()
