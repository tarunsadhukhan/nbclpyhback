"""
Tests for Jute MR and Bill Pass number formatters.
Tests the Python formatting functions and SQL expression generators.
"""

import pytest
from datetime import date

from src.juteProcurement.formatters import (
    format_jute_mr_number,
    format_jute_bill_pass_number,
    get_jute_mr_number_sql_expression,
    get_jute_bill_pass_number_sql_expression,
)


class TestFormatJuteMRNumber:
    """Tests for format_jute_mr_number()."""

    def test_with_all_prefixes(self):
        result = format_jute_mr_number(1, date(2025, 5, 15), "ABC", "FAC")
        assert result == "ABC/FAC/JMR/25-26/00001"

    def test_fy_before_april(self):
        result = format_jute_mr_number(42, date(2025, 2, 10), "ABC", "FAC")
        assert result == "ABC/FAC/JMR/24-25/00042"

    def test_fy_april_boundary(self):
        result = format_jute_mr_number(1, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JMR/25-26/00001"

    def test_fy_march_boundary(self):
        result = format_jute_mr_number(1, date(2025, 3, 31), "X", "Y")
        assert result == "X/Y/JMR/24-25/00001"

    def test_without_prefixes(self):
        result = format_jute_mr_number(123, date(2025, 5, 15))
        assert result == "JMR/25-26/00123"

    def test_with_only_co_prefix(self):
        result = format_jute_mr_number(5, date(2025, 6, 1), "ABC")
        assert result == "ABC/JMR/25-26/00005"

    def test_with_only_branch_prefix(self):
        result = format_jute_mr_number(5, date(2025, 6, 1), branch_prefix="FAC")
        assert result == "FAC/JMR/25-26/00005"

    def test_zero_padded(self):
        result = format_jute_mr_number(7, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JMR/25-26/00007"

    def test_large_number(self):
        result = format_jute_mr_number(99999, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JMR/25-26/99999"

    def test_number_exceeding_5_digits(self):
        result = format_jute_mr_number(100001, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JMR/25-26/100001"


class TestFormatJuteBillPassNumber:
    """Tests for format_jute_bill_pass_number()."""

    def test_with_all_prefixes(self):
        result = format_jute_bill_pass_number(1, date(2025, 5, 15), "ABC", "FAC")
        assert result == "ABC/FAC/JBP/25-26/00001"

    def test_fy_before_april(self):
        result = format_jute_bill_pass_number(42, date(2025, 2, 10), "ABC", "FAC")
        assert result == "ABC/FAC/JBP/24-25/00042"

    def test_fy_april_boundary(self):
        result = format_jute_bill_pass_number(1, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JBP/25-26/00001"

    def test_without_prefixes(self):
        result = format_jute_bill_pass_number(123, date(2025, 5, 15))
        assert result == "JBP/25-26/00123"

    def test_with_only_co_prefix(self):
        result = format_jute_bill_pass_number(5, date(2025, 6, 1), "ABC")
        assert result == "ABC/JBP/25-26/00005"

    def test_zero_padded(self):
        result = format_jute_bill_pass_number(7, date(2025, 4, 1), "X", "Y")
        assert result == "X/Y/JBP/25-26/00007"


class TestJuteMRNumberSQLExpression:
    """Tests for get_jute_mr_number_sql_expression()."""

    def test_returns_string(self):
        expr = get_jute_mr_number_sql_expression()
        assert isinstance(expr, str)

    def test_contains_jmr_prefix(self):
        expr = get_jute_mr_number_sql_expression()
        assert "'JMR/'" in expr

    def test_contains_concat(self):
        expr = get_jute_mr_number_sql_expression()
        assert "CONCAT" in expr

    def test_contains_lpad(self):
        expr = get_jute_mr_number_sql_expression()
        assert "LPAD" in expr

    def test_uses_default_columns(self):
        expr = get_jute_mr_number_sql_expression()
        assert "jm.branch_mr_no" in expr
        assert "jm.jute_mr_date" in expr
        assert "cm.co_prefix" in expr
        assert "bm.branch_prefix" in expr

    def test_custom_columns(self):
        expr = get_jute_mr_number_sql_expression(
            mr_no_column="vso.branch_mr_no",
            mr_date_column="jm2.jute_mr_date",
            co_prefix_column="cm2.co_prefix",
            branch_prefix_column="bm2.branch_prefix",
        )
        assert "vso.branch_mr_no" in expr
        assert "jm2.jute_mr_date" in expr
        assert "cm2.co_prefix" in expr
        assert "bm2.branch_prefix" in expr


class TestJuteBillPassNumberSQLExpression:
    """Tests for get_jute_bill_pass_number_sql_expression()."""

    def test_returns_string(self):
        expr = get_jute_bill_pass_number_sql_expression()
        assert isinstance(expr, str)

    def test_contains_jbp_prefix(self):
        expr = get_jute_bill_pass_number_sql_expression()
        assert "'JBP/'" in expr

    def test_contains_concat(self):
        expr = get_jute_bill_pass_number_sql_expression()
        assert "CONCAT" in expr

    def test_uses_default_columns(self):
        expr = get_jute_bill_pass_number_sql_expression()
        assert "jm.bill_pass_no" in expr
        assert "jm.bill_pass_date" in expr
        assert "cm.co_prefix" in expr
        assert "bm.branch_prefix" in expr
