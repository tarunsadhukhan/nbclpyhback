"""Tests for the spinning standards/targets master CRUD endpoints.

Tests for src/juteProduction/spng_target_map.py. The router IS registered in
src/main.py at prefix /api/spngTargetMap (tags=["spng-target-map"]), so we drive it
through the real application via TestClient(app).

Mocking pattern (mirrors src/test/test_yarn_quality.py + the project test-writer guide):
each test @patch-es get_tenant_db / get_current_user_with_refresh where they are looked
up in the module under test, sets mock_db.return_value.__enter__.return_value =
mock_session and mock_auth.return_value = {"user_id": 1}. Because FastAPI binds the
Depends(...) callables at route-definition time, the patches are paired with
app.dependency_overrides on the real dependency objects so the request actually resolves
to the mock session/user. db.execute(...).fetchall()/.fetchone() return rows whose
._mapping is a dict.

NOTE on the "planning grid": spng_target_map.py exposes only setup / list / create /
edit / delete. There is no planning-grid endpoint here (rows / shift_rollup live in
spinning_entry.py), so this file has no planning-grid test.
"""

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.main import app

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _exec_params(mock_session, call_index: int) -> dict:
    """Bound params of the Nth db.execute call."""
    return mock_session.execute.call_args_list[call_index][0][1]


@contextmanager
def _mocked(mock_session):
    """Patch the module's get_tenant_db / get_current_user_with_refresh AND override the
    FastAPI dependencies so the request resolves to mock_session / {"user_id": 1}."""
    with patch("src.juteProduction.spng_target_map.get_tenant_db") as mock_db, patch(
        "src.juteProduction.spng_target_map.get_current_user_with_refresh"
    ) as mock_auth:
        mock_auth.return_value = {"user_id": 1}
        mock_db.return_value.__enter__.return_value = mock_session
        app.dependency_overrides[get_tenant_db] = lambda: mock_session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            yield
        finally:
            app.dependency_overrides.clear()


# =============================================================================
# GET /target_map_setup
# =============================================================================


class TestTargetMapSetup:
    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_setup_success_returns_data_and_enums(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        machine_row = _mock_row(
            {
                "machine_id": 10,
                "machine_name": "Frame-1",
                "mech_code": "M1",
                "branch_id": 1,
            }
        )
        quality_row = _mock_row(
            {
                "item_id": 5,
                "item_code": "Q5",
                "item_name": "Hessian",
                "std_count": 12.0,
                "std_mr_pct": 13.75,
            }
        )
        # setup executes twice: machines then yarn_items
        mock_session.execute.return_value.fetchall.side_effect = [
            [machine_row],
            [quality_row],
        ]

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_setup?co_id=1")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["machines"][0]["machine_id"] == 10
        assert data["yarn_items"][0]["item_id"] == 5
        assert data["id_types"] == ["mcid", "qid"]
        assert data["value_roles"] == ["standard", "target", "actual"]
        assert data["params"] == ["speed", "tpi", "eff", "spindles", "dc", "tc", "bobbin_wt"]

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_setup_passes_branch_id_bind(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchall.side_effect = [[], []]

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_setup?co_id=1&branch_id=2")

        assert resp.status_code == 200
        assert _exec_params(mock_session, 0)["branch_id"] == 2  # machines query

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_setup_missing_co_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_setup")

        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_setup_invalid_branch_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_setup?co_id=1&branch_id=abc")

        assert resp.status_code == 400
        assert "branch_id" in resp.json()["detail"].lower()


# =============================================================================
# GET /target_map_list
# =============================================================================


class TestTargetMapList:
    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_success_casts_value_and_date(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchall.return_value = [
            _mock_row(
                {
                    "spng_target_map_id": 5,
                    "co_id": 1,
                    "branch_id": None,
                    "effective_date": date(2026, 6, 13),
                    "ref_id": 42,
                    "id_type": "mcid",
                    "value_role": "standard",
                    "param": "speed",
                    "value": 1450,
                    "active": 1,
                    "ref_code": "SPG-01",
                    "ref_name": "Spinning Frame 1",
                }
            )
        ]

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_list?co_id=1")

        assert resp.status_code == 200
        rows = resp.json()["data"]
        assert len(rows) == 1
        row = rows[0]
        assert row["spng_target_map_id"] == 5
        assert row["value"] == 1450.0
        assert isinstance(row["value"], float)
        assert row["effective_date"] == "2026-06-13"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_empty(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchall.return_value = []

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_list?co_id=1")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_passes_optional_filter_binds(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchall.return_value = []

        with _mocked(mock_session):
            resp = client.get(
                "/api/spngTargetMap/target_map_list"
                "?co_id=1&id_type=qid&ref_id=9&value_role=target&param=tpi"
            )

        assert resp.status_code == 200
        params = _exec_params(mock_session, 0)
        assert params["id_type"] == "qid"
        assert params["ref_id"] == 9
        assert params["value_role"] == "target"
        assert params["param"] == "tpi"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_binds_none_when_no_filters(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchall.return_value = []

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_list?co_id=1")

        assert resp.status_code == 200
        params = _exec_params(mock_session, 0)
        # None for SQL NULL, never the string "null"
        assert params["id_type"] is None
        assert params["ref_id"] is None
        assert params["value_role"] is None
        assert params["param"] is None

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_missing_co_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_list")

        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_list_invalid_enum_rejected(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get("/api/spngTargetMap/target_map_list?co_id=1&param=bogus")

        assert resp.status_code == 400
        assert "param" in resp.json()["detail"].lower()


# =============================================================================
# POST /target_map_create
# =============================================================================


class TestTargetMapCreate:
    def _ok_body(self, **overrides):
        body = {
            "co_id": 1,
            "branch_id": 2,
            "effective_date": "2026-06-13",
            "ref_id": 42,
            "id_type": "mcid",
            "value_role": "standard",
            "param": "speed",
            "value": 1450.0,
        }
        body.update(overrides)
        return body

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_success(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.lastrowid = 11

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create", json=self._ok_body()
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["spng_target_map_id"] == 11
        mock_session.commit.assert_called_once()
        params = _exec_params(mock_session, 0)
        assert params["updated_by"] == 1
        assert params["value"] == 1450.0

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_accepts_bobbin_wt_param(self, mock_auth, mock_db):
        # bobbin_wt is a valid machine (mcid) param after the spinningMachineAttr migration.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.lastrowid = 12

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create",
                json=self._ok_body(param="bobbin_wt", value=0.5),
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["spng_target_map_id"] == 12
        params = _exec_params(mock_session, 0)
        assert params["param"] == "bobbin_wt"
        assert params["value"] == 0.5

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_invalid_id_type_rolls_back(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create",
                json=self._ok_body(id_type="xxx"),
            )

        assert resp.status_code == 400
        assert "id_type" in resp.json()["detail"].lower()
        mock_session.rollback.assert_called_once()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_invalid_value_role(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create",
                json=self._ok_body(value_role="bad"),
            )

        assert resp.status_code == 400
        assert "value_role" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_invalid_param(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create",
                json=self._ok_body(param="bad"),
            )

        assert resp.status_code == 400
        assert "param" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_missing_required_field(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        body = self._ok_body()
        del body["effective_date"]  # required field

        with _mocked(mock_session):
            resp = client.post("/api/spngTargetMap/target_map_create", json=body)

        # Pydantic rejects a missing required field with 422
        assert resp.status_code == 422

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_create_negative_value_rejected(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_create",
                json=self._ok_body(value=-5),
            )

        # value has Field(ge=0) -> 422
        assert resp.status_code == 422


# =============================================================================
# PUT /target_map_edit/{target_map_id}
# =============================================================================


class TestTargetMapEdit:
    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_edit_updates_provided_fields(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        existing = MagicMock()
        existing.fetchone.return_value = _mock_row({"spng_target_map_id": 5})
        update_result = MagicMock()
        # first execute = existence check, second = UPDATE
        mock_session.execute.side_effect = [existing, update_result]

        with _mocked(mock_session):
            resp = client.put(
                "/api/spngTargetMap/target_map_edit/5",
                json={"value": 99.5, "active": 1},
            )

        assert resp.status_code == 200
        assert resp.json()["data"]["spng_target_map_id"] == 5
        mock_session.commit.assert_called_once()
        params = _exec_params(mock_session, 1)
        assert params["value"] == 99.5
        assert params["active"] == 1
        assert params["updated_by"] == 1

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_edit_not_found(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = None

        with _mocked(mock_session):
            resp = client.put(
                "/api/spngTargetMap/target_map_edit/999", json={"value": 1.0}
            )

        assert resp.status_code == 404
        mock_session.rollback.assert_called_once()


# =============================================================================
# DELETE /target_map_delete/{target_map_id}
# =============================================================================


class TestTargetMapDelete:
    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_delete_soft_sets_active_zero(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        existing = MagicMock()
        existing.fetchone.return_value = _mock_row({"spng_target_map_id": 5})
        delete_result = MagicMock()
        mock_session.execute.side_effect = [existing, delete_result]

        with _mocked(mock_session):
            resp = client.delete("/api/spngTargetMap/target_map_delete/5")

        assert resp.status_code == 200
        assert resp.json()["data"]["message"] == "Deleted"
        mock_session.commit.assert_called_once()
        # second execute is the soft-delete UPDATE
        assert _exec_params(mock_session, 1)["id"] == 5

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_delete_not_found(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = None

        with _mocked(mock_session):
            resp = client.delete("/api/spngTargetMap/target_map_delete/999")

        assert resp.status_code == 404
        mock_session.rollback.assert_called_once()


# =============================================================================
# Helpers for the inline-grid endpoints
# =============================================================================
#
# target_map_grid reads the resolve query via ATTRIBUTE access (resolved.value /
# resolved.effective_date), and target_map_bulk_save reads find_exact_grid_row via
# existing.spng_target_map_id -- NOT via ._mapping. So the inline-grid tests use
# plain objects (or MagicMocks with explicit attributes) for those rows.


class _Attr:
    """A tiny attribute bag for rows accessed by attribute (not ._mapping)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _machine_row(machine_id, mech_code, machine_name, branch_id=1):
    return _mock_row(
        {
            "machine_id": machine_id,
            "mech_code": mech_code,
            "machine_name": machine_name,
            "branch_id": branch_id,
        }
    )


def _yarn_row(item_id, item_code, item_name):
    return _mock_row(
        {"item_id": item_id, "item_code": item_code, "item_name": item_name}
    )


def _resolve_call_params(mock_session, call_index: int) -> dict:
    """Bound params of the Nth db.execute call (resolve cell queries)."""
    return mock_session.execute.call_args_list[call_index][0][1]


# =============================================================================
# GET /target_map_grid
# =============================================================================


class TestTargetMapGrid:
    def _grid_url(self, **kw):
        base = (
            "/api/spngTargetMap/target_map_grid"
            "?co_id=1&id_type={id_type}&value_role={value_role}"
            "&effective_date={effective_date}"
        )
        params = {
            "id_type": "mcid",
            "value_role": "target",
            "effective_date": "2026-06-13",
        }
        params.update(kw)
        url = base.format(**params)
        if kw.get("branch_id") is not None:
            url += f"&branch_id={kw['branch_id']}"
        return url

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_mcid_target_param_set_excludes_spindles_and_bobbin(
        self, mock_auth, mock_db
    ):
        # mcid + target -> params are exactly ["speed", "dc", "tc"]: spindles and
        # bobbin_wt (standard-only physical config) must NOT appear.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        # execute call 0 = list machines; calls 1..3 = resolve speed/dc/tc for that ref.
        machines = MagicMock()
        machines.fetchall.return_value = [_machine_row(10, "M1", "Frame-1")]
        resolved = MagicMock()
        resolved.fetchone.return_value = _Attr(value=1450, effective_date=date(2026, 6, 13))
        mock_session.execute.side_effect = [machines, resolved, resolved, resolved]

        with _mocked(mock_session):
            resp = client.get(self._grid_url(id_type="mcid", value_role="target"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["params"] == ["speed", "dc", "tc"]
        assert "spindles" not in data["params"]
        assert "bobbin_wt" not in data["params"]
        # one resolve per param: 1 list + 3 resolves = 4 executes
        assert mock_session.execute.call_count == 4
        resolved_params = {
            _resolve_call_params(mock_session, i)["param"] for i in (1, 2, 3)
        }
        assert resolved_params == {"speed", "dc", "tc"}

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_mcid_standard_includes_spindles_and_bobbin(self, mock_auth, mock_db):
        # mcid + standard -> full physical set: speed, spindles, dc, tc, bobbin_wt.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        machines = MagicMock()
        machines.fetchall.return_value = [_machine_row(10, "M1", "Frame-1")]
        resolved = MagicMock()
        resolved.fetchone.return_value = _Attr(value=5, effective_date=date(2026, 6, 13))
        # 1 list + 5 resolves
        mock_session.execute.side_effect = [machines] + [resolved] * 5

        with _mocked(mock_session):
            resp = client.get(self._grid_url(id_type="mcid", value_role="standard"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["params"] == ["speed", "spindles", "dc", "tc", "bobbin_wt"]
        assert mock_session.execute.call_count == 6

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_qid_param_set(self, mock_auth, mock_db):
        # qid + standard/target -> exactly ["tpi", "eff"]. Refs come from yarn items.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        resolved = MagicMock()
        resolved.fetchone.return_value = _Attr(value=4.2, effective_date=date(2026, 6, 13))
        mock_session.execute.side_effect = [yarns, resolved, resolved]

        with _mocked(mock_session):
            resp = client.get(self._grid_url(id_type="qid", value_role="target"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["params"] == ["tpi", "eff"]
        assert data["rows"][0]["ref_id"] == 7
        assert data["rows"][0]["ref_code"] == "Q7"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_qid_actual_drops_eff(self, mock_auth, mock_db):
        # qid + actual -> only ["tpi"]; eff is a standard/target, not an actual.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        resolved = MagicMock()
        resolved.fetchone.return_value = _Attr(value=4.2, effective_date=date(2026, 6, 13))
        # 1 list + 1 resolve (tpi only)
        mock_session.execute.side_effect = [yarns, resolved]

        with _mocked(mock_session):
            resp = client.get(self._grid_url(id_type="qid", value_role="actual"))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["params"] == ["tpi"]
        assert mock_session.execute.call_count == 2

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_is_exact_true_when_source_date_equals_effective_date(
        self, mock_auth, mock_db
    ):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        # source_date == effective_date (2026-06-13) -> is_exact True
        exact = MagicMock()
        exact.fetchone.return_value = _Attr(value=4.2, effective_date=date(2026, 6, 13))
        mock_session.execute.side_effect = [yarns, exact, exact]

        with _mocked(mock_session):
            resp = client.get(
                self._grid_url(
                    id_type="qid", value_role="target", effective_date="2026-06-13"
                )
            )

        assert resp.status_code == 200
        cells = resp.json()["data"]["rows"][0]["cells"]
        assert cells["tpi"]["is_exact"] is True
        assert cells["tpi"]["source_date"] == "2026-06-13"
        assert cells["tpi"]["value"] == 4.2

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_is_exact_false_when_inherited_from_earlier_date(
        self, mock_auth, mock_db
    ):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        # source_date (2026-06-01) < effective_date (2026-06-13) -> inherited, is_exact False
        inherited = MagicMock()
        inherited.fetchone.return_value = _Attr(value=4.2, effective_date=date(2026, 6, 1))
        mock_session.execute.side_effect = [yarns, inherited, inherited]

        with _mocked(mock_session):
            resp = client.get(
                self._grid_url(
                    id_type="qid", value_role="target", effective_date="2026-06-13"
                )
            )

        assert resp.status_code == 200
        cells = resp.json()["data"]["rows"][0]["cells"]
        assert cells["tpi"]["is_exact"] is False
        assert cells["tpi"]["source_date"] == "2026-06-01"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_omits_param_when_no_active_row_resolves(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        none_result = MagicMock()
        none_result.fetchone.return_value = None  # nothing resolves
        mock_session.execute.side_effect = [yarns, none_result, none_result]

        with _mocked(mock_session):
            resp = client.get(self._grid_url(id_type="qid", value_role="target"))

        assert resp.status_code == 200
        cells = resp.json()["data"]["rows"][0]["cells"]
        assert cells == {}

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_resolve_omits_branch_filter_passes_on_date(self, mock_auth, mock_db):
        # resolve_grid_cell binds only co_id/ref_id/id_type/value_role/param/on_date --
        # NO branch_id (mirrors resolve_param). branch_id scopes only ref listing.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        yarns = MagicMock()
        yarns.fetchall.return_value = [_yarn_row(7, "Q7", "Hessian")]
        resolved = MagicMock()
        resolved.fetchone.return_value = _Attr(value=4.2, effective_date=date(2026, 6, 13))
        mock_session.execute.side_effect = [yarns, resolved, resolved]

        with _mocked(mock_session):
            resp = client.get(
                self._grid_url(id_type="qid", value_role="target", branch_id=3)
            )

        assert resp.status_code == 200
        # ref listing (call 0) gets branch_id; resolve calls (1,2) do not bind branch_id
        assert _resolve_call_params(mock_session, 0)["branch_id"] == 3
        resolve_params = _resolve_call_params(mock_session, 1)
        assert "branch_id" not in resolve_params
        assert resolve_params["on_date"] == date(2026, 6, 13)
        assert resolve_params["value_role"] == "target"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_missing_co_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get(
                "/api/spngTargetMap/target_map_grid"
                "?id_type=mcid&value_role=target&effective_date=2026-06-13"
            )

        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_missing_id_type(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get(
                "/api/spngTargetMap/target_map_grid"
                "?co_id=1&value_role=target&effective_date=2026-06-13"
            )

        assert resp.status_code == 400
        assert "id_type" in resp.json()["detail"].lower()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_grid_invalid_effective_date(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.get(self._grid_url(effective_date="13-06-2026"))

        assert resp.status_code == 400
        assert "effective_date" in resp.json()["detail"].lower()


# =============================================================================
# POST /target_map_bulk_save
# =============================================================================


class TestTargetMapBulkSave:
    def _body(self, cells, **overrides):
        body = {
            "co_id": 1,
            "branch_id": None,
            "effective_date": "2026-06-13",
            "id_type": "mcid",
            "value_role": "target",
            "cells": cells,
        }
        body.update(overrides)
        return body

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_updates_when_exact_row_exists(self, mock_auth, mock_db):
        # find returns an existing exact-date row -> UPDATE branch, updated count.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find = MagicMock()
        find.fetchone.return_value = _Attr(spng_target_map_id=55, value=1400)
        update_result = MagicMock()
        # call 0 = find, call 1 = update
        mock_session.execute.side_effect = [find, update_result]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body([{"ref_id": 10, "param": "speed", "value": 1450}]),
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"inserted": 0, "updated": 1, "cleared": 0}
        mock_session.commit.assert_called_once()
        # second execute is the UPDATE, targeting existing row 55 with new value
        update_params = _exec_params(mock_session, 1)
        assert update_params["id"] == 55
        assert update_params["value"] == 1450.0
        assert update_params["updated_by"] == 1

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_inserts_when_no_exact_row(self, mock_auth, mock_db):
        # find returns None -> INSERT branch, inserted count.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find = MagicMock()
        find.fetchone.return_value = None
        insert_result = MagicMock()
        mock_session.execute.side_effect = [find, insert_result]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body([{"ref_id": 10, "param": "speed", "value": 1450}]),
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"inserted": 1, "updated": 0, "cleared": 0}
        mock_session.commit.assert_called_once()
        # second execute is the INSERT carrying full key + value
        insert_params = _exec_params(mock_session, 1)
        assert insert_params["ref_id"] == 10
        assert insert_params["param"] == "speed"
        assert insert_params["value"] == 1450.0
        assert insert_params["id_type"] == "mcid"
        assert insert_params["value_role"] == "target"

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_null_value_clears_existing_exact_row(self, mock_auth, mock_db):
        # value=null with an existing exact row -> soft-delete (active=0), cleared count.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find = MagicMock()
        find.fetchone.return_value = _Attr(spng_target_map_id=77, value=1400)
        clear_result = MagicMock()
        mock_session.execute.side_effect = [find, clear_result]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body([{"ref_id": 10, "param": "speed", "value": None}]),
            )

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"inserted": 0, "updated": 0, "cleared": 1}
        mock_session.commit.assert_called_once()
        # second execute is the clear (active=0) on row 77
        clear_params = _exec_params(mock_session, 1)
        assert clear_params["id"] == 77
        assert clear_params["updated_by"] == 1

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_null_value_no_existing_row_is_noop(self, mock_auth, mock_db):
        # value=null with no existing row -> no clear, no insert, all-zero counts.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find = MagicMock()
        find.fetchone.return_value = None
        mock_session.execute.side_effect = [find]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body([{"ref_id": 10, "param": "speed", "value": None}]),
            )

        assert resp.status_code == 200
        assert resp.json()["data"] == {"inserted": 0, "updated": 0, "cleared": 0}
        # only the find executed; no second statement
        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_called_once()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_rejects_param_not_allowed_for_combo(self, mock_auth, mock_db):
        # spindles is NOT allowed for mcid+target -> 400, whole batch rolled back.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body(
                    [{"ref_id": 10, "param": "spindles", "value": 480}],
                    id_type="mcid",
                    value_role="target",
                ),
            )

        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "spindles" in detail
        mock_session.rollback.assert_called_once()
        # validation happens before any DB statement
        mock_session.execute.assert_not_called()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_rejects_eff_for_qid_actual(self, mock_auth, mock_db):
        # eff is NOT allowed for qid+actual (only standard/target) -> 400, batch rolled back.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body(
                    [{"ref_id": 7, "param": "eff", "value": 85}],
                    id_type="qid",
                    value_role="actual",
                ),
            )

        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        assert "eff" in detail
        mock_session.rollback.assert_called_once()
        mock_session.execute.assert_not_called()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_rejects_negative_value(self, mock_auth, mock_db):
        # negative value -> 400 (in-handler, not Pydantic 422), batch rolled back.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body([{"ref_id": 10, "param": "speed", "value": -5}]),
            )

        assert resp.status_code == 400
        assert "negative" in resp.json()["detail"].lower()
        mock_session.rollback.assert_called_once()
        mock_session.execute.assert_not_called()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_invalid_id_type(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body(
                    [{"ref_id": 10, "param": "speed", "value": 1450}], id_type="zzz"
                ),
            )

        assert resp.status_code == 400
        assert "id_type" in resp.json()["detail"].lower()
        mock_session.rollback.assert_called_once()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_mixed_batch_one_commit(self, mock_auth, mock_db):
        # Two cells: one updates an existing row, one inserts. Single commit at the end.
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find_existing = MagicMock()
        find_existing.fetchone.return_value = _Attr(spng_target_map_id=55, value=1400)
        update_result = MagicMock()
        find_missing = MagicMock()
        find_missing.fetchone.return_value = None
        insert_result = MagicMock()
        # cell 1: find->update ; cell 2: find->insert
        mock_session.execute.side_effect = [
            find_existing,
            update_result,
            find_missing,
            insert_result,
        ]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body(
                    [
                        {"ref_id": 10, "param": "speed", "value": 1450},
                        {"ref_id": 11, "param": "dc", "value": 3},
                    ]
                ),
            )

        assert resp.status_code == 200
        assert resp.json()["data"] == {"inserted": 1, "updated": 1, "cleared": 0}
        mock_session.commit.assert_called_once()

    @patch("src.juteProduction.spng_target_map.get_tenant_db")
    @patch("src.juteProduction.spng_target_map.get_current_user_with_refresh")
    def test_bulk_save_branch_id_passed_to_find_key(self, mock_auth, mock_db):
        # branch_id flows into the exact-key find params (NULL-vs-branch scoping).
        mock_auth.return_value = {"user_id": 1}
        mock_session = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_session

        find = MagicMock()
        find.fetchone.return_value = None
        insert_result = MagicMock()
        mock_session.execute.side_effect = [find, insert_result]

        with _mocked(mock_session):
            resp = client.post(
                "/api/spngTargetMap/target_map_bulk_save",
                json=self._body(
                    [{"ref_id": 10, "param": "speed", "value": 1450}], branch_id=4
                ),
            )

        assert resp.status_code == 200
        find_params = _exec_params(mock_session, 0)
        assert find_params["branch_id"] == 4
        assert find_params["effective_date"] == date(2026, 6, 13)
