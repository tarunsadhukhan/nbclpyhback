"""Last-date resolvers for the weaving planning grid.

Clone of ``beaming_standards.py`` for the Weaving section (CONTRACT §3). These
helpers resolve the time-versioned QUALITY-linked standard/target/actual params
that feed the per-loom-per-quality planning grid. They are pure data-access
functions: each accepts an open SQLAlchemy ``Session`` and returns plain floats
so the formula layer (``weaving_rules.py``) stays DB-agnostic.

Resolution rules:
  * resolve_param              -> jute_prod_weaving_target_map row with
                                  MAX(effective_date) <= on_date for
                                  (co_id, ref_id, id_type, value_role, param,
                                  active=1). Branch-agnostic.
  * resolve_quality_standards  -> the per-(machine, quality) bundle resolved through
                                  resolve_param across BOTH dimensions (LOCKED
                                  CONTRACT, mirroring beaming). Weaving is
                                  TWO-DIMENSIONAL:
                                    MACHINE-linked (id_type='mcid', ref_id=machine_id,
                                    a LOOM): speed -> standard/target/actual.
                                    QUALITY-linked (id_type='qid',
                                    ref_id=weaving_quality_id): picks -> standard;
                                    eff -> standard/target; actual picks come from
                                    vw_weaving_pick_act (resolve_act_picks), NOT the
                                    target map.
                                  plus the COALESCE eff_speed/eff_picks the rules +
                                  entry router consume.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.juteProduction.constants import WEAVING_ID_TYPE_MC, WEAVING_ID_TYPE_QLTY


def _f(x) -> float:
    """Coerce to float, treating None / '' as 0.0."""
    if x in (None, ""):
        return 0.0
    return float(x)


# =============================================================================
# Working hours — net of stoppage (moved here from weaving_rules when that module
# was slimmed to pure formulas, 2026-06-24). vw_weaving_daily computes this same
# net working_hours on read; these helpers remain only so the machine_standards
# prefill endpoint can resolve it as-of a date before any row is saved.
# =============================================================================


def spell_working_hours(db: Session, spell_id) -> float:
    """Gross ``spell_mst.working_hours`` for a spell_id (status = 1). 0.0 when unknown."""
    if not spell_id:
        return 0.0
    row = db.execute(
        text(
            """
            SELECT working_hours
            FROM spell_mst
            WHERE spell_id = :spell_id AND status = 1
            """
        ),
        {"spell_id": int(spell_id)},
    ).fetchone()
    return _f(row.working_hours) if row else 0.0


def stoppage_hours(db: Session, co_id, machine_id, tran_date, spell_id) -> float:
    """Σ active jute_prod_stoppage_hours for (co_id, machine_id, tran_date, spell_id).

    0.0 when no stoppage rows exist. Mirrors the correlated SUM inside vw_weaving_daily.
    """
    if not (co_id and machine_id and spell_id):
        return 0.0
    row = db.execute(
        text(
            """
            SELECT COALESCE(SUM(stoppage_hours), 0) AS idle_hours
            FROM jute_prod_stoppage_hours
            WHERE active = 1
              AND co_id = :co_id
              AND machine_id = :machine_id
              AND tran_date = :tran_date
              AND spell_id = :spell_id
            """
        ),
        {
            "co_id": int(co_id),
            "machine_id": int(machine_id),
            "tran_date": tran_date,
            "spell_id": int(spell_id),
        },
    ).fetchone()
    return _f(row.idle_hours) if row else 0.0


def net_working_hours(db: Session, co_id, machine_id, tran_date, spell_id) -> float:
    """Net working_hours = max(0, gross spell working_hours - Σ stoppage_hours)."""
    gross = spell_working_hours(db, spell_id)
    idle = stoppage_hours(db, co_id, machine_id, tran_date, spell_id)
    return max(0.0, gross - idle)


def resolve_param(
    db: Session,
    co_id: int,
    ref_id: int,
    id_type: str,
    value_role: str,
    param: str,
    on_date,
) -> float:
    """Last-date standard/target/actual value for one (ref, role, param) tuple.

    Picks the row with the greatest effective_date that is on or before
    ``on_date``. Returns 0.0 when no matching active row exists.
    """
    row = db.execute(
        text(
            """
            SELECT value
            FROM jute_prod_weaving_target_map
            WHERE co_id = :co_id
              AND ref_id = :ref_id
              AND id_type = :id_type
              AND value_role = :value_role
              AND param = :param
              AND active = 1
              AND effective_date <= :on_date
            ORDER BY effective_date DESC, weaving_target_map_id DESC
            LIMIT 1
            """
        ),
        {
            "co_id": int(co_id),
            "ref_id": int(ref_id),
            "id_type": id_type,
            "value_role": value_role,
            "param": param,
            "on_date": on_date,
        },
    ).fetchone()
    if not row or row.value is None:
        return 0.0
    return float(row.value)


def resolve_act_picks(
    db: Session, co_id: int, weaving_quality_id, on_date
) -> float:
    """Last-date measured average picks from the Weaving Pick-SQC view.

    Selects ``avg_picks`` from ``vw_weaving_pick_act`` for the row with the
    greatest entry_date that is on or before ``on_date`` for
    (co_id, weaving_quality_id). Returns 0.0 when ``weaving_quality_id`` is
    falsy, no matching row exists, or the value is NULL.
    """
    if not weaving_quality_id:
        return 0.0
    row = db.execute(
        text(
            """
            SELECT avg_picks
            FROM vw_weaving_pick_act
            WHERE co_id = :co_id
              AND weaving_quality_id = :weaving_quality_id
              AND entry_date <= :on_date
            ORDER BY entry_date DESC
            LIMIT 1
            """
        ),
        {
            "co_id": int(co_id),
            "weaving_quality_id": int(weaving_quality_id),
            "on_date": on_date,
        },
    ).fetchone()
    if not row or row.avg_picks is None:
        return 0.0
    return float(row.avg_picks)


def resolve_quality_standards(
    db: Session, co_id: int, machine_id, weaving_quality_id, on_date
) -> dict:
    """Per-(machine, quality) standard/target/actual bundle for one weaving row.

    Resolves each param from ``jute_prod_weaving_target_map`` across BOTH dimensions
    (LOCKED CONTRACT, mirroring beaming): the MACHINE-linked speed params key off
    ``id_type='mcid'`` (``ref_id=machine_id``, a LOOM), while the QUALITY-linked
    picks/eff params key off ``id_type='qid'`` (``ref_id=weaving_quality_id``):

      * std_speed   -> mcid / standard / speed (the loom standard speed)
      * act_speed   -> mcid / actual   / speed (Weaving SQC "Actual Speed" tab;
                       0.0 until entered)
      * std_picks   -> qid  / standard / picks
      * act_picks   -> vw_weaving_pick_act avg_picks (the Weaving Pick-SQC
                       measured average, NOT the target map; 0.0 until entered)
      * std_eff     -> qid  / standard / eff
      * target_eff  -> qid  / target   / eff

    The COALESCE'd effective values the rules/entry router consume:
      * eff_speed   = act_speed if > 0 else std_speed
      * eff_picks   = act_picks if > 0 else std_picks

    Each value is a LAST-DATE resolution (newest effective_date <= on_date),
    branch-agnostic, defaulting to 0.0 when absent. Either ``machine_id`` or
    ``weaving_quality_id`` may be None/0 (e.g. a prefill asking before a loom or
    quality is mapped) — the affected params then resolve to 0.0. The returned dict
    KEYS are unchanged so callers need no shape change.
    """
    mc_ref = int(machine_id) if machine_id else 0
    qid_ref = int(weaving_quality_id) if weaving_quality_id else 0

    std_speed = resolve_param(
        db, co_id, mc_ref, WEAVING_ID_TYPE_MC, "standard", "speed", on_date
    )
    act_speed = resolve_param(
        db, co_id, mc_ref, WEAVING_ID_TYPE_MC, "actual", "speed", on_date
    )
    std_picks = resolve_param(
        db, co_id, qid_ref, WEAVING_ID_TYPE_QLTY, "standard", "picks", on_date
    )
    act_picks = resolve_act_picks(db, co_id, weaving_quality_id, on_date)
    std_eff = resolve_param(
        db, co_id, qid_ref, WEAVING_ID_TYPE_QLTY, "standard", "eff", on_date
    )
    target_eff = resolve_param(
        db, co_id, qid_ref, WEAVING_ID_TYPE_QLTY, "target", "eff", on_date
    )

    # COALESCE: prefer the actual (SQC) value when present (> 0), else the standard.
    eff_speed = act_speed if act_speed else std_speed
    eff_picks = act_picks if act_picks else std_picks

    return {
        # --- QUALITY-linked (qid, ref_id = weaving_quality_id) ----------------
        "std_speed": std_speed,
        "act_speed": act_speed,
        "std_picks": std_picks,
        "act_picks": act_picks,
        "std_eff": std_eff,
        "target_eff": target_eff,
        # --- COALESCE'd effective values (consumed by the §3 formulas) --------
        "eff_speed": eff_speed,
        "eff_picks": eff_picks,
    }
