"""
Common formatters for Jute Procurement module.
Provides SQL expressions and Python functions for formatting document numbers.

Financial Year Logic:
- Financial year runs from April 1 to March 31
- Example: April 1, 2025 to March 31, 2026 = FY "25-26"
- January 20, 2025 falls in FY "24-25" (since it's before April 2025)
- PO numbering is per branch per financial year
"""

from datetime import date
from typing import Tuple


def get_financial_year(dt: date) -> Tuple[int, int]:
    """
    Get the financial year for a given date.
    
    Financial year: April 1 to March 31
    Example: 
        - January 20, 2025 → FY 2024-2025 (returns (2024, 2025))
        - April 15, 2025 → FY 2025-2026 (returns (2025, 2026))
    
    Args:
        dt: The date to check
    
    Returns:
        Tuple of (start_year, end_year)
    """
    if dt.month >= 4:  # April onwards
        return (dt.year, dt.year + 1)
    else:  # January to March
        return (dt.year - 1, dt.year)


def get_financial_year_string(dt: date) -> str:
    """
    Get the financial year string for a given date.
    
    Example:
        - January 20, 2025 → "24-25"
        - April 15, 2025 → "25-26"
    
    Args:
        dt: The date to check
    
    Returns:
        Financial year string like "25-26"
    """
    start_year, end_year = get_financial_year(dt)
    return f"{start_year % 100:02d}-{end_year % 100:02d}"


def get_financial_year_sql_expression(date_column: str = "po_date") -> str:
    """
    Returns a SQL expression that calculates the financial year string from a date.
    
    Financial year: April 1 to March 31
    Result format: "25-26" for FY 2025-2026
    
    Args:
        date_column: The column containing the date
    
    Returns:
        SQL expression string for financial year (e.g., "25-26")
    """
    # If month >= 4 (April onwards), FY starts in current year
    # If month < 4 (Jan-Mar), FY started in previous year
    return f"""CONCAT(
        CASE 
            WHEN MONTH({date_column}) >= 4 
            THEN LPAD(MOD(YEAR({date_column}), 100), 2, '0')
            ELSE LPAD(MOD(YEAR({date_column}) - 1, 100), 2, '0')
        END,
        '-',
        CASE 
            WHEN MONTH({date_column}) >= 4 
            THEN LPAD(MOD(YEAR({date_column}) + 1, 100), 2, '0')
            ELSE LPAD(MOD(YEAR({date_column}), 100), 2, '0')
        END
    )"""


def get_jute_po_number_sql_expression(
    po_no_column: str = "jp.po_no",
    po_date_column: str = "jp.po_date",
    co_prefix_column: str = "cm.co_prefix",
    branch_prefix_column: str = "bm.branch_prefix"
) -> str:
    """
    Returns a SQL CONCAT expression that formats the Jute PO number.
    
    Format: {co_prefix}/{branch_prefix}/JPO/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JPO/25-26/00001
    
    Financial year: April 1 to March 31
    Example: January 20, 2025 → FY 24-25
    
    Args:
        po_no_column: The column containing the PO sequence number
        po_date_column: The column containing the PO date (for financial year)
        co_prefix_column: The column containing the company prefix
        branch_prefix_column: The column containing the branch prefix
    
    Returns:
        SQL expression string for CONCAT
    """
    fy_expr = get_financial_year_sql_expression(po_date_column)
    return f"""CONCAT(
        COALESCE({co_prefix_column}, ''),
        CASE WHEN {co_prefix_column} IS NOT NULL AND {co_prefix_column} != '' THEN '/' ELSE '' END,
        COALESCE({branch_prefix_column}, ''),
        CASE WHEN {branch_prefix_column} IS NOT NULL AND {branch_prefix_column} != '' THEN '/' ELSE '' END,
        'JPO/',
        {fy_expr},
        '/',
        LPAD({po_no_column}, 5, '0')
    )"""


def format_jute_po_number(
    po_no: int,
    po_date: date,
    co_prefix: str = None,
    branch_prefix: str = None
) -> str:
    """
    Python function to format Jute PO number.
    
    Format: {co_prefix}/{branch_prefix}/JPO/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JPO/25-26/00001
    
    Args:
        po_no: The PO sequence number
        po_date: The date of the PO (for financial year calculation)
        co_prefix: The company prefix (optional)
        branch_prefix: The branch prefix (optional)
    
    Returns:
        Formatted PO number string
    """
    fy_string = get_financial_year_string(po_date)
    parts = []
    if co_prefix:
        parts.append(co_prefix)
    if branch_prefix:
        parts.append(branch_prefix)
    parts.append("JPO")
    parts.append(fy_string)
    parts.append(f"{po_no:05d}")
    return "/".join(parts)


def get_jute_gate_entry_number_sql_expression(
    gate_entry_no_column: str = "jge.branch_gate_entry_no",
    entry_date_column: str = "jge.jute_gate_entry_date",
    co_prefix_column: str = "cm.co_prefix",
    branch_prefix_column: str = "bm.branch_prefix"
) -> str:
    """
    Returns a SQL CONCAT expression that formats the Jute Gate Entry number.
    
    Format: {co_prefix}/{branch_prefix}/JGE/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JGE/25-26/00001
    
    Financial year: April 1 to March 31
    
    Args:
        gate_entry_no_column: The column containing the gate entry sequence number
        entry_date_column: The column containing the entry date (for financial year)
        co_prefix_column: The column containing the company prefix
        branch_prefix_column: The column containing the branch prefix
    
    Returns:
        SQL expression string for CONCAT
    """
    fy_expr = get_financial_year_sql_expression(entry_date_column)
    return f"""CONCAT(
        COALESCE({co_prefix_column}, ''),
        CASE WHEN {co_prefix_column} IS NOT NULL AND {co_prefix_column} != '' THEN '/' ELSE '' END,
        COALESCE({branch_prefix_column}, ''),
        CASE WHEN {branch_prefix_column} IS NOT NULL AND {branch_prefix_column} != '' THEN '/' ELSE '' END,
        'JGE/',
        {fy_expr},
        '/',
        LPAD({gate_entry_no_column}, 5, '0')
    )"""


def format_jute_gate_entry_number(
    gate_entry_no: int,
    entry_date: date,
    co_prefix: str = None,
    branch_prefix: str = None
) -> str:
    """
    Python function to format Jute Gate Entry number.
    
    Format: {co_prefix}/{branch_prefix}/JGE/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JGE/25-26/00001
    
    Args:
        gate_entry_no: The gate entry sequence number
        entry_date: The date of the gate entry (for financial year calculation)
        co_prefix: The company prefix (optional)
        branch_prefix: The branch prefix (optional)
    
    Returns:
        Formatted gate entry number string
    """
    fy_string = get_financial_year_string(entry_date)
    parts = []
    if co_prefix:
        parts.append(co_prefix)
    if branch_prefix:
        parts.append(branch_prefix)
    parts.append("JGE")
    parts.append(fy_string)
    parts.append(f"{gate_entry_no:05d}")
    return "/".join(parts)


def get_jute_mr_number_sql_expression(
    mr_no_column: str = "jm.branch_mr_no",
    mr_date_column: str = "jm.jute_mr_date",
    co_prefix_column: str = "cm.co_prefix",
    branch_prefix_column: str = "bm.branch_prefix"
) -> str:
    """
    Returns a SQL CONCAT expression that formats the Jute MR number.

    Format: {co_prefix}/{branch_prefix}/JMR/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JMR/25-26/00001

    Args:
        mr_no_column: The column containing the MR sequence number
        mr_date_column: The column containing the MR date (for financial year)
        co_prefix_column: The column containing the company prefix
        branch_prefix_column: The column containing the branch prefix

    Returns:
        SQL expression string for CONCAT
    """
    fy_expr = get_financial_year_sql_expression(mr_date_column)
    return f"""CONCAT(
        COALESCE({co_prefix_column}, ''),
        CASE WHEN {co_prefix_column} IS NOT NULL AND {co_prefix_column} != '' THEN '/' ELSE '' END,
        COALESCE({branch_prefix_column}, ''),
        CASE WHEN {branch_prefix_column} IS NOT NULL AND {branch_prefix_column} != '' THEN '/' ELSE '' END,
        'JMR/',
        {fy_expr},
        '/',
        LPAD({mr_no_column}, 5, '0')
    )"""


def format_jute_mr_number(
    mr_no: int,
    mr_date: date,
    co_prefix: str = None,
    branch_prefix: str = None
) -> str:
    """
    Python function to format Jute MR number.

    Format: {co_prefix}/{branch_prefix}/JMR/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JMR/25-26/00001

    Args:
        mr_no: The MR sequence number
        mr_date: The date of the MR (for financial year calculation)
        co_prefix: The company prefix (optional)
        branch_prefix: The branch prefix (optional)

    Returns:
        Formatted MR number string
    """
    fy_string = get_financial_year_string(mr_date)
    parts = []
    if co_prefix:
        parts.append(co_prefix)
    if branch_prefix:
        parts.append(branch_prefix)
    parts.append("JMR")
    parts.append(fy_string)
    parts.append(f"{mr_no:05d}")
    return "/".join(parts)


def get_jute_bill_pass_number_sql_expression(
    bill_pass_no_column: str = "jm.bill_pass_no",
    bill_pass_date_column: str = "jm.bill_pass_date",
    co_prefix_column: str = "cm.co_prefix",
    branch_prefix_column: str = "bm.branch_prefix"
) -> str:
    """
    Returns a SQL CONCAT expression that formats the Jute Bill Pass number.

    Format: {co_prefix}/{branch_prefix}/JBP/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JBP/25-26/00001

    Args:
        bill_pass_no_column: The column containing the bill pass sequence number
        bill_pass_date_column: The column containing the bill pass date (for financial year)
        co_prefix_column: The column containing the company prefix
        branch_prefix_column: The column containing the branch prefix

    Returns:
        SQL expression string for CONCAT
    """
    fy_expr = get_financial_year_sql_expression(bill_pass_date_column)
    return f"""CONCAT(
        COALESCE({co_prefix_column}, ''),
        CASE WHEN {co_prefix_column} IS NOT NULL AND {co_prefix_column} != '' THEN '/' ELSE '' END,
        COALESCE({branch_prefix_column}, ''),
        CASE WHEN {branch_prefix_column} IS NOT NULL AND {branch_prefix_column} != '' THEN '/' ELSE '' END,
        'JBP/',
        {fy_expr},
        '/',
        LPAD({bill_pass_no_column}, 5, '0')
    )"""


def format_jute_bill_pass_number(
    bill_pass_no: int,
    bill_pass_date: date,
    co_prefix: str = None,
    branch_prefix: str = None
) -> str:
    """
    Python function to format Jute Bill Pass number.

    Format: {co_prefix}/{branch_prefix}/JBP/{fy_year}/{sequence:05d}
    Example: ABC/FAC/JBP/25-26/00001

    Args:
        bill_pass_no: The bill pass sequence number
        bill_pass_date: The date of the bill pass (for financial year calculation)
        co_prefix: The company prefix (optional)
        branch_prefix: The branch prefix (optional)

    Returns:
        Formatted bill pass number string
    """
    fy_string = get_financial_year_string(bill_pass_date)
    parts = []
    if co_prefix:
        parts.append(co_prefix)
    if branch_prefix:
        parts.append(branch_prefix)
    parts.append("JBP")
    parts.append(fy_string)
    parts.append(f"{bill_pass_no:05d}")
    return "/".join(parts)
