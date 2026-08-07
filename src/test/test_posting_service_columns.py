# src/test/test_posting_service_columns.py
"""
Regression guard for src/accounting/posting_service.py.

The predecessor module (auto_post.py, now deleted) selected columns that do not
exist on the real source tables (pi.co_id, pid.taxable_amount, jm.mr_id,
si.net_amount, acc_fy_id, voucher_seq, debit_amount, ...). This test inspects
the source of each posting recipe and asserts:

  1. the known-bad column names never reappear, and
  2. the verified-real column names each recipe depends on are present.

Column-name truths (verified against src/models/):
  - proc_inward has NO co_id (derive via branch_mst); proc_inward_dtl has NO
    taxable_amount; proc_gst's detail FK is literally named `proc_inward_dtl`.
  - jute_mr PK is jute_mr_id, date is jute_mr_date, freight is `frieght_paid`
    (production typo — kept).
  - sales_invoice PK is invoice_id, total is invoice_amount, round-off is
    round_off; detail taxable is amount_without_tax; sales GST joins on
    invoice_line_item_id.
  - acc_voucher uses acc_financial_year_id (not acc_fy_id), no voucher_seq;
    acc_voucher_line uses dr_cr + amount (not debit_amount/credit_amount).
"""

import inspect

from src.accounting import posting_service
from src.models.procurement import ProcGst, ProcInward, ProcInwardDtl
from src.models.jute import JuteMr
from src.models.sales import InvoiceHdr, InvoiceLineItem


# Column names the old broken auto_post used — must never appear again.
KNOWN_BAD_NAMES = [
    "pi.co_id",            # proc_inward has no co_id
    "pid.taxable_amount",  # proc_inward_dtl has no taxable_amount
    "jm.co_id",            # jute_mr has no co_id
    "jm.mr_id",            # PK is jute_mr_id
    "jm.mr_date",          # date column is jute_mr_date
    "jm.mr_no",            # no such column (branch_mr_no / bill_pass_no exist)
    "si.co_id",            # sales_invoice has no co_id
    "si.net_amount",       # total is invoice_amount
    "si.round_off_value",  # round-off column is round_off
    "sales_invoice_id",    # PK is invoice_id
    "sid.taxable_amount",  # detail taxable is amount_without_tax
    "acc_fy_id",           # real FK is acc_financial_year_id
    "voucher_seq",         # no such column on acc_voucher
    "debit_amount",        # acc_voucher_line uses dr_cr + amount
    "credit_amount",       # acc_voucher_line uses dr_cr + amount
]


def _whole_module_source():
    return inspect.getsource(posting_service)


def _recipe_sources():
    return {
        "proc_billpass": inspect.getsource(posting_service._recipe_proc_billpass),
        "drcr_note": inspect.getsource(posting_service._recipe_drcr_note),
        "jute_billpass": inspect.getsource(posting_service._recipe_jute_billpass),
        "sales_invoice": inspect.getsource(posting_service._recipe_sales_invoice),
    }


class TestNoKnownBadColumnNames:
    def test_module_has_no_known_bad_column_names(self):
        src = _whole_module_source()
        for bad in KNOWN_BAD_NAMES:
            assert bad not in src, (
                f"posting_service references '{bad}' — this column does not exist "
                "on the real schema (see src/models/)"
            )

    def test_each_recipe_has_no_known_bad_column_names(self):
        for name, src in _recipe_sources().items():
            for bad in KNOWN_BAD_NAMES:
                assert bad not in src, f"recipe {name} references bad column '{bad}'"


class TestRequiredRealColumnNames:
    def test_proc_recipe_uses_real_columns(self):
        src = _recipe_sources()["proc_billpass"]
        # co_id derived via branch join, GST via the oddly-named FK columns
        assert "bm.co_id" in src
        assert "pg.c_tax_amount" in src
        assert "pg.s_tax_amount" in src
        assert "pg.i_tax_amount" in src
        assert "pg.proc_inward_dtl" in src
        assert "pg.proc_inward_additional_id" in src
        assert "pid.approved_qty" in src
        assert "pid.accepted_rate" in src
        assert "round_off_value" in src  # real column on proc_inward
        assert "invoice_due_date" in src
        assert "credit_days" in src      # PO chain for due-date rule

    def test_drcr_recipe_uses_real_columns(self):
        src = _recipe_sources()["drcr_note"]
        assert "debit_credit_note_id" in src  # real PK (not drcr_note_id)
        assert "dn.adjustment_type" in src
        assert "dn.net_amount" in src
        assert "dng.cgst_amount" in src       # drcr_note_dtl_gst naming
        assert "dng.sgst_amount" in src
        assert "dng.igst_amount" in src

    def test_jute_recipe_uses_real_columns(self):
        src = _recipe_sources()["jute_billpass"]
        assert "jute_mr_id" in src
        assert "jm.jute_mr_date" in src
        assert "jm.frieght_paid" in src   # production typo — kept deliberately
        assert "jm.total_amount" in src
        assert "jm.tds_amount" in src
        assert "jm.claim_amount" in src
        assert "CAST(jm.party_id AS UNSIGNED)" in src  # party_id is VARCHAR
        assert "payment_due_date" in src
        assert "credit_term" in src       # jute_po credit days column

    def test_sales_recipe_uses_real_columns(self):
        src = _recipe_sources()["sales_invoice"]
        assert "invoice_id" in src
        assert "invoice_amount" in src
        assert "amount_without_tax" in src
        assert "si.round_off" in src
        assert "invoice_line_item_id" in src       # sales GST join key
        assert "sales_invoice_additional_gst" in src
        assert "sales_invoice_jute" in src         # claim source
        assert "payment_terms" in src

    def test_voucher_writer_uses_orm_dialect_columns(self):
        src = inspect.getsource(posting_service._write_voucher)
        assert "acc_financial_year_id" in src
        assert "dr_cr" in src
        assert "source_line_type" in src
        assert "is_auto_posted" in src


class TestModelsStillMatchAssumptions:
    """If any of these fail, the recipes must be re-verified against the ORM."""

    def test_proc_models(self):
        inward_cols = {c.name for c in ProcInward.__table__.columns}
        assert "co_id" not in inward_cols
        for required in ("supplier_id", "invoice_no", "invoice_date",
                         "invoice_due_date", "round_off_value", "branch_id",
                         "billpass_status", "sr_no"):
            assert required in inward_cols

        dtl_cols = {c.name for c in ProcInwardDtl.__table__.columns}
        assert "taxable_amount" not in dtl_cols
        for required in ("approved_qty", "accepted_rate", "rate",
                         "discount_amount", "amount", "po_dtl_id"):
            assert required in dtl_cols

        gst_cols = {c.name for c in ProcGst.__table__.columns}
        for required in ("c_tax_amount", "s_tax_amount", "i_tax_amount",
                         "proc_inward_dtl", "proc_inward_additional_id", "active"):
            assert required in gst_cols
        for absent in ("cgst_amount", "sgst_amount", "igst_amount", "inward_dtl_id"):
            assert absent not in gst_cols

    def test_jute_mr_model(self):
        cols = {c.name for c in JuteMr.__table__.columns}
        for absent in ("co_id", "mr_id", "mr_date", "mr_no"):
            assert absent not in cols
        for required in ("jute_mr_id", "jute_mr_date", "frieght_paid",
                         "total_amount", "claim_amount", "tds_amount",
                         "roundoff", "net_total", "bill_pass_complete",
                         "payment_due_date", "po_id", "party_id"):
            assert required in cols

    def test_sales_invoice_models(self):
        hdr_cols = {c.name for c in InvoiceHdr.__table__.columns}
        for absent in ("co_id", "net_amount", "round_off_value", "sales_invoice_id"):
            assert absent not in hdr_cols
        for required in ("invoice_id", "invoice_no", "invoice_amount",
                         "round_off", "due_date", "payment_terms", "party_id",
                         "branch_id"):
            assert required in hdr_cols

        dtl_cols = {c.name for c in InvoiceLineItem.__table__.columns}
        assert "taxable_amount" not in dtl_cols
        for required in ("invoice_line_item_id", "amount_without_tax",
                         "invoice_id", "item_id"):
            assert required in dtl_cols


class TestPublicContract:
    def test_post_document_signature_is_frozen(self):
        sig = inspect.signature(posting_service.post_document)
        assert list(sig.parameters) == ["db", "source_doc_type", "source_doc_id", "user_id"]

    def test_post_document_never_raises_on_garbage_input(self):
        # No DB needed: an unparseable source_doc_id must return FAILED, not raise.
        result = posting_service.post_document(None, "PROC_BILLPASS", "not-an-int", 1)
        assert result["status"] == "FAILED"
        assert result["acc_voucher_id"] is None
        assert "message" in result


class TestJuteTotalsHelper:
    """Owner decision 2: jute net_total must deduct TDS."""

    def test_tds_is_deducted(self):
        from src.juteProcurement.totals import compute_jute_totals
        roundoff, net_total = compute_jute_totals(100000.00, 2500.50, 97.50)
        # net_pre = 100000 - 2500.50 - 97.50 = 97402.00 -> whole rupee already
        assert roundoff == 0.0
        assert net_total == 97402.00

    def test_roundoff_makes_whole_rupee(self):
        from src.juteProcurement.totals import compute_jute_totals
        roundoff, net_total = compute_jute_totals(1000.75, 100.25, 50.10)
        # net_pre = 850.40 -> rounds to 850, roundoff = -0.40
        assert roundoff == -0.40
        assert net_total == 850.00
        assert net_total == round(net_total)

    def test_none_inputs_are_zero(self):
        from src.juteProcurement.totals import compute_jute_totals
        roundoff, net_total = compute_jute_totals(None, None, None)
        assert roundoff == 0.0
        assert net_total == 0.0
