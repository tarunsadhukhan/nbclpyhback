"""Spinning Process + status endpoints: fill-sync, BLOCK, freeze/lock, reprocess, drift.

Mock plumbing transposed from test_weaving_process.py: dependency_overrides for
get_tenant_db / get_current_user_with_refresh, module-path patches for
_resolve_spell_id / require_edit_if_locked / get_process_lock / _run_doff_sync /
_spell_name, and MagicMock execute-side-effect sequencing for the set-based
statement order.

/process execute order (with sync + spell-name patched): unmapped B1 probe,
attendance_inactive W11 probe, no_standard, no_count, soft-delete, INSERT
freeze, lock probe, lock INSERT/UPDATE.
"""
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

PAYLOAD = {"co_id": 1, "branch_id": 2, "tran_date": "2026-07-01", "spell": "A1"}

SYNC_RESULT = {
    "quality_stamped": 0,
    "operator_stamped": 0,
    "exceptions": {
        "machines_unmapped": [],
        "doffs_no_operator": 0,
        "operator_ambiguous": [],
        "item_overridden": [],
        "bobbin_missing": [],
    },
}


def _sqls(session):
    return [str(c.args[0]) for c in session.execute.call_args_list]


class TestProcessEndpoint:
    def _run(self, session, sync_result=None):
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.spinning_process._resolve_spell", return_value=91), \
                 patch("src.juteProduction.spinning_process.require_edit_if_locked"), \
                 patch("src.juteProduction.spinning_process._run_doff_sync",
                       return_value=sync_result or SYNC_RESULT) as sync_mock:
                resp = client.post("/api/spinningProd/process", json=PAYLOAD)
                return resp, sync_mock
        finally:
            app.dependency_overrides.clear()

    def test_process_blocks_on_unmapped_produced_machine(self):
        """A doff row still item_id NULL after fill-sync blocks Process (400,
        B1) and no freeze runs — but the sync itself DID run first (spec 5.4)."""
        session = MagicMock()
        row = MagicMock()
        row._mapping = {"machine_id": 42, "mech_code": "S42"}
        session.execute.return_value.fetchall.return_value = [row]  # unmapped -> BLOCK
        resp, sync_mock = self._run(session)
        assert resp.status_code == 400
        assert resp.json()["detail"]["unmapped"][0]["machine_id"] == 42
        sync_mock.assert_called_once()  # fill-sync ran before the block
        assert sync_mock.call_args.kwargs["mode"] == "fill"
        assert sync_mock.call_args.kwargs["targets"] == ["quality", "operator"]
        session.commit.assert_not_called()  # no INSERT / freeze committed

    def test_process_freezes_and_locks(self):
        """Unmapped empty + WARN probes empty -> soft-delete, INSERT...SELECT freeze
        (rowcount 7), and a fresh lock INSERT (no prior lock). Warnings carry the
        sync counts + W3 + W11."""
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=7)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        # execute() order: unmapped, attendance_inactive, no_standard, no_count,
        # soft_delete, INSERT, lock_row, lock_insert.
        session.execute.side_effect = [empty, empty, empty, empty, MagicMock(),
                                       insert, lockrow, MagicMock()]
        resp, _ = self._run(session)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["processed"] == 7
        assert resp.json()["data"]["warnings"] == {
            "no_standard": [],
            "no_count": [],
            "sync": {"quality_stamped": 0, "operator_stamped": 0},
            "doffs_no_operator": 0,       # W3
            "attendance_inactive": [],    # W11
        }
        sqls = _sqls(session)
        soft_idx = next(i for i, s in enumerate(sqls) if "SET active = 0" in s)
        ins_idx = next(i for i, s in enumerate(sqls) if "INSERT INTO jute_prod_spinning_daily" in s)
        assert soft_idx < ins_idx  # soft-delete precedes freeze
        assert any("INSERT INTO jute_prod_spinning_process_lock" in s for s in sqls)
        session.commit.assert_called_once()

    def test_process_surfaces_sync_counts_and_w3_w11(self):
        """Sync stamped counts, W3 doffs-no-operator and the W11
        attendance-inactive rows all land in the warnings dict."""
        session = MagicMock()
        w11_row = MagicMock()
        w11_row._mapping = {"daily_doff_tbl_id": 9, "machine_id": 10, "eb_id": 77}
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        w11 = MagicMock(fetchall=MagicMock(return_value=[w11_row]))
        insert = MagicMock(rowcount=2)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [empty, w11, empty, empty, MagicMock(),
                                       insert, lockrow, MagicMock()]
        sync_result = {
            "quality_stamped": 3,
            "operator_stamped": 5,
            "exceptions": {**SYNC_RESULT["exceptions"], "doffs_no_operator": 2},
        }
        resp, _ = self._run(session, sync_result=sync_result)
        assert resp.status_code == 200, resp.text
        warns = resp.json()["data"]["warnings"]
        assert warns["sync"] == {"quality_stamped": 3, "operator_stamped": 5}
        assert warns["doffs_no_operator"] == 2
        assert warns["attendance_inactive"] == [
            {"daily_doff_tbl_id": 9, "machine_id": 10, "eb_id": 77}
        ]

    def test_process_lock_probe_is_branch_scoped(self):
        """Branch-B Process (PAYLOAD branch_id=2) probes the lock header
        branch-scoped: the probe SQL carries the branch predicate and the
        executed probe binds branch_id=2, so a branch-A header is not matched
        -> a fresh branch-B INSERT runs (not an UPDATE of A's header)."""
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=4)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))  # no branch-B header
        session.execute.side_effect = [empty, empty, empty, empty, MagicMock(),
                                       insert, lockrow, MagicMock()]
        resp, _ = self._run(session)
        assert resp.status_code == 200, resp.text
        sqls = _sqls(session)
        probe_idx = next(
            i for i, s in enumerate(sqls)
            if "SELECT spinning_process_lock_id FROM jute_prod_spinning_process_lock" in s
        )
        assert "branch_id = :branch_id" in sqls[probe_idx]  # branch predicate present
        probe_binds = session.execute.call_args_list[probe_idx][0][1]
        assert probe_binds.get("branch_id") == 2  # branch B carried into the probe
        # No prior branch-B header -> fresh INSERT, not an UPDATE of another branch.
        assert any("INSERT INTO jute_prod_spinning_process_lock" in s for s in sqls)

    def test_process_reprocess_updates_existing_lock(self):
        """A prior lock row -> lock UPDATE, never a second INSERT."""
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=3)
        prior = MagicMock()
        prior.spinning_process_lock_id = 55
        lockrow = MagicMock(fetchone=MagicMock(return_value=prior))
        session.execute.side_effect = [empty, empty, empty, empty, MagicMock(),
                                       insert, lockrow, MagicMock()]
        resp, _ = self._run(session)
        assert resp.status_code == 200, resp.text
        sqls = _sqls(session)
        assert any("is_locked = 1, reprocess_needed = 0" in s for s in sqls)  # lock UPDATE
        assert not any("INSERT INTO jute_prod_spinning_process_lock" in s for s in sqls)

    def test_process_unknown_spell_400(self):
        """_resolve_spell (unpatched) finds no spell -> 400 before any freeze."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = None  # spell_mst miss
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            resp = client.post("/api/spinningProd/process", json=PAYLOAD)
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 400

    def _run_unpatched_resolver(self, session, payload):
        """Run /process with the real _resolve_spell (only sync/lock patched)."""
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.spinning_process.require_edit_if_locked"), \
                 patch("src.juteProduction.spinning_process._run_doff_sync",
                       return_value=SYNC_RESULT):
                return client.post("/api/spinningProd/process", json=payload)
        finally:
            app.dependency_overrides.clear()

    def test_process_accepts_spell_id(self):
        """spell_id body field validated (exists + branch) and used directly —
        no spell_code lookup, no unscoped MIN()."""
        session = MagicMock()
        spell_row = MagicMock(spell_id=97, branch_id=2)
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=5)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        # execute order: spell_id validation, unmapped, attendance_inactive,
        # no_standard, no_count, soft_delete, INSERT, lock_row, lock_insert.
        session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=spell_row)),
            empty, empty, empty, empty, MagicMock(), insert, lockrow, MagicMock(),
        ]
        payload = {"co_id": 1, "branch_id": 2, "tran_date": "2026-07-01",
                   "spell_id": 97}
        resp = self._run_unpatched_resolver(session, payload)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["processed"] == 5
        val_sql = _sqls(session)[0]
        assert "sp.spell_id = :spell_id" in val_sql
        binds = session.execute.call_args_list[0][0][1]
        assert binds["spell_id"] == 97

    def test_process_spell_id_wrong_branch_400(self):
        """A spell_id whose shift belongs to another branch -> 400, no freeze."""
        session = MagicMock()
        spell_row = MagicMock(spell_id=91, branch_id=4)  # branch 4 spell
        session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=spell_row)),
        ]
        payload = {"co_id": 1, "branch_id": 2, "tran_date": "2026-07-01",
                   "spell_id": 91}
        resp = self._run_unpatched_resolver(session, payload)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Spell does not belong to this branch"
        session.commit.assert_not_called()

    def test_process_code_fallback_is_branch_scoped(self):
        """Deprecated spell-code path resolves via shift_mst scoped to the
        body branch — sls 'A1' must land on the caller's branch spell."""
        session = MagicMock()
        spell_row = MagicMock(spell_id=97)
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=1)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=spell_row)),
            empty, empty, empty, empty, MagicMock(), insert, lockrow, MagicMock(),
        ]
        resp = self._run_unpatched_resolver(session, PAYLOAD)
        assert resp.status_code == 200, resp.text
        res_sql = _sqls(session)[0]
        assert "shift_mst" in res_sql
        assert "sh.branch_id = :branch_id" in res_sql
        assert "MIN(" not in res_sql
        binds = session.execute.call_args_list[0][0][1]
        assert binds["branch_id"] == 2  # body branch scopes the lookup

    def test_process_both_spell_inputs_400(self):
        session = MagicMock()
        resp = self._run_unpatched_resolver(
            session, {**PAYLOAD, "spell_id": 97})
        assert resp.status_code == 400
        assert "exactly one" in resp.json()["detail"].lower()


class TestProcessStatusEndpoint:
    def _get(self, session, patches, query):
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patches:
                return client.get("/api/spinningProd/process_status" + query)
        finally:
            app.dependency_overrides.clear()

    def test_process_status_unlocked(self):
        """No active lock -> locked False, reprocess_needed False, no timestamp."""
        session = MagicMock()
        with patch("src.juteProduction.spinning_process._resolve_spell", return_value=91), \
             patch("src.juteProduction.spinning_process.get_process_lock", return_value=None):
            resp = self._get(session, _noop(),
                             "?co_id=1&tran_date=2026-07-01&spell=A1")
        assert resp.status_code == 200
        assert resp.json()["data"] == {"locked": False, "reprocess_needed": False,
                                       "processed_date_time": None}

    def test_process_status_drift_flags_reprocess(self):
        """Locked with reprocess_needed=0 + drift row present -> reprocess UPDATE
        executed, reprocess_needed True, and processed_date_time surfaced from
        the lock row (spec 5.6.3)."""
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = MagicMock()  # drift row
        lock = MagicMock(is_locked=1, reprocess_needed=0,
                         processed_date_time="2026-07-01 14:05:00")
        lock.spinning_process_lock_id = 77
        with patch("src.juteProduction.spinning_process._resolve_spell", return_value=91), \
             patch("src.juteProduction.spinning_process.get_process_lock", return_value=lock):
            resp = self._get(session, _noop(),
                             "?co_id=1&tran_date=2026-07-01&spell=A1")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["locked"] is True
        assert body["reprocess_needed"] is True
        assert body["processed_date_time"] == "2026-07-01 14:05:00"
        assert any("SET reprocess_needed = 1" in s for s in _sqls(session))

    def test_process_status_missing_params_400(self):
        """tran_date omitted -> 400 (before spell resolution)."""
        session = MagicMock()
        resp = self._get(session, _noop(), "?co_id=1&spell=A1")
        assert resp.status_code == 400


class _noop:
    """A do-nothing context manager for the no-patch status test."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
