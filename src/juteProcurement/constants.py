"""
Jute Procurement module constants - single source of truth for jute MR status IDs.

Status code reference (verified against src/models/jute.py:737 and
src/juteProcurement/mr.py:628-634):
    21 -> Draft
    1  -> Open
    13 -> Pending / Finalised (terminal state on MR screen, handed off to external system)
    20 -> Pending Approval
    3  -> Approved
    4  -> Rejected
    6  -> Cancelled

The `vw_jute_stock_outstanding` view filters MRs by `status_id IN (3, 13)` to
include both Approved and Finalised MRs as issuable stock. Downstream reports
that need "approved-or-finalised" MRs must use the same tuple to stay
consistent with the view.
"""

# MRs visible as approved-or-finalised stock (matches vw_jute_stock_outstanding).
JUTE_MR_APPROVED_STATUSES = (3, 13)

# 194Q annual TDS threshold per supplier (INR). TDS deducts at 0.1% above this.
TDS_CAP_INR = 5_000_000
