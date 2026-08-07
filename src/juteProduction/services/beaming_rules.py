"""Business rules for beaming production — single source of truth.

The frontend mirrors these computations for live preview only (``beamingCalc.ts``);
the server values are authoritative and recomputed on every create/edit/save —
exactly as Spinning (``spinningCalc.ts`` previews, ``spinning_rules.py``
authoritative).

Two bases, one efficiency (SPEC §3):
- LENGTH basis (yards): ``p100prod``, ``std_prod``, ``target_prod``,
  ``act_prod_yards``. ``act_eff`` is computed HERE and is length÷length only.
- WEIGHT basis (kg): ``kg_per_cut``, ``kg_per_beam``, ``act_prod_kg``. These are
  reported weight outputs and must NEVER be divided by the yards ``p100prod``.

Unit caution: the kg/cut divisor (``BEAMING_SPYNDLE_YDS`` = 14400 yd per jute
spyndle, ``BEAMING_KG_TO_LB`` = 2.20462) encodes the legacy count-system
conversion. Do NOT "simplify" them — they reproduce the exact spreadsheet the
mill audits against. Beaming defines its OWN constants (2.20462) to avoid the
2.2046 vs 2.20462 precision drift carried by the Spinning constants.
"""

import math

from src.juteProduction.constants import (
    BEAMING_SPYNDLE_YDS,
    BEAMING_KG_TO_LB,
)


def round2(x) -> float:
    """Round to 2 dp (kg / efficiency reporting)."""
    return round(float(x), 2)


def round3(x) -> float:
    """Round to 3 dp (kg / length reporting)."""
    return round(float(x), 3)


# =============================================================================
# Speed
# =============================================================================


def act_speed(rpm, dia) -> float:
    """Starch-roller surface speed (yd/min) = rpm × dia × π / 36.

    Pure multiplication — no division by an input, so no div-by-zero guard
    needed. Returns 0.0 when either input is falsy/None.
    """
    if not rpm or not dia:
        return 0.0
    return round3(float(rpm) * float(dia) * math.pi / 36)


# =============================================================================
# LENGTH basis (yards) — efficiency is computed here
# =============================================================================


def yards_per_beam(laid_length, cuts) -> float:
    """yards_per_beam = laid_length × cuts (cuts = std_cuts_per_beam | act_cuts)."""
    return round3(float(laid_length) * float(cuts))


def p100prod(std_speed, working_hours) -> float:
    """100%-efficiency length capacity (yards).

    p100prod = std_speed × working_hours × 60. ONE value, ALWAYS std_speed-based
    (mirrors Spinning). Rounded to 0 dp. ``std_prod`` and ``target_prod`` both
    derive from this single value via their own eff%.
    """
    return round(float(std_speed) * float(working_hours) * 60, 0)


def std_prod(std_eff_pct, p100prod_yards) -> float:
    """std_prod (yards) = std_eff% × p100prod."""
    return round3(float(std_eff_pct) / 100 * float(p100prod_yards))


def target_prod(tgt_eff_pct, p100prod_yards) -> float:
    """target_prod (yards) = trgt_eff% × p100prod."""
    return round3(float(tgt_eff_pct) / 100 * float(p100prod_yards))


def act_prod_yards(laid_length, act_cuts, no_of_beam) -> float:
    """Actual length produced (yards) = laid_length × act_cuts × no_of_beam."""
    return round3(float(laid_length) * float(act_cuts) * float(no_of_beam))


def act_eff(act_prod_yards_val, p100prod_yards) -> float:
    """Actual efficiency (%) = act_prod_yards ÷ p100prod × 100 (yards ÷ yards).

    Like-for-like length÷length only — NEVER divide a kg figure by this yards
    ``p100prod``. Returns 0.0 when ``p100prod`` is zero/falsy (avoids div-by-zero).
    """
    if not p100prod_yards:
        return 0.0
    return round2(float(act_prod_yards_val) / float(p100prod_yards) * 100)


# =============================================================================
# WEIGHT basis (kg) — reported only; NOT compared to the length standard
# =============================================================================


def kg_per_cut_composite(components, laid_length) -> float:
    """kg per cut for a COMPOSITE warp — the Σ_n form over warp components.

    kg_per_cut = laid_length × Σ_n(ends_n × count_n)
                 / (BEAMING_SPYNDLE_YDS × BEAMING_KG_TO_LB)

    ``components`` is a list of ``{"ends": int, "count": float}`` (>= 1 component;
    a simple single-component quality is just the one-element case). When
    ``jute_prod_bm_quality.is_composite = 1`` the real (ends, count) pairs live in
    ``jute_prod_bm_quality_dtl`` (>= 2 components); when is_composite = 0 there is
    one component carrying the parent's ends/count. ``count`` = std_count
    (standard line) | act_count (actual line) per component.

    Returns 0.0 when ``components`` is empty or the divisor constants are falsy
    (defensive; the constants are nonzero).
    """
    if not components:
        return 0.0
    denom = float(BEAMING_SPYNDLE_YDS) * float(BEAMING_KG_TO_LB)
    if not denom:
        return 0.0
    sigma = 0.0
    for c in components:
        sigma += float(c.get("ends", 0) or 0) * float(c.get("count", 0) or 0)
    return round3(float(laid_length) * sigma / denom)


def kg_per_cut(ends, laid_length, count) -> float:
    """kg per cut for a SINGLE warp component (simple quality).

    kg_per_cut = ends × laid_length × count / (BEAMING_SPYNDLE_YDS × BEAMING_KG_TO_LB)

    ``count`` = std_count (standard line) | act_count (actual line). This is the
    one-component case of :func:`kg_per_cut_composite`; composite Σ_n qualities
    (>= 2 warp components, ``is_composite = 1``) use that function directly with
    the ``jute_prod_bm_quality_dtl`` rows. Returns 0.0 when the divisor constants
    are falsy (defensive; they are nonzero constants).
    """
    return kg_per_cut_composite([{"ends": ends, "count": count}], laid_length)


def kg_per_beam(kg_per_cut_val, cuts) -> float:
    """kg per beam = kg_per_cut × cuts (cuts = std_cuts_per_beam | act_cuts)."""
    return round3(float(kg_per_cut_val) * float(cuts))


def act_prod_kg(kg_per_cut_act, act_cuts, no_of_beam) -> float:
    """Actual weight produced (kg) = kg_per_cut(act_count) × act_cuts × no_of_beam.

    Weight report only — NEVER divided by the yards ``p100prod``.
    """
    return round3(float(kg_per_cut_act) * float(act_cuts) * float(no_of_beam))


# =============================================================================
# Daily roll-up — every computed column of jute_prod_beaming_daily (§C.2)
# =============================================================================


def compute_beaming_daily(inputs: dict, standards: dict) -> dict:
    """Compute every derived column of ``jute_prod_beaming_daily`` (SPEC §C.2).

    ``inputs`` — entry row fields::
        act_cuts, no_of_beam

    RPM → SURFACE-SPEED model (LOCKED CONTRACT). The values entered as the machine
    'speed' param in ``jute_prod_beaming_target_map`` are RPMs (rotations/min), NOT
    surface speeds. The starch-roller SURFACE speed (yd/min) for any role is
    ``rpm × dia × π / 36`` — the existing :func:`act_speed` conversion. So:
        std_speed (standards)    = std RPM     → std_surface    = act_speed(std_rpm, dia)
        target_speed (standards) = target RPM  → target_surface = act_speed(target_rpm, dia)
        act_rpm (standards)      = actual RPM  → act_surface    = act_speed(act_rpm, dia)

    ``dia`` is a machine-linked STANDARD (resolved server-side) read from
    ``standards["dia"]``; it feeds every surface-speed conversion above.

    SQC seam — RPM is NOT a production-entry input. The ACTUAL roller RPM is entered
    on the Beaming SQC page (reuses the /beamingTargetMap endpoints with
    value_role='actual', param='speed'(rpm)), resolved server-side as-of tran_date
    and passed in as ``standards["act_rpm"]``. Production entry passes no rpm, so when
    no actual SQC value exists ``act_rpm`` is absent/0 and ``act_speed`` (surface)
    computes to 0 until the SQC value is entered — exactly like ``idle_hours`` read 0
    before Stoppage Hours was wired.

    ``standards`` — resolved standards (machine + quality, as-of tran_date)::
        ends, std_count, act_count (defaults std_count), laid_length,
        std_cuts_per_beam, std_speed (= std RPM), target_speed (= target RPM),
        act_rpm (= actual RPM, defaults 0), std_eff, target_eff, working_hours, dia,
        components (optional list of {"ends": int, "count": float})

    Composite Σ_n: when ``standards`` carries a non-empty ``components`` list
    (``is_composite = 1``, rows from ``jute_prod_bm_quality_dtl``), kg_per_cut is
    the Σ_n form (:func:`kg_per_cut_composite`) and ``ends`` = SUM(component ends);
    otherwise the simple single-component path uses ``standards["ends"]`` with
    ``act_count``. Per Q5 the actual line reuses the std counts (act_count
    defaults std_count).

    Returns a dict with EVERY computed column:
        yards_per_beam, kg_per_cut, kg_per_beam, p100prod, std_prod,
        target_prod, act_prod_yards, act_prod_kg, act_eff,
        std_speed, target_speed, act_speed  (the three SURFACE speeds, yd/min)

    ``std_speed`` / ``target_speed`` / ``act_speed`` in the result are the computed
    SURFACE speeds (yd/min) — they overwrite/augment the raw RPMs that arrived in
    ``standards``. ``p100prod`` uses the STD SURFACE speed (NOT the raw rpm).

    The LENGTH basis (p100prod/std_prod/target_prod/act_prod_yards) and act_eff
    are yards; the WEIGHT basis (kg_per_cut/kg_per_beam/act_prod_kg) is kg. The
    kg figures are NEVER divided by the yards p100prod.
    """
    # --- entry inputs --------------------------------------------------------
    act_cuts = float(inputs.get("act_cuts", 0) or 0)
    no_of_beam = float(inputs.get("no_of_beam", 0) or 0)

    # --- resolved standards --------------------------------------------------
    std_count = float(standards.get("std_count", 0) or 0)
    act_count = standards.get("act_count")
    act_count = float(act_count) if act_count not in (None, "") else std_count
    laid_length = float(standards.get("laid_length", 0) or 0)
    std_cuts_per_beam = float(standards.get("std_cuts_per_beam", 0) or 0)
    # std_speed / target_speed are RPMs (machine 'speed' param); act_rpm is the
    # actual RPM resolved from the Beaming SQC actual role (0 until SQC entered).
    std_rpm = float(standards.get("std_speed", 0) or 0)
    target_rpm = float(standards.get("target_speed", 0) or 0)
    act_rpm = float(standards.get("act_rpm", 0) or 0)
    std_eff = float(standards.get("std_eff", 0) or 0)
    target_eff = float(standards.get("target_eff", 0) or 0)
    working_hours = float(standards.get("working_hours", 0) or 0)
    # dia is a machine-linked STANDARD (NOT an entry input).
    dia = standards.get("dia", 0) or 0
    components = standards.get("components")

    # --- surface speeds (yd/min) = rpm × dia × π / 36 ------------------------
    std_surface = act_speed(std_rpm, dia)
    target_surface = act_speed(target_rpm, dia)
    act_surface = act_speed(act_rpm, dia)

    # --- LENGTH basis (yards) ------------------------------------------------
    # yards_per_beam uses the STANDARD cuts/beam (planning standard).
    ypb = yards_per_beam(laid_length, std_cuts_per_beam)
    # p100prod uses the STD SURFACE speed (NOT the raw rpm).
    p100 = p100prod(std_surface, working_hours)
    sprod = std_prod(std_eff, p100)
    tprod = target_prod(target_eff, p100)
    apy = act_prod_yards(laid_length, act_cuts, no_of_beam)
    aeff = act_eff(apy, p100)

    # --- WEIGHT basis (kg) — NEVER divided by the yards p100prod -------------
    # Composite Σ_n: kg_per_cut over warp components; ends = SUM(component ends).
    # Per Q5 the actual line reuses the std counts (act_count defaults std_count).
    if components:
        kpc = kg_per_cut_composite(components, laid_length)
    else:
        # Simple single-component quality: kg_per_cut on the ACTUAL line uses
        # act_count (defaults std_count), and ends = standards["ends"].
        ends = float(standards.get("ends", 0) or 0)
        kpc = kg_per_cut(ends, laid_length, act_count)
    # kg_per_beam uses the STANDARD cuts/beam.
    kpb = kg_per_beam(kpc, std_cuts_per_beam)
    apk = act_prod_kg(kpc, act_cuts, no_of_beam)

    return {
        "yards_per_beam": ypb,
        "kg_per_cut": kpc,
        "kg_per_beam": kpb,
        "p100prod": p100,
        "std_prod": sprod,
        "target_prod": tprod,
        "act_prod_yards": apy,
        "act_prod_kg": apk,
        "act_eff": aeff,
        # SURFACE speeds (yd/min) = rpm × dia × π / 36 — these supersede the raw
        # RPMs that arrived in standards. std_speed feeds p100prod.
        "std_speed": std_surface,
        "target_speed": target_surface,
        "act_speed": act_surface,
    }
