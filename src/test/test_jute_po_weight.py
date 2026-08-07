"""
Tests for Jute PO weight calculation — verifies header-level jute_unit
is used for weight calculation, not per-line-item defaults.
"""
from src.juteProcurement.jutePO import (
    calculate_line_item_weight,
    validate_vehicle_weight,
    JutePOCreate,
    JutePOUpdate,
    JutePOLineItemCreate,
    WEIGHT_PER_BALE_KG,
    WEIGHT_PER_LOOSE_KG,
)


# =============================================================================
# Unit tests for calculate_line_item_weight
# =============================================================================

class TestCalculateLineItemWeight:
    def test_bale_weight(self):
        assert calculate_line_item_weight(10, "BALE") == WEIGHT_PER_BALE_KG * 10

    def test_loose_weight(self):
        assert calculate_line_item_weight(10, "LOOSE") == WEIGHT_PER_LOOSE_KG * 10

    def test_bale_vs_loose_different(self):
        """BALE and LOOSE must produce different weights for the same quantity."""
        bale = calculate_line_item_weight(100, "BALE")
        loose = calculate_line_item_weight(100, "LOOSE")
        assert bale != loose
        assert bale > loose

    def test_zero_quantity(self):
        assert calculate_line_item_weight(0, "BALE") == 0
        assert calculate_line_item_weight(0, "LOOSE") == 0


# =============================================================================
# Pydantic model tests
# =============================================================================

class TestJutePOModels:
    def test_create_jute_unit_defaults_to_bale(self):
        """JutePOCreate.jute_unit should default to BALE."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            supplier_id=857, vehicle_type_id=1, vehicle_quantity=3,
            channel_code="DOMESTIC",
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        assert payload.jute_unit == "BALE"

    def test_create_jute_unit_bale_preserved(self):
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="BALE",
            supplier_id=857, vehicle_type_id=1, vehicle_quantity=3,
            channel_code="DOMESTIC",
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        assert payload.jute_unit == "BALE"

    def test_create_jute_unit_loose_preserved(self):
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="LOOSE",
            supplier_id=857, vehicle_type_id=1, vehicle_quantity=3,
            channel_code="DOMESTIC",
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        assert payload.jute_unit == "LOOSE"

    def test_update_jute_unit_optional(self):
        """JutePOUpdate.jute_unit should be optional (None by default)."""
        payload = JutePOUpdate()
        assert payload.jute_unit is None

    def test_update_jute_unit_preserved(self):
        payload = JutePOUpdate(jute_unit="LOOSE")
        assert payload.jute_unit == "LOOSE"


# =============================================================================
# Simulate the exact create endpoint weight logic
# =============================================================================

class TestCreateEndpointWeightLogic:
    """
    Simulates the weight calculation logic from jute_po_create to verify
    header jute_unit is used, not per-line-item jute_unit.
    """

    def _simulate_create_weight(self, payload: JutePOCreate) -> tuple[float, float, str]:
        """
        Replicates the weight calculation logic from jute_po_create endpoint.
        Returns (total_weight_kg, total_value, jute_uom_stored).
        """
        header_jute_unit = payload.jute_unit or "BALE"
        total_weight_kg = 0.0
        total_value = 0.0

        for li in payload.line_items:
            weight_kg = calculate_line_item_weight(li.quantity, header_jute_unit)
            weight_in_quintals = weight_kg / 100
            amount = weight_in_quintals * li.rate
            total_weight_kg += weight_kg
            total_value += amount

        return total_weight_kg, total_value, header_jute_unit

    def test_bale_weight_330_qty(self):
        """330 bales at BALE = 330 * 150 = 49500 kg."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="BALE", supplier_id=857, vehicle_type_id=1,
            vehicle_quantity=3, channel_code="DOMESTIC",
            line_items=[JutePOLineItemCreate(quantity=330, rate=12311)],
        )
        weight, value, uom = self._simulate_create_weight(payload)
        assert weight == 330 * WEIGHT_PER_BALE_KG  # 49500
        assert uom == "BALE"
        # value = (49500 / 100) * 12311 = 495 * 12311
        assert value == 495 * 12311

    def test_loose_weight_330_qty(self):
        """330 loose at LOOSE = 330 * 48 = 15840 kg."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="LOOSE", supplier_id=857, vehicle_type_id=1,
            vehicle_quantity=3, channel_code="DOMESTIC",
            line_items=[JutePOLineItemCreate(quantity=330, rate=12311)],
        )
        weight, value, uom = self._simulate_create_weight(payload)
        assert weight == 330 * WEIGHT_PER_LOOSE_KG  # 15840
        assert uom == "LOOSE"

    def test_header_bale_overrides_line_item_loose(self):
        """Header BALE must override line item LOOSE."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="BALE", supplier_id=857, vehicle_type_id=1,
            vehicle_quantity=3, channel_code="DOMESTIC",
            line_items=[
                JutePOLineItemCreate(quantity=100, rate=10000, jute_unit="LOOSE"),
            ],
        )
        weight, _, uom = self._simulate_create_weight(payload)
        # Header says BALE → 100 * 150 = 15000, NOT 100 * 48 = 4800
        assert weight == 100 * WEIGHT_PER_BALE_KG
        assert weight != 100 * WEIGHT_PER_LOOSE_KG
        assert uom == "BALE"

    def test_header_loose_overrides_line_item_bale(self):
        """Header LOOSE must override line item BALE."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="LOOSE", supplier_id=857, vehicle_type_id=1,
            vehicle_quantity=3, channel_code="DOMESTIC",
            line_items=[
                JutePOLineItemCreate(quantity=100, rate=10000, jute_unit="BALE"),
            ],
        )
        weight, _, uom = self._simulate_create_weight(payload)
        assert weight == 100 * WEIGHT_PER_LOOSE_KG
        assert weight != 100 * WEIGHT_PER_BALE_KG
        assert uom == "LOOSE"

    def test_multiple_line_items_all_use_header_unit(self):
        """All line items should use the header unit regardless of their own."""
        payload = JutePOCreate(
            co_id=1, branch_id=2, po_date="2026-03-26", mukam_id=307,
            jute_unit="BALE", supplier_id=857, vehicle_type_id=1,
            vehicle_quantity=5, channel_code="DOMESTIC",
            line_items=[
                JutePOLineItemCreate(quantity=100, rate=10000, jute_unit="LOOSE"),
                JutePOLineItemCreate(quantity=200, rate=8000, jute_unit="LOOSE"),
                JutePOLineItemCreate(quantity=50, rate=12000),  # no jute_unit
            ],
        )
        weight, _, uom = self._simulate_create_weight(payload)
        # All 3 should use BALE: (100+200+50) * 150 = 52500
        expected = (100 + 200 + 50) * WEIGHT_PER_BALE_KG
        assert weight == expected
        assert uom == "BALE"

    def test_real_payload_from_frontend(self):
        """Test with the actual payload from the frontend."""
        payload = JutePOCreate(
            co_id=0,
            branch_id=2,
            po_date="2026-03-26",
            mukam_id=307,
            jute_unit="BALE",
            supplier_id=857,
            party_id=8907,
            vehicle_type_id=1,
            vehicle_quantity=3,
            channel_code="DOMESTIC",
            credit_term=10,
            delivery_timeline=10,
            line_items=[
                JutePOLineItemCreate(
                    item_id=269847,
                    quantity=330,
                    rate=12311,
                    allowable_moisture=18,
                    jute_unit="BALE",
                ),
            ],
        )
        weight, value, uom = self._simulate_create_weight(payload)

        # 330 bales * 150 kg = 49500 kg
        assert weight == 49500
        assert uom == "BALE"
        # value = (49500/100) * 12311 = 495 * 12311 = 6,093,945
        assert value == 6093945.0


# =============================================================================
# Simulate the update endpoint weight logic
# =============================================================================

class TestUpdateEndpointWeightLogic:
    """
    Simulates the weight calculation logic from jute_po_update to verify
    header jute_unit (or existing PO value) is used.
    """

    def _simulate_update_weight(
        self, payload: JutePOUpdate, existing_jute_uom: str | None
    ) -> tuple[float, str]:
        """
        Replicates: header_jute_unit = payload.jute_unit or jute_po.jute_uom or "BALE"
        """
        header_jute_unit = payload.jute_unit or existing_jute_uom or "BALE"
        total_weight_kg = 0.0

        for li in (payload.line_items or []):
            weight_kg = calculate_line_item_weight(li.quantity, header_jute_unit)
            total_weight_kg += weight_kg

        return total_weight_kg, header_jute_unit

    def test_update_uses_payload_jute_unit(self):
        payload = JutePOUpdate(
            jute_unit="LOOSE",
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        weight, uom = self._simulate_update_weight(payload, existing_jute_uom="BALE")
        assert weight == 100 * WEIGHT_PER_LOOSE_KG
        assert uom == "LOOSE"

    def test_update_falls_back_to_existing_po_uom(self):
        payload = JutePOUpdate(
            jute_unit=None,  # not sent
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        weight, uom = self._simulate_update_weight(payload, existing_jute_uom="BALE")
        assert weight == 100 * WEIGHT_PER_BALE_KG
        assert uom == "BALE"

    def test_update_falls_back_to_default_bale(self):
        payload = JutePOUpdate(
            jute_unit=None,
            line_items=[JutePOLineItemCreate(quantity=100, rate=10000)],
        )
        weight, uom = self._simulate_update_weight(payload, existing_jute_uom=None)
        assert weight == 100 * WEIGHT_PER_BALE_KG
        assert uom == "BALE"
