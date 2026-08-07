"""Pure weaving jugar/production formulas — FE parity + unit tests ONLY.

STORAGE MODEL = FREEZE NOTHING + VIEW (2026-06-24). The view ``vw_weaving_daily``
is now the single source of truth for every derived weaving column (open_jugar via a
LAG window, jugar, production_yds/kg/mt, std_prod_yds, efficiency, ...). The server no
longer computes or freezes anything on save: ``entry_create``/``entry_edit`` persist
INPUTS ONLY and the read endpoints SELECT from the view.

So the old save-path machinery is GONE:
  * resolve_open_jugar / close_jugar  -> replaced by the view's LAG-over-existing-rows
  * compute_weaving_daily save-path    -> replaced by the view's per-row computation
  * recompute_cascade                  -> the LAG auto-propagates downstream/across days

What remains here is a THIN, pure formula module mirroring the view's jugar math
EXACTLY, kept only so the frontend (weavingCalc.ts) and the unit tests have a Python
reference for the live preview. No DB access; no SQLAlchemy import.

REVISED PRODUCTION MODEL 2026-06-30 (server math is authoritative — matches vw_weaving_daily):
    oj = open_jugar  (resolved by the view's LAG; passed in here for preview)
    cj = close_jugar (operator input; 0 <= cj <= jc, rejected at write time)
    jc = no_of_jugar_per_cut (quality master, > 0)
    adj = less_production (reduce-jugar adjustment; 0 when not applicable)
    total_jugar    = cuts * jc + cj - oj - adj      # no wrap, no clamp
    production_yds = total_jugar * finished_length / jc      # GUARD jc > 0 else 0

The cuts*jc term keeps total_jugar non-negative in practice, so no GREATEST(0)/max guard.
Constants WEAVING_GRAMS_PER_OZ=28.35 and WEAVING_YARD_FACTOR=36 are NOT simplified.
"""


def _f(x) -> float:
    """Coerce to float, treating None / '' as 0.0."""
    if x in (None, ""):
        return 0.0
    return float(x)


def total_jugar(cuts, jc, oj, cj, adj=0) -> float:
    """total_jugar = cuts*jc + cj - oj - adj (mirrors vw_weaving_daily EXACTLY).

    No wrap, no clamp. jc = no_of_jugar_per_cut, oj = open_jugar (last close),
    cj = closing-jugar operator input, adj = less_production. Returns 0.0 when jc<=0.

    Worked (jc=16, no adj): A1 oj=0, cj=12, cuts=10 -> 10*16 + 12 - 0 = 172;
                            A2 oj=12, cj=4, cuts=5 -> 5*16 + 4 - 12 = 72.
    """
    jc_f = _f(jc)
    if jc_f <= 0:
        return 0.0
    return _f(cuts) * jc_f + _f(cj) - _f(oj) - _f(adj)


def production_yds(total, jc, fl) -> float:
    """production_yds = total_jugar * finished_length / jc. GUARD jc > 0 else 0.

    ``total`` is the total jugar (use :func:`total_jugar`). Mirrors the view's
    production_yds expression.
    """
    jc_f = _f(jc)
    if jc_f <= 0:
        return 0.0
    return _f(total) * _f(fl) / jc_f
