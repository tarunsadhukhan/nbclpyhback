"""Tests for R-08-05/06/07 Breaker Card (Coarse Side SWT) QC endpoints.

Covers src/juteSQC/breaker_card_swt.py — the carding stage, first report of the
carding/drawing sub-family. Quality is now linked via a BATCH (jute_batch_plan,
branch-scoped) instead of a single line quality:

  * UNIT tests for compute_breaker_card_stats against the verified worked
    examples in the R-08-05/06/07 build plan / report spec (§2 / §5):
      - Row1 HESSIAN (std MR 16): (21.47/32)(20.41/28)(20.81/30)(18.56/26)
        -> calc_wt 20.32, calc_mr 29, calc_corr_wt 18.27 (~18.26), sdev ~0.795,
           cv ~0.0436.
      - Row3 SACKING WEFT (std MR 20): (19.93/32)(19.66/30)(20.63/32)(21.38/35)
        -> calc_corr_wt 18.51, cv ~0.0240.
      - std MR fallback to 16 when None.
      - cv_within_band None when no high edge; 1/0 when a band high edge is given.
    These call the helper directly with EXPLICIT std_mr and are unaffected by the
    batch-linkage change.
  * UNIT tests for compute_grand_averages: quality is linked via batch_plan_id now
    (was item_id). The grand average regroups by batch_plan_id and emits
    batch_plan_id / batch_plan_name keys (NOT item_id / jute_quality). Two rows of
    one batch -> one block with a POOLED CV% (stdev of all corrected cuts / mean of
    corrected cuts) that is provably NOT the mean of the per-row CVs. Rows without a
    batch_plan_id are skipped.
  * ENDPOINT tests via FastAPI dependency_overrides for get_tenant_db +
    get_current_user_with_refresh:
    setup-200 (returns `batches`, not `qualities`), missing-co_id-400,
    missing-branch_id-400, create requires branch_id + a batch per row,
    len!=4-400, empty-rows-400, multi-row create-success (std MR fallback 16,
    persisted batch_plan_id), by-date OBJECT envelope (batch-keyed grand),
    delete-404-when-absent.
"""

import json
import statistics

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.breaker_card_swt import (
    DEFAULT_STD_MR_PCT,
    compute_breaker_card_stats,
    compute_grand_averages,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Verified worked-example fixtures (R-08-05/06/07 report spec §5)
# ---------------------------------------------------------------------------
# Row 1 — Mc 4, Spell A1, HESSIAN side (cached at explicit STD MR 16).
ROW1_WT = [21.47, 20.41, 20.81, 18.56]
ROW1_MR = [32, 28, 30, 26]
# Row 3 — Mc 10, A1, SACKING WEFT (cached at explicit STD MR 20).
ROW3_WT = [19.93, 19.66, 20.63, 21.38]
ROW3_MR = [32, 30, 32, 35]
# Row 2 — second row pooled with Row1 into one batch to exercise the per-batch
# grand average. Chosen so calc_wt == 22.92, calc_mr_pct == 31 (the spec's
# HESSIAN grand pair 20.32 & 22.92 / 29 & 31) -> grand OBS 21.62, CORR ~19.29.
ROW2_WT = [24.0, 22.0, 23.5, 22.18]
ROW2_MR = [32, 30, 31, 31]

STD_MR_HESSIAN = 16.0
STD_MR_SACKING = 20.0


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ===========================================================================
# UNIT — compute_breaker_card_stats (unaffected by the batch-linkage change)
# ===========================================================================
class TestComputeBreakerCardStats:
    """Per-row avg-then-correct stats against the spec's hard-verified numbers.

    These call the helper directly with an EXPLICIT std_mr, so the linkage change
    (item_id -> batch_plan_id) does not touch them."""

    def test_default_std_is_16(self):
        assert DEFAULT_STD_MR_PCT == 16

    def test_row1_hessian_averages(self):
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        # spec: WT 20.32, MR% 29
        assert stats["calc_wt"] == pytest.approx(20.32, abs=0.01)
        assert stats["calc_mr_pct"] == pytest.approx(29.0, abs=0.01)

    def test_row1_hessian_corrected_weight(self):
        """Corr Wt = WT * (100+stdMR) / (100+MR%) = 20.32 * 116/129 ~ 18.27 (~18.26)."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        # 20.3125 * 116 / 129 = 18.2655 -> rounds to 18.27; spec prints 18.26.
        assert stats["calc_corr_wt"] == pytest.approx(18.27, abs=0.01)

    def test_row1_hessian_sdev(self):
        """Sample StDev of the 4 corrected cuts ~ 0.795."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        assert stats["calc_sdev"] == pytest.approx(0.795, abs=0.005)

    def test_row1_hessian_cv(self):
        """cv% = sdev / corr_wt ~ 0.0436 (corrected basis)."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(0.0436, abs=0.0002)

    def test_row1_cv_identity(self):
        """cv% must equal sdev/corr_wt exactly (not some other ratio)."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        expected = stats["calc_sdev"] / stats["calc_corr_wt"]
        assert stats["calc_cv_pct"] == pytest.approx(expected, abs=0.0005)

    def test_row3_sacking_corrected_weight(self):
        """Row3 SACKING WEFT std 20: WT 20.40 @ MR 32.25 -> 20.40*120/132.25 = 18.51."""
        stats = compute_breaker_card_stats(ROW3_WT, ROW3_MR, STD_MR_SACKING, None, None)
        assert stats["calc_wt"] == pytest.approx(20.40, abs=0.01)
        assert stats["calc_mr_pct"] == pytest.approx(32.25, abs=0.01)
        assert stats["calc_corr_wt"] == pytest.approx(18.51, abs=0.01)

    def test_row3_sacking_cv(self):
        """Row3 cv% ~ 0.0240."""
        stats = compute_breaker_card_stats(ROW3_WT, ROW3_MR, STD_MR_SACKING, None, None)
        assert stats["calc_cv_pct"] == pytest.approx(0.0240, abs=0.0002)

    def test_std_mr_fallback_to_16(self):
        """std_mr None falls back to the base-16 standard (=> Row1 corr 18.27).

        The create path now ALWAYS computes with std_mr=None (no per-quality
        lookup), so this fallback is the production path."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, None, None, None)
        assert stats["std_mr_pct"] == 16.0
        # Same as the explicit-16 Row1 correction.
        explicit = compute_breaker_card_stats(
            ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None
        )
        assert stats["calc_corr_wt"] == pytest.approx(explicit["calc_corr_wt"], abs=1e-6)
        assert stats["calc_corr_wt"] == pytest.approx(18.27, abs=0.01)

    def test_cv_within_band_none_when_no_high_edge(self):
        """No band high edge seeded -> cv_within_band is None (not computed).

        The create path passes no band, so persisted cv_within_band is always None."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        assert stats["cv_within_band"] is None
        # Even a low edge alone is informational; still None without a high edge.
        stats_low_only = compute_breaker_card_stats(
            ROW1_WT, ROW1_MR, STD_MR_HESSIAN, 8.0, None
        )
        assert stats_low_only["cv_within_band"] is None

    def test_cv_within_band_pass_when_under_high_edge(self):
        """Row1 cv% 4.36% sits under the HESSIAN 8-10% band -> pass (1)."""
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, 8.0, 10.0)
        assert stats["cv_within_band"] == 1

    def test_cv_within_band_fail_when_over_high_edge(self):
        """A tight high edge below the row's CV% -> fail (0)."""
        # Row1 cv%*100 ~ 4.36; force a high edge of 2.0 so it is exceeded.
        stats = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, 1.0, 2.0)
        assert stats["cv_within_band"] == 0


# ===========================================================================
# UNIT — compute_grand_averages (now batch-keyed)
# ===========================================================================
class TestComputeGrandAverages:
    """Per-BATCH grand-average block recomputed at read (pooled corrected cuts).

    Quality is linked via batch_plan_id now (was item_id): the grand average regroups
    by batch_plan_id and emits batch_plan_id / batch_plan_name keys."""

    def _shaped_row(self, batch_plan_id, batch_name, weights, mr, std_mr):
        """Shape a by-date-style row the way _by_date_row_out emits it."""
        s = compute_breaker_card_stats(weights, mr, std_mr, None, None)
        return {
            "breaker_card_swt_id": None,
            "batch_plan_id": batch_plan_id,
            "batch_plan_name": batch_name,
            "weights": weights,
            "mr_pcts": mr,
            "std_mr_pct": std_mr,
            "calc_wt": s["calc_wt"],
            "calc_mr_pct": s["calc_mr_pct"],
            "calc_corr_wt": s["calc_corr_wt"],
        }

    def test_batch_grand_average_block(self):
        rows = [
            self._shaped_row(10, "BATCH HESSIAN", ROW1_WT, ROW1_MR, STD_MR_HESSIAN),
            self._shaped_row(10, "BATCH HESSIAN", ROW2_WT, ROW2_MR, STD_MR_HESSIAN),
        ]
        blocks = compute_grand_averages(rows)
        assert len(blocks) == 1
        block = blocks[0]
        # Batch-keyed now: batch_plan_id / batch_plan_name; no item_id / jute_quality.
        assert block["batch_plan_id"] == 10
        assert block["batch_plan_name"] == "BATCH HESSIAN"
        assert "item_id" not in block
        assert "jute_quality" not in block
        assert block["row_count"] == 2
        # spec: OBS (20.32+22.92)/2 = 21.62 ; MR% (29+31)/2 = 30 ; CORR ~19.29
        assert block["grand_obs"] == pytest.approx(21.62, abs=0.01)
        assert block["grand_mr_pct"] == pytest.approx(30.0, abs=0.01)
        assert block["grand_corr_wt"] == pytest.approx(19.29, abs=0.02)

    def test_grand_cv_is_pooled_not_mean_of_row_cvs(self):
        """Grand CV% = stdev(ALL corrected cuts) / mean(corrected cuts) — pooled.

        It must NOT equal the mean of the per-row CVs (the spec is explicit:
        the grand CV is over the combined corrected set).
        """
        rows = [
            self._shaped_row(10, "BATCH HESSIAN", ROW1_WT, ROW1_MR, STD_MR_HESSIAN),
            self._shaped_row(10, "BATCH HESSIAN", ROW2_WT, ROW2_MR, STD_MR_HESSIAN),
        ]
        blocks = compute_grand_averages(rows)
        grand_cv = blocks[0]["grand_cv_pct"]

        # Re-derive the expected pooled CV from the same fixture.
        def corr_cuts(w, m, std):
            return [wi * (100.0 + std) / (100.0 + mi) for wi, mi in zip(w, m)]

        pooled = corr_cuts(ROW1_WT, ROW1_MR, 16.0) + corr_cuts(ROW2_WT, ROW2_MR, 16.0)
        expected_pooled_cv = statistics.stdev(pooled) / (sum(pooled) / len(pooled))
        assert grand_cv == pytest.approx(expected_pooled_cv, abs=0.0005)

        # And it must differ from the mean of the per-row CVs.
        cv1 = compute_breaker_card_stats(ROW1_WT, ROW1_MR, 16.0, None, None)["calc_cv_pct"]
        cv2 = compute_breaker_card_stats(ROW2_WT, ROW2_MR, 16.0, None, None)["calc_cv_pct"]
        mean_of_row_cvs = (cv1 + cv2) / 2
        assert grand_cv != pytest.approx(mean_of_row_cvs, abs=0.005)

    def test_single_row_grand_cv_matches_row_cv(self):
        """A single-row batch's grand CV equals that row's CV (pooled = its cuts)."""
        rows = [self._shaped_row(20, "BATCH SACKING", ROW3_WT, ROW3_MR, STD_MR_SACKING)]
        blocks = compute_grand_averages(rows)
        assert len(blocks) == 1
        row_cv = compute_breaker_card_stats(
            ROW3_WT, ROW3_MR, STD_MR_SACKING, None, None
        )["calc_cv_pct"]
        assert blocks[0]["grand_cv_pct"] == pytest.approx(row_cv, abs=0.0005)

    def test_multiple_batches_grouped_separately(self):
        rows = [
            self._shaped_row(10, "BATCH HESSIAN", ROW1_WT, ROW1_MR, STD_MR_HESSIAN),
            self._shaped_row(20, "BATCH SACKING", ROW3_WT, ROW3_MR, STD_MR_SACKING),
        ]
        blocks = compute_grand_averages(rows)
        assert {b["batch_plan_id"] for b in blocks} == {10, 20}

    def test_rows_without_batch_plan_id_skipped(self):
        rows = [
            self._shaped_row(None, None, ROW1_WT, ROW1_MR, STD_MR_HESSIAN),
        ]
        assert compute_grand_averages(rows) == []

    def test_grand_cv_within_band_flag(self):
        """The grand block flags its pooled CV% against std_cv_high carried from the
        rows: pass=1 when grand CV% <= high, fail=0 over it, None when no high edge."""
        r1 = self._shaped_row(10, "BATCH HESSIAN", ROW1_WT, ROW1_MR, STD_MR_HESSIAN)
        r2 = self._shaped_row(10, "BATCH HESSIAN", ROW2_WT, ROW2_MR, STD_MR_HESSIAN)
        # No band on the rows -> grand flag is None.
        assert compute_grand_averages([dict(r1), dict(r2)])[0]["cv_within_band"] is None
        # Pooled grand CV% is ~6.8%. A high edge of 10 passes; 5 fails.
        pass_rows = [{**r1, "std_cv_high": 10.0}, {**r2, "std_cv_high": 10.0}]
        fail_rows = [{**r1, "std_cv_high": 5.0}, {**r2, "std_cv_high": 5.0}]
        pass_block = compute_grand_averages(pass_rows)[0]
        fail_block = compute_grand_averages(fail_rows)[0]
        assert pass_block["std_cv_high"] == 10.0
        assert pass_block["cv_within_band"] == 1
        assert fail_block["cv_within_band"] == 0


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestBreakerCardEndpoints:
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
                "machine_name": "BREAKER CARD 4",
                "mech_code": "BC4",
                "dept_id": 2,
                "dept_name": "Carding",
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
        # No per-quality std fetchone any more — quality is a batch (no single std).
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [spell_row],
            [machine_row],
            [batch_row],
        ]

        response = client.get(
            "/api/juteSQC/get_breaker_card_swt_setup?co_id=1&branch_id=1"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert "spells" in data
        assert "machines" in data
        assert "batches" in data  # batch linkage replaces qualities
        assert "qualities" not in data
        assert "entries" in data
        assert data["machines"][0]["machine_name"] == "BREAKER CARD 4"
        assert data["batches"][0]["batch_plan_id"] == 7
        assert data["batches"][0]["plan_name"] == "BATCH HESSIAN"
        assert data["batches"][0]["line_qty"] == 3
        assert data["entries"] == []

    def test_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/get_breaker_card_swt_setup?branch_id=1")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_branch_id(self):
        response = client.get("/api/juteSQC/get_breaker_card_swt_setup?co_id=1")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_missing_branch_id_400(self):
        """The save is per-branch: body.branch_id None -> 400."""
        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": None,
                "entry_date": "2026-01-05",
                "rows": [
                    {
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
        assert "branch_id" in response.json()["detail"].lower()

    def test_create_missing_batch_400(self):
        """A row with no batch_plan_id -> 400 (the report is batch-linked)."""
        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
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

    def test_create_wrong_weight_count(self):
        """A row with != 4 weights -> 400."""
        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": [21.47, 20.41, 20.81],  # only 3
                        "mr_pcts": [32, 28, 30, 26],
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_wrong_mr_count(self):
        """A row with != 4 MR% readings -> 400."""
        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": ROW1_WT,
                        "mr_pcts": [32, 28, 30],  # only 3
                    }
                ],
            },
        )
        assert response.status_code == 400
        assert "4" in response.json()["detail"]

    def test_create_multi_row_success(self):
        """One save inserts an ARRAY of 2 rows; persisted calc_* are authoritative.

        Rows carry batch_plan_id (batch linkage); no std lookup runs (std MR falls
        back to 16, band unevaluated)."""
        self._mock_session.add_all = MagicMock()
        self._mock_session.commit = MagicMock()

        counter = {"n": 0}

        def _refresh(rec):
            counter["n"] += 1
            setattr(rec, "breaker_card_swt_id", 100 + counter["n"])

        self._mock_session.refresh = MagicMock(side_effect=_refresh)

        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [
                    {
                        "mc_id": 4,
                        "spell_id": 1,
                        "batch_plan_id": 7,
                        "weights": ROW1_WT,
                        "mr_pcts": ROW1_MR,
                    },
                    {
                        "mc_id": 5,
                        "spell_id": 1,
                        "batch_plan_id": 9,
                        "weights": ROW2_WT,
                        "mr_pcts": ROW2_MR,
                    },
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["count"] == 2
        assert body["breaker_card_swt_ids"] == [101, 102]
        self._mock_session.add_all.assert_called_once()
        self._mock_session.commit.assert_called_once()

        # Inspect the persisted ORM rows: server-authoritative stats + batch linkage.
        saved = self._mock_session.add_all.call_args[0][0]
        assert len(saved) == 2
        # Row1: corr ~18.27, std MR fallback 16 (no per-quality std), batch persisted.
        assert saved[0].calc_corr_wt == pytest.approx(18.27, abs=0.01)
        assert saved[0].std_mr_pct == 16.0
        assert saved[0].card_side == "COARSE"
        assert saved[0].batch_plan_id == 7
        # Row2: corr ~20.30, second batch.
        assert saved[1].calc_corr_wt == pytest.approx(20.30, abs=0.02)
        assert saved[1].std_mr_pct == 16.0
        assert saved[1].batch_plan_id == 9

    def test_create_empty_rows_400(self):
        response = client.post(
            "/api/juteSQC/create_breaker_card_swt",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "rows": [],
            },
        )
        assert response.status_code == 400

    def test_by_date_object_envelope(self):
        """Regression guard: by-date returns the OBJECT envelope
        {"data": {"rows": [...], "grand_averages": [...]}}, NOT a bare list.

        Two rows of one batch -> a single batch-keyed grand-average block
        (OBS 21.62, MR% 30, CORR ~19.29). Also asserts the JSON readings round-trip.
        """
        s1 = compute_breaker_card_stats(ROW1_WT, ROW1_MR, STD_MR_HESSIAN, None, None)
        s2 = compute_breaker_card_stats(ROW2_WT, ROW2_MR, STD_MR_HESSIAN, None, None)

        def _persisted_row(swt_id, mc_id, wt, mr, stats):
            return _mock_row(
                {
                    "breaker_card_swt_id": swt_id,
                    "co_id": 1,
                    "branch_id": 1,
                    "entry_date": "2026-01-05",
                    "spell_id": 1,
                    "spell_code": "A1",
                    "mc_id": mc_id,
                    "machine_name": f"BREAKER CARD {mc_id}",
                    "mech_code": f"BC{mc_id}",
                    "item_id": None,
                    "jute_quality": None,
                    "item_code": None,
                    "batch_plan_id": 7,
                    "batch_plan_name": "BATCH HESSIAN",
                    "card_side": "COARSE",
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
            _persisted_row(101, 4, ROW1_WT, ROW1_MR, s1),
            _persisted_row(102, 5, ROW2_WT, ROW2_MR, s2),
        ]

        response = client.get(
            "/api/juteSQC/get_breaker_card_swt_by_date?co_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # OBJECT envelope — not a bare list.
        assert isinstance(data, dict)
        assert "rows" in data
        assert "grand_averages" in data

        rows = data["rows"]
        assert len(rows) == 2
        assert rows[0]["breaker_card_swt_id"] == 101
        # JSON readings parsed back to arrays for the grid.
        assert rows[0]["weights"] == ROW1_WT
        assert rows[0]["mr_pcts"] == ROW1_MR

        grand = data["grand_averages"]
        assert len(grand) == 1
        block = grand[0]
        # grand_averages is batch-keyed now (not item_id).
        assert block["batch_plan_id"] == 7
        assert block["batch_plan_name"] == "BATCH HESSIAN"
        assert "item_id" not in block
        assert block["row_count"] == 2
        assert block["grand_obs"] == pytest.approx(21.62, abs=0.01)
        assert block["grand_mr_pct"] == pytest.approx(30.0, abs=0.01)
        assert block["grand_corr_wt"] == pytest.approx(19.29, abs=0.02)

    def test_by_date_missing_co_id_400(self):
        response = client.get(
            "/api/juteSQC/get_breaker_card_swt_by_date?entry_date=2026-01-05"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_delete_when_absent_404(self):
        # No active row found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/breaker_card_swt_delete/99999")

        assert response.status_code == 404
