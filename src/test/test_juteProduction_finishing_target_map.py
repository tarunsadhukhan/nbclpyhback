"""Tests for the Finishing Spec-Sheet (standards / targets / actuals) endpoints.

Tests for src/juteProduction/finishing_target_map.py (prefix /api/finishingTargetMap).

Portal persona: DB + auth mocked (no real DB). get_tenant_db /
get_current_user_with_refresh are imported into the router module's namespace and
resolved by FastAPI via Depends, so we override them through app.dependency_overrides
keyed by those EXACT symbols (mirrors test_beaming_target_map.py).

REDESIGN (9 processes, qid-only params, SQC dropped): machine LINKING is unused so
id_type 'mcid' carries NO params for any process; value_role 'actual' is EMPTY for every
process. Only a small set of qid standard/target params remain (constants.FINISHING_PARAMS):
  lapping    qid/standard = [std_prod_yds]
  cutting    qid/target   = [target_pcs]   (hemming/herackle same)
  sacksewing qid/standard = [pcs_per_bundle, bundles]
  balepress  qid/standard = [no_of_bales]
  damping / calendering / rolling = {}  (no params at all)
Quality applicability: cloth processes (damping/calendering/lapping/rolling) -> type 1;
bag processes (cutting/hemming/herackle/sacksewing) -> type 2; balepress -> None (BOTH).

Covered:
  * grid_params_for matrix contract (new qid params; mcid + actual always empty)
  * quality_type_for_process applicability (cloth=1, bag=2, balepress=None)
  * target_map_setup happy path + missing co_id 400 + invalid process 400
  * target_map_grid happy path (params match grid_params_for; rows + resolved cells)
  * target_map_grid missing required param 400, invalid enum 400, empty refs 200
  * target_map_bulk_save inserted/updated/cleared; invalid param 400; negative value 400
  * target_map_list happy path + empty
  * target_map_create / edit / delete happy paths + 404
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.finishing_target_map import (
    grid_params_for,
    quality_type_for_process,
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
    """Result object for resolve_finishing_grid_cell_query().fetchone().

    The resolver reads .value and .effective_date attributes (NOT _mapping).
    """
    cell = MagicMock()
    cell.value = value
    cell.effective_date = eff_date
    ex = MagicMock()
    ex.fetchone.return_value = cell
    return ex


# =============================================================================
# grid_params_for — pure-function matrix contract (no mocking)
# =============================================================================


class TestGridParamsForContract:
    """grid_params_for LOCKED CONTRACT — the single source of truth for the grid.

    mcid carries NO params for any process; value_role 'actual' is EMPTY everywhere.
    Only the qid standard/target params below remain.
    """

    # --- mcid is empty for EVERY process / value_role (machine linking unused) ---

    def test_mcid_empty_for_all_processes(self):
        for proc in (
            "damping", "calendering", "lapping", "rolling",
            "cutting", "hemming", "herackle", "sacksewing", "balepress",
        ):
            for role in ("standard", "target", "actual"):
                assert grid_params_for(proc, "mcid", role) == [], (proc, role)

    # --- actual is EMPTY for EVERY process / id_type (SQC dropped) ---

    def test_actual_empty_for_all_processes(self):
        for proc in (
            "damping", "calendering", "lapping", "rolling",
            "cutting", "hemming", "herackle", "sacksewing", "balepress",
        ):
            for id_type in ("mcid", "qid"):
                assert grid_params_for(proc, id_type, "actual") == [], (proc, id_type)

    # --- no-param processes: nothing under any dimension ---

    def test_damping_all_empty(self):
        assert grid_params_for("damping", "qid", "standard") == []
        assert grid_params_for("damping", "qid", "target") == []

    def test_calendering_all_empty(self):
        assert grid_params_for("calendering", "qid", "standard") == []
        assert grid_params_for("calendering", "qid", "target") == []

    def test_rolling_all_empty(self):
        assert grid_params_for("rolling", "qid", "standard") == []
        assert grid_params_for("rolling", "qid", "target") == []

    # --- the qid params that DO exist ---

    # Each process's qid params are available under BOTH standard and target.

    def test_lapping_qid_standard(self):
        assert grid_params_for("lapping", "qid", "standard") == ["std_prod_yds"]
        assert grid_params_for("lapping", "qid", "target") == ["std_prod_yds"]

    def test_cutting_qid_target(self):
        assert grid_params_for("cutting", "qid", "target") == ["target_pcs"]
        assert grid_params_for("cutting", "qid", "standard") == ["target_pcs"]

    def test_hemming_qid_target(self):
        assert grid_params_for("hemming", "qid", "target") == ["target_pcs"]
        assert grid_params_for("hemming", "qid", "standard") == ["target_pcs"]

    def test_herackle_qid_target(self):
        assert grid_params_for("herackle", "qid", "target") == ["target_pcs"]
        assert grid_params_for("herackle", "qid", "standard") == ["target_pcs"]

    def test_sacksewing_qid_standard(self):
        assert grid_params_for("sacksewing", "qid", "standard") == [
            "pcs_per_bundle",
            "bundles",
        ]
        assert grid_params_for("sacksewing", "qid", "target") == [
            "pcs_per_bundle",
            "bundles",
        ]

    def test_balepress_qid_standard(self):
        assert grid_params_for("balepress", "qid", "standard") == ["no_of_bales"]
        assert grid_params_for("balepress", "qid", "target") == ["no_of_bales"]

    def test_unknown_process_returns_empty(self):
        assert grid_params_for("bogus", "qid", "standard") == []

    def test_unknown_value_role_returns_empty(self):
        assert grid_params_for("lapping", "qid", "bogus") == []

    def test_unknown_id_type_returns_empty(self):
        assert grid_params_for("lapping", "bogus", "standard") == []


# =============================================================================
# quality_type_for_process — applicability filter contract
# =============================================================================


class TestQualityTypeForProcess:
    """Cloth processes -> 1, bag processes -> 2, balepress/unknown -> None (BOTH)."""

    def test_cloth_processes_type_1(self):
        for proc in ("damping", "calendering", "lapping", "rolling"):
            assert quality_type_for_process(proc) == 1, proc

    def test_bag_processes_type_2(self):
        for proc in ("cutting", "hemming", "herackle", "sacksewing"):
            assert quality_type_for_process(proc) == 2, proc

    def test_balepress_returns_none_both_qualities(self):
        assert quality_type_for_process("balepress") is None

    def test_unknown_returns_none(self):
        assert quality_type_for_process("bogus") is None


# =============================================================================
# target_map_setup
# =============================================================================


class TestTargetMapSetup:
    """GET /api/finishingTargetMap/target_map_setup"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_without_process_returns_enums_and_matrix(self):
        # No process -> machines/qualities empty, no DB calls for refs.
        response = client.get("/api/finishingTargetMap/target_map_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        # all NINE processes surfaced, including the new rolling/herackle/sacksewing.
        for proc in (
            "damping", "calendering", "lapping", "rolling",
            "cutting", "hemming", "herackle", "sacksewing", "balepress",
        ):
            assert proc in data["processes"], proc
        assert data["id_types"] == ["mcid", "qid"]
        assert "standard" in data["value_roles"]
        assert "target" in data["value_roles"]
        assert "actual" in data["value_roles"]
        # full FINISHING_PARAMS matrix surfaced for FE.
        assert data["params"]["lapping"]["qid"]["standard"] == ["std_prod_yds"]
        assert data["params"]["balepress"]["qid"]["standard"] == ["no_of_bales"]
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
        # Execute order in setup: machines (mcid) then qualities (qid).
        self._mock_session.execute.side_effect = [
            _machine_exec(machine_rows),
            _machine_exec(quality_rows),
        ]

        response = client.get(
            "/api/finishingTargetMap/target_map_setup?co_id=1&process=lapping"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["machines"][0]["machine_id"] == 9
        assert data["machines"][0]["mech_code"] == "LAP01"
        assert data["qualities"][0]["finishing_quality_id"] == 3
        assert data["qualities"][0]["fin_quality_code"] == "HC-10"

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/finishingTargetMap/target_map_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_invalid_process_returns_400(self):
        response = client.get(
            "/api/finishingTargetMap/target_map_setup?co_id=1&process=bogus"
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()


# =============================================================================
# target_map_grid
# =============================================================================


class TestTargetMapGrid:
    """GET /api/finishingTargetMap/target_map_grid"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_lapping_qid_standard_params_and_cells(self):
        """params == grid_params_for('lapping','qid','standard') == ['std_prod_yds'] and one
        quality row with the resolved cell. Execute order: quality refs list, then ONE
        resolve for std_prod_yds."""
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
            _machine_exec(quality_rows),
            _resolve_cell(4500.0),  # std_prod_yds
        ]

        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=lapping&id_type=qid&value_role=standard"
            "&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["std_prod_yds"]
        assert data["rows"][0]["ref_id"] == 3
        assert data["rows"][0]["ref_code"] == "HC-10"
        assert data["rows"][0]["cells"]["std_prod_yds"]["value"] == 4500.0
        assert data["rows"][0]["cells"]["std_prod_yds"]["is_exact"] is True

    def test_balepress_qid_standard_uses_quality_refs(self):
        """balepress/qid/standard -> params == ['no_of_bales'], refs are qualities (BOTH
        quality types since quality_type_for_process('balepress') is None)."""
        quality_rows = [
            _mock_row(
                {
                    "finishing_quality_id": 4,
                    "fin_quality_code": "BAG-A",
                    "fin_quality_name": "BagA",
                }
            ),
        ]
        self._mock_session.execute.side_effect = [
            _machine_exec(quality_rows),
            _resolve_cell(50.0),  # no_of_bales
        ]

        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=balepress&id_type=qid&value_role=standard"
            "&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["no_of_bales"]
        assert data["rows"][0]["ref_id"] == 4
        assert data["rows"][0]["ref_code"] == "BAG-A"
        assert data["rows"][0]["cells"]["no_of_bales"]["value"] == 50.0

    def test_cutting_qid_target_pcs(self):
        """cutting/qid/target -> params == ['target_pcs']."""
        quality_rows = [
            _mock_row(
                {
                    "finishing_quality_id": 7,
                    "fin_quality_code": "SK-A",
                    "fin_quality_name": "Sack-A",
                }
            ),
        ]
        self._mock_session.execute.side_effect = [
            _machine_exec(quality_rows),
            _resolve_cell(1200.0),  # target_pcs
        ]

        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=cutting&id_type=qid&value_role=target"
            "&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["target_pcs"]
        assert data["rows"][0]["cells"]["target_pcs"]["value"] == 1200.0

    def test_no_param_process_returns_empty_params(self):
        """damping has NO params at all -> params == [], no resolve calls (only refs)."""
        quality_rows = [
            _mock_row(
                {
                    "finishing_quality_id": 5,
                    "fin_quality_code": "HC-20",
                    "fin_quality_name": "Hessian-20",
                }
            ),
        ]
        self._mock_session.execute.side_effect = [_machine_exec(quality_rows)]

        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=damping&id_type=qid&value_role=standard"
            "&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == []
        # ref still listed, with no cells.
        assert data["rows"][0]["ref_id"] == 5
        assert data["rows"][0]["cells"] == {}

    def test_missing_effective_date_returns_400(self):
        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=lapping&id_type=qid&value_role=standard"
        )
        assert response.status_code == 400
        assert "effective_date" in response.json()["detail"].lower()

    def test_missing_process_returns_400(self):
        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&id_type=qid&value_role=standard&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()

    def test_invalid_id_type_returns_400(self):
        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=lapping&id_type=bogus&value_role=standard"
            "&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "id_type" in response.json()["detail"].lower()

    def test_invalid_value_role_returns_400(self):
        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=lapping&id_type=qid&value_role=bogus"
            "&effective_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "value_role" in response.json()["detail"].lower()

    def test_empty_refs_returns_empty_rows(self):
        self._mock_session.execute.side_effect = [_machine_exec([])]

        response = client.get(
            "/api/finishingTargetMap/target_map_grid"
            "?co_id=1&process=lapping&id_type=qid&value_role=standard"
            "&effective_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["params"] == ["std_prod_yds"]
        assert data["rows"] == []


# =============================================================================
# target_map_bulk_save
# =============================================================================


class TestTargetMapBulkSave:
    """POST /api/finishingTargetMap/target_map_bulk_save"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_inserted_updated_cleared_one_transaction(self):
        """One insert (no existing), one update (existing + value), one clear (existing +
        value=None) — all committed once. sacksewing/qid/standard allows
        pcs_per_bundle + bundles; the clear reuses pcs_per_bundle on a second ref."""
        existing_row = MagicMock()
        existing_row.finishing_target_map_id = 555

        no_existing = MagicMock()
        no_existing.fetchone.return_value = None
        found_for_update = MagicMock()
        found_for_update.fetchone.return_value = existing_row
        found_for_clear = MagicMock()
        found_for_clear.fetchone.return_value = existing_row

        # find(cell1), insert(cell1), find(cell2), update(cell2), find(cell3), clear(cell3)
        self._mock_session.execute.side_effect = [
            no_existing, MagicMock(),       # insert
            found_for_update, MagicMock(),  # update
            found_for_clear, MagicMock(),   # clear
        ]

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "process": "sacksewing",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 9, "param": "pcs_per_bundle", "value": 25.0},
                {"ref_id": 9, "param": "bundles", "value": 40.0},
                {"ref_id": 10, "param": "pcs_per_bundle", "value": None},
            ],
        }

        response = client.post(
            "/api/finishingTargetMap/target_map_bulk_save", json=payload
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["inserted"] == 1
        assert data["updated"] == 1
        assert data["cleared"] == 1
        self._mock_session.commit.assert_called_once()

        # INSERT bind params carry the exact key (incl. process).
        insert_params = self._mock_session.execute.call_args_list[1].args[1]
        assert insert_params["process"] == "sacksewing"
        assert insert_params["id_type"] == "qid"
        assert insert_params["value_role"] == "standard"
        assert insert_params["param"] == "pcs_per_bundle"
        assert insert_params["ref_id"] == 9
        assert insert_params["value"] == 25.0

    def test_invalid_param_for_combination_returns_400(self):
        """'std_prod_yds' belongs to lapping, NOT cutting (cutting/qid/target ==
        ['target_pcs']) -> 400, batch rolled back."""
        payload = {
            "co_id": 1,
            "process": "cutting",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "target",
            "cells": [
                {"ref_id": 9, "param": "std_prod_yds", "value": 100.0},
            ],
        }

        response = client.post(
            "/api/finishingTargetMap/target_map_bulk_save", json=payload
        )

        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_mcid_param_rejected_machine_unused(self):
        """mcid carries NO params for any process -> any cell under id_type='mcid' is
        rejected (machine linking unused)."""
        payload = {
            "co_id": 1,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "id_type": "mcid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 9, "param": "std_prod_yds", "value": 100.0},
            ],
        }
        response = client.post(
            "/api/finishingTargetMap/target_map_bulk_save", json=payload
        )
        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_negative_value_returns_400(self):
        payload = {
            "co_id": 1,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "standard",
            "cells": [
                {"ref_id": 9, "param": "std_prod_yds", "value": -5.0},
            ],
        }
        # find query may run before the negative check; benign result.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.post(
            "/api/finishingTargetMap/target_map_bulk_save", json=payload
        )

        assert response.status_code == 400
        assert "negative" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()

    def test_invalid_process_returns_400(self):
        payload = {
            "co_id": 1,
            "process": "bogus",
            "effective_date": "2026-06-21",
            "id_type": "qid",
            "value_role": "standard",
            "cells": [{"ref_id": 9, "param": "std_prod_yds", "value": 100.0}],
        }
        response = client.post(
            "/api/finishingTargetMap/target_map_bulk_save", json=payload
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()
        self._mock_session.commit.assert_not_called()


# =============================================================================
# target_map_list
# =============================================================================


class TestTargetMapList:
    """GET /api/finishingTargetMap/target_map_list"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_list_success(self):
        rows = [
            _mock_row(
                {
                    "finishing_target_map_id": 11,
                    "co_id": 1,
                    "branch_id": 2,
                    "process": "lapping",
                    "effective_date": "2026-06-21",
                    "ref_id": 3,
                    "id_type": "qid",
                    "value_role": "standard",
                    "param": "std_prod_yds",
                    "value": 4500.0,
                    "active": 1,
                    "ref_code": "HC-10",
                    "ref_name": "Hessian-10",
                }
            ),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get("/api/finishingTargetMap/target_map_list?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["finishing_target_map_id"] == 11
        assert data[0]["process"] == "lapping"
        assert data[0]["param"] == "std_prod_yds"
        assert data[0]["value"] == 4500.0

    def test_list_empty(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get("/api/finishingTargetMap/target_map_list?co_id=1")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_list_missing_co_id_returns_400(self):
        response = client.get("/api/finishingTargetMap/target_map_list")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


# =============================================================================
# target_map_create / edit / delete
# =============================================================================


class TestTargetMapCreate:
    """POST /api/finishingTargetMap/target_map_create"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_create_success(self):
        result = MagicMock()
        result.lastrowid = 77
        self._mock_session.execute.return_value = result

        payload = {
            "co_id": 1,
            "branch_id": 2,
            "process": "lapping",
            "effective_date": "2026-06-21",
            "ref_id": 3,
            "id_type": "qid",
            "value_role": "standard",
            "param": "std_prod_yds",
            "value": 4500.0,
        }
        response = client.post(
            "/api/finishingTargetMap/target_map_create", json=payload
        )

        assert response.status_code == 200
        assert response.json()["data"]["finishing_target_map_id"] == 77
        self._mock_session.commit.assert_called_once()

    def test_create_invalid_param_for_combination_returns_400(self):
        # 'std_prod_yds' not valid for cutting/qid/target (cross-dimension guard).
        payload = {
            "co_id": 1,
            "process": "cutting",
            "effective_date": "2026-06-21",
            "ref_id": 3,
            "id_type": "qid",
            "value_role": "target",
            "param": "std_prod_yds",
            "value": 100.0,
        }
        response = client.post(
            "/api/finishingTargetMap/target_map_create", json=payload
        )
        assert response.status_code == 400
        assert "invalid param" in response.json()["detail"].lower()

    def test_create_invalid_process_returns_400(self):
        payload = {
            "co_id": 1,
            "process": "bogus",
            "effective_date": "2026-06-21",
            "ref_id": 3,
            "id_type": "qid",
            "value_role": "standard",
            "param": "std_prod_yds",
            "value": 100.0,
        }
        response = client.post(
            "/api/finishingTargetMap/target_map_create", json=payload
        )
        assert response.status_code == 400
        assert "process" in response.json()["detail"].lower()


class TestTargetMapEditDelete:
    """PUT/DELETE /api/finishingTargetMap/target_map_{edit,delete}/{id}"""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_edit_success(self):
        existing = _mock_row({"co_id": 1})
        find_exec = MagicMock()
        find_exec.fetchone.return_value = existing
        # find(existing) then UPDATE.
        self._mock_session.execute.side_effect = [find_exec, MagicMock()]

        response = client.put(
            "/api/finishingTargetMap/target_map_edit/11?co_id=1",
            json={"value": 5000.0},
        )

        assert response.status_code == 200
        assert response.json()["data"]["finishing_target_map_id"] == 11
        self._mock_session.commit.assert_called_once()

    def test_edit_not_found_returns_404(self):
        find_exec = MagicMock()
        find_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = find_exec

        response = client.put(
            "/api/finishingTargetMap/target_map_edit/999?co_id=1",
            json={"value": 5000.0},
        )

        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()

    def test_edit_foreign_co_id_returns_404(self):
        existing = _mock_row({"co_id": 99})  # belongs to a different company
        find_exec = MagicMock()
        find_exec.fetchone.return_value = existing
        self._mock_session.execute.return_value = find_exec

        response = client.put(
            "/api/finishingTargetMap/target_map_edit/11?co_id=1",
            json={"value": 5000.0},
        )

        assert response.status_code == 404

    def test_delete_success(self):
        existing = _mock_row({"co_id": 1})
        find_exec = MagicMock()
        find_exec.fetchone.return_value = existing
        self._mock_session.execute.side_effect = [find_exec, MagicMock()]

        response = client.delete(
            "/api/finishingTargetMap/target_map_delete/11?co_id=1"
        )

        assert response.status_code == 200
        assert response.json()["data"]["message"] == "Deleted"
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found_returns_404(self):
        find_exec = MagicMock()
        find_exec.fetchone.return_value = None
        self._mock_session.execute.return_value = find_exec

        response = client.delete(
            "/api/finishingTargetMap/target_map_delete/999?co_id=1"
        )

        assert response.status_code == 404

    def test_delete_missing_co_id_returns_400(self):
        response = client.delete("/api/finishingTargetMap/target_map_delete/11")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
