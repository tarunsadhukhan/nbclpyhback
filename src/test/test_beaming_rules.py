"""Unit tests for the beaming formula layer (src/juteProduction/services/beaming_rules.py).

Pure functions — no DB, no auth, no HTTP. These pin the RPM -> SURFACE-SPEED model
(LOCKED CONTRACT): the machine 'speed' params (std/target/actual) are RPMs, and every
surface speed (yd/min) = rpm × dia × π/36 via act_speed(); p100prod capacity is built
from the STD SURFACE speed, NOT the raw std rpm.
"""

import math

from src.juteProduction.services.beaming_rules import (
    act_speed,
    p100prod,
    compute_beaming_daily,
)


class TestActSpeed:
    """act_speed(rpm, dia) = rpm × dia × π / 36 (the one reusable conversion)."""

    def test_surface_speed_from_rpm_and_dia(self):
        # 100 rpm × 12 dia × π/36 = 104.7197... -> round3 104.72
        assert act_speed(100, 12) == round(100 * 12 * math.pi / 36, 3)
        assert act_speed(100, 12) == 104.72

    def test_zero_rpm_returns_zero(self):
        # SQC seam: act_rpm = 0 (no actual entered yet) -> 0 surface speed.
        assert act_speed(0, 12) == 0.0

    def test_zero_dia_returns_zero(self):
        assert act_speed(100, 0) == 0.0

    def test_none_inputs_return_zero(self):
        assert act_speed(None, 12) == 0.0
        assert act_speed(100, None) == 0.0


class TestP100ProdFromStdSurface:
    """p100prod is built from the STD SURFACE speed (yd/min), not the raw std rpm."""

    def test_p100prod_uses_surface_speed(self):
        # std rpm 100, dia 12 -> std surface 104.72 yd/min.
        std_surface = act_speed(100, 12)
        # p100prod = std_surface × working_hours × 60, rounded to 0 dp.
        assert p100prod(std_surface, 8.0) == round(104.72 * 8.0 * 60, 0)
        assert p100prod(std_surface, 8.0) == 50266.0

    def test_p100prod_differs_from_raw_rpm_basis(self):
        # Proof the capacity is NOT computed from the raw rpm: raw-rpm basis would be
        # 100 × 8 × 60 = 48000, the surface basis is 50266.
        std_surface = act_speed(100, 12)
        assert p100prod(std_surface, 8.0) != p100prod(100, 8.0)
        assert p100prod(100, 8.0) == 48000.0


class TestComputeBeamingDailySurfaceSpeeds:
    """compute_beaming_daily converts std/target/act RPMs to surface speeds and feeds
    p100prod from the std surface speed (LOCKED CONTRACT)."""

    def _standards(self, **overrides):
        s = {
            "ends": 272.0, "std_count": 13.0, "act_count": 13.0, "laid_length": 1200.0,
            "std_cuts_per_beam": 50.0,
            "std_speed": 100.0,      # std RPM
            "target_speed": 110.0,   # target RPM
            "act_rpm": 30.0,         # actual RPM (value_role='actual')
            "std_eff": 85.0, "target_eff": 90.0, "working_hours": 8.0,
            "dia": 12.0, "components": None,
        }
        s.update(overrides)
        return s

    def test_three_surface_speeds_derived_from_rpm(self):
        out = compute_beaming_daily({"act_cuts": 4, "no_of_beam": 2}, self._standards())
        assert out["std_speed"] == act_speed(100, 12)      # 104.72
        assert out["target_speed"] == act_speed(110, 12)   # 115.192
        assert out["act_speed"] == act_speed(30, 12)       # 31.416
        assert out["std_speed"] == 104.72
        assert out["target_speed"] == 115.192
        assert out["act_speed"] == 31.416

    def test_p100prod_built_from_std_surface(self):
        out = compute_beaming_daily({"act_cuts": 4, "no_of_beam": 2}, self._standards())
        # std surface 104.72 × 8 × 60 -> 50266 (NOT the raw-rpm 48000).
        assert out["p100prod"] == p100prod(act_speed(100, 12), 8.0)
        assert out["p100prod"] == 50266.0

    def test_act_speed_zero_when_act_rpm_absent(self):
        # SQC seam: no actual RPM resolved -> act surface speed 0; std/target unaffected.
        out = compute_beaming_daily(
            {"act_cuts": 4, "no_of_beam": 2}, self._standards(act_rpm=0.0)
        )
        assert out["act_speed"] == 0.0
        assert out["std_speed"] == 104.72
        assert out["p100prod"] == 50266.0

    def test_composite_components_drive_kg_per_cut(self):
        # Composite stays green: Σ_n kg/cut from components; surface speeds unchanged.
        out = compute_beaming_daily(
            {"act_cuts": 4, "no_of_beam": 2},
            self._standards(
                std_count=None,
                act_count=None,
                components=[{"ends": 120, "count": 8.0}, {"ends": 160, "count": 10.0}],
            ),
        )
        assert out["std_speed"] == 104.72
        assert out["act_speed"] == 31.416
        assert out["kg_per_cut"] > 0
