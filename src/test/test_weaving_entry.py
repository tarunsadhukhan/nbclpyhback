"""Tests for Weaving Production Entry endpoints (Page C).

Tests for src/juteProduction/weaving_entry.py (prefix /api/weavingProd).

STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24): the entry endpoints persist INPUTS
ONLY (cuts, close_jugar, less_production + identity); the read endpoints SELECT from the
view vw_weaving_daily. There is NO server-side compute, NO standards snapshot, NO open-jugar
resolution, and NO recompute cascade â€” the view derives every column on read. So these tests
no longer patch compute/open/cascade; they assert the persisted INPUT params and that reads
pass the view's already-computed columns straight through.

Portal persona: DB + auth mocked (no real DB) via app.dependency_overrides keyed by the
get_tenant_db / get_current_user_with_refresh symbols imported into the router module.

QUALITY IS MAPPED, NOT SELECTED INLINE: the weaving_quality_id is INHERITED from the active
jute_prod_weaving_quality_map, never sent in the entry body.

Covered:
  * entry_create happy path â€” upsert INSERT branch, INPUTS-ONLY persisted
  * entry_create upsert UPDATE branch (existing active row -> update in place)
  * entry_create missing mapped quality -> 400 (no Loom->Quality map row)
  * entry_create close_jugar > no_of_jugar_per_cut -> 400 (reject at write time)
  * entry_create missing spell (body validation) -> 422
  * entry_create co_id optional (derived from branch)
  * entry_edit inputs-only update (no cascade)
  * entries_by_date view-backed (success + missing co_id 400 + missing tran_date 400)
  * planning_grid driver LEFT JOIN view (success + missing co_id 400)
  * machine_standards: speed resolved by MACHINE (mcid), picks/eff by quality (qid);
    resolve_quality_standards now takes machine_id (two-dimensional)
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


def _mapped_qid_exec(qid):
    """execute() result for _mapped_quality_id (.fetchone().weaving_quality_id)."""
    ex = MagicMock()
    if qid is None:
        ex.fetchone.return_value = None
    else:
        r = MagicMock()
        r.weaving_quality_id = qid
        ex.fetchone.return_value = r
    return ex


def _resolve_spell_exec(spell_id=1):
    """execute() result for _resolve_spell_id (.fetchone().spell_id)."""
    r = MagicMock()
    r.spell_id = spell_id
    ex = MagicMock()
    ex.fetchone.return_value = r
    return ex


def _derive_co_id_exec(co_id=1):
    """execute() result for _derive_co_id (.fetchone().co_id) â€” branch_mst lookup."""
    r = MagicMock()
    r.co_id = co_id
    ex = MagicMock()
    ex.fetchone.return_value = r
    return ex


def _branch_exec(branch_id=2):
    r = MagicMock()
    r.branch_id = branch_id
    ex = MagicMock()
    ex.fetchone.return_value = r
    return ex


def _quality_exec(qrow=None):
    ex = MagicMock()
    ex.fetchone.return_value = qrow if qrow is not None else _quality_attr_row()
    return ex


def _chain_sync_execs(open_jugar=4.0, successor_id=None):
    """Executes _sync_jugar_chain_after_write issues after a daily-row write (Phase 1b).

    open_jugar is now a STORED column: every write re-resolves this row's own open_jugar
    and repairs its single chain successor in the same transaction. That is, in order:
      (a) resync-self SELECT   -> resolve_weaving_open_jugar_for_row_query, .fetchone().open_jugar
      (b) resync-self UPDATE   -> update_weaving_daily_open_jugar_query
      (c) chain-successor probe -> get_weaving_chain_successor_query, .scalar()
    successor_id=None ends the chain (no successor); pass an id to append the successor's
    own open_jugar SELECT + UPDATE.
    """
    self_select = MagicMock()
    self_select.fetchone.return_value = MagicMock(open_jugar=open_jugar)
    self_update = MagicMock()
    successor_probe = MagicMock()
    successor_probe.scalar.return_value = successor_id
    execs = [self_select, self_update, successor_probe]
    if successor_id is not None:
        succ_select = MagicMock()
        succ_select.fetchone.return_value = MagicMock(open_jugar=open_jugar)
        execs += [succ_select, MagicMock()]
    return execs


class TestEntryCreate:
    """POST /api/weavingProd/entry_create â€” INPUTS-ONLY upsert."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _payload(self):
        # NO weaving_quality_id / beam_no / eb_id â€” those are server-resolved.
        # spell is the CODE ('A1'); co_id is optional (derived from branch).
        # close_jugar (operator cj) replaces the old 'jugar' field.
        return {
            "co_id": 1,
            "tran_date": "2026-06-21",
            "spell": "A1",
            "machine_id": 7,
            "cuts": 10,
            "close_jugar": 12,
        }

    def test_create_inserts_inputs_only(self):
        """Quality is INHERITED from the map; the server validates cj <= jc and persists
        INPUTS ONLY (no computed columns), then INSERTs (no existing active row).

        Execute order in entry_create:
          1. _resolve_spell_id   -> spell 'A1' -> spell_id 1
          2. _derive_branch_id   -> branch row (body omits branch_id)
          3. _mapped_quality_id  -> qid 5 (active Loom->Quality map row)
          4. _fetch_quality      -> quality row (cj range check)
          5. latest beam_no      -> scalar beam_no
          6. active-row lookup   -> None (no existing)
          7. insert_weaving_daily -> lastrowid
          8. resync-self open_jugar SELECT (Phase 1b â€” write-time stored open_jugar)
          9. resync-self open_jugar UPDATE
         10. chain-successor probe -> None (no successor to repair)
        """
        resolve_exec = _resolve_spell_exec(1)
        branch_exec = _branch_exec(2)
        map_exec = _mapped_qid_exec(5)
        q_exec = _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0))
        beam_exec = MagicMock(); beam_exec.scalar.return_value = "BEAM-007"
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 555
        self._mock_session.execute.side_effect = [
            resolve_exec, branch_exec, map_exec, q_exec, beam_exec,
            active_exec, insert_exec,
        ] + _chain_sync_execs()

        response = client.post("/api/weavingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["weaving_daily_id"] == 555
        assert data["weaving_quality_id"] == 5
        # No 'computed' key any more (the view computes on read).
        assert "computed" not in data
        self._mock_session.commit.assert_called_once()

        # INSERT carries INPUTS ONLY: identity + cuts/close_jugar/less_production + beam_no.
        insert_params = self._mock_session.execute.call_args_list[6].args[1]
        assert insert_params["beam_no"] == "BEAM-007"
        assert insert_params["weaving_quality_id"] == 5
        assert insert_params["cuts"] == 10.0
        assert insert_params["close_jugar"] == 12.0
        assert insert_params["less_production"] == 0.0
        assert insert_params["eb_id"] is None
        # No computed/standard columns leak into the persisted params.
        for forbidden in ("production_yds", "efficiency", "open_jugar", "jugar",
                          "std_prod_yds", "std_speed", "working_hours"):
            assert forbidden not in insert_params

    def test_create_upserts_existing_active_row(self):
        """An existing active row for the (date, spell, loom, quality) key is UPDATED in
        place (no second insert) â€” app-uniqueness upsert.

        Execute order: spell resolve, branch derive, mapped qid, fetch quality, beam,
        active-row lookup (existing 321), preserve-less_production SELECT, UPDATE,
        then Phase 1b: resync-self open_jugar SELECT + UPDATE + chain-successor probe (None).
        """
        resolve_exec = _resolve_spell_exec(1)
        branch_exec = _branch_exec(2)
        map_exec = _mapped_qid_exec(5)
        q_exec = _quality_exec()
        beam_exec = MagicMock(); beam_exec.scalar.return_value = None
        active_exec = MagicMock()
        existing = MagicMock(); existing.weaving_daily_id = 321
        active_exec.fetchone.return_value = existing
        # body omits less_production -> on an existing row the endpoint re-reads the
        # stored value (preserve adjustment) before UPDATE: one extra SELECT execute.
        preserve_exec = MagicMock(); preserve_exec.scalar.return_value = 0.0
        update_exec = MagicMock()
        self._mock_session.execute.side_effect = [
            resolve_exec, branch_exec, map_exec, q_exec, beam_exec,
            active_exec, preserve_exec, update_exec,
        ] + _chain_sync_execs()

        response = client.post("/api/weavingProd/entry_create", json=self._payload())

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["weaving_daily_id"] == 321  # existing row id, not a new insert
        self._mock_session.commit.assert_called_once()
        update_params = self._mock_session.execute.call_args_list[7].args[1]
        assert update_params["id"] == 321
        assert update_params["close_jugar"] == 12.0

    def test_create_allowed_when_no_mapped_quality(self):
        """Capture is allowed BEFORE the Loom->Quality map (spec 2026-07-07): no mapping
        -> quality NULL, inputs persisted; quality is resolved later at Process."""
        # Order: spell resolve, branch derive, mapped=None, beam, active-row (None), insert.
        # No _fetch_quality (quality None) and NO chain sync (chain partitions by quality).
        beam_exec = MagicMock(); beam_exec.scalar.return_value = None
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 556
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), _branch_exec(2), _mapped_qid_exec(None),
            beam_exec, active_exec, insert_exec,
        ]

        response = client.post("/api/weavingProd/entry_create", json=self._payload())

        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["weaving_daily_id"] == 556
        assert data["weaving_quality_id"] is None
        self._mock_session.commit.assert_called_once()

    def test_create_close_jugar_over_jc_returns_400(self):
        """close_jugar > no_of_jugar_per_cut is rejected at write time (0 <= cj <= jc)."""
        # Order: spell resolve, branch derive, mapped qid 5, fetch quality (jc=16).
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), _branch_exec(2), _mapped_qid_exec(5),
            _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0)),
        ]
        bad = self._payload()
        bad["close_jugar"] = 20  # > jc 16

        response = client.post("/api/weavingProd/entry_create", json=bad)

        assert response.status_code == 400
        assert "close_jugar" in response.json()["detail"]
        self._mock_session.commit.assert_not_called()

    def test_create_missing_spell_returns_400(self):
        """spell is a required body field â€” Pydantic rejects its absence with 422."""
        # Neither spell_id nor spell -> 400 exactly-one rule (shared _resolve_spell).
        self._mock_session.execute.side_effect = [_branch_exec(2)]
        bad = self._payload()
        del bad["spell"]
        response = client.post("/api/weavingProd/entry_create", json=bad)
        assert response.status_code == 400
        assert "exactly one of spell_id or spell" in response.json()["detail"]

    def test_create_co_id_optional_derived_from_branch(self):
        """co_id is no longer required: omitted -> derived from the machine's branch."""
        # Order: spell resolve, branch derive, co_id derive, mapped qid 5, fetch quality,
        # beam, active-row (None), insert, then Phase 1b chain sync.
        beam_exec = MagicMock(); beam_exec.scalar.return_value = None
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 557
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), _branch_exec(2), _derive_co_id_exec(1),
            _mapped_qid_exec(5), _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0)),
            beam_exec, active_exec, insert_exec,
        ] + _chain_sync_execs()
        bad = self._payload()
        del bad["co_id"]
        response = client.post("/api/weavingProd/entry_create", json=bad)
        # Not 422 (co_id optional); 200 with the derived co_id + mapped quality.
        assert response.status_code == 200, response.text
        assert response.json()["data"]["weaving_quality_id"] == 5


def _spell_id_path_exec(spell_id=1, branch_id=2):
    """execute() result for _resolve_spell's spell_id path (row.branch_id is checked
    against the request branch)."""
    r = MagicMock()
    r.spell_id = spell_id
    r.branch_id = branch_id
    ex = MagicMock()
    ex.fetchone.return_value = r
    return ex


class TestSpellIdContract:
    """spell_id preferred + DEPRECATED branch-scoped spell-code fallback -- the shared
    spinning_entry._resolve_spell contract (no global fallback)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _payload(self, **over):
        base = {
            "co_id": 1,
            "branch_id": 2,
            "tran_date": "2026-06-21",
            "spell_id": 1,
            "machine_id": 7,
            "cuts": 10,
            "close_jugar": 12,
        }
        base.update(over)
        return base

    def test_create_accepts_spell_id(self):
        """spell_id (no spell code) resolves via the id path -- validated against the
        branch -- and the resolved id is stamped on the INSERT. Execute order (co_id +
        branch_id in body, so no derive execs):
          0. _resolve_spell id path -> row(branch_id=2 matches)
          1. _mapped_quality_id     -> qid 5
          2. _fetch_quality         -> quality (jc=16)
          3. latest beam_no; 4. active-row (None); 5. INSERT; 6-8. chain sync
        """
        insert_exec = MagicMock(); insert_exec.lastrowid = 700
        beam_exec = MagicMock(); beam_exec.scalar.return_value = None
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        self._mock_session.execute.side_effect = [
            _spell_id_path_exec(1, branch_id=2), _mapped_qid_exec(5),
            _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0)),
            beam_exec, active_exec, insert_exec,
        ] + _chain_sync_execs()

        response = client.post("/api/weavingProd/entry_create", json=self._payload())

        assert response.status_code == 200, response.text
        insert_params = self._mock_session.execute.call_args_list[5].args[1]
        assert insert_params["spell_id"] == 1
        # The id-path lookup binds the spell_id, not a code.
        resolve_binds = self._mock_session.execute.call_args_list[0].args[1]
        assert resolve_binds == {"spell_id": 1}

    def test_create_wrong_branch_spell_id_returns_400(self):
        """A spell_id whose shift belongs to ANOTHER branch is rejected (dev3
        branch-12 'C' = 8 vs branch-2 'C' = 5 fanout)."""
        self._mock_session.execute.side_effect = [
            _spell_id_path_exec(1, branch_id=12),  # shift branch 12 != body branch 2
        ]
        response = client.post("/api/weavingProd/entry_create", json=self._payload())
        assert response.status_code == 400
        assert "does not belong to this branch" in response.json()["detail"]
        self._mock_session.commit.assert_not_called()

    def test_create_both_spell_id_and_spell_returns_400(self):
        response = client.post(
            "/api/weavingProd/entry_create", json=self._payload(spell="A1")
        )
        assert response.status_code == 400
        assert "exactly one of spell_id or spell" in response.json()["detail"]

    def test_code_fallback_is_branch_scoped(self):
        """The deprecated spell-code fallback binds the branch (single execute -- the
        legacy global-fallback retry is GONE)."""
        beam_exec = MagicMock(); beam_exec.scalar.return_value = None
        active_exec = MagicMock(); active_exec.fetchone.return_value = None
        insert_exec = MagicMock(); insert_exec.lastrowid = 701
        self._mock_session.execute.side_effect = [
            _resolve_spell_exec(1), _mapped_qid_exec(5),
            _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0)),
            beam_exec, active_exec, insert_exec,
        ] + _chain_sync_execs()

        payload = self._payload(spell="A1")
        del payload["spell_id"]
        response = client.post("/api/weavingProd/entry_create", json=payload)

        assert response.status_code == 200, response.text
        resolve_binds = self._mock_session.execute.call_args_list[0].args[1]
        assert resolve_binds == {"spell_code": "A1", "branch_id": 2}

    def test_code_fallback_no_branch_match_400_no_global_retry(self):
        """No branch-scoped match -> 400 Unknown spell after ONE resolve execute --
        the old resolver's second global-MIN probe must not fire."""
        self._mock_session.execute.side_effect = [_resolve_spell_exec(None)]
        payload = self._payload(spell="ZZ")
        del payload["spell_id"]
        response = client.post("/api/weavingProd/entry_create", json=payload)
        assert response.status_code == 400
        assert "unknown spell" in response.json()["detail"].lower()
        assert self._mock_session.execute.call_count == 1

    def test_quality_map_get_accepts_spell_id_param(self):
        """Reads accept ?spell_id= as the preferred identity (branch-validated)."""
        rows_exec = MagicMock(); rows_exec.fetchall.return_value = []
        last_exec = MagicMock(); last_exec.scalar.return_value = None
        self._mock_session.execute.side_effect = [
            _spell_id_path_exec(1, branch_id=2), rows_exec, last_exec,
        ]
        response = client.get(
            "/api/weavingProd/quality_map_get"
            "?co_id=1&branch_id=2&tran_date=2026-06-21&spell_id=1"
        )
        assert response.status_code == 200, response.text
        grid_binds = self._mock_session.execute.call_args_list[1].args[1]
        assert grid_binds["spell_id"] == 1


class TestEntryEdit:
    """PUT /api/weavingProd/entry_edit/{entry_id} â€” inputs-only update, no cascade."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_edit_persists_inputs_no_cascade(self):
        """Editing cuts/close_jugar validates cj <= jc and persists the UPDATE (inputs only).
        There is NO cascade and NO 'computed' echo â€” the view re-derives on read.

        Execute order in entry_edit:
          1. existing daily row lookup -> fetchone existing
          2. _mapped_quality_id        -> qid 5
          3. _fetch_quality            -> quality row (cj range check)
          4. _derive_branch_id         -> branch row
          5. latest beam_no            -> scalar
          6. UPDATE edited row         -> result
          7. resync-self open_jugar SELECT (Phase 1b)
          8. resync-self open_jugar UPDATE
          9. chain-successor probe -> None
        Identity is unchanged (body sends no spell/machine), so there is NO old-chain probe.
        """
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
        existing.less_production = 0.0
        existing_exec = MagicMock(); existing_exec.fetchone.return_value = existing

        map_exec = _mapped_qid_exec(5)
        q_exec = _quality_exec(_quality_attr_row(no_of_jugar_per_cut=16.0))
        branch_exec = _branch_exec(2)
        beam_exec = MagicMock(); beam_exec.scalar.return_value = "BEAM-007"
        update_exec = MagicMock()
        self._mock_session.execute.side_effect = [
            existing_exec, map_exec, q_exec, branch_exec, beam_exec, update_exec,
        ] + _chain_sync_execs()

        response = client.put(
            "/api/weavingProd/entry_edit/900?co_id=1",
            json={"cuts": 12, "close_jugar": 6},
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["weaving_daily_id"] == 900
        assert data["weaving_quality_id"] == 5
        assert "cascade" not in data
        assert "computed" not in data
        self._mock_session.commit.assert_called_once()

        # UPDATE carries the edited inputs (12 / 6), not the existing (4 / 2), inputs only.
        update_params = self._mock_session.execute.call_args_list[5].args[1]
        assert update_params["id"] == 900
        assert update_params["cuts"] == 12.0
        assert update_params["close_jugar"] == 6.0
        assert update_params["beam_no"] == "BEAM-007"

    def test_edit_missing_co_id_returns_400(self):
        response = client.put(
            "/api/weavingProd/entry_edit/900", json={"cuts": 1, "close_jugar": 1}
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_edit_entry_not_found_returns_404(self):
        not_found = MagicMock(); not_found.fetchone.return_value = None
        self._mock_session.execute.return_value = not_found
        response = client.put(
            "/api/weavingProd/entry_edit/900?co_id=1", json={"cuts": 1, "close_jugar": 1}
        )
        assert response.status_code == 404


class TestMachineStandards:
    """GET /api/weavingProd/machine_standards â€” two-dimensional prefill.

    Weaving is TWO-DIMENSIONAL: speed (std/actual) resolves from the MCID target map for
    the LOOM (machine_id); picks/eff resolve from the QID target map for the quality.
    resolve_quality_standards now takes machine_id, so the endpoint forwards both
    machine_id and weaving_quality_id; the speed resolves resolve_param with id_type
    'mcid' & ref_id = machine_id, the picks/eff resolves with id_type 'qid' & ref_id =
    weaving_quality_id.
    """

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    @staticmethod
    def _value_exec(value):
        r = MagicMock(); r.value = value
        ex = MagicMock(); ex.fetchone.return_value = r
        return ex

    @staticmethod
    def _avg_picks_exec(avg):
        r = MagicMock(); r.avg_picks = avg
        ex = MagicMock(); ex.fetchone.return_value = r
        return ex

    @staticmethod
    def _working_hours_exec(hours):
        r = MagicMock(); r.working_hours = hours
        ex = MagicMock(); ex.fetchone.return_value = r
        return ex

    @staticmethod
    def _idle_hours_exec(idle):
        r = MagicMock(); r.idle_hours = idle
        ex = MagicMock(); ex.fetchone.return_value = r
        return ex

    def test_speed_resolves_by_machine_picks_eff_by_quality(self):
        """Execute order in machine_standards (machine_id + quality + spell supplied):
          1. _resolve_spell_id            -> spell 'A1' -> spell_id 1
          2. resolve_param std_speed      -> mcid / ref_id=machine_id (LOOM)
          3. resolve_param act_speed      -> mcid / ref_id=machine_id (LOOM)
          4. resolve_param std_picks      -> qid  / ref_id=weaving_quality_id
          5. resolve_act_picks            -> vw_weaving_pick_act avg_picks
          6. resolve_param std_eff        -> qid  / ref_id=weaving_quality_id
          7. resolve_param target_eff     -> qid  / ref_id=weaving_quality_id
          8. spell_working_hours          -> gross spell hours
          9. stoppage_hours               -> idle hours
        """
        spell_exec = _resolve_spell_exec(1)
        std_speed_exec = self._value_exec(200.0)   # mcid std speed (loom)
        act_speed_exec = self._value_exec(198.0)   # mcid act speed (loom)
        std_picks_exec = self._value_exec(12.0)    # qid std picks
        act_picks_exec = self._avg_picks_exec(11.5)  # measured picks (Pick-SQC view)
        std_eff_exec = self._value_exec(85.0)      # qid std eff
        target_eff_exec = self._value_exec(90.0)   # qid target eff
        wh_exec = self._working_hours_exec(8.0)    # gross spell hours
        idle_exec = self._idle_hours_exec(1.0)     # stoppage hours
        self._mock_session.execute.side_effect = [
            spell_exec, std_speed_exec, act_speed_exec, std_picks_exec,
            act_picks_exec, std_eff_exec, target_eff_exec, wh_exec, idle_exec,
        ]

        response = client.get(
            "/api/weavingProd/machine_standards"
            "?co_id=1&machine_id=7&weaving_quality_id=5&spell=A1&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # Speed comes from the LOOM (mcid dimension).
        assert data["std_speed"] == 200.0
        assert data["act_speed"] == 198.0
        # act > 0 -> eff_speed prefers the actual loom speed.
        assert data["eff_speed"] == 198.0
        # Picks/eff come from the quality (qid dimension); act_picks from the Pick-SQC view.
        assert data["std_picks"] == 12.0
        assert data["act_picks"] == 11.5
        assert data["eff_picks"] == 11.5
        assert data["std_eff"] == 85.0
        assert data["target_eff"] == 90.0
        # working_hours = gross 8 - idle 1.
        assert data["working_hours"] == 7.0
        assert data["weaving_quality_id"] == 5

        # std_speed resolve (call index 1) binds id_type='mcid', ref_id = machine_id (LOOM).
        std_speed_params = self._mock_session.execute.call_args_list[1].args[1]
        assert std_speed_params["id_type"] == "mcid"
        assert std_speed_params["param"] == "speed"
        assert std_speed_params["ref_id"] == 7
        assert std_speed_params["value_role"] == "standard"
        # act_speed resolve (call index 2) is mcid/actual for the LOOM.
        act_speed_params = self._mock_session.execute.call_args_list[2].args[1]
        assert act_speed_params["id_type"] == "mcid"
        assert act_speed_params["value_role"] == "actual"
        assert act_speed_params["ref_id"] == 7
        # std_picks resolve (call index 3) is qid for the QUALITY ref.
        std_picks_params = self._mock_session.execute.call_args_list[3].args[1]
        assert std_picks_params["id_type"] == "qid"
        assert std_picks_params["param"] == "picks"
        assert std_picks_params["ref_id"] == 5
        # std_eff resolve (call index 5) is qid for the QUALITY ref.
        std_eff_params = self._mock_session.execute.call_args_list[5].args[1]
        assert std_eff_params["id_type"] == "qid"
        assert std_eff_params["param"] == "eff"
        assert std_eff_params["ref_id"] == 5

    def test_missing_tran_date_returns_400(self):
        response = client.get(
            "/api/weavingProd/machine_standards?co_id=1&machine_id=7&weaving_quality_id=5"
        )
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()

    def test_missing_co_id_returns_400(self):
        response = client.get(
            "/api/weavingProd/machine_standards"
            "?machine_id=7&weaving_quality_id=5&tran_date=2026-06-21"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestMachineStandardsResolver:
    """src.juteProduction.services.weaving_standards.resolve_quality_standards â€” unit.

    The resolver is now TWO-DIMENSIONAL and its signature takes machine_id:
    resolve_quality_standards(db, co_id, machine_id, weaving_quality_id, on_date).
    Speed resolves via the MCID dimension (ref_id = machine_id), picks/eff via the QID
    dimension (ref_id = weaving_quality_id), act_picks via vw_weaving_pick_act.
    """

    def test_resolver_takes_machine_id_and_resolves_both_dims(self):
        from src.juteProduction.services.weaving_standards import (
            resolve_quality_standards,
        )

        db = MagicMock()

        def _value_exec(value):
            r = MagicMock(); r.value = value
            ex = MagicMock(); ex.fetchone.return_value = r
            return ex

        avg_picks_row = MagicMock(); avg_picks_row.avg_picks = 11.5
        avg_picks_exec = MagicMock(); avg_picks_exec.fetchone.return_value = avg_picks_row

        # Order inside resolve_quality_standards:
        #   std_speed (mcid), act_speed (mcid), std_picks (qid), act_picks (view),
        #   std_eff (qid), target_eff (qid).
        db.execute.side_effect = [
            _value_exec(200.0),  # std_speed (mcid)
            _value_exec(0.0),    # act_speed (mcid) -> 0 so eff_speed falls back to std
            _value_exec(12.0),   # std_picks (qid)
            avg_picks_exec,      # act_picks (vw_weaving_pick_act)
            _value_exec(85.0),   # std_eff (qid)
            _value_exec(90.0),   # target_eff (qid)
        ]

        out = resolve_quality_standards(
            db, co_id=1, machine_id=7, weaving_quality_id=5, on_date="2026-06-21"
        )

        assert out["std_speed"] == 200.0
        assert out["act_speed"] == 0.0
        assert out["eff_speed"] == 200.0  # act 0 -> std
        assert out["std_picks"] == 12.0
        assert out["act_picks"] == 11.5
        assert out["eff_picks"] == 11.5  # act picks present -> preferred
        assert out["std_eff"] == 85.0
        assert out["target_eff"] == 90.0

        # std_speed resolve binds the MCID dimension with ref_id = machine_id (LOOM).
        std_speed_params = db.execute.call_args_list[0].args[1]
        assert std_speed_params["id_type"] == "mcid"
        assert std_speed_params["param"] == "speed"
        assert std_speed_params["ref_id"] == 7
        # std_picks resolve binds the QID dimension with ref_id = weaving_quality_id.
        std_picks_params = db.execute.call_args_list[2].args[1]
        assert std_picks_params["id_type"] == "qid"
        assert std_picks_params["param"] == "picks"
        assert std_picks_params["ref_id"] == 5


class TestEntryCreateSetup:
    """GET /api/weavingProd/entry_create_setup â€” looms, spells, eb, qualities."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_qualities_for_map_dropdown(self):
        machines_exec = MagicMock()
        machines_exec.fetchall.return_value = [
            _mock_row({"machine_id": 7, "mech_code": "LM01", "machine_name": "Loom-1",
                       "branch_id": 2}),
        ]
        spells_exec = MagicMock()
        spells_exec.fetchall.return_value = [
            _mock_row({"spell_id": 1, "spell_code": "A1", "spell_name": "A1",
                       "working_hours": 8.0}),
        ]
        eb_exec = MagicMock()
        eb_exec.fetchall.return_value = []
        qualities_exec = MagicMock()
        qualities_exec.fetchall.return_value = [
            _mock_row({"weaving_quality_id": 6, "item_id": 10,
                       "weaving_quality_code": "WQ-300",
                       "weaving_quality_name": "300 Hessian"}),
            _mock_row({"weaving_quality_id": 5, "item_id": None,
                       "weaving_quality_code": "WQ-272",
                       "weaving_quality_name": None}),
        ]
        # Execute order: machines, spells, eb_list, qualities.
        self._mock_session.execute.side_effect = [
            machines_exec, spells_exec, eb_exec, qualities_exec,
        ]

        response = client.get("/api/weavingProd/entry_create_setup?co_id=1&branch_id=2")

        assert response.status_code == 200
        data = response.json()["data"]
        assert "qualities" in data
        assert len(data["qualities"]) == 2
        first = data["qualities"][0]
        assert first["weaving_quality_id"] == 6
        assert first["weaving_quality_code"] == "WQ-300"
        assert first["weaving_quality_name"] == "300 Hessian"
        assert first["item_id"] == 10
        assert data["qualities"][1]["item_id"] is None

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingProd/entry_create_setup?branch_id=2")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()


class TestEntriesByDate:
    """GET /api/weavingProd/entries_by_date â€” view-backed (vw_weaving_daily)."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_success_returns_view_computed_rows(self):
        """Each row comes straight from vw_weaving_daily: the view already computed
        open_jugar/jugar/production/efficiency; Decimal/date columns are JSON-serialized."""
        rows = [
            _mock_row({
                "weaving_daily_id": 10, "co_id": 1, "branch_id": 2,
                "tran_date": "2026-06-21", "spell_id": 1, "machine_id": 7,
                "weaving_quality_id": 5,  # inherited from the map via COALESCE (in view)
                "cuts": 10.0, "close_jugar": 12.0, "open_jugar": 0.0, "jugar": 172.0,
                "production_yds": 1075.0, "efficiency": 95.0,
            }),
        ]
        ex = MagicMock(); ex.fetchall.return_value = rows
        self._mock_session.execute.return_value = ex

        response = client.get(
            "/api/weavingProd/entries_by_date?co_id=1&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["weaving_quality_id"] == 5
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


class TestPlanningGrid:
    """GET /api/weavingProd/planning_grid â€” driver (quality map) LEFT JOIN view."""

    def setup_method(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_driver_join_view(self):
        """The grid driver rows are the active jute_prod_weaving_quality_map rows LEFT JOIN
        vw_weaving_daily â€” each row already carries the view-computed columns. A single DB
        execute (the driver query) feeds the grid; the rollup sums num/denom (never the
        avg of effs).

        Execute order in planning_grid:
          1. get_weaving_plan_driver_query -> fetchall driver rows (map LEFT JOIN view)
        """
        driver_rows = [
            _mock_row({
                "weaving_quality_map_id": 50, "machine_id": 7, "spell_id": 1,
                "spell_code": "A1", "mech_code": "L01", "machine_name": "Loom-1",
                "line_no": "1", "branch_id": 2, "item_id": 10, "item_code": "JC",
                "item_name": "Jute Cloth", "weaving_quality_id": 5,
                "weaving_quality_code": "Q5", "weaving_quality_name": "Red",
                "finished_length": 100.0, "ozs_yds": 10.0, "std_ozs_yds": 10.0,
                "no_of_jugar_per_cut": 16.0, "is_composite": 0,
                # view-computed columns joined in:
                "weaving_daily_id": 10, "cuts": 10.0, "close_jugar": 12.0,
                "less_production": 0.0, "open_jugar": 0.0, "jugar": 172.0,
                "production_yds": 1075.0, "production_kg": 304.76,
                "std_prod_yds": 1200.0, "efficiency": 89.58,
            }),
        ]
        driver_exec = MagicMock(); driver_exec.fetchall.return_value = driver_rows
        self._mock_session.execute.side_effect = [driver_exec]

        response = client.get(
            "/api/weavingProd/planning_grid?co_id=1&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        rows = payload["rows"]
        assert len(rows) == 1
        r = rows[0]
        assert r["weaving_quality_map_id"] == 50
        assert r["weaving_quality_id"] == 5  # driven by the map
        assert r["machine_id"] == 7
        assert r["shift_bucket"] == "A"
        assert r["cuts"] == 10.0  # joined from the view
        assert r["weaving_daily_id"] == 10
        assert r["production_yds"] == 1075.0  # view-computed
        assert r["jugar"] == 172.0

        # rollup: SUM(production_yds) / SUM(std_prod_yds) * 100 = 1075 / 1200 * 100.
        rollup = payload["shift_rollup"]
        assert len(rollup) == 1
        assert rollup[0]["shift_bucket"] == "A"
        assert rollup[0]["efficiency"] == round(1075.0 / 1200.0 * 100, 2)

    def test_mapped_loom_no_entry_coalesces_zero(self):
        """A mapped loom with no saved entry (NULL view columns) still appears, coalesced to 0."""
        driver_rows = [
            _mock_row({
                "weaving_quality_map_id": 51, "machine_id": 8, "spell_id": 1,
                "spell_code": "A1", "mech_code": "L02", "machine_name": "Loom-2",
                "line_no": "1", "branch_id": 2, "item_id": 10, "item_code": "JC",
                "item_name": "Jute Cloth", "weaving_quality_id": 5,
                "weaving_quality_code": "Q5", "weaving_quality_name": "Red",
                "finished_length": 100.0, "ozs_yds": 10.0, "std_ozs_yds": 10.0,
                "no_of_jugar_per_cut": 16.0, "is_composite": 0,
                # no entry -> the LEFT JOIN view columns are NULL:
                "weaving_daily_id": None, "cuts": None, "close_jugar": None,
                "less_production": None, "open_jugar": None, "jugar": None,
                "production_yds": None, "production_kg": None,
                "std_prod_yds": None, "efficiency": None,
            }),
        ]
        driver_exec = MagicMock(); driver_exec.fetchall.return_value = driver_rows
        self._mock_session.execute.side_effect = [driver_exec]

        response = client.get(
            "/api/weavingProd/planning_grid?co_id=1&tran_date=2026-06-21"
        )

        assert response.status_code == 200
        r = response.json()["data"]["rows"][0]
        assert r["weaving_daily_id"] is None
        assert r["cuts"] == 0.0
        assert r["production_yds"] == 0.0
        assert r["jugar"] == 0.0

    def test_missing_co_id_returns_400(self):
        response = client.get("/api/weavingProd/planning_grid?tran_date=2026-06-21")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_missing_tran_date_returns_400(self):
        response = client.get("/api/weavingProd/planning_grid?co_id=1")
        assert response.status_code == 400
        assert "tran_date" in response.json()["detail"].lower()
