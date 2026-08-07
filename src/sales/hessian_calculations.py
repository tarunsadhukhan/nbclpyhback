"""
Shared Hessian (invoice_type_id = 2) computation utilities for Sales Invoice.

MIRROR CONTRACT: keep in lockstep with
`vowerp3ui/src/utils/hessianCalculations.ts`. Any change to formulas or
rounding here MUST be applied there too.

Brokerage intentionally omitted for the invoice flow — the stored rate IS
the billing rate (as received from the frontend / inherited from the linked
sales order). Brokerage was applied upstream (Sales Order) and is not
recomputed on the invoice side.
"""
from typing import Optional, TypedDict


class HessianFields(TypedDict):
    qty_mt: float
    rate_per_bale: float
    billing_rate_mt: float
    billing_rate_bale: float


def compute_hessian_fields(
    qty_bales: float,
    rate_mt: float,
    conv_factor: float,
    qty_rounding: int = 3,
) -> HessianFields:
    """Derive all Hessian line values from the three user inputs.

    :param qty_bales:    User-entered quantity in bales.
    :param rate_mt:      Rate per MT (= billing rate; no brokerage applied here).
    :param conv_factor:  Bales per MT from uom_item_map_mst.relation_value.
    :param qty_rounding: Decimals for qty_mt (default 3; uses
                         uom_item_map_mst.rounding when callers pass it).
    """
    qty_mt = qty_bales / conv_factor if conv_factor > 0 else 0.0
    rate_per_bale = rate_mt / conv_factor if conv_factor > 0 else 0.0
    return {
        "qty_mt": round(qty_mt, qty_rounding),
        "rate_per_bale": round(rate_per_bale, 2),
        "billing_rate_mt": round(rate_mt, 2),
        "billing_rate_bale": round(rate_per_bale, 2),
    }


def resolve_qty_rounding(recorded_rounding: Optional[int], default: int = 3) -> int:
    """Use uom_item_map_mst.rounding when populated; else fall back to default (3)."""
    return recorded_rounding if recorded_rounding is not None else default
