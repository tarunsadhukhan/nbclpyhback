"""Tests for Beaming Standards / Targets Map endpoints (Page B).

Tests for src/juteProduction/beaming_target_map.py (prefix /api/beamingTargetMap).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through
app.dependency_overrides keyed by those exact symbols.

Covered:
  * happy path (target_map_setup)
  * missing co_id -> 400 (target_map_setup)
  * bulk_save reporting inserted / updated / cleared in one transaction
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteProduction.beaming_target_map import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestTargetMapSetup:
    """GET /api/beamingTargetMap/target_map_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_machines_qualities_and_enums(self):
        # Setup now resolves TWO ref lists: machines (mcid) then qualities (qid).
        machine_rows = [
            _mock_row({
                "machine_id": 7, "machine_name": "Beam-1", "mech_code": "BM01",
                "branch_id": 2,
            }),
        ]
        quality_rows = [
            _mock_row({
                "bm_quality_id": 5, "bm_quality_code": "272-13/272",
                "bm_quality_name": "Red", "branch_id": 2,
            }),
        ]
        exec_machines = MagicMock(); exec_machines.fetchall.return_value = machine_rows
        exec_qualities = MagicMock(); exec_qualities.fetchall.return_value = quality_rows
        # Execute order: machines list, then qualities list.
        self._mock_session.execute.side_effect = [exec_machines, exec_qualities]

        response = client.get("/api/beamingTargetMap/target_map_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["machines"][0]["machine_id"] == 7
        # qid dimension re-added: qualities are listed as qid refs (bm_quality_id).
        assert data["qualities"][0]["bm_quality_id"] == 5
        assert data["qualities"][0]["bm_quality_code"] == "272-13/272"
        # Two id_types now: machine (mcid) + quality (qid).
        assert data["id_types"] == ["mcid", "qid"]
        # 'actual' joins standard/target — the Beaming SQC page reuses these endpoints
        # with value_role='actual' (param 'speed' = actual RPM). LOCKED CONTRACT.
        assert "standard" in data["value_roles"]
        assert "target" in data["value_roles"]
        assert "actual" in data["value_roles"]
        # PARAMS is the union across both dimensions: machine speed/dia + quality
        # laid_length/cuts_per_beam/eff.
        assert "laid_length" in data["params"]
        assert "cuts_per_beam" in data["params"]
        assert "eff" in data["params"]
        assert "speed" in data["params"]
        assert "dia" in data["params"]

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/beamingTargetMap/target_map_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestTargetMapBulkSave:
    """POST /api/beamingTargetMap/target_map_bulk_save"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_bulk_save_inserted_updated_cleared(self):
        """One insert (no existing row), one update (existing + value), one clear
        (existing + value=None), all committed in a single transaction.

        Uses the QID dimension (laid_length / cuts_per_beam / eff are quality-linked
        standards now), so ref_id is a bm_quality_id and id_type='qid'."""
        # find_exact_beaming_grid_row_query result per cell, in cell order:
        #   cell 1 (insert): no existing row -> fetchone None
        #   cell 2 (update): existing row present -> fetchone row
        #   cell 3 (clear) : existing row present -> fetchone row (then soft-deleted)
        existing_row = MagicMock()
        existing_row.beaming_target_map_id = 321

        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        found_for_update = MagicMock()
        found_for_update.fetchone.return_value = existing_row
        found_for_clear = MagicMock()
        found_for_clear.fetchone.return_value = existing_row

        # Side effects, in execution order: find(cell1), insert(cell1),
        # find(cell2), update(cell2), find(cell3), clear(cell3).
        self._mock_session.execute.side_effect = [
            no_existing, MagicMock(),       # cell 1 -> insert
            found_for_update, MagicMock(),  # cell 2 -> update
            found_for_clear, MagicMock(),   # cell 3 -> clear
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "qid",          # quality-linked standards
            "value_role": "standard",
            "cells": [
                {"ref_id": 5, "param": "laid_length", "value": 1200.0},
                {"ref_id": 5, "param": "cuts_per_beam", "value": 50.0},
                {"ref_id": 5, "param": "eff", "value": None},
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 1
        assert data["updated"] == 1
        assert data["cleared"] == 1
        self._mock_session.commit.assert_called_once()

        # The INSERT bind params carry the QID-linked standard row (laid_length).
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "qid"
        assert insert_params["value_role"] == "standard"
        assert insert_params["param"] == "laid_length"
        assert insert_params["ref_id"] == 5
        assert insert_params["value"] == 1200.0

    def test_invalid_param_for_role_returns_400(self):
        """A param not valid for (id_type, value_role) -> 400; whole batch rolled back."""
        # 'laid_length' is a QUALITY-linked (qid) param; it is NOT valid under id_type
        # 'mcid' for any role (mcid/target only allows 'speed').
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "target",
            "cells": [
                {"ref_id": 7, "param": "laid_length", "value": 1200.0},
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_qid_standard_inserts_quality_linked_row(self):
        """A qid/standard cell (eff) inserts a QUALITY-linked standard row (ref_id =
        bm_quality_id). grid_params_for('qid','standard') allows laid_length /
        cuts_per_beam / eff."""
        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        insert_exec = MagicMock()
        self._mock_session.execute.side_effect = [no_existing, insert_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 5, "param": "eff", "value": 85.0},  # quality std eff
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["inserted"] == 1
        self._mock_session.commit.assert_called_once()
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "qid"
        assert insert_params["param"] == "eff"
        assert insert_params["ref_id"] == 5

    def test_qid_target_only_allows_eff(self):
        """value_role='target' under qid only allows 'eff' (the quality target eff);
        laid_length/cuts_per_beam are standard-only on the quality -> 400."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "target",
            "cells": [
                {"ref_id": 5, "param": "laid_length", "value": 1200.0},  # not allowed
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_mcid_standard_rejects_quality_param(self):
        """The machine (mcid) standard only carries speed/dia now; a quality param
        (cuts_per_beam) under mcid/standard -> 400 (moved to the qid dimension)."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 7, "param": "cuts_per_beam", "value": 50.0},  # qid-only now
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_negative_value_returns_400(self):
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 7, "param": "speed", "value": -5.0},
            ],
        }
        # find query may run before the negative check; give it a benign result.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "negative" in response.json()["detail"].lower()

    def test_actual_role_inserts_rpm_row(self):
        """value_role='actual' is the Beaming SQC seam: it reuses THIS endpoint to
        insert an actual RPM row (param 'speed'). No existing row -> one INSERT bound
        to value_role='actual', param='speed'. LOCKED CONTRACT (the SQC page calls the
        same bulk_save, just role=actual / param=speed(rpm))."""
        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        insert_exec = MagicMock()
        # Side effects: find(cell1) -> None, then insert(cell1).
        self._mock_session.execute.side_effect = [no_existing, insert_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "actual",
            "cells": [
                {"ref_id": 7, "param": "speed", "value": 30.0},  # actual RPM
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 1
        assert data["updated"] == 0
        assert data["cleared"] == 0
        self._mock_session.commit.assert_called_once()

        # The INSERT bind params carry the actual-role RPM row.
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["value_role"] == "actual"
        assert insert_params["param"] == "speed"
        assert insert_params["value"] == 30.0
        assert insert_params["ref_id"] == 7

    def test_actual_role_updates_existing_rpm_row(self):
        """value_role='actual' with an existing exact-key row -> UPDATE (not insert).
        Mirrors how re-entering the Beaming SQC actual RPM overwrites the same row."""
        existing_row = MagicMock()
        existing_row.beaming_target_map_id = 654
        found = MagicMock()
        found.fetchone.return_value = existing_row
        update_exec = MagicMock()
        # Side effects: find(cell1) -> existing, then update(cell1).
        self._mock_session.execute.side_effect = [found, update_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "actual",
            "cells": [
                {"ref_id": 7, "param": "speed", "value": 32.5},  # updated actual RPM
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["updated"] == 1
        assert data["inserted"] == 0
        self._mock_session.commit.assert_called_once()

        update_params = self._mock_session.execute.call_args_list[1].args[1]
        assert update_params["id"] == 654
        assert update_params["value"] == 32.5

    def test_actual_role_rejects_non_speed_param(self):
        """value_role='actual' only allows 'speed' (RPM) — a non-speed param 400s
        (grid_params_for('mcid','actual') == ['speed'])."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "actual",
            "cells": [
                {"ref_id": 7, "param": "eff", "value": 90.0},  # not allowed for actual
            ],
        }

        response = client.post("/api/beamingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


class TestTargetMapGridActualRole:
    """GET /api/beamingTargetMap/target_map_grid with value_role='actual'."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_actual_grid_resolves_speed_param_only(self):
        """value_role='actual' resolves params == ['speed'] (the actual RPM column).
        One machine ref + a resolved speed cell -> the returned grid carries params
        ['speed'] and the cell value. Beaming SQC reuses this exact grid read."""
        machine_rows = [
            _mock_row({
                "machine_id": 7, "machine_name": "Beam-1", "mech_code": "BM01",
                "branch_id": 2,
            }),
        ]
        machines_exec = MagicMock()
        machines_exec.fetchall.return_value = machine_rows
        # resolve_beaming_grid_cell_query result for the single 'speed' cell.
        speed_cell = MagicMock()
        speed_cell.value = 30.0
        # is_exact compares str(source) == str(effective_date); the endpoint builds
        # effective_date as date.fromisoformat("2026-06-21"), whose str() is "2026-06-21".
        speed_cell.effective_date = "2026-06-21"
        cell_exec = MagicMock()
        cell_exec.fetchone.return_value = speed_cell
        # Execute order: machines list, then ONE resolve per param (only 'speed').
        self._mock_session.execute.side_effect = [machines_exec, cell_exec]

        response = client.get(
            "/api/beamingTargetMap/target_map_grid"
            "?co_id=1&id_type=mcid&value_role=actual&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # actual role exposes only the speed (RPM) param.
        assert data["params"] == ["speed"]
        assert data["rows"][0]["ref_id"] == 7
        assert data["rows"][0]["cells"]["speed"]["value"] == 30.0
        assert data["rows"][0]["cells"]["speed"]["is_exact"] is True


class TestTargetMapGridQid:
    """GET /api/beamingTargetMap/target_map_grid with id_type='qid'."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_qid_standard_grid_uses_quality_refs(self):
        """id_type='qid' lists QUALITY refs (bm_quality_id/code/name) and resolves the
        quality-linked standard params laid_length / cuts_per_beam / eff (one resolve
        call per param)."""
        quality_rows = [
            _mock_row({
                "bm_quality_id": 5, "bm_quality_code": "272-13/272",
                "bm_quality_name": "Red", "branch_id": 2,
            }),
        ]
        qualities_exec = MagicMock()
        qualities_exec.fetchall.return_value = quality_rows

        def _cell(value):
            c = MagicMock()
            c.value = value
            c.effective_date = "2026-06-21"
            exec_m = MagicMock()
            exec_m.fetchone.return_value = c
            return exec_m

        # Execute order: qualities list, then ONE resolve per param in order
        # laid_length, cuts_per_beam, eff.
        self._mock_session.execute.side_effect = [
            qualities_exec,
            _cell(1200.0),  # laid_length
            _cell(50.0),    # cuts_per_beam
            _cell(85.0),    # eff
        ]

        response = client.get(
            "/api/beamingTargetMap/target_map_grid"
            "?co_id=1&id_type=qid&value_role=standard&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # qid/standard exposes the quality-linked standard params.
        assert data["params"] == ["laid_length", "cuts_per_beam", "eff"]
        # ref is the quality, not a machine.
        assert data["rows"][0]["ref_id"] == 5
        assert data["rows"][0]["ref_code"] == "272-13/272"
        assert data["rows"][0]["cells"]["laid_length"]["value"] == 1200.0
        assert data["rows"][0]["cells"]["eff"]["value"] == 85.0


class TestGridParamsForContract:
    """grid_params_for LOCKED CONTRACT (param ↔ (id_type, value_role))."""

    def test_locked_contract(self):
        from src.juteProduction.beaming_target_map import grid_params_for

        # Quality (qid) dimension.
        assert grid_params_for("qid", "standard") == [
            "laid_length", "cuts_per_beam", "eff",
        ]
        assert grid_params_for("qid", "target") == ["eff"]
        assert grid_params_for("qid", "actual") == []  # no qid actual role
        # Machine (mcid) dimension.
        assert grid_params_for("mcid", "standard") == ["speed", "dia"]
        assert grid_params_for("mcid", "target") == ["speed"]
        assert grid_params_for("mcid", "actual") == ["speed"]
        # Unknown combination.
        assert grid_params_for("bogus", "standard") == []
