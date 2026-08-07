"""Business rules for spinning / doff production — single source of truth.

The frontend mirrors these computations for live preview only; the server
values are authoritative and recomputed on every create/edit/save.

Unit caution: the production constants baked into ``p100_x`` (14400, 2.2046,
36) encode the legacy unit conversions (count system, lb<->kg, inches<->yards).
Do NOT "simplify" them — they reproduce the exact spreadsheet the mill audits
against. Change only with mill sign-off.
"""

from src.juteProduction.constants import (
    DOFF_NET_MIN,
    DOFF_NET_MAX,
    SPNG_PROD_C1,
    SPNG_PROD_C2,
    SPNG_PROD_C3,
)


def compute_tare(trolly_weight, busket_weight, bobbin_weight) -> float:
    """Doff tare = trolly + busket (sic) + bobbin weights."""
    return round(float(trolly_weight) + float(busket_weight) + float(bobbin_weight), 3)


def compute_net(gross, tare) -> float:
    """Net doff weight = gross - tare."""
    return round(float(gross) - float(tare), 3)


def validate_net(net) -> bool:
    """A single doff net weight must fall within [DOFF_NET_MIN, DOFF_NET_MAX]."""
    return DOFF_NET_MIN <= net <= DOFF_NET_MAX


def p100_x(speed, hrs_x, act_count, spindle, frames_x, tpi) -> float:
    """100%-efficiency production (kg) for one shift bucket.

    Returns 0.0 when frames_x or tpi is zero/falsy (avoids div-by-zero).
    """
    if not frames_x or not tpi:
        return 0.0
    return round((speed * hrs_x * 60 * act_count * spindle * frames_x) / (tpi * 14400 * 2.2046 * 36), 2)


def compute_spinning_daily(
    *,
    speed,
    tpi,
    spindle,
    act_count,
    tar_eff,
    frames_a,
    frames_b,
    frames_c,
    prod_a,
    prod_b,
    prod_c,
    hrs_a,
    hrs_b,
    hrs_c,
    winders,
):
    """Roll up the per-shift spinning daily snapshot and efficiency outputs."""
    p100a = p100_x(speed, hrs_a, act_count, spindle, frames_a, tpi)
    p100b = p100_x(speed, hrs_b, act_count, spindle, frames_b, tpi)
    p100c = p100_x(speed, hrs_c, act_count, spindle, frames_c, tpi)
    p100 = round(p100a + p100b + p100c, 2)
    totprd = prod_a + prod_b + prod_c
    totmc = frames_a + frames_b + frames_c
    return {
        "p100a": p100a,
        "p100b": p100b,
        "p100c": p100c,
        "tar_prd": p100,
        "hunprod": round(p100 * tar_eff / 10000, 0) * 100,
        "act_eff": round(totprd / p100 * 100, 2) if p100 else 0.0,
        "eff_a": round(prod_a / p100a * 100, 2) if p100a else 0.0,
        "eff_b": round(prod_b / p100b * 100, 2) if p100b else 0.0,
        "eff_c": round(prod_c / p100c * 100, 2) if p100c else 0.0,
        "totmc": totmc,
        "totprd": totprd,
        "tarprd_frm": round(p100 / totmc, 0) if totmc else 0.0,
        "prd_frm": round(totprd / totmc, 0) if totmc else 0.0,
        "prd_wnd": round(totprd / winders, 0) if winders else 0.0,
    }


# =============================================================================
# Spinning planning refactor — per-frame-per-spell production rules
# =============================================================================


def p100_prod_spell(std_speed, minutes, act_count, spindles, std_tpi) -> float:
    """100%-efficiency production (kg) for ONE frame over ONE spell.

    p100prod = (std_speed * minutes * act_count * spindles)
               / (SPNG_PROD_C1 * SPNG_PROD_C2 * SPNG_PROD_C3 * std_tpi)
    rounded to 0 decimals. Returns 0.0 when std_tpi or spindles is zero/falsy
    (avoids div-by-zero / meaningless zero-spindle frames).

    Worked examples (doc §3): speed=4000, minutes=300, act_count=12.5,
    spindles=120, tpi=4 -> 394 ; same with speed=100... (see tests).
    """
    if not std_tpi or not spindles:
        return 0.0
    numer = float(std_speed) * float(minutes) * float(act_count) * float(spindles)
    denom = SPNG_PROD_C1 * SPNG_PROD_C2 * SPNG_PROD_C3 * float(std_tpi)
    return round(numer / denom, 0)


def allocate_winding(rows, winding_total) -> list:
    """Allocate a winding total W across rows in proportion to their doff.

    Group = (yarn_quality_id, date, shift_bucket). Within the group::

        doff_share(row) = act_prod_doff(row) / SUM(act_prod_doff over rows)
        act_prod_wind(row) = round(W * doff_share, 3)

    Returns a NEW list of shallow-copied row dicts (inputs are not mutated),
    each carrying an added/overwritten ``act_prod_wind`` key. When the doff
    denominator is zero every allocation is 0.0. Shares sum to 1 so the
    allocations sum back to W (within rounding).
    """
    W = float(winding_total)
    denom = sum(float(r.get("act_prod_doff", 0.0) or 0.0) for r in rows)
    out = []
    for r in rows:
        new_row = dict(r)
        if denom:
            doff = float(r.get("act_prod_doff", 0.0) or 0.0)
            new_row["act_prod_wind"] = round(W * doff / denom, 3)
        else:
            new_row["act_prod_wind"] = 0.0
        out.append(new_row)
    return out
