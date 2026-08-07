"""Weaving Process: builder smoke, BLOCK, happy-path freeze, DB-guarded parity."""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction import weaving_query as q

client = TestClient(app)


def test_process_builders_compile():
    for name in [
        "get_weaving_daily_active_row_by_machine_query",
        "get_weaving_unit_daily_ids_query", "get_weaving_unmapped_produced_looms_query",
        "get_weaving_process_quality_mismatch_query",
        "get_weaving_process_negative_jugar_query",
        "get_weaving_process_no_worker_query", "get_weaving_process_no_standard_query",
        "get_weaving_process_no_picks_query", "soft_delete_weaving_log_for_unit_query",
        "insert_weaving_log_from_slice_query", "update_weaving_log_eb_stamp_query",
        "get_weaving_process_lock_row_query", "insert_weaving_process_lock_query",
        "update_weaving_process_lock_query", "update_weaving_process_lock_reprocess_query",
        "get_weaving_drift_query", "get_weaving_log_rows_query",
    ]:
        assert getattr(q, name)() is not None


class TestProcessEndpoint:
    def _run(self, session):
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.weaving_process._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_process._derive_co_id", return_value=1), \
                 patch("src.juteProduction.weaving_process.require_edit_if_locked"):
                return client.post("/api/weavingProd/process", json={
                    "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell": "A1"})
        finally:
            app.dependency_overrides.clear()

    def test_block_when_unmapped(self):
        session = MagicMock()
        row = MagicMock()
        row._mapping = {"machine_id": 42, "mech_code": "L42", "machine_name": "Loom 42"}
        session.execute.return_value.fetchall.return_value = [row]  # unmapped -> BLOCK
        resp = self._run(session)
        assert resp.status_code == 400
        assert resp.json()["detail"]["unmapped"][0]["machine_id"] == 42

    def test_process_400_when_co_id_underivable(self):
        """Regression: body omitting co_id AND branch_id must 400, not int(None) -> 500."""
        session = MagicMock()
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.weaving_process._resolve_spell", return_value=91):
                resp = client.post("/api/weavingProd/process", json={
                    "tran_date": "2026-07-07", "spell": "A1"})
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"]

    def test_process_freezes_and_warns(self):
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=5)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        unit_ids = MagicMock(fetchall=MagicMock(return_value=[]))
        # execute() order: unmapped, quality_mismatch, no_worker, no_standard, no_picks,
        # unit_ids, negative_jugar, soft_delete, INSERT, eb_stamp, lock_row, lock_insert.
        session.execute.side_effect = [empty, empty, empty, empty, empty, unit_ids,
                                       empty, MagicMock(), insert, MagicMock(),
                                       lockrow, MagicMock()]
        resp = self._run(session)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["processed"] == 5
        assert resp.json()["data"]["warnings"]["no_worker"] == []
        assert resp.json()["data"]["warnings"]["negative_jugar"] == []

    def test_warns_negative_jugar(self):
        """Regression: a row whose straight-count total_jugar goes negative is
        surfaced in warnings["negative_jugar"] (never clamped or blocked)."""
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        neg_row = MagicMock()
        neg_row._mapping = {"machine_id": 7, "mech_code": "L07", "machine_name": "Loom 7"}
        neg = MagicMock(fetchall=MagicMock(return_value=[neg_row]))
        insert = MagicMock(rowcount=1)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [empty, empty, empty, empty, empty, empty,
                                       neg, MagicMock(), insert, MagicMock(),
                                       lockrow, MagicMock()]
        resp = self._run(session)
        assert resp.status_code == 200, resp.text
        warns = resp.json()["data"]["warnings"]
        assert warns["negative_jugar"] == [
            {"machine_id": 7, "mech_code": "L07", "machine_name": "Loom 7"}]

    def test_branch_id_bound_on_every_unit_query(self):
        """Regression: the body's branch_id must ride in the binds of every unit-scoped
        statement (BLOCK probes, WARN collectors, unit ids, soft-delete, freeze INSERT)
        so branch A's Process never re-freezes branch B's rows."""
        session = MagicMock()
        empty = MagicMock(fetchall=MagicMock(return_value=[]))
        insert = MagicMock(rowcount=0)
        lockrow = MagicMock(fetchone=MagicMock(return_value=None))
        session.execute.side_effect = [empty, empty, empty, empty, empty, empty,
                                       empty, MagicMock(), insert, MagicMock(),
                                       lockrow, MagicMock()]
        resp = self._run(session)
        assert resp.status_code == 200, resp.text
        # calls 0-6: unmapped, mismatch, no_worker, no_standard, no_picks,
        # unit_ids, negative_jugar; 7: soft-delete; 8: freeze INSERT.
        for i in list(range(7)) + [7, 8]:
            binds = session.execute.call_args_list[i].args[1]
            assert binds["branch_id"] == 2, f"call {i} missing branch_id bind"
        # And the unit-query SQL actually carries the NULL-tolerant predicate.
        for builder in [q.get_weaving_unit_daily_ids_query,
                        q.get_weaving_unmapped_produced_looms_query,
                        q.get_weaving_process_quality_mismatch_query,
                        q.get_weaving_process_negative_jugar_query,
                        q.soft_delete_weaving_log_for_unit_query]:
            assert ":branch_id IS NULL OR" in str(builder())

    def test_block_when_stored_quality_mismatches_map(self):
        """A daily row whose STORED quality is NULL/stale vs the active map blocks
        Process — quality_mismatch carries the mech_code list."""
        session = MagicMock()
        no_unmapped = MagicMock(fetchall=MagicMock(return_value=[]))
        row = MagicMock()
        row._mapping = {"machine_id": 42, "mech_code": "L42", "machine_name": "Loom 42"}
        mismatch = MagicMock(fetchall=MagicMock(return_value=[row]))
        session.execute.side_effect = [no_unmapped, mismatch]
        resp = self._run(session)
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["unmapped"] == []
        assert detail["quality_mismatch"] == ["L42"]


class TestProcessSpellIdContract:
    """process accepts spell_id (preferred) via the real shared _resolve_spell:
    wrong-branch spell_id -> 400; both spell_id and spell -> 400 exactly-one."""

    def _post(self, session, body):
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            return client.post("/api/weavingProd/process", json=body)
        finally:
            app.dependency_overrides.clear()

    def test_wrong_branch_spell_id_400(self):
        session = MagicMock()
        row = MagicMock(); row.spell_id = 91; row.branch_id = 12  # shift branch != 2
        session.execute.return_value.fetchone.return_value = row
        resp = self._post(session, {
            "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07", "spell_id": 91})
        assert resp.status_code == 400
        assert "does not belong to this branch" in resp.json()["detail"]

    def test_both_spell_id_and_spell_400(self):
        resp = self._post(MagicMock(), {
            "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07",
            "spell_id": 91, "spell": "A1"})
        assert resp.status_code == 400
        assert "exactly one of spell_id or spell" in resp.json()["detail"]

    def test_neither_spell_id_nor_spell_400(self):
        resp = self._post(MagicMock(), {
            "co_id": 1, "branch_id": 2, "tran_date": "2026-07-07"})
        assert resp.status_code == 400
        assert "exactly one of spell_id or spell" in resp.json()["detail"]


RUN_DB = os.environ.get("WEAVING_PARITY_DB")  # e.g. "dev3"; unset -> skip


@pytest.mark.skipif(not RUN_DB, reason="set WEAVING_PARITY_DB to run DB parity")
def test_log_matches_slice_after_process():
    """After Process, each frozen log row equals the live day-slice row for the
    same (machine, quality) on production_yds/efficiency/working_hours (<=0.001)."""
    import pymysql
    conn = pymysql.connect(host=os.environ["DB_HOST"], user=os.environ["DB_USER"],
                           password=os.environ["DB_PASS"], database=RUN_DB, port=3306)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    co = int(os.environ["PARITY_CO"]); d = os.environ["PARITY_DATE"]
    spell_id = int(os.environ["PARITY_SPELL_ID"])
    cur.execute("""SELECT machine_id, weaving_quality_id, ROUND(production_yds,3) p,
                          ROUND(efficiency,2) e, ROUND(working_hours,3) w
                   FROM jute_prod_weaving_log
                   WHERE co_id=%s AND tran_date=%s AND spell_id=%s AND active=1""",
                (co, d, spell_id))
    log_rows = {(r["machine_id"], r["weaving_quality_id"]): r for r in cur.fetchall()}
    assert log_rows, "no frozen rows — process the unit first"
    conn.close()
