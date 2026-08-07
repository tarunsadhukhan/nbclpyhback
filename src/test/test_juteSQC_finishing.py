"""Tests for the Finishing SQC (actuals) endpoints.

Tests for src/juteSQC/finishing_sqc.py (prefix /api/juteSQC).

The Finishing SQC page captures ACTUALS into the SAME spec-sheet table the standards /
targets live in (jute_prod_finishing_target_map, value_role='actual'). These endpoints
PROXY to the finishing_target_map core functions with value_role forced to 'actual'.

REDESIGN (SQC dropped for now): value_role 'actual' is EMPTY for EVERY process/id_type
in constants.FINISHING_PARAMS. So:
  * the actuals param matrix is empty everywhere (every list is []),
  * the actual grid resolves NO cells (params == []),
  * the actual save accepts no param (any cell -> 400 'invalid param'); only an
    empty-cells body succeeds, returning inserted=updated=cleared=0.
The proxy plumbing (value_role forced to 'actual', enum validation, response shape) is
still exercised.

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the SQC router module's namespace and
resolved by FastAPI via Depends, so we override them through app.dependency_overrides
keyed by those EXACT symbols.

Covered:
  * finishing_sqc_setup happy path (value_role locked to 'actual', EMPTY actual matrix)
    + missing co_id 400 + invalid process 400
  * finishing_sqc_actual_grid success (params == [] — actual role empty) + missing co_id
    400 + missing process 400 + invalid id_type 400 + missing effective_date 400
  * finishing_sqc_actual_save empty-cells no-op (value_role forced 'actual') + any param
    rejected 400 + invalid process 400 + invalid id_type 400
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteSQC.finishing_sqc import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _machine_exec(rows):
    ex = MagicMock()
    ex.fetchall.return_value = rows
    return ex


def _resolve_cell(value, eff_date="2026-06-21"):
    cell = MagicMock()
    cell.value = value
    cell.effective_date = eff_date
    ex = MagicMock()
    ex.fetchone.return_value = cell
    return ex


# =============================================================================
# finishing_sqc_setup
# =============================================================================


class TestFinishingSqcSetup:
    """GET /api/juteSQC/finishing_sqc_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_without_process_locks_value_role_actual(self):
        response = client.get("/api/juteSQC/finishing_sqc_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        # Finishing SQC only ever writes ACTUALS.
        assert data["value_role"] == "actual"
        assert data["id_types"] == ["mcid", "qid"]
        # all NINE processes surfaced (incl. new rolling/herackle/sacksewing).
        for proc in (
            "damping", "calendering", "lapping", "rolling",
            "cutting", "hemming", "herackle", "sacksewing", "balepress",
        ):
            assert proc in data["processes"], proc
        # SQC dropped -> the 'actual'-role slice is EMPTY for every process/id_type.
        # no-param processes have NO id_type keys at all ({}).
        assert data["params"]["damping"] == {}
        assert data["params"]["calendering"] == {}
        assert data["params"]["rolling"] == {}
        # processes that DO have a qid key still expose an EMPTY actual list.
        assert data["params"]["lapping"]["qid"] == []
        assert data["params"]["cutting"]["qid"] == []
        assert data["params"]["sacksewing"]["qid"] == []
        assert data["params"]["balepress"]["qid"] == []
        assert data["machines"] == []
        assert data["qualities"] == []

    def test_success_with_process_returns_refs(self):
        machine_rows = [
            _mock_row({"machine_id": 9, "mech_code": "LAP01", "machine_name": "Lap-1"}),
        ]
        quality_rows = [
            _mock_row(
                {
                    "finishing_quality_id": 3,
                    "fin_quality_code": "HC-10",
                    "fin_quality_name": "Hessian-10",
                }
            ),
        ]
        self._mock_session.execute.side_effect = [
            _machine_exec(machine_rows),
            _machine_exec(quality_rows),
        ]

        response = client.get(
            "/api/juteSQC/finishing_sqc_setup?co_id=1&process=lapping"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["machines"][0]["machine_id"] == 9
        assert data["qualities"][0]["finishing_quality_id"] == 3

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/juteSQC/finishing_sqc_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_process_returns_400(self):
        response = client.get(
            "/api/juteSQC/finishing_sqc_setup?co_id=1&process=bogus"
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()


# =============================================================================
# finishing_sqc_actual_grid
# =============================================================================


class TestFinishingSqcActualGrid:
    """GET /api/juteSQC/finishing_sqc_actual_grid"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_actual_grid_has_no_params_sqc_dropped(self):
        """value_role is forced to 'actual'; the actual role is EMPTY for every process,
        so params == [] and NO cells are resolved (only the refs list is fetched).
        The proxy still lists refs (one row per quality) with empty cells."""
        quality_rows = [
            _mock_row({"finishing_quality_id": 3, "fin_quality_code": "HC-10",
                       "fin_quality_name": "Hessian-10"}),
        ]
        self._mock_session.execute.side_effect = [_machine_exec(quality_rows)]

        response = client.get(
            "/api/juteSQC/finishing_sqc_actual_grid"
            "?co_id=1&process=lapping&id_type=qid&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # actual-role slice is empty everywhere.
        assert data["params"] == []
        assert data["rows"][0]["ref_id"] == 3
        assert data["rows"][0]["cells"] == {}

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/juteSQC/finishing_sqc_actual_grid"
            "?process=lapping&id_type=qid&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_process_returns_400(self):
        response = client.get(
            "/api/juteSQC/finishing_sqc_actual_grid"
            "?co_id=1&id_type=qid&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()

    def test_invalid_id_type_returns_400(self):
        response = client.get(
            "/api/juteSQC/finishing_sqc_actual_grid"
            "?co_id=1&process=lapping&id_type=bogus&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "id_type" in response.json()["detail"].lower()

    def test_missing_effective_date_returns_400(self):
        response = client.get(
            "/api/juteSQC/finishing_sqc_actual_grid"
            "?co_id=1&process=lapping&id_type=qid"
        )
        assert response.status_code == 400
        assert "effective_date" in response.json()["detail"].lower()


# =============================================================================
# finishing_sqc_actual_save
# =============================================================================


class TestFinishingSqcActualSave:
    """POST /api/juteSQC/finishing_sqc_actual_save"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_actual_save_empty_cells_is_noop(self):
        """SQC is dropped: the 'actual' role has no params, so the only payload that can
        succeed is one with NO cells. The proxy forces value_role='actual' and commits an
        empty batch (inserted=updated=cleared=0). LOCKED CONTRACT (SQC reuses
        bulk_save_finishing_cells with value_role='actual')."""
        payload = {
            "co_id": 1,
            "branch_id": 2,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "cells": [],
        }
        response = client.post(
            "/api/juteSQC/finishing_sqc_actual_save", json=payload
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 0
        assert data["updated"] == 0
        assert data["cleared"] == 0
        self._mock_session.commit.assert_called_once()
        # No cell -> no find/insert query was executed.
        self._mock_session.execute.assert_not_called()

    def test_actual_save_rejects_any_param(self):
        """The 'actual' role is EMPTY for every process/id_type, so ANY cell param is
        invalid for value_role='actual' -> 400, batch rolled back. 'std_prod_yds' is a
        lapping STANDARD param but there is no lapping ACTUAL param."""
        payload = {
            "co_id": 1,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "cells": [
                {"ref_id": 9, "param": "std_prod_yds", "value": 4500.0},
            ],
        }
        # find query may run before the param check; benign result.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.post(
            "/api/juteSQC/finishing_sqc_actual_save", json=payload
        )

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_actual_save_invalid_process_returns_400(self):
        payload = {
            "co_id": 1,
            "process": "bogus",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "cells": [],
        }
        response = client.post(
            "/api/juteSQC/finishing_sqc_actual_save", json=payload
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_actual_save_invalid_id_type_returns_400(self):
        payload = {
            "co_id": 1,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "id_type": "bogus",
            "cells": [],
        }
        response = client.post(
            "/api/juteSQC/finishing_sqc_actual_save", json=payload
        )
        assert response.status_code == 400
        assert "id_type" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()
