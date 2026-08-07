"""
Tests for R-08-21 Width and Picks QC endpoints.
Tests for src/juteSQC/width_picks.py

Includes a math-lock using the VERIFIED EXAMPLE:
  quality std_width_cm 99.06, std_picks 24; rows width/pick =
    [100/24, 99.5/24, 100/25, 100/(null)]
  -> avg_width 99.88, tol 98.56..99.56, remark '$' (99.88 > 99.56);
     avg_picks 24.33, stdev 0.5774, max 25, min 24, pick_count 3.
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


def _create_body(**overrides):
    body = {
        "co_id": 1,
        "branch_id": 2,
        "entry_date": "2026-06-28",
        "item_id": 10,
        "std_width_cm": 99.06,
        "std_picks": 24,
        "inspector_name": "QC1",
        "rows": [
            {"loom_id": 101, "width_cm": 100.0, "picks_dm": 24.0},
            {"loom_id": 102, "width_cm": 99.5, "picks_dm": 24.0},
            {"loom_id": 103, "width_cm": 100.0, "picks_dm": 25.0},
            {"loom_id": 104, "width_cm": 100.0},
        ],
    }
    body.update(overrides)
    return body


def _dtl(loom_id, width_cm, picks_dm):
    return _mock_row(
        {
            "width_picks_dtl_id": loom_id,
            "width_picks_id": 7,
            "loom_id": loom_id,
            "loom_name": f"LOOM {loom_id}",
            "mech_code": f"L{loom_id}",
            "width_cm": width_cm,
            "picks_dm": picks_dm,
        }
    )


class TestWidthPicksEndpoints:
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
        loom1 = _mock_row({"machine_id": 101, "machine_name": "LOOM 1", "mech_code": "L1"})
        loom1_dup = _mock_row({"machine_id": 101, "machine_name": "LOOM 1", "mech_code": "L1"})
        loom2 = _mock_row({"machine_id": 102, "machine_name": "LOOM 2", "mech_code": "L2"})
        # First execute -> cloth qualities; second execute -> looms (with a dup row).
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [cloth_row],
            [loom1, loom1_dup, loom2],
        ]

        response = client.get("/api/juteSQC/width_picks_create_setup?co_id=1&branch_id=2")
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["cloth_qualities"]) == 1
        assert data["cloth_qualities"][0]["item_id"] == 10
        # Duplicate loom de-duped by machine_id -> 2 distinct looms.
        assert len(data["looms"]) == 2
        assert {l["machine_id"] for l in data["looms"]} == {101, 102}

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/width_picks_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        def _flush():
            header = self._mock_session.add.call_args_list[0][0][0]
            header.width_picks_id = 7
        self._mock_session.flush = MagicMock(side_effect=_flush)

        response = client.post("/api/juteSQC/create_width_picks", json=_create_body())
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Width and Picks QC log created successfully"
        assert body["width_picks_id"] == 7
        self._mock_session.commit.assert_called_once()

        # add() called once for the header + once per loom row (4).
        added = [c[0][0] for c in self._mock_session.add.call_args_list]
        assert len(added) == 5
        header = added[0]
        assert header.std_width_cm == 99.06
        assert header.std_picks == 24
        # Optional picks_dm preserved as None on the 4th row.
        assert added[4].picks_dm is None
        assert added[1].picks_dm == 24.0

    def test_create_zero_rows(self):
        response = client.post("/api/juteSQC/create_width_picks", json=_create_body(rows=[]))
        assert response.status_code == 400
        assert "row" in response.json()["detail"].lower()

    def test_create_non_positive_width(self):
        bad = [{"loom_id": 101, "width_cm": 0, "picks_dm": 24.0}]
        response = client.post("/api/juteSQC/create_width_picks", json=_create_body(rows=bad))
        assert response.status_code == 400
        assert "width_cm" in response.json()["detail"]

    def test_create_non_positive_std_width(self):
        response = client.post("/api/juteSQC/create_width_picks", json=_create_body(std_width_cm=0))
        assert response.status_code == 400
        assert "std_width_cm" in response.json()["detail"].lower()

    def test_create_non_positive_std_picks(self):
        response = client.post("/api/juteSQC/create_width_picks", json=_create_body(std_picks=0))
        assert response.status_code == 400
        assert "std_picks" in response.json()["detail"].lower()

    def test_create_non_positive_picks_dm(self):
        bad = [{"loom_id": 101, "width_cm": 100.0, "picks_dm": 0}]
        response = client.post("/api/juteSQC/create_width_picks", json=_create_body(rows=bad))
        assert response.status_code == 400
        assert "picks_dm" in response.json()["detail"]

    # ---------------------------------------------------------------- by_date
    def test_by_date_math_lock(self):
        """VERIFIED EXAMPLE: avg_width 99.88, remark '$', avg_picks 24.33,
        stdev 0.5774, max 25, min 24, pick_count 3."""
        header = _mock_row({
            "width_picks_id": 7, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "std_width_cm": 99.06, "std_picks": 24, "inspector_name": "QC1",
        })
        dtls = [
            _dtl(101, 100.0, 24.0),
            _dtl(102, 99.5, 24.0),
            _dtl(103, 100.0, 25.0),
            _dtl(104, 100.0, None),
        ]
        self._mock_session.execute.return_value.fetchall.side_effect = [[header], dtls]

        response = client.get(
            "/api/juteSQC/get_width_picks_by_date?co_id=1&branch_id=2&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        blocks = response.json()["data"]["blocks"]
        assert len(blocks) == 1
        block = blocks[0]
        assert len(block["rows"]) == 4

        ws = block["width_summary"]
        assert ws["avg_width"] == 99.88
        assert ws["tol_low"] == 98.56
        assert ws["tol_high"] == 99.56
        assert ws["remark"] == "$"

        ps = block["picks_summary"]
        assert ps["avg_picks"] == 24.33
        assert ps["stdev"] == 0.5774
        assert ps["max_picks"] == 25.0
        assert ps["min_picks"] == 24.0
        assert ps["pick_count"] == 3

    def test_by_date_within_band(self):
        """avg_width within +/-0.5% of std -> remark ''."""
        header = _mock_row({
            "width_picks_id": 8, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "std_width_cm": 100.0, "std_picks": 24, "inspector_name": None,
        })
        # widths [100, 100] -> avg 100; tol 99.5..100.5 -> within band.
        dtls = [_dtl(101, 100.0, 24.0), _dtl(102, 100.0, 24.0)]
        self._mock_session.execute.return_value.fetchall.side_effect = [[header], dtls]

        response = client.get(
            "/api/juteSQC/get_width_picks_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        block = response.json()["data"]["blocks"][0]
        assert block["width_summary"]["avg_width"] == 100.0
        assert block["width_summary"]["remark"] == ""

    def test_by_date_width_only_block(self):
        """All picks_dm null -> stdev null, pick_count 0, avg/max/min null."""
        header = _mock_row({
            "width_picks_id": 9, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "std_width_cm": 100.0, "std_picks": 24, "inspector_name": None,
        })
        dtls = [_dtl(101, 100.0, None), _dtl(102, 99.0, None)]
        self._mock_session.execute.return_value.fetchall.side_effect = [[header], dtls]

        response = client.get(
            "/api/juteSQC/get_width_picks_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        ps = response.json()["data"]["blocks"][0]["picks_summary"]
        assert ps["pick_count"] == 0
        assert ps["avg_picks"] is None
        assert ps["stdev"] is None
        assert ps["max_picks"] is None
        assert ps["min_picks"] is None

    def test_by_date_single_pick_stdev_null(self):
        """Only one non-null pick -> stdev null (needs >=2 values), pick_count 1."""
        header = _mock_row({
            "width_picks_id": 11, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "std_width_cm": 100.0, "std_picks": 24, "inspector_name": None,
        })
        dtls = [_dtl(101, 100.0, 24.0), _dtl(102, 100.0, None)]
        self._mock_session.execute.return_value.fetchall.side_effect = [[header], dtls]

        response = client.get(
            "/api/juteSQC/get_width_picks_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        ps = response.json()["data"]["blocks"][0]["picks_summary"]
        assert ps["pick_count"] == 1
        assert ps["avg_picks"] == 24.0
        assert ps["stdev"] is None

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_width_picks_by_date?co_id=1&branch_id=2")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_width_picks_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "width_picks_id": 7, "entry_date": "2026-06-28", "branch_id": 2,
            "item_id": 10, "item_code": "H10", "item_name": "Hessian 10oz",
            "std_width_cm": 99.06, "std_picks": 24, "inspector_name": "QC1",
            "updated_date_time": "2026-06-28 10:00:00", "loom_count": 4,
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_width_picks_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_width_picks_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"width_picks_id": 7, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_width_picks",
            json={"width_picks_id": 7, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_width_picks",
            json={"width_picks_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
