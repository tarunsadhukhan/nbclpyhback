"""Tests for Stoppage Hours entry endpoints.

Tests for src/juteProduction/stoppage_entry.py (prefix /api/stoppageProd).

Portal persona: dependencies get_tenant_db + get_current_user_with_refresh are
overridden via app.dependency_overrides (same pattern as test_winding_entry.py).
The DB session is a MagicMock; rows expose a dict ._mapping for fetchall reads,
and attribute access (.working_hours, .branch_id, .spell_id, ...) for fetchone
reads.

Coverage:
* entry_create_setup: 200-with-data success (machines/spells/reasons) + missing
  co_id -> 400
* entries_by_date: 200-with-data success (floats/dates serialized) + missing
  co_id / tran_date -> 400
* entry_create: success (200, returns stoppage_hours_id), branch derivation when
  omitted, rejects bad reason_code (400), rejects stoppage_hours <= 0 (400) and
  > working_hours (400)
* entry_edit: success (200), re-validates and updates only editable fields
* entry_delete: success (200, soft-delete active = 0) + 404 when missing
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.constants import STOPPAGE_REASONS

client = TestClient(app)


def _mock_row(mapping: dict):
    """A query row whose ._mapping is a plain dict (matches r._mapping usage)."""
    row = MagicMock()
    row._mapping = mapping
    return row


def _attr_row(**attrs):
    """A fetchone() row exposing attributes (e.g. .working_hours, .branch_id)."""
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    return row


_UNSET = object()


def _exec_result(*, fetchall=_UNSET, fetchone=_UNSET, lastrowid=_UNSET):
    """Build a MagicMock execute() result with the given return values.

    Uses an _UNSET sentinel so an explicit ``fetchone=None`` (e.g. "row not
    found") is honored rather than leaving fetchone() returning a truthy mock.
    """
    res = MagicMock()
    if fetchall is not _UNSET:
        res.fetchall.return_value = fetchall
    if fetchone is not _UNSET:
        res.fetchone.return_value = fetchone
    if lastrowid is not _UNSET:
        res.lastrowid = lastrowid
    return res


class TestStoppageEntryEndpoints:
    """Tests for Stoppage Hours API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ----------------------------------------------------------------- setup
    def test_entry_create_setup_success(self):
        """Setup returns machines / spells / reasons under data."""
        machine_row = _mock_row(
            {
                "machine_id": 10,
                "machine_name": "M-1",
                "mech_code": "MC1",
                "machine_type_id": 3,
                "machine_type_name": "Spinning",
                "dept_id": 50,
                "dept_name": "Spinning Dept",
                "branch_id": 1,
            }
        )
        spell_row = _mock_row(
            {
                "spell_id": 7,
                "spell_code": "A1",
                "spell_name": "Shift A1",
                "working_hours": 5.0,
            }
        )
        # Order of execute().fetchall(): machines, spells
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [machine_row],
            [spell_row],
        ]

        response = client.get("/api/stoppageProd/entry_create_setup?co_id=1&branch_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["machines"][0]["machine_id"] == 10
        assert data["machines"][0]["dept_name"] == "Spinning Dept"
        assert data["spells"][0]["spell_id"] == 7
        assert data["spells"][0]["working_hours"] == 5.0
        # reasons derived from STOPPAGE_REASONS / labels
        codes = [r["code"] for r in data["reasons"]]
        assert codes == list(STOPPAGE_REASONS)
        assert {"code": "mechanical", "label": "Mechanical"} in data["reasons"]

    def test_entry_create_setup_missing_co_id(self):
        response = client.get("/api/stoppageProd/entry_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    # ------------------------------------------------------------ by_date
    def test_entries_by_date_success(self):
        """entries_by_date returns a list under data with floats/dates serialized."""
        row = _mock_row(
            {
                "stoppage_hours_id": 101,
                "tran_date": "2026-06-01",
                "spell_id": 7,
                "spell_code": "A1",
                "machine_id": 10,
                "machine_name": "M-1",
                "dept_id": 50,
                "dept_name": "Spinning Dept",
                "stoppage_hours": 2.5,
                "reason_code": "mechanical",
                "remarks": "belt slip",
                "branch_id": 1,
            }
        )
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get(
            "/api/stoppageProd/entries_by_date?co_id=1&branch_id=1&tran_date=2026-06-01"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["stoppage_hours_id"] == 101
        assert data[0]["stoppage_hours"] == 2.5
        assert data[0]["spell_code"] == "A1"
        assert data[0]["dept_name"] == "Spinning Dept"
        assert data[0]["tran_date"] == "2026-06-01"

    def test_entries_by_date_missing_co_id(self):
        response = client.get("/api/stoppageProd/entries_by_date?tran_date=2026-06-01")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_entries_by_date_missing_tran_date(self):
        response = client.get("/api/stoppageProd/entries_by_date?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json().get("detail", "").lower()

    # ------------------------------------------------------------ create
    def test_entry_create_success(self):
        """Valid event inserts a row and returns the new stoppage_hours_id."""
        # execute() sequence: working_hours lookup (validation), then insert.
        # branch_id supplied -> no derivation query.
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_attr_row(working_hours=5.0)),  # _validate_hours
            _exec_result(lastrowid=101),                           # insert
        ]
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "machine_id": 10,
            "stoppage_hours": 2.5,
            "reason_code": "mechanical",
            "remarks": "belt slip",
        }

        response = client.post("/api/stoppageProd/entry_create", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["stoppage_hours_id"] == 101

    def test_entry_create_derives_branch_when_omitted(self):
        """branch_id None -> branch is derived via machine->dept->branch."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_attr_row(working_hours=5.0)),   # _validate_hours
            _exec_result(fetchone=_attr_row(branch_id=9)),         # _derive_branch_id
            _exec_result(lastrowid=102),                            # insert
        ]
        payload = {
            "co_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "machine_id": 10,
            "stoppage_hours": 1.0,
            "reason_code": "electrical",
        }

        response = client.post("/api/stoppageProd/entry_create", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["stoppage_hours_id"] == 102
        # The insert (last execute call) must carry the derived branch_id = 9.
        insert_params = self._mock_session.execute.call_args_list[-1].args[1]
        assert insert_params["branch_id"] == 9

    def test_entry_create_rejects_bad_reason_code(self):
        """reason_code outside STOPPAGE_REASONS -> 400 (before any DB read)."""
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "machine_id": 10,
            "stoppage_hours": 2.5,
            "reason_code": "weather",  # not in the enum
        }

        response = client.post("/api/stoppageProd/entry_create", json=payload)

        assert response.status_code == 400
        assert "reason_code" in response.json().get("detail", "").lower()

    def test_entry_create_rejects_non_positive_hours(self):
        """stoppage_hours <= 0 -> 400."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_attr_row(working_hours=5.0)),  # _validate_hours
        ]
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "machine_id": 10,
            "stoppage_hours": 0,  # not > 0
            "reason_code": "mechanical",
        }

        response = client.post("/api/stoppageProd/entry_create", json=payload)

        assert response.status_code == 400
        assert "stoppage_hours" in response.json().get("detail", "").lower()

    def test_entry_create_rejects_hours_over_working_hours(self):
        """stoppage_hours > spell working_hours -> 400."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_attr_row(working_hours=5.0)),  # _validate_hours
        ]
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "machine_id": 10,
            "stoppage_hours": 6.0,  # > 5.0 working hours
            "reason_code": "mechanical",
        }

        response = client.post("/api/stoppageProd/entry_create", json=payload)

        assert response.status_code == 400
        assert "stoppage_hours" in response.json().get("detail", "").lower()

    # ------------------------------------------------------------- delete
    def test_entry_delete_sets_active_zero(self):
        """Delete loads the active row then issues the soft-delete UPDATE."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_attr_row(stoppage_hours_id=101)),  # active-by-id
            _exec_result(),                                            # soft delete
        ]

        response = client.delete("/api/stoppageProd/entry_delete/101?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"]["stoppage_hours_id"] == 101
        # The soft-delete UPDATE (last execute call) targets this row by id.
        delete_params = self._mock_session.execute.call_args_list[-1].args[1]
        assert delete_params["id"] == 101
        self._mock_session.commit.assert_called()

    def test_entry_delete_not_found_returns_404(self):
        """Deleting a missing/inactive row -> 404."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=None),  # active-by-id -> none
        ]

        response = client.delete("/api/stoppageProd/entry_delete/999?co_id=1")

        assert response.status_code == 404

    # --------------------------------------------------------------- edit
    def test_entry_edit_success(self):
        """Edit re-validates and updates only the editable fields."""
        existing = _attr_row(
            stoppage_hours_id=101,
            co_id=1,
            branch_id=1,
            tran_date="2026-06-01",
            spell_id=7,
            machine_id=10,
            stoppage_hours=2.5,
            reason_code="mechanical",
            remarks="old",
        )
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),                      # active-by-id
            _exec_result(fetchone=_attr_row(working_hours=5.0)),  # _validate_hours
            _exec_result(),                                       # update
        ]
        payload = {"stoppage_hours": 3.0, "reason_code": "labor", "remarks": "new"}

        response = client.put("/api/stoppageProd/entry_edit/101", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["stoppage_hours_id"] == 101
        update_params = self._mock_session.execute.call_args_list[-1].args[1]
        assert update_params["stoppage_hours"] == 3.0
        assert update_params["reason_code"] == "labor"
        assert update_params["remarks"] == "new"
        assert update_params["spell_id"] == 7  # unchanged -> falls back to existing
