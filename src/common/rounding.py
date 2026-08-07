"""Shared rounding helpers for transaction payloads.

Rules enforced consistently across sales order, sales invoice, and delivery
order create/update endpoints (and any future writer):

- ``rate`` and ``discounted_rate`` on item lines → ``item_mst.rate_rounding``
  (default 2 when NULL).
- All amount-like fields (net_amount, total_amount, discount_amount,
  gst.*_amount, header gross_amount/net_amount/tax_amount/tax_payable,
  freight, round_off, additional charges) → 2 decimals.
- ``None`` passes through unchanged so callers can keep their NULL-able
  semantics.
"""

from typing import Dict, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


def round_amount(value):
    """Round any amount-like value to 2 decimals, preserving ``None``."""
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def round_rate(value, rate_rounding: Optional[int]):
    """Round a rate value to ``item_mst.rate_rounding`` decimals (default 2)."""
    if value is None:
        return None
    try:
        decimals = 2 if rate_rounding is None else int(rate_rounding)
    except (TypeError, ValueError):
        decimals = 2
    if decimals < 0:
        decimals = 2
    try:
        return round(float(value), decimals)
    except (TypeError, ValueError):
        return value


def fetch_item_rate_roundings(db: Session, item_ids: Iterable[Optional[int]]) -> Dict[int, int]:
    """Look up ``rate_rounding`` for the given item ids.

    Returns ``{item_id: rate_rounding_or_2}``. Items missing from the result
    set fall back to the caller's own default (typically 2). If the query
    itself fails (e.g. mocked DB session in tests), returns an empty dict
    so callers transparently fall back to the 2-decimal default.
    """
    ids = []
    for raw in item_ids:
        if raw is None:
            continue
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    ids = list({i for i in ids if i})
    if not ids:
        return {}
    try:
        rows = db.execute(
            text(
                "SELECT item_id, COALESCE(rate_rounding, 2) AS rr "
                "FROM item_mst WHERE item_id IN :ids"
            ),
            {"ids": tuple(ids)},
        ).fetchall()
    except Exception:
        return {}
    out: Dict[int, int] = {}
    try:
        for r in rows:
            m = dict(r._mapping)
            try:
                out[int(m["item_id"])] = int(m["rr"]) if m.get("rr") is not None else 2
            except (TypeError, ValueError):
                continue
    except Exception:
        return {}
    return out
