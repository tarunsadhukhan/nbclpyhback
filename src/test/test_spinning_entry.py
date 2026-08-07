"""Endpoint tests for src/juteProduction/spinning_entry.py.

The spinning routers are not (yet) mounted on the main app, so we build a
local FastAPI app, include the router under its production prefix, and use
dependency_overrides for get_tenant_db + get_current_user_with_refresh —
the same override style as test_drawing_entry.py.

Covers the spec 5.2 stamping paths (manual/helper/mapper/null), the 5.4
doff_sync (fill vs force, manual protection, ambiguity reporting), the 6-W10
exact-only dedup, and the 7.x weight fixes (bobbin<=0 B5, weight-only
recompute, machine-derived co).
"""

from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.spinning_entry import (
    router as spinning_entry_router,
    DOFF_NET_RANGE_MSG,
    NO_MACHINE_ATTR_MSG,
    TROLLY_SCOPE_MSG,
)

app = FastAPI()
app.include_router(spinning_entry_router, prefix="/api/spinningProd")
client = TestClient(app)

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _row(**attrs):
    """A MagicMock whose attributes are the given kwargs (for .fetchone() rows)."""
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    return row


def _mapping_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    for k, v in mapping.items():
        setattr(row, k, v)
    return row


def _fetchone(row):
    r = MagicMock()
    r.fetchone.return_value = row
    return r


def _fetchall(rows):
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _rowcount(n):
    r = MagicMock()
    r.rowcount = n
    return r


def _scalar(v):
    r = MagicMock()
    r.scalar.return_value = v
    return r


def _exec_params(mock_session, call_index: int) -> dict:
    return mock_session.execute.call_args_list[call_index][0][1]


def _exec_sql(mock_session, call_index: int) -> str:
    return str(mock_session.execute.call_args_list[call_index][0][0])


class SpinningEntryBase:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _sqls(self):
        return [str(c.args[0]) for c in self._mock_session.execute.call_args_list]


# Shared canned rows -----------------------------------------------------------

SPELL_ROW = _row(spell_id=1)
MACHINE_ROW = _row(branch_id=4, co_id=1)  # _machine_branch_co
TROLLY_ROW = _row(
    trolly_id=7, trolly_weight=10.0, busket_weight=2.0,
    branch_id=4, machine_type_name="Spinning",
)
BOBBIN_ROW = _row(value=0.5)
# Helper row whose rule is effective well in the past -> fast path applies (D4).
HELPER_ROW = _row(item_id=42, item_name="Yarn 42",
                  effective_from_date=date(2000, 1, 1),
                  effective_start_time=None)
# Overnight probe result for a plain day spell (doff_entry_create D5 check).
OVERNIGHT_OFF_ROW = _row(is_overnight=0, end_time=None)


# =============================================================================
# doff_entry_create_setup
# =============================================================================


class TestDoffEntryCreateSetup(SpinningEntryBase):
    def test_missing_co_id(self):
        resp = client.get("/api/spinningProd/doff_entry_create_setup")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_missing_branch_id(self):
        # branch_id is required: without it the setup would silently return
        # every branch's machines/trollies/spells.
        resp = client.get("/api/spinningProd/doff_entry_create_setup?co_id=1")
        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()

    def test_setup_returns_sections(self):
        machine = _mapping_row(
            {"machine_id": 5, "machine_name": "Spinning-1", "mech_code": "SP01",
             "branch_id": 4}
        )
        spell = _mapping_row(
            {"spell_code": "A1", "spell_name": "A1", "spell_id": 1, "working_hours": 8.0}
        )
        trolly = _mapping_row(
            {"trolly_id": 7, "trolly_name": "T-7", "trolly_weight": 10.0,
             "bucket_weight": 2.0}
        )
        quality = _mapping_row(
            {"item_id": 9, "item_code": "Q9", "item_name": "Quality 9",
             "std_count": 12.0, "std_mr_pct": 13.75}
        )
        # Order: batch bobbin, machines, spells, trollies, qualities.
        self._mock_session.execute.side_effect = [
            _fetchall([_row(machine_id=5, bobbin_weight=0.5)]),
            _fetchall([machine]),
            _fetchall([spell]),
            _fetchall([trolly]),
            _fetchall([quality]),
        ]
        resp = client.get("/api/spinningProd/doff_entry_create_setup?co_id=1&branch_id=4")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["machines"][0]["bobbin_weight"] == 0.5
        assert data["spells"][0]["spell_code"] == "A1"
        assert data["trollies"][0]["bucket_weight"] == 2.0
        assert data["yarn_items"][0]["item_id"] == 9


# =============================================================================
# doff_entry_create — stamping paths (spec 5.2) + weight guards (spec 7)
# =============================================================================


class TestDoffEntryCreate(SpinningEntryBase):
    def _body(self, **over):
        b = {
            "co_id": 1,
            "branch_id": 4,
            "tran_date": TODAY,
            "spell": "A1",
            "machine_id": 5,
            "trolly_id": 7,
            "gross_weight": 50.0,
        }
        b.update(over)
        return b

    def test_create_manual_item_stamped(self):
        # item_id in body -> item_source='manual', no helper/mapper query.
        insert_result = MagicMock()
        insert_result.lastrowid = 99
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),    # 0 machine branch/co (feeds spell scope)
            _fetchone(SPELL_ROW),      # 1 resolve spell (branch-scoped code fallback)
            _fetchone(TROLLY_ROW),     # 2 trolly (scope-checked)
            _fetchone(BOBBIN_ROW),     # 3 bobbin
            _fetchone(None),           # 4 lock probe -> unlocked
            insert_result,             # 5 INSERT
            MagicMock(),               # 6 flag_reprocess
            _fetchone(OVERNIGHT_OFF_ROW),  # 7 overnight probe (D5)
        ]
        resp = client.post(
            "/api/spinningProd/doff_entry_create", json=self._body(item_id=9)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["daily_doff_tbl_id"] == 99
        assert data["tare_weight"] == 12.5   # 10 + 2 + 0.5
        assert data["net_weight"] == 37.5
        assert data["item_id"] == 9
        assert data["item_source"] == "manual"
        assert "unmapped_machine" not in data
        assert "overnight_date_warning" not in data
        ins = _exec_params(self._mock_session, 5)
        assert ins["item_id"] == 9
        assert ins["item_source"] == "manual"
        assert "NOW()" in _exec_sql(self._mock_session, 5)  # dead-column fix
        assert not any("spg_quality" in s for s in self._sqls())

    def test_create_today_stamps_from_helper(self):
        insert_result = MagicMock()
        insert_result.lastrowid = 100
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                # lock
            _fetchone(HELPER_ROW),          # helper lookup (effective in past)
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),   # overnight probe (D5)
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["item_id"] == 42
        assert data["item_source"] == "helper"
        assert any("spg_quality_helper" in s for s in self._sqls())
        assert not any("spg_quality_mapper" in s for s in self._sqls())

    def test_create_today_helper_effective_later_spell_falls_to_mapper(self):
        """D4: helper rule effective TODAY from a LATER spell must not stamp an
        earlier spell's doff — the fast path falls through to the mapper as-of."""
        insert_result = MagicMock()
        insert_result.lastrowid = 103
        later_helper = _row(item_id=42, item_name="Yarn 42",
                            effective_from_date=date.today(),
                            effective_start_time="14:00:00")
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                                   # lock
            _fetchone(later_helper),                           # helper lookup
            _fetchone(_row(starting_time="06:00:00")),         # doff _spell_start
            _fetchone(_row(item_id=55, item_name="Yarn 55")),  # mapper as-of
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["item_id"] == 55
        assert data["item_source"] == "mapper"
        assert any("spg_quality_mapper" in s for s in self._sqls())

    def test_create_today_helper_effective_earlier_spell_applies(self):
        """D4 counterpart: same-day helper rule effective from an EARLIER
        spell (or day-start) stamps normally via the fast path."""
        insert_result = MagicMock()
        insert_result.lastrowid = 104
        same_day_helper = _row(item_id=42, item_name="Yarn 42",
                               effective_from_date=date.today(),
                               effective_start_time="06:00:00")
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                              # lock
            _fetchone(same_day_helper),                   # helper lookup
            _fetchone(_row(starting_time="14:00:00")),    # doff _spell_start
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["item_id"] == 42
        assert data["item_source"] == "helper"
        assert not any("spg_quality_mapper" in s for s in self._sqls())

    def test_create_backdated_stamps_from_mapper_asof(self):
        # T1: backdated entry resolves as-of from the mapper log, NOT the helper.
        insert_result = MagicMock()
        insert_result.lastrowid = 101
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                                    # lock
            _fetchone(_row(starting_time="06:00:00")),          # _spell_start
            _fetchone(_row(item_id=55, item_name="Yarn 55")),   # mapper as-of
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),                       # overnight probe
        ]
        resp = client.post(
            "/api/spinningProd/doff_entry_create", json=self._body(tran_date=YESTERDAY)
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["item_id"] == 55
        assert data["item_source"] == "mapper"
        assert any("spg_quality_mapper" in s for s in self._sqls())
        assert not any("spg_quality_helper" in s for s in self._sqls())

    def test_create_unmapped_machine_inserts_null_and_warns(self):
        # T4: helper row missing -> item NULL + unmapped_machine warn.
        insert_result = MagicMock()
        insert_result.lastrowid = 102
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),      # lock
            _fetchone(None),      # helper lookup -> nothing
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["item_id"] is None
        assert data["item_source"] is None
        assert data["unmapped_machine"] is True
        ins = _exec_params(self._mock_session, 6)
        assert ins["item_id"] is None
        assert ins["item_source"] is None

    def test_create_overnight_tail_dated_today_warns(self):
        """D5/T12: overnight spell, server clock in the post-midnight tail,
        tran_date = today -> soft `overnight_date_warning` (saved, not
        rejected — convention is shift-START date)."""
        from datetime import datetime as real_datetime, time as dt_time
        from unittest.mock import patch as mock_patch

        insert_result = MagicMock()
        insert_result.lastrowid = 105
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                 # lock
            insert_result,                   # INSERT (manual item, no helper)
            MagicMock(),                     # flag
            _fetchone(_row(is_overnight=1,
                           end_time=timedelta(hours=6))),  # overnight probe
        ]
        fixed_now = real_datetime.combine(date.today(), dt_time(1, 30))
        with mock_patch("src.juteProduction.spinning_entry.datetime") as dt:
            dt.now.return_value = fixed_now
            resp = client.post(
                "/api/spinningProd/doff_entry_create", json=self._body(item_id=9)
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["overnight_date_warning"] is True

    def test_create_bobbin_missing_rejected_400(self):
        # B5 / 7.2: resolved bobbin <= 0 must refuse, never save tare-understated.
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(_row(value=0.0)),  # bobbin standard 0
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 400
        assert resp.json()["detail"] == NO_MACHINE_ATTR_MSG

    def test_create_trolly_wrong_branch_rejected_400(self):
        # 7.6: trolly of another branch refused at save time.
        wrong_trolly = _row(
            trolly_id=7, trolly_weight=10.0, busket_weight=2.0,
            branch_id=99, machine_type_name="Spinning",
        )
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(wrong_trolly),
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 400
        assert resp.json()["detail"] == TROLLY_SCOPE_MSG

    def test_create_net_out_of_range_rejected(self):
        heavy_trolly = _row(
            trolly_id=7, trolly_weight=40.0, busket_weight=20.0,
            branch_id=4, machine_type_name="Spinning",
        )
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(heavy_trolly),
            _fetchone(BOBBIN_ROW),
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 400
        assert resp.json()["detail"] == DOFF_NET_RANGE_MSG

    def test_create_unknown_spell_rejected(self):
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(None),  # branch-scoped code lookup: no match
        ]
        resp = client.post("/api/spinningProd/doff_entry_create", json=self._body())
        assert resp.status_code == 400
        assert "spell" in resp.json()["detail"].lower()

    def test_create_accepts_spell_id(self):
        # spell_id-first contract: body carries spell_id (no code string); the
        # resolver validates existence + branch and stamps that exact id.
        insert_result = MagicMock()
        insert_result.lastrowid = 106
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),                     # machine branch/co
            _fetchone(_row(spell_id=97, branch_id=4)),  # spell_id validation
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),                            # lock
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        body = self._body(item_id=9)
        del body["spell"]
        body["spell_id"] = 97
        resp = client.post("/api/spinningProd/doff_entry_create", json=body)
        assert resp.status_code == 200, resp.text
        val_sql = _exec_sql(self._mock_session, 1)
        assert "sp.spell_id = :spell_id" in val_sql
        assert _exec_params(self._mock_session, 1)["spell_id"] == 97
        assert _exec_params(self._mock_session, 5)["spell_id"] == 97  # stamped as given

    def test_create_spell_id_wrong_branch_400(self):
        # A spell_id whose shift belongs to another branch is refused.
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),                      # machine branch 4
            _fetchone(_row(spell_id=91, branch_id=99)),  # spell of branch 99
        ]
        body = self._body()
        del body["spell"]
        body["spell_id"] = 91
        resp = client.post("/api/spinningProd/doff_entry_create", json=body)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Spell does not belong to this branch"

    def test_create_code_fallback_is_branch_scoped(self):
        # Deprecated code path resolves through shift_mst scoped to the branch
        # (sls 'A1' repeats per branch) — never the unscoped MIN().
        insert_result = MagicMock()
        insert_result.lastrowid = 107
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(TROLLY_ROW),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        resp = client.post(
            "/api/spinningProd/doff_entry_create", json=self._body(item_id=9)
        )
        assert resp.status_code == 200, resp.text
        res_sql = _exec_sql(self._mock_session, 1)
        assert "shift_mst" in res_sql
        assert "sh.branch_id = :branch_id" in res_sql
        assert "MIN(" not in res_sql
        assert _exec_params(self._mock_session, 1)["branch_id"] == 4

    def test_create_both_spell_inputs_400(self):
        self._mock_session.execute.side_effect = [_fetchone(MACHINE_ROW)]
        resp = client.post(
            "/api/spinningProd/doff_entry_create", json=self._body(spell_id=97)
        )
        assert resp.status_code == 400
        assert "exactly one" in resp.json()["detail"].lower()

    def test_create_trolly_type_check_case_insensitive(self):
        # sls stores 'SPINNING' (upper) — must pass the scope check.
        upper_trolly = _row(
            trolly_id=7, trolly_weight=10.0, busket_weight=2.0,
            branch_id=4, machine_type_name="SPINNING",
        )
        insert_result = MagicMock()
        insert_result.lastrowid = 108
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(upper_trolly),
            _fetchone(BOBBIN_ROW),
            _fetchone(None),
            insert_result,
            MagicMock(),
            _fetchone(OVERNIGHT_OFF_ROW),
        ]
        resp = client.post(
            "/api/spinningProd/doff_entry_create", json=self._body(item_id=9)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["tare_weight"] == 12.5


# =============================================================================
# doff_entry_edit — weight-only recompute (7.3), machine-derived co (7.4),
# manual identity stamps
# =============================================================================


EXISTING_DOFF = dict(
    daily_doff_tbl_id=99, mc_id=5, trolly_id=7, gross_weight=50.0,
    tare_weight=12.5, net_weight=37.5, item_id=9,
    doff_date="2026-06-11", spell=1, branch_id=4,
)


class TestDoffEntryEdit(SpinningEntryBase):
    def test_edit_gross_recomputes_weights(self):
        self._mock_session.execute.side_effect = [
            _fetchone(_row(**EXISTING_DOFF)),  # existing
            _fetchone(MACHINE_ROW),            # machine co/branch (co matches)
            _fetchone(None),                   # lock probe
            _fetchone(TROLLY_ROW),             # trolly (weights touched)
            _fetchone(BOBBIN_ROW),             # bobbin
            MagicMock(),                       # UPDATE
            MagicMock(),                       # flag
        ]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/99?co_id=1", json={"gross_weight": 55.0}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["tare_weight"] == 12.5
        assert data["net_weight"] == 42.5
        upd_sql = _exec_sql(self._mock_session, 5)
        assert "gross_weight" in upd_sql
        assert "updated_date_time = NOW()" in upd_sql

    def test_edit_item_only_keeps_stored_weights(self):
        # 7.3: item-only edit must NOT recompute from current trolly weights,
        # must NOT run validate_net, and stamps item_source='manual'.
        self._mock_session.execute.side_effect = [
            _fetchone(_row(**EXISTING_DOFF)),
            _fetchone(MACHINE_ROW),
            _fetchone(None),      # lock probe
            MagicMock(),          # UPDATE
            MagicMock(),          # flag
        ]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/99?co_id=1", json={"item_id": 33}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["tare_weight"] == 12.5  # stored, untouched
        assert data["net_weight"] == 37.5
        assert not any("trolly_mst" in s for s in self._sqls())
        assert not any("jute_prod_spng_target_map" in s for s in self._sqls())
        upd_sql = _exec_sql(self._mock_session, 3)
        assert "item_source = 'manual'" in upd_sql
        assert "gross_weight" not in upd_sql
        assert _exec_params(self._mock_session, 3)["item_id"] == 33

    def test_edit_eb_only_stamps_manual_source(self):
        self._mock_session.execute.side_effect = [
            _fetchone(_row(**EXISTING_DOFF)),
            _fetchone(MACHINE_ROW),
            _fetchone(None),
            MagicMock(),
            MagicMock(),
        ]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/99?co_id=1", json={"eb_id": 777}
        )
        assert resp.status_code == 200, resp.text
        upd_sql = _exec_sql(self._mock_session, 3)
        assert "eb_source = 'manual'" in upd_sql
        assert "net_weight" not in upd_sql
        assert _exec_params(self._mock_session, 3)["eb_id"] == 777

    def test_edit_co_mismatch_404(self):
        # 7.4: co derived from the entry's machine; caller-supplied co_id that
        # mismatches must 404 (no lock-gate bypass, no wrong-co bobbin).
        self._mock_session.execute.side_effect = [
            _fetchone(_row(**EXISTING_DOFF)),
            _fetchone(_row(branch_id=4, co_id=2)),  # machine belongs to co 2
        ]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/99?co_id=1", json={"gross_weight": 55.0}
        )
        assert resp.status_code == 404

    def test_edit_not_found_404(self):
        self._mock_session.execute.side_effect = [_fetchone(None)]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/1?co_id=1", json={"gross_weight": 55.0}
        )
        assert resp.status_code == 404


# =============================================================================
# NULL-spell legacy rows (edit + delete must not 500 on the lock gate/flag)
# =============================================================================


class TestDoffEntryNullSpell(SpinningEntryBase):
    """Legacy daily_doff_tbl rows can carry a NULL spell. Edit/delete of such a
    row must succeed without touching the lock gate/flag — int(None) would 500,
    and a NULL-spell row can't belong to any processed unit anyway."""

    def test_edit_null_spell_skips_gate_and_flag(self):
        existing = dict(EXISTING_DOFF, spell=None)
        self._mock_session.execute.side_effect = [
            _fetchone(_row(**existing)),
            _fetchone(MACHINE_ROW),
            _fetchone(TROLLY_ROW),   # weights touched -> trolly
            _fetchone(BOBBIN_ROW),   # bobbin
            MagicMock(),             # UPDATE
        ]
        resp = client.put(
            "/api/spinningProd/doff_entry_edit/99?co_id=1",
            json={"gross_weight": 50.0, "trolly_id": 7, "item_id": 9},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["net_weight"] == 37.5  # 50 - (10+2+0.5)
        assert not any("jute_prod_spinning_process_lock" in s for s in self._sqls())

    def test_delete_null_spell_skips_gate_and_flag(self):
        self._mock_session.execute.side_effect = [
            _fetchone(_row(daily_doff_tbl_id=99, mc_id=5, doff_date="2026-06-11",
                           spell=None, branch_id=4)),
            _fetchone(MACHINE_ROW),  # machine-derived co (7.4)
            MagicMock(),             # UPDATE active=0
        ]
        resp = client.delete("/api/spinningProd/doff_entry_delete/99?co_id=1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["message"] == "Deleted"
        assert not any("jute_prod_spinning_process_lock" in s for s in self._sqls())


class TestDoffEntryDelete(SpinningEntryBase):
    def test_delete_co_mismatch_404(self):
        self._mock_session.execute.side_effect = [
            _fetchone(_row(daily_doff_tbl_id=99, mc_id=5, doff_date="2026-06-11",
                           spell=1, branch_id=4)),
            _fetchone(_row(branch_id=4, co_id=2)),
        ]
        resp = client.delete("/api/spinningProd/doff_entry_delete/99?co_id=1")
        assert resp.status_code == 404


# =============================================================================
# doff_dedup_run — exact duplicates only (spec 6 W10)
# =============================================================================


DUP_ROWS = [
    _row(daily_doff_tbl_id=11, mc_id=5, keep_id=10,
         gross_weight=50.0, tare_weight=12.5, net_weight=37.5),
    _row(daily_doff_tbl_id=12, mc_id=5, keep_id=10,
         gross_weight=50.0, tare_weight=12.5, net_weight=37.5),
]


class TestDoffDedupRun(SpinningEntryBase):
    def test_dedup_confirm_deactivates_exact_duplicates(self):
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),      # resolve spell
            _fetchall(DUP_ROWS),       # exact-dup candidates
            _fetchone(None),           # lock probe (confirm path)
            MagicMock(),               # deactivate UPDATE
            MagicMock(),               # flag
        ]
        resp = client.post(
            "/api/spinningProd/doff_dedup_run",
            json={"co_id": 1, "tran_date": "2026-06-11", "spell": "A1",
                  "confirm": True},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["preview"] is False
        assert data["deactivated"] == 2
        assert data["deactivated_ids"] == [11, 12]
        # Exact-duplicate grouping (mc + trolly + gross + tare), lowest id kept,
        # co-scoped via the machine spine (D3c).
        sel_sql = _exec_sql(self._mock_session, 1)
        assert "MIN(di.daily_doff_tbl_id)" in sel_sql
        assert "trolly_id" in sel_sql and "gross_weight" in sel_sql
        assert "HAVING COUNT(*) > 1" in sel_sql
        assert "co_id = :co_id" in sel_sql
        assert _exec_params(self._mock_session, 1)["co_id"] == 1

    def test_dedup_preview_lists_candidates_without_deactivating(self):
        """D8: confirm:false (the default) returns the candidate rows with
        weights and writes NOTHING."""
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),
            _fetchall(DUP_ROWS),
        ]
        resp = client.post(
            "/api/spinningProd/doff_dedup_run",
            json={"co_id": 1, "tran_date": "2026-06-11", "spell": "A1"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["preview"] is True
        assert data["deactivated"] == 0
        assert data["deactivated_ids"] == []
        assert data["candidates"] == [
            {"daily_doff_tbl_id": 11, "mc_id": 5, "keep_id": 10,
             "gross_weight": 50.0, "tare_weight": 12.5, "net_weight": 37.5},
            {"daily_doff_tbl_id": 12, "mc_id": 5, "keep_id": 10,
             "gross_weight": 50.0, "tare_weight": 12.5, "net_weight": 37.5},
        ]
        assert not any("UPDATE" in s for s in self._sqls())
        self._mock_session.commit.assert_not_called()

    def test_dedup_no_duplicates_touches_nothing(self):
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),
            _fetchall([]),
            _fetchone(None),   # lock probe
        ]
        resp = client.post(
            "/api/spinningProd/doff_dedup_run",
            json={"co_id": 1, "tran_date": "2026-06-11", "spell": "A1",
                  "confirm": True},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"] == {"preview": False, "deactivated": 0,
                                       "deactivated_ids": []}
        assert len(self._mock_session.execute.call_args_list) == 3  # no UPDATE ran


# =============================================================================
# doff_sync (spec 5.4)
# =============================================================================


def _sync_body(**over):
    b = {
        "co_id": 1,
        "branch_id": 4,
        "tran_date": "2026-06-11",
        "spell": "A1",
        "mode": "fill",
        "targets": ["quality", "operator"],
    }
    b.update(over)
    return b


class TestDoffSync(SpinningEntryBase):
    def test_fill_sync_stamps_and_reports_exceptions(self):
        # The spinner-designation gate runs in SQL now, so machine 7's
        # off-designation worker never reaches Python — mc 7 has doff rows but
        # no candidate, which is exactly the doffs_no_operator case.
        candidates = [
            # machine 5: TWO spinner candidates -> ambiguous, lowest atten wins
            _row(mc_id=5, eb_id=102, daily_atten_id=1001),
            _row(mc_id=5, eb_id=101, daily_atten_id=1000),
            # machine 6: one candidate
            _row(mc_id=6, eb_id=103, daily_atten_id=1002),
        ]
        scope = [
            _row(mc_id=5, doff_rows=2, null_item_rows=0, null_eb_rows=0),
            _row(mc_id=6, doff_rows=1, null_item_rows=0, null_eb_rows=1),
            _row(mc_id=7, doff_rows=2, null_item_rows=1, null_eb_rows=2),
        ]
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),                          # 0 resolve spell
            _fetchone(None),                               # 1 lock probe
            _fetchone(_row(starting_time="06:00:00")),     # 2 _spell_start
            _rowcount(2),                                  # 3 quality stamp
            _fetchall(candidates),                         # 4 candidates
            _rowcount(1),                                  # 5 stamp mc 5
            _rowcount(1),                                  # 6 stamp mc 6
            _fetchall(scope),                              # 7 scope summary
            _fetchall([_row(machine_id=5, bobbin_weight=0.5)]),  # 8 bobbin batch
            MagicMock(),                                   # 9 flag
        ]
        resp = client.post("/api/spinningProd/doff_sync", json=_sync_body())
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["quality_stamped"] == 2
        assert data["operator_stamped"] == 2
        exc = data["exceptions"]
        assert exc["machines_unmapped"] == [7]
        assert exc["doffs_no_operator"] == 3
        # W4: ambiguous machine reported even though the cascade resolved it.
        assert exc["operator_ambiguous"] == [
            {"machine_id": 5, "eb_ids": [101, 102], "stamped_eb_id": 101}
        ]
        assert exc["item_overridden"] == []
        assert exc["bobbin_missing"] == [6, 7]
        # W7 collector present; every attended machine here has doffs.
        assert exc["attendance_no_doffs"] == []
        # fill mode: quality stamp targets NULL item rows; force bind = 0;
        # co-scope rides the machine spine (D3b).
        q_sql = _exec_sql(self._mock_session, 3)
        assert "item_id IS NULL" in q_sql
        assert "co_id = :co_id" in q_sql
        assert _exec_params(self._mock_session, 3)["force"] == 0
        assert _exec_params(self._mock_session, 3)["co_id"] == 1
        # Candidates are gated on the spinner designation prefix, spell joins on
        # spell_id (never the repeating spell name).
        c_sql = _exec_sql(self._mock_session, 4)
        assert "LIKE :desig_prefix" in c_sql
        assert "da.spell_id = :spell_id" in c_sql
        assert "da.spell = " not in c_sql
        assert _exec_params(self._mock_session, 4)["desig_prefix"] == "spinner%"
        assert _exec_params(self._mock_session, 4)["ignore_designation"] == 0
        # manual rows are protected in the operator stamp SQL in ANY mode.
        o_sql = _exec_sql(self._mock_session, 5)
        assert "'manual'" in o_sql
        assert "co_id = :co_id" in o_sql
        assert _exec_params(self._mock_session, 5)["eb_id"] == 101  # lowest atten
        assert _exec_params(self._mock_session, 5)["co_id"] == 1

    def test_force_sync_requires_edit_level(self):
        # B6: mode=force without Edit (level < 4) -> 403, nothing stamped.
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),
            _fetchone(None),   # lock probe
            _scalar(3),        # user_menu_access_level -> Write only
        ]
        resp = client.post(
            "/api/spinningProd/doff_sync", json=_sync_body(mode="force")
        )
        assert resp.status_code == 403
        assert not any("daily_doff_tbl" in s for s in self._sqls())

    def test_force_sync_reports_item_overridden_and_protects_manual(self):
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),                        # 0 resolve spell
            _fetchone(None),                             # 1 lock probe
            _scalar(4),                                  # 2 access level: Edit
            _fetchone(_row(starting_time="06:00:00")),   # 3 _spell_start
            _fetchall([_row(daily_doff_tbl_id=9, mc_id=5,
                            old_item_id=100, new_item_id=200)]),  # 4 preview
            _rowcount(3),                                # 5 quality stamp
            _fetchall([_row(mc_id=5, doff_rows=3,
                            null_item_rows=0, null_eb_rows=0)]),  # 6 scope
            _fetchall([_row(machine_id=5, bobbin_weight=0.5)]),   # 7 bobbin
            MagicMock(),                                 # 8 flag
        ]
        resp = client.post(
            "/api/spinningProd/doff_sync",
            json=_sync_body(mode="force", targets=["quality"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["quality_stamped"] == 3
        assert data["operator_stamped"] == 0
        assert data["exceptions"]["item_overridden"] == [
            {"daily_doff_tbl_id": 9, "machine_id": 5,
             "old_item_id": 100, "new_item_id": 200}
        ]
        # force stamp still excludes manual rows — in EVERY mode.
        q_sql = _exec_sql(self._mock_session, 5)
        assert "item_source <> 'manual'" in q_sql
        assert _exec_params(self._mock_session, 5)["force"] == 1

    def test_fill_sync_reports_attendance_no_doffs(self):
        """W7 (D6): a machine with an active spinner attendance candidate but
        ZERO doff rows in the unit is reported {machine_id, mech_code,
        eb_ids}."""
        candidates = [
            _row(mc_id=8, eb_id=104, daily_atten_id=1004),
        ]
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),                          # 0 resolve spell
            _fetchone(None),                               # 1 lock probe
            _fetchone(_row(starting_time="06:00:00")),     # 2 _spell_start
            _rowcount(0),                                  # 3 quality stamp
            _fetchall(candidates),                         # 4 candidates
            _rowcount(0),                                  # 5 stamp mc 8 (no rows)
            _fetchall([_row(mc_id=5, doff_rows=1,          # 6 scope: only mc 5
                            null_item_rows=0, null_eb_rows=0)]),
            _fetchall([_row(machine_id=8, mech_code="S08")]),    # 7 mech lookup (W7)
            _fetchall([_row(machine_id=5, bobbin_weight=0.5)]),  # 8 bobbin batch
            MagicMock(),                                   # 9 flag
        ]
        resp = client.post("/api/spinningProd/doff_sync", json=_sync_body())
        assert resp.status_code == 200, resp.text
        exc = resp.json()["data"]["exceptions"]
        assert exc["attendance_no_doffs"] == [
            {"machine_id": 8, "mech_code": "S08", "eb_ids": [104]}
        ]

    def test_invalid_mode_rejected(self):
        resp = client.post(
            "/api/spinningProd/doff_sync", json=_sync_body(mode="nuke")
        )
        assert resp.status_code == 400

    def test_empty_targets_rejected(self):
        resp = client.post(
            "/api/spinningProd/doff_sync", json=_sync_body(targets=["bogus"])
        )
        assert resp.status_code == 400


class TestFrameMapMappedDelegate(SpinningEntryBase):
    def test_mapped_delegates_to_sync_and_keeps_keys(self):
        self._mock_session.execute.side_effect = [
            _fetchone(SPELL_ROW),                        # resolve spell
            _fetchone(None),                             # lock probe
            _fetchone(_row(starting_time="06:00:00")),   # _spell_start
            _rowcount(4),                                # quality stamp
            _fetchall([]),                               # candidates: none
            _fetchall([]),                               # scope summary
            _fetchall([]),                               # bobbin batch
            MagicMock(),                                 # flag
        ]
        resp = client.post(
            "/api/spinningProd/frame_map_mapped",
            json={"co_id": 1, "branch_id": 4, "tran_date": "2026-06-11", "spell": "A1"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["quality_stamped"] == 4
        assert data["operator_stamped"] == 0
        assert "exceptions" in data
        # The delegate stamps from the MAPPER, not the retired frames_winding map.
        assert any("spg_quality_mapper" in s for s in self._sqls())
        assert not any("daily_doff_frames_winding" in s for s in self._sqls())


# =============================================================================
# doff_entries_by_date — own-item resolution + unsynced counts
# =============================================================================


class TestDoffEntriesByDate(SpinningEntryBase):
    def test_rows_and_unsynced_counts(self):
        rows = [
            _mapping_row({"daily_doff_tbl_id": 1, "doff_date": "2026-06-11",
                          "item_id": 9, "eb_id": 101, "eb_name": "A Worker",
                          "item_source": "helper", "eb_source": "sync",
                          "gross_weight": 50.0, "tare_weight": 12.5,
                          "net_weight": 37.5}),
            _mapping_row({"daily_doff_tbl_id": 2, "doff_date": "2026-06-11",
                          "item_id": None, "eb_id": None, "eb_name": None,
                          "item_source": None, "eb_source": None,
                          "gross_weight": 51.0, "tare_weight": 12.5,
                          "net_weight": 38.5}),
        ]
        self._mock_session.execute.side_effect = [_fetchall(rows)]
        resp = client.get(
            "/api/spinningProd/doff_entries_by_date?co_id=1&tran_date=2026-06-11"
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"][0]["eb_name"] == "A Worker"
        assert body["data"][0]["item_source"] == "helper"
        assert body["unsynced"] == {"no_item": 1, "no_eb": 1}
        # Item resolves from the row's OWN item_id only — fallback removed.
        sql = _exec_sql(self._mock_session, 0)
        assert "daily_doff_frames_winding" not in sql
        assert "hrms_ed_personal_details" in sql


# =============================================================================
# doff_editor_setup (spec 5.8)
# =============================================================================


class TestDoffEditorSetup(SpinningEntryBase):
    def test_returns_yarns_and_workers(self):
        yarn = _mapping_row({"item_id": 9, "item_code": "Q9", "item_name": "Quality 9",
                             "std_count": 12.0, "std_mr_pct": None})
        # worker_name arrives already concatenated — the picker renders it as-is.
        worker = _row(eb_id=101, worker_name="E-101 - A Worker")
        self._mock_session.execute.side_effect = [
            _fetchall([yarn]),
            _fetchall([worker]),
        ]
        resp = client.get("/api/spinningProd/doff_editor_setup?co_id=1&branch_id=4")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["yarn_items"][0]["item_id"] == 9
        assert data["workers"] == [
            {"eb_id": 101, "worker_name": "E-101 - A Worker"}
        ]

    def test_missing_co_id_400(self):
        resp = client.get("/api/spinningProd/doff_editor_setup")
        assert resp.status_code == 400


# =============================================================================
# doff_machine_prev_state — mapped_item prefill (spec 5.3 FE note)
# =============================================================================


class TestDoffMachinePrevState(SpinningEntryBase):
    def test_today_returns_helper_mapped_item(self):
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),                              # machine branch/co
            _fetchone(SPELL_ROW),                                # resolve spell
            _fetchone(_row(total_net=42.5, doff_count=3)),       # running total
            _fetchone(HELPER_ROW),                               # helper lookup
        ]
        resp = client.get(
            "/api/spinningProd/doff_machine_prev_state"
            f"?co_id=1&machine_id=5&tran_date={TODAY}&spell=A1"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["running_total_net"] == 42.5
        assert data["next_doff_no"] == 4
        assert data["mapped_item_id"] == 42
        assert data["mapped_item_name"] == "Yarn 42"
        assert any("spg_quality_helper" in s for s in self._sqls())

    def test_backdated_resolves_mapped_item_from_mapper(self):
        self._mock_session.execute.side_effect = [
            _fetchone(MACHINE_ROW),
            _fetchone(SPELL_ROW),
            _fetchone(_row(total_net=0.0, doff_count=0)),
            _fetchone(_row(starting_time="06:00:00")),          # _spell_start
            _fetchone(_row(item_id=55, item_name="Yarn 55")),   # mapper as-of
        ]
        resp = client.get(
            "/api/spinningProd/doff_machine_prev_state"
            f"?co_id=1&machine_id=5&tran_date={YESTERDAY}&spell=A1"
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["mapped_item_id"] == 55
        assert any("spg_quality_mapper" in s for s in self._sqls())
        assert not any("spg_quality_helper" in s for s in self._sqls())
