"""
Tests for R-08-23 Bag Weight QC endpoints.
Tests for src/juteSQC/bag_weight.py
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


# The VERIFIED EXAMPLE — locks the math (per-row MR correction + row-wise avg_corr +
# SAMPLE stdev of obs (n-1)). 20 A-TYPE rows; std_bag_weight 580, std_mr 20.
VERIFIED_READINGS = [
    {"mr": 17, "obs": 541},
    {"mr": 18, "obs": 605},
    {"mr": 19, "obs": 576},
    {"mr": 18, "obs": 575},
    {"mr": 18, "obs": 559},
    {"mr": 19, "obs": 588},
    {"mr": 19, "obs": 547},
    {"mr": 18, "obs": 566},
    {"mr": 19, "obs": 541},
    {"mr": 18, "obs": 566},
    {"mr": 19, "obs": 576},
    {"mr": 22, "obs": 610},
    {"mr": 20, "obs": 586},
    {"mr": 21, "obs": 610},
    {"mr": 21, "obs": 595},
    {"mr": 18, "obs": 540},
    {"mr": 17.5, "obs": 530},
    {"mr": 18, "obs": 520},
    {"mr": 17, "obs": 523},
    {"mr": 17, "obs": 545},
]
VERIFIED_STD_BW = 580
VERIFIED_STD_MR = 20
# Stored (calc_*) values: avg_mr 3dp, weights 2dp, stdev 3dp, cv/hy-lt 2dp.
VERIFIED_AVG_MR = 18.675
VERIFIED_AVG_OBS = 564.95
VERIFIED_AVG_CORR = 571.1
VERIFIED_OBS_STDEV = 28.484
VERIFIED_OBS_CV = 5.04
VERIFIED_OBS_HY_LT = -2.59
VERIFIED_CORR_HY_LT = -1.53


class TestBagWeightEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        bag_row = _mock_row({"item_id": 10, "item_code": "A580", "item_name": "A-Twill 580g"})
        self._mock_session.execute.return_value.fetchall.return_value = [bag_row]

        response = client.get("/api/juteSQC/bag_weight_create_setup?co_id=1&branch_id=1")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "max_rows" not in data
        assert data["default_std_mr_pct"] == 20.0
        assert len(data["bag_types"]) == 1
        assert data["bag_types"][0]["item_name"] == "A-Twill 580g"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/bag_weight_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------- per-row corr checks
    def test_single_row_corr(self):
        """corr = obs * (100 + std_mr) / (100 + mr). Two locked points: 554.87, 600.0."""
        from src.juteSQC.bag_weight import row_corr
        assert round(row_corr(541, 17, 20), 2) == 554.87
        assert round(row_corr(610, 22, 20), 2) == 600.0

    # ----------------------------------------------------------------- create
    def test_create_math_lock(self):
        """Locks the whole 20-row block: avg_mr 18.675, avg_obs 564.95, avg_corr 571.10
        (row-wise), obs_stdev 28.484, obs_cv 5.04, obs_hy_lt -2.59, corr_hy_lt -1.53."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "bag_weight_id", 42)
        )
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-06-28",
                "item_id": 10,
                "bag_type_label": "A-TYPE",
                "std_bag_weight": VERIFIED_STD_BW,
                "std_mr_pct": VERIFIED_STD_MR,
                "readings": VERIFIED_READINGS,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Bag weight QC log created successfully"
        assert body["bag_weight_id"] == 42
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

        record = self._mock_session.add.call_args[0][0]
        assert record.calc_avg_mr == VERIFIED_AVG_MR
        assert record.calc_avg_obs_wt == VERIFIED_AVG_OBS
        assert record.calc_avg_corr_wt == VERIFIED_AVG_CORR
        assert record.calc_obs_stdev == VERIFIED_OBS_STDEV
        assert record.calc_obs_cv_pct == VERIFIED_OBS_CV
        assert record.calc_obs_hy_lt_pct == VERIFIED_OBS_HY_LT
        assert record.calc_corr_hy_lt_pct == VERIFIED_CORR_HY_LT

    def test_create_single_row_stdev_null(self):
        """<2 rows -> obs_stdev (and cv) null; HY/LT still computed from the single obs."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "bag_weight_id", 43)
        )
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 20,
                "readings": [{"mr": 17, "obs": 541}],
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_obs_stdev is None
        assert record.calc_obs_cv_pct is None
        assert record.calc_avg_corr_wt == 554.87

    def test_create_zero_rows(self):
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 20,
                "readings": [],
            },
        )
        assert response.status_code == 400
        assert "at least 1" in response.json()["detail"].lower()

    def test_create_many_rows_allowed(self):
        """No upper cap on reading rows — a large block (100 rows) saves fine."""
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 20,
                "readings": [{"mr": 18, "obs": 560}] * 100,
            },
        )
        assert response.status_code == 200

    def test_create_non_positive_mr(self):
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 20,
                "readings": [{"mr": 0, "obs": 541}],
            },
        )
        assert response.status_code == 400
        assert "mr" in response.json()["detail"].lower()

    def test_create_non_positive_obs(self):
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 20,
                "readings": [{"mr": 17, "obs": 0}],
            },
        )
        assert response.status_code == 400
        assert "obs" in response.json()["detail"].lower()

    def test_create_non_positive_std_bag_weight(self):
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 0,
                "std_mr_pct": 20,
                "readings": [{"mr": 17, "obs": 541}],
            },
        )
        assert response.status_code == 400
        assert "std_bag_weight" in response.json()["detail"].lower()

    def test_create_non_positive_std_mr(self):
        response = client.post(
            "/api/juteSQC/create_bag_weight",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "std_bag_weight": 580,
                "std_mr_pct": 0,
                "readings": [{"mr": 17, "obs": 541}],
            },
        )
        assert response.status_code == 400
        assert "std_mr_pct" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_success(self):
        row = _mock_row({
            "bag_weight_id": 1,
            "item_id": 10,
            "item_name": "A-Twill 580g",
            "item_code": "A580",
            "bag_type_label": "A-TYPE",
            "std_bag_weight": 580.0,
            "std_mr_pct": 20.0,
            "readings": '[{"mr": 17, "obs": 541}, {"mr": 22, "obs": 610}]',
            "avg_mr": 18.675,
            "avg_obs": 564.95,
            "avg_corr": 571.1,
            "obs_stdev": 28.484,
            "obs_cv_pct": 5.04,
            "obs_hy_lt_pct": -2.59,
            "corr_hy_lt_pct": -1.53,
        })
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get(
            "/api/juteSQC/get_bag_weight_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        blocks = response.json()["data"]["blocks"]
        assert len(blocks) == 1
        first = blocks[0]
        assert isinstance(first["readings"], list) and len(first["readings"]) == 2
        # per-row corr re-derived on read from the snapshotted std_mr_pct (20)
        assert first["readings"][0]["corr"] == 554.87
        assert first["readings"][1]["corr"] == 600.0
        assert first["avg_corr"] == 571.1
        assert first["obs_hy_lt_pct"] == -2.59

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_bag_weight_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_bag_weight_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "bag_weight_id": 1,
            "entry_date": "2026-06-28",
            "branch_id": 1,
            "item_id": 10,
            "item_name": "A-Twill 580g",
            "item_code": "A580",
            "bag_type_label": "A-TYPE",
            "std_bag_weight": 580.0,
            "std_mr_pct": 20.0,
            "avg_mr": 18.675,
            "avg_obs": 564.95,
            "avg_corr": 571.1,
            "obs_stdev": 28.484,
            "obs_cv_pct": 5.04,
            "obs_hy_lt_pct": -2.59,
            "corr_hy_lt_pct": -1.53,
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_bag_weight_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_bag_weight_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"bag_weight_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_bag_weight",
            json={"bag_weight_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_bag_weight",
            json={"bag_weight_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
