"""Pure unit tests for src/juteProduction/services/winding_rules.py.

No mocks — import the formula functions and assert. Winding entry is
person-keyed (docs/winding-person-keyed-entry-spec.md §5, decision D4): one
weighing by one person = one row, so net = gross - trolly - spool with no
machine split and no no_of_machines.
"""

import pytest

from src.juteProduction.constants import (
    WINDING_NET_MAX,
    WINDING_NET_MIN,
)
from src.juteProduction.services import winding_rules
from src.juteProduction.services.winding_rules import (
    compute_winding_net,
    compute_winding_row_gross_wt,
    reconcile_production,
    validate_winding_net,
)


# =============================================================================
# compute_winding_net — net = gross - trolly - spool  (no nomc)
# =============================================================================


class TestComputeWindingNet:
    def test_worked_example_positive(self):
        # grosswt=100, trollywt=2, spoolwt=1 -> 97
        assert compute_winding_net(100, 2, 1) == 97.0

    def test_net_gate_value_above_zero(self):
        assert compute_winding_net(100, 2, 1) > 0

    def test_net_can_be_zero_or_negative_for_gating(self):
        # When tare exceeds gross the function returns <= 0 (caller gates, no clamp).
        assert compute_winding_net(20, 20, 5) == -5.0
        assert compute_winding_net(25, 20, 5) == 0.0

    def test_rounds_to_three(self):
        assert compute_winding_net(320.12345, 20, 5) == round(320.12345 - 20 - 5, 3)

    def test_casts_strings(self):
        assert compute_winding_net("320", "20", "5") == 295.0

    def test_takes_exactly_three_arguments(self):
        """The nomc argument is gone — a 4-arg call must fail loudly rather than
        silently reinterpret the spool weight as a machine count."""
        with pytest.raises(TypeError):
            compute_winding_net(320, 20, 2, 5)


# =============================================================================
# compute_winding_net_per_mc — DELETED with the machine split (D4)
# =============================================================================


class TestNetPerMcIsGone:
    def test_compute_winding_net_per_mc_no_longer_exists(self):
        assert not hasattr(winding_rules, "compute_winding_net_per_mc")


# =============================================================================
# compute_winding_row_gross_wt — net + trolly + spool
# =============================================================================


class TestComputeWindingRowGrossWt:
    def test_row_gross_formula(self):
        assert compute_winding_row_gross_wt(145, 20, 5) == 170.0

    def test_round_trips_the_net(self):
        """row_gross_wt is the inverse of compute_winding_net."""
        net = compute_winding_net(100, 2, 1)
        assert compute_winding_row_gross_wt(net, 2, 1) == 100.0

    def test_rounds_to_three(self):
        assert compute_winding_row_gross_wt(145, 20.1234, 5) == round(145 + 20.1234 + 5, 3)


# =============================================================================
# validate_winding_net — boundaries [WINDING_NET_MIN, WINDING_NET_MAX]
# =============================================================================


class TestValidateWindingNet:
    def test_constants_are_one_and_five_hundred(self):
        assert WINDING_NET_MIN == 1
        assert WINDING_NET_MAX == 500

    def test_lower_boundary_inclusive(self):
        assert validate_winding_net(1) is True

    def test_upper_boundary_inclusive(self):
        assert validate_winding_net(500) is True

    def test_below_lower_boundary(self):
        assert validate_winding_net(0) is False

    def test_above_upper_boundary(self):
        assert validate_winding_net(501) is False

    def test_mid_range(self):
        assert validate_winding_net(290) is True

    def test_worked_example_passes(self):
        assert validate_winding_net(compute_winding_net(100, 2, 1)) is True


# =============================================================================
# reconcile_production — SUM(production) - opening + closing  (kg)
# =============================================================================


class TestReconcileProduction:
    def test_worked_example(self):
        # sum=100, open=10, close=8 -> 100 - 10 + 8 = 98
        assert reconcile_production(100, 10, 8) == 98.0

    def test_no_jugar_returns_sum(self):
        assert reconcile_production(100, 0, 0) == 100.0

    def test_opening_only_reduces(self):
        assert reconcile_production(100, 12, 0) == 88.0

    def test_closing_only_increases(self):
        assert reconcile_production(100, 0, 7) == 107.0

    def test_rounds_to_three(self):
        assert reconcile_production(100.12345, 10, 8) == round(100.12345 - 10 + 8, 3)

    def test_casts_strings(self):
        assert reconcile_production("100", "10", "8") == 98.0
