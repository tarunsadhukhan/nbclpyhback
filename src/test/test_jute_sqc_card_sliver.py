"""Tests for R-08-07A Inter Card & Tow Breaker Sliver Weight QC endpoints.

Covers src/juteSQC/card_sliver_wt.py — the carding-stage sliver-weight uniformity
report for the three sub-sections INTER_CARD / TOW_BREAKER / HOPPER. Clone of
test_jute_sqc_breaker_card.py with the structural delta `card_side -> section` and an
extra per-section average block.

  * UNIT tests for compute_card_sliver_stats against the cached worked examples in
    the R-08-07A report spec (avg-then-correct; sample stdev of the per-cut corrected
    weights wt_i*(100+std_mr)/(100+mr_i); cv = sdev / corr_wt).
  * UNIT tests for compute_section_averages (per-SECTION footer) and
    compute_grand_averages (per-BATCH pooled-CV block — quality is now linked via
    batch_plan_id, not item_id).
  * ENDPOINT tests via FastAPI dependency_overrides for get_tenant_db +
    get_current_user_with_refresh: setup-200, missing-co_id-400, missing-branch_id-400,
    bad-section-400, len!=4-400, multi-row create-success, by-date OBJECT envelope,
    delete-404-when-absent.

NOTE on the cached numbers: the spec's cached corrected-weight / sdev / MR% values
(Inter-Card row1: COR WT 19.617, sdev 0.381, MR% 26.75; row3 MC 9A: COR WT 19.032)
reproduce under the report's owner-decision standard MR of 20 (DEFAULT_STD_MR_PCT),
NOT 16 — the correction factor (100+std)/(100+mr) lands those exact numbers only at
std=20. (CV% is std-independent — the std factor cancels — so 0.0194 / 0.0486 hold at
any std.) These tests assert the cached values at std=20 (what the module actually
computes and what the cached sheet encodes) and keep a separate std=16-vs-fallback
distinctness check for the fallback assertion.
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
    DEFAULT_STD_MR_PCT,
    SAMPLE_SIZE,
    compute_card_sliver_stats,
    compute_section_averages,
    compute_grand_averages,
)
from src.juteSQC.constants import CARD_SLIVER_SECTIONS


client = TestClient(app)


# ---------------------------------------------------------------------------
# Verified worked-example fixtures (R-08-07A report spec)
# ---------------------------------------------------------------------------
# Inter-Card row 1 — SACKING WEFT. Cached at owner std MR 20:
#   Avg 20.723, MR% 26.75, COR WT 19.617(~19.619), sdev 0.381, CV% 0.0194.
ROW1_WT = [20.326, 21.076, 20.106, 21.384]
ROW1_MR = [25, 28, 26, 28]
# Inter-Card row 3 — MC 9A. Cached at owner std MR 20:
#   COR WT 19.032(~19.039), CV% 0.0486(~0.0485).
ROW3_WT = [19.40, 18.30, 20.37, 20.94]
ROW3_MR = [24, 23, 25, 26]

STD_MR_OWNER = 20.0  # DEFAULT_STD_MR_PCT — the cached numbers reproduce here.


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ===========================================================================
# UNIT — compute_card_sliver_stats
# ===========================================================================
class TestComputeCardSliverStats:
    """Per-row avg-then-correct stats against the spec's cached numbers."""

    def test_default_std_is_20_and_sample_size_4(self):
        assert DEFAULT_STD_MR_PCT == 20
        assert SAMPLE_SIZE == 4

    # -- A. Inter-Card row1 SACKING WEFT (cached corr/sdev/cv reproduce at std=20) --
    def test_row1_averages(self):
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        assert stats["calc_wt"] == pytest.approx(20.723, abs=0.01)
        assert stats["calc_mr_pct"] == 26.75

    def test_row1_corrected_weight(self):
        """COR WT = Avg * (100+std) / (100+MR%) = 20.723 * 120/126.75 ~ 19.617."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(19.617, abs=0.01)

    def test_row1_sdev(self):
        """Sample StDev of the 4 corrected cuts ~ 0.381."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        assert stats["calc_sdev"] == pytest.approx(0.381, abs=0.01)

    def test_row1_cv(self):
        """cv% = sdev / corr_wt ~ 0.0194 (corrected basis; std-independent)."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(0.0194, abs=0.001)

    def test_row1_cv_identity(self):
        """cv% must equal sdev/corr_wt exactly (not some other ratio)."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        expected = stats["calc_sdev"] / stats["calc_corr_wt"]
        assert stats["calc_cv_pct"] == pytest.approx(expected, abs=0.0005)

    def test_row1_cv_std_independent(self):
        """CV% is invariant to std_mr — the (100+std) factor cancels in sdev/corr."""
        s16 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, 16.0, None, None)
        s20 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, 20.0, None, None)
        assert s16["calc_cv_pct"] == pytest.approx(s20["calc_cv_pct"], abs=1e-6)
        assert s16["calc_cv_pct"] == pytest.approx(0.0194, abs=0.001)

    # -- B. Inter-Card row3 MC 9A (cached corr/cv reproduce at std=20) --
    def test_row3_corrected_weight(self):
        """Row3 COR WT ~ 19.032."""
        stats = compute_card_sliver_stats(ROW3_WT, ROW3_MR, STD_MR_OWNER, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(19.032, abs=0.01)

    def test_row3_cv(self):
        """Row3 cv% ~ 0.0486."""
        stats = compute_card_sliver_stats(ROW3_WT, ROW3_MR, STD_MR_OWNER, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(0.0486, abs=0.001)

    # -- C. FALLBACK: std_mr None uses 20.0 --
    def test_std_mr_fallback_to_20(self):
        """std_mr None falls back to DEFAULT_STD_MR_PCT (20.0)."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, None, None, None)
        assert stats["std_mr_pct"] == 20.0
        # Fallback (=20) corr differs from the explicit std=16 corr for the same input.
        explicit_16 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, 16.0, None, None)
        assert stats["calc_corr_wt"] != pytest.approx(
            explicit_16["calc_corr_wt"], abs=0.05
        )
        # And the fallback corr equals the explicit std=20 corr (the cached 19.617).
        explicit_20 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, 20.0, None, None)
        assert stats["calc_corr_wt"] == pytest.approx(
            explicit_20["calc_corr_wt"], abs=1e-6
        )
        assert stats["calc_corr_wt"] == pytest.approx(19.617, abs=0.01)

    # -- D. cv_within_band edges --
    def test_cv_within_band_none_when_no_high_edge(self):
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        assert stats["cv_within_band"] is None
        # A low edge alone is informational; still None without a high edge.
        low_only = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, 1.0, None)
        assert low_only["cv_within_band"] is None

    def test_cv_within_band_pass_when_under_high_edge(self):
        """Row1 cv% ~1.94% sits under a 5% high edge -> pass (1)."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, 2.0, 5.0)
        assert stats["cv_within_band"] == 1

    def test_cv_within_band_fail_when_over_high_edge(self):
        """A tight high edge (1.0%) below the row's CV% ~1.94% -> fail (0)."""
        stats = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, 0.5, 1.0)
        assert stats["cv_within_band"] == 0


# ===========================================================================
# UNIT — compute_section_averages
# ===========================================================================
class TestComputeSectionAverages:
    """Per-SECTION footer block (unweighted mean of per-row stats)."""

    def _shaped_row(self, section, item_id, quality, weights, mr, std_mr):
        s = compute_card_sliver_stats(weights, mr, std_mr, None, None)
        return {
            "card_sliver_wt_id": None,
            "section": section,
            "item_id": item_id,
            "jute_quality": quality,
            "item_code": "X",
            "weights": weights,
            "mr_pcts": mr,
            "std_mr_pct": std_mr,
            "calc_wt": s["calc_wt"],
            "calc_mr_pct": s["calc_mr_pct"],
            "calc_corr_wt": s["calc_corr_wt"],
            "calc_sdev": s["calc_sdev"],
            "calc_cv_pct": s["calc_cv_pct"],
        }

    def test_one_entry_per_section_with_counts(self):
        """Two INTER_CARD rows + one TOW_BREAKER row -> one entry per section."""
        rows = [
            self._shaped_row("INTER_CARD", 10, "SACKING WEFT", ROW1_WT, ROW1_MR, STD_MR_OWNER),
            self._shaped_row("INTER_CARD", 10, "SACKING WEFT", ROW3_WT, ROW3_MR, STD_MR_OWNER),
            self._shaped_row("TOW_BREAKER", 20, "HESSIAN", ROW1_WT, ROW1_MR, STD_MR_OWNER),
        ]
        blocks = compute_section_averages(rows)
        by_section = {b["section"]: b for b in blocks}
        assert set(by_section) == {"INTER_CARD", "TOW_BREAKER"}
        assert by_section["INTER_CARD"]["row_count"] == 2
        assert by_section["TOW_BREAKER"]["row_count"] == 1

    def test_avg_corr_wt_is_unweighted_mean_of_rows(self):
        """INTER_CARD avg_corr_wt == unweighted mean of the two rows' calc_corr_wt."""
        r1 = self._shaped_row("INTER_CARD", 10, "SACKING WEFT", ROW1_WT, ROW1_MR, STD_MR_OWNER)
        r3 = self._shaped_row("INTER_CARD", 10, "SACKING WEFT", ROW3_WT, ROW3_MR, STD_MR_OWNER)
        blocks = compute_section_averages([r1, r3])
        ic = next(b for b in blocks if b["section"] == "INTER_CARD")
        expected = round((r1["calc_corr_wt"] + r3["calc_corr_wt"]) / 2, 3)
        assert ic["avg_corr_wt"] == pytest.approx(expected, abs=0.001)
        # ~ (19.617 + 19.032) / 2 = 19.329.
        assert ic["avg_corr_wt"] == pytest.approx(19.329, abs=0.01)

    def test_rows_without_section_skipped(self):
        rows = [self._shaped_row(None, 10, "X", ROW1_WT, ROW1_MR, STD_MR_OWNER)]
        assert compute_section_averages(rows) == []


# ===========================================================================
# UNIT — compute_grand_averages
# ===========================================================================
class TestComputeGrandAverages:
    """Per-BATCH grand-average block recomputed at read (pooled corrected cuts).

    Quality is linked via batch_plan_id now (was item_id): the grand-average regroups by
    batch_plan_id and emits batch_plan_id / batch_plan_name keys."""

    def _shaped_row(self, batch_plan_id, batch_name, weights, mr, std_mr, section="INTER_CARD"):
        s = compute_card_sliver_stats(weights, mr, std_mr, None, None)
        return {
            "card_sliver_wt_id": None,
            "section": section,
            "batch_plan_id": batch_plan_id,
            "batch_plan_name": batch_name,
            "weights": weights,
            "mr_pcts": mr,
            "std_mr_pct": std_mr,
            "calc_wt": s["calc_wt"],
            "calc_mr_pct": s["calc_mr_pct"],
            "calc_corr_wt": s["calc_corr_wt"],
        }

    def test_grand_cv_is_pooled_not_mean_of_row_cvs(self):
        """Grand CV% = stdev(ALL corrected cuts) / mean(corrected cuts) — pooled."""
        rows = [
            self._shaped_row(10, "BATCH SACKING", ROW1_WT, ROW1_MR, STD_MR_OWNER),
            self._shaped_row(10, "BATCH SACKING", ROW3_WT, ROW3_MR, STD_MR_OWNER),
        ]
        blocks = compute_grand_averages(rows)
        assert len(blocks) == 1
        block = blocks[0]
        assert block["batch_plan_id"] == 10
        assert block["batch_plan_name"] == "BATCH SACKING"
        assert "item_id" not in block
        assert block["row_count"] == 2

        # Re-derive the expected pooled CV from the same fixture.
        def corr_cuts(w, m, std):
            return [wi * (100.0 + std) / (100.0 + mi) for wi, mi in zip(w, m)]

        pooled = corr_cuts(ROW1_WT, ROW1_MR, 20.0) + corr_cuts(ROW3_WT, ROW3_MR, 20.0)
        expected_pooled_cv = statistics.stdev(pooled) / (sum(pooled) / len(pooled))
        assert block["grand_cv_pct"] == pytest.approx(expected_pooled_cv, abs=0.0005)

        # And it must differ from the mean of the per-row CVs.
        cv1 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, 20.0, None, None)["calc_cv_pct"]
        cv3 = compute_card_sliver_stats(ROW3_WT, ROW3_MR, 20.0, None, None)["calc_cv_pct"]
        mean_of_row_cvs = (cv1 + cv3) / 2
        assert block["grand_cv_pct"] != pytest.approx(mean_of_row_cvs, abs=0.0005)

    def test_grand_obs_and_corr_are_means(self):
        rows = [
            self._shaped_row(10, "BATCH SACKING", ROW1_WT, ROW1_MR, STD_MR_OWNER),
            self._shaped_row(10, "BATCH SACKING", ROW3_WT, ROW3_MR, STD_MR_OWNER),
        ]
        block = compute_grand_averages(rows)[0]
        s1 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        s3 = compute_card_sliver_stats(ROW3_WT, ROW3_MR, STD_MR_OWNER, None, None)
        assert block["grand_obs"] == pytest.approx((s1["calc_wt"] + s3["calc_wt"]) / 2, abs=0.01)
        assert block["grand_corr_wt"] == pytest.approx(19.329, abs=0.01)

    def test_single_row_grand_cv_matches_row_cv(self):
        """A single-row batch's grand CV equals that row's CV (pooled = its cuts)."""
        rows = [self._shaped_row(20, "BATCH HESSIAN", ROW1_WT, ROW1_MR, STD_MR_OWNER)]
        block = compute_grand_averages(rows)[0]
        row_cv = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)["calc_cv_pct"]
        assert block["grand_cv_pct"] == pytest.approx(row_cv, abs=0.0005)

    def test_multiple_batches_grouped_separately(self):
        rows = [
            self._shaped_row(10, "BATCH SACKING", ROW1_WT, ROW1_MR, STD_MR_OWNER),
            self._shaped_row(20, "BATCH HESSIAN", ROW3_WT, ROW3_MR, STD_MR_OWNER, section="TOW_BREAKER"),
        ]
        blocks = compute_grand_averages(rows)
        assert {b["batch_plan_id"] for b in blocks} == {10, 20}

    def test_rows_without_batch_plan_id_skipped(self):
        rows = [self._shaped_row(None, None, ROW1_WT, ROW1_MR, STD_MR_OWNER)]
        assert compute_grand_averages(rows) == []


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestCardSliverEndpoints:
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
                "machine_name": "CARD 4",
                "mech_code": "C4",
                "machine_type_name": "Card",
                "dept_id": 2,
                "dept_name": "Carding",
                "branch_id": 1,
            }
        )
        batch_row = _mock_row(
            {
                "batch_plan_id": 7,
                "plan_name": "BATCH SACKING",
                "branch_id": 1,
                "line_qty": 3,
            }
        )

        # execute() call order: spells.fetchall, machines.fetchall, batches.fetchall.
        # No per-quality std lookup any more — quality is a batch (no single std).
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [spell_row],
            [machine_row],
            [batch_row],
        ]

        response = client.get(
            "/api/juteSQC/get_card_sliver_wt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "sections" in data
        assert "spells" in data
        assert "machines" in data
        assert "batches" in data  # batch linkage replaces qualities/std_by_section
        assert "qualities" not in data
        assert "entries" in data
        assert list(data["sections"]) == list(CARD_SLIVER_SECTIONS)
        assert data["machines"][0]["machine_name"] == "CARD 4"
        assert data["batches"][0]["batch_plan_id"] == 7
        assert data["batches"][0]["plan_name"] == "BATCH SACKING"
        assert data["batches"][0]["line_qty"] == 3
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_card_sliver_wt_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/get_card_sliver_wt_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_bad_section_400(self):
        """A row whose section is not one of the 3 valid -> 400."""
        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "FINISHER",  # not a valid carding section
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": ROW1_WT,
                        "mr_pcts": ROW1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "section" in response.json()["detail"].lower()

    def test_create_missing_batch_400(self):
        """A row with no batch_plan_id -> 400 (the report is batch-linked; batch is required)."""
        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": None,  # no batch selected
                        "weights": ROW1_WT,
                        "mr_pcts": ROW1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "batch" in response.json()["detail"].lower()

    def test_create_wrong_weight_count_400(self):
        """A row with != 4 weights -> 400."""
        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": [20.326, 21.076, 20.106],  # only 3
                        "mr_pcts": ROW1_MR,
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_wrong_mr_count_400(self):
        """A row with != 4 MR% readings -> 400."""
        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": ROW1_WT,
                        "mr_pcts": [25, 28, 26],  # only 3
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_empty_rows_400(self):
        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [],
            },
        )
        assert response.status_code == 400

    def test_create_multi_row_success(self):
        """One save inserts an ARRAY of 2 rows; persisted calc_* are authoritative.

        Rows carry batch_plan_id (batch linkage); no std lookup runs (std MR falls back to 20,
        band unevaluated)."""
        self._mock_session.add_all = MagicMock()
        self._mock_session.commit = MagicMock()

        counter = {"n": 0}

        def _refresh(rec):
            counter["n"] += 1
            setattr(rec, "card_sliver_wt_id", 100 + counter["n"])

        self._mock_session.refresh = MagicMock(side_effect=_refresh)

        response = client.post(
            "/api/juteSQC/create_card_sliver_wt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "section": "INTER_CARD",
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": ROW1_WT,
                        "mr_pcts": ROW1_MR,
                    },
                    {
                        "section": "TOW_BREAKER",
                        "mc_id": 5,
                        "spell_id": 1,
                        "batch_plan_id": 9,
                        "weights": ROW3_WT,
                        "mr_pcts": ROW3_MR,
                    },
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["count"] == 2
        assert body["card_sliver_wt_ids"] == [101, 102]
        self._mock_session.add_all.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # Inspect the persisted ORM rows: server-authoritative stats + batch linkage.
        saved = self._mock_session.add_all.call_args[0][0]
        assert len(saved) == 2
        # Row1: corr ~19.617, std MR fallback 20 (no per-quality std), batch + section persisted.
        assert saved[0].calc_corr_wt == pytest.approx(19.617, abs=0.01)
        assert saved[0].std_mr_pct == 20.0
        assert saved[0].section == "INTER_CARD"
        assert saved[0].batch_plan_id == 7
        # Row2 (=spec row3): corr ~19.032, TOW_BREAKER, second batch.
        assert saved[1].calc_corr_wt == pytest.approx(19.032, abs=0.01)
        assert saved[1].std_mr_pct == 20.0
        assert saved[1].section == "TOW_BREAKER"
        assert saved[1].batch_plan_id == 9

    def test_by_date_object_envelope(self):
        """Regression guard: by-date returns the OBJECT envelope
        {"data": {"rows": [...], "section_averages": [...], "grand_averages": [...]}}.
        """
        s1 = compute_card_sliver_stats(ROW1_WT, ROW1_MR, STD_MR_OWNER, None, None)
        s3 = compute_card_sliver_stats(ROW3_WT, ROW3_MR, STD_MR_OWNER, None, None)

        def _persisted_row(swt_id, mc_id, section, wt, mr, stats):
            return _mock_row(
                {
                    "card_sliver_wt_id": swt_id,
                    "co_id": 1,
                    "branch_id": 1,
                    "entry_date": "2026-01-05",
                    "section": section,
                    "spell_id": 1,
                    "spell_code": "A1",
                    "mc_id": mc_id,
                    "machine_name": f"CARD {mc_id}",
                    "mech_code": f"C{mc_id}",
                    "item_id": None,
                    "jute_quality": None,
                    "item_code": None,
                    "batch_plan_id": 7,
                    "batch_plan_name": "BATCH SACKING",
                    "weights": json.dumps(wt),
                    "mr_pcts": json.dumps(mr),
                    "std_mr_pct": 20.0,
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
            _persisted_row(101, 4, "INTER_CARD", ROW1_WT, ROW1_MR, s1),
            _persisted_row(102, 4, "INTER_CARD", ROW3_WT, ROW3_MR, s3),
        ]

        response = client.get(
            "/api/juteSQC/get_card_sliver_wt_by_date?co_id=1&entry_date=2026-01-05"
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
        assert rows[0]["card_sliver_wt_id"] == 101
        assert rows[0]["section"] == "INTER_CARD"
        # JSON readings parsed back to arrays for the grid.
        assert rows[0]["weights"] == ROW1_WT
        assert rows[0]["mr_pcts"] == ROW1_MR

        section_avgs = data["section_averages"]
        assert len(section_avgs) == 1
        assert section_avgs[0]["section"] == "INTER_CARD"
        assert section_avgs[0]["row_count"] == 2
        assert section_avgs[0]["avg_corr_wt"] == pytest.approx(19.329, abs=0.01)

        grand = data["grand_averages"]
        assert len(grand) == 1
        block = grand[0]
        # grand_averages is batch-keyed now (not item_id).
        assert block["batch_plan_id"] == 7
        assert block["batch_plan_name"] == "BATCH SACKING"
        assert "item_id" not in block
        assert block["row_count"] == 2
        assert block["grand_corr_wt"] == pytest.approx(19.329, abs=0.02)

    def test_by_date_missing_co_id_400(self):
        response = client.get(
            "/api/juteSQC/get_card_sliver_wt_by_date?entry_date=2026-01-05"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/card_sliver_wt_delete/99999")

        assert response.status_code == 404
