"""Tests for the Weaving "reduce jugar" adjustment endpoints (prefix /api/weavingProd).

less_production is the "reduce jugar" value already stored on jute_prod_weaving_daily
(DECIMAL(12,3) NULL DEFAULT 0). These two endpoints let the operator review and set it
per loom for a (tran_date, spell):

  * GET  /adjustment_get   -> looms + mapped quality + current less_production
  * POST /adjustment_save  -> sets ONLY less_production on existing daily rows
                             (loom with no mapped quality -> skipped)

Portal persona: DB + auth mocked (no real DB) via app.dependency_overrides keyed by the
get_tenant_db / get_current_user_with_refresh symbols imported into the router module,
exactly like test_weaving_entry.py. Rows expose ._mapping; auth returns {"user_id": 1}.

Also includes an entry_create-style regression for the existing update path: editing a row
WITHOUT sending less_production must NOT zero the stored value â€” it must carry forward the
existing row's value (asserted by inspecting the bind dict passed to the update query).
"""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.weaving_entry import (
    get_tenant_db,
    get_current_user_with_refresh,
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


def _resolve_spell_exec(spell_id=1):
    """execute() result for _resolve_spell_id (.fetchone().spell_id)."""
    r = MagicMock()
    r.spell_id = spell_id
    ex = MagicMock()
    ex.fetchone.return_value = r
    return ex


def _quality_attr_row(*, weaving_quality_id=5, item_id=10, finished_length=120.0,
                      ozs_yds=10.0, std_ozs_yds=10.0, no_of_jugar_per_cut=16.0,
                      is_composite=0, ends=272):
    """Attribute-access row for _fetch_quality (uses row.no_of_jugar_per_cut etc.)."""
    row = MagicMock()
    row.weaving_quality_id = weaving_quality_id
    row.item_id = item_id
    row.ends = ends
    row.finished_length = finished_length
    row.ozs_yds = ozs_yds
    row.std_ozs_yds = std_ozs_yds
    row.no_of_jugar_per_cut = no_of_jugar_per_cut
    row.is_composite = is_composite
    return row


def _quality_exec(qrow=None):
    ex = MagicMock()
    ex.fetchone.return_value = qrow if qrow is not None else _quality_attr_row()
    return ex


def _chain_sync_execs(open_jugar=4.0, successor_id=None):
    """Executes _sync_jugar_chain_after_write issues after a daily-row write (Phase 1b).

    open_jugar is a STORED column now: a write resolves this row's own open_jugar and
    repairs its single successor in the same transaction â€” resync-self SELECT + UPDATE +
    chain-successor probe (.scalar()). successor_id=None ends the chain.
    """
    self_select = MagicMock()
    self_select.fetchone.return_value = MagicMock(open_jugar=open_jugar)
    successor_probe = MagicMock()
    successor_probe.scalar.return_value = successor_id
    execs = [self_select, MagicMock(), successor_probe]
    if successor_id is not None:
        succ_select = MagicMock()
        succ_select.fetchone.return_value = MagicMock(open_jugar=open_jugar)
        execs += [succ_select, MagicMock()]
    return execs


class TestAdjustmentGet:
    """GET /api/weavingProd/adjustment_get â€” looms + mapped quality + less_production."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_adjustment_rows(self):
        """Each row exposes the loom identity, mapped quality, and the current
        less_production. mech_posting_code and less_production must be present.

        Execute order in adjustment_get:
          1. _resolve_spell_id          -> spell 'A1' -> spell_id 1
          2. get_weaving_adjustment_grid_query -> fetchall grid rows
        """
        spell_exec = _resolve_spell_exec(1)
        grid_rows = [
            _mock_row({
                "machine_id": 7, "mech_code": "LM01", "mech_posting_code": 101,
                "machine_name": "Loom-1", "line_no": "1", "branch_id": 2,
                "weaving_quality_id": 5, "weaving_quality_code": "WQ-272",
                "weaving_quality_name": "272 Hessian", "weaving_daily_id": 555,
                "less_production": 3.5,
            }),
            _mock_row({
                "machine_id": 8, "mech_code": "LM02", "mech_posting_code": None,
                "machine_name": "Loom-2", "line_no": "1", "branch_id": 2,
                "weaving_quality_id": None, "weaving_quality_code": None,
                "weaving_quality_name": None, "weaving_daily_id": None,
                "less_production": None,
            }),
        ]
        grid_exec = MagicMock()
        grid_exec.fetchall.return_value = grid_rows
        self._mock_session.execute.side_effect = [spell_exec, grid_exec]

        response = client.get(
            "/api/weavingProd/adjustment_get?co_id=1&tran_date=2026-06-24&spell=A1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, list)
        assert len(data) == 2
        first = data[0]
        assert "mech_posting_code" in first
        assert "less_production" in first
        assert first["machine_id"] == 7
        assert first["mech_posting_code"] == 101
        assert first["weaving_quality_id"] == 5
        assert first["weaving_daily_id"] == 555
        assert float(first["less_production"]) == 3.5
        # A loom with no mapped quality still appears, less_production coalesced (None -> 0).
        second = data[1]
        assert second["machine_id"] == 8
        assert second["weaving_quality_id"] is None
        assert float(second["less_production"]) == 0.0

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingProd/adjustment_get?tran_date=2026-06-24&spell=A1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/adjustment_get?co_id=1&spell=A1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()


class TestAdjustmentSave:
    """POST /api/weavingProd/adjustment_save â€” set ONLY less_production per loom."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_save_updates_existing_daily_row(self):
        """A loom WITH a mapped quality and an EXISTING active daily row -> the
        update_weaving_daily_less_production path runs and saved == 1.

        Execute order in adjustment_save (one entry):
          1. _resolve_spell_id            -> spell 'A1' -> spell_id 1
          2. _mapped_quality_id           -> qid 5 (active Loom->Quality map row)
          3. active-row lookup            -> existing daily row (weaving_daily_id 555)
          4. update less_production       -> result
        """
        spell_exec = _resolve_spell_exec(1)
        map_exec = MagicMock()
        map_row = MagicMock(); map_row.weaving_quality_id = 5
        map_exec.fetchone.return_value = map_row
        active_exec = MagicMock()
        existing = MagicMock(); existing.weaving_daily_id = 555
        active_exec.fetchone.return_value = existing
        update_exec = MagicMock()
        self._mock_session.execute.side_effect = [
            spell_exec, map_exec, active_exec, update_exec,
        ]

        body = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-24",
            "spell": "A1",
            "entries": [{"machine_id": 7, "less_production": 4.0}],
        }
        response = client.post("/api/weavingProd/adjustment_save", json=body)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 1
        assert data.get("skipped", 0) == 0
        self._mock_session.commit.assert_called_once()

        # The UPDATE carries the new less_production for the existing row.
        update_params = self._mock_session.execute.call_args_list[3].args[1]
        assert update_params["less_production"] == 4.0

    def test_save_skips_loom_with_no_mapped_quality(self):
        """A loom with NO mapped quality is skipped (skipped >= 1, saved == 0).

        Execute order:
          1. _resolve_spell_id   -> spell_id 1
          2. _mapped_quality_id  -> None (no active Loom->Quality map row)
        """
        spell_exec = _resolve_spell_exec(1)
        map_exec = MagicMock()
        map_exec.fetchone.return_value = None  # no mapped quality
        self._mock_session.execute.side_effect = [spell_exec, map_exec]

        body = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-24",
            "spell": "A1",
            "entries": [{"machine_id": 9, "less_production": 2.0}],
        }
        response = client.post("/api/weavingProd/adjustment_save", json=body)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 0
        assert data["skipped"] >= 1
        assert 9 in data["skipped_machines"]

    def test_save_skips_loom_with_no_daily_row(self):
        """Regression: a loom with a mapped quality but NO active daily row is SKIPPED â€”
        no phantom cuts=0 row is inserted (it would compute strictly negative total_jugar
        and zero its chain successor's open_jugar). Execute order:
          1. _resolve_spell_id   -> spell_id 1
          2. _mapped_quality_id  -> qid 5
          3. active-row lookup   -> None (no daily row)
        Nothing else executes (no beam_no lookup, no INSERT, no chain sync)."""
        spell_exec = _resolve_spell_exec(1)
        map_exec = MagicMock()
        map_row = MagicMock(); map_row.weaving_quality_id = 5
        map_exec.fetchone.return_value = map_row
        active_exec = MagicMock()
        active_exec.fetchone.return_value = None  # no daily row
        self._mock_session.execute.side_effect = [spell_exec, map_exec, active_exec]

        body = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-24",
            "spell": "A1",
            "entries": [{"machine_id": 7, "less_production": 4.0}],
        }
        response = client.post("/api/weavingProd/adjustment_save", json=body)

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["saved"] == 0
        assert data["skipped"] == 1
        assert data["skipped_machines"] == [7]
        assert self._mock_session.execute.call_count == 3  # no INSERT fired
        self._mock_session.commit.assert_called_once()


class TestEntryEditLessProductionRegression:
    """entry_edit regression: omitting less_production must NOT zero the stored value.

    WeavingEntryUpdate.less_production defaults to None; entry_edit falls back to the
    existing row's value. The UPDATE bind dict must therefore carry the EXISTING value,
    not 0 â€” asserted via mock_session.execute.call_args.

    Execute order in entry_edit (mirrors test_weaving_entry.TestEntryEdit):
      1. existing daily row lookup -> fetchone existing
      2. _mapped_quality_id        -> qid 5
      3. _fetch_quality            -> quality row (cj range check)
      4. _derive_branch_id         -> branch row
      5. latest beam_no            -> scalar
      6. UPDATE edited row         -> result
      7. resync-self open_jugar SELECT (Phase 1b â€” stored open_jugar)
      8. resync-self open_jugar UPDATE
      9. chain-successor probe -> None (identity unchanged, no old-chain probe)
    """

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_edit_without_less_production_keeps_existing_value(self):
        existing = MagicMock()
        existing.weaving_daily_id = 900
        existing.co_id = 1
        existing.branch_id = 2
        existing.tran_date = "2026-06-21"
        existing.spell_id = 1
        existing.machine_id = 7
        existing.weaving_quality_id = 5
        existing.eb_id = None
        existing.beam_no = "BEAM-OLD"
        existing.cuts = 4.0
        existing.close_jugar = 2.0
        existing.less_production = 7.5  # the value that must NOT be zeroed
        existing_exec = MagicMock(); existing_exec.fetchone.return_value = existing

        map_exec = MagicMock()
        map_row = MagicMock(); map_row.weaving_quality_id = 5
        map_exec.fetchone.return_value = map_row
        q_exec = _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0))
        branch_exec = MagicMock()
        branch_row = MagicMock(); branch_row.branch_id = 2
        branch_exec.fetchone.return_value = branch_row
        beam_exec = MagicMock(); beam_exec.scalar.return_value = "BEAM-007"
        update_exec = MagicMock()
        self._mock_session.execute.side_effect = [
            existing_exec, map_exec, q_exec, branch_exec, beam_exec, update_exec,
        ] + _chain_sync_execs()

        # Body omits less_production entirely.
        response = client.put(
            "/api/weavingProd/entry_edit/900?co_id=1",
            json={"cuts": 12, "close_jugar": 6},
        )

        assert response.status_code == 200
        # The UPDATE bind dict must carry the EXISTING less_production (7.5), not 0.
        update_params = self._mock_session.execute.call_args_list[5].args[1]
        assert update_params["less_production"] == 7.5
