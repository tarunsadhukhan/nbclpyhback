"""
Shared jute bill-pass financial computations.

Owner decision (2026-07): jute bill-pass net_total MUST deduct TDS.
    net_pre   = total_amount - claim_amount - tds_amount
    roundoff  = round(net_pre) - net_pre          (makes net a whole rupee)
    net_total = net_pre + roundoff

Used by:
    - src/juteProcurement/mr.py        (final-approval amount calculation)
    - src/juteProcurement/billPass.py  (server-side recompute on bill-pass update)
    - src/accounting/posting_service.py (defensive recompute before posting)
"""


def compute_jute_totals(total_amount, claim_amount, tds_amount):
    """
    Compute (roundoff, net_total) for a jute MR / bill pass, deducting TDS.

    Args:
        total_amount: gross material value (sum of line values)
        claim_amount: total claims deducted from the supplier bill
        tds_amount: TDS deducted at source

    Returns:
        tuple (roundoff, net_total) — both rounded to 2 decimal places;
        net_total is always a whole rupee (roundoff absorbs the paise).
    """
    net_pre = round(
        float(total_amount or 0) - float(claim_amount or 0) - float(tds_amount or 0), 2
    )
    roundoff = round(round(net_pre) - net_pre, 2)
    net_total = round(net_pre + roundoff, 2)
    return roundoff, net_total
