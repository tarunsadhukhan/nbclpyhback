from src.models.enquiry import SalesEnquiryDtl
from src.bomcosting.bomCosting import compute_base_total


def test_enquiry_dtl_has_pricing_columns():
    cols = SalesEnquiryDtl.__table__.columns.keys()
    assert "overhead_pct" in cols
    assert "margin_pct" in cols


def test_base_total_excludes_overhead():
    # material 100, conversion 40 -> base 140 (overhead entered separately, never summed)
    assert compute_base_total(100.0, 40.0) == 140.0
    assert compute_base_total(0.0, 0.0) == 0.0


from src.sales.enquiry_query import get_enquiry_dtl_by_id_query, get_enquiry_board_query


def test_line_query_exposes_sell_price():
    sql = str(get_enquiry_dtl_by_id_query())
    assert "overhead_pct" in sql and "margin_pct" in sql
    assert "sell_price_per_unit" in sql


def test_board_query_exposes_costed_count():
    assert "costed_line_count" in str(get_enquiry_board_query())


from src.sales.enquiry_query import get_enquiry_costing_pending_query


def test_costing_pending_query_flags_unpriced():
    sql = str(get_enquiry_costing_pending_query())
    assert "overhead_pct IS NULL" in sql and "margin_pct IS NULL" in sql
    assert "item_id IS NULL" in sql


def test_quotation_prefill_carries_pcts():
    from src.sales.query import get_enquiry_lines_for_sales_doc_query
    sql = str(get_enquiry_lines_for_sales_doc_query())
    assert "overhead_pct" in sql and "margin_pct" in sql
