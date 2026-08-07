"""Tests for R-08-12/13/14 Finisher Drawing Sliver Weight QC endpoints.

Covers src/juteSQC/fin_draw_sliver_wt.py — the drawing-stage sliver-weight uniformity
report for the three sections HESS / SWP / SWT. Clone of test_jute_sqc_card_sliver.py with
two structural deltas: the section enum is FIN_DRAW_SECTIONS, and each reading carries a
per-cut delivery (DLV) number array (dlv_nos).

The compute_card_sliver_stats / compute_section_averages / compute_grand_averages helpers
are REUSED from card_sliver_wt (R-08-07A) — the drawing module only passes a different std-MR
default (16, fixed explicitly). So those helpers are exercised here via the fin_draw router's
create / by_date behaviour PLUS a couple of direct compute calls at std=16.

  * ENDPOINT tests via FastAPI dependency_overrides for get_tenant_db +
    get_current_user_with_refresh: setup-200 (batches + sections), missing-co_id-400,
    missing-branch_id-400, create requires batch_plan_id + branch_id, bad-section-400,
    len!=4-400, multi-row create-success (dlv_nos + std_mr_pct==16 persisted),
    by-date OBJECT envelope with batch-keyed grand_averages, delete-404-when-absent.
  * A FEW direct compute calls at std=16 to pin the avg-then-correct formula
    (corrected cut = wt_i * (100+16)/(100+mr_i); sample stdev of those; cv = sdev/corr).

NOTE on the cached numbers (std=16): the drawing default MR is 16 (DRAW_STD_MR_PCT), passed
explicitly. Finisher-drawing HESS MC1 (wt [142.2,147.3,132.1,136.5], mr [25,25,23,24]) ->
COR WT ~130.2, CV% ~0.0405; worked HESS MC4 (wt [150.5,148.6,138.4,143.5], mr [26,26,23,24])
-> COR WT ~135.0, CV% ~0.0257. CV% is std-independent (the (100+std) factor cancels), but the
corrected weights here are pinned at the drawing std of 16.
"""

import json
import statistics

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.card_sliver_wt import (
    compute_card_sliver_stats,
    compute_section_averages,
    compute_grand_averages,
)
from src.juteSQC.fin_draw_sliver_wt import DRAW_STD_MR_PCT, SAMPLE_SIZE
from src.juteSQC.constants import FIN_DRAW_SECTIONS


client = TestClient(app)


# ---------------------------------------------------------------------------
# Worked-example fixtures (R-08-12/13/14 — drawing std MR = 16)
# ---------------------------------------------------------------------------
# HESS MC1 — cached at drawing std MR 16: COR WT ~130.26, CV% ~0.0404.
MC1_WT = [142.2, 147.3, 132.1, 136.5]
MC1_MR = [25, 25, 23, 24]
MC1_DLV = [1, 2, 3, 4]
# HESS MC4 — worked at std MR 16: COR WT ~135.06, CV% ~0.0258.
MC4_WT = [150.5, 148.6, 138.4, 143.5]
MC4_MR = [26, 26, 23, 24]
MC4_DLV = [5, 6, 7, 8]

STD_DRAW = 16.0  # DRAW_STD_MR_PCT — drawing-stage owner-decision default.


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _corr_cuts(w, m, std):
    return [wi * (100.0 + std) / (100.0 + mi) for wi, mi in zip(w, m)]


# ===========================================================================
# UNIT — reused compute at the drawing std of 16
# ===========================================================================
class TestComputeAtDrawingStd:
    """A handful of direct compute calls at std=16 — the helpers are shared with the card
    family, so this just pins the avg-then-correct formula at the drawing default."""

    def test_module_constants(self):
        assert DRAW_STD_MR_PCT == 16
        assert SAMPLE_SIZE == 4

    def test_mc1_corrected_and_cv(self):
        """HESS MC1 at std=16 -> COR WT ~130.2, CV% ~0.0405."""
        stats = compute_card_sliver_stats(MC1_WT, MC1_MR, STD_DRAW, None, None)
        assert stats["std_mr_pct"] == 16.0
        assert stats["calc_corr_wt"] == pytest.approx(130.2, abs=0.1)
        assert stats["calc_cv_pct"] == pytest.approx(0.0405, abs=0.001)

    def test_mc4_corrected_and_cv(self):
        """Worked HESS MC4 at std=16 -> COR WT ~135.0, CV% ~0.0257."""
        stats = compute_card_sliver_stats(MC4_WT, MC4_MR, STD_DRAW, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(135.0, abs=0.1)
        assert stats["calc_cv_pct"] == pytest.approx(0.0257, abs=0.001)

    def test_cv_identity(self):
        """cv% must equal sdev/corr_wt exactly."""
        stats = compute_card_sliver_stats(MC1_WT, MC1_MR, STD_DRAW, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(
            stats["calc_sdev"] / stats["calc_corr_wt"], abs=0.0005
        )

    def test_band_unevaluated_without_edges(self):
        """Drawing passes no CV band (batch has no single std) -> cv_within_band None."""
        stats = compute_card_sliver_stats(MC1_WT, MC1_MR, STD_DRAW, None, None)
        assert stats["cv_within_band"] is None


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestFinDrawEndpoints:
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
                "machine_id": 4,
                "machine_name": "DRAW 4",
                "mech_code": "D4",
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
            "/api/juteSQC/get_fin_draw_sliver_wt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "sections" in data
        assert "spells" in data
        assert "machines" in data
        assert "batches" in data
        assert "qualities" not in data
        assert "entries" in data
        assert list(data["sections"]) == list(FIN_DRAW_SECTIONS)
        assert data["machines"][0]["machine_name"] == "DRAW 4"
        assert data["batches"][0]["batch_plan_id"] == 7
        assert data["batches"][0]["plan_name"] == "BATCH HESSIAN"
        assert data["batches"][0]["line_qty"] == 3
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    # -- create negatives ---------------------------------------------------
    def test_create_missing_branch_400(self):
        """No branch_id on the header -> 400 (branch is required)."""
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": None,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "HESS",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "dlv_nos": MC1_DLV,
                        "weights": MC1_WT,
                        "mr_pcts": MC1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "branch" in response.json()["detail"].lower()

    def test_create_bad_section_400(self):
        """A section not in HESS/SWP/SWT -> 400."""
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",  # carding section, not a drawing one
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "dlv_nos": MC1_DLV,
                        "weights": MC1_WT,
                        "mr_pcts": MC1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "section" in response.json()["detail"].lower()

    def test_create_missing_batch_400(self):
        """A row with no batch_plan_id -> 400 (batch-linked report; batch is required)."""
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "HESS",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": None,
                        "dlv_nos": MC1_DLV,
                        "weights": MC1_WT,
                        "mr_pcts": MC1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "batch" in response.json()["detail"].lower()

    def test_create_wrong_weight_count_400(self):
        """A row with != 4 weights -> 400."""
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "HESS",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "dlv_nos": MC1_DLV,
                        "weights": [142.2, 147.3, 132.1],  # only 3
                        "mr_pcts": MC1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_wrong_mr_count_400(self):
        """A row with != 4 MR% readings -> 400."""
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "HESS",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "dlv_nos": MC1_DLV,
                        "weights": MC1_WT,
                        "mr_pcts": [25, 25, 23],  # only 3
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_empty_rows_400(self):
        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
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
        """One save inserts an ARRAY of 2 rows; persisted calc_* + dlv_nos are authoritative,
        std MR fixed at the drawing default 16, band unevaluated."""
        self._mock_session.add_all = MagicMock()
        self._mock_session.commit = MagicMock()

        counter = {"n": 0}

        def _refresh(rec):
            counter["n"] += 1
            setattr(rec, "fin_draw_sliver_wt_id", 100 + counter["n"])

        self._mock_session.refresh = MagicMock(side_effect=_refresh)

        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "HESS",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "dlv_nos": MC1_DLV,
                        "weights": MC1_WT,
                        "mr_pcts": MC1_MR,
                    },
                    {
                        "section": "SWT",
                        "mc_id": 5,
                        "spell_id": 1,
                        "batch_plan_id": 9,
                        "dlv_nos": MC4_DLV,
                        "weights": MC4_WT,
                        "mr_pcts": MC4_MR,
                    },
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["count"] == 2
        assert body["fin_draw_sliver_wt_ids"] == [101, 102]
        self._mock_session.add_all.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # Inspect the persisted ORM rows: server-authoritative stats + batch + dlv linkage.
        saved = self._mock_session.add_all.call_args[0][0]
        assert len(saved) == 2
        # Row1 (HESS MC1): corr ~130.2, std MR fixed 16, batch + section + dlv persisted.
        assert saved[0].calc_corr_wt == pytest.approx(130.2, abs=0.1)
        assert saved[0].calc_cv_pct == pytest.approx(0.0405, abs=0.001)
        assert saved[0].std_mr_pct == 16.0
        assert saved[0].cv_within_band is None
        assert saved[0].section == "HESS"
        assert saved[0].batch_plan_id == 7
        assert json.loads(saved[0].dlv_nos) == MC1_DLV
        # Row2 (SWT MC4): corr ~135.0, second batch, dlv persisted.
        assert saved[1].calc_corr_wt == pytest.approx(135.0, abs=0.1)
        assert saved[1].std_mr_pct == 16.0
        assert saved[1].section == "SWT"
        assert saved[1].batch_plan_id == 9
        assert json.loads(saved[1].dlv_nos) == MC4_DLV

    def test_create_dlv_defaults_to_four_nulls(self):
        """Missing dlv_nos never 400s — it's normalised to 4 nulls and persisted."""
        self._mock_session.add_all = MagicMock()
        self._mock_session.commit = MagicMock()
        self._mock_session.refresh = MagicMock(
            side_effect=lambda rec: setattr(rec, "fin_draw_sliver_wt_id", 1)
        )

        response = client.post(
            "/api/juteSQC/create_fin_draw_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "SWP",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": MC1_WT,
                        "mr_pcts": MC1_MR,
                    }
                ],
            },
        )

        assert response.status_code == 200
        saved = self._mock_session.add_all.call_args[0][0]
        assert json.loads(saved[0].dlv_nos) == [None, None, None, None]

    # -- by_date envelope ---------------------------------------------------
    def test_by_date_object_envelope(self):
        """Regression guard: by-date returns the OBJECT envelope
        {"data": {"rows": [...], "section_averages": [...], "grand_averages": [...]}}
        with batch-keyed grand_averages."""
        s1 = compute_card_sliver_stats(MC1_WT, MC1_MR, STD_DRAW, None, None)
        s4 = compute_card_sliver_stats(MC4_WT, MC4_MR, STD_DRAW, None, None)

        def _persisted_row(swt_id, mc_id, section, wt, mr, dlv, stats):
            return _mock_row(
                {
                    "fin_draw_sliver_wt_id": swt_id,
                    "co_id": 1,
                    "branch_id": 1,
                    "entry_date": "2026-01-05",
                    "section": section,
                    "spell_id": 1,
                    "spell_code": "A1",
                    "mc_id": mc_id,
                    "machine_name": f"DRAW {mc_id}",
                    "mech_code": f"D{mc_id}",
                    "batch_plan_id": 7,
                    "batch_plan_name": "BATCH HESSIAN",
                    "weights": json.dumps(wt),
                    "mr_pcts": json.dumps(mr),
                    "dlv_nos": json.dumps(dlv),
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
            _persisted_row(101, 4, "HESS", MC1_WT, MC1_MR, MC1_DLV, s1),
            _persisted_row(102, 4, "HESS", MC4_WT, MC4_MR, MC4_DLV, s4),
        ]

        response = client.get(
            "/api/juteSQC/get_fin_draw_sliver_wt_by_date?co_id=1&entry_date=2026-01-05"
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
        assert rows[0]["fin_draw_sliver_wt_id"] == 101
        assert rows[0]["section"] == "HESS"
        # JSON readings parsed back to arrays for the grid.
        assert rows[0]["weights"] == MC1_WT
        assert rows[0]["mr_pcts"] == MC1_MR
        assert rows[0]["dlv_nos"] == MC1_DLV

        section_avgs = data["section_averages"]
        assert len(section_avgs) == 1
        assert section_avgs[0]["section"] == "HESS"
        assert section_avgs[0]["row_count"] == 2
        # Unweighted mean of the two corrected weights (~130.26 + ~135.06) / 2 ~ 132.66.
        assert section_avgs[0]["avg_corr_wt"] == pytest.approx(132.66, abs=0.1)

        grand = data["grand_averages"]
        assert len(grand) == 1
        block = grand[0]
        # grand_averages is batch-keyed (not item_id).
        assert block["batch_plan_id"] == 7
        assert block["batch_plan_name"] == "BATCH HESSIAN"
        assert "item_id" not in block
        assert block["row_count"] == 2

        # Pooled grand CV = stdev(ALL corrected cuts) / mean(corrected cuts).
        pooled = _corr_cuts(MC1_WT, MC1_MR, 16.0) + _corr_cuts(MC4_WT, MC4_MR, 16.0)
        expected_pooled_cv = statistics.stdev(pooled) / (sum(pooled) / len(pooled))
        assert block["grand_cv_pct"] == pytest.approx(expected_pooled_cv, abs=0.0005)
        assert block["grand_corr_wt"] == pytest.approx(sum(pooled) / len(pooled), abs=0.05)

    def test_by_date_missing_co_id_400(self):
        response = client.get(
            "/api/juteSQC/get_fin_draw_sliver_wt_by_date?entry_date=2026-01-05"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_by_date_missing_entry_date_400(self):
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_by_date?co_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    # -- table --------------------------------------------------------------
    def test_table_success(self):
        total_row = MagicMock()
        total_row.total = 1
        self._mock_session.execute.return_value.fetchone.return_value = total_row
        self._mock_session.execute.return_value.fetchall.return_value = [
            _mock_row({"fin_draw_sliver_wt_id": 101, "section": "HESS"})
        ]

        response = client.get(
            "/api/juteSQC/get_fin_draw_sliver_wt_table?co_id=1&page=1&limit=10"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["data"][0]["fin_draw_sliver_wt_id"] == 101

    def test_table_missing_co_id_400(self):
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # -- by_id --------------------------------------------------------------
    def test_by_id_success_parses_readings(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {
                "fin_draw_sliver_wt_id": 101,
                "section": "HESS",
                "weights": json.dumps(MC1_WT),
                "mr_pcts": json.dumps(MC1_MR),
                "dlv_nos": json.dumps(MC1_DLV),
            }
        )

        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_by_id?id=101&co_id=1")

        assert response.status_code == 200
        row = response.json()["data"]
        assert row["weights"] == MC1_WT
        assert row["mr_pcts"] == MC1_MR
        assert row["dlv_nos"] == MC1_DLV

    def test_by_id_missing_id_400(self):
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_by_id?co_id=1")
        assert response.status_code == 400
        assert "id" in response.json()["detail"].lower()

    def test_by_id_not_found_404(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.get("/api/juteSQC/get_fin_draw_sliver_wt_by_id?id=99999&co_id=1")
        assert response.status_code == 404

    # -- delete -------------------------------------------------------------
    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/fin_draw_sliver_wt_delete/99999")

        assert response.status_code == 404

    def test_delete_success(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"fin_draw_sliver_wt_id": 101}
        )
        self._mock_session.commit = MagicMock()

        response = client.delete("/api/juteSQC/fin_draw_sliver_wt_delete/101")

        assert response.status_code == 200
        self._mock_session.commit.assert_called_once()
