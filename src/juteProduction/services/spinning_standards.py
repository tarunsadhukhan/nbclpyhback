"""Last-date / aggregate resolvers for the spinning planning refactor.

These helpers resolve the time-versioned standards/targets and the SQC actuals
that feed the per-frame-per-spell planning grid (doc 2.5 / 6.1 / 6.2). They are
pure data-access functions: each accepts an open SQLAlchemy ``Session`` and
returns plain floats so the formula layer (``spinning_rules.py``) stays
DB-agnostic.

Resolution rules:
  * resolve_param        -> jute_prod_spng_target_map row with MAX(effective_date)
                            <= on_date for (co_id, ref_id, id_type, value_role,
                            param, active=1). Std/target/actual speed, tpi and eff
                            all resolve through this (value_role discriminates).
  * resolve_act_count    -> AVG(observed_count) from jute_sqc_spinning_count for
                            (co_id, item_id, entry_date=on_date, active=1).
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
            FROM jute_prod_spng_target_map
            WHERE co_id = :co_id
              AND ref_id = :ref_id
              AND id_type = :id_type
              AND value_role = :value_role
              AND param = :param
              AND active = 1
              AND effective_date <= :on_date
            ORDER BY effective_date DESC
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


def resolve_act_count(db: Session, co_id: int, item_id: int, on_date) -> float:
    """Act Count = AVG(observed_count) for the yarn item on ``on_date``.

    Averages every active observation recorded for the (co_id, item_id,
    entry_date) tuple. Returns 0.0 when there are no observations.
    """
    row = db.execute(
        text(
            """
            SELECT AVG(observed_count) AS avg_count
            FROM jute_sqc_spinning_count
            WHERE co_id = :co_id
              AND item_id = :item_id
              AND entry_date = :on_date
              AND active = 1
            """
        ),
        {
            "co_id": int(co_id),
            "item_id": int(item_id),
            "on_date": on_date,
        },
    ).fetchone()
    if not row or row.avg_count is None:
        return 0.0
    return float(row.avg_count)
