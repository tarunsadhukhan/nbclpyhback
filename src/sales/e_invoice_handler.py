"""
E-Invoice Portal Integration Handler

This module provides the structure for future GST e-invoice portal integration.
Placeholders define the interface for:
- Portal API client (authentication, submission)
- Response parsing (extract IRN, Ack No., etc.)
- Error handling (submission status tracking)
- Audit trail logging (e_invoice_responses table)

Implementation deferred until portal API credentials and specifications are available.
"""


class EInvoicePortalClient:
    """GST e-invoice portal API client - structure only, implementation TBD."""
    pass


class EInvoiceResponseParser:
    """Parser for GST portal API responses - structure only, implementation TBD."""
    pass


def submit_invoice_to_portal(invoice_id: int, invoice_data: dict, db_session) -> dict:
    """
    Submit invoice to GST e-invoice portal.

    Args:
        invoice_id: Sales invoice ID
        invoice_data: Invoice details dict
        db_session: Database session

    Returns:
        dict with keys: success (bool), irn (str), ack_no (str), ack_date (str), qr_code (str), error (str)

    Implementation TBD - awaiting portal API credentials and spec.
    """
    raise NotImplementedError("E-invoice portal integration pending")
