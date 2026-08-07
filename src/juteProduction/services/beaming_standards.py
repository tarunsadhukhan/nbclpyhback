"""Last-date resolvers for the beaming planning grid.

Mirrors ``spinning_standards.py`` for the Beaming section (SPEC §B.6 / §2).
These helpers resolve the time-versioned machine-linked standard/target params
that feed the per-machine-per-quality planning grid. They are pure data-access
functions: each accepts an open SQLAlchemy ``Session`` and returns plain floats
so the formula layer (``beaming_rules.py``) stays DB-agnostic.

Resolution rules:
  * resolve_param              -> jute_prod_beaming_target_map row with
                                  MAX(effective_date) <= on_date for
                                  (co_id, ref_id, id_type, value_role, param,
                                  active=1). Branch-agnostic.
  * resolve_machine_standards  -> the per-(machine, quality) bundle resolved
                                  through resolve_param across BOTH dimensions
                                  (LOCKED CONTRACT): the MACHINE-linked params
                                  (speed/dia) key off id_type='mcid'
                                  (ref_id=machine_id), while the QUALITY-linked
                                  params (laid_length/cuts_per_beam/eff) key off
                                  id_type='qid' (ref_id=bm_quality_id).
"""

from sqlalchemy import text
from sqlalchemy.orm import Session


def resolve_param(
    db: Session,
    co_id: int,
    ref_id: int,
    id_type: str,
    value_role: str,
    param: str,
    on_date,
) -> float:
    """Last-date standard/target value for one (ref, role, param) tuple.

    Picks the row with the greatest effective_date that is on or before
    ``on_date``. Returns 0.0 when no matching active row exists.
    """
    row = db.execute(
        text(
            """
            SELECT value
            FROM jute_prod_beaming_target_map
            WHERE co_id = :co_id
              AND ref_id = :ref_id
              AND id_type = :id_type
              AND value_role = :value_role
              AND param = :param
              AND active = 1
              AND effective_date <= :on_date
            ORDER BY effective_date DESC, beaming_target_map_id DESC
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


def resolve_machine_standards(
    db: Session, co_id: int, machine_id: int, bm_quality_id, on_date
) -> dict:
    """Per-(machine, quality) standard/target bundle for one beaming row.

    Resolves each param from ``jute_prod_beaming_target_map`` across BOTH dimensions
    (LOCKED CONTRACT): QUALITY-linked params key off ``id_type='qid'``
    (``ref_id=bm_quality_id``); MACHINE-linked params key off ``id_type='mcid'``
    (``ref_id=machine_id``):
      * laid_length     -> qid  / standard / laid_length
      * cuts_per_beam   -> qid  / standard / cuts_per_beam (std cuts/beam)
      * std_eff         -> qid  / standard / eff
      * target_eff      -> qid  / target   / eff
      * std_speed       -> mcid / standard / speed
      * target_speed    -> mcid / target   / speed
      * act_rpm         -> mcid / actual   / speed
      * dia             -> mcid / standard / dia (roller diameter)

    Each value is a LAST-DATE resolution (newest effective_date <= on_date),
    branch-agnostic, defaulting to 0.0 when absent. The returned KEYS are unchanged
    (laid_length, cuts_per_beam, std_speed, target_speed, std_eff, target_eff, dia,
    act_rpm) so the entry/compute callers need no shape change — only the linkage of
    where each value is read from. ``bm_quality_id`` may be None/0 (e.g. the prefill
    endpoint asking for machine-only params) — the qid params then resolve to 0.0.

    SPEED MODEL (locked contract): the resolved 'speed' params are RPMs
    (rotations/min), NOT surface speeds. So ``std_speed`` and ``target_speed``
    here are RPM values, and ``act_rpm`` is the actual RPM resolved from
    value_role='actual' (entered via the Beaming SQC page; 0.0 until entered).
    Surface speed (yd/min) = rpm × dia × π / 36 is computed downstream in
    ``beaming_rules`` (use ``beaming_rules.act_speed(rpm, dia)`` for the
    std / target / actual surface speeds). ``act_rpm`` = mcid / actual / speed.
    """
    qid_ref = int(bm_quality_id) if bm_quality_id else 0
    return {
        # --- QUALITY-linked (qid, ref_id = bm_quality_id) --------------------
        "laid_length": resolve_param(
            db, co_id, qid_ref, "qid", "standard", "laid_length", on_date
        ),
        "cuts_per_beam": resolve_param(
            db, co_id, qid_ref, "qid", "standard", "cuts_per_beam", on_date
        ),
        "std_eff": resolve_param(
            db, co_id, qid_ref, "qid", "standard", "eff", on_date
        ),
        "target_eff": resolve_param(
            db, co_id, qid_ref, "qid", "target", "eff", on_date
        ),
        # --- MACHINE-linked (mcid, ref_id = machine_id) ----------------------
        "std_speed": resolve_param(
            db, co_id, machine_id, "mcid", "standard", "speed", on_date
        ),
        "target_speed": resolve_param(
            db, co_id, machine_id, "mcid", "target", "speed", on_date
        ),
        "act_rpm": resolve_param(
            db, co_id, machine_id, "mcid", "actual", "speed", on_date
        ),
        "dia": resolve_param(
            db, co_id, machine_id, "mcid", "standard", "dia", on_date
        ),
    }
