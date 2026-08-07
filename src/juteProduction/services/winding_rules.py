"""Business rules for winding production — single source of truth.

Pure functions, no DB. The frontend (``utils/windingCalc.ts``) mirrors these
computations for live preview only; the server values are authoritative and are
recomputed on every doff create/edit and at reconciliation (read) time.

Provenance: legacy CodeIgniter ``winding_doff_data.php`` (net) and
``view_winding_all_data`` (daily reconciliation). Per
``docs/winding-person-keyed-entry-spec.md`` §5 (decision D4) there is no MACHINE
split and no ``no_of_machines``, so the old ``compute_winding_net_per_mc`` is
gone. One weighing may still be shared by several WINDERS: ``compute_winding_net``
deducts the tare exactly once and ``doff_create`` divides that net equally into
one row per person, gating each person's share against
[WINDING_NET_MIN, WINDING_NET_MAX].
"""

from src.juteProduction.constants import WINDING_NET_MAX, WINDING_NET_MIN


def compute_winding_net(grosswt, trollywt, spoolwt) -> float:
    """Net weight of one weighing (kg).

        net = grosswt - trollywt - spoolwt

    May be <= 0 (e.g. trolly/spool tare exceeds gross). This is the SAVE GATE
    value: the caller must reject the doff when ``net <= 0`` (status 400). This
    function deliberately does NOT clamp — gating is the router's job.
    """
    return round(float(grosswt) - float(trollywt) - float(spoolwt), 3)


def compute_winding_row_gross_wt(net, trollywt, spoolwt) -> float:
    """Stored per-row gross weight.

        row_gross_wt = net + trollywt + spoolwt

    (Legacy ``gross_wt`` column; distinct from ``gross_input_wt`` which is the
    weighed gross as entered.)
    """
    return round(float(net) + float(trollywt) + float(spoolwt), 3)


def validate_winding_net(net) -> bool:
    """A doff net weight must fall within [WINDING_NET_MIN, WINDING_NET_MAX]."""
    return WINDING_NET_MIN <= net <= WINDING_NET_MAX


def reconcile_production(sum_production, opening, closing) -> float:
    """Daily reconciled production (kg) per person/spell/quality.

        production_kg = SUM(doff.production_qty) - opening_jugar + closing_jugar

    Subtracting the opening jugar and adding the closing jugar converts "weight
    doffed this shift" into "weight actually produced this shift" net of the
    spindle carryover (yarn started but not yet doffed). Computed at READ time
    only — never persisted (per the locked design). Result stays in KG; the
    BUNDLE_KG (14) divisor is intentionally NOT applied here.
    """
    return round(float(sum_production) - float(opening) + float(closing), 3)
