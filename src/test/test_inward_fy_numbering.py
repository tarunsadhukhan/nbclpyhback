"""
Tests for FY-aware inward number minting.

create_inward computes fy_start_date / fy_end_date from inward_date
(April 1 -> March 31 Indian FY) and mints
next_inward_no = COALESCE(MAX(inward_sequence_no),0)+1 scoped to that
(branch_id, FY) window via get_max_inward_no_for_branch_fy().

These tests guard the SQL shape of that query (the regression that caused
inward_sequence_no to be stamped with the global inward_id instead of a
per-branch per-FY sequence). They mirror the SQL-shape guards in
test_jute_po_fy_numbering.py.
"""
from src.procurement.query import get_max_inward_no_for_branch_fy


def _normalised_sql() -> str:
    """Return whitespace-normalised SQL text of the FY-scoped MAX query."""
    query = get_max_inward_no_for_branch_fy()
    return " ".join(str(query.text).split())


class TestGetMaxInwardNoForBranchFyQuery:
    """The MAX(inward_sequence_no) query must scope by branch_id AND FY window."""

    def test_query_returns_text_object(self):
        query = get_max_inward_no_for_branch_fy()
        # SQLAlchemy TextClause exposes a .text attribute with the SQL string.
        assert hasattr(query, "text")
        assert "SELECT" in str(query.text).upper()

    def test_sql_scopes_by_branch_id(self):
        assert "branch_id = :branch_id" in _normalised_sql(), (
            "MAX(inward_sequence_no) query must scope by branch_id"
        )

    def test_sql_filters_by_fy_date_window(self):
        sql = _normalised_sql()
        assert "inward_date >= :fy_start_date" in sql, (
            "query must include FY lower bound on inward_date"
        )
        assert "inward_date <= :fy_end_date" in sql, (
            "query must include FY upper bound on inward_date"
        )

    def test_sql_uses_coalesce_max_and_numeric_guard(self):
        sql = _normalised_sql().upper()
        # COALESCE(MAX(...),0) so an empty branch/FY bucket yields 0 -> seq 1.
        assert "COALESCE(MAX(" in sql
        assert ", 0)" in sql or ",0)" in sql
        # Numeric guard mirrors the PO query so non-numeric values can't poison MAX.
        assert "CAST(" in sql and "UNSIGNED" in sql
        assert "REGEXP" in sql

    def test_sql_targets_proc_inward_sequence_column(self):
        sql = _normalised_sql()
        # Must MAX the per-branch-FY counter column, never the global inward_id.
        assert "inward_sequence_no" in sql
        assert "proc_inward" in sql
        assert "MAX(CAST(pi.inward_sequence_no" in sql.replace("  ", " ")
