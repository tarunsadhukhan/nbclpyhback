"""Tests for R-08-17 Yarn TPI & TPI CV% QC endpoints.

Covers src/juteSQC/yarn_tpi.py — the 20-reading twist-uniformity study (one saved
group = (date, machine, item_id) carrying 20 TPI readings, cells may be null). Clone
of the test_jute_sqc_card_sliver.py structure (FastAPI TestClient + dependency_overrides
for get_tenant_db / get_current_user_with_refresh; direct unit tests of the stats helper;
endpoint negatives).

  * UNIT tests for _tpi_stats against the worked example readings [5.0, 4.7, 5.3, 5.1]:
    avg_tpi 5.025, std_dev SAMPLE stdev ~0.250, cv_pct = std_dev/avg*100 ~4.98,
    min 4.7, max 5.3. (NOTE: the module rounds every returned value to 2dp, so the
    literal returns are avg 5.03 / std 0.25 / cv 4.98 — these tests assert the formula
    values with a 0.01 tolerance that covers the rounding.)
  * ENDPOINT tests via dependency_overrides: setup-200 / missing-co_id-400 /
    missing-entry_date-400; save missing-branch_id-400, missing-item_id-422 (item_id is
    a required Pydantic field — rejected BEFORE the handler; cannot be a 400),
    readings len!=20-400, valid-200 + saved count + header snapshot (std_tpi / tp_value /
    count_lbs) persisted; by_date OBJECT envelope {"data": {"groups": [...]}} with stats;
    delete-404-when-absent.
"""

import statistics

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.yarn_tpi import SAMPLE_SIZE, _tpi_stats


client = TestClient(app)


# ---------------------------------------------------------------------------
# Worked-example fixture (R-08-17 spec)
# ---------------------------------------------------------------------------
# 4 non-null readings -> avg 5.025, sample stdev ~0.250, cv ~4.98, min 4.7, max 5.3.
READINGS = [5.0, 4.7, 5.3, 5.1]


def _reading_rows(vals):
    """_tpi_stats consumes a list of {"reading_val": x} dicts (nulls allowed)."""
    return [{"reading_no": i + 1, "reading_val": v} for i, v in enumerate(vals)]


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


# ===========================================================================
# UNIT — _tpi_stats
# ===========================================================================
class TestTpiStats:
    """Server-side TPI stats over the non-null readings (RAW, no MR correction)."""

    def test_sample_size_is_20(self):
        assert SAMPLE_SIZE == 20

    def test_avg_tpi(self):
        stats = _tpi_stats(_reading_rows(READINGS), None)
        assert stats["avg_tpi"] == pytest.approx(5.025, abs=0.01)

    def test_std_dev_is_sample_stdev(self):
        stats = _tpi_stats(_reading_rows(READINGS), None)
        assert stats["std_dev"] == pytest.approx(statistics.stdev(READINGS), abs=0.01)
        assert stats["std_dev"] == pytest.approx(0.250, abs=0.01)

    def test_cv_pct(self):
        """cv% = std_dev / avg_tpi * 100 ~ 4.98."""
        stats = _tpi_stats(_reading_rows(READINGS), None)
        expected = statistics.stdev(READINGS) / (sum(READINGS) / len(READINGS)) * 100
        assert stats["cv_pct"] == pytest.approx(expected, abs=0.01)
        assert stats["cv_pct"] == pytest.approx(4.98, abs=0.01)

    def test_min_max(self):
        stats = _tpi_stats(_reading_rows(READINGS), None)
        assert stats["min_tpi"] == 4.7
        assert stats["max_tpi"] == 5.3

    def test_n_counts_non_null_only(self):
        """Null cells are excluded from n / avg / stdev."""
        stats = _tpi_stats(_reading_rows(READINGS + [None, None]), None)
        assert stats["n"] == 4
        assert stats["avg_tpi"] == pytest.approx(5.025, abs=0.01)

    def test_std_tpi_echo_and_diff(self):
        """std_tpi snapshot echoed; tpi_diff = avg_tpi - std_tpi."""
        stats = _tpi_stats(_reading_rows(READINGS), 5.0)
        assert stats["std_tpi"] == pytest.approx(5.0, abs=0.001)
        assert stats["tpi_diff"] == pytest.approx(5.025 - 5.0, abs=0.01)

    def test_all_null_yields_none_stats(self):
        stats = _tpi_stats(_reading_rows([None, None, None]), None)
        assert stats["n"] == 0
        assert stats["avg_tpi"] is None
        assert stats["std_dev"] is None
        assert stats["cv_pct"] is None
        assert stats["min_tpi"] is None
        assert stats["max_tpi"] is None

    def test_single_reading_std_is_zero(self):
        stats = _tpi_stats(_reading_rows([5.0]), None)
        assert stats["n"] == 1
        assert stats["std_dev"] == 0.0
        assert stats["cv_pct"] == 0.0


# ===========================================================================
# ENDPOINT — dependency_overrides
# ===========================================================================
class TestYarnTpiEndpoints:
    """Endpoint tests with mocked tenant DB + auth via dependency_overrides."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # -- setup --------------------------------------------------------------
    def test_setup_success(self):
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
        yarn_row = _mock_row(
            {
                "item_id": 10,
                "item_code": "Y10",
                "item_name": "YARN 10",
                "std_count": 8.0,
                "std_mr_pct": 20.0,
            }
        )
        # execute order in setup: machines.fetchall, yarn_items.fetchall,
        # then _tpi_groups -> headers.fetchall (empty -> no dtl round-trip).
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [machine_row],
            [yarn_row],
            [],
        ]

        response = client.get(
            "/api/juteSQC/yarn_tpi_setup?co_id=1&branch_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data) == {"machines", "yarn_items", "groups"}
        assert data["machines"][0]["machine_name"] == "CARD 4"
        assert data["yarn_items"][0]["item_id"] == 10
        assert data["groups"] == []

    def test_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/yarn_tpi_setup?branch_id=1&entry_date=2026-01-05")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_setup_missing_entry_date(self):
        response = client.get("/api/juteSQC/yarn_tpi_setup?co_id=1&branch_id=1")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    # -- save negatives -----------------------------------------------------
    def test_save_missing_branch_id_400(self):
        response = client.post(
            "/api/juteSQC/yarn_tpi_save",
            json={
                "co_id": 1,
                "entry_date": "2026-01-05",
                "entries": [
                    {"mc_id": 4, "item_id": 10, "readings": [5.0] * SAMPLE_SIZE}
                ],
            },
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_save_missing_item_id_422(self):
        """item_id is a required Pydantic field -> rejected at validation (422), not 400.

        ponytail: spec asked for 400, but the module makes item_id a non-optional int, so
        the request never reaches the handler. 422 is the real, correct behaviour."""
        response = client.post(
            "/api/juteSQC/yarn_tpi_save",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "entries": [{"mc_id": 4, "readings": [5.0] * SAMPLE_SIZE}],
            },
        )
        assert response.status_code == 422
        # The validation error names the missing item_id field.
        assert "item_id" in str(response.json()).lower()

    def test_save_wrong_readings_count_400(self):
        response = client.post(
            "/api/juteSQC/yarn_tpi_save",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "entries": [{"mc_id": 4, "item_id": 10, "readings": [5.0] * 5}],
            },
        )
        assert response.status_code == 400
        assert "20" in response.json()["detail"]

    # -- save success -------------------------------------------------------
    def test_save_success_snapshot_persisted(self):
        """One save inserts a header (lastrowid) + 20 detail rows; the header snapshot
        (std_tpi / tp_value / count_lbs / item_id / updated_by) is persisted from the body."""
        result = MagicMock()
        result.lastrowid = 101
        self._mock_session.execute.return_value = result

        response = client.post(
            "/api/juteSQC/yarn_tpi_save",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "entries": [
                    {
                        "mc_id": 4,
                        "item_id": 10,
                        "count_lbs": 8.0,
                        "std_tpi": 5.0,
                        "tp_value": 1.0,
                        "prepared_by": "QA",
                        "readings": READINGS + [None] * 16,
                    }
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["saved"] == 1
        assert body["ids"] == [101]
        self._mock_session.commit.assert_called_once()

        # 1 header insert + 20 detail inserts.
        assert self._mock_session.execute.call_count == 1 + SAMPLE_SIZE

        # First execute = header insert; inspect its bind dict for the snapshot.
        hdr_binds = self._mock_session.execute.call_args_list[0][0][1]
        assert hdr_binds["std_tpi"] == 5.0
        assert hdr_binds["tp_value"] == 1.0
        assert hdr_binds["count_lbs"] == 8.0
        assert hdr_binds["item_id"] == 10
        assert hdr_binds["updated_by"] == 7

    def test_save_multi_entry_success(self):
        """Two studies in one save -> 2 ids, 2 headers + 40 details."""
        # Each entry = 1 header insert + 20 detail inserts; only header inserts
        # advance the id. Detect a header insert by its bind dict (carries item_id).
        next_id = {"v": 100}

        def _execute(*args, **_kwargs):
            res = MagicMock()
            params = args[1] if len(args) > 1 else {}
            if isinstance(params, dict) and "item_id" in params:
                next_id["v"] += 1
                res.lastrowid = next_id["v"]
            else:
                res.lastrowid = None
            return res

        self._mock_session.execute.side_effect = _execute

        response = client.post(
            "/api/juteSQC/yarn_tpi_save",
            json={
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "entries": [
                    {"mc_id": 4, "item_id": 10, "readings": READINGS + [None] * 16},
                    {"mc_id": 5, "item_id": 11, "readings": [5.2] * SAMPLE_SIZE},
                ],
            },
        )

        assert response.status_code == 200
        body = response.json()["data"]
        assert body["saved"] == 2
        assert body["ids"] == [101, 102]
        # 2 headers + 2*20 details.
        assert self._mock_session.execute.call_count == 2 * (1 + SAMPLE_SIZE)

    # -- by_date ------------------------------------------------------------
    def test_by_date_object_envelope_with_stats(self):
        """Regression guard: by-date returns {"data": {"groups": [...]}} and each group
        carries server-computed stats."""
        hdr = _mock_row(
            {
                "yarn_tpi_id": 101,
                "co_id": 1,
                "branch_id": 1,
                "entry_date": "2026-01-05",
                "mc_id": 4,
                "mech_code": "C4",
                "machine_name": "CARD 4",
                "item_id": 10,
                "item_code": "Y10",
                "item_name": "YARN 10",
                "count_lbs": 8.0,
                "std_tpi": 5.0,
                "tp_value": 1.0,
                "prepared_by": "QA",
            }
        )
        dtls = [
            _mock_row({"yarn_tpi_id": 101, "reading_no": i + 1, "reading_val": v})
            for i, v in enumerate(READINGS + [None] * 16)
        ]
        # _tpi_groups execute order: headers.fetchall, then dtl.fetchall.
        self._mock_session.execute.return_value.fetchall.side_effect = [[hdr], dtls]

        response = client.get(
            "/api/juteSQC/yarn_tpi_by_date?co_id=1&branch_id=1&entry_date=2026-01-05"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        # OBJECT envelope, not a bare list.
        assert isinstance(data, dict)
        assert "groups" in data

        groups = data["groups"]
        assert len(groups) == 1
        g = groups[0]
        assert g["yarn_tpi_id"] == 101
        assert g["item_id"] == 10
        assert g["std_tpi"] == pytest.approx(5.0, abs=0.001)

        stats = g["stats"]
        assert stats["avg_tpi"] == pytest.approx(5.025, abs=0.01)
        assert stats["std_dev"] == pytest.approx(0.250, abs=0.01)
        assert stats["cv_pct"] == pytest.approx(4.98, abs=0.01)
        assert stats["min_tpi"] == 4.7
        assert stats["max_tpi"] == 5.3
        assert stats["n"] == 4

    def test_by_date_missing_co_id_400(self):
        response = client.get("/api/juteSQC/yarn_tpi_by_date?entry_date=2026-01-05")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # -- delete -------------------------------------------------------------
    def test_delete_when_absent_404(self):
        # No active header found -> 404 before any soft-delete UPDATE.
        self._mock_session.execute.return_value.fetchone.return_value = None

        response = client.delete("/api/juteSQC/yarn_tpi_delete/99999")

        assert response.status_code == 404
