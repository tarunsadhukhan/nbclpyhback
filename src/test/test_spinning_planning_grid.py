"""Tests for Spinning / Doff Production Entry + Planning-grid endpoints.

Tests for src/juteProduction/spinning_entry.py (router prefix /api/spinningProd).

Portal persona: every endpoint depends on get_tenant_db (tenant session) and
get_current_user_with_refresh (auth). Both are mocked here -- NO real DB is
touched.

Mocking note: the spinning router is mounted on the shared main app, so auth +
DB are swapped via ``app.dependency_overrides`` (the working pattern in
src/test/test_yarn_quality.py). ``@patch("...spinning_entry.get_tenant_db")``
does NOT work for an already-registered FastAPI dependency -- FastAPI captured
the original callable at import time, so a later module-attribute patch is never
consulted (it would fall through to real auth -> 403). planning_grid is now
slice-driven (one day-slice execute, no per-row resolvers), so its tests mock the
slice/frozen-log execute result rather than patching resolver functions.

The mocked session is a MagicMock whose db.execute(...).fetchall()/.fetchone()/
.scalar() returns rows whose ``._mapping`` is a dict (attributes mirror it too,
for the helpers that read ``row.col``). token_data is {"user_id": 1}.

Per endpoint we cover (a) a 200 success carrying a "data" key and (b) for GET
setup/list endpoints, missing co_id -> 400. The planning-grid success test also
asserts the payload exposes "rows" and "shift_rollup".
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.main import app

client = TestClient(app)

PREFIX = "/api/spinningProd"


def _mock_row(mapping: dict):
    """A result row whose ._mapping is a dict and whose attributes mirror it."""
    row = MagicMock()
    row._mapping = mapping
    for k, v in mapping.items():
        setattr(row, k, v)
    return row


class _Base:
    """Override auth + tenant DB for every test; expose a fresh mock session."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self.mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self.mock_session
        yield
        app.dependency_overrides.clear()


# =============================================================================
# Stage 1 -- doff_entry_create_setup (GET setup)
# =============================================================================


class TestDoffEntryCreateSetup(_Base):
    def test_success_returns_data(self):
        machine_row = _mock_row(
            {
                "machine_id": 10,
                "machine_name": "Frame 10",
                "mech_code": "F10",
                "branch_id": 1,
                "bobbin_weight": 0.25,
                "no_of_spindle": 120,
            }
        )
        spell_row = _mock_row(
            {
                "spell_code": "A1",
                "spell_name": "Morning",
                "spell_id": 1,
                "working_hours": 8.0,
            }
        )
        trolly_row = _mock_row(
            {
                "trolly_id": 5,
                "trolly_name": "T5",
                "trolly_weight": 12.0,
                "bucket_weight": 1.5,
            }
        )
        quality_row = _mock_row(
            {
                "item_id": 7,
                "item_code": "Q7",
                "item_name": "Quality 7",
                "std_count": 12.0,
                "std_mr_pct": 13.75,
            }
        )

        # execute order: batch bobbin (.fetchall, one row per machine — replaces the
        # per-machine resolve loop), machines (.fetchall), spells, trollies, yarn_items.
        bobbin_res = MagicMock()
        bobbin_res.fetchall.return_value = [
            _mock_row({"machine_id": 10, "bobbin_weight": 0.25})
        ]
        machines_res = MagicMock()
        machines_res.fetchall.return_value = [machine_row]
        spells_res = MagicMock()
        spells_res.fetchall.return_value = [spell_row]
        trollies_res = MagicMock()
        trollies_res.fetchall.return_value = [trolly_row]
        quality_res = MagicMock()
        quality_res.fetchall.return_value = [quality_row]
        self.mock_session.execute.side_effect = [
            bobbin_res,
            machines_res,
            spells_res,
            trollies_res,
            quality_res,
        ]

        resp = client.get(f"{PREFIX}/doff_entry_create_setup?co_id=1&branch_id=1")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["machines"][0]["machine_id"] == 10
        assert data["machines"][0]["bobbin_weight"] == 0.25
        assert data["spells"][0]["spell_code"] == "A1"
        assert data["trollies"][0]["bucket_weight"] == 1.5
        assert data["yarn_items"][0]["item_id"] == 7

    def test_missing_co_id_returns_400(self):
        resp = client.get(f"{PREFIX}/doff_entry_create_setup")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()


# =============================================================================
# Stage 1 -- doff_machine_prev_state (GET)
# =============================================================================


class TestDoffMachinePrevState(_Base):
    def test_success_returns_data(self):
        spell_row = _mock_row({"spell_id": 1})
        running_row = _mock_row({"total_net": 42.5, "doff_count": 3})

        # 1) _machine_branch_co (feeds spell scope); 2) branch-scoped spell
        # resolve; 3) running total; 4) _spell_start + 5) mapper as-of
        # (tran_date is backdated -> mapped item resolves from the mapper log;
        # nothing mapped here). No trolly_id param, so tare compute is skipped.
        self.mock_session.execute.return_value.fetchone.side_effect = [
            _mock_row({"branch_id": 1, "co_id": 1}),
            spell_row,
            running_row,
            _mock_row({"starting_time": "06:00:00"}),
            _mock_row({"item_id": None, "item_name": None}),
        ]

        resp = client.get(
            f"{PREFIX}/doff_machine_prev_state"
            "?co_id=1&machine_id=10&tran_date=2026-06-13&spell=A1"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["running_total_net"] == 42.5
        assert data["next_doff_no"] == 4
        assert data["tare"] == 0.0

    def test_missing_co_id_returns_400(self):
        resp = client.get(
            f"{PREFIX}/doff_machine_prev_state"
            "?machine_id=10&tran_date=2026-06-13&spell=A1"
        )
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_machine_params_returns_400(self):
        # co_id present but machine_id/tran_date/spell missing.
        resp = client.get(f"{PREFIX}/doff_machine_prev_state?co_id=1")
        assert resp.status_code == 400


# =============================================================================
# Stage 1 -- doff_entry_create (POST)
# =============================================================================


class TestDoffEntryCreate(_Base):
    def test_success_returns_data(self):
        spell_row = _mock_row({"spell_id": 1})
        machine_row = _mock_row({"branch_id": 1, "co_id": 1})
        trolly_row = _mock_row(
            {"trolly_id": 5, "trolly_weight": 12.0, "busket_weight": 1.0,
             "branch_id": 1, "machine_type_name": "Spinning"}
        )
        # resolve_param row for the standard bobbin_wt (jute_prod_spng_target_map).
        bobbin_row = _mock_row({"value": 0.5})

        # execute order: 1) _machine_branch_co (.fetchone, feeds spell scope);
        # 2) branch-scoped spell resolve; 3) _fetch_trolly (scope-checked);
        # 4) resolve bobbin via resolve_param; 5) lock probe (.fetchone ->
        # None = unlocked); 6) INSERT (.lastrowid) (item_id supplied ->
        # 'manual', no helper/mapper lookup); 7) flag_reprocess_if_locked.
        # tare = 12.0 + 1.0 + 0.5 = 13.5 ; gross 40 -> net 26.5 (within 5..60).
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls <= 4:
                r.fetchone.return_value = [machine_row, spell_row, trolly_row,
                                           bobbin_row][execute_side_effect.calls - 1]
            elif execute_side_effect.calls == 5:
                r.fetchone.return_value = None  # lock probe -> unlocked
            else:
                r.lastrowid = 999
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-13",
            "spell": "A1",
            "machine_id": 10,
            "trolly_id": 5,
            "item_id": 7,
            "gross_weight": 40.0,
        }
        resp = client.post(f"{PREFIX}/doff_entry_create", json=payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["daily_doff_tbl_id"] == 999
        assert data["net_weight"] == 26.5
        assert data["tare_weight"] == 13.5

    def test_missing_required_body_field_returns_422(self):
        # Omit gross_weight (required) -> pydantic rejects with 422.
        payload = {
            "co_id": 1,
            "tran_date": "2026-06-13",
            "spell": "A1",
            "machine_id": 10,
            "trolly_id": 5,
        }
        resp = client.post(f"{PREFIX}/doff_entry_create", json=payload)
        assert resp.status_code == 422


# =============================================================================
# Stage 1 -- doff_entries_by_date (GET list)
# =============================================================================


class TestDoffEntriesByDate(_Base):
    def test_success_returns_data(self):
        entry_row = _mock_row(
            {
                "daily_doff_tbl_id": 1,
                "doff_date": "2026-06-13",
                "gross_weight": 40.0,
                "tare_weight": 13.5,
                "net_weight": 26.5,
            }
        )
        # No spell param -> _resolve_spell_id is skipped; single fetchall.
        self.mock_session.execute.return_value.fetchall.return_value = [entry_row]

        resp = client.get(
            f"{PREFIX}/doff_entries_by_date?co_id=1&tran_date=2026-06-13"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"][0]["net_weight"] == 26.5
        assert body["data"][0]["doff_date"] == "2026-06-13"

    def test_empty_results_returns_data_list(self):
        self.mock_session.execute.return_value.fetchall.return_value = []

        resp = client.get(
            f"{PREFIX}/doff_entries_by_date?co_id=1&tran_date=2026-06-13"
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_missing_co_id_returns_400(self):
        resp = client.get(f"{PREFIX}/doff_entries_by_date?tran_date=2026-06-13")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        resp = client.get(f"{PREFIX}/doff_entries_by_date?co_id=1")
        assert resp.status_code == 400
        assert "tran_date" in resp.json()["detail"].lower()


# =============================================================================
# Stage 1 -- doff_entry_edit (PUT) / doff_entry_delete (DELETE)
# =============================================================================


class TestDoffEntryEdit(_Base):
    def test_success_returns_data(self):
        existing = _mock_row(
            {
                "daily_doff_tbl_id": 1,
                "mc_id": 10,
                "trolly_id": 5,
                "gross_weight": 40.0,
                "item_id": 7,
                "doff_date": "2026-06-13",
                "spell": 1,
                "branch_id": 1,
            }
        )
        machine_row = _mock_row({"branch_id": 1, "co_id": 1})
        trolly_row = _mock_row(
            {"trolly_id": 5, "trolly_weight": 12.0, "busket_weight": 1.0,
             "branch_id": 1, "machine_type_name": "Spinning"}
        )
        # resolve_param row for the standard bobbin_wt (jute_prod_spng_target_map).
        bobbin_row = _mock_row({"value": 0.5})

        # fetchone order: 1) existing lookup; 2) _machine_branch_co (7.4 co
        # derivation); 3) lock probe (-> None = unlocked); 4) _compute_doff_tare
        # -> _fetch_trolly; 5) resolve bobbin via resolve_param.
        # (UPDATE + flag_reprocess_if_locked do not call fetchone.)
        self.mock_session.execute.return_value.fetchone.side_effect = [
            existing,
            machine_row,
            None,
            trolly_row,
            bobbin_row,
        ]

        # gross_weight 50 -> tare 13.5 -> net 36.5 (within range)
        resp = client.put(
            f"{PREFIX}/doff_entry_edit/1?co_id=1",
            json={"gross_weight": 50.0},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["daily_doff_tbl_id"] == 1
        assert data["net_weight"] == 36.5

    def test_not_found_returns_404(self):
        self.mock_session.execute.return_value.fetchone.return_value = None

        resp = client.put(
            f"{PREFIX}/doff_entry_edit/999?co_id=1",
            json={"gross_weight": 50.0},
        )
        assert resp.status_code == 404


class TestDoffEntryDelete(_Base):
    def test_success_returns_data(self):
        existing = _mock_row(
            {"daily_doff_tbl_id": 1, "mc_id": 10, "doff_date": "2026-06-13",
             "spell": 1, "branch_id": 1}
        )
        machine_row = _mock_row({"branch_id": 1, "co_id": 1})

        # execute order: 1) existing lookup (.fetchone); 2) _machine_branch_co
        # (7.4 co derivation); 3) lock probe (.fetchone -> None = unlocked);
        # 4) UPDATE active=0; 5) flag_reprocess_if_locked.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = existing
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = machine_row
            elif execute_side_effect.calls == 3:
                r.fetchone.return_value = None  # lock probe -> unlocked
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.delete(f"{PREFIX}/doff_entry_delete/1?co_id=1")
        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == "Deleted"

    def test_not_found_returns_404(self):
        self.mock_session.execute.return_value.fetchone.return_value = None

        resp = client.delete(f"{PREFIX}/doff_entry_delete/999?co_id=1")
        assert resp.status_code == 404

    def test_missing_co_id_returns_400(self):
        resp = client.delete(f"{PREFIX}/doff_entry_delete/1")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()


# =============================================================================
# Stage 1 -- doff_dedup_run (POST)
# =============================================================================


class TestDoffDedupRun(_Base):
    def test_success_returns_data(self):
        spell_row = _mock_row({"spell_id": 1})

        # execute order (W10 exact-only dedup, D8 confirm flow):
        # 1) resolve_spell_id; 2) exact-duplicate candidate SELECT (.fetchall);
        # 3) lock probe (confirm path); 4) deactivate UPDATE;
        # 5) flag_reprocess_if_locked.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row  # resolve_spell_id
            elif execute_side_effect.calls == 2:
                r.fetchall.return_value = [
                    _mock_row({"daily_doff_tbl_id": 11, "mc_id": 5, "keep_id": 10,
                               "gross_weight": 50.0, "tare_weight": 12.5,
                               "net_weight": 37.5}),
                    _mock_row({"daily_doff_tbl_id": 12, "mc_id": 5, "keep_id": 10,
                               "gross_weight": 50.0, "tare_weight": 12.5,
                               "net_weight": 37.5}),
                ]
            elif execute_side_effect.calls == 3:
                r.fetchone.return_value = None  # lock probe -> unlocked
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.post(
            f"{PREFIX}/doff_dedup_run",
            json={"co_id": 1, "tran_date": "2026-06-13", "spell": "A1",
                  "confirm": True},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["deactivated"] == 2
        assert resp.json()["data"]["deactivated_ids"] == [11, 12]


# =============================================================================
# Stage 2 -- frame_map_get (GET) / frame_map_save (POST) / frame_map_mapped (POST)
# =============================================================================


class TestFrameMapGet(_Base):
    def test_success_returns_data(self):
        spell_row = _mock_row({"spell_id": 1})
        frame_row = _mock_row(
            {
                "machine_id": 10,
                "mech_code": "F10",
                "machine_name": "Frame 10",
                # Nothing saved for this spell today; the frame's most recent saved
                # mapping (any spell/date) is the draft suggestion.
                "item_id": None,
                "item_code": None,
                "item_name": None,
                "prev_item_id": 7,
                "prev_item_name": "Quality 7",
                "prev_date": "2026-06-12",
            }
        )

        # execute order (draft model, no auto-persist): 1) resolve_spell_id .fetchone;
        # 2) frame map .fetchall; 3) last-updated .scalar.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row
            elif execute_side_effect.calls == 2:
                r.fetchall.return_value = [frame_row]
            else:
                r.scalar.return_value = "2026-06-16 14:32:00"
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.get(
            f"{PREFIX}/frame_map_get?co_id=1&tran_date=2026-06-13&spell=A1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["data"][0]["machine_id"] == 10
        assert body["data"][0]["item_id"] is None
        assert body["data"][0]["prev_item_id"] == 7
        assert body["data"][0]["prev_item_name"] == "Quality 7"
        assert body["data"][0]["prev_date"] == "2026-06-12"
        assert body["last_updated"] == "2026-06-16 14:32:00"

    def test_missing_co_id_returns_400(self):
        resp = client.get(f"{PREFIX}/frame_map_get?tran_date=2026-06-13&spell=A1")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_date_spell_returns_400(self):
        resp = client.get(f"{PREFIX}/frame_map_get?co_id=1")
        assert resp.status_code == 400


class TestFrameMapSave(_Base):
    def test_success_returns_data(self):
        spell_row = _mock_row({"spell_id": 1})

        # 1) resolve spell .fetchone; 2) lock probe .fetchone -> None (unlocked);
        # 3) _spell_name (INSERT writes the spell NAME, derived server-side);
        # 4) active-row lookup -> None (insert path); 5) INSERT;
        # 6) flag_reprocess_if_locked.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = None  # lock probe -> unlocked
            elif execute_side_effect.calls == 3:
                r.fetchone.return_value = _mock_row({"spell_name": "Morning"})
            elif execute_side_effect.calls == 4:
                r.fetchone.return_value = None  # no existing -> INSERT
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-13",
            "spell": "A1",
            "entries": [{"machine_id": 10, "item_id": 7}],
        }
        resp = client.post(f"{PREFIX}/frame_map_save", json=payload)
        assert resp.status_code == 200
        assert resp.json()["data"]["saved"] == 1
        assert resp.json()["data"]["skipped"] == 0


class TestFrameMapMapped(_Base):
    def test_success_returns_data(self):
        # frame_map_mapped is now a thin delegate over the doff_sync internals
        # (fill mode, both targets). Execute order: 1) resolve_spell_id; 2) lock
        # probe; 3) _spell_start; 4) quality stamp (mapper as-of, rowcount);
        # 5) _spell_name; 6) operator candidates (.fetchall, none here);
        # 7) scope summary (.fetchall); 8) bobbin batch (.fetchall);
        # 9) flag_reprocess_if_locked.
        spell_row = _mock_row({"spell_id": 1})
        spell_name_row = _mock_row({"spell_name": "Morning"})

        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = None  # lock probe -> unlocked
            elif execute_side_effect.calls == 3:
                r.fetchone.return_value = _mock_row({"starting_time": "06:00:00"})
            elif execute_side_effect.calls == 4:
                r.rowcount = 4  # quality stamped
            elif execute_side_effect.calls == 5:
                r.fetchone.return_value = spell_name_row
            else:
                r.fetchall.return_value = []  # candidates / scope / bobbin
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-13",
            "spell": "A1",
        }
        resp = client.post(f"{PREFIX}/frame_map_mapped", json=payload)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["quality_stamped"] == 4
        assert data["operator_stamped"] == 0  # no attendance candidates mocked
        assert "exceptions" in data


# =============================================================================
# Planning grid (GET) — slice-driven + lock-gated (planning_grid_save removed)
# =============================================================================


def _slice_row_mapping():
    """A day-slice result row carrying every planning-grid alias the handler reads."""
    return {
        "spell_id": 1,
        "spell_code": "A1",
        "shift_bucket": "A",
        "machine_id": 10,
        "mech_code": "F10",
        "machine_name": "Frame 10",
        "branch_id": 1,
        "item_id": 7,
        "item_code": "Q7",
        "item_name": "Quality 7",
        "spindles": 120,
        "minutes": 480,
        "act_count": 12.5,
        "std_count": 12.0,
        "std_speed": 4000.0,
        "actual_speed": 4100.0,
        "target_speed": 4200.0,
        "std_tpi": 5.0,
        "actual_tpi": 5.1,
        "target_tpi": 5.2,
        "std_eff": 85.0,
        "target_eff": 90.0,
        "p100prod": 400.0,
        "std_prod": 340.0,
        "target_prod": 360.0,
        "act_prod_doff": 300.0,
        "winding_total": 280.0,
        "act_prod_wind": 280.0,
        "eff_doff": 75.0,
        "eff_winding": 70.0,
    }


class TestPlanningGrid(_Base):
    def test_success_returns_rows_and_shift_rollup(self):
        # Unlocked path: ONE day-slice execute whose rows already carry every grid
        # alias (no per-row resolvers, no view reads), preceded by a lock probe that
        # returns None. spell=A1 so the lock switch runs; None -> live slice.
        spell_row = _mock_row({"spell_id": 1})
        slice_row = _mock_row(_slice_row_mapping())

        # execute order: 1) resolve_spell_id .fetchone; 2) lock probe .fetchone ->
        # None (unlocked); 3) day-slice .fetchall.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = None  # lock probe -> unlocked
            else:
                r.fetchall.return_value = [slice_row]
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.get(
            f"{PREFIX}/planning_grid?co_id=1&tran_date=2026-06-13&spell=A1"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert "rows" in data
        assert "shift_rollup" in data
        # Additive lock flags exist and are False on the unlocked path.
        assert data["locked"] is False
        assert data["reprocess_needed"] is False
        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert row["machine_id"] == 10
        assert row["item_id"] == 7
        assert row["shift_bucket"] == "A"
        # Grid values are projected straight from the slice row aliases.
        assert row["actual_speed"] == 4100.0
        assert row["actual_tpi"] == 5.1
        assert row["act_prod_doff"] == 300.0
        assert row["winding_total"] == 280.0
        assert row["act_prod_wind"] == 280.0
        assert len(data["shift_rollup"]) == 1
        agg = data["shift_rollup"][0]
        assert agg["shift_bucket"] == "A"
        # Rollup: SUM(num)/SUM(denom) — doff_eff = 300/400*100, wind_eff = 280/400*100.
        assert agg["prod_doff"] == 300.0
        assert agg["prod_wind"] == 280.0
        assert agg["doff_eff"] == 75.0
        assert agg["wind_eff"] == 70.0

    def test_locked_serves_frozen_log(self):
        # Locked path: the lock probe returns is_locked=1, so the frozen
        # jute_prod_spinning_daily rows are served (get_spinning_log_rows_query) and
        # locked=True is surfaced. Same alias contract as the live slice.
        spell_row = _mock_row({"spell_id": 1})
        lock_row = _mock_row({"is_locked": 1, "reprocess_needed": 0})
        log_row = _mock_row(_slice_row_mapping())

        # execute order: 1) resolve_spell_id .fetchone; 2) lock probe .fetchone ->
        # locked; 3) frozen-log .fetchall.
        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = lock_row
            else:
                r.fetchall.return_value = [log_row]
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.get(
            f"{PREFIX}/planning_grid?co_id=1&tran_date=2026-06-13&spell=A1"
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["locked"] is True
        assert data["reprocess_needed"] is False
        assert len(data["rows"]) == 1
        assert data["rows"][0]["machine_id"] == 10

    def test_accepts_spell_id_param(self):
        # spell_id-first contract: ?spell_id=1 validates the id (no code lookup)
        # and serves the same slice path.
        spell_row = _mock_row({"spell_id": 1, "branch_id": None})
        slice_row = _mock_row(_slice_row_mapping())

        def execute_side_effect(*args, **kwargs):
            execute_side_effect.calls += 1
            r = MagicMock()
            if execute_side_effect.calls == 1:
                r.fetchone.return_value = spell_row  # spell_id validation
            elif execute_side_effect.calls == 2:
                r.fetchone.return_value = None  # lock probe -> unlocked
            else:
                r.fetchall.return_value = [slice_row]
            return r

        execute_side_effect.calls = 0
        self.mock_session.execute.side_effect = execute_side_effect

        resp = client.get(
            f"{PREFIX}/planning_grid?co_id=1&tran_date=2026-06-13&spell_id=1"
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["data"]["rows"]) == 1
        first_sql = str(self.mock_session.execute.call_args_list[0].args[0])
        assert "sp.spell_id = :spell_id" in first_sql

    def test_missing_co_id_returns_400(self):
        resp = client.get(f"{PREFIX}/planning_grid?tran_date=2026-06-13")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        resp = client.get(f"{PREFIX}/planning_grid?co_id=1")
        assert resp.status_code == 400
        assert "tran_date" in resp.json()["detail"].lower()
