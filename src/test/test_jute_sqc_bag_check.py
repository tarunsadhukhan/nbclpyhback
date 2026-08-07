"""
Tests for R-08-24 Bag Checking QC endpoints.
Tests for src/juteSQC/bag_check.py
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


# --- The VERIFIED EXAMPLE — locks the math -----------------------------------
# bag_wt/mr come from the R-08-23 verified 20-row block (avg_bag_wt 564.95, stdev 28.484,
# avg_corr 571.10, obs_hy_lt -2.59, corr_hy_lt -1.53 at std_bag_weight 580 / std_mr 20).
# The other measured columns use 19 copies of a base + 1 adjuster so each column's mean
# equals the spec aggregate exactly (length 93.9, width 57.15, ends 43.8, picks 47.9,
# stitch 8.975).
_BW_MR = [
    (541, 17), (605, 18), (576, 19), (575, 18), (559, 18),
    (588, 19), (547, 19), (566, 18), (541, 19), (566, 18),
    (576, 19), (610, 22), (586, 20), (610, 21), (595, 21),
    (540, 18), (530, 17.5), (520, 18), (523, 17), (545, 17),
]
_WIDTHS = [58.1] + [57.1] * 19   # mean 57.15
_STITCH = [8.5] + [9.0] * 19     # mean 8.975

VERIFIED_STD = {
    "std_bag_weight": 580,
    "std_length": 93,
    "std_width": 57,
    "std_ends": 43,
    "std_picks": 47,
    "std_stitch": 9,
    "std_mr_pct": 20,
}


def _verified_bags():
    bags = []
    for i, (bw, mr) in enumerate(_BW_MR):
        bags.append(
            {
                "length_cm": 93.9,
                "width_cm": _WIDTHS[i],
                "ends_dm": 43.8,
                "picks_dm": 47.9,
                "mr_pct": mr,
                "bag_wt_gm": bw,
                "stitch_dm": _STITCH[i],
                "defects": None,
            }
        )
    return bags


class TestBagCheckEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        bag_row = _mock_row({"item_id": 10, "item_code": "A580", "item_name": "A-Twill Bag 580g"})
        self._mock_session.execute.return_value.fetchall.return_value = [bag_row]

        response = client.get("/api/juteSQC/bag_check_create_setup?co_id=1&branch_id=1")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["default_std_mr_pct"] == 20.0
        assert len(data["bag_types"]) == 1
        assert data["bag_types"][0]["item_name"] == "A-Twill Bag 580g"

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/bag_check_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # --------------------------------------------------- per-bag corr (locked)
    def test_single_bag_corr(self):
        """corr = bag_wt * (100 + std_mr) / (100 + mr). Two locked points: 554.87, 592.94."""
        from src.juteSQC.bag_check import bag_corr
        assert round(bag_corr(541, 17, 20), 2) == 554.87
        assert round(bag_corr(588, 19, 20), 2) == 592.94

    # ----------------------------------------------------------------- create
    def test_create_math_lock(self):
        """Locks the 20-bag block: per-bag corr (554.87, 592.94) stored on the detail rows;
        co_id-scoped header. Aggregates are computed on read (asserted in test_by_date)."""
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "bag_check_id", 42)
        )
        payload = {
            "co_id": 1,
            "branch_id": 1,
            "entry_date": "2026-06-28",
            "item_id": 10,
            "bag_type_label": "A-TYPE",
            "vendor_name": "Acme Jute Co",
            "id_code": "LOT-001",
            "bags": _verified_bags(),
            **VERIFIED_STD,
        }
        response = client.post("/api/juteSQC/create_bag_check", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Bag Checking QC log created successfully"
        assert body["bag_check_id"] == 42
        self._mock_session.commit.assert_called_once()

        # 1 header + 20 detail rows added.
        added = [c[0][0] for c in self._mock_session.add.call_args_list]
        header = added[0]
        details = added[1:]
        assert header.std_bag_weight == 580
        assert header.std_mr_pct == 20
        assert header.vendor_name == "Acme Jute Co"
        assert len(details) == 20
        # bag 0: 541 @ mr 17 -> 554.87 ; bag 5: 588 @ mr 19 -> 592.94
        assert details[0].corr_wt_gm == 554.87
        assert details[5].corr_wt_gm == 592.94
        assert details[0].sl_no == 1

    def test_create_zero_bags(self):
        response = client.post(
            "/api/juteSQC/create_bag_check",
            json={"co_id": 1, "entry_date": "2026-06-28", "bags": [], **VERIFIED_STD},
        )
        assert response.status_code == 400
        assert "at least 1" in response.json()["detail"].lower()

    def test_create_non_positive_measure(self):
        bad = _verified_bags()
        bad[0]["length_cm"] = 0
        response = client.post(
            "/api/juteSQC/create_bag_check",
            json={"co_id": 1, "entry_date": "2026-06-28", "bags": bad, **VERIFIED_STD},
        )
        assert response.status_code == 400
        assert "length_cm" in response.json()["detail"].lower()

    def test_create_non_positive_std(self):
        std = dict(VERIFIED_STD)
        std["std_width"] = 0
        response = client.post(
            "/api/juteSQC/create_bag_check",
            json={"co_id": 1, "entry_date": "2026-06-28", "bags": _verified_bags(), **std},
        )
        assert response.status_code == 400
        assert "std_width" in response.json()["detail"].lower()

    # ---------------------------------------------------------------- by_date
    def test_by_date_aggregates(self):
        """by_date computes per-column avg/stdev/cv/min/max + HY/LT over the 20 bags.
        Locks: avg length 93.9 / width 57.15 / ends 43.8 / picks 47.9 / mr 18.675 /
        bag_wt 564.95 / stitch 8.975 / corr_wt 571.10; bag_wt stdev 28.484 cv 5.04 min 520
        max 610; obs_hy_lt -2.59, corr_hy_lt -1.53."""
        header = _mock_row({
            "bag_check_id": 1,
            "entry_date": "2026-06-28",
            "branch_id": 1,
            "item_id": 10,
            "item_name": "A-Twill Bag 580g",
            "item_code": "A580",
            "bag_type_label": "A-TYPE",
            "vendor_name": "Acme Jute Co",
            "id_code": "LOT-001",
            "std_bag_weight": 580.0,
            "std_length": 93.0,
            "std_width": 57.0,
            "std_ends": 43.0,
            "std_picks": 47.0,
            "std_stitch": 9.0,
            "std_mr_pct": 20.0,
        })
        # Per-bag detail rows: corr re-derived at save (std_mr 20).
        dtl = []
        for i, (bw, mr) in enumerate(_BW_MR):
            dtl.append(_mock_row({
                "sl_no": i + 1,
                "length_cm": 93.9,
                "width_cm": _WIDTHS[i],
                "ends_dm": 43.8,
                "picks_dm": 47.9,
                "mr_pct": mr,
                "bag_wt_gm": bw,
                "stitch_dm": _STITCH[i],
                "defects": None,
                "corr_wt_gm": round(bw * 120 / (100 + mr), 2),
            }))

        # first execute() = header fetch, second = detail fetch.
        self._mock_session.execute.return_value.fetchall.side_effect = [[header], dtl]

        response = client.get(
            "/api/juteSQC/get_bag_check_by_date?co_id=1&branch_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        blocks = response.json()["data"]["blocks"]
        assert len(blocks) == 1
        blk = blocks[0]
        assert len(blk["bags"]) == 20

        agg = blk["aggregates"]
        assert agg["length_cm"]["avg"] == 93.9
        assert agg["width_cm"]["avg"] == 57.15
        assert agg["ends_dm"]["avg"] == 43.8
        assert agg["picks_dm"]["avg"] == 47.9
        assert agg["mr_pct"]["avg"] == 18.675
        assert agg["bag_wt_gm"]["avg"] == 564.95
        assert agg["stitch_dm"]["avg"] == 8.975
        # corr avg is the row-wise mean of the per-bag (2dp-stored) corr; 571.097 -> 571.10 (2dp lock)
        assert round(agg["corr_wt_gm"]["avg"], 2) == 571.1

        assert agg["bag_wt_gm"]["stdev"] == 28.484
        assert agg["bag_wt_gm"]["cv_pct"] == 5.04
        assert agg["bag_wt_gm"]["min"] == 520.0
        assert agg["bag_wt_gm"]["max"] == 610.0

        assert blk["obs_hy_lt_pct"] == -2.59
        assert blk["corr_hy_lt_pct"] == -1.53

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_bag_check_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get("/api/juteSQC/get_bag_check_by_date?entry_date=2026-06-28")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row({
            "bag_check_id": 1,
            "entry_date": "2026-06-28",
            "branch_id": 1,
            "item_id": 10,
            "item_name": "A-Twill Bag 580g",
            "item_code": "A580",
            "bag_type_label": "A-TYPE",
            "vendor_name": "Acme Jute Co",
            "id_code": "LOT-001",
            "std_bag_weight": 580.0,
            "std_length": 93.0,
            "std_width": 57.0,
            "std_ends": 43.0,
            "std_picks": 47.0,
            "std_stitch": 9.0,
            "std_mr_pct": 20.0,
            "bag_count": 20,
            "updated_date_time": "2026-06-28 10:00:00",
        })
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get("/api/juteSQC/get_bag_check_table?co_id=1&page=1&limit=10")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1
        assert body["data"][0]["bag_count"] == 20

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_bag_check_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_table_query_exposes_trend_aggregates(self):
        # Regression: the History (trend) table reads these six per-block weight
        # aggregates straight off the row. The query must compute them (grouped
        # over the detail rows) or the FE history columns render "—". Locks the fix.
        from src.juteSQC.query import get_bag_check_table_query

        sql = str(get_bag_check_table_query())
        for col in (
            "avg_bag_wt", "avg_corr_wt", "bag_wt_stdev",
            "bag_wt_cv_pct", "obs_hy_lt_pct", "corr_hy_lt_pct",
        ):
            assert col in sql, f"history aggregate column {col} missing from table query"
        # CV / HY-LT must be guarded against divide-by-zero (std bag weight / avg > 0).
        assert "STDDEV_SAMP" in sql

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"bag_check_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_bag_check",
            json={"bag_check_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_bag_check",
            json={"bag_check_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
