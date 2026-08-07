"""
Regression tests for get_item_group_drodown() in src/masters/query.py.

The item_grp_mst.active column is VARCHAR(255) storing 'Y'/'N'/'1'/'0'/NULL.
Comparing it as `active = 1` (integer) causes MySQL error 1292:
  "Truncated incorrect DOUBLE value: 'Y'"

These tests ensure the query uses string-based comparison for the active column.
"""
import pytest
from sqlalchemy import text
from src.masters.query import get_item_group_drodown


class TestGetItemGroupDropdown:
    """Tests for the item group dropdown recursive CTE query."""

    def test_returns_text_object(self):
        """Query function should return a sqlalchemy text object."""
        result = get_item_group_drodown(co_id=1)
        assert isinstance(result, type(text("")))

    def test_contains_co_id_bind(self):
        """Query should have :co_id bind parameter."""
        result = get_item_group_drodown(co_id=1)
        sql_str = str(result)
        assert ":co_id" in sql_str

    def test_no_bare_active_equals_integer(self):
        """active column must NOT be compared as integer (= 1) since it's VARCHAR.

        This is the regression test for the 1292 'Truncated incorrect DOUBLE value' error.
        The query must use string comparison like active IN ('Y', '1') instead of active = 1.
        """
        result = get_item_group_drodown(co_id=1)
        sql_str = str(result)
        # Should NOT contain bare `active = 1` (integer comparison)
        # Allow `active = '1'` (string comparison) or `active IN ('Y', '1')`
        import re
        bare_int_pattern = re.compile(r"\.active\s*=\s*1(?!')")
        matches = bare_int_pattern.findall(sql_str)
        assert len(matches) == 0, (
            f"Found bare integer comparison for active column: {matches}. "
            "item_grp_mst.active is VARCHAR — use string comparison like IN ('Y', '1')."
        )

    def test_anchor_filters_active(self):
        """Anchor member of CTE should filter on active status."""
        result = get_item_group_drodown(co_id=1)
        sql_str = str(result)
        assert "igm.active" in sql_str, "Anchor should filter on igm.active"

    def test_recursive_member_filters_active(self):
        """Recursive member should also filter inactive child groups."""
        result = get_item_group_drodown(co_id=1)
        sql_str = str(result)
        assert "child.active" in sql_str, (
            "Recursive member should filter on child.active to exclude inactive child groups"
        )

    def test_handles_null_active_values(self):
        """Query should treat NULL active values as active (OR active IS NULL)."""
        result = get_item_group_drodown(co_id=1)
        sql_str = str(result).lower()
        assert "is null" in sql_str, (
            "Query should handle NULL active values with IS NULL check"
        )
