"""Behavior tests for the weaving day-slice read endpoints (Page C reads).

The SQL bodies of get_weaving_entries_by_date_query / get_weaving_plan_driver_query are
being rewritten (view -> inline day-scoped SELECT via weaving_day_slice_sql). These tests
deliberately do NOT assert on SQL text for the endpoint behavior â€” they pin the ROUTER
contract (params in, {'data': ...} out, 400s) which must survive the rewrite unchanged.

A separate SQL-sanity class pins the one architectural invariant: the rendered SQL must
not read vw_weaving_daily / vw_weaving_pick_act, must bind :co_id/:tran_date, and the
entries query must ORDER BY. No formula text is asserted.

Portal persona: DB + auth mocked via app.dependency_overrides keyed by the symbols
imported into src.juteProduction.weaving_entry (repo pattern, see test_weaving_entry.py).
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.weaving_entry import (
    get_tenant_db,
    get_current_user_with_refresh,
)
from src.juteProduction.weaving_query import (
    get_weaving_entries_by_date_query,
    get_weaving_entry_inputs_query,
    get_weaving_plan_driver_query,
)

client = TestClient(app)


import pytest as _pytest
from unittest.mock import patch as _patch


@_pytest.fixture(autouse=True)
def _bypass_weaving_lock():
    """Locking is tested in test_weaving_lock.py; bypass the guard here so the legacy
    execute-order mocks (which predate the Process lock lookup) stay aligned."""
    with _patch("src.juteProduction.weaving_entry.require_edit_if_locked"), \
         _patch("src.juteProduction.weaving_entry.is_unit_locked", return_value=False), \
         _patch("src.juteProduction.weaving_entry.flag_reprocess_if_locked"), \
         _patch("src.juteProduction.weaving_entry._flag_reprocess_units"):
        yield


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _fetchall_exec(rows):
    ex = MagicMock()
    ex.fetchall.return_value = rows
    return ex


def _resolve_spell_exec(spell_id=1):
    """execute() result for _resolve_spell_id (.fetchone().spell_id)."""
    ex = MagicMock()
    r = MagicMock()
    r.spell_id = spell_id
    ex.fetchone.return_value = r
    return ex


class _MockedDb:
    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()


# =============================================================================
# GET /api/weavingProd/entries_by_date
# =============================================================================


class TestEntriesByDateDaySlice(_MockedDb):
    def _entry_row(self, **over):
        base = {
            "weaving_daily_id": 10, "co_id": 1, "branch_id": 2,
            "tran_date": "2026-06-21", "spell_id": 1, "machine_id": 7,
            "weaving_quality_id": 5, "cuts": 10, "close_jugar": 12.0,
            "less_production": 0.0, "open_jugar": 0.0, "jugar": 172.0,
            "production_yds": 1075.0, "production_kg": 304.76,
            "efficiency": 95.0,
        }
        base.update(over)
        return _mock_row(base)

    def test_success_data_shape(self):
        self._mock_session.execute.return_value = _fetchall_exec([self._entry_row()])
        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["weaving_daily_id"] == 10
        assert data[0]["production_yds"] == 1075.0
        assert data[0]["jugar"] == 172.0
        assert data[0]["tran_date"] == "2026-06-21"

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingProd/entries_by_date?tran_date=2026-06-21")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/entries_by_date?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()

    def test_invalid_tran_date_returns_400(self):
        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=not-a-date"
        )
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()

    def test_spell_resolution_path(self):
        """spell code param -> extra resolve execute, then the day query with spell_id."""
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(spell_id=3),
            _fetchall_exec([self._entry_row(spell_id=3)]),
        ]
        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=2026-06-21&spell=A2"
        )
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
        # Second execute is the day query; its bind params carry the resolved spell_id.
        _, params = self._mock_session.execute.call_args_list[1][0]
        assert params["spell_id"] == 3

    def test_branch_id_passthrough(self):
        self._mock_session.execute.return_value = _fetchall_exec([])
        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=2026-06-21&branch_id=2"
        )
        assert response.status_code == 200
        _, params = self._mock_session.execute.call_args[0]
        assert params["branch_id"] == 2
        assert params["co_id"] == 1

    def test_empty_day_returns_empty_data(self):
        self._mock_session.execute.return_value = _fetchall_exec([])
        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        assert response.json() == {"data": []}


# =============================================================================
# GET /api/weavingProd/planning_grid
# =============================================================================


class TestPlanningGridDaySlice(_MockedDb):
    def _driver_row(self, **over):
        base = {
            "weaving_quality_map_id": 50, "machine_id": 7, "spell_id": 1,
            "spell_code": "A1", "mech_code": "L01", "machine_name": "Loom-1",
            "line_no": "1", "branch_id": 2, "item_id": 10, "item_code": "JC",
            "item_name": "Jute Cloth", "weaving_quality_id": 5,
            "weaving_quality_code": "Q5", "weaving_quality_name": "Red",
            "finished_length": 100.0, "ozs_yds": 10.0, "std_ozs_yds": 10.0,
            "no_of_jugar_per_cut": 16.0, "is_composite": 0,
            "weaving_daily_id": 10, "cuts": 10.0, "close_jugar": 12.0,
            "less_production": 0.0, "open_jugar": 0.0, "jugar": 172.0,
            "std_speed": 160.0, "act_speed": 155.0, "std_picks": 9.0,
            "act_picks": 9.5, "std_eff": 85.0, "target_eff": 90.0,
            "eff_speed": 150.0, "eff_picks": 9.2, "working_hours": 8.0,
            "production_yds": 1075.0, "production_kg": 304.76,
            "production_mt": 0.305, "std_prod_yds": 1200.0,
            "target_prod_yds": 1080.0, "efficiency": 89.58,
            "std_prod_kg": 340.0, "target_kg": 306.0,
        }
        base.update(over)
        return _mock_row(base)

    def test_success_shape(self):
        self._mock_session.execute.return_value = _fetchall_exec([self._driver_row()])
        response = client.get(
            "/api/weavingProd/planning_grid?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert set(payload.keys()) == {"rows", "shift_rollup"}
        r = payload["rows"][0]
        assert r["weaving_quality_map_id"] == 50
        assert r["shift_bucket"] == "A"
        assert r["production_yds"] == 1075.0
        # rollup: SUM(production_yds)/SUM(std_prod_yds)*100, never avg of effs.
        assert payload["shift_rollup"][0]["efficiency"] == round(
            1075.0 / 1200.0 * 100, 2
        )

    def test_null_view_columns_coalesced_to_zero(self):
        """Mapped loom with no entry: all day-slice columns NULL -> router _f() coalesces
        the numeric ones to 0.0 and weaving_daily_id stays None."""
        null_cols = {
            "weaving_daily_id": None, "cuts": None, "close_jugar": None,
            "less_production": None, "open_jugar": None, "jugar": None,
            "std_speed": None, "act_speed": None, "std_picks": None,
            "act_picks": None, "std_eff": None, "target_eff": None,
            "eff_speed": None, "eff_picks": None, "working_hours": None,
            "production_yds": None, "production_kg": None, "production_mt": None,
            "std_prod_yds": None, "target_prod_yds": None, "efficiency": None,
            "std_prod_kg": None, "target_kg": None,
        }
        self._mock_session.execute.return_value = _fetchall_exec(
            [self._driver_row(**null_cols)]
        )
        response = client.get(
            "/api/weavingProd/planning_grid?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        r = response.json()["data"]["rows"][0]
        assert r["weaving_daily_id"] is None
        for col in (
            "cuts", "close_jugar", "less_production", "open_jugar", "jugar",
            "std_speed", "act_speed", "std_picks", "act_picks", "std_eff",
            "target_eff", "eff_speed", "eff_picks", "working_hours",
            "production_yds", "production_kg", "production_mt", "std_prod_yds",
            "target_prod_yds", "efficiency", "std_prod_kg", "target_kg",
            "std_prod_eff",
        ):
            assert r[col] == 0.0, col
        # zero std_prod_yds -> rollup efficiency 0.0, no ZeroDivision.
        assert response.json()["data"]["shift_rollup"][0]["efficiency"] == 0.0

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingProd/planning_grid?tran_date=2026-06-21")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/planning_grid?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()


# =============================================================================
# GET /api/weavingProd/entry_inputs_by_date â€” LIGHT table-direct entry-tab read
# =============================================================================


class TestEntryInputsByDate(_MockedDb):
    def _inputs_row(self, **over):
        base = {
            "weaving_daily_id": 10, "co_id": 1, "branch_id": 2,
            "tran_date": "2026-06-21", "spell_id": 1, "spell_code": "A1",
            "machine_id": 7, "mech_code": "L001", "machine_name": "Loom 1",
            "weaving_quality_id": 5, "weaving_quality_code": "Q1",
            "weaving_quality_name": "Hessian", "beam_no": "B-9",
            "cuts": 10, "close_jugar": 12.0, "less_production": 0.0,
            "jpc": 18.0, "fl": 105.0, "ozs_yds": 8.0, "open_jugar": 4.0,
        }
        base.update(over)
        return _mock_row(base)

    def test_success_data_shape_with_jpc(self):
        self._mock_session.execute.return_value = _fetchall_exec([self._inputs_row()])
        response = client.get(
            "/api/weavingProd/entry_inputs_by_date?co_id=1&tran_date=2026-06-21"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["jpc"] == 18.0  # FE Tot.Jugar preview field
        assert data[0]["open_jugar"] == 4.0
        assert data[0]["cuts"] == 10.0

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingProd/entry_inputs_by_date?tran_date=2026-06-21")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/entry_inputs_by_date?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()

    def test_light_query_has_no_heavy_probes(self):
        # The whole point: no view, no standards/pick/stoppage probes â€” table-direct.
        sql = str(get_weaving_entry_inputs_query())
        assert "vw_weaving_daily" not in sql
        assert "vw_weaving_pick_act" not in sql
        assert "jute_prod_weaving_target_map" not in sql
        assert "jute_sqc_weaving_pick" not in sql
        assert "jute_prod_stoppage_hours" not in sql
        assert "AS jpc" in sql
        assert ":co_id" in sql and ":tran_date" in sql


# =============================================================================
# SQL sanity â€” architectural invariant only (no formula text pinned)
# =============================================================================


class TestDaySliceSqlSanity:
    def test_entries_query_is_view_free_and_parameterized(self):
        sql = str(get_weaving_entries_by_date_query())
        assert "vw_weaving_daily" not in sql
        assert "vw_weaving_pick_act" not in sql
        assert ":co_id" in sql
        assert ":tran_date" in sql
        assert "ORDER BY" in sql.upper()

    def test_plan_driver_query_is_view_free_and_parameterized(self):
        sql = str(get_weaving_plan_driver_query())
        assert "vw_weaving_daily" not in sql
        assert "vw_weaving_pick_act" not in sql
        assert ":co_id" in sql
        assert ":tran_date" in sql

    def test_day_slice_builder_is_view_free_and_parameterized(self):
        from src.juteProduction.weaving_query import weaving_day_slice_sql

        sql = weaving_day_slice_sql()
        assert isinstance(sql, str)
        assert "vw_weaving_daily" not in sql
        assert "vw_weaving_pick_act" not in sql
        assert ":co_id" in sql
        assert ":tran_date" in sql
        assert ":branch_id" in sql

    def test_day_slice_builder_branch_filter_toggle(self):
        # Plan driver embeds the slice branch-UNfiltered (old view-join semantics);
        # branch scope there is driver-side d.branch_id only.
        from src.juteProduction.weaving_query import weaving_day_slice_sql

        assert ":branch_id" not in weaving_day_slice_sql(include_branch_filter=False)
