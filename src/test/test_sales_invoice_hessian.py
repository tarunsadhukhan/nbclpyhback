"""Unit tests for the shared Hessian calculation formula used by Sales Invoice.

Mirrors `vowerp3ui/src/app/dashboardportal/sales/salesOrder/createSalesOrder/utils/hessianCalculations.test.ts`
for the invoice flow (no brokerage).
"""
from src.sales.hessian_calculations import (
    compute_hessian_fields,
    resolve_qty_rounding,
)


class TestComputeHessianFields:
    def test_standard_values(self):
        # 10 bales, 60000 rate/MT, conv=5 (1 MT = 5 bales)
        r = compute_hessian_fields(10, 60000, 5)
        assert r["qty_mt"] == 2.0  # 10 / 5
        assert r["rate_per_bale"] == 12000.0
        assert r["billing_rate_mt"] == 60000.0
        assert r["billing_rate_bale"] == 12000.0

    def test_default_qty_rounding_is_3(self):
        # 7 / 3 = 2.3333333... with default rounding=3 → 2.333
        r = compute_hessian_fields(7, 10000, 3)
        assert r["qty_mt"] == 2.333

    def test_custom_qty_rounding(self):
        # Same inputs but caller overrides to 4 decimals
        r = compute_hessian_fields(7, 10000, 3, 4)
        assert r["qty_mt"] == 2.3333

    def test_rate_always_rounded_to_2(self):
        r = compute_hessian_fields(10, 12345.6789, 5)
        assert r["billing_rate_mt"] == 12345.68
        assert r["rate_per_bale"] == 2469.14  # 12345.6789 / 5 = 2469.13578 → 2469.14
        assert r["billing_rate_bale"] == 2469.14

    def test_zero_conversion_factor_zeros_qty_and_rates(self):
        r = compute_hessian_fields(10, 60000, 0)
        assert r["qty_mt"] == 0
        assert r["rate_per_bale"] == 0
        # billing_rate_mt still reflects the rate itself (rounded to 2)
        assert r["billing_rate_mt"] == 60000.0
        assert r["billing_rate_bale"] == 0

    def test_zero_bales_keeps_rates(self):
        r = compute_hessian_fields(0, 60000, 5)
        assert r["qty_mt"] == 0
        assert r["rate_per_bale"] == 12000.0

    def test_no_brokerage_applied_regardless_of_input(self):
        # Invoice flow never subtracts brokerage. Rate goes in → billing_rate_mt
        # comes out identical (rounded).
        r = compute_hessian_fields(1, 1000, 1)
        assert r["billing_rate_mt"] == 1000.0


class TestResolveQtyRounding:
    def test_recorded_value_wins(self):
        assert resolve_qty_rounding(4) == 4
        assert resolve_qty_rounding(2) == 2

    def test_none_falls_back_to_default(self):
        assert resolve_qty_rounding(None) == 3

    def test_custom_default(self):
        assert resolve_qty_rounding(None, default=5) == 5

    def test_zero_is_honoured_not_treated_as_missing(self):
        # 0 is a legitimate rounding target (integer qty)
        assert resolve_qty_rounding(0) == 0
