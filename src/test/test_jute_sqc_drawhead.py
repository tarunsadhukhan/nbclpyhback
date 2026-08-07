"""Tests for R-08-08/09/10 Drawhead + Finisher Card Sliver Weight QC endpoints.

Covers src/juteSQC/draw_sliver_wt.py — the drawing-stage sliver-weight uniformity report
for the three sections DRAWHEAD_SWT / DRAWHEAD_SWP / FINISHER_CARD, each reading carrying an
AM/PM time-band (MORNING / AFTERNOON). Clone of test_jute_sqc_card_sliver.py with the deltas:
section enum DRAW_SECTIONS, an extra time_band header, and the DRAWING std-MR default of 16.

The compute_card_sliver_stats / compute_section_averages / compute_grand_averages helpers are
REUSED from card_sliver_wt (the draw module passes DRAW_STD_MR_PCT=16 explicitly), so the unit
coverage here is a couple of direct compute calls at std=16 + the full create/by_date behavior
that exercises the reuse path end-to-end.

  * UNIT — a couple of direct compute_card_sliver_stats calls at std_mr=16 against the
    cached drawing worked examples (avg-then-correct; sample stdev of the per-cut corrected
    weights wt_i*(100+16)/(100+mr_i); cv = sdev / corr_wt).
  * ENDPOINT — dependency_overrides for get_tenant_db + get_current_user_with_refresh:
    setup-200 ('batches' + 'sections' + 'time_bands'), missing-co_id-400, missing-branch_id-400,
    bad-section-400, missing-batch-400, invalid-time_band-400, len!=4-400, multi-row create-200
    (count + time_band/section/batch persisted, std_mr_pct==16), by-date OBJECT envelope with
    batch-keyed grand_averages, delete-404-when-absent.

Cached drawing numbers (std MR 16, drawing default):
  Finisher-card Hessian MC3: weights [7.099,7.319,6.944,7.143], mr [27,28,25,28]
      -> calc_corr_wt ~ 6.509, calc_cv_pct ~ 0.013.
  10LBS MC6 (mr avg 28): weights [7.05,7.20,7.10,7.13], mr [28,28,28,28]
      -> calc_corr_wt ~ 6.453.
"""

import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

# The draw module REUSES these compute helpers from card_sliver_wt.
from src.juteSQC.card_sliver_wt import (
    compute_card_sliver_stats,
    compute_section_averages,
    compute_grand_averages,
)
from src.juteSQC.draw_sliver_wt import DRAW_STD_MR_PCT, SAMPLE_SIZE
from src.juteSQC.constants import DRAW_SECTIONS, DRAW_TIME_BANDS


client = TestClient(app)


# ---------------------------------------------------------------------------
# Verified worked-example fixtures (drawing stage, std MR 16)
# ---------------------------------------------------------------------------
# Finisher-card Hessian MC3 — corr ~6.509, sdev ~0.0846, cv% ~0.013 at std=16.
HESS_WT = [7.099, 7.319, 6.944, 7.143]
HESS_MR = [27, 28, 25, 28]
# 10LBS MC6 — mr avg 28, corr ~6.453 at std=16.
TENLBS_WT = [7.05, 7.20, 7.10, 7.13]
TENLBS_MR = [28, 28, 28, 28]

STD_MR_DRAW = 16.0  # DRAW_STD_MR_PCT — the cached drawing numbers reproduce here.


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ===========================================================================
# UNIT — compute_card_sliver_stats at std=16 (the reused helper, drawing default)
# ===========================================================================
class TestComputeDrawSliverStats:
    """Direct compute calls at std_mr=16 against the cached drawing examples."""

    def test_draw_std_mr_default_is_16_and_sample_size_4(self):
        assert DRAW_STD_MR_PCT == 16
        assert SAMPLE_SIZE == 4

    def test_hess_mc3_corrected_weight(self):
        """Finisher-card Hessian MC3: COR WT = 7.12625 * 116/127 ~ 6.509."""
        stats = compute_card_sliver_stats(HESS_WT, HESS_MR, STD_MR_DRAW, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(6.509, abs=0.01)
        assert stats["std_mr_pct"] == 16.0

    def test_hess_mc3_cv(self):
        """Finisher-card Hessian MC3: cv% = sdev/corr ~ 0.013."""
        stats = compute_card_sliver_stats(HESS_WT, HESS_MR, STD_MR_DRAW, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(0.013, abs=0.001)

    def test_hess_mc3_cv_identity(self):
        """cv% must equal sdev/corr_wt exactly (corrected basis)."""
        stats = compute_card_sliver_stats(HESS_WT, HESS_MR, STD_MR_DRAW, None, None)
        expected = stats["calc_sdev"] / stats["calc_corr_wt"]
        assert stats["calc_cv_pct"] == pytest.approx(expected, abs=0.0005)

    def test_tenlbs_mc6_corrected_weight(self):
        """10LBS MC6 (mr avg 28): COR WT = 7.12 * 116/128 ~ 6.453."""
        stats = compute_card_sliver_stats(TENLBS_WT, TENLBS_MR, STD_MR_DRAW, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(6.453, abs=0.01)
        assert stats["calc_mr_pct"] == 28.0

    def test_no_cv_band_when_no_high_edge(self):
        """Drawing rows are batch-linked -> no std band seeded -> cv_within_band None."""
        stats = compute_card_sliver_stats(HESS_WT, HESS_MR, STD_MR_DRAW, None, None)
        assert stats["cv_within_band"] is None


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestDrawSliverEndpoints:
    """Endpoint tests with mocked tenant DB + auth via dependency_overrides."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # -- setup --------------------------------------------------------------
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
                "machine_id": 3,
                "machine_name": "DRAW 3",
                "mech_code": "D3",
                "machine_type_name": "Drawing",
                "dept_id": 2,
                "dept_name": "Drawing",
                "branch_id": 1,
            }
        )
        batch_row = _mock_row(
            {
                "batch_plan_id": 7,
                "plan_name": "BATCH HESSIAN",
                "branch_id": 1,
                "line_qty": 3,
            }
        )

        # execute() call order: spells.fetchall, machines.fetchall, batches.fetchall.
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [spell_row],
            [machine_row],
            [batch_row],
        ]

        response = client.get(
            "/api/juteSQC/get_draw_sliver_wt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "sections" in data
        assert "time_bands" in data  # AM/PM header — the draw-stage delta
        assert "spells" in data
        assert "machines" in data
        assert "batches" in data  # batch linkage (no qualities/std_by_section)
        assert "qualities" not in data
        assert "entries" in data
        assert list(data["sections"]) == list(DRAW_SECTIONS)
        assert list(data["time_bands"]) == list(DRAW_TIME_BANDS)
        assert data["machines"][0]["machine_name"] == "DRAW 3"
        assert data["batches"][0]["batch_plan_id"] == 7
        assert data["batches"][0]["plan_name"] == "BATCH HESSIAN"
        assert data["batches"][0]["line_qty"] == 3
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_draw_sliver_wt_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/get_draw_sliver_wt_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # -- create negatives ---------------------------------------------------
    def test_create_missing_branch_400(self):
        """No branch_id on the header -> 400 (branch is required)."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": HESS_WT,
                        "mr_pcts": HESS_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_bad_section_400(self):
        """A row whose section is not one of the 3 valid draw sections -> 400."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",  # a carding section, not a draw section
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": HESS_WT,
                        "mr_pcts": HESS_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "section" in response.json()["detail"].lower()

    def test_create_missing_batch_400(self):
        """A row with no batch_plan_id -> 400 (the report is batch-linked; batch is required)."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": None,  # no batch selected
                        "weights": HESS_WT,
                        "mr_pcts": HESS_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "batch" in response.json()["detail"].lower()

    def test_create_invalid_time_band_400(self):
        """A row with a time_band outside MORNING/AFTERNOON -> 400 (when provided)."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "EVENING",  # not a valid band
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": HESS_WT,
                        "mr_pcts": HESS_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "time_band" in response.json()["detail"].lower()

    def test_create_wrong_weight_count_400(self):
        """A row with != 4 weights -> 400."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": [7.099, 7.319, 6.944],  # only 3
                        "mr_pcts": HESS_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_wrong_mr_count_400(self):
        """A row with != 4 MR% readings -> 400."""
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": HESS_WT,
                        "mr_pcts": [27, 28, 25],  # only 3
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_empty_rows_400(self):
        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [],
            },
        )
        assert response.status_code == 400

    # -- create success -----------------------------------------------------
    def test_create_multi_row_success(self):
        """One save inserts an ARRAY of 2 rows; persisted calc_* are authoritative.

        Rows carry batch_plan_id (batch linkage) + time_band; std MR is fixed at the drawing
        default 16 (passed explicitly), band unevaluated."""
        self._mock_session.add_all = MagicMock()
        self._mock_session.commit = MagicMock()

        counter = {"n": 0}

        def _refresh(rec):
            counter["n"] += 1
            setattr(rec, "draw_sliver_wt_id", 100 + counter["n"])

        self._mock_session.refresh = MagicMock(side_effect=_refresh)

        response = client.post(
            "/api/juteSQC/create_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER_CARD",
                        "time_band": "MORNING",
                        "mc_id": 3,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": HESS_WT,
                        "mr_pcts": HESS_MR,
                    },
                    {
                        "section": "DRAWHEAD_SWT",
                        "time_band": "AFTERNOON",
                        "mc_id": 6,
                        "spell_id": 1,
                        "batch_plan_id": 9,
                        "weights": TENLBS_WT,
                        "mr_pcts": TENLBS_MR,
                    },
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["count"] == 2
        assert body["draw_sliver_wt_ids"] == [101, 102]
        self._mock_session.add_all.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # Inspect the persisted ORM rows: server-authoritative stats + batch + time_band.
        saved = self._mock_session.add_all.call_args[0][0]
        assert len(saved) == 2
        # Row1 (finisher Hessian MC3): corr ~6.509, std MR fixed 16, section/band/batch persisted.
        assert saved[0].calc_corr_wt == pytest.approx(6.509, abs=0.01)
        assert saved[0].std_mr_pct == 16.0
        assert saved[0].section == "FINISHER_CARD"
        assert saved[0].time_band == "MORNING"
        assert saved[0].batch_plan_id == 7
        # Row2 (10LBS MC6): corr ~6.453, DRAWHEAD_SWT, AFTERNOON, second batch.
        assert saved[1].calc_corr_wt == pytest.approx(6.453, abs=0.01)
        assert saved[1].std_mr_pct == 16.0
        assert saved[1].section == "DRAWHEAD_SWT"
        assert saved[1].time_band == "AFTERNOON"
        assert saved[1].batch_plan_id == 9

    # -- by_date envelope ---------------------------------------------------
    def test_by_date_object_envelope(self):
        """by-date returns the OBJECT envelope
        {"data": {"rows": [...], "section_averages": [...], "grand_averages": [...]}}
        with batch-keyed grand_averages."""
        s_hess = compute_card_sliver_stats(HESS_WT, HESS_MR, STD_MR_DRAW, None, None)
        s_ten = compute_card_sliver_stats(TENLBS_WT, TENLBS_MR, STD_MR_DRAW, None, None)

        def _persisted_row(swt_id, mc_id, section, band, wt, mr, stats):
            return _mock_row(
                {
                    "draw_sliver_wt_id": swt_id,
                    "co_id": 1,
                    "branch_id": 1,
                    "entry_date": "2026-01-05",
                    "section": section,
                    "time_band": band,
                    "spell_id": 1,
                    "spell_code": "A1",
                    "mc_id": mc_id,
                    "machine_name": f"DRAW {mc_id}",
                    "mech_code": f"D{mc_id}",
                    "batch_plan_id": 7,
                    "batch_plan_name": "BATCH HESSIAN",
                    "weights": json.dumps(wt),
                    "mr_pcts": json.dumps(mr),
                    "std_mr_pct": 16.0,
                    "std_cv_low": None,
                    "std_cv_high": None,
                    "calc_wt": stats["calc_wt"],
                    "calc_mr_pct": stats["calc_mr_pct"],
                    "calc_corr_wt": stats["calc_corr_wt"],
                    "calc_sdev": stats["calc_sdev"],
                    "calc_cv_pct": stats["calc_cv_pct"],
                    "cv_within_band": None,
                }
            )

        self._mock_session.execute.return_value.fetchall.return_value = [
            _persisted_row(101, 3, "FINISHER_CARD", "MORNING", HESS_WT, HESS_MR, s_hess),
            _persisted_row(102, 3, "FINISHER_CARD", "AFTERNOON", TENLBS_WT, TENLBS_MR, s_ten),
        ]

        response = client.get(
            "/api/juteSQC/get_draw_sliver_wt_by_date?co_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # OBJECT envelope — not a bare list.
        assert isinstance(data, dict)
        assert "rows" in data
        assert "section_averages" in data
        assert "grand_averages" in data

        rows = data["rows"]
        assert len(rows) == 2
        assert rows[0]["draw_sliver_wt_id"] == 101
        assert rows[0]["section"] == "FINISHER_CARD"
        assert rows[0]["time_band"] == "MORNING"
        # JSON readings parsed back to arrays for the grid.
        assert rows[0]["weights"] == HESS_WT
        assert rows[0]["mr_pcts"] == HESS_MR

        section_avgs = data["section_averages"]
        assert len(section_avgs) == 1
        assert section_avgs[0]["section"] == "FINISHER_CARD"
        assert section_avgs[0]["row_count"] == 2

        grand = data["grand_averages"]
        assert len(grand) == 1
        block = grand[0]
        # grand_averages is batch-keyed (not item_id).
        assert block["batch_plan_id"] == 7
        assert block["batch_plan_name"] == "BATCH HESSIAN"
        assert "item_id" not in block
        assert block["row_count"] == 2

    def test_by_date_missing_co_id_400(self):
        response = client.get(
            "/api/juteSQC/get_draw_sliver_wt_by_date?entry_date=2026-01-05"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # -- delete -------------------------------------------------------------
    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/draw_sliver_wt_delete/99999")

        assert response.status_code == 404
