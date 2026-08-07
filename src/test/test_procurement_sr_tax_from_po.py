# src/test/test_procurement_sr_tax_from_po.py
"""
Regression tests: SR line-item GST must inherit tax % from the originating PO
(po_gst.tax_pct), NOT from item_mst.tax_percentage.

Bug: save_sr previously read tax from item_mst, so an SR could be taxed at the
current item-master rate even when its PO was raised at a different rate.
"""

from sqlalchemy import text

from src.procurement.query import get_inward_line_tax_pct_query


class TestInwardLineTaxQuery:
    """Unit tests for the PO-inheriting tax query used by save_sr."""

    def test_returns_text_object(self):
        assert isinstance(get_inward_line_tax_pct_query(), type(text("")))

    def test_sources_tax_from_po_gst(self):
        sql = str(get_inward_line_tax_pct_query())
        # Tax must come from the PO's GST line, keyed by po_dtl_id.
        assert "po_gst" in sql
        assert "po_dtl_id" in sql
        assert "tax_pct" in sql

    def test_only_active_po_gst_rows(self):
        sql = str(get_inward_line_tax_pct_query())
        assert "pg.active = 1" in sql

    def test_binds_inward_dtl_id(self):
        sql = str(get_inward_line_tax_pct_query())
        assert ":inward_dtl_id" in sql

    def test_falls_back_to_item_master_only_for_non_po_lines(self):
        """item_mst is referenced, but guarded by po_dtl_id IS NOT NULL CASE."""
        sql = str(get_inward_line_tax_pct_query())
        assert "po_dtl_id IS NOT NULL" in sql
        assert "item_mst" in sql
        # PO branch must reference the PO tax, not the item-master tax.
        po_branch = sql.split("ELSE")[0]
        assert "pg.tax_pct" in po_branch
        assert "tax_percentage" not in po_branch
