"""
Tests for Jute PO percentage-based line entry.

The UI now sends `percentage` per line item (summing to 100%). The backend
derives `quantity` and `weight` server-side so downstream consumers that
read `quantity` (e.g. gate entry) keep working unchanged. Legacy payloads
without `percentage` fall through to the old quantity-based path.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.jutePO import (
    derive_from_percentage,
    validate_percentage_sum,
    JutePOLineItemCreate,
    WEIGHT_PER_BALE_KG,
    WEIGHT_PER_LOOSE_KG,
)


client = TestClient(app)


# =============================================================================
# Unit tests for helpers
# =============================================================================


class TestDeriveFromPercentage:
    def test_50_percent_bale(self):
        # vehicle 100 qtl x 2 qty x 100 = 20000 kg. 50% = 10000 kg = 10000/150 bales = 66.66 -> 67
        weight_kg, qty = derive_from_percentage(50.0, 100.0, 2, "BALE")
        assert weight_kg == pytest.approx(10000.0)
        assert qty == pytest.approx(round(10000.0 / WEIGHT_PER_BALE_KG))

    def test_30_percent_bale(self):
        # 30% of 20000 kg = 6000 kg = 40 bales (already whole)
        weight_kg, qty = derive_from_percentage(30.0, 100.0, 2, "BALE")
        assert weight_kg == pytest.approx(6000.0)
        assert qty == pytest.approx(round(6000.0 / WEIGHT_PER_BALE_KG))

    def test_loose_unit(self):
        # 10000 kg / 48 = 208.33 -> 208
        weight_kg, qty = derive_from_percentage(50.0, 100.0, 2, "LOOSE")
        assert weight_kg == pytest.approx(10000.0)
        assert qty == pytest.approx(round(10000.0 / WEIGHT_PER_LOOSE_KG))

    def test_quantity_is_rounded_to_whole_number(self):
        # Any derived bales/drums must be a whole number (integer-valued float)
        weight_kg, qty = derive_from_percentage(33.33, 100.0, 2, "BALE")
        assert qty == float(int(qty))
        weight_kg, qty = derive_from_percentage(66.67, 100.0, 2, "LOOSE")
        assert qty == float(int(qty))

    def test_full_percentage_matches_vehicle_capacity(self):
        weight_kg, _ = derive_from_percentage(100.0, 100.0, 2, "BALE")
        # 100% should equal full vehicle capacity in kg
        assert weight_kg == pytest.approx(100.0 * 2 * 100)


class TestValidatePercentageSum:
    def test_valid_sum_100_passes(self):
        items = [
            JutePOLineItemCreate(percentage=50.0, rate=10000),
            JutePOLineItemCreate(percentage=30.0, rate=10000),
            JutePOLineItemCreate(percentage=20.0, rate=10000),
        ]
        # Should not raise
        validate_percentage_sum(items)

    def test_sum_mismatch_raises_400(self):
        items = [
            JutePOLineItemCreate(percentage=50.0, rate=10000),
            JutePOLineItemCreate(percentage=30.0, rate=10000),
            JutePOLineItemCreate(percentage=15.0, rate=10000),
        ]
        with pytest.raises(HTTPException) as exc:
            validate_percentage_sum(items)
        assert exc.value.status_code == 400
        assert "sum to 100" in exc.value.detail.lower()

    def test_missing_percentage_raises_400(self):
        items = [
            JutePOLineItemCreate(percentage=50.0, rate=10000),
            JutePOLineItemCreate(quantity=10, rate=10000),  # no percentage
        ]
        with pytest.raises(HTTPException) as exc:
            validate_percentage_sum(items)
        assert exc.value.status_code == 400
        assert "percentage" in exc.value.detail.lower()

    def test_epsilon_tolerance(self):
        # 100 ± 0.01 should pass (floating point slop)
        items = [
            JutePOLineItemCreate(percentage=33.33, rate=10000),
            JutePOLineItemCreate(percentage=33.33, rate=10000),
            JutePOLineItemCreate(percentage=33.34, rate=10000),
        ]
        # Should not raise (sum = 100.00 exactly or within 0.01)
        validate_percentage_sum(items)


# =============================================================================
# Endpoint tests (via TestClient with mocked DB)
# =============================================================================


def _make_mock_session_for_create(vehicle_weight_qtl: float = 100.0):
    """
    Build a MagicMock session that simulates the DB calls made during
    jute_po_create. Returns the session along with a holder for captured
    `db.add` calls so tests can assert on JutePoLi rows.
    """
    session = MagicMock()
    added_objects = []
    session.add.side_effect = lambda obj: added_objects.append(obj)

    # Branch check: returns row with matching co_id
    branch_row = MagicMock()
    branch_row.co_id = 1

    # Supplier/party mapping check: returns a truthy row
    supplier_row = (1,)

    # Vehicle weight lookup
    vehicle_row = MagicMock()
    vehicle_row.weight = vehicle_weight_qtl

    # Max PO number
    max_po_row = MagicMock()
    max_po_row.next_po = 1

    # Prefix lookup for formatted PO number
    prefix_row = MagicMock()
    prefix_row.co_prefix = "CO"
    prefix_row.branch_prefix = "BR"

    fetchone_returns = [
        branch_row,    # _validate_branch_belongs_to_co
        supplier_row,  # _validate_supplier_party_for_co
        vehicle_row,   # vehicle weight lookup
        max_po_row,    # max po_no
        prefix_row,    # format prefix
    ]
    session.execute.return_value.fetchone.side_effect = fetchone_returns

    # flush simulates setting jute_po_id on the JutePo after add()
    def _flush_side_effect():
        if added_objects:
            first = added_objects[0]
            if not hasattr(first, "jute_po_id") or first.jute_po_id is None:
                first.jute_po_id = 12345
    session.flush.side_effect = _flush_side_effect

    return session, added_objects


def _make_mock_session_for_update(
    existing_status_id: int = 21,
    existing_branch_id: int = 2,
    existing_vehicle_quantity: int = 2,
    vehicle_weight_qtl: float = 100.0,
):
    """
    Build a MagicMock session for jute_po_update. The real handler uses
    db.query(JutePo).filter(...).first() to fetch the existing PO; we
    mock that chain to return a stand-in object we can inspect.
    """
    session = MagicMock()
    added_objects = []
    session.add.side_effect = lambda obj: added_objects.append(obj)

    # Existing PO stand-in
    existing_po = MagicMock()
    existing_po.jute_po_id = 12345
    existing_po.status_id = existing_status_id
    existing_po.branch_id = existing_branch_id
    existing_po.supplier_id = 857
    existing_po.party_id = None
    existing_po.vehicle_type_id = 1
    existing_po.vehicle_quantity = existing_vehicle_quantity
    existing_po.jute_uom = "BALE"

    # Chain: db.query(JutePo).filter(...).first()
    session.query.return_value.filter.return_value.first.return_value = existing_po

    # For the delete-existing-line-items step: db.query(JutePoLi).filter(...).delete()
    # MagicMock already handles this chain transparently; the .delete() returns MagicMock.

    # Valid branches for co: returns list of rows each with branch_id
    branch_rows = [MagicMock(branch_id=existing_branch_id)]

    # Branch co-check row
    branch_check_row = MagicMock()
    branch_check_row.co_id = 1

    # Supplier row
    supplier_row = (1,)

    # Vehicle weight row
    vehicle_row = MagicMock()
    vehicle_row.weight = vehicle_weight_qtl

    # fetchall for valid branches; fetchone for co scope checks + vehicle
    session.execute.return_value.fetchall.return_value = branch_rows
    session.execute.return_value.fetchone.side_effect = [
        branch_check_row,  # _validate_branch_belongs_to_co
        supplier_row,      # _validate_supplier_party_for_co
        vehicle_row,       # vehicle weight lookup
    ]

    return session, added_objects, existing_po


class TestJutePOCreateEndpoint:
    """Endpoint-level tests for /api/jutePO/jute_po_create."""

    def setup_method(self):
        self.session, self.added = _make_mock_session_for_create(vehicle_weight_qtl=100.0)
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self.session

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _base_payload(self):
        return {
            "co_id": 1,
            "branch_id": 2,
            "po_date": "2026-03-26",
            "mukam_id": 307,
            "jute_unit": "BALE",
            "supplier_id": 857,
            "party_id": None,
            "vehicle_type_id": 1,
            "vehicle_quantity": 2,
            "channel_code": "DOMESTIC",
            "line_items": [],
        }

    def test_create_with_percentage_derives_quantity(self):
        """3 lines 50/30/20 on vehicle 100qtl x 2 -> 10000/6000/4000 kg derived."""
        payload = self._base_payload()
        payload["line_items"] = [
            {"item_id": 269847, "percentage": 50.0, "rate": 10000, "jute_unit": "BALE"},
            {"item_id": 269848, "percentage": 30.0, "rate": 10000, "jute_unit": "BALE"},
            {"item_id": 269849, "percentage": 20.0, "rate": 10000, "jute_unit": "BALE"},
        ]

        response = client.post("/api/jutePO/jute_po_create", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True

        # Header + 3 detail rows added
        # added[0] = JutePo header, added[1..3] = JutePoLi rows
        po_lis = [obj for obj in self.added if type(obj).__name__ == "JutePoLi"]
        assert len(po_lis) == 3

        # Line 1: 50% -> 10000 kg -> 66.666... bales -> rounded to 67
        assert po_lis[0].percentage == 50.0
        assert po_lis[0].quantity == pytest.approx(round(10000.0 / WEIGHT_PER_BALE_KG))

        # Line 2: 30% -> 6000 kg -> 40 bales (already whole)
        assert po_lis[1].percentage == 30.0
        assert po_lis[1].quantity == pytest.approx(round(6000.0 / WEIGHT_PER_BALE_KG))

        # Line 3: 20% -> 4000 kg -> 26.666... bales -> rounded to 27
        assert po_lis[2].percentage == 20.0
        assert po_lis[2].quantity == pytest.approx(round(4000.0 / WEIGHT_PER_BALE_KG))

    def test_create_percentage_sum_mismatch(self):
        """Sum = 95 -> 400 with 'sum to 100' in detail."""
        payload = self._base_payload()
        payload["line_items"] = [
            {"item_id": 1, "percentage": 50.0, "rate": 10000, "jute_unit": "BALE"},
            {"item_id": 2, "percentage": 30.0, "rate": 10000, "jute_unit": "BALE"},
            {"item_id": 3, "percentage": 15.0, "rate": 10000, "jute_unit": "BALE"},
        ]
        response = client.post("/api/jutePO/jute_po_create", json=payload)
        assert response.status_code == 400
        assert "sum to 100" in response.json()["detail"].lower()

    def test_create_mixed_percentage_missing(self):
        """One line with percentage, another without -> 400."""
        payload = self._base_payload()
        payload["line_items"] = [
            {"item_id": 1, "percentage": 50.0, "rate": 10000, "jute_unit": "BALE"},
            {"item_id": 2, "quantity": 10, "rate": 10000, "jute_unit": "BALE"},
        ]
        response = client.post("/api/jutePO/jute_po_create", json=payload)
        assert response.status_code == 400
        assert "percentage" in response.json()["detail"].lower()

    def test_create_legacy_quantity_path(self):
        """Payload with quantity and no percentage -> legacy path, vehicle tolerance applies."""
        payload = self._base_payload()
        # Vehicle: 100 qtl x 2 = 200 qtl = 20000 kg. Bale = 150 kg.
        # Use 133 bales -> 133*150 = 19950 kg ~ 199.5 qtl -> 0.25% below capacity, within +/-5%.
        payload["line_items"] = [
            {"item_id": 1, "quantity": 133, "rate": 10000, "jute_unit": "BALE"},
        ]
        response = client.post("/api/jutePO/jute_po_create", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True

        po_lis = [obj for obj in self.added if type(obj).__name__ == "JutePoLi"]
        assert len(po_lis) == 1
        # Legacy path: quantity preserved, percentage is None
        assert po_lis[0].quantity == 133
        assert po_lis[0].percentage is None


class TestJutePOUpdateEndpoint:
    """Endpoint-level tests for /api/jutePO/jute_po_update/{id}."""

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_update_with_percentage(self):
        session, added, existing_po = _make_mock_session_for_update(
            existing_vehicle_quantity=2, vehicle_weight_qtl=100.0
        )
        app.dependency_overrides[get_tenant_db] = lambda: session

        payload = {
            "jute_unit": "BALE",
            "line_items": [
                {"item_id": 1, "percentage": 60.0, "rate": 10000, "jute_unit": "BALE"},
                {"item_id": 2, "percentage": 40.0, "rate": 10000, "jute_unit": "BALE"},
            ],
        }
        response = client.put(
            "/api/jutePO/jute_po_update/12345?co_id=1",
            json=payload,
        )
        assert response.status_code == 200, response.text
        assert response.json()["success"] is True

        po_lis = [obj for obj in added if type(obj).__name__ == "JutePoLi"]
        assert len(po_lis) == 2
        # 60% of 20000 kg = 12000 kg -> 80 bales (already whole)
        assert po_lis[0].percentage == 60.0
        assert po_lis[0].quantity == pytest.approx(round(12000.0 / WEIGHT_PER_BALE_KG))
        # 40% of 20000 kg = 8000 kg -> 53.333 bales -> rounded to 53
        assert po_lis[1].percentage == 40.0
        assert po_lis[1].quantity == pytest.approx(round(8000.0 / WEIGHT_PER_BALE_KG))

    def test_update_percentage_sum_mismatch(self):
        session, _, _ = _make_mock_session_for_update(
            existing_vehicle_quantity=2, vehicle_weight_qtl=100.0
        )
        app.dependency_overrides[get_tenant_db] = lambda: session

        payload = {
            "line_items": [
                {"item_id": 1, "percentage": 60.0, "rate": 10000, "jute_unit": "BALE"},
                {"item_id": 2, "percentage": 30.0, "rate": 10000, "jute_unit": "BALE"},
            ],
        }
        response = client.put(
            "/api/jutePO/jute_po_update/12345?co_id=1",
            json=payload,
        )
        assert response.status_code == 400
        assert "sum to 100" in response.json()["detail"].lower()
