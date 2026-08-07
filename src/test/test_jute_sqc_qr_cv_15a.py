"""Tests for R-08-15A Yarn QR% & CV% Special Purpose QC endpoints.

Covers src/juteSQC/qr_cv_15a.py — the special-purpose QR/CV variant: 2 machines + a
FLAT 12-reading b/s set, yarn-quality (item_id) linked, observed_count / mr_pct
OPERATOR-ENTERED on the header. Clone of test_jute_sqc_card_sliver.py's structure
(FastAPI TestClient + dependency_overrides for get_tenant_db/get_current_user_with_refresh;
direct unit tests of the stats helper; endpoint negatives).

  * UNIT tests for _qr_cv_stats against the R-08-15 formula recomputed from a scratch
    script: readings [5.0,4.8,5.2,5.1] obs_count=5.0 ->
      avg_bs 5.025 (rounds to 5.03), qr_pct = avg/obs*100 = 100.5,
      std_dev = sample(n-1) stdev ~ 0.171 (rounds 0.17),
      cv_pct = std_dev/qr_pct*100 ~ 0.17, qr_at_min = min/obs*100 = 96.0.
  * ENDPOINT tests via dependency_overrides: setup-200, setup missing-co_id/entry_date-400,
    save missing-branch_id-400, save missing-item_id-422, save readings len!=12-400,
    save valid-200 (observed_count/mr_pct persisted on header), by_date OBJECT envelope
    {"data": {"groups": [...]}} with qr/cv/qr_at_min stats, table-200, delete-404-when-absent.
"""

import statistics

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.qr_cv_15a import READINGS, _qr_cv_stats


client = TestClient(app)


# ---------------------------------------------------------------------------
# Worked-example fixture (recomputed in a scratch script before asserting)
# ---------------------------------------------------------------------------
EX_READINGS = [5.0, 4.8, 5.2, 5.1]
EX_OBS_COUNT = 5.0
# avg_bs = 5.025 (rounds 2dp -> 5.03); qr_pct = 5.025/5*100 = 100.5;
# std_dev = sample stdev ~ 0.1708 (rounds 0.17); cv_pct = 0.1708/100.5*100 ~ 0.17;
# qr_at_min = 4.8/5*100 = 96.0.


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _reading_dicts(vals):
    return [{"reading_no": i + 1, "reading_val": v} for i, v in enumerate(vals)]


# ===========================================================================
# UNIT — _qr_cv_stats
# ===========================================================================
class TestQrCvStats:
    """The QR/CV stats helper over the flat readings + header observed_count."""

    def test_readings_constant_is_12(self):
        assert READINGS == 12

    def test_avg_and_qr_pct(self):
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        # avg_bs 5.025 rounds to 5.03; qr_pct = avg/obs*100 = 100.5.
        assert s["avg_bs"] == pytest.approx(5.03, abs=0.001)
        assert s["qr_pct"] == pytest.approx(100.5, abs=0.001)

    def test_qr_pct_identity(self):
        """qr_pct == avg_bs/observed_count*100 (recompute unrounded)."""
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        avg = sum(EX_READINGS) / len(EX_READINGS)
        assert s["qr_pct"] == pytest.approx(round(avg / EX_OBS_COUNT * 100, 2), abs=0.001)
        assert s["qr_pct"] == pytest.approx(100.5, abs=0.001)

    def test_std_dev_is_sample_stdev(self):
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        expected = round(statistics.stdev(EX_READINGS), 2)
        assert s["std_dev"] == pytest.approx(expected, abs=0.001)
        assert s["std_dev"] == pytest.approx(0.17, abs=0.001)

    def test_cv_pct(self):
        """cv_pct = std_dev / qr_pct * 100 ~ 0.17."""
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        avg = sum(EX_READINGS) / len(EX_READINGS)
        qr = avg / EX_OBS_COUNT * 100
        expected = round(statistics.stdev(EX_READINGS) / qr * 100, 2)
        assert s["cv_pct"] == pytest.approx(expected, abs=0.001)
        assert s["cv_pct"] == pytest.approx(0.17, abs=0.01)

    def test_qr_at_min(self):
        """qr_at_min = min/observed_count*100 = 4.8/5*100 = 96.0."""
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        assert s["qr_at_min"] == pytest.approx(96.0, abs=0.001)
        assert s["min"] == pytest.approx(4.8, abs=0.001)
        assert s["max"] == pytest.approx(5.2, abs=0.001)

    def test_n_counts_non_null(self):
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), EX_OBS_COUNT)
        assert s["n"] == 4

    def test_nulls_skipped(self):
        """None cells are excluded from n / avg / stdev."""
        vals = [5.0, None, 5.2, None]
        s = _qr_cv_stats(_reading_dicts(vals), EX_OBS_COUNT)
        assert s["n"] == 2
        assert s["avg_bs"] == pytest.approx(round((5.0 + 5.2) / 2, 2), abs=0.001)

    def test_no_observed_count_yields_none_ratios(self):
        """observed_count None/0 -> qr_pct / cv_pct / qr_at_min are None (guarded)."""
        s = _qr_cv_stats(_reading_dicts(EX_READINGS), None)
        assert s["qr_pct"] is None
        assert s["cv_pct"] is None
        assert s["qr_at_min"] is None
        # avg/std still computed from readings.
        assert s["avg_bs"] == pytest.approx(5.03, abs=0.001)

    def test_empty_readings_all_none(self):
        s = _qr_cv_stats([], EX_OBS_COUNT)
        assert s["n"] == 0
        assert s["avg_bs"] is None
        assert s["std_dev"] is None
        assert s["qr_pct"] is None
        assert s["cv_pct"] is None
        assert s["qr_at_min"] is None

    def test_single_reading_std_dev_zero(self):
        s = _qr_cv_stats(_reading_dicts([5.0]), EX_OBS_COUNT)
        assert s["n"] == 1
        assert s["std_dev"] == 0.0
        assert s["cv_pct"] == 0.0


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestQrCv15aEndpoints:
    """Endpoint tests with mocked tenant DB + auth via dependency_overrides."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # -- setup --
    def test_setup_success(self):
        machine_row = _mock_row(
            {
                "machine_id": 4,
                "machine_name": "DRAW 3",
                "mech_code": "D3",
                "machine_type_name": "Drawing",
                "dept_id": 2,
                "dept_name": "Drawing",
                "branch_id": 1,
            }
        )
        yarn_row = _mock_row(
            {
                "item_id": 50,
                "item_code": "Y50",
                "item_name": "8 LBS",
                "std_count": 8.0,
                "std_mr_pct": 16.0,
            }
        )
        # execute().fetchall call order: machines, yarn-qualities, by-date headers (empty).
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [machine_row],
            [yarn_row],
            [],  # no headers for the date
        ]

        response = client.get(
            "/api/juteSQC/qr_cv_15a_setup?co_id=1&branch_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "machines" in data
        assert "yarn_items" in data
        assert "groups" in data
        assert data["machines"][0]["machine_name"] == "DRAW 3"
        assert data["yarn_items"][0]["item_id"] == 50
        assert data["groups"] == []

    def test_setup_missing_co_id(self):
        response = client.get(
            "/api/juteSQC/qr_cv_15a_setup?branch_id=1&entry_date=2026-01-05"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_entry_date(self):
        response = client.get("/api/juteSQC/qr_cv_15a_setup?co_id=1&branch_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    # -- save --
    def _valid_save_body(self, **over):
        body = {
            "co_id": 1,
            "branch_id": 1,
            "entry_date": "2026-01-05",
            "entries": [
                {
                    "drawing_mc_id": 4,
                    "mc_id": 9,
                    "item_id": 50,
                    "observed_count": EX_OBS_COUNT,
                    "mr_pct": 16.0,
                    "readings": EX_READINGS + [None] * (READINGS - len(EX_READINGS)),
                }
            ],
        }
        body.update(over)
        return body

    def test_save_missing_branch_id_400(self):
        body = self._valid_save_body(branch_id=None)
        response = client.post("/api/juteSQC/qr_cv_15a_save", json=body)
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_save_missing_item_id_422(self):
        """item_id is a required (non-optional) field -> Pydantic 422 before the route runs."""
        body = self._valid_save_body()
        del body["entries"][0]["item_id"]
        response = client.post("/api/juteSQC/qr_cv_15a_save", json=body)
        assert response.status_code == 422

    def test_save_wrong_reading_count_400(self):
        """A test with != 12 readings -> 400."""
        body = self._valid_save_body()
        body["entries"][0]["readings"] = EX_READINGS  # only 4
        response = client.post("/api/juteSQC/qr_cv_15a_save", json=body)
        assert response.status_code == 400
        assert "12" in response.json()["detail"]

    def test_save_success_persists_header_fields(self):
        """Valid save -> 200; header insert binds observed_count / mr_pct from the entry,
        and 12 detail reading rows are inserted."""
        self._mock_session.execute.return_value.lastrowid = 777

        response = client.post(
            "/api/juteSQC/qr_cv_15a_save", json=self._valid_save_body()
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["saved"] == 1
        assert data["ids"] == [777]
        self._mock_session.commit.assert_called_once()

        # 1 header insert + 12 detail inserts = 13 execute() calls.
        assert self._mock_session.execute.call_count == 1 + READINGS

        # The first execute() call is the header insert — inspect its bound params.
        header_params = self._mock_session.execute.call_args_list[0][0][1]
        assert header_params["co_id"] == 1
        assert header_params["branch_id"] == 1
        assert header_params["item_id"] == 50
        assert header_params["observed_count"] == EX_OBS_COUNT
        assert header_params["mr_pct"] == 16.0
        assert header_params["drawing_mc_id"] == 4
        assert header_params["mc_id"] == 9

        # The non-null readings land in the detail inserts in order.
        detail_params = [
            c[0][1] for c in self._mock_session.execute.call_args_list[1:]
        ]
        assert len(detail_params) == READINGS
        assert detail_params[0]["reading_no"] == 1
        assert detail_params[0]["reading_val"] == EX_READINGS[0]
        assert detail_params[3]["reading_val"] == EX_READINGS[3]
        # Padding cells are persisted as None.
        assert detail_params[4]["reading_val"] is None

    # -- by_date --
    def test_by_date_object_envelope_with_stats(self):
        """by_date returns {"data": {"groups": [...]}} with the qr/cv/qr_at_min stats."""
        header_row = _mock_row(
            {
                "qr_cv_15a_id": 101,
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "drawing_mc_id": 4,
                "drawing_mech_code": "D3",
                "drawing_machine_name": "DRAW 3",
                "mc_id": 9,
                "mech_code": "S9",
                "machine_name": "FRAME 9",
                "item_id": 50,
                "item_code": "Y50",
                "item_name": "8 LBS",
                "observed_count": EX_OBS_COUNT,
                "mr_pct": 16.0,
                "updated_date_time": None,
            }
        )
        dtl_rows = [
            _mock_row({"qr_cv_15a_id": 101, "reading_no": i + 1, "reading_val": v})
            for i, v in enumerate(EX_READINGS)
        ]
        # execute().fetchall call order in _qr_cv_groups: headers, then detail rows.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [header_row],
            dtl_rows,
        ]

        response = client.get(
            "/api/juteSQC/qr_cv_15a_by_date?co_id=1&branch_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert isinstance(data, dict)
        assert "groups" in data
        groups = data["groups"]
        assert len(groups) == 1
        g = groups[0]
        assert g["qr_cv_15a_id"] == 101
        assert g["item_id"] == 50
        assert g["observed_count"] == EX_OBS_COUNT
        assert len(g["readings"]) == len(EX_READINGS)

        stats = g["stats"]
        assert stats["avg_bs"] == pytest.approx(5.03, abs=0.001)
        assert stats["qr_pct"] == pytest.approx(100.5, abs=0.001)
        assert stats["std_dev"] == pytest.approx(0.17, abs=0.001)
        assert stats["cv_pct"] == pytest.approx(0.17, abs=0.01)
        assert stats["qr_at_min"] == pytest.approx(96.0, abs=0.001)
        assert stats["n"] == 4

    def test_by_date_missing_co_id_400(self):
        response = client.get("/api/juteSQC/qr_cv_15a_by_date?entry_date=2026-01-05")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_by_date_missing_entry_date_400(self):
        response = client.get("/api/juteSQC/qr_cv_15a_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    # -- table --
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row(
                {
                    "qr_cv_15a_id": 101,
                    "co_id": 1,
                    "branch_id": 1,
                    "entry_date": "2026-01-05",
                    "drawing_mc_id": 4,
                    "drawing_machine_name": "DRAW 3",
                    "mc_id": 9,
                    "machine_name": "FRAME 9",
                    "mech_code": "S9",
                    "item_id": 50,
                    "yarn_quality": "8 LBS",
                    "item_code": "Y50",
                    "observed_count": EX_OBS_COUNT,
                    "mr_pct": 16.0,
                    "updated_date_time": None,
                }
            )
        ]

        response = client.get("/api/juteSQC/qr_cv_15a_table?co_id=1&branch_id=1")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert len(body["data"]) == 1
        assert body["data"][0]["qr_cv_15a_id"] == 101

    def test_table_missing_co_id_400(self):
        response = client.get("/api/juteSQC/qr_cv_15a_table?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # -- delete --
    def test_delete_when_absent_404(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.delete("/api/juteSQC/qr_cv_15a_delete/99999")
        assert response.status_code == 404

    def test_delete_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"qr_cv_15a_id": 101}
        )
        response = client.delete("/api/juteSQC/qr_cv_15a_delete/101")
        assert response.status_code == 200
        self._mock_session.commit.assert_called_once()
