"""
Tests for R-08-28 Fabric Fault SQC endpoints.
Tests for src/juteSQC/fabric_fault.py
"""

import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import FABRIC_FAULT_TYPES, FABRIC_FAULT_COUNT

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


def _zeros():
    return [0] * FABRIC_FAULT_COUNT


# Index of each fault in the FIXED order (lock the example to named faults, not positions).
MINOR_GAW = FABRIC_FAULT_TYPES.index("Minor Gaw")        # 1
MINOR_FLOAT = FABRIC_FAULT_TYPES.index("Minor Float")    # 5
MAJOR_FLOAT = FABRIC_FAULT_TYPES.index("Major Float")    # 6


# ---------------------------------------------------------------------------
# Math lock — the VERIFIED example. A piece {Minor Gaw 13, Major Float 1, Minor
# Float 3, rest 0} totals 17. A 16-piece day with the Minor Gaw row
# [3,13,5,5,4,7,8,4,11,3,9,3,3,8,3,4] -> fault_total 93, fault_score 93/16 = 5.8125;
# grand_total 118, grand_score 118/16 = 7.375. Locks counting/scoring exactly.
# ---------------------------------------------------------------------------
def test_piece_total_math_lock():
    counts = _zeros()
    counts[MINOR_GAW] = 13
    counts[MAJOR_FLOAT] = 1
    counts[MINOR_FLOAT] = 3
    assert sum(counts) == 17


def test_constants_lock():
    assert FABRIC_FAULT_COUNT == 15
    assert len(FABRIC_FAULT_TYPES) == 15
    assert FABRIC_FAULT_TYPES[0] == "Single Broken Warp"
    assert FABRIC_FAULT_TYPES[1] == "Minor Gaw"
    assert FABRIC_FAULT_TYPES[14] == "Smash"


class TestFabricFaultEndpoints:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ------------------------------------------------------------------ setup
    def test_create_setup_success(self):
        # create_setup runs three execute().fetchall() calls (cloth, looms, spells) in order.
        cloth_row = _mock_row(
            {"item_id": 10, "item_code": "C1", "item_name": "Hessian Cloth"}
        )
        loom_row = _mock_row(
            {"machine_id": 23, "machine_name": "LOOM 1", "mech_code": "L1"}
        )
        spell_row = _mock_row({"spell_id": 2, "spell_code": "A"})
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [cloth_row],
            [loom_row],
            [spell_row],
        ]

        response = client.get(
            "/api/juteSQC/fabric_fault_create_setup?co_id=1&branch_id=2"
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["fault_types"]) == 15
        assert data["fault_types"][1] == "Minor Gaw"
        assert data["qualities"][0]["item_name"] == "Hessian Cloth"
        assert data["looms"][0]["machine_id"] == 23
        assert data["spells"][0]["spell_code"] == "A"

    def test_create_setup_dedup(self):
        cloth_row = _mock_row({"item_id": 10, "item_code": "C1", "item_name": "Cloth"})
        loom_dup = _mock_row(
            {"machine_id": 23, "machine_name": "LOOM 1", "mech_code": "L1"}
        )
        spell_dup = _mock_row({"spell_id": 2, "spell_code": "A"})
        self._mock_session.execute.return_value.fetchall.side_effect = [
            [cloth_row],
            [loom_dup, loom_dup],   # duplicate loom rows -> de-dup to 1
            [spell_dup, spell_dup],  # duplicate spell_code -> de-dup to 1
        ]
        response = client.get(
            "/api/juteSQC/fabric_fault_create_setup?co_id=1&branch_id=2"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert len(data["looms"]) == 1
        assert len(data["spells"]) == 1

    def test_create_setup_missing_co_id(self):
        response = client.get("/api/juteSQC/fabric_fault_create_setup?branch_id=2")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- create
    def test_create_success(self):
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "fabric_fault_id", 7)
        )
        counts = _zeros()
        counts[MINOR_GAW] = 13
        counts[MAJOR_FLOAT] = 1
        counts[MINOR_FLOAT] = 3  # piece_total = 17

        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={
                "co_id": 1,
                "branch_id": 2,
                "entry_date": "2026-06-28",
                "spell_id": 2,
                "item_id": 10,
                "loom_id": 23,
                "date_of_weaving": "2026-06-27",
                "fault_counts": counts,
                "remarks": "edge",
                "inspector_name": "QC John",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Fabric Fault QC log created successfully"
        assert body["fabric_fault_id"] == 7
        self._mock_session.add.assert_called_once()
        self._mock_session.commit.assert_called_once()
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_piece_total == 17
        assert json.loads(record.fault_counts) == counts
        assert record.inspector_name == "QC John"

    def test_create_all_zeros_allowed(self):
        # A clean piece (all faults 0) is valid — counts default to 0, validate >= 0 NOT > 0.
        self._mock_session.refresh = MagicMock(
            side_effect=lambda r: setattr(r, "fabric_fault_id", 8)
        )
        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "fault_counts": _zeros(),
            },
        )
        assert response.status_code == 200
        record = self._mock_session.add.call_args[0][0]
        assert record.calc_piece_total == 0

    def test_create_missing_co_id(self):
        # co_id is a required body field -> 422 from pydantic (not a 400 guard)
        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={"entry_date": "2026-06-28", "fault_counts": _zeros()},
        )
        assert response.status_code == 422

    def test_create_wrong_count_length(self):
        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "fault_counts": [0, 0, 0],  # only 3, not 15
            },
        )
        assert response.status_code == 400
        assert "15" in response.json()["detail"]

    def test_create_negative_count(self):
        counts = _zeros()
        counts[MINOR_GAW] = -1
        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={
                "co_id": 1,
                "entry_date": "2026-06-28",
                "fault_counts": counts,
            },
        )
        assert response.status_code == 400
        assert ">= 0" in response.json()["detail"]

    @pytest.mark.parametrize("bad", [True, 2.5, "5"])
    def test_create_non_integer_count_rejected(self, bad):
        # Regression: StrictInt rejects bool/float/numeric-string counts at the schema
        # boundary (422). Pre-fix, json `true`/`"5"` were coerced to int and slipped
        # past the router guard, persisting a bogus count.
        counts = _zeros()
        counts[MINOR_GAW] = bad
        response = client.post(
            "/api/juteSQC/create_fabric_fault",
            json={"co_id": 1, "entry_date": "2026-06-28", "fault_counts": counts},
        )
        assert response.status_code == 422
        self._mock_session.add.assert_not_called()

    # ---------------------------------------------------------------- by_date
    def test_by_date_rollup_math_lock(self):
        # 16 pieces. Minor Gaw counts come from the verified row
        # [3,13,5,5,4,7,8,4,11,3,9,3,3,8,3,4] (fault_total 93). The piece with Minor
        # Gaw=13 also carries Major Float=1 and Minor Float=3 (the verified example, piece
        # total 17). The grand total must be 118: Minor Gaw column 93 + that piece's
        # extra 1+3=4 + 21 more parked on one piece's Major Gaw -> 118 -> 118/16 = 7.375.
        minor_gaw_row = [3, 13, 5, 5, 4, 7, 8, 4, 11, 3, 9, 3, 3, 8, 3, 4]
        extra_major_gaw = 118 - sum(minor_gaw_row) - 4  # = 21
        MAJOR_GAW = FABRIC_FAULT_TYPES.index("Major Gaw")

        rows = []
        for i, gaw in enumerate(minor_gaw_row):
            counts = _zeros()
            counts[MINOR_GAW] = gaw
            if gaw == 13:  # the verified example piece
                counts[MAJOR_FLOAT] = 1
                counts[MINOR_FLOAT] = 3
            if i == 0:  # park all the remaining grand-total mass on one piece's Major Gaw
                counts[MAJOR_GAW] = extra_major_gaw
            rows.append(
                _mock_row(
                    {
                        "fabric_fault_id": i + 1,
                        "spell_id": 2,
                        "spell_code": "A",
                        "item_id": 10,
                        "item_name": "Hessian Cloth",
                        "loom_id": 23,
                        "loom_name": "LOOM 1",
                        "mech_code": "L1",
                        "date_of_weaving": "2026-06-27",
                        "remarks": None,
                        "inspector_name": "QC",
                        "fault_counts": json.dumps(counts),
                        "calc_piece_total": sum(counts),
                    }
                )
            )
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/juteSQC/get_fabric_fault_by_date?co_id=1&branch_id=2&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["pieces_inspected"] == 16
        assert len(data["pieces"]) == 16
        assert len(data["fault_types"]) == 15
        # Minor Gaw row: fault_total 93, fault_score 93/16 = 5.8125
        assert data["fault_totals"][MINOR_GAW] == 93
        assert data["fault_scores"][MINOR_GAW] == 5.8125
        # grand: total 118, score 118/16 = 7.375
        assert data["grand_total"] == 118
        assert data["grand_score"] == 7.375
        # the verified example piece still totals 17
        example = next(p for p in data["pieces"] if p["fault_counts"][MINOR_GAW] == 13)
        assert example["piece_total"] == 17

    def test_by_date_empty(self):
        # No pieces -> guard N > 0: scores null, totals zeroed, grand null.
        self._mock_session.execute.return_value.fetchall.return_value = []
        response = client.get(
            "/api/juteSQC/get_fabric_fault_by_date?co_id=1&entry_date=2026-06-28"
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["pieces_inspected"] == 0
        assert data["grand_score"] is None
        assert all(s is None for s in data["fault_scores"])
        assert data["grand_total"] == 0

    def test_by_date_missing_entry_date(self):
        response = client.get("/api/juteSQC/get_fabric_fault_by_date?co_id=1&branch_id=2")
        assert response.status_code == 400
        assert "entry_date" in response.json()["detail"].lower()

    def test_by_date_missing_co_id(self):
        response = client.get(
            "/api/juteSQC/get_fabric_fault_by_date?entry_date=2026-06-28"
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ------------------------------------------------------------------ table
    def test_table_success(self):
        count_row = MagicMock()
        count_row.total = 1
        data_row = _mock_row(
            {
                "fabric_fault_id": 1,
                "entry_date": "2026-06-28",
                "branch_id": 2,
                "item_id": 10,
                "item_name": "Hessian Cloth",
                "loom_id": 23,
                "loom_name": "LOOM 1",
                "spell_code": "A",
                "piece_total": 17,
                "updated_date_time": "2026-06-28 10:00:00",
            }
        )
        self._mock_session.execute.return_value.fetchone.return_value = count_row
        self._mock_session.execute.return_value.fetchall.return_value = [data_row]

        response = client.get(
            "/api/juteSQC/get_fabric_fault_table?co_id=1&page=1&limit=10"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["page_size"] == 10
        assert len(body["data"]) == 1
        row = body["data"][0]
        assert row["piece_total"] == 17
        assert row["loom_name"] == "LOOM 1"

    def test_table_missing_co_id(self):
        response = client.get("/api/juteSQC/get_fabric_fault_table")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ----------------------------------------------------------------- delete
    def test_delete_success(self):
        existing = MagicMock()
        existing._mapping = {"fabric_fault_id": 1, "co_id": 1, "active": 1}
        self._mock_session.execute.return_value.fetchone.return_value = existing

        response = client.post(
            "/api/juteSQC/delete_fabric_fault",
            json={"fabric_fault_id": 1, "co_id": 1},
        )
        assert response.status_code == 200
        assert "deleted" in response.json()["message"].lower()
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self):
        self._mock_session.execute.return_value.fetchone.return_value = None
        response = client.post(
            "/api/juteSQC/delete_fabric_fault",
            json={"fabric_fault_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
