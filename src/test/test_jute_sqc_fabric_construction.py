"""
Tests for R-08-19 Fabric Construction QC endpoints.
Tests for src/juteSQC/fabric_construction.py
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# A known sample row + its expected server-computed values (std_mr_pct=16):
#   obs_ozs   = round((3.05 * 1000 / 28.3495) / 100, 3) = 1.076
#   crcted_oz = round(1.076 * (116 / 114), 3)            = 1.095
_KNOWN_ROW = {
    "length_yds": 100.0, "width_cms": 102.0, "ends_per_dm": 90.0,
    "picks_per_dm": 88.0, "mr_pct": 14.0, "obs_wt_kg": 3.05,
}
_EXPECTED_OBS_OZS = 1.076
_EXPECTED_CRCTED_OZ = 1.095


def _create_body(**overrides):
    body = {
        "co_id": 1,
        "branch_id": 2,
        "entry_date": "2026-06-28",
        "item_id": 10,
        "quality_text": "Hessian 10oz",
        "std_length_yds": 100.0,
        "std_width_cms": 102.0,
        "std_ends_dm": 90.0,
        "std_picks_dm": 88.0,
        "std_mr_pct": 16.0,
        "std_oz_per_yd": 1.10,
        "rows": [dict(_KNOWN_ROW)],
    }
    body.update(overrides)
    return body


class TestFabricConstructionEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        cloth_row = _mock_row(
            {"item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
             "item_grp_id": 3, "item_grp_name": "Cloth", "item_type_id": 5}
        )
        self._mock_session.execute.return_value.fetchall.return_value = [cloth_row]

        response = client.get(
            "/api/juteSQC/get_fabric_construction_create_setup?co_id=1&branch_id=2"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "cloth_qualities" in data
        assert data["default_std_mr_pct"] == 16.0
        assert data["sample_rows"] == 5
        assert len(data["cloth_qualities"]) == 1
        assert data["cloth_qualities"][0]["item_id"] == 10

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_fabric_construction_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        # The endpoint flushes to obtain the header PK, then refreshes; emulate the
        # DB-assigned id on flush so the detail rows + the returned id are correct.
        def _flush():
            header = self._mock_session.add.call_args_list[0][0][0]
            header.fabric_const_id = 7
        self._mock_session.flush = MagicMock(side_effect=_flush)

        response = client.post("/api/juteSQC/create_fabric_construction", json=_create_body())
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Fabric Construction QC log created successfully"
        assert body["fabric_const_id"] == 7
        self._mock_session.commit.assert_called_once()

        # add() called once for the header + once for the single sample row.
        added = [c[0][0] for c in self._mock_session.add.call_args_list]
        assert len(added) == 2
        header, dtl = added
        # Header snapshots the 6 std values.
        assert header.std_mr_pct == 16.0
        assert header.std_oz_per_yd == 1.10
        # Detail carries the server-computed per-row values for the KNOWN row.
        assert dtl.sl == 1
        assert dtl.obs_ozs == _EXPECTED_OBS_OZS
        assert dtl.crcted_oz == _EXPECTED_CRCTED_OZ

    def test_create_zero_rows(self):
        response = client.post(
            "/api/juteSQC/create_fabric_construction", json=_create_body(rows=[])
        )
        assert response.status_code == 400
        assert "row" in response.json()["detail"].lower()

    def test_create_too_many_rows(self):
        response = client.post(
            "/api/juteSQC/create_fabric_construction",
            json=_create_body(rows=[dict(_KNOWN_ROW) for _ in range(6)]),
        )
        assert response.status_code == 400
        assert "5" in response.json()["detail"]

    def test_create_non_positive_measure(self):
        bad = dict(_KNOWN_ROW)
        bad["width_cms"] = 0
        response = client.post(
            "/api/juteSQC/create_fabric_construction", json=_create_body(rows=[bad])
        )
        assert response.status_code == 400
        assert "width_cms" in response.json()["detail"]

    def test_create_non_positive_std_mr(self):
        response = client.post(
            "/api/juteSQC/create_fabric_construction", json=_create_body(std_mr_pct=0)
        )
        assert response.status_code == 400
        assert "std_mr_pct" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_avg_and_comparison(self):
        header = _mock_row({
            "fabric_const_id": 7, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "quality_text": "Hessian 10oz",
            "std_length_yds": 100.0, "std_width_cms": 100.0, "std_ends_dm": 90.0,
            "std_picks_dm": 88.0, "std_mr_pct": 16.0, "std_oz_per_yd": 1.0,
        })
        # Two sample rows: width avg = (102 + 104)/2 = 103; obs_ozs avg = (1.0 + 1.2)/2 = 1.1.
        dtl1 = _mock_row({
            "fabric_const_dtl_id": 1, "fabric_const_id": 7, "sl": 1,
            "length_yds": 100.0, "width_cms": 102.0, "ends_per_dm": 90.0,
            "picks_per_dm": 88.0, "mr_pct": 14.0, "obs_wt_kg": 3.0,
            "obs_ozs": 1.0, "crcted_oz": 1.02,
        })
        dtl2 = _mock_row({
            "fabric_const_dtl_id": 2, "fabric_const_id": 7, "sl": 2,
            "length_yds": 100.0, "width_cms": 104.0, "ends_per_dm": 90.0,
            "picks_per_dm": 88.0, "mr_pct": 14.0, "obs_wt_kg": 3.2,
            "obs_ozs": 1.2, "crcted_oz": 1.22,
        })
        # First execute -> headers; second execute -> that header's detail rows.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [header],
            [dtl1, dtl2],
        ]

        response = client.get(
            "/api/juteSQC/get_fabric_construction_by_date?co_id=1&branch_id=2&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        blocks = response.json()["data"]["blocks"]
        assert len(blocks) == 1
        block = blocks[0]
        # by_date exposes the sample rows under "rows" (the FE grid reads block.rows).
        assert len(block["rows"]) == 2
        assert block["averages"]["width_cms"] == 103.0
        assert block["averages"]["obs_ozs"] == 1.1

        comp = {c["dimension"]: c for c in block["comparison"]}
        # width: actual 103 vs std 100 -> deviation +3
        assert comp["width_cms"]["std"] == 100.0
        assert comp["width_cms"]["actual"] == 103.0
        assert comp["width_cms"]["deviation"] == 3.0
        # obs_ozs dimension compares against std_oz_per_yd (1.0): actual 1.1 -> deviation 0.1
        assert comp["obs_ozs"]["std"] == 1.0
        assert comp["obs_ozs"]["actual"] == 1.1
        assert comp["obs_ozs"]["deviation"] == 0.1

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_fabric_construction_by_date?co_id=1&branch_id=2")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_fabric_construction_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "fabric_const_id": 7, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "quality_text": "Hessian 10oz",
            "std_length_yds": 100.0, "std_width_cms": 102.0, "std_ends_dm": 90.0,
            "std_picks_dm": 88.0, "std_mr_pct": 16.0, "std_oz_per_yd": 1.10,
            "updated_date_time": "2026-06-28 10:00:00", "sample_count": 5,
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_fabric_construction_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_fabric_construction_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"fabric_const_id": 7, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_fabric_construction",
            json={"fabric_const_id": 7, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_fabric_construction",
            json={"fabric_const_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
