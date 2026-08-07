"""Unit tests for the thin weaving formula layer (services/weaving_rules.py).

STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24): the view vw_weaving_daily is the
single source of truth for every derived weaving column. weaving_rules.py is now a THIN,
PURE formula module (no DB) kept only for FE parity (weavingCalc.ts) + these unit tests.

REVISED PRODUCTION MODEL 2026-06-30 — it exposes two functions mirroring the view:

  total_jugar(cuts, jc, oj, cj, adj=0): cuts*jc + cj - oj - adj   (no wrap, no clamp)
  production_yds(total, jc, fl):        total * fl / jc           (GUARD jc>0 else 0)

A FastAPI TestClient(app) is imported (repo test pattern) so module wiring is exercised
on import; the assertions run against the pure functions.
"""

from fastapi.testclient import TestClient

from src.main import app
from src.juteProduction.services.weaving_rules import (
    total_jugar,
    production_yds,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# total_jugar = cuts*jc + cj - oj - adj   (mirrors vw_weaving_daily EXACTLY)
# ---------------------------------------------------------------------------


class TestTotalJugar:
    def test_worked_a1(self):
        # jc=16, oj=0, cj=12, cuts=10 -> 10*16 + 12 - 0 = 172.
        assert total_jugar(10, 16, 0, 12) == 172.0

    def test_worked_a2_close_below_open(self):
        # jc=16, oj=12, cj=4, cuts=5 -> 5*16 + 4 - 12 = 72 (no wrap: cj-oj is -8).
        assert total_jugar(5, 16, 12, 4) == 72.0

    def test_adjustment_subtracted(self):
        # adj (less_production) deducts directly: 10*16 + 12 - 0 - 2 = 170.
        assert total_jugar(10, 16, 0, 12, 2) == 170.0

    def test_jc_zero_guarded(self):
        # jc <= 0 -> 0 (the view's CASE jc>0 guard).
        assert total_jugar(5, 0, 1, 2) == 0.0

    def test_none_inputs_coerced_to_zero(self):
        # oj None -> 0; jc=16, cj=2, cuts=5 -> 5*16 + 2 - 0 = 82.
        assert total_jugar(5, 16, None, 2) == 82.0

    def test_zero_cuts_is_close_minus_open(self):
        # cuts=0 -> total_jugar = cj - oj (the pure spell delta): 7 - 3 = 4.
        assert total_jugar(0, 16, 3, 7) == 4.0


# ---------------------------------------------------------------------------
# production_yds = total_jugar * fl / jc   [GUARD jc > 0 else 0]
# ---------------------------------------------------------------------------


class TestProductionYds:
    def test_worked_example_a1(self):
        # jc=16, FL=100, A1 cuts=10 oj=0 cj=12 -> total=172 -> 172*100/16 = 1075.0.
        total = total_jugar(10, 16, 0, 12)  # = 172
        assert production_yds(total, 16, 100) == 1075.0

    def test_worked_example_a2(self):
        # A2 oj=12 cuts=5 cj=4 -> total=72 -> 72*100/16 = 450.0.
        total = total_jugar(5, 16, 12, 4)  # = 72
        assert production_yds(total, 16, 100) == 450.0

    def test_jc_zero_guarded(self):
        # jc <= 0 -> 0 (no divide-by-zero).
        assert production_yds(172, 0, 100) == 0.0

    def test_spec_worked_a1_fl_unit(self):
        # FL=1: total=172 -> 172/16 = 10.75.
        total = total_jugar(10, 16, 0, 12)  # = 172
        assert production_yds(total, 16, 1) == 10.75

    def test_spec_worked_a2_fl_unit(self):
        # FL=1: total=72 -> 72/16 = 4.5.
        total = total_jugar(5, 16, 12, 4)  # = 72
        assert production_yds(total, 16, 1) == 4.5
