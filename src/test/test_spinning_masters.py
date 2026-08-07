"""Endpoint tests for src/juteProduction/spinning_masters.py.

The spinning masters router is not (yet) mounted on the main app, so we build
a local FastAPI app, include the router under its production prefix, and use
dependency_overrides for get_tenant_db + get_current_user_with_refresh —
mirroring test_drawing_entry.py's override style.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProduction.spinning_masters import router as spinning_masters_router

app = FastAPI()
app.include_router(spinning_masters_router, prefix="/api/spinningMasters")
client = TestClient(app)


def _row(**attrs):
    row = MagicMock()
    for k, v in attrs.items():
        setattr(row, k, v)
    return row


def _mapping_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _exec_params(mock_session, call_index: int) -> dict:
    return mock_session.execute.call_args_list[call_index][0][1]


class SpinningMastersBase:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()


# =============================================================================
# Trolly master
# =============================================================================


class TestTrollyMaster(SpinningMastersBase):
    def test_trolly_list_requires_co_id(self):
        resp = client.get("/api/spinningMasters/trolly_list")
        assert resp.status_code == 400
        assert "co_id" in resp.json()["detail"].lower()

    def test_trolly_list_aliases_bucket_weight(self):
        row = _mapping_row(
            {
                "trolly_id": 7,
                "trolly_name": "T-7",
                "trolly_weight": 10.0,
                "bucket_weight": 2.0,
                "trolly_posting_code": "TP7",
                "branch_id": 4,
            }
        )
        self._mock_session.execute.return_value.fetchall.return_value = [row]
        resp = client.get("/api/spinningMasters/trolly_list?co_id=1")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data[0]["bucket_weight"] == 2.0
        assert data[0]["trolly_weight"] == 10.0

    def test_trolly_create_success(self):
        insert_result = MagicMock()
        insert_result.lastrowid = 15
        self._mock_session.execute.side_effect = [insert_result]
        body = {
            "trolly_name": "T-15",
            "trolly_weight": 9.5,
            "busket_weight": 1.5,
            "trolly_posting_code": "TP15",
            "branch_id": 4,
            "machine_type_id": 3,
        }
        resp = client.post("/api/spinningMasters/trolly_create", json=body)
        assert resp.status_code == 200
        assert resp.json()["data"]["trolly_id"] == 15
        ins = _exec_params(self._mock_session, 0)
        assert ins["busket_weight"] == 1.5
        assert ins["trolly_weight"] == 9.5
        assert ins["machine_type_id"] == 3
        assert ins["trolly_type"] == "T"

    def test_trolly_create_requires_machine_type(self):
        body = {
            "trolly_name": "T-16",
            "trolly_weight": 9.5,
            "busket_weight": 1.5,
        }
        resp = client.post("/api/spinningMasters/trolly_create", json=body)
        assert resp.status_code == 422

    def test_trolly_list_passes_null_machine_type(self):
        self._mock_session.execute.return_value.fetchall.return_value = []
        resp = client.get("/api/spinningMasters/trolly_list?co_id=1")
        assert resp.status_code == 200
        params = _exec_params(self._mock_session, 0)
        assert params["machine_type_name"] is None

    def test_trolly_edit_persists_machine_type(self):
        select_result = MagicMock()
        select_result.fetchone.return_value = _row(trolly_id=15)
        update_result = MagicMock()
        self._mock_session.execute.side_effect = [select_result, update_result]
        resp = client.put(
            "/api/spinningMasters/trolly_edit/15",
            json={"machine_type_id": 4},
        )
        assert resp.status_code == 200
        upd = _exec_params(self._mock_session, 1)
        assert upd["machine_type_id"] == 4

    def test_trolly_machine_types_returns_stages(self):
        rows = [
            _mapping_row({"machine_type_id": 3, "machine_type_name": "Spinning"}),
            _mapping_row({"machine_type_id": 4, "machine_type_name": "Winding"}),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows
        resp = client.get("/api/spinningMasters/trolly_machine_types")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert {d["machine_type_name"] for d in data} == {"Spinning", "Winding"}
        assert all("machine_type_id" in d for d in data)


# NOTE: TestSpinningMachineAttr was removed — the jute_prod_spinning_machine_attr
# master and its CRUD endpoints were dropped. Machine config (bobbin weight,
# spindles, speed) now lives in jute_prod_spng_target_map; see
# src/test/test_spng_target_map.py.
