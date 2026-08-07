"""Tests for R-08-03 Spreader Roll Sliver Weight QC endpoints.

Covers src/juteSQC/spreader_sliver_wt.py:
  * UNIT tests for compute_spreader_sliver_stats against the verified worked
    example in the R-08-03 build plan (§2): the single moisture correction
    20.32 * (100+16) / (100+29) = 20.32 * 116/129 = 18.27 on a std-MR-16 basis,
    the avg/stdev/CV identity on the CORRECTED series, the std-MR fallback to 16,
    and VARIABLE-length samples (3 and 12 readings). Unlike R-08-04 there are NO
    weight bands / buckets, so there are no band assertions.
  * ENDPOINT tests using FastAPI dependency_overrides for get_tenant_db +
    get_current_user_with_refresh (mirrors test_jute_sqc_spreader_roll_wt.py):
    setup-200, missing-co_id-400, missing-branch_id-400, len<1 (0 readings)-400,
    len>12 (13 readings)-400, create-success, by-date envelope shape + JSON
    round-trip, delete-404-when-absent.
"""

import json
import statistics

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.spreader_sliver_wt import compute_spreader_sliver_stats

client = TestClient(app)


# ---------------------------------------------------------------------------
# Verified worked-example fixtures (R-08-03 build plan §2)
# ---------------------------------------------------------------------------
# The one fully hard-verified number: 20.32 lb/100yds @ 29% MR corrects to 18.27
# on a std-MR-16 basis. The remaining readings are valid same-shape data used to
# exercise the variable-length (3 and 12) paths.
FIXTURE_STD_MR = 16.0

# 3-reading sample (first reading is the verified 20.32 @ 29% -> 18.27).
OBS3 = [20.32, 19.5, 21.1]
MR3 = [29, 27, 31]

# 12-reading sample (max length; first reading is again the verified pair).
OBS12 = [20.32, 19.5, 21.1, 20.0, 18.9, 22.0, 19.8, 20.5, 21.3, 19.0, 20.1, 18.5]
MR12 = [29, 27, 31, 28, 26, 33, 30, 29, 32, 25, 28, 24]


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _expected_corrected(obs, mr, std_mr=FIXTURE_STD_MR):
    return [o * (100.0 + std_mr) / (100.0 + m) for o, m in zip(obs, mr)]


class TestComputeSpreaderSliverStats:
    """Unit tests for the pure stats helper (no bands)."""

    def test_single_correction_hard_verified(self):
        """The one fully hard-verified number: 20.32 * 116 / 129 = 18.27."""
        stats = compute_spreader_sliver_stats(OBS3, MR3, FIXTURE_STD_MR)
        # 20.32 * (100+16) / (100+29) = 20.32 * 116/129 = 18.272 -> 18.27
        assert round(stats["corrected"][0], 2) == 18.27

    def test_full_corrected_series_three(self):
        """Every corrected reading matches the hand-computed vector (3 dp)."""
        stats = compute_spreader_sliver_stats(OBS3, MR3, FIXTURE_STD_MR)
        expected = [round(c, 3) for c in _expected_corrected(OBS3, MR3)]
        got = [round(c, 3) for c in stats["corrected"]]
        assert got == expected

    def test_averages_three(self):
        stats = compute_spreader_sliver_stats(OBS3, MR3, FIXTURE_STD_MR)
        corr = _expected_corrected(OBS3, MR3)
        assert stats["calc_avg_obs"] == pytest.approx(sum(OBS3) / 3, abs=0.001)
        assert stats["calc_avg_mr"] == pytest.approx(sum(MR3) / 3, abs=0.01)
        assert stats["calc_avg_corr"] == pytest.approx(sum(corr) / 3, abs=0.001)

    def test_stdev_and_cv_identity_corrected_basis(self):
        """stdev = sample(n-1) on CORRECTED; CV = stdev/avg_corr (corrected)."""
        stats = compute_spreader_sliver_stats(OBS3, MR3, FIXTURE_STD_MR)
        corr = _expected_corrected(OBS3, MR3)
        expected_stdev = statistics.stdev(corr)
        expected_avg_corr = sum(corr) / 3
        expected_cv = expected_stdev / expected_avg_corr

        assert stats["calc_stdev"] == pytest.approx(expected_stdev, abs=0.0001)
        # CV identity holds on the CORRECTED series.
        assert stats["calc_cv_pct"] == pytest.approx(expected_cv, abs=0.0001)
        # And it must equal the persisted stdev / avg_corr exactly.
        assert stats["calc_cv_pct"] == pytest.approx(
            stats["calc_stdev"] / stats["calc_avg_corr"], abs=0.0002
        )
        # And it must NOT be the observed-basis ratio.
        observed_cv = statistics.stdev(OBS3) / (sum(OBS3) / 3)
        assert stats["calc_cv_pct"] != pytest.approx(observed_cv, abs=0.0001)

    def test_std_mr_fallback_to_16(self):
        """std_mr_pct None falls back to the base-16 standard."""
        stats = compute_spreader_sliver_stats(OBS3, MR3, None)
        assert stats["std_mr_pct"] == 16.0
        # Same fixture, fallback std -> first correction still 18.27.
        assert round(stats["corrected"][0], 2) == 18.27

    def test_variable_length_three_readings(self):
        """A 3-reading sample produces 3 corrected values and valid stats."""
        stats = compute_spreader_sliver_stats(OBS3, MR3, FIXTURE_STD_MR)
        assert len(stats["corrected"]) == 3
        assert stats["calc_avg_corr"] > 0
        assert stats["calc_stdev"] >= 0
        # No band keys exist on the sliver-weight stats (unlike R-08-04).
        assert "band_counts_obs" not in stats
        assert "band_counts_corr" not in stats
        assert "band_edges" not in stats

    def test_variable_length_twelve_readings(self):
        """A 12-reading (max) sample produces 12 corrected values + stats."""
        stats = compute_spreader_sliver_stats(OBS12, MR12, FIXTURE_STD_MR)
        corr = _expected_corrected(OBS12, MR12)
        assert len(stats["corrected"]) == 12
        assert stats["calc_avg_corr"] == pytest.approx(sum(corr) / 12, abs=0.001)
        assert stats["calc_stdev"] == pytest.approx(statistics.stdev(corr), abs=0.0001)
        # First reading is still the verified pair.
        assert round(stats["corrected"][0], 2) == 18.27
        # Still no band keys at the max length.
        assert "band_counts_obs" not in stats
        assert "band_edges" not in stats

    def test_single_reading_stdev_cv_guard(self):
        """n<=1 -> sample stdev and CV are guarded to 0 (no exception)."""
        stats = compute_spreader_sliver_stats([20.32], [29], FIXTURE_STD_MR)
        assert stats["calc_stdev"] == 0.0
        assert stats["calc_cv_pct"] == 0.0
        assert round(stats["corrected"][0], 2) == 18.27


class TestSpreaderSliverWtEndpoints:
    """Endpoint tests with mocked tenant DB + auth via dependency_overrides."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def test_setup_success(self):
        spell_row = _mock_row(
            {
                "spell_id": 1,
                "spell_code": "A1",
                "spell_name": "Shift A",
                "working_hours": 8,
            }
        )
        machine_row = _mock_row(
            {
                "machine_id": 4,
                "machine_name": "SPREADER 4",
                "mech_code": "SP4",
                "dept_id": 2,
                "dept_name": "Spreader",
                "branch_id": 1,
            }
        )
        quality_row = _mock_row(
            {"item_id": 10, "item_name": "MESTA", "item_code": "MST"}
        )

        # Order of execute().fetchall() calls in the setup endpoint:
        #   1) spells, 2) machines, 3) qualities. No entry_date -> no 4th call.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [spell_row],
            [machine_row],
            [quality_row],
        ]

        response = client.get(
            "/api/juteSQC/get_spreader_sliver_wt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "spells" in data
        assert "machines" in data
        assert "qualities" in data
        assert "entries" in data
        assert data["machines"][0]["machine_name"] == "SPREADER 4"
        assert data["qualities"][0]["item_name"] == "MESTA"
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get(
            "/api/juteSQC/get_spreader_sliver_wt_setup?branch_id=1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get(
            "/api/juteSQC/get_spreader_sliver_wt_setup?co_id=1"
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_zero_readings(self):
        """0 readings (below MIN_READINGS) -> 400."""
        response = client.post(
            "/api/juteSQC/create_spreader_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "mc_id": 4,
                "item_id": 10,
                "observed_weights": [],
                "mr_pcts": [],
            },
        )
        assert response.status_code == 400
        assert "12" in response.json()["detail"]

    def test_create_thirteen_readings(self):
        """13 readings (above MAX_READINGS) -> 400."""
        obs13 = OBS12 + [20.0]
        mr13 = MR12 + [30]
        response = client.post(
            "/api/juteSQC/create_spreader_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "mc_id": 4,
                "item_id": 10,
                "observed_weights": obs13,
                "mr_pcts": mr13,
            },
        )
        assert response.status_code == 400
        assert "12" in response.json()["detail"]

    def test_create_success(self):
        # std_mr lookup -> fetchone (None => fallback 16).
        self._mock_session.execute.return_value.fetchone.return_value = None
        self._mock_session.add = MagicMock()
        self._mock_session.commit = MagicMock()
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "spreader_sliver_wt_id", 77)
        )

        response = client.post(
            "/api/juteSQC/create_spreader_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "category": "BENCH",
                "mc_id": 4,
                "item_id": 10,
                "observed_weights": OBS3,
                "mr_pcts": MR3,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["spreader_sliver_wt_id"] == 77
        assert "successfully" in body["data"]["message"].lower()
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # The persisted ORM row carries the server-authoritative stats.
        corr = _expected_corrected(OBS3, MR3)
        saved = self._mock_session.add.call_args[0][0]
        assert saved.std_mr_pct == 16.0
        assert saved.calc_avg_corr == pytest.approx(sum(corr) / 3, abs=0.01)
        assert saved.calc_cv_pct == pytest.approx(
            statistics.stdev(corr) / (sum(corr) / 3), abs=0.0002
        )

    def test_by_date_envelope_shape(self):
        """Regression guard: by-date must return {"data": {"readings": [...]}}.

        The FE useSqcSliverWtByDate hook (and SpreaderSliverWtByDateResponse)
        read resp.data.readings — a bare {"data": [...]} list silently empties
        the grid. Also asserts the JSON readings round-trip back to arrays.
        """
        row = _mock_row(
            {
                "spreader_sliver_wt_id": 77,
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "spell_code": "A1",
                "category": "BENCH",
                "mc_id": 4,
                "machine_name": "SPREADER 4",
                "mech_code": "SP4",
                "item_id": 10,
                "jute_quality": "MESTA",
                "item_code": "MST",
                "sample_length_yds": 5.0,
                "weight_basis": "LB/100YDS",
                "observed_weights": json.dumps(OBS3),
                "mr_pcts": json.dumps(MR3),
                "std_mr_pct": 16.0,
                "calc_avg_obs": 20.31,
                "calc_avg_corr": 18.26,
                "calc_avg_mr": 29.0,
                "calc_stdev": 0.4367,
                "calc_cv_pct": 0.0239,
            }
        )
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get(
            "/api/juteSQC/get_spreader_sliver_wt_by_date?co_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # Object with a "readings" list — NOT a bare list.
        assert isinstance(data, dict)
        assert "readings" in data
        readings = data["readings"]
        assert len(readings) == 1
        assert readings[0]["spreader_sliver_wt_id"] == 77
        # JSON columns parsed back to arrays for the grid.
        assert readings[0]["observed_weights"] == OBS3
        assert readings[0]["mr_pcts"] == MR3

    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/spreader_sliver_wt_delete/99999")

        assert response.status_code == 404
