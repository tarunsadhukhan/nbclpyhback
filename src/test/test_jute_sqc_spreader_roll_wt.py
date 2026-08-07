"""Tests for R-08-04 Spreader Roll Weight QC endpoints.

Covers src/juteSQC/spreader_roll_wt.py:
  * UNIT tests for compute_spreader_roll_wt_stats against the verified worked
    example in the R-08-04 build plan / report spec (§2 / §5): the 10-roll MESTA
    sample whose first reading 69.40 kg @ 38% MR corrects to 58.34 on a std-MR-16
    basis, with avg_corr 56.22, stdev_obs 2.89, stdev_corr 2.26, CV 0.0402.
  * ENDPOINT tests using FastAPI dependency_overrides for get_tenant_db +
    get_current_user_with_refresh (mirrors the built reference
    test_jute_sqc_morrah_weight.py for this exact router): setup-200,
    missing-co_id-400, missing-branch_id-400, len!=10-400, create-success,
    delete-404-when-absent.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.spreader_roll_wt import compute_spreader_roll_wt_stats

client = TestClient(app)


# ---------------------------------------------------------------------------
# Verified worked-example fixture (R-08-04 report spec §5, MESTA / SPREADER 4)
# ---------------------------------------------------------------------------
# Observed roll weights (kg) and the parallel MR% readings, std MR base = 16.
FIXTURE_OBS = [69.4, 71.32, 73.24, 67.14, 70.62, 65.91, 67.15, 71.22, 64.38, 66.24]
FIXTURE_MR = [38, 40, 46, 37, 44, 45, 43, 43, 39, 42]
FIXTURE_STD_MR = 16.0


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestComputeSpreaderRollWtStats:
    """Unit tests for the pure stats helper against the verified fixture."""

    def test_single_correction_hard_verified(self):
        """The one fully hard-verified number: 69.40 * 116 / 138 = 58.34."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        # 69.4 * (100+16) / (100+38) = 69.4 * 116/138 = 58.336 -> 58.34
        assert round(stats["corrected"][0], 2) == 58.34

    def test_full_corrected_series(self):
        """Every corrected reading matches the spec's worked vector (2dp)."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        expected = [58.34, 59.09, 58.19, 56.85, 56.89, 52.73, 54.47, 57.77, 53.73, 54.11]
        got = [round(c, 2) for c in stats["corrected"]]
        assert got == expected

    def test_averages(self):
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        # spec: avg_obs 68.66, avg_mr 41.70, avg_corr 56.22
        assert stats["calc_avg_obs"] == pytest.approx(68.66, abs=0.01)
        assert stats["calc_avg_mr_pct"] == pytest.approx(41.70, abs=0.01)
        assert stats["calc_avg_corr"] == pytest.approx(56.22, abs=0.01)

    def test_stdevs(self):
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        # spec: sample (n-1) stdev — obs 2.89, corr 2.26
        assert stats["calc_stdev_obs"] == pytest.approx(2.89, abs=0.01)
        assert stats["calc_stdev_corr"] == pytest.approx(2.26, abs=0.01)

    def test_cv_pct_corrected_basis(self):
        """CV% = stdev_corr / avg_corr on the CORRECTED series ≈ 0.0402."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        # 2.26 / 56.22 = 0.04020; full-precision 2.2555/56.217 = 0.04012.
        # Tolerance spans both the spec's rounded value and the exact value.
        assert stats["calc_cv_pct"] == pytest.approx(0.0402, abs=0.0002)

    def test_cv_identity_holds(self):
        """CV must equal stdev_corr/avg_corr exactly (corrected, not observed)."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        expected_cv = stats["calc_stdev_corr"] / stats["calc_avg_corr"]
        assert stats["calc_cv_pct"] == pytest.approx(expected_cv, abs=0.0002)
        # And it must NOT be the observed-basis ratio (2.89/68.66 = 0.0421).
        observed_cv = stats["calc_stdev_obs"] / stats["calc_avg_obs"]
        assert stats["calc_cv_pct"] != pytest.approx(observed_cv, abs=0.0001)

    def test_band_counts_corrected(self):
        """CORR histogram matches the spec exactly: <55->4, 55-60->6, rest 0."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        # Corrected values (52.73..59.09) all sit at or below 60.
        assert stats["band_counts_corr"] == [4, 6, 0, 0, 0, 0]
        assert sum(stats["band_counts_corr"]) == 10

    def test_band_counts_observed_continuous_edges(self):
        """OBS histogram via the continuous 5-edge bucketer (v <= edge).

        Build plan §2/§4 mandate the continuous-edge bucketer
        (<55 / 55-60 / 61-65 / 66-70 / 71-75 / >75 with v<=edge), so:
          64.38 -> 61-65 ; 65.91,66.24,67.14,67.15,69.40 -> 66-70 ;
          70.62,71.22,71.32,73.24 -> 71-75.
        (The report's worked OBS counts come from integer-rounding the Excel
        boundaries; the persisted server value is the exact-edge histogram.)
        """
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, None
        )
        assert stats["band_counts_obs"] == [0, 0, 1, 5, 4, 0]
        assert sum(stats["band_counts_obs"]) == 10

    def test_std_mr_fallback_to_16(self):
        """std_mr_pct None falls back to the base-16 standard."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, None, None
        )
        assert stats["std_mr_pct"] == 16.0
        # Same fixture, fallback std -> first correction still 58.34.
        assert round(stats["corrected"][0], 2) == 58.34

    def test_custom_band_edges_spreader_2(self):
        """Spreader-2's 85-105 edge set buckets differently (all light here)."""
        stats = compute_spreader_roll_wt_stats(
            FIXTURE_OBS, FIXTURE_MR, FIXTURE_STD_MR, [85, 90, 95, 100, 105]
        )
        # All observed weights (64..73) are below 85 -> first bucket.
        assert stats["band_counts_obs"] == [10, 0, 0, 0, 0, 0]
        assert stats["band_edges"] == [85.0, 90.0, 95.0, 100.0, 105.0]


class TestSpreaderRollWtEndpoints:
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
                "wt_per_roll": 60.0,
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
            "/api/juteSQC/get_spreader_roll_wt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "spells" in data
        assert "machines" in data
        assert "qualities" in data
        assert "entries" in data
        assert data["machines"][0]["machine_name"] == "SPREADER 4"
        assert data["machines"][0]["wt_per_roll"] == 60.0
        assert data["qualities"][0]["item_name"] == "MESTA"
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get(
            "/api/juteSQC/get_spreader_roll_wt_setup?branch_id=1"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get(
            "/api/juteSQC/get_spreader_roll_wt_setup?co_id=1"
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_wrong_weight_count(self):
        response = client.post(
            "/api/juteSQC/create_spreader_roll_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "mc_id": 4,
                "item_id": 10,
                "feeder_name": "Upendra Roy",
                "roll_weights": [69.4, 71.32, 73.24],  # only 3
                "mr_pcts": [38, 40, 46, 37, 44, 45, 43, 43, 39, 42],
            },
        )
        assert response.status_code == 400
        assert "10" in response.json()["detail"]

    def test_create_success(self):
        # std_mr lookup -> fetchone (None => fallback 16); band edges -> fetchone
        # (None => default set). Both reads return None.
        self._mock_session.execute.return_value.fetchone.return_value = None
        self._mock_session.add = MagicMock()
        self._mock_session.commit = MagicMock()
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "spreader_roll_wt_id", 77)
        )

        response = client.post(
            "/api/juteSQC/create_spreader_roll_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "mc_id": 4,
                "item_id": 10,
                "feeder_name": "Upendra Roy",
                "roll_weights": FIXTURE_OBS,
                "mr_pcts": FIXTURE_MR,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["data"]["spreader_roll_wt_id"] == 77
        assert "successfully" in body["data"]["message"].lower()
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # The persisted ORM row carries the server-authoritative stats.
        saved = self._mock_session.add.call_args[0][0]
        assert saved.calc_avg_corr == pytest.approx(56.22, abs=0.01)
        assert saved.std_mr_pct == 16.0
        assert saved.calc_cv_pct == pytest.approx(0.0402, abs=0.0002)

    def test_by_date_envelope_shape(self):
        """Regression guard: by-date must return {"data": {"readings": [...]}}.

        The FE useSqcRollWtByDate hook (and SpreaderRollWtByDateResponse) read
        resp.data.readings — a bare {"data": [...]} list silently empties the
        grid. Also asserts the JSON readings round-trip to arrays.
        """
        import json

        row = _mock_row(
            {
                "spreader_roll_wt_id": 77,
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "spell_id": 1,
                "spell_code": "A1",
                "mc_id": 4,
                "machine_name": "SPREADER 4",
                "mech_code": "SP4",
                "item_id": 10,
                "jute_quality": "MESTA",
                "item_code": "MST",
                "feeder_name": "Upendra Roy",
                "roll_weights": json.dumps(FIXTURE_OBS),
                "mr_pcts": json.dumps(FIXTURE_MR),
                "std_mr_pct": 16.0,
                "calc_avg_mr_pct": 41.70,
                "calc_avg_obs": 68.66,
                "calc_avg_corr": 56.22,
                "calc_stdev_obs": 2.89,
                "calc_stdev_corr": 2.26,
                "calc_cv_pct": 0.0402,
                "band_counts_obs": json.dumps([0, 0, 1, 5, 4, 0]),
                "band_counts_corr": json.dumps([4, 6, 0, 0, 0, 0]),
            }
        )
        self._mock_session.execute.return_value.fetchall.return_value = [row]

        response = client.get(
            "/api/juteSQC/get_spreader_roll_wt_by_date?co_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # Object with a "readings" list — NOT a bare list.
        assert isinstance(data, dict)
        assert "readings" in data
        readings = data["readings"]
        assert len(readings) == 1
        assert readings[0]["spreader_roll_wt_id"] == 77
        # JSON columns parsed back to arrays for the grid.
        assert readings[0]["roll_weights"] == FIXTURE_OBS
        assert readings[0]["band_counts_corr"] == [4, 6, 0, 0, 0, 0]

    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/spreader_roll_wt_delete/99999")

        assert response.status_code == 404
