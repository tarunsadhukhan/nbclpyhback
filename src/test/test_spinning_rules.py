"""Pure unit tests for src/juteProduction/services/spinning_rules.py.

No mocks — import the formula functions and assert. These mirror the legacy
mill spreadsheet computations and must stay green.
"""

from src.juteProduction.services.spinning_rules import (
    allocate_winding,
    compute_net,
    compute_spinning_daily,
    compute_tare,
    p100_prod_spell,
    p100_x,
    validate_net,
)


# =============================================================================
# p100_x — 100%-efficiency production per shift bucket
# =============================================================================


class TestP100X:
    def test_zero_when_no_frames(self):
        assert p100_x(speed=100, hrs_x=8, act_count=10, spindle=100, frames_x=0, tpi=12) == 0.0

    def test_zero_when_no_tpi(self):
        assert p100_x(speed=100, hrs_x=8, act_count=10, spindle=100, frames_x=5, tpi=0) == 0.0

    def test_known_nonzero_value(self):
        # speed*hrs*60*act_count*spindle*frames / (tpi*14400*2.2046*36)
        speed, hrs_x, act_count, spindle, frames_x, tpi = 600, 8, 8, 100, 4, 12
        numer = speed * hrs_x * 60 * act_count * spindle * frames_x
        denom = tpi * 14400 * 2.2046 * 36
        expected = round(numer / denom, 2)
        assert p100_x(speed, hrs_x, act_count, spindle, frames_x, tpi) == expected
        # sanity: a real, positive number
        assert expected > 0


# =============================================================================
# compute_tare / compute_net
# =============================================================================


class TestTareNet:
    def test_compute_tare_sums_three_weights(self):
        assert compute_tare(10.0, 2.0, 0.5) == 12.5

    def test_compute_tare_rounds_to_three(self):
        # 1.2345 + 2.0 + 0.5 = 3.7345 -> rounds to 3.734 (banker's rounding on the 5)
        assert compute_tare(1.2345, 2.0, 0.5) == round(1.2345 + 2.0 + 0.5, 3)

    def test_compute_tare_casts_strings(self):
        assert compute_tare("10", "2", "0.5") == 12.5

    def test_compute_net_subtracts_tare(self):
        assert compute_net(50.0, 12.5) == 37.5

    def test_compute_net_rounds_to_three(self):
        assert compute_net(50.12345, 12.0) == 38.123


# =============================================================================
# validate_net — boundaries [5.0, 60.0]
# =============================================================================


class TestValidateNet:
    def test_lower_boundary_inclusive(self):
        assert validate_net(5.0) is True

    def test_upper_boundary_inclusive(self):
        assert validate_net(60.0) is True

    def test_below_lower_boundary(self):
        assert validate_net(4.9) is False

    def test_above_upper_boundary(self):
        assert validate_net(60.1) is False

    def test_mid_range(self):
        assert validate_net(30.0) is True


# =============================================================================
# compute_spinning_daily — roll-up
# =============================================================================


class TestComputeSpinningDaily:
    KW = dict(
        speed=600,
        tpi=12,
        spindle=100,
        act_count=8,
        tar_eff=85.0,
        frames_a=4,
        frames_b=4,
        frames_c=2,
        prod_a=300.0,
        prod_b=290.0,
        prod_c=150.0,
        hrs_a=8.0,
        hrs_b=8.0,
        hrs_c=7.5,
        winders=10,
    )

    def test_tar_prd_is_sum_of_p100s(self):
        r = compute_spinning_daily(**self.KW)
        assert r["tar_prd"] == round(r["p100a"] + r["p100b"] + r["p100c"], 2)

    def test_totmc_is_sum_of_frames(self):
        r = compute_spinning_daily(**self.KW)
        assert r["totmc"] == 4 + 4 + 2

    def test_totprd_is_sum_of_prod(self):
        r = compute_spinning_daily(**self.KW)
        assert r["totprd"] == 300.0 + 290.0 + 150.0

    def test_act_eff_matches_formula(self):
        r = compute_spinning_daily(**self.KW)
        totprd = 300.0 + 290.0 + 150.0
        expected = round(totprd / r["tar_prd"] * 100, 2) if r["tar_prd"] else 0.0
        assert r["act_eff"] == expected

    def test_eff_a_matches_formula(self):
        r = compute_spinning_daily(**self.KW)
        expected = round(300.0 / r["p100a"] * 100, 2) if r["p100a"] else 0.0
        assert r["eff_a"] == expected

    def test_prd_frm_is_totprd_over_totmc(self):
        r = compute_spinning_daily(**self.KW)
        totprd = 300.0 + 290.0 + 150.0
        assert r["prd_frm"] == round(totprd / 10, 0)  # totmc = 10

    def test_prd_wnd_is_totprd_over_winders(self):
        r = compute_spinning_daily(**self.KW)
        totprd = 300.0 + 290.0 + 150.0
        assert r["prd_wnd"] == round(totprd / 10, 0)  # winders = 10

    def test_zero_winders_no_div_error(self):
        r = compute_spinning_daily(**dict(self.KW, winders=0))
        assert r["prd_wnd"] == 0.0

    def test_zero_frames_gives_zero_effs(self):
        r = compute_spinning_daily(
            **dict(self.KW, frames_a=0, frames_b=0, frames_c=0)
        )
        assert r["p100a"] == 0.0 and r["p100b"] == 0.0 and r["p100c"] == 0.0
        assert r["tar_prd"] == 0.0
        assert r["act_eff"] == 0.0
        assert r["eff_a"] == 0.0
        assert r["totmc"] == 0
        assert r["tarprd_frm"] == 0.0
        assert r["prd_frm"] == 0.0


# =============================================================================
# p100_prod_spell — per-frame-per-spell 100% production (planning refactor)
# =============================================================================


class TestP100ProdSpell:
    def test_worked_example_speed_4000(self):
        # doc §3: speed=4000, minutes=300, act_count=12.5, spindles=120, tpi=4 -> 394
        assert p100_prod_spell(
            std_speed=4000, minutes=300, act_count=12.5, spindles=120, std_tpi=4
        ) == 394

    def test_worked_example_spindles_100(self):
        # doc §3 second example: same inputs but spindles=100 -> 328.
        # (4000*300*12.5*100) / (36*14400*2.2046*4) = 328.1 -> round 0 -> 328
        assert p100_prod_spell(
            std_speed=4000, minutes=300, act_count=12.5, spindles=100, std_tpi=4
        ) == 328

    def test_zero_when_no_tpi(self):
        assert p100_prod_spell(
            std_speed=4000, minutes=300, act_count=12.5, spindles=120, std_tpi=0
        ) == 0.0

    def test_zero_when_no_spindles(self):
        assert p100_prod_spell(
            std_speed=4000, minutes=300, act_count=12.5, spindles=0, std_tpi=4
        ) == 0.0


# =============================================================================
# allocate_winding — winding total split across rows by doff share
# =============================================================================


class TestAllocateWinding:
    # doc §5: seven frames, doffs sum 1540, winding total W = 1450.
    DOFFS = [280, 150, 270, 145, 270, 145, 280]
    W = 1450

    def _rows(self):
        return [{"act_prod_doff": d} for d in self.DOFFS]

    def test_allocations_sum_back_to_w(self):
        rows = self._rows()
        out = allocate_winding(rows, self.W)
        total = sum(r["act_prod_wind"] for r in out)
        assert abs(total - 1450.0) <= 0.1

    def test_returns_one_row_per_input(self):
        out = allocate_winding(self._rows(), self.W)
        assert len(out) == 7

    def test_does_not_mutate_inputs(self):
        rows = self._rows()
        allocate_winding(rows, self.W)
        assert all("act_prod_wind" not in r for r in rows)

    def test_zero_denominator_gives_zero_allocations(self):
        rows = [{"act_prod_doff": 0}, {"act_prod_doff": 0}]
        out = allocate_winding(rows, self.W)
        assert all(r["act_prod_wind"] == 0.0 for r in out)
