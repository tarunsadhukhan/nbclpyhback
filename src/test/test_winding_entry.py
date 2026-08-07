"""Tests for Winding production entry endpoints.

Tests for src/juteProduction/winding_entry.py (prefix /api/windingProd), which is
PERSON-keyed per docs/winding-person-keyed-entry-spec.md: every doff / jugar /
quality row is identified by ``eb_id`` (the winder) and no machine appears on any
entry form.

Portal persona: dependencies get_tenant_db + get_current_user_with_refresh are
overridden via app.dependency_overrides (same pattern as test_yarn_quality.py).
The DB session is a MagicMock; rows expose a dict ._mapping. Spells resolve via
spinning_entry._resolve_spell: spell_id preferred (validated against its shift's
branch), spell code deprecated branch-scoped fallback (mocked via fetchone()).

Coverage follows the spec §9 checklist:
* net = gross - trolly - spool; net <= 0 -> 400; out-of-range net -> 400
* doff_create writes ONE row per winder (no machine_id / no_of_machines, eb_id set):
  one weighing shared by N winders deducts the tare once and splits the net equally,
  the shares summing back to net_total; the 1..500 gate applies to each row's SHARE
* unknown eb_id -> 400; missing eb_id -> 422 (pydantic)
* branch derived from the worker when the body omits it
* doff_by_date returns emp_code / worker_name and keeps rows whose worker does not
  resolve in HRMS (deleted/deactivated employee) instead of dropping them
* quality_setup seeds carried-forward PERSONS, is idempotent, seeds nothing with
  no prior spell
* quality_add duplicate -> 400; quality_delete soft-deletes
* the quality map (and ONLY it) carries a machine: quality_setup lists Winding-type
  machines, quality_add / quality_save forward machine_id (None when omitted)
* jugar is ONE entry with two fields: jugar_save upserts opening and/or closing
  (a stored side is updated, never a duplicate 400); jugar_state prefills each
  side from the saved row, else the previous spell's closing in spell-sequence
  order, else a previous opening
* branch_id is the SCOPE KEY of every winding read (co_id no longer filters):
  the day grids 400 without it, and a winder whose HRMS record has no branch is
  rejected at the write boundary
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.winding_query import (
    auto_seed_quality_query,
    get_doff_by_date_query,
    insert_doff_row_query,
    soft_delete_doff_group_query,
)

client = TestClient(app)


def _mock_row(mapping: dict):
    """A query row whose ._mapping is a plain dict (matches r._mapping usage)."""
    row = MagicMock()
    row._mapping = mapping
    return row


def _spell_row(spell_id: int = 7):
    """Code-fallback resolve query fetchone() returns a row with .spell_id."""
    row = MagicMock()
    row.spell_id = spell_id
    return row


def _spell_branch_row(spell_id: int = 7, branch_id: int = 1):
    """spell_id-validation query fetchone() row (.spell_id + .branch_id)."""
    row = MagicMock()
    row.spell_id = spell_id
    row.branch_id = branch_id
    return row


def _worker_row(branch_id: int = 1):
    """derive_branch_for_worker_query().fetchone() row (.branch_id)."""
    row = MagicMock()
    row.branch_id = branch_id
    return row


def _doff_group_row(doff_id: int, eb_id: int, gross_input_wt: float):
    """One active share of a weighing, as get_doff_group_rows_query returns it."""
    row = MagicMock()
    row.winding_doff_id = doff_id
    row.eb_id = eb_id
    row.gross_input_wt = gross_input_wt
    return row


def _trolly_row(trolly_weight: float):
    """get_winding_trolly_query().fetchone() returns a row with .trolly_weight."""
    row = MagicMock()
    row.trolly_weight = trolly_weight
    return row


_UNSET = object()


def _exec_result(*, fetchall=_UNSET, fetchone=_UNSET, scalar=_UNSET, lastrowid=_UNSET):
    """Build a MagicMock execute() result with the given return values.

    Uses an _UNSET sentinel so an explicit ``fetchone=None`` (e.g. "no duplicate
    found") is honored rather than leaving fetchone() returning a truthy mock.
    """
    res = MagicMock()
    if fetchall is not _UNSET:
        res.fetchall.return_value = fetchall
    if fetchone is not _UNSET:
        res.fetchone.return_value = fetchone
    if scalar is not _UNSET:
        res.scalar.return_value = scalar
    if lastrowid is not _UNSET:
        res.lastrowid = lastrowid
    return res


_WORKER_PICKER_ROW = _mock_row(
    {
        "eb_id": 2413,
        "emp_code": "02413",
        "worker_name": "LAXMI DEBI",
        "designation": "WINDER SPOOL",
        "label": "02413 - LAXMI DEBI",
    }
)
_YARN_ROW = _mock_row(
    {
        "item_id": 5,
        "item_code": "Q5",
        "item_name": "Q Five",
        "std_count": 12.0,
        "std_mr_pct": 13.75,
    }
)
_TROLLY_PICKER_ROW = _mock_row(
    {"trolly_id": 3, "trolly_name": "T-3", "trolly_weight": 2.0, "bucket_weight": 0.5}
)
_SPOOL_PICKER_ROW = _mock_row(
    {"trolly_id": 4, "trolly_name": "S-4", "trolly_weight": 1.0, "bucket_weight": 0.2}
)
_SPELL_PICKER_ROW = _mock_row(
    {"spell_code": "A1", "spell_name": "Shift A1", "spell_id": 7, "working_hours": 5.0}
)
_MACHINE_PICKER_ROW = _mock_row(
    {
        "machine_id": 61,
        "machine_name": "WINDING 1",
        "mech_code": "W-01",
        "dept_id": 53,
        "dept_name": "WINDING",
        "branch_id": 1,
    }
)


class TestWindingEntryEndpoints:
    """Tests for Winding doff / jugar / quality API endpoints."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _params_of(self, index: int) -> dict:
        """Bind params of the index-th db.execute() call."""
        return self._mock_session.execute.call_args_list[index].args[1]

    # --------------------------------------------------------------- Workers
    def test_workers_returns_hrms_picker_rows(self):
        """GET /workers returns eb_id/emp_code/worker_name/designation/label."""
        self._mock_session.execute.return_value.fetchall.return_value = [_WORKER_PICKER_ROW]

        response = client.get("/api/windingProd/workers?co_id=1&branch_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[0]["eb_id"] == 2413
        assert data[0]["label"] == "02413 - LAXMI DEBI"
        assert data[0]["designation"] == "WINDER SPOOL"
        # Branch-scoped, no search, default limit.
        assert self._params_of(0) == {"branch_id": 1, "search": None, "limit": 200}

    def test_workers_search_is_wrapped_in_wildcards(self):
        self._mock_session.execute.return_value.fetchall.return_value = []

        response = client.get("/api/windingProd/workers?co_id=1&search=LAXMI&limit=50")

        assert response.status_code == 200
        assert self._params_of(0) == {"branch_id": None, "search": "%LAXMI%", "limit": 50}

    def test_workers_missing_co_id(self):
        response = client.get("/api/windingProd/workers")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    # ------------------------------------------------------------------ Doff
    def test_doff_setup_success(self):
        """doff_setup returns workers/yarn_items/trollies/spools/spells — no machines."""
        # Order of execute().fetchall(): workers, yarn, trollies, spools, spells
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_WORKER_PICKER_ROW],
            [_YARN_ROW],
            [_TROLLY_PICKER_ROW],
            [_SPOOL_PICKER_ROW],
            [_SPELL_PICKER_ROW],
        ]

        response = client.get("/api/windingProd/doff_setup?co_id=1&branch_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" not in data
        assert data["workers"][0]["eb_id"] == 2413
        assert data["yarn_items"][0]["item_id"] == 5
        assert data["trollies"][0]["bucket_weight"] == 0.5
        assert data["spools"][0]["trolly_id"] == 4
        assert data["spells"][0]["spell_id"] == 7

    def test_winding_setup_filters_trollies_by_machine_type(self):
        """Both get_winding_trollies_query calls must pass machine_type_name='Winding'."""
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_WORKER_PICKER_ROW],
            [_YARN_ROW],
            [_TROLLY_PICKER_ROW],
            [_SPOOL_PICKER_ROW],
            [_SPELL_PICKER_ROW],
        ]

        response = client.get("/api/windingProd/doff_setup?co_id=1&branch_id=1")
        assert response.status_code == 200

        winding_calls = [
            c.args[1]
            for c in self._mock_session.execute.call_args_list
            if isinstance(c.args[1], dict) and "trolly_type" in c.args[1]
        ]
        assert winding_calls, "expected winding trolley queries"
        assert all(p.get("machine_type_name") == "Winding" for p in winding_calls)
        assert {p["trolly_type"] for p in winding_calls} == {"T", "S"}

    def test_doff_setup_missing_co_id(self):
        response = client.get("/api/windingProd/doff_setup")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_doff_prev_state_is_keyed_on_the_winder(self):
        """/doff_prev_state (renamed from /doff_machine_prev_state) takes eb_id."""
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {
                "winding_doff_id": 101,
                "tran_date": "2026-06-01",
                "spell_id": 7,
                "eb_id": 2413,
                "item_id": 5,
                "trolly_id": 3,
                "trolly_wt": 2.0,
                "spool_id": 4,
                "spool_wt": 1.0,
                "gross_input_wt": 100.0,
                "production_qty": 97.0,
            }
        )

        response = client.get("/api/windingProd/doff_prev_state?co_id=1&eb_id=2413")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["eb_id"] == 2413
        assert data["trolly_wt"] == 2.0
        assert self._params_of(0)["eb_id"] == 2413

    def test_doff_prev_state_requires_eb_id(self):
        response = client.get("/api/windingProd/doff_prev_state?co_id=1")
        assert response.status_code == 400
        assert "eb_id" in response.json().get("detail", "").lower()

    def test_doff_create_writes_exactly_one_person_keyed_row(self):
        """One weighing = one row: eb_id set, machine_id / no_of_machines absent."""
        # execute() order: worker branch, resolve spell, trolly, spool, insert,
        # weighing-group stamp.
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(lastrowid=101),
            _exec_result(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        # net = 100 - 2 - 1 = 97, all of it on the single winder's row
        assert data == {
            "winding_doff_ids": [101],
            "winding_doff_id": 101,
            "weighing_id": 101,
            "net_total": 97.0,
            "net_per_row": 97.0,
            "net": 97.0,
            "row_gross_wt": 100.0,
        }
        assert "net_per_mc" not in data

        insert_params = self._params_of(4)
        assert insert_params["eb_id"] == 2413
        assert insert_params["production_qty"] == 97.0
        assert "machine_id" not in insert_params
        assert "no_of_machines" not in insert_params
        # A solo weighing is still stamped, so edit/delete key off it uniformly.
        assert self._params_of(5) == {"ids": [101], "weighing_id": 101}
        # Exactly one insert (6 statements: 4 lookups + insert + group stamp).
        assert self._mock_session.execute.call_count == 6

    def test_doff_create_splits_one_weighing_across_several_winders(self):
        """One weighing shared by N winders: N rows, tare deducted ONCE, the
        shares summing back to net_total (last row takes the remainder)."""
        # execute() order: 3x worker branch, resolve spell, trolly, spool,
        # 3x insert, weighing-group stamp.
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(lastrowid=101),
            _exec_result(lastrowid=102),
            _exec_result(lastrowid=103),
            _exec_result(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_ids": [2413, 2414, 2415],
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        # net_total = 100 - 2 - 1 = 97; 97/3 = 32.333 with 32.334 on the last row
        assert data["winding_doff_ids"] == [101, 102, 103]
        assert data["winding_doff_id"] == 101  # kept for compatibility
        assert data["net_total"] == 97.0
        assert data["net_per_row"] == 32.333
        assert data["net"] == 32.333

        inserts = [self._params_of(i) for i in (6, 7, 8)]
        assert [p["eb_id"] for p in inserts] == [2413, 2414, 2415]
        assert [p["production_qty"] for p in inserts] == [32.333, 32.333, 32.334]
        # No kg lost or invented, on either the net or the weighed gross.
        assert round(sum(p["production_qty"] for p in inserts), 3) == 97.0
        assert round(sum(p["gross_input_wt"] for p in inserts), 3) == 100.0
        # The tare describes the shared trolly/spool — stored in FULL on each row.
        assert all(p["trolly_wt"] == 2.0 and p["spool_wt"] == 1.0 for p in inserts)
        assert all("machine_id" not in p and "no_of_machines" not in p for p in inserts)
        # All three shares tied to the first row's id, so edit/delete see the
        # whole weighing instead of one winder's slice of it.
        assert data["weighing_id"] == 101
        assert self._params_of(9) == {"ids": [101, 102, 103], "weighing_id": 101}
        # All three rows in ONE transaction.
        assert self._mock_session.commit.call_count == 1

    def test_doff_create_gates_the_share_not_the_total(self):
        """A 4-way split whose total is a valid net but whose share falls below
        WINDING_NET_MIN (1 kg) is rejected — and nothing is written."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_ids": [2413, 2414, 2415, 2416],
            "trolly_id": 3,
            "spool_id": 4,
            "gross_weight": 5.0,  # net_total 2.0 is in range; 2/4 = 0.5 per row is not
            "quality_id": 5,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "range" in response.json().get("detail", "").lower()
        # 4 worker lookups + spell + trolly + spool, then the gate — no insert.
        assert self._mock_session.execute.call_count == 7
        assert self._mock_session.commit.call_count == 0

    def test_doff_create_unknown_eb_id_in_the_list_returns_400(self):
        """Any unknown winder in the selection aborts the whole weighing."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=None),  # the second eb_id resolves to nothing
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_ids": [2413, 999999],
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "eb_id" in response.json().get("detail", "").lower()
        assert self._mock_session.execute.call_count == 2
        assert self._mock_session.commit.call_count == 0

    def test_doff_create_duplicate_eb_ids_collapse_to_one_row(self):
        """The same winder selected twice is still one row with the whole net."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(lastrowid=101),
            _exec_result(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_ids": [2413, 2413],
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["winding_doff_ids"] == [101]
        assert data["net_total"] == 97.0 and data["net_per_row"] == 97.0
        assert self._params_of(4)["production_qty"] == 97.0
        assert self._mock_session.execute.call_count == 6

    def test_doff_insert_sql_never_writes_machine_columns(self):
        sql = str(insert_doff_row_query())
        assert "eb_id" in sql
        assert "machine_id" not in sql
        assert "no_of_machines" not in sql

    def test_doff_create_unknown_eb_id_returns_400(self):
        """No active HRMS record for the eb_id -> 400 before anything is written."""
        self._mock_session.execute.side_effect = [_exec_result(fetchone=None)]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 999999,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "eb_id" in response.json().get("detail", "").lower()

    def test_doff_create_missing_eb_id_returns_422(self):
        """A winder is still mandatory: neither eb_id nor eb_ids -> 422."""
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 422
        # An empty selection is just as missing.
        assert (
            client.post(
                "/api/windingProd/doff_create", json={**payload, "eb_ids": []}
            ).status_code
            == 422
        )

    def test_doff_create_derives_branch_from_the_worker(self):
        """Body without branch_id -> branch comes from hrms_ed_official_details."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(29)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(lastrowid=101),
            _exec_result(),
        ]

        payload = {
            "co_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 200
        assert self._params_of(0) == {"eb_id": 2413}
        assert self._params_of(4)["branch_id"] == 29
        # The spell resolves against the derived branch, not None.
        assert self._params_of(1) == {"spell_code": "A1", "branch_id": 29}

    def test_doff_create_accepts_spell_id(self):
        """spell_id (preferred) is validated against its shift's branch and used."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(lastrowid=101),
            _exec_result(),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell_id": 7,
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 200
        assert self._params_of(4)["spell_id"] == 7

    def test_doff_create_wrong_branch_spell_id_returns_400(self):
        """A spell_id whose shift belongs to another branch is rejected."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_branch_row(97, branch_id=29)),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,  # caller branch 1 != spell branch 29
            "tran_date": "2026-06-01",
            "spell_id": 97,
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "does not belong" in response.json().get("detail", "").lower()

    def test_doff_create_requires_exactly_one_of_spell_or_spell_id(self):
        """Neither (or both) of spell / spell_id -> 400."""
        self._mock_session.execute.side_effect = [_exec_result(fetchone=_worker_row(1))]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 100.0,
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "exactly one" in response.json().get("detail", "").lower()

    def test_doff_create_net_not_positive_returns_400(self):
        """Tare (trolly + spool) exceeding gross -> net <= 0 -> 400."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(5.0)),  # trolly tare 5
            _exec_result(fetchone=_trolly_row(1.0)),  # spool tare 1
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 2.0,  # 2 - 5 - 1 = -4 net
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "greater than 0" in response.json().get("detail", "").lower()

    def test_doff_create_net_out_of_range_returns_400(self):
        """net above WINDING_NET_MAX (500 kg) -> 400."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "trolly_id": 3,
            "spool_id": 4,
            "quality_id": 5,
            "gross_weight": 900.0,  # net 897 > 500
        }

        response = client.post("/api/windingProd/doff_create", json=payload)

        assert response.status_code == 400
        assert "range" in response.json().get("detail", "").lower()

    def test_doff_by_date_returns_worker_columns_and_unresolved_worker_rows(self):
        """Rows carry eb_id/emp_code/worker_name; a doff whose worker does not
        resolve (eb_id points at a deleted/deactivated HRMS employee, so emp_code
        and worker_name come back NULL) is still returned, not dropped."""
        person_row = _mock_row(
            {
                "winding_doff_id": 101,
                "eb_id": 2413,
                "emp_code": "02413",
                "worker_name": "LAXMI DEBI",
                "trolly_wt": 2.0,
                "spool_wt": 1.0,
                "gross_input_wt": 100.0,
                "production_qty": 97.0,
                "row_gross_wt": 100.0,
                "tran_date": "2026-06-01",
            }
        )
        # eb_id IS set (it always is) but matches no ACTIVE hrms row -> blank worker.
        unresolved_worker_row = _mock_row(
            {
                "winding_doff_id": 7,
                "eb_id": 9999,
                "emp_code": None,
                "worker_name": None,
                "trolly_wt": 2.0,
                "spool_wt": 1.0,
                "gross_input_wt": 100.0,
                "production_qty": 97.0,
                "row_gross_wt": 100.0,
                "tran_date": "2026-06-01",
            }
        )
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[unresolved_worker_row, person_row]),
        ]

        response = client.get(
            "/api/windingProd/doff_by_date?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data) == 2
        assert data[1]["emp_code"] == "02413"
        assert data[1]["worker_name"] == "LAXMI DEBI"
        # The row whose worker did not resolve is returned, with a blank worker.
        assert data[0]["winding_doff_id"] == 7 and data[0]["eb_id"] == 9999
        assert data[0]["emp_code"] is None and data[0]["worker_name"] is None
        # no_of_machines is gone from the payload.
        assert "no_of_machines" not in data[1]

    def test_doff_by_date_keeps_unresolved_workers_via_left_join(self):
        """The worker join must be LEFT so a doff whose eb_id has no matching
        active HRMS row is still listed instead of being dropped by the join."""
        sql = str(get_doff_by_date_query())
        assert "LEFT JOIN hrms_ed_personal_details" in sql
        assert "INNER JOIN hrms_ed_personal_details" not in sql
        assert ":eb_id IS NULL OR wd.eb_id = :eb_id" in sql

    def test_doff_by_date_filters_by_eb_id(self):
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[]),
        ]

        response = client.get(
            "/api/windingProd/doff_by_date?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1&eb_id=2413"
        )

        assert response.status_code == 200
        assert self._params_of(1)["eb_id"] == 2413
        # Branch is the scope key; co_id is not a bind any more.
        assert self._params_of(1)["branch_id"] == 1
        assert "co_id" not in self._params_of(1)

    def test_doff_by_date_requires_branch_id(self):
        """branch_id is the scope key — omitting it is a 400, not an all-branch read."""
        response = client.get("/api/windingProd/doff_by_date?co_id=1&tran_date=2026-06-01")

        assert response.status_code == 400
        assert "branch_id" in response.json().get("detail", "").lower()

    def test_quality_by_date_requires_branch_id(self):
        response = client.get("/api/windingProd/quality_by_date?co_id=1&tran_date=2026-06-01")

        assert response.status_code == 400
        assert "branch_id" in response.json().get("detail", "").lower()

    def test_doff_edit_recomputes_the_single_row(self):
        """A solo weighing (its own group) edits exactly as it always did."""
        existing = MagicMock()
        existing.trolly_id = 3
        existing.spool_id = 4
        existing.item_id = 5
        existing.weighing_id = 101
        existing.gross_input_wt = 100.0
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            _exec_result(fetchall=[_doff_group_row(101, 2413, 100.0)]),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(),
        ]

        response = client.put(
            "/api/windingProd/doff_edit/101?co_id=1", json={"gross_weight": 60.0}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data == {
            "winding_doff_id": 101,
            "weighing_id": 101,
            "winding_doff_ids": [101],
            "net_total": 57.0,
            "net": 57.0,
            "row_gross_wt": 60.0,
        }

    def test_doff_edit_respreads_the_whole_weighing(self):
        """Editing one share re-splits the weighing across ALL its winders, so
        the shares keep summing to the weighing instead of drifting apart."""
        existing = MagicMock()
        existing.trolly_id = 3
        existing.spool_id = 4
        existing.item_id = 5
        existing.weighing_id = 101
        existing.gross_input_wt = 33.333
        group = [
            _doff_group_row(101, 2413, 33.333),
            _doff_group_row(102, 2414, 33.333),
            _doff_group_row(103, 2415, 33.334),
        ]
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            _exec_result(fetchall=group),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(),
            _exec_result(),
            _exec_result(),
        ]

        response = client.put(
            "/api/windingProd/doff_edit/102?co_id=1", json={"gross_weight": 61.0}
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # net_total = 61 - 2 - 1 = 58; 58/3 = 19.333 with 19.334 on the last row
        assert data["net_total"] == 58.0
        assert data["winding_doff_ids"] == [101, 102, 103]
        assert data["net"] == 19.333  # the edited row's own share

        updates = [self._params_of(i) for i in (4, 5, 6)]
        assert [u["id"] for u in updates] == [101, 102, 103]
        assert [u["production_qty"] for u in updates] == [19.333, 19.333, 19.334]
        # No kg lost or invented across the weighing.
        assert round(sum(u["production_qty"] for u in updates), 3) == 58.0
        assert round(sum(u["gross_input_wt"] for u in updates), 3) == 61.0

    def test_doff_edit_without_gross_keeps_the_weighings_total(self):
        """A quality-only edit must not shrink a shared weighing to one share:
        the gross defaults to the SUM of the shares, not this row's slice."""
        existing = MagicMock()
        existing.trolly_id = 3
        existing.spool_id = 4
        existing.item_id = 5
        existing.weighing_id = 101
        existing.gross_input_wt = 50.0  # this row's share of a 100 kg weighing
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            _exec_result(fetchall=[
                _doff_group_row(101, 2413, 50.0),
                _doff_group_row(102, 2414, 50.0),
            ]),
            _exec_result(fetchone=_trolly_row(2.0)),
            _exec_result(fetchone=_trolly_row(1.0)),
            _exec_result(),
            _exec_result(),
        ]

        response = client.put(
            "/api/windingProd/doff_edit/101?co_id=1", json={"quality_id": 9}
        )

        assert response.status_code == 200
        # gross stays 100 (50 + 50) -> net_total 97, not 47 off one share.
        assert response.json()["data"]["net_total"] == 97.0
        updates = [self._params_of(i) for i in (4, 5)]
        assert all(u["item_id"] == 9 for u in updates)
        assert round(sum(u["production_qty"] for u in updates), 3) == 97.0

    def test_doff_delete_removes_every_share_of_the_weighing(self):
        """Deleting one winder's share would leave the survivors summing to a
        weighing that never happened, and the spinning planning grid (which sums
        production_qty per item + shift) would lose the difference."""
        existing = MagicMock()
        existing.weighing_id = 101
        deleted = _exec_result()
        deleted.rowcount = 3
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            deleted,
        ]

        response = client.delete("/api/windingProd/doff_delete/102?co_id=1")

        assert response.status_code == 200
        assert response.json()["data"] == {
            "message": "Deleted",
            "weighing_id": 101,
            "rows_deleted": 3,
        }
        # Keyed off the group, never the row the user happened to click.
        assert self._params_of(1)["group_id"] == 101
        assert "id" not in self._params_of(1)

    def test_doff_delete_sql_keys_off_the_weighing_group(self):
        sql = str(soft_delete_doff_group_query())
        assert "COALESCE(weighing_id, winding_doff_id) = :group_id" in sql
        assert "winding_doff_id = :id" not in sql

    # ----------------------------------------------------------------- Jugar
    def test_jugar_setup_success(self):
        """jugar_setup returns workers + spells (was machines + spells)."""
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [_WORKER_PICKER_ROW],
            [_SPELL_PICKER_ROW],
        ]

        response = client.get("/api/windingProd/jugar_setup?co_id=1")

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" not in data
        assert data["workers"][0]["eb_id"] == 2413
        assert data["spells"][0]["spell_code"] == "A1"

    def test_jugar_setup_missing_co_id(self):
        response = client.get("/api/windingProd/jugar_setup")
        assert response.status_code == 400
        assert "co_id" in response.json().get("detail", "").lower()

    def test_jugar_save_inserts_both_sides(self):
        """One payload carries opening + closing — two person-keyed rows, no O/C flag."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),   # _worker_branch
            _exec_result(fetchone=_spell_row(7)),    # _resolve_spell
            _exec_result(fetchall=[]),               # nothing stored yet
            _exec_result(lastrowid=202),             # insert opening
            _exec_result(lastrowid=203),             # insert closing
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "opening": 12.5,
            "closing": 9.0,
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["opening"] == {"winding_jugar_id": 202, "weight": 12.5}
        assert data["closing"] == {"winding_jugar_id": 203, "weight": 9.0}
        assert self._params_of(3)["open_close"] == "O"
        assert self._params_of(4)["open_close"] == "C"
        assert self._params_of(3)["eb_id"] == 2413
        assert "machine_id" not in self._params_of(3)

    def test_jugar_save_upserts_an_existing_side(self):
        """A stored side is UPDATED (no duplicate 400) — the carried opening can be re-saved."""
        stored = MagicMock(open_close="O", winding_jugar_id=202, weight=8.0)
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[stored]),         # opening already stored
            _exec_result(lastrowid=None),            # update opening
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "opening": 12.5,
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["opening"]["winding_jugar_id"] == 202
        assert self._params_of(3) == {"id": 202, "weight": 12.5, "updated_by": 1}

    def test_jugar_save_accepts_a_zero_opening(self):
        """Opening 0 is legal — a spell can start with an empty spindle."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[]),
            _exec_result(lastrowid=202),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "opening": 0,
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["opening"] == {"winding_jugar_id": 202, "weight": 0.0}
        assert self._params_of(3)["weight"] == 0.0

    def test_jugar_save_rejects_a_zero_closing(self):
        """Closing 0 stays a 400 — "nothing left" is expressed by omitting it."""
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "closing": 0,
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 400
        assert "greater than" in response.json().get("detail", "").lower()

    def test_jugar_save_weight_out_of_range_returns_400(self):
        """weight > JUGAR_MAX (100) fails the router gate -> 400."""
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "opening": 150.0,  # > 100
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 400
        assert "weight" in response.json().get("detail", "").lower()

    def test_jugar_save_requires_a_side(self):
        """Neither opening nor closing -> 422 from the pydantic validator."""
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
        }

        response = client.post("/api/windingProd/jugar_save", json=payload)

        assert response.status_code == 422

    def test_jugar_by_date_success(self):
        """jugar_by_date returns a list under data with worker columns."""
        jugar_row = _mock_row(
            {
                "winding_jugar_id": 202,
                "eb_id": 2413,
                "emp_code": "02413",
                "worker_name": "LAXMI DEBI",
                "weight": 12.5,
                "open_close": "O",
                "tran_date": "2026-06-01",
            }
        )
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[jugar_row]),
        ]

        response = client.get(
            "/api/windingProd/jugar_by_date"
            "?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1&open_close=O"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[0]["winding_jugar_id"] == 202
        assert data[0]["worker_name"] == "LAXMI DEBI"
        assert data[0]["weight"] == 12.5
        # Branch is the scope key; co_id is not a bind any more.
        grid_params = self._params_of(1)
        assert grid_params["branch_id"] == 1
        assert "co_id" not in grid_params

    def test_jugar_by_date_requires_branch_id(self):
        """branch_id is the scope key — omitting it is a 400, not an all-branch read."""
        response = client.get("/api/windingProd/jugar_by_date?co_id=1&tran_date=2026-06-01")

        assert response.status_code == 400
        assert "branch_id" in response.json().get("detail", "").lower()

    def test_jugar_by_date_accepts_spell_id_param(self):
        """GET endpoints take spell_id (validated against branch_id param)."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),
            _exec_result(fetchall=[]),
        ]

        response = client.get(
            "/api/windingProd/jugar_by_date"
            "?co_id=1&branch_id=1&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 200
        assert self._params_of(1)["spell_id"] == 7

    def test_jugar_state_carries_the_previous_spell_closing(self):
        """Nothing saved yet -> both sides carry the previous spell's closing,
        looked up per winder + BRANCH."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),  # _resolve_spell
            _exec_result(fetchall=[]),                                 # nothing saved
            _exec_result(fetchone=MagicMock(weight=9.0)),              # prev closing
        ]

        response = client.get(
            "/api/windingProd/jugar_state"
            "?co_id=1&branch_id=1&eb_id=2413&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["opening"] == {"weight": 9.0, "winding_jugar_id": None, "source": "carry"}
        assert data["closing"]["source"] == "carry"
        carry_params = self._params_of(2)
        assert carry_params["eb_id"] == 2413
        assert carry_params["branch_id"] == 1
        assert carry_params["spell_id"] == 7
        assert carry_params["open_close"] == "C"
        # branch_id is the scope key — co_id is not a bind on winding lookups.
        assert "co_id" not in carry_params
        assert "co_id" not in self._params_of(1)

    def test_jugar_state_rejects_a_worker_with_no_branch(self):
        """branch_id omitted + HRMS record without a branch -> 400, never an
        unscoped read (a branchless row would be invisible to every winding query)."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(None)),  # HRMS row, branch_id NULL
        ]

        response = client.get(
            "/api/windingProd/jugar_state?co_id=1&eb_id=2413&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 400
        assert "branch" in response.json().get("detail", "").lower()

    def test_jugar_state_saved_row_beats_the_carry(self):
        """A stored opening wins over the carry-forward and carries its row id."""
        saved = MagicMock(open_close="O", winding_jugar_id=202, weight=12.5)
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),
            _exec_result(fetchall=[saved]),
            _exec_result(fetchone=MagicMock(weight=9.0)),  # prev closing (carry)
        ]

        response = client.get(
            "/api/windingProd/jugar_state"
            "?co_id=1&branch_id=1&eb_id=2413&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["opening"] == {"weight": 12.5, "winding_jugar_id": 202, "source": "saved"}
        # Closing has no stored row, so it still shows the carry.
        assert data["closing"] == {"weight": 9.0, "winding_jugar_id": None, "source": "carry"}

    def test_jugar_state_falls_back_to_a_previous_opening(self):
        """No closing ever recorded -> opening falls back to the prior OPENING (legacy 'OE')."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),
            _exec_result(fetchall=[]),
            _exec_result(fetchone=None),                   # no prior closing
            _exec_result(fetchone=MagicMock(weight=7.5)),  # prior opening
        ]

        response = client.get(
            "/api/windingProd/jugar_state"
            "?co_id=1&branch_id=1&eb_id=2413&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["opening"] == {"weight": 7.5, "winding_jugar_id": None, "source": "carry_open"}
        assert data["closing"]["source"] == "none"
        assert self._params_of(3)["open_close"] == "O"

    # --------------------------------------------------------------- Quality
    def test_quality_setup_success_no_seed(self):
        """quality_setup returns rows + yarn_items + workers + machines when rows exist."""
        map_row = _mock_row(
            {
                "winding_daily_qlty_id": 301,
                "eb_id": 2413,
                "emp_code": "02413",
                "worker_name": "LAXMI DEBI",
                "item_id": 5,
                "machine_id": 61,
                "machine_name": "WINDING 1",
                "mech_code": "W-01",
                "no_of_spindle": 12,
                "tran_date": "2026-06-01",
            }
        )
        # execute() order: resolve spell, exists-count (>0 so no seed),
        # quality_by_date rows, yarn_items picker, workers picker, machines picker.
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(scalar=2),
            _exec_result(fetchall=[map_row]),
            _exec_result(fetchall=[_YARN_ROW]),
            _exec_result(fetchall=[_WORKER_PICKER_ROW]),
            _exec_result(fetchall=[_MACHINE_PICKER_ROW]),
        ]

        response = client.get(
            "/api/windingProd/quality_setup?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["rows"][0]["winding_daily_qlty_id"] == 301
        assert data["rows"][0]["worker_name"] == "LAXMI DEBI"
        # The map row carries its machine (the ONLY winding table that does).
        assert data["rows"][0]["machine_id"] == 61
        assert data["rows"][0]["machine_name"] == "WINDING 1"
        assert data["yarn_items"][0]["item_id"] == 5
        assert data["workers"][0]["eb_id"] == 2413

    def test_quality_setup_returns_winding_machines(self):
        """The map's machine picker: Winding-type machines, branch-scoped."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_branch_row(7, branch_id=1)),
            _exec_result(scalar=1),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[_MACHINE_PICKER_ROW]),
        ]

        response = client.get(
            "/api/windingProd/quality_setup"
            "?co_id=1&branch_id=1&tran_date=2026-06-01&spell_id=7"
        )

        assert response.status_code == 200
        machines = response.json()["data"]["machines"]
        assert machines == [
            {
                "machine_id": 61,
                "machine_name": "WINDING 1",
                "mech_code": "W-01",
                "dept_id": 53,
                "dept_name": "WINDING",
                "branch_id": 1,
            }
        ]
        # Resolved by type NAME (the constant), not a hardcoded id, and branch-scoped.
        assert self._params_of(5) == {"machine_type_name": "Winding", "branch_id": 1}

    def test_quality_setup_seeds_persons_from_the_previous_spell(self):
        """Empty date/spell -> carry the previous spell's WINDERS forward."""
        prev = MagicMock()
        prev.prev_date = "2026-05-31"
        prev.prev_spell_id = 9
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),   # resolve spell
            _exec_result(scalar=0),                 # no rows yet
            _exec_result(fetchone=prev),            # previous date/spell
            _exec_result(),                         # auto-seed INSERT..SELECT
            _exec_result(fetchall=[]),              # rows
            _exec_result(fetchall=[]),              # yarn_items
            _exec_result(fetchall=[]),              # workers
            _exec_result(fetchall=[]),              # machines
        ]

        response = client.get(
            "/api/windingProd/quality_setup?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1"
        )

        assert response.status_code == 200
        seed_params = self._params_of(3)
        assert seed_params["prev_date"] == "2026-05-31"
        assert seed_params["prev_spell_id"] == 9
        assert seed_params["spell_id"] == 7

    def test_quality_setup_seeds_nothing_without_a_previous_spell(self):
        """No prior rows -> prev_date / prev_spell_id are SQL NULL (Python None),
        which selects zero source rows: an empty map, not a machine list."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(scalar=0),
            _exec_result(fetchone=None),  # no previous date/spell at all
            _exec_result(),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[]),
            _exec_result(fetchall=[]),
        ]

        response = client.get(
            "/api/windingProd/quality_setup?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1"
        )

        assert response.status_code == 200
        assert response.json()["data"]["rows"] == []
        seed_params = self._params_of(3)
        assert seed_params["prev_date"] is None
        assert seed_params["prev_spell_id"] is None

    def test_auto_seed_is_person_keyed_and_idempotent(self):
        """The seed is keyed on the PERSON and keeps the NOT EXISTS guard re-keyed
        on eb_id, so a re-run never duplicates a winder. It carries each person's
        machine forward as a plain column — the seed source is still the previous
        map, never a machine list."""
        sql = str(auto_seed_quality_query())
        assert "FROM jute_prod_winding_daily_qlty pq" in sql
        assert "pq.eb_id" in sql
        assert "NOT EXISTS" in sql
        assert "x.eb_id = pq.eb_id" in sql
        assert "machine_mst" not in sql
        # The machine rides along with the person, it does not drive the seed.
        assert "pq.machine_id" in sql
        assert "x.machine_id" not in sql

    def test_quality_setup_missing_params(self):
        """Missing tran_date/spell -> 400 (both required together)."""
        response = client.get("/api/windingProd/quality_setup?co_id=1&branch_id=1")
        assert response.status_code == 400
        detail = response.json().get("detail", "").lower()
        assert "tran_date" in detail and "spell" in detail

    def test_quality_add_success(self):
        """POST /quality_add inserts one winder into the day's map."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),  # _worker_branch
            _exec_result(fetchone=_spell_row(7)),   # _resolve_spell
            _exec_result(fetchone=None),            # duplicate guard -> none
            _exec_result(lastrowid=302),            # insert
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "item_id": 5,
            "machine_id": 61,
            "no_of_spindle": 12,
        }

        response = client.post("/api/windingProd/quality_add", json=payload)

        assert response.status_code == 200
        assert response.json()["data"]["winding_daily_qlty_id"] == 302
        insert_params = self._params_of(3)
        assert insert_params["eb_id"] == 2413
        # The map is the one winding table that records a machine.
        assert insert_params["machine_id"] == 61

    def test_quality_add_without_machine_binds_sql_null(self):
        """machine_id is optional — omitting it binds None (SQL NULL), not 'null'."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=None),
            _exec_result(lastrowid=302),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
            "item_id": 5,
        }

        response = client.post("/api/windingProd/quality_add", json=payload)

        assert response.status_code == 200
        assert self._params_of(3)["machine_id"] is None

    def test_quality_add_duplicate_person_returns_400(self):
        """Duplicate (co, date, spell, eb) -> 400."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_worker_row(1)),
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchone=MagicMock(winding_daily_qlty_id=301)),
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 2413,
        }

        response = client.post("/api/windingProd/quality_add", json=payload)

        assert response.status_code == 400
        assert "already exists" in response.json().get("detail", "").lower()
        assert self._params_of(2)["eb_id"] == 2413

    def test_quality_add_unknown_eb_id_returns_400(self):
        self._mock_session.execute.side_effect = [_exec_result(fetchone=None)]

        payload = {
            "co_id": 1,
            "tran_date": "2026-06-01",
            "spell": "A1",
            "eb_id": 999999,
        }

        response = client.post("/api/windingProd/quality_add", json=payload)

        assert response.status_code == 400
        assert "eb_id" in response.json().get("detail", "").lower()

    def test_quality_delete_soft_deletes(self):
        """DELETE /quality_delete/{id} sets active = 0 and echoes the id."""
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=MagicMock(winding_daily_qlty_id=301)),
            _exec_result(),
        ]

        response = client.delete("/api/windingProd/quality_delete/301")

        assert response.status_code == 200
        assert response.json()["data"] == {"deleted": 301}
        assert "active = 0" in str(self._mock_session.execute.call_args_list[1].args[0])

    def test_quality_delete_missing_row_returns_404(self):
        self._mock_session.execute.side_effect = [_exec_result(fetchone=None)]

        response = client.delete("/api/windingProd/quality_delete/999")

        assert response.status_code == 404

    def test_quality_save_success(self):
        """Valid spindle in [1,30] updates the row; dup guard re-keyed on eb_id."""
        existing = MagicMock()
        existing.co_id = 1
        existing.tran_date = "2026-06-01"
        existing.spell_id = 7
        existing.eb_id = 2413
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            _exec_result(fetchone=None),  # no duplicate
            _exec_result(),               # update
        ]

        payload = {
            "co_id": 1,
            "branch_id": 1,
            "item_id": 5,
            "machine_id": 61,
            "no_of_spindle": 12,
        }

        response = client.put("/api/windingProd/quality_save/301", json=payload)

        assert response.status_code == 200
        data = response.json()["data"]
        assert data == {"winding_daily_qlty_id": 301, "no_of_spindle": 12}
        dup_params = self._params_of(1)
        assert dup_params["eb_id"] == 2413
        # The duplicate guard stays person-keyed — the machine plays no part in it.
        assert "machine_id" not in dup_params
        # ...but the update itself writes the machine.
        assert self._params_of(2)["machine_id"] == 61

    def test_quality_save_without_machine_binds_sql_null(self):
        """Omitting machine_id on edit clears it to SQL NULL (None), not 'null'."""
        existing = MagicMock()
        existing.co_id = 1
        existing.tran_date = "2026-06-01"
        existing.spell_id = 7
        existing.eb_id = 2413
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=existing),
            _exec_result(fetchone=None),
            _exec_result(),
        ]

        response = client.put(
            "/api/windingProd/quality_save/301",
            json={"co_id": 1, "branch_id": 1, "item_id": 5, "no_of_spindle": 12},
        )

        assert response.status_code == 200
        assert self._params_of(2)["machine_id"] is None

    def test_quality_by_date_success(self):
        """quality_by_date returns a list under data with worker columns."""
        quality_row = _mock_row(
            {
                "winding_daily_qlty_id": 301,
                "eb_id": 2413,
                "emp_code": "02413",
                "worker_name": "LAXMI DEBI",
                "item_id": 5,
                "no_of_spindle": 12,
                "tran_date": "2026-06-01",
            }
        )
        self._mock_session.execute.side_effect = [
            _exec_result(fetchone=_spell_row(7)),
            _exec_result(fetchall=[quality_row]),
        ]

        response = client.get(
            "/api/windingProd/quality_by_date?co_id=1&branch_id=1&tran_date=2026-06-01&spell=A1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data[0]["winding_daily_qlty_id"] == 301
        assert data[0]["emp_code"] == "02413"
