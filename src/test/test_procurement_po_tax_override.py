# src/test/test_procurement_po_tax_override.py
"""
Tests for per-line tax % override on PO save.

The frontend can override the tax percentage stored in item_mst per line item.
Server-side GST is then calculated from the resolved value (see
`resolve_line_tax_percentage` in src/procurement/po.py), not the master default.

Covers: override honored, explicit 0 honored, blank/absent -> master fallback,
and that the resolved value feeds the GST calculation.
"""

import pytest

from src.procurement.po import resolve_line_tax_percentage, calculate_gst_amounts


class TestResolveLineTaxPercentage:
    def test_override_value_is_honored(self):
        # Item master says 18, frontend sends 5 -> use 5
        assert resolve_line_tax_percentage({"tax_pct": 5}, 18.0) == 5.0

    def test_override_string_value_is_honored(self):
        # Numeric strings (as sent over JSON form payloads) are coerced
        assert resolve_line_tax_percentage({"tax_pct": "12.5"}, 18.0) == 12.5

    def test_explicit_zero_is_honored(self):
        # Explicit 0 means "no tax" — must NOT fall back to the master default
        assert resolve_line_tax_percentage({"tax_pct": 0}, 18.0) == 0.0

    def test_explicit_zero_string_is_honored(self):
        assert resolve_line_tax_percentage({"tax_pct": "0"}, 18.0) == 0.0

    def test_absent_key_falls_back_to_master(self):
        # No tax_pct key at all -> keep the item_mst default
        assert resolve_line_tax_percentage({}, 18.0) == 18.0

    def test_none_value_falls_back_to_master(self):
        assert resolve_line_tax_percentage({"tax_pct": None}, 18.0) == 18.0

    def test_blank_string_falls_back_to_master(self):
        assert resolve_line_tax_percentage({"tax_pct": "   "}, 18.0) == 18.0

    def test_unparseable_value_falls_back_to_master(self):
        # Garbage input keeps the master default rather than silently becoming 0
        assert resolve_line_tax_percentage({"tax_pct": "abc"}, 18.0) == 18.0


class TestResolvedTaxFeedsGstCalc:
    """The resolved value (not the master) drives server-side GST amounts."""

    def test_override_changes_gst_amount_same_state(self):
        master_default = 18.0
        resolved = resolve_line_tax_percentage({"tax_pct": 5}, master_default)
        # Same state (1 == 1) -> CGST/SGST split of 5% on 1000 = 50 total
        gst = calculate_gst_amounts(1000.0, resolved, source_state_id=1, destination_state_id=1)
        assert gst["tax_pct"] == 5.0
        assert gst["c_tax_amount"] == 25.0
        assert gst["s_tax_amount"] == 25.0
        assert gst["i_tax_amount"] == 0.0
        assert gst["tax_amount"] == 50.0

    def test_override_changes_gst_amount_inter_state(self):
        resolved = resolve_line_tax_percentage({"tax_pct": "12"}, 18.0)
        # Different states -> full IGST: 12% of 1000 = 120
        gst = calculate_gst_amounts(1000.0, resolved, source_state_id=1, destination_state_id=2)
        assert gst["i_tax_amount"] == 120.0
        assert gst["c_tax_amount"] == 0.0
        assert gst["s_tax_amount"] == 0.0
        assert gst["tax_amount"] == 120.0

    def test_zero_override_yields_no_tax(self):
        resolved = resolve_line_tax_percentage({"tax_pct": 0}, 18.0)
        gst = calculate_gst_amounts(1000.0, resolved, source_state_id=1, destination_state_id=2)
        assert resolved == 0.0
        assert gst["tax_amount"] == 0.0
        assert gst["i_tax_amount"] == 0.0
