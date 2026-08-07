"""
Sales Report Queries.
Contains SQL queries for sales reports (Tally exports etc.).
"""

from sqlalchemy import text

from src.juteProcurement.formatters import (
    get_jute_mr_number_sql_expression,
    get_financial_year_sql_expression,
)


def _sales_invoice_no_sql_expression() -> str:
    """SQL CONCAT expression that formats the sales invoice number.

    Format mirrors format_indent_no(... document_type="SI") used in
    src/sales/salesInvoice.py: "{co_prefix}/{branch_prefix}/SI/{fy}/{invoice_no}".
    Empty parts are dropped.
    """
    fy_expr = get_financial_year_sql_expression("ih.invoice_date")
    return f"""CONCAT(
        COALESCE(cm.co_prefix, ''),
        CASE WHEN cm.co_prefix IS NOT NULL AND cm.co_prefix != '' THEN '/' ELSE '' END,
        COALESCE(bm.branch_prefix, ''),
        CASE WHEN bm.branch_prefix IS NOT NULL AND bm.branch_prefix != '' THEN '/' ELSE '' END,
        'SI/',
        {fy_expr},
        '/',
        CAST(ih.invoice_no AS CHAR)
    )"""


def _sales_order_no_sql_expression(date_col: str = "so.sales_order_date",
                                   no_col: str = "so.sales_no") -> str:
    """SQL CONCAT expression that formats the sales order number.

    Format mirrors format_indent_no(... document_type="SO"):
    "{co_prefix}/{branch_prefix}/SO/{fy}/{sales_no}".
    """
    fy_expr = get_financial_year_sql_expression(date_col)
    return f"""CONCAT(
        COALESCE(cm.co_prefix, ''),
        CASE WHEN cm.co_prefix IS NOT NULL AND cm.co_prefix != '' THEN '/' ELSE '' END,
        COALESCE(bm.branch_prefix, ''),
        CASE WHEN bm.branch_prefix IS NOT NULL AND bm.branch_prefix != '' THEN '/' ELSE '' END,
        'SO/',
        {fy_expr},
        '/',
        CAST({no_col} AS CHAR)
    )"""


def _invoice_no_for_list_sql_expression() -> str:
    """Same as _sales_invoice_no_sql_expression but referencing the
    `si` alias used by the invoice-list-report query (instead of `ih`)."""
    fy_expr = get_financial_year_sql_expression("si.invoice_date")
    return f"""CONCAT(
        COALESCE(cm.co_prefix, ''),
        CASE WHEN cm.co_prefix IS NOT NULL AND cm.co_prefix != '' THEN '/' ELSE '' END,
        COALESCE(bm.branch_prefix, ''),
        CASE WHEN bm.branch_prefix IS NOT NULL AND bm.branch_prefix != '' THEN '/' ELSE '' END,
        'SI/',
        {fy_expr},
        '/',
        CAST(si.invoice_no AS CHAR)
    )"""


def get_sales_order_list_report_query():
    """Sales Order list report — date-range scoped, all statuses.

    Bind params:
        :co_id      (int, required)
        :branch_id  (int or NULL — optional branch filter)
        :date_from  (str 'YYYY-MM-DD', required)
        :date_to    (str 'YYYY-MM-DD', required)

    Returns: text() sql object with columns:
        sales_order_id, sales_no, sales_no_formatted, sales_order_date,
        branch_name, party_name, quotation_no, invoice_type, status_name,
        status_id, approval_level, gross_amount, net_amount.
    """
    so_no_expr = _sales_order_no_sql_expression()
    sql = f"""
        SELECT
            so.sales_order_id                            AS sales_order_id,
            so.sales_no                                  AS sales_no,
            {so_no_expr}                                 AS sales_no_formatted,
            so.sales_order_date                          AS sales_order_date,
            COALESCE(bm.branch_name, '')                 AS branch_name,
            COALESCE(pm.supp_name, '')                   AS party_name,
            COALESCE(sq.quotation_no, '')                AS quotation_no,
            so.invoice_type                              AS invoice_type,
            COALESCE(sm.status_name, '')                 AS status_name,
            so.status_id                                 AS status_id,
            COALESCE(so.approval_level, 0)               AS approval_level,
            COALESCE(so.gross_amount, 0)                 AS gross_amount,
            COALESCE(so.net_amount, 0)                   AS net_amount
        FROM sales_order AS so
        LEFT JOIN branch_mst AS bm ON bm.branch_id = so.branch_id
        LEFT JOIN co_mst     AS cm ON cm.co_id = bm.co_id
        LEFT JOIN party_mst  AS pm ON pm.party_id = so.party_id
        LEFT JOIN sales_quotation AS sq ON sq.sales_quotation_id = so.quotation_id
        LEFT JOIN status_mst AS sm ON sm.status_id = so.status_id
        WHERE so.active = 1
          AND bm.co_id = :co_id
          AND (:branch_id IS NULL OR so.branch_id = :branch_id)
          AND so.sales_order_date BETWEEN :date_from AND :date_to
        ORDER BY so.sales_order_date DESC, so.sales_order_id DESC
    """
    return text(sql)


def get_invoice_list_report_query():
    """Sales Invoice list report — date-range scoped, all statuses.

    Bind params:
        :co_id      (int, required)
        :branch_id  (int or NULL — optional branch filter)
        :date_from  (str 'YYYY-MM-DD', required)
        :date_to    (str 'YYYY-MM-DD', required)

    Returns: text() sql object with columns:
        invoice_id, invoice_no, invoice_no_formatted, invoice_date,
        branch_name, party_name, invoice_type, status_name, status_id,
        approval_level, challan_no, challan_date, due_date, invoice_amount,
        tax_amount, tax_payable, round_off.
    """
    inv_no_expr = _invoice_no_for_list_sql_expression()
    sql = f"""
        SELECT
            si.invoice_id                                AS invoice_id,
            si.invoice_no                                AS invoice_no,
            {inv_no_expr}                                AS invoice_no_formatted,
            si.invoice_date                              AS invoice_date,
            COALESCE(bm.branch_name, '')                 AS branch_name,
            COALESCE(pm.supp_name, '')                   AS party_name,
            si.invoice_type                              AS invoice_type,
            COALESCE(sm.status_name, '')                 AS status_name,
            si.status_id                                 AS status_id,
            COALESCE(si.approval_level, 0)               AS approval_level,
            COALESCE(si.challan_no, '')                  AS challan_no,
            si.challan_date                              AS challan_date,
            si.due_date                                  AS due_date,
            COALESCE(si.invoice_amount, 0)               AS invoice_amount,
            COALESCE(si.tax_amount, 0)                   AS tax_amount,
            COALESCE(si.tax_payable, 0)                  AS tax_payable,
            COALESCE(si.round_off, 0)                    AS round_off
        FROM sales_invoice AS si
        LEFT JOIN branch_mst AS bm ON bm.branch_id = si.branch_id
        LEFT JOIN co_mst     AS cm ON cm.co_id = bm.co_id
        LEFT JOIN party_mst  AS pm ON pm.party_id = si.party_id
        LEFT JOIN status_mst AS sm ON sm.status_id = si.status_id
        WHERE bm.co_id = :co_id
          AND (si.active = 1 OR si.active IS NULL)
          AND (:branch_id IS NULL OR si.branch_id = :branch_id)
          AND si.invoice_date BETWEEN :date_from AND :date_to
        ORDER BY si.invoice_date DESC, si.invoice_id DESC
    """
    return text(sql)


def get_sales_jute_summary_query():
    """Per-sales-invoice summary mirroring the Tally download scope.

    One row per `sales_invoice` matching the same filters as
    `get_sales_jute_tally_download_query`. Useful for a "Load" preview
    before downloading the xlsx.

    Bind params:
        :co_id               (int, required)
        :branch_id           (int or NULL — optional branch filter)
        :date_from           (str 'YYYY-MM-DD', required)
        :date_to             (str 'YYYY-MM-DD', required)
        :invoice_type_id     (int — INVOICE_TYPE_IDS["RAW_JUTE"])
        :approved_status_id  (int — SALES_STATUS_IDS["APPROVED"])

    Returns: text() sql object with columns:
        invoice_id, invoice_no, invoice_date, party_name, branch_name,
        vehicle_no, challan_no, mr_number, total_qty_kg, invoice_amount,
        claim_amount
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    invoice_no_expr = _sales_invoice_no_sql_expression()

    sql = f"""
        WITH
        agg_qty AS (
            SELECT sid.invoice_id,
                   SUM(sid.quantity) AS tqty
            FROM sales_invoice_dtl sid
            GROUP BY sid.invoice_id
        ),
        agg_claim AS (
            SELECT sid.invoice_id,
                   SUM(COALESCE(sijd.claim_amount_dtl, 0)) AS tclm
            FROM sales_invoice_dtl sid
            LEFT JOIN sales_invoice_jute_dtl sijd
                ON sijd.invoice_line_item_id = sid.invoice_line_item_id
            GROUP BY sid.invoice_id
        ),
        agg_mr AS (
            SELECT sij.invoice_id,
                   MIN(sij.mr_id) AS mr_id
            FROM sales_invoice_jute sij
            WHERE sij.mr_id IS NOT NULL
            GROUP BY sij.invoice_id
        )
        SELECT
            ih.invoice_id                                          AS invoice_id,
            {invoice_no_expr}                                      AS invoice_no,
            ih.invoice_date                                        AS invoice_date,
            COALESCE(pm.supp_name, '')                             AS party_name,
            COALESCE(bm.branch_name, '')                           AS branch_name,
            COALESCE(ih.vehicle_no, '')                            AS vehicle_no,
            COALESCE(ih.challan_no, '')                            AS challan_no,
            CASE WHEN amr.mr_id IS NOT NULL
                 THEN {mr_num_expr}
                 ELSE ''
            END                                                    AS mr_number,
            COALESCE(aq.tqty, 0)                                   AS total_qty_kg,
            (COALESCE(ih.invoice_amount, 0) - COALESCE(ih.round_off, 0))
                                                                   AS invoice_amount,
            COALESCE(ac.tclm, 0)                                   AS claim_amount
        FROM sales_invoice ih
        LEFT JOIN branch_mst bm ON bm.branch_id = ih.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN party_mst pm ON pm.party_id = ih.party_id
        LEFT JOIN agg_qty aq ON aq.invoice_id = ih.invoice_id
        LEFT JOIN agg_claim ac ON ac.invoice_id = ih.invoice_id
        LEFT JOIN agg_mr amr ON amr.invoice_id = ih.invoice_id
        LEFT JOIN jute_mr jm ON jm.jute_mr_id = amr.mr_id
        WHERE bm.co_id = :co_id
          AND ih.invoice_type = :invoice_type_id
          AND ih.status_id = :approved_status_id
          AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
          AND ih.invoice_date BETWEEN :date_from AND :date_to
        ORDER BY ih.invoice_date, ih.invoice_id
    """
    return text(sql)


def get_sales_jute_tally_download_query():
    """Sales Raw Jute Tally download query.

    Translates the legacy PHP/MySQL `sales_raw_jute_tally` report to the current
    VoWERP3 schema. UNION ALL of three selects against `sales_invoice` (ih):

      rem='hd'  — customer ledger Dr per invoice  (one row per invoice)
      rem='ln'  — "Sale of Raw Jute" Cr per line  (one row per invoice line)
      rem='oth' — "Claim on Gross Sales" Dr per invoice (only if SUM claim > 0)

    Rows are ordered by invoice_date, invoice_no, rem_rank (hd<ln<oth),
    invoice_line_item_id. Internal ordering columns are emitted so SQL can
    ORDER BY — the caller strips them before returning.

    Bind params:
        :co_id               (int, required)
        :branch_id           (int or NULL — optional branch filter)
        :date_from           (str 'YYYY-MM-DD', required)
        :date_to             (str 'YYYY-MM-DD', required)
        :invoice_type_id     (int — INVOICE_TYPE_IDS["RAW_JUTE"])
        :approved_status_id  (int — SALES_STATUS_IDS["APPROVED"])

    Returns: text() sql object.
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    invoice_no_expr = _sales_invoice_no_sql_expression()

    # Per-invoice aggregates (total qty in Kg; total claim). Built once so
    # each UNION branch can join to them cheaply.
    # NOTE: sales_invoice_dtl has no `active` column — header status_id = 3
    # already excludes cancelled invoices (user-confirmed).
    agg_qty_cte = """
        agg_qty AS (
            SELECT sid.invoice_id,
                   SUM(sid.quantity) AS tqty
            FROM sales_invoice_dtl sid
            GROUP BY sid.invoice_id
        )
    """
    agg_claim_cte = """
        agg_claim AS (
            SELECT sid.invoice_id,
                   SUM(COALESCE(sijd.claim_amount_dtl, 0)) AS tclm
            FROM sales_invoice_dtl sid
            LEFT JOIN sales_invoice_jute_dtl sijd
                ON sijd.invoice_line_item_id = sid.invoice_line_item_id
            GROUP BY sid.invoice_id
        )
    """
    # Best-available MR number per invoice. A single invoice can link to
    # multiple MRs via sales_invoice_jute.mr_id — pick MIN(mr_id) for a
    # stable, deterministic value (user-confirmed).
    agg_mr_cte = """
        agg_mr AS (
            SELECT sij.invoice_id,
                   MIN(sij.mr_id) AS mr_id
            FROM sales_invoice_jute sij
            WHERE sij.mr_id IS NOT NULL
            GROUP BY sij.invoice_id
        )
    """

    # Common FROM/JOIN for header-level rows (hd / oth).
    # NOTE: legacy uses `ih.shipping_address` — no such column exists here. We
    # fall back to party_branch_mst.address joined via shipping_to_id; if null,
    # emit empty string.
    header_joins = """
        FROM sales_invoice ih
        LEFT JOIN branch_mst bm ON bm.branch_id = ih.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN party_mst pm ON pm.party_id = ih.party_id
        LEFT JOIN party_branch_mst pbm
            ON pbm.party_mst_branch_id = ih.shipping_to_id
        LEFT JOIN state_mst sm ON sm.state_id = pbm.state_id
        LEFT JOIN agg_qty aq ON aq.invoice_id = ih.invoice_id
        LEFT JOIN agg_mr amr ON amr.invoice_id = ih.invoice_id
        LEFT JOIN jute_mr jm ON jm.jute_mr_id = amr.mr_id
    """

    # FROM/JOIN for line-level rows (ln).
    line_joins = """
        FROM sales_invoice ih
        INNER JOIN sales_invoice_dtl sid ON sid.invoice_id = ih.invoice_id
        LEFT JOIN branch_mst bm ON bm.branch_id = ih.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN item_mst im ON im.item_id = sid.item_id
        LEFT JOIN agg_mr amr ON amr.invoice_id = ih.invoice_id
        LEFT JOIN jute_mr jm ON jm.jute_mr_id = amr.mr_id
    """

    # Base WHERE clause (same across all three branches).
    # Note: we explicitly filter invoice_type AND status_id from bind params
    # (user-confirmed: constants passed from Python, not hardcoded in SQL).
    where_common = """
        WHERE bm.co_id = :co_id
          AND ih.invoice_type = :invoice_type_id
          AND ih.status_id = :approved_status_id
          AND (:branch_id IS NULL OR ih.branch_id = :branch_id)
          AND ih.invoice_date BETWEEN :date_from AND :date_to
    """

    # For the 'oth' branch, only emit row if sum(claim) > 0.
    where_oth_extra = " AND ac.tclm > 0"

    sql = f"""
        WITH
        {agg_qty_cte},
        {agg_claim_cte},
        {agg_mr_cte}
        SELECT * FROM (
            /* ---------- Row 1: header debit (customer ledger, Dr) ---------- */
            SELECT
                'Sales'                                                AS `Voucher Type Name`,
                DATE_FORMAT(ih.invoice_date, '%d-%b-%Y')               AS `Voucher Date`,
                {invoice_no_expr}                                      AS `Voucher Number`,
                COALESCE(pm.supp_name, '')                             AS `Ledger Name`,
                (COALESCE(ih.invoice_amount, 0) - COALESCE(ih.round_off, 0))
                                                                       AS `Ledger Amount`,
                'Dr'                                                   AS `Ledger Amount Dr/Cr`,
                CONCAT(' Ch.No: ', COALESCE(ih.challan_no, ''))        AS `Despatch Doc no.`,
                CONCAT('Truck No: ', COALESCE(ih.vehicle_no, ''))      AS `Despath though`,
                COALESCE(pbm.address, '')                              AS `Destination`,
                CASE WHEN amr.mr_id IS NOT NULL
                     THEN {mr_num_expr}
                     ELSE ''
                END                                                    AS `other references`,
                ' '                                                    AS `Item Name`,
                ' '                                                    AS `Godown`,
                ''                                                     AS `Batch/Lotno.`,
                ''                                                     AS `Billed Quantity`,
                ''                                                     AS `Item Rate`,
                ''                                                     AS `Item Rate per`,
                ''                                                     AS `Item Amount`,
                ''                                                     AS `Description ?`,
                'Item Invoice'                                         AS `Change Mode`,
                (COALESCE(ih.invoice_amount, 0) - COALESCE(ih.round_off, 0))
                                                                       AS `Bill Amount`,
                'Dr'                                                   AS `Bill Amount - Dr/Cr`,
                CONCAT({invoice_no_expr}, ' / ',
                       CASE WHEN amr.mr_id IS NOT NULL THEN {mr_num_expr} ELSE '' END)
                                                                       AS `Bill Name`,
                'New Ref'                                              AS `Bill Type of Ref`,
                180                                                    AS `Due or credit days`,
                CONCAT(
                    'Being ', COALESCE(aq.tqty, 0),
                    ' Kg. Raw Jute Sold To ', COALESCE(pm.supp_name, ''),
                    ' against Inv No: ', {invoice_no_expr},
                    '  Dt: ', COALESCE(DATE_FORMAT(ih.invoice_date, '%Y-%m-%d'), ''),
                    ' MR NO: ', CASE WHEN amr.mr_id IS NOT NULL THEN {mr_num_expr} ELSE '' END,
                    ', Amount Rs. ', COALESCE(ih.invoice_amount, 0),
                    ' /-'
                )                                                      AS `Narration`,
                COALESCE(pbm.address, '')                              AS `Address1`,
                COALESCE(sm.state, '')                                 AS `State1`,
                'India'                                                AS `Country1`,
                COALESCE(pbm.address, '')                              AS `Address2`,
                COALESCE(sm.state, '')                                 AS `State2`,
                'India'                                                AS `Country2`,
                ih.invoice_date                                        AS invoice_date,
                {invoice_no_expr}                                      AS invoice_no_string,
                0                                                      AS invoice_line_item_id,
                'hd'                                                   AS rem,
                1                                                      AS rem_rank,
                0                                                      AS slno
            {header_joins}
            {where_common}

            UNION ALL

            /* ---------- Row 2: line credits ("Sale of Raw Jute") ---------- */
            SELECT
                ''                                                     AS `Voucher Type Name`,
                ''                                                     AS `Voucher Date`,
                ''                                                     AS `Voucher Number`,
                'Sale of Raw Jute'                                     AS `Ledger Name`,
                (COALESCE(ih.invoice_amount, 0) - COALESCE(ih.round_off, 0))
                                                                       AS `Ledger Amount`,
                'Cr'                                                   AS `Ledger Amount Dr/Cr`,
                ''                                                     AS `Despatch Doc no.`,
                ''                                                     AS `Despath though`,
                ''                                                     AS `Destination`,
                ''                                                     AS `other references`,
                COALESCE(im.item_name, '')                             AS `Item Name`,
                COALESCE(bm.branch_name, '')                           AS `Godown`,
                CASE WHEN amr.mr_id IS NOT NULL
                     THEN {mr_num_expr}
                     ELSE ''
                END                                                    AS `Batch/Lotno.`,
                COALESCE(sid.quantity, 0)                              AS `Billed Quantity`,
                COALESCE(sid.rate, 0)                                  AS `Item Rate`,
                'kg'                                                   AS `Item Rate per`,
                COALESCE(sid.amount_without_tax, 0)                    AS `Item Amount`,
                CONCAT(
                    'Raw Jute: ',
                    CASE
                        WHEN COALESCE(sid.sales_weight, 0) > 0
                            THEN CONCAT(sid.sales_weight, ' Bales')
                        ELSE 'loose'
                    END
                )                                                      AS `Description ?`,
                ''                                                     AS `Change Mode`,
                ''                                                     AS `Bill Amount`,
                ''                                                     AS `Bill Amount - Dr/Cr`,
                ''                                                     AS `Bill Name`,
                ''                                                     AS `Bill Type of Ref`,
                ''                                                     AS `Due or credit days`,
                ''                                                     AS `Narration`,
                ''                                                     AS `Address1`,
                ''                                                     AS `State1`,
                ''                                                     AS `Country1`,
                ''                                                     AS `Address2`,
                ''                                                     AS `State2`,
                ''                                                     AS `Country2`,
                ih.invoice_date                                        AS invoice_date,
                {invoice_no_expr}                                      AS invoice_no_string,
                sid.invoice_line_item_id                               AS invoice_line_item_id,
                'ln'                                                   AS rem,
                2                                                      AS rem_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY sid.invoice_id
                    ORDER BY sid.invoice_line_item_id
                )                                                      AS slno
            {line_joins}
            {where_common}

            UNION ALL

            /* ---------- Row 3: header claim debit ("Claim on Gross Sales") ---------- */
            SELECT
                ''                                                     AS `Voucher Type Name`,
                ''                                                     AS `Voucher Date`,
                ''                                                     AS `Voucher Number`,
                'Claim on Gross Sales'                                 AS `Ledger Name`,
                (0 - COALESCE(ac.tclm, 0))                             AS `Ledger Amount`,
                ''                                                     AS `Ledger Amount Dr/Cr`,
                ''                                                     AS `Despatch Doc no.`,
                ''                                                     AS `Despath though`,
                ''                                                     AS `Destination`,
                ''                                                     AS `other references`,
                ' '                                                    AS `Item Name`,
                ' '                                                    AS `Godown`,
                ''                                                     AS `Batch/Lotno.`,
                ''                                                     AS `Billed Quantity`,
                ''                                                     AS `Item Rate`,
                ''                                                     AS `Item Rate per`,
                ''                                                     AS `Item Amount`,
                ''                                                     AS `Description ?`,
                ''                                                     AS `Change Mode`,
                ''                                                     AS `Bill Amount`,
                ''                                                     AS `Bill Amount - Dr/Cr`,
                ''                                                     AS `Bill Name`,
                ''                                                     AS `Bill Type of Ref`,
                ''                                                     AS `Due or credit days`,
                ''                                                     AS `Narration`,
                ''                                                     AS `Address1`,
                ''                                                     AS `State1`,
                ''                                                     AS `Country1`,
                ''                                                     AS `Address2`,
                ''                                                     AS `State2`,
                ''                                                     AS `Country2`,
                ih.invoice_date                                        AS invoice_date,
                {invoice_no_expr}                                      AS invoice_no_string,
                0                                                      AS invoice_line_item_id,
                'oth'                                                  AS rem,
                3                                                      AS rem_rank,
                0                                                      AS slno
            FROM sales_invoice ih
            LEFT JOIN branch_mst bm ON bm.branch_id = ih.branch_id
            LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
            LEFT JOIN party_mst pm ON pm.party_id = ih.party_id
            LEFT JOIN agg_claim ac ON ac.invoice_id = ih.invoice_id
            {where_common}
            {where_oth_extra}
        ) g
        ORDER BY invoice_date, invoice_no_string, rem_rank, invoice_line_item_id
    """
    return text(sql)
