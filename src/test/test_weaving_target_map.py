"""Tests for Weaving Standards / Targets Map endpoints.

Tests for src/juteProduction/weaving_target_map.py (prefix /api/weavingTargetMap).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through
app.dependency_overrides keyed by those exact symbols.

Weaving is TWO-DIMENSIONAL (mirrors beaming): id_type is 'mcid' (ref_id = machine_id,
a LOOM) or 'qid' (ref_id = weaving_quality_id). grid_params_for LOCKED CONTRACT:
  mcid + standard -> speed
  mcid + target   -> speed
  mcid + actual   -> speed   (Weaving SQC "Actual Speed" tab)
  qid  + standard -> picks, eff
  qid  + target   -> eff
  qid  + actual   -> []      (NONE: actual picks owned by vw_weaving_pick_act)

Covered:
  * setup returns BOTH machines (mcid) and qualities (qid) + enums
  * grid lists loom refs for id_type='mcid' and quality refs for id_type='qid'
  * bulk_save: mcid speed insert; qid picks/eff insert + update + clear in one txn
  * invalid-param 400 (param not in grid_params_for) -> whole batch rolled back
  * mcid actual speed insert (Weaving SQC "Actual Speed" tab seam)
  * missing co_id -> 400 ; negative value -> 400 ; invalid id_type -> 400
  * grid_params_for locked contract
"""

from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.juteProduction.weaving_target_map import (
    get_tenant_db,
    get_current_user_with_refresh,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestTargetMapSetup:
    """GET /api/weavingTargetMap/target_map_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_machines_qualities_and_enums(self):
        # Two-dimensional: setup resolves machines (mcid) THEN qualities (qid).
        machine_rows = [
            _mock_row({
                "machine_id": 7, "machine_name": "Loom-1", "mech_code": "LM01",
                "branch_id": 2,
            }),
        ]
        quality_rows = [
            _mock_row({
                "weaving_quality_id": 5, "weaving_quality_code": "WQ-272",
                "weaving_quality_name": "Sacking", "branch_id": 2,
            }),
        ]
        exec_machines = MagicMock(); exec_machines.fetchall.return_value = machine_rows
        exec_qualities = MagicMock(); exec_qualities.fetchall.return_value = quality_rows
        # Execute order: machines list, then qualities list.
        self._mock_session.execute.side_effect = [exec_machines, exec_qualities]

        response = client.get("/api/weavingTargetMap/target_map_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        # Loom (mcid) refs.
        assert data["machines"][0]["machine_id"] == 7
        assert data["machines"][0]["mech_code"] == "LM01"
        assert data["machines"][0]["machine_name"] == "Loom-1"
        # Quality (qid) refs.
        assert data["qualities"][0]["weaving_quality_id"] == 5
        assert data["qualities"][0]["weaving_quality_code"] == "WQ-272"
        assert data["qualities"][0]["weaving_quality_name"] == "Sacking"
        # Two id_types now: machine (mcid) + quality (qid).
        assert data["id_types"] == ["mcid", "qid"]
        # value_roles: standard / target / actual (SQC reuses with role=actual).
        assert "standard" in data["value_roles"]
        assert "target" in data["value_roles"]
        assert "actual" in data["value_roles"]
        # PARAMS is the union across both dimensions: machine speed + quality picks/eff.
        assert "speed" in data["params"]
        assert "picks" in data["params"]
        assert "eff" in data["params"]
        # 'dia' was a beaming-machine param; it must NOT leak into weaving.
        assert "dia" not in data["params"]

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingTargetMap/target_map_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestTargetMapBulkSave:
    """POST /api/weavingTargetMap/target_map_bulk_save"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_bulk_save_qid_inserted_updated_cleared(self):
        """One insert (no existing row), one update (existing + value), one clear
        (existing + value=None), all committed in a single transaction.

        QID dimension: ref_id is a weaving_quality_id, id_type='qid'; standard params
        are picks/eff."""
        existing_row = MagicMock()
        existing_row.weaving_target_map_id = 321

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
            "id_type": "qid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 5, "param": "picks", "value": 12.0},  # insert
                {"ref_id": 6, "param": "picks", "value": 14.0},  # update (existing)
                {"ref_id": 7, "param": "eff", "value": None},    # clear (existing)
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 1
        assert data["updated"] == 1
        assert data["cleared"] == 1
        self._mock_session.commit.assert_called_once()

        # The INSERT bind params carry the QID-linked standard row (picks).
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "qid"
        assert insert_params["value_role"] == "standard"
        assert insert_params["param"] == "picks"
        assert insert_params["ref_id"] == 5
        assert insert_params["value"] == 12.0

    def test_mcid_speed_cell_inserts_machine_linked_row(self):
        """A mcid/standard 'speed' cell inserts a MACHINE-linked standard row
        (ref_id = machine_id, a LOOM). grid_params_for('mcid','standard') == ['speed']."""
        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        insert_exec = MagicMock()
        self._mock_session.execute.side_effect = [no_existing, insert_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 7, "param": "speed", "value": 200.0},  # loom std speed
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["inserted"] == 1
        self._mock_session.commit.assert_called_once()
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "mcid"
        assert insert_params["value_role"] == "standard"
        assert insert_params["param"] == "speed"
        assert insert_params["ref_id"] == 7
        assert insert_params["value"] == 200.0

    def test_qid_eff_cell_inserts_quality_linked_row(self):
        """A qid/standard 'eff' cell inserts a QUALITY-linked standard row
        (ref_id = weaving_quality_id). grid_params_for('qid','standard') allows picks/eff."""
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

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["inserted"] == 1
        self._mock_session.commit.assert_called_once()
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "qid"
        assert insert_params["param"] == "eff"
        assert insert_params["ref_id"] == 5

    def test_invalid_param_for_role_returns_400(self):
        """A param not valid for (id_type, value_role) -> 400; whole batch rolled back.
        'dia' is not a weaving param at all -> rejected by the union enum check."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 5, "param": "dia", "value": 10.0},
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_mcid_standard_rejects_quality_param(self):
        """The machine (mcid) standard only carries speed; a quality param (picks)
        under mcid/standard -> 400 (picks is qid-only)."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 7, "param": "picks", "value": 12.0},  # qid-only
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_qid_target_rejects_picks(self):
        """value_role='target' under qid allows only eff; 'picks' is standard-only -> 400
        (param not in grid_params_for('qid','target'))."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "target",
            "cells": [
                {"ref_id": 5, "param": "picks", "value": 12.0},  # not allowed for target
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_qid_actual_rejects_any_param(self):
        """value_role='actual' under qid has NO params (grid_params_for('qid','actual')
        == []) — actual picks are owned by vw_weaving_pick_act, actual speed is mcid.
        Any qid actual cell -> 400."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "actual",
            "cells": [
                {"ref_id": 5, "param": "picks", "value": 11.5},  # no qid actual param
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

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

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "negative" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_invalid_id_type_returns_400(self):
        """id_type other than 'mcid'/'qid' -> 400."""
        payload = {
            "co_id": 1,
            "effective_date": "2026-06-21",
            "id_type": "bogus",
            "value_role": "standard",
            "cells": [
                {"ref_id": 5, "param": "speed", "value": 200.0},
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "id_type" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_mcid_actual_role_inserts_speed_row(self):
        """value_role='actual' is the Weaving SQC "Actual Speed" tab seam for the LOOM:
        it reuses THIS endpoint to insert an actual loom-speed row under id_type='mcid'.
        grid_params_for('mcid','actual') == ['speed'], so a 'speed' cell inserts (no
        existing row) bound to value_role='actual'. (Actual picks go to the Pick-SQC view.)"""
        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        insert_exec = MagicMock()
        self._mock_session.execute.side_effect = [no_existing, insert_exec]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "actual",
            "cells": [
                {"ref_id": 7, "param": "speed", "value": 198.0},  # actual loom speed
            ],
        }

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 1
        assert data["updated"] == 0
        assert data["cleared"] == 0
        self._mock_session.commit.assert_called_once()

        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["id_type"] == "mcid"
        assert insert_params["value_role"] == "actual"
        assert insert_params["param"] == "speed"
        assert insert_params["value"] == 198.0
        assert insert_params["ref_id"] == 7

    def test_mcid_actual_rejects_non_speed_param(self):
        """value_role='actual' under mcid only allows 'speed' -> a non-speed param 400s
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

        response = client.post("/api/weavingTargetMap/target_map_bulk_save", json=payload)

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


class TestTargetMapGrid:
    """GET /api/weavingTargetMap/target_map_grid"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    @staticmethod
    def _batch_cell(ref_id, param, value, effective_date):
        """One row of resolve_weaving_grid_cells_batch_query (attr access)."""
        c = MagicMock()
        c.ref_id = ref_id
        c.param = param
        c.value = value
        # is_exact compares str(source) == str(effective_date); endpoint builds
        # effective_date via date.fromisoformat("2026-06-21") -> str() "2026-06-21".
        c.effective_date = effective_date
        return c

    def test_mcid_standard_grid_lists_loom_refs(self):
        """id_type='mcid' value_role='standard' lists LOOM refs (machine_id/mech_code/
        machine_name) and resolves the single machine param 'speed'."""
        machine_rows = [
            _mock_row({
                "machine_id": 7, "machine_name": "Loom-1", "mech_code": "LM01",
                "branch_id": 2,
            }),
        ]
        machines_exec = MagicMock()
        machines_exec.fetchall.return_value = machine_rows

        batch_exec = MagicMock()
        batch_exec.fetchall.return_value = [
            self._batch_cell(7, "speed", 200.0, "2026-06-21"),
        ]

        # Execute order: machines list, then ONE batch resolve for the whole grid.
        self._mock_session.execute.side_effect = [machines_exec, batch_exec]

        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?co_id=1&id_type=mcid&value_role=standard&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["speed"]
        # ref is the loom.
        assert data["rows"][0]["ref_id"] == 7
        assert data["rows"][0]["ref_code"] == "LM01"
        assert data["rows"][0]["ref_name"] == "Loom-1"
        assert data["rows"][0]["cells"]["speed"]["value"] == 200.0
        assert data["rows"][0]["cells"]["speed"]["is_exact"] is True

    def test_qid_standard_grid_resolves_quality_refs_and_params(self):
        """id_type='qid' value_role='standard' lists QUALITY refs and resolves the
        standard params picks / eff (one resolve call per param, in order)."""
        quality_rows = [
            _mock_row({
                "weaving_quality_id": 5, "weaving_quality_code": "WQ-272",
                "weaving_quality_name": "Sacking", "branch_id": 2,
            }),
        ]
        qualities_exec = MagicMock()
        qualities_exec.fetchall.return_value = quality_rows

        batch_exec = MagicMock()
        batch_exec.fetchall.return_value = [
            self._batch_cell(5, "picks", 12.0, "2026-06-21"),
            self._batch_cell(5, "eff", 85.0, "2026-06-21"),
        ]

        # Execute order: qualities list, then ONE batch resolve for the whole grid.
        self._mock_session.execute.side_effect = [qualities_exec, batch_exec]

        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?co_id=1&id_type=qid&value_role=standard&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["picks", "eff"]
        # ref is the quality.
        assert data["rows"][0]["ref_id"] == 5
        assert data["rows"][0]["ref_code"] == "WQ-272"
        assert data["rows"][0]["ref_name"] == "Sacking"
        assert data["rows"][0]["cells"]["picks"]["value"] == 12.0
        assert data["rows"][0]["cells"]["eff"]["value"] == 85.0
        # All cells resolved at the exact effective_date -> is_exact True.
        assert data["rows"][0]["cells"]["picks"]["is_exact"] is True

    def test_mcid_actual_grid_resolves_speed_only(self):
        """id_type='mcid' value_role='actual' resolves params == ['speed'] (the loom
        actual speed from the Weaving SQC "Actual Speed" tab). An inherited (earlier-
        dated) speed cell is marked is_exact=False."""
        machine_rows = [
            _mock_row({
                "machine_id": 7, "machine_name": "Loom-1", "mech_code": "LM01",
                "branch_id": 2,
            }),
        ]
        machines_exec = MagicMock()
        machines_exec.fetchall.return_value = machine_rows

        batch_exec = MagicMock()
        batch_exec.fetchall.return_value = [
            # inherited (earlier than on_date) -> is_exact False
            self._batch_cell(7, "speed", 198.0, "2026-06-01"),
        ]

        # Execute order: machines list, then ONE batch resolve for the whole grid.
        self._mock_session.execute.side_effect = [machines_exec, batch_exec]

        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?co_id=1&id_type=mcid&value_role=actual&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["speed"]
        cells = data["rows"][0]["cells"]
        assert cells["speed"]["value"] == 198.0
        assert cells["speed"]["is_exact"] is False  # inherited

    def test_grid_omits_unresolved_cell(self):
        """A param whose resolve returns None (or value None) is omitted from cells."""
        quality_rows = [
            _mock_row({
                "weaving_quality_id": 5, "weaving_quality_code": "WQ-272",
                "weaving_quality_name": "Sacking", "branch_id": 2,
            }),
        ]
        qualities_exec = MagicMock()
        qualities_exec.fetchall.return_value = quality_rows

        batch_exec = MagicMock()
        batch_exec.fetchall.return_value = [
            self._batch_cell(5, "picks", 12.0, "2026-06-21"),
            self._batch_cell(5, "eff", None, "2026-06-21"),  # value NULL -> omitted
        ]

        # Execute order: qualities, then ONE batch resolve (eff has value None).
        self._mock_session.execute.side_effect = [qualities_exec, batch_exec]

        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?co_id=1&id_type=qid&value_role=standard&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        cells = response.json()["data"]["rows"][0]["cells"]
        assert "picks" in cells
        assert "eff" not in cells

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?id_type=qid&value_role=standard&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_id_type_returns_400(self):
        response = client.get(
            "/api/weavingTargetMap/target_map_grid"
            "?co_id=1&id_type=bogus&value_role=standard&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "id_type" in response.json()["detail"].lower()


class TestGridParamsForContract:
    """grid_params_for LOCKED CONTRACT (param <-> (id_type, value_role))."""

    def test_locked_contract(self):
        from src.juteProduction.weaving_target_map import grid_params_for

        # Machine (mcid) dimension — the LOOM speed.
        assert grid_params_for("mcid", "standard") == ["speed"]
        assert grid_params_for("mcid", "target") == ["speed"]
        assert grid_params_for("mcid", "actual") == ["speed"]
        # Quality (qid) dimension — picks/eff.
        assert grid_params_for("qid", "standard") == ["picks", "eff"]
        assert grid_params_for("qid", "target") == ["eff"]
        # No qid actual param: actual picks owned by vw_weaving_pick_act, actual speed
        # is the mcid dimension.
        assert grid_params_for("qid", "actual") == []
        # Unknown combination.
        assert grid_params_for("qid", "bogus") == []
        assert grid_params_for("bogus", "standard") == []
