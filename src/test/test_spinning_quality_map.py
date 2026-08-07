"""Spinning quality mapper endpoints (spec 5.3): grid, save validation,
preview no-write, retro_mode scoping, reprocess flagging.

Mock plumbing transposed from test_spinning_process.py: dependency_overrides
for get_tenant_db / get_current_user_with_refresh, module-path patches for
user_menu_access_level / flag_reprocess_if_locked, and MagicMock
execute-side-effect sequencing for the set-based statement order.

Save statement order (no effective_from_spell): per entry — machine validate,
item validate, next-change-point select (D2 cap), locked-units select; then
preview COUNT (confirm:false) OR mapper INSERT, helper RE-DERIVATION (D1),
capped retro UPDATE, mapper retro_rows UPDATE.
"""
from datetime import date
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

GRID = "/api/spinningProd/quality_map_grid"
SAVE = "/api/spinningProd/quality_map_save"
MOD = "src.juteProduction.spinning_quality_map"

PAYLOAD = {
    "co_id": 1,
    "branch_id": 2,
    "entries": [{"mc_id": 16, "item_id": 269876}],
    "effective_from_date": "2026-07-20",
    "retro_mode": "fill",
    "confirm": True,
}


def _sqls(session):
    return [str(c.args[0]) for c in session.execute.call_args_list]


def _override(session):
    app.dependency_overrides[get_tenant_db] = lambda: session
    app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}


def _mc_res(branch_id=2, co_id=1):
    res = MagicMock()
    res.fetchone.return_value = MagicMock(
        machine_id=16, branch_id=branch_id, co_id=co_id
    )
    return res


def _item_res():
    res = MagicMock()
    res.fetchone.return_value = MagicMock(item_id=269876)
    return res


def _next_res(row=None):
    """Next-change-point probe (D2). None = no later rule -> uncapped range."""
    res = MagicMock()
    res.fetchone.return_value = row
    return res


def _locked_res(rows=()):
    res = MagicMock()
    res.fetchall.return_value = list(rows)
    return res


def _save(session, payload):
    _override(session)
    try:
        return client.post(SAVE, json=payload)
    finally:
        app.dependency_overrides.clear()


class TestQualityMapGrid:
    def test_grid_200(self):
        """Machines (helper-joined) + yarn master list, {"data": ...} wrapped."""
        session = MagicMock()
        mc_row = MagicMock()
        mc_row._mapping = {
            "machine_id": 16, "mech_code": "S16", "machine_name": "SPINNING 16",
            "branch_id": 2, "item_id": 269876, "item_code": "Y1",
            "item_name": "8LBS-SKWP", "effective_from_date": "2026-07-15",
            "effective_from_spell_id": 5, "effective_from_spell_code": "A1",
            "mapper_rows": 3,
        }
        yarn_row = MagicMock()
        yarn_row._mapping = {"item_id": 269876, "item_code": "Y1",
                             "item_name": "8LBS-SKWP", "std_count": 8.0,
                             "std_mr_pct": 16.0}
        grid_res = MagicMock(fetchall=MagicMock(return_value=[mc_row]))
        yarn_res = MagicMock(fetchall=MagicMock(return_value=[yarn_row]))
        session.execute.side_effect = [grid_res, yarn_res]
        _override(session)
        try:
            resp = client.get(GRID + "?co_id=1&branch_id=2")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["machines"][0]["machine_id"] == 16
        assert body["machines"][0]["mapper_rows"] == 3
        assert body["yarn_items"][0]["item_id"] == 269876
        # Machine scoping mirrors get_spinning_machines_query (type by name).
        assert "machine_type_name = :spinning_type" in _sqls(session)[0]

    def test_grid_missing_co_id_400(self):
        session = MagicMock()
        _override(session)
        try:
            resp = client.get(GRID)
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 400


class TestQualityMapSaveValidation:
    def test_future_effective_date_400(self):
        """T2: future effective_from_date rejected before any DB write."""
        session = MagicMock()
        resp = _save(session, {**PAYLOAD, "effective_from_date": "2099-01-01"})
        assert resp.status_code == 400
        assert "future" in resp.json()["detail"]
        session.commit.assert_not_called()

    def test_invalid_retro_mode_400(self):
        session = MagicMock()
        resp = _save(session, {**PAYLOAD, "retro_mode": "bogus"})
        assert resp.status_code == 400
        session.commit.assert_not_called()

    def test_unknown_machine_400(self):
        """Machine not active spinning type -> 400, nothing written."""
        session = MagicMock()
        miss = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [miss]
        resp = _save(session, PAYLOAD)
        assert resp.status_code == 400
        assert "Machine 16" in resp.json()["detail"]
        session.commit.assert_not_called()

    def test_inactive_item_400(self):
        session = MagicMock()
        miss = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [_mc_res(), miss]
        resp = _save(session, PAYLOAD)
        assert resp.status_code == 400
        assert "Item 269876" in resp.json()["detail"]
        session.commit.assert_not_called()


class TestQualityMapSavePreview:
    def test_preview_counts_and_writes_nothing(self):
        """confirm:false -> COUNT only; no INSERT/UPDATE SQL, no commit."""
        session = MagicMock()
        count_res = MagicMock(scalar=MagicMock(return_value=5))
        session.execute.side_effect = [_mc_res(), _item_res(), _next_res(),
                                       _locked_res(), count_res]
        resp = _save(session, {**PAYLOAD, "confirm": False})
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body == {"mapper_ids": [], "retro_rows": 5,
                        "reprocessed_units": [], "preview": True}
        sqls = _sqls(session)
        assert not any("INSERT" in s or "UPDATE" in s for s in sqls)
        session.commit.assert_not_called()

    def test_preview_count_uses_the_same_cap(self):
        """D2: the preview COUNT carries the same next-change-point binds as
        the real retro UPDATE would."""
        session = MagicMock()
        count_res = MagicMock(scalar=MagicMock(return_value=2))
        nxt = MagicMock(next_date="2026-07-25", next_start_time="06:00:00")
        session.execute.side_effect = [_mc_res(), _item_res(), _next_res(nxt),
                                       _locked_res(), count_res]
        resp = _save(session, {**PAYLOAD, "confirm": False})
        assert resp.status_code == 200, resp.text
        count_idx = next(i for i, s in enumerate(_sqls(session))
                         if "COUNT(*)" in s)
        binds = session.execute.call_args_list[count_idx].args[1]
        assert binds["next_date"] == "2026-07-25"
        assert binds["next_start_time"] == "06:00:00"
        assert "dd.doff_date < :next_date" in _sqls(session)[count_idx]


class TestQualityMapSaveRetroScoping:
    def _commit_ok(self, payload, locked=(), access_level=4, next_row=None):
        """Run a confirm:true save; return (resp, session, flag_mock)."""
        session = MagicMock()
        ins = MagicMock(lastrowid=11)
        upd = MagicMock(rowcount=3)
        session.execute.side_effect = [_mc_res(), _item_res(),
                                       _next_res(next_row),
                                       _locked_res(locked),
                                       ins, MagicMock(), upd, MagicMock()]
        with patch(f"{MOD}.user_menu_access_level", return_value=access_level), \
             patch(f"{MOD}.flag_reprocess_if_locked") as flag:
            resp = _save(session, payload)
        return resp, session, flag

    def _retro_update(self, session):
        sqls = _sqls(session)
        idx = next(i for i, s in enumerate(sqls) if "UPDATE daily_doff_tbl" in s)
        return sqls[idx], session.execute.call_args_list[idx].args[1]

    def test_fill_scopes_to_null_item(self):
        resp, session, _ = self._commit_ok(PAYLOAD)
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["mapper_ids"] == [11]
        assert body["retro_rows"] == 3
        assert body["preview"] is False
        sql, binds = self._retro_update(session)
        assert "dd.item_id IS NULL" in sql
        assert "item_source IN" not in sql
        assert "item_source = 'mapper'" in sql  # stamped
        assert binds["mc_id"] == 16
        assert binds["item_id"] == 269876
        assert str(binds["eff_date"]) == "2026-07-20"
        assert binds["eff_start_time"] is None  # no spell = start of day
        assert binds["next_date"] is None       # no later rule -> uncapped
        assert binds["next_start_time"] is None
        # (doff_date, spell-order) grain comparison present, both bounds.
        assert "sp.starting_time >= :eff_start_time" in sql
        assert "dd.doff_date < :next_date" in sql
        session.commit.assert_called_once()

    def test_retro_capped_at_next_change_point(self):
        """D2: a backdated rule's retro range stops strictly before the
        machine's NEXT active rule — later-rule rows are never overwritten."""
        nxt = MagicMock(next_date="2026-07-25", next_start_time="06:00:00")
        resp, session, _ = self._commit_ok(PAYLOAD, next_row=nxt)
        assert resp.status_code == 200, resp.text
        sql, binds = self._retro_update(session)
        assert binds["next_date"] == "2026-07-25"
        assert binds["next_start_time"] == "06:00:00"
        assert "dd.doff_date < :next_date" in sql
        assert "sp.starting_time < :next_start_time" in sql
        # The probe compares STRICTLY greater than the save's effective point.
        nxt_idx = next(i for i, s in enumerate(_sqls(session))
                       if "next_date" in s and "spg_quality_mapper" in s)
        assert "LIMIT 1" in _sqls(session)[nxt_idx]

    def test_synced_scopes_to_helper_mapper_sources(self):
        resp, session, _ = self._commit_ok({**PAYLOAD, "retro_mode": "synced"})
        assert resp.status_code == 200, resp.text
        sql, binds = self._retro_update(session)
        assert "dd.item_source IN ('helper','mapper')" in sql  # never 'manual'
        assert binds["mc_id"] == 16
        # mapper row records the mode it applied.
        ins_idx = next(i for i, s in enumerate(_sqls(session))
                       if "INSERT INTO spg_quality_mapper" in s)
        assert session.execute.call_args_list[ins_idx].args[1]["retro_mode"] == "synced"

    def test_all_is_unscoped_and_needs_edit(self):
        resp, session, _ = self._commit_ok({**PAYLOAD, "retro_mode": "all"})
        assert resp.status_code == 200, resp.text
        sql, _binds = self._retro_update(session)
        assert "item_id IS NULL" not in sql
        assert "item_source IN" not in sql
        assert "item_source = 'mapper'" in sql

    def test_all_without_edit_403(self):
        session = MagicMock()
        with patch(f"{MOD}.user_menu_access_level", return_value=3):
            resp = _save(session, {**PAYLOAD, "retro_mode": "all"})
        assert resp.status_code == 403
        session.commit.assert_not_called()

    def test_helper_rederived_from_latest_mapper_row(self):
        """D1/T3: the helper write is a RE-DERIVATION from the machine's latest
        active mapper row (INSERT..SELECT..ON DUPLICATE KEY UPDATE ordered
        eff-date/spell-order/id DESC), in the same transaction — NOT an
        unconditional upsert of the saved rule, so a backdated save can never
        regress the helper."""
        resp, session, _ = self._commit_ok(PAYLOAD)
        assert resp.status_code == 200
        sqls = _sqls(session)
        helper_sql = next(s for s in sqls if "INSERT INTO spg_quality_helper" in s)
        assert "ON DUPLICATE KEY UPDATE" in helper_sql
        assert "FROM spg_quality_mapper" in helper_sql          # derived, not VALUES
        assert "effective_from_date DESC" in helper_sql
        assert "quality_mapper_id DESC" in helper_sql
        helper_idx = sqls.index(helper_sql)
        binds = session.execute.call_args_list[helper_idx].args[1]
        assert binds["mc_id"] == 16
        session.commit.assert_called_once()


class TestQualityMapSaveEffectiveSpell:
    """spell_id-first contract for effective_from_spell (branch-scoped)."""

    def test_effective_from_spell_id_accepted(self):
        session = MagicMock()
        spell_val = MagicMock(fetchone=MagicMock(
            return_value=MagicMock(spell_id=5, branch_id=2)))
        start = MagicMock(fetchone=MagicMock(
            return_value=MagicMock(starting_time="06:00:00")))
        ins = MagicMock(lastrowid=11)
        upd = MagicMock(rowcount=3)
        session.execute.side_effect = [spell_val, start, _mc_res(), _item_res(),
                                       _next_res(), _locked_res(),
                                       ins, MagicMock(), upd, MagicMock()]
        with patch(f"{MOD}.user_menu_access_level", return_value=4), \
             patch(f"{MOD}.flag_reprocess_if_locked"):
            resp = _save(session, {**PAYLOAD, "effective_from_spell_id": 5})
        assert resp.status_code == 200, resp.text
        val_sql = _sqls(session)[0]
        assert "sp.spell_id = :spell_id" in val_sql
        ins_idx = next(i for i, s in enumerate(_sqls(session))
                       if "INSERT INTO spg_quality_mapper" in s)
        assert session.execute.call_args_list[ins_idx].args[1]["eff_spell_id"] == 5

    def test_effective_from_spell_id_wrong_branch_400(self):
        session = MagicMock()
        spell_val = MagicMock(fetchone=MagicMock(
            return_value=MagicMock(spell_id=91, branch_id=4)))  # branch 4 spell
        session.execute.side_effect = [spell_val]
        resp = _save(session, {**PAYLOAD, "effective_from_spell_id": 91})
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Spell does not belong to this branch"
        session.commit.assert_not_called()

    def test_effective_spell_code_fallback_branch_scoped(self):
        """Deprecated code path resolves via shift_mst scoped to body branch —
        never the unscoped MIN()."""
        session = MagicMock()
        spell_res = MagicMock(fetchone=MagicMock(
            return_value=MagicMock(spell_id=97)))
        start = MagicMock(fetchone=MagicMock(
            return_value=MagicMock(starting_time="06:00:00")))
        count_res = MagicMock(scalar=MagicMock(return_value=0))
        session.execute.side_effect = [spell_res, start, _mc_res(), _item_res(),
                                       _next_res(), _locked_res(), count_res]
        resp = _save(session, {**PAYLOAD, "effective_from_spell": "A1",
                               "confirm": False})
        assert resp.status_code == 200, resp.text
        res_sql = _sqls(session)[0]
        assert "shift_mst" in res_sql
        assert "sh.branch_id = :branch_id" in res_sql
        assert "MIN(" not in res_sql
        assert session.execute.call_args_list[0].args[1]["branch_id"] == 2

    def test_both_effective_spell_inputs_400(self):
        session = MagicMock()
        resp = _save(session, {**PAYLOAD, "effective_from_spell": "A1",
                               "effective_from_spell_id": 5})
        assert resp.status_code == 400
        assert "exactly one" in resp.json()["detail"].lower()
        session.commit.assert_not_called()


class TestQualityMapSaveReprocess:
    LOCKED = MagicMock(tran_date=date(2026, 7, 21), spell_id=5)

    def test_locked_units_flagged_for_reprocess_with_machine_co(self):
        """Retro range crossing a locked unit -> explicit flag per unit +
        unit reported in reprocessed_units (drift is blind to item swaps).
        The flag keys on the MACHINE's spine-derived co (D3a), not the body."""
        resp, session, flag = (
            TestQualityMapSaveRetroScoping()._commit_ok(PAYLOAD,
                                                        locked=[self.LOCKED]))
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["reprocessed_units"] == [{"tran_date": "2026-07-21",
                                              "spell_id": 5}]
        flag.assert_called_once()
        args = flag.call_args.args
        assert args[1] == 1  # machine-spine co (mc_res co_id=1)
        assert args[2] == "2026-07-21"  # tran_date
        assert args[3] == 5  # spell_id

    def test_locked_units_use_machine_spine_co_not_body(self):
        """D3a: a bogus body co_id cannot dodge the lock gate — the
        locked-units lookup binds the machine's own co."""
        resp, session, flag = (
            TestQualityMapSaveRetroScoping()._commit_ok(
                {**PAYLOAD, "co_id": 999}, locked=[self.LOCKED]))
        assert resp.status_code == 200, resp.text
        sqls = _sqls(session)
        locked_idx = next(i for i, s in enumerate(sqls)
                          if "jute_prod_spinning_process_lock" in s)
        binds = session.execute.call_args_list[locked_idx].args[1]
        assert binds["co_id"] == 1  # machine spine, NOT the body's 999
        assert flag.call_args.args[1] == 1

    def test_locked_crossing_without_edit_403(self):
        session = MagicMock()
        session.execute.side_effect = [_mc_res(), _item_res(), _next_res(),
                                       _locked_res([self.LOCKED])]
        with patch(f"{MOD}.user_menu_access_level", return_value=3), \
             patch(f"{MOD}.flag_reprocess_if_locked") as flag:
            resp = _save(session, PAYLOAD)
        assert resp.status_code == 403
        flag.assert_not_called()
        session.commit.assert_not_called()

    def test_preview_reports_locked_units_without_403(self):
        """Preview shows the would-be reprocessed units even for a Write-only
        user (the FE prompt needs the count); the gate applies on commit."""
        session = MagicMock()
        count_res = MagicMock(scalar=MagicMock(return_value=2))
        session.execute.side_effect = [_mc_res(), _item_res(), _next_res(),
                                       _locked_res([self.LOCKED]), count_res]
        with patch(f"{MOD}.user_menu_access_level", return_value=3):
            resp = _save(session, {**PAYLOAD, "confirm": False})
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        assert body["preview"] is True
        assert body["reprocessed_units"] == [{"tran_date": "2026-07-21",
                                              "spell_id": 5}]
        session.commit.assert_not_called()
