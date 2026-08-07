"""
Tests for the cost_basis_qty additions in src/bomcosting/bomCosting.py
(AMCL enquiry flow design, section 5.2 + 6 touch-points):

- bom_cost_rollup: cost_per_unit = total_cost / item_bom_hdr_mst.cost_basis_qty,
  with 0 / None basis guarded as 1.
- bom_costing_create / bom_costing_update: persist cost_basis_qty (validated > 0).
- snapshot_approve: flips bom_cost_snapshot.status to 'approved'; 404 when missing.

House pattern: TestClient(app) + app.dependency_overrides for get_tenant_db /
get_current_user_with_refresh, MagicMock sessions with _mapping rows
(same as the neighboring src/test/test_bomcosting.py).
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


def _element_row(cost_element_id, element_type, amount_source=None, **overrides):
    base = {
        "cost_element_id": cost_element_id,
        "element_code": f"EL{cost_element_id}",
        "element_name": f"Element {cost_element_id}",
        "element_type": element_type,
        "element_level": 0,
        "parent_element_id": None,
        "is_leaf": 1,
        "sort_order": cost_element_id * 100,
    }
    base.update(overrides)
    return _mock_row(base)


# ═══════════════════════════════════════════════════════════════
# ROLLUP: cost_per_unit = total_cost / cost_basis_qty
# ═══════════════════════════════════════════════════════════════


class TestRollupCostBasis:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _setup_rollup_session(self, cost_basis_qty, entry_amount=100.0):
        """Wire the mock session for one bom_cost_rollup call.

        Header: single BomHdr with the given cost_basis_qty (returned both by
        the endpoint's existence check and compute_full_rollup's reload).
        Tree: one root material leaf element with one active entry of
        entry_amount → total_cost == entry_amount.
        execute() call order inside compute_full_rollup:
          1. cost element tree (fetchall)
          2. active cost entries (fetchall)
          3. mark previous snapshots superseded (result unused)
        """
        hdr = MagicMock()
        hdr.cost_basis_qty = cost_basis_qty
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = hdr

        tree_result = MagicMock()
        tree_result.fetchall.return_value = [_element_row(1, "material")]
        entries_result = MagicMock()
        entries_result.fetchall.return_value = [
            _mock_row({"cost_element_id": 1, "amount": entry_amount, "source": "manual"})
        ]
        self._mock_session.execute.side_effect = [
            tree_result,
            entries_result,
            MagicMock(),  # mark_previous_snapshots_superseded
        ]
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: setattr(obj, "bom_cost_snapshot_id", 77)
        )
        return hdr

    def test_rollup_divides_total_by_cost_basis_qty(self):
        self._setup_rollup_session(cost_basis_qty=4, entry_amount=100.0)

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        snapshot = response.json()["snapshot"]
        assert snapshot["total_cost"] == 100.0
        assert snapshot["cost_basis_qty"] == 4.0
        assert snapshot["cost_per_unit"] == 25.0

        # The persisted BomCostSnapshot carries the divided per-unit cost
        added_snapshot = self._mock_session.add.call_args[0][0]
        assert added_snapshot.cost_per_unit == 25.0
        assert added_snapshot.total_cost == 100.0
        assert added_snapshot.status == "draft"

    def test_rollup_fractional_cost_basis_qty(self):
        self._setup_rollup_session(cost_basis_qty=2.5, entry_amount=100.0)

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        snapshot = response.json()["snapshot"]
        assert snapshot["cost_basis_qty"] == 2.5
        assert snapshot["cost_per_unit"] == 40.0

    def test_rollup_zero_cost_basis_treated_as_one(self):
        self._setup_rollup_session(cost_basis_qty=0, entry_amount=100.0)

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        snapshot = response.json()["snapshot"]
        assert snapshot["cost_basis_qty"] == 1.0
        assert snapshot["cost_per_unit"] == 100.0

    def test_rollup_none_cost_basis_treated_as_one(self):
        self._setup_rollup_session(cost_basis_qty=None, entry_amount=100.0)

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        snapshot = response.json()["snapshot"]
        assert snapshot["cost_basis_qty"] == 1.0
        assert snapshot["cost_per_unit"] == 100.0

    def test_rollup_negative_cost_basis_treated_as_one(self):
        self._setup_rollup_session(cost_basis_qty=-5, entry_amount=100.0)

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1, "co_id": 1}
        )
        assert response.status_code == 200
        assert response.json()["snapshot"]["cost_per_unit"] == 100.0

    def test_rollup_missing_bom_hdr_id_400(self):
        response = client.post("/api/bomCosting/bom_cost_rollup", json={"co_id": 1})
        assert response.status_code == 400
        assert "bom_hdr_id" in response.json()["detail"].lower()

    def test_rollup_missing_co_id_400(self):
        response = client.post("/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 1})
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_rollup_header_not_found_404(self):
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = client.post(
            "/api/bomCosting/bom_cost_rollup", json={"bom_hdr_id": 999, "co_id": 1}
        )
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════
# CREATE: cost_basis_qty persisted on item_bom_hdr_mst
# ═══════════════════════════════════════════════════════════════


class TestCreatePersistsCostBasis:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _setup_create_session(self):
        self._mock_session.execute.return_value.fetchone.return_value = _mock_row(
            {"next_version": 1}
        )
        self._mock_session.refresh = MagicMock(
            side_effect=lambda obj: (
                setattr(obj, "bom_hdr_id", 42),
                setattr(obj, "bom_version", 1),
            )
        )

    def test_create_persists_cost_basis_qty(self):
        self._setup_create_session()

        response = client.post(
            "/api/bomCosting/bom_costing_create",
            json={"item_id": 10, "co_id": 1, "cost_basis_qty": 4},
        )
        assert response.status_code == 201

        added_hdr = self._mock_session.add.call_args[0][0]
        assert added_hdr.cost_basis_qty == 4.0

    def test_create_defaults_cost_basis_qty_to_one_when_omitted(self):
        self._setup_create_session()

        response = client.post(
            "/api/bomCosting/bom_costing_create", json={"item_id": 10, "co_id": 1}
        )
        assert response.status_code == 201

        added_hdr = self._mock_session.add.call_args[0][0]
        assert added_hdr.cost_basis_qty == 1.0

    def test_create_invalid_cost_basis_qty_format_400(self):
        response = client.post(
            "/api/bomCosting/bom_costing_create",
            json={"item_id": 10, "co_id": 1, "cost_basis_qty": "abc"},
        )
        assert response.status_code == 400
        assert "cost_basis_qty" in response.json()["detail"].lower()

    def test_create_zero_cost_basis_qty_400(self):
        response = client.post(
            "/api/bomCosting/bom_costing_create",
            json={"item_id": 10, "co_id": 1, "cost_basis_qty": 0},
        )
        assert response.status_code == 400
        assert "cost_basis_qty" in response.json()["detail"].lower()

    def test_create_missing_item_id_400(self):
        response = client.post(
            "/api/bomCosting/bom_costing_create", json={"co_id": 1, "cost_basis_qty": 4}
        )
        assert response.status_code == 400


# ═══════════════════════════════════════════════════════════════
# UPDATE: cost_basis_qty persisted on item_bom_hdr_mst
# ═══════════════════════════════════════════════════════════════


class TestUpdatePersistsCostBasis:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _setup_header(self, cost_basis_qty=1.0):
        hdr = MagicMock()
        hdr.cost_basis_qty = cost_basis_qty
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = hdr
        return hdr

    def test_update_persists_cost_basis_qty(self):
        hdr = self._setup_header()

        response = client.post(
            "/api/bomCosting/bom_costing_update",
            json={"bom_hdr_id": 1, "co_id": 1, "cost_basis_qty": 2.5},
        )
        assert response.status_code == 200
        assert hdr.cost_basis_qty == 2.5
        self._mock_session.commit.assert_called_once()

    def test_update_leaves_cost_basis_qty_untouched_when_absent(self):
        hdr = self._setup_header(cost_basis_qty=7.0)

        response = client.post(
            "/api/bomCosting/bom_costing_update",
            json={"bom_hdr_id": 1, "co_id": 1, "remarks": "no basis change"},
        )
        assert response.status_code == 200
        assert hdr.cost_basis_qty == 7.0

    def test_update_invalid_cost_basis_qty_format_400(self):
        self._setup_header()

        response = client.post(
            "/api/bomCosting/bom_costing_update",
            json={"bom_hdr_id": 1, "co_id": 1, "cost_basis_qty": "xyz"},
        )
        assert response.status_code == 400
        assert "cost_basis_qty" in response.json()["detail"].lower()

    def test_update_negative_cost_basis_qty_400(self):
        self._setup_header()

        response = client.post(
            "/api/bomCosting/bom_costing_update",
            json={"bom_hdr_id": 1, "co_id": 1, "cost_basis_qty": -3},
        )
        assert response.status_code == 400
        assert "cost_basis_qty" in response.json()["detail"].lower()

    def test_update_missing_params_400(self):
        response = client.post(
            "/api/bomCosting/bom_costing_update", json={"cost_basis_qty": 2}
        )
        assert response.status_code == 400

    def test_update_header_not_found_404(self):
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = client.post(
            "/api/bomCosting/bom_costing_update",
            json={"bom_hdr_id": 999, "co_id": 1, "cost_basis_qty": 2},
        )
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════════
# SNAPSHOT APPROVE
# ═══════════════════════════════════════════════════════════════


class TestSnapshotApprove:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    def _setup_snapshot(self):
        snap = MagicMock()
        snap.bom_cost_snapshot_id = 9
        snap.status = "draft"
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = snap
        return snap

    def test_approve_by_snapshot_id_sets_status_approved(self):
        snap = self._setup_snapshot()

        response = client.post(
            "/api/bomCosting/snapshot_approve",
            json={"bom_cost_snapshot_id": 9, "co_id": 1},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["bom_cost_snapshot_id"] == 9
        assert snap.status == "approved"
        assert snap.updated_by == 1
        self._mock_session.commit.assert_called_once()

        # Looked up by explicit snapshot id
        filter_kwargs = self._mock_session.query.return_value.filter_by.call_args.kwargs
        assert filter_kwargs["bom_cost_snapshot_id"] == 9
        assert filter_kwargs["co_id"] == 1

    def test_approve_by_bom_hdr_id_targets_current_snapshot(self):
        snap = self._setup_snapshot()

        response = client.post(
            "/api/bomCosting/snapshot_approve", json={"bom_hdr_id": 5, "co_id": 1}
        )
        assert response.status_code == 200
        assert snap.status == "approved"

        # Looked up as the header's current active snapshot
        filter_kwargs = self._mock_session.query.return_value.filter_by.call_args.kwargs
        assert filter_kwargs["bom_hdr_id"] == 5
        assert filter_kwargs["is_current"] == 1

    def test_approve_missing_co_id_400(self):
        response = client.post(
            "/api/bomCosting/snapshot_approve", json={"bom_cost_snapshot_id": 9}
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    def test_approve_missing_both_ids_400(self):
        response = client.post("/api/bomCosting/snapshot_approve", json={"co_id": 1})
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "bom_cost_snapshot_id" in detail
        assert "bom_hdr_id" in detail

    def test_approve_snapshot_not_found_404(self):
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = client.post(
            "/api/bomCosting/snapshot_approve",
            json={"bom_cost_snapshot_id": 999, "co_id": 1},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_approve_not_found_does_not_commit(self):
        self._mock_session.query.return_value.filter_by.return_value.first.return_value = None

        response = client.post(
            "/api/bomCosting/snapshot_approve", json={"bom_hdr_id": 999, "co_id": 1}
        )
        assert response.status_code == 404
        self._mock_session.commit.assert_not_called()
