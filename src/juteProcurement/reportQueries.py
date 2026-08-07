"""
Jute Procurement Report Queries.
Contains SQL queries for jute stock and related reports.
"""

from sqlalchemy import text

from src.juteProcurement.constants import JUTE_MR_APPROVED_STATUSES, TDS_CAP_INR
from src.juteProcurement.formatters import (
    get_jute_mr_number_sql_expression,
    get_jute_po_number_sql_expression,
)


def _group_path_cte():
    """
    Returns a recursive CTE that builds full hierarchical group paths.
    Creates a temp table `full_group_paths` with columns: item_grp_id, item_grp_name_path.
    Usage: prepend to any query, then JOIN full_group_paths fgp ON fgp.item_grp_id = ...
    and use COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS jute_group_name.
    """
    return """
        WITH RECURSIVE group_path AS (
            SELECT
                igm.item_grp_id AS target_id,
                igm.item_grp_id,
                igm.item_grp_name,
                igm.parent_grp_id,
                CAST(igm.item_grp_name AS CHAR(500)) AS item_grp_name_path
            FROM item_grp_mst igm

            UNION ALL

            SELECT
                child.target_id,
                p.item_grp_id,
                p.item_grp_name,
                p.parent_grp_id,
                CAST(CONCAT(p.item_grp_name, ' > ', child.item_grp_name_path) AS CHAR(500))
            FROM item_grp_mst p
            JOIN group_path child ON child.parent_grp_id = p.item_grp_id
        ),
        full_group_paths AS (
            SELECT target_id AS item_grp_id, item_grp_name_path
            FROM group_path
            WHERE parent_grp_id IS NULL
        )
    """


def get_jute_stock_report_query():
    """
    Query to calculate daily jute stock position grouped by item group and item.

    Returns opening stock, receipt, issue, closing stock, and MTD receipt/issue
    for a given branch and report date.

    Key tables:
    - jute_mr + jute_mr_li for receipts (out_date = inward date, actual_weight, actual_item_id)
    - jute_issue for issues (issue_date, weight, COALESCE(item_id, mrli.actual_item_id))
    - item_mst + item_grp_mst for item/group names

    Parameters: :branch_id (int), :report_date (string 'YYYY-MM-DD')
    """
    sql = _group_path_cte() + """,
        -- Receipts before report_date (for opening)
        receipt_before AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date < :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- Issues before report_date (for opening)
        issue_before AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date < :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        -- Receipts ON report_date
        receipt_on AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date = :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- Issues ON report_date
        issue_on AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        -- MTD receipts (1st of month to report_date)
        receipt_mtd AS (
            SELECT
                mrli.actual_item_id AS item_id,
                ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS total_weight
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date >= DATE_SUB(:report_date, INTERVAL DAYOFMONTH(:report_date) - 1 DAY)
              AND jm.out_date <= :report_date
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        -- MTD issues (1st of month to report_date)
        issue_mtd AS (
            SELECT
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_weight
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date >= DATE_SUB(:report_date, INTERVAL DAYOFMONTH(:report_date) - 1 DAY)
              AND ji.issue_date <= :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        )

        SELECT
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS item_group_name,
            im.item_id,
            im.item_name,
            ROUND(COALESCE(rb.total_weight, 0) - COALESCE(ib.total_weight, 0), 3) AS opening_weight,
            ROUND(COALESCE(ro.total_weight, 0), 3) AS receipt_weight,
            ROUND(COALESCE(io.total_weight, 0), 3) AS issue_weight,
            ROUND(
                (COALESCE(rb.total_weight, 0) - COALESCE(ib.total_weight, 0))
                + COALESCE(ro.total_weight, 0)
                - COALESCE(io.total_weight, 0),
                3
            ) AS closing_weight,
            ROUND(COALESCE(rm.total_weight, 0), 3) AS mtd_receipt_weight,
            ROUND(COALESCE(im2.total_weight, 0), 3) AS mtd_issue_weight
        FROM item_mst im
        INNER JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        LEFT JOIN receipt_before rb ON rb.item_id = im.item_id
        LEFT JOIN issue_before ib ON ib.item_id = im.item_id
        LEFT JOIN receipt_on ro ON ro.item_id = im.item_id
        LEFT JOIN issue_on io ON io.item_id = im.item_id
        LEFT JOIN receipt_mtd rm ON rm.item_id = im.item_id
        LEFT JOIN issue_mtd im2 ON im2.item_id = im.item_id
        WHERE (
            rb.item_id IS NOT NULL
            OR ib.item_id IS NOT NULL
            OR ro.item_id IS NOT NULL
            OR io.item_id IS NOT NULL
            OR rm.item_id IS NOT NULL
            OR im2.item_id IS NOT NULL
        )
        ORDER BY ig.item_grp_name, im.item_name
    """
    return text(sql)


def get_batch_cost_report_query():
    """
    Query to calculate yarn quality-wise planned vs actual jute issue
    for a given branch and date (batch cost report).

    For each yarn type assigned on the date, computes:
    - Planned weight: (batch_plan_li percentage / 100) * total actual issue weight for that yarn type
    - Actual weight: sum of jute_issue weight grouped by yarn_type + item
    - Avg rate: average of jute_mr_li.actual_rate per group
    - Issue value: sum of jute_issue.issue_value
    - Variance: actual_weight - planned_weight

    Uses a UNION to emulate FULL OUTER JOIN (MySQL doesn't support it natively).

    Parameters: :branch_id (int), :report_date (string 'YYYY-MM-DD')
    """
    sql = """
        -- CTE 1: Total actual issue weight per yarn type on this date
        WITH yarn_totals AS (
            SELECT
                ji.yarn_type_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS total_actual_weight
            FROM jute_issue ji
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY ji.yarn_type_id
        ),

        -- CTE 2: Planned weights from batch daily assignments + batch plan line items
        planned AS (
            SELECT
                bda.jute_yarn_id AS yarn_type_id,
                bpl.jute_quality_id AS item_id,
                bpl.percentage,
                yt.total_actual_weight,
                ROUND((bpl.percentage / 100.0) * COALESCE(yt.total_actual_weight, 0), 3) AS planned_weight
            FROM jute_batch_daily_assign bda
            INNER JOIN jute_batch_plan_li bpl ON bpl.batch_plan_id = bda.batch_plan_id
            LEFT JOIN yarn_totals yt ON yt.yarn_type_id = bda.jute_yarn_id
            WHERE bda.branch_id = :branch_id
              AND bda.assign_date = :report_date
              AND bda.status_id IN (1, 3)
        ),

        -- CTE 3: Actual issues grouped by yarn_type + item
        actual AS (
            SELECT
                ji.yarn_type_id,
                COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                ROUND(COALESCE(SUM(ji.weight), 0), 3) AS actual_weight,
                ROUND(AVG(mrli.actual_rate), 2) AS avg_rate,
                ROUND(COALESCE(SUM(ji.issue_value), 0), 2) AS issue_value
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date = :report_date
              AND ji.status_id IN (1, 3)
            GROUP BY ji.yarn_type_id, COALESCE(ji.item_id, mrli.actual_item_id)
        )

        -- FULL OUTER JOIN emulated via LEFT JOIN + UNION
        -- Part 1: All planned items, with actual data where available
        SELECT
            COALESCE(p.yarn_type_id, a.yarn_type_id) AS yarn_type_id,
            COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
            COALESCE(p.item_id, a.item_id) AS item_id,
            im.item_name,
            im.item_grp_id,
            COALESCE(igm.item_grp_name) AS item_group_name,
            COALESCE(p.planned_weight, 0) AS planned_weight,
            COALESCE(a.actual_weight, 0) AS actual_weight,
            COALESCE(a.avg_rate, 0) AS actual_rate,
            COALESCE(a.issue_value, 0) AS issue_value,
            ROUND(COALESCE(a.actual_weight, 0) - COALESCE(p.planned_weight, 0), 3) AS variance
        FROM planned p
        LEFT JOIN actual a ON a.yarn_type_id = p.yarn_type_id AND a.item_id = p.item_id
        LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = COALESCE(p.yarn_type_id, a.yarn_type_id)
        LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
        LEFT JOIN item_mst im ON im.item_id = COALESCE(p.item_id, a.item_id)
        LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id

        UNION

        -- Part 2: Actual-only items not in the plan
        SELECT
            a.yarn_type_id,
            COALESCE(yim.item_name, jym.jute_yarn_name) AS yarn_type_name,
            a.item_id,
            im.item_name,
            im.item_grp_id,
            COALESCE(igm.item_grp_name) AS item_group_name,
            0 AS planned_weight,
            COALESCE(a.actual_weight, 0) AS actual_weight,
            COALESCE(a.avg_rate, 0) AS actual_rate,
            COALESCE(a.issue_value, 0) AS issue_value,
            ROUND(COALESCE(a.actual_weight, 0) - 0, 3) AS variance
        FROM actual a
        LEFT JOIN planned p ON p.yarn_type_id = a.yarn_type_id AND p.item_id = a.item_id
        LEFT JOIN jute_yarn_mst jym ON jym.jute_yarn_id = a.yarn_type_id
        LEFT JOIN item_mst yim ON yim.item_id = jym.item_id
        LEFT JOIN item_mst im ON im.item_id = a.item_id
        LEFT JOIN item_grp_mst igm ON igm.item_grp_id = im.item_grp_id
        WHERE p.yarn_type_id IS NULL

        ORDER BY yarn_type_name, item_name
    """
    return text(sql)


def _mr_list_base_from_clause():
    """
    Shared FROM + JOIN + WHERE clauses for the MR list report and its count query.
    Note: the caller supplies the SELECT and pagination/ORDER BY.

    Parameters (bind):
        :co_id (int, required)
        :branch_id (int or NULL) - optional branch filter
        :date_from (str YYYY-MM-DD, required)
        :date_to (str YYYY-MM-DD, required)
        :search_like (str or NULL) - LIKE pattern for party name, vehicle_no,
                                     challan_no, and formatted MR number
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    approved_statuses_sql = ", ".join(str(s) for s in JUTE_MR_APPROVED_STATUSES)
    return f"""
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE bm.co_id = :co_id
          AND jm.status_id IN ({approved_statuses_sql})
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR jm.branch_id = :branch_id)
          AND (
              :search_like IS NULL
              OR COALESCE(pm.supp_name, '') LIKE :search_like
              OR COALESCE(jsm.supplier_name, '') LIKE :search_like
              OR COALESCE(jm.vehicle_no, '') LIKE :search_like
              OR COALESCE(jm.challan_no, '') LIKE :search_like
              OR {mr_num_expr} LIKE :search_like
          )
    """


def get_mr_list_query():
    """
    Query to list Jute MR headers (approved/finalised) for the MR list report.

    Returns one row per MR header with supplier/party, branch, challan, weights,
    totals, and status info. Uses jute_mr_li.total_price as a fallback when
    jute_mr.total_amount / jute_mr.net_total are NULL.

    Parameters (bind):
        :co_id (int, required)
        :branch_id (int or NULL)
        :date_from (str YYYY-MM-DD, required)
        :date_to (str YYYY-MM-DD, required)
        :search_like (str or NULL)
        :limit (int)
        :offset (int)
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    from_clause = _mr_list_base_from_clause()

    sql = f"""
        SELECT
            jm.jute_mr_id,
            {mr_num_expr} AS mr_number,
            jm.jute_mr_date,
            jm.branch_id,
            bm.branch_name,
            jm.jute_supplier_id AS party_id,
            COALESCE(pm.supp_name, jsm.supplier_name) AS party_name,
            jm.vehicle_no,
            jm.challan_no,
            jm.challan_date,
            jm.gross_weight,
            jm.net_weight,
            jm.actual_weight,
            COALESCE(
                jm.total_amount,
                (
                    SELECT COALESCE(SUM(mrli.total_price), 0)
                    FROM jute_mr_li mrli
                    WHERE mrli.jute_mr_id = jm.jute_mr_id
                      AND (mrli.active = 1 OR mrli.active IS NULL)
                )
            ) AS total_amount,
            COALESCE(
                jm.net_total,
                (
                    SELECT COALESCE(SUM(mrli.total_price), 0)
                    FROM jute_mr_li mrli
                    WHERE mrli.jute_mr_id = jm.jute_mr_id
                      AND (mrli.active = 1 OR mrli.active IS NULL)
                )
            ) AS net_total,
            jm.status_id,
            COALESCE(
                sm.status_name,
                CASE jm.status_id
                    WHEN 3 THEN 'Approved'
                    WHEN 13 THEN 'Finalised'
                    ELSE CAST(jm.status_id AS CHAR)
                END
            ) AS status_name
        {from_clause}
        ORDER BY jm.jute_mr_date DESC, jm.jute_mr_id DESC
        LIMIT :limit OFFSET :offset
    """
    return text(sql)


def get_mr_list_count_query():
    """
    Count query for the Jute MR list report (matches get_mr_list_query filters).

    Parameters (bind): same filter params as get_mr_list_query (no limit/offset).
    """
    from_clause = _mr_list_base_from_clause()
    sql = f"""
        SELECT COUNT(*) AS total
        {from_clause}
    """
    return text(sql)


def _jute_tally_base_from_clause():
    """
    Shared FROM + JOIN + WHERE clauses for the Jute Purchase Tally download query
    and its count query. Filters include:
      - co_id scoping via branch_mst.co_id
      - status_id IN (JUTE_MR_APPROVED_STATUSES)
      - jute_mr_date BETWEEN :date_from AND :date_to
      - optional :branch_id filter
      - jute_mr_li.active = 1 AND (status IS NULL OR status NOT IN ('4','6'))

    Parameters (bind):
        :co_id (int, required)
        :branch_id (int or NULL) - optional branch filter
        :date_from (str YYYY-MM-DD, required)
        :date_to (str YYYY-MM-DD, required)
    """
    approved_statuses_sql = ", ".join(str(s) for s in JUTE_MR_APPROVED_STATUSES)
    return f"""
        FROM jute_mr jm
        INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN item_mst im ON im.item_id = mrli.actual_item_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        WHERE bm.co_id = :co_id
          AND jm.status_id IN ({approved_statuses_sql})
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR jm.branch_id = :branch_id)
          AND (mrli.active = 1 OR mrli.active IS NULL)
          AND (mrli.status IS NULL OR mrli.status NOT IN ('4', '6'))
    """


def get_jute_tally_download_query():
    """
    Jute Purchase Tally download query (translated from legacy PHP/MySQL
    `scm_mr_hdr` + `scm_mr_line_item` + `bill_pass` + `tbl_tally_link_file`).

    Produces one row per MR line item with Tally-compatible column names
    (backtick-quoted aliases preserved byte-for-byte so CSV column order
    matches the legacy export). Includes two subqueries:
      - `smh2`: per-MR aggregation (mrdate / mrwt / naramt / noofitems)
      - `tds`:  cumulative naramt window per supplier from FY-start, used
        to compute 194Q TDS at 0.1% once cumulative crosses TDS_CAP_INR.

    naramt formula (preserved from legacy, rate/claim_rate are per-100kg):
        ROUND(accepted_weight / 100 * rate, 0)
            - (accepted_weight / 100 * claim_rate)

    Tally name mappings (since tbl_tally_link_file doesn't exist in VoWERP3):
      - Party Name (ttlf)  -> COALESCE(pm.supp_name, jsm.supplier_name)
      - Item Name (ttlf2)  -> im.item_name
      - Godown (ttlf3)     -> bm.branch_name
      - Claim Ledger (ttlf4) -> literal 'Claim on Gross Purchase'
      - Purchase Ledger (ttlf5) -> literal 'Raw Jute Purchase'

    Parameters (bind):
        :co_id (int, required)
        :branch_id (int or NULL) - optional branch filter
        :date_from (str YYYY-MM-DD, required)
        :date_to (str YYYY-MM-DD, required)
        :fy_start (str YYYY-MM-DD, required) - start of current FY for TDS window
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    po_num_expr = get_jute_po_number_sql_expression()
    approved_statuses_sql = ", ".join(str(s) for s in JUTE_MR_APPROVED_STATUSES)
    tds_cap = int(TDS_CAP_INR)

    # Per-MR aggregation subquery (smh2 in legacy)
    smh2_sql = f"""
        SELECT
            jm_in.jute_mr_id,
            jm_in.jute_mr_date AS mrdate,
            SUM(COALESCE(mrli_in.accepted_weight, 0)) AS mrwt,
            SUM(
                ROUND(COALESCE(mrli_in.accepted_weight, 0) / 100.0
                      * COALESCE(mrli_in.rate, 0), 0)
                - (COALESCE(mrli_in.accepted_weight, 0) / 100.0
                   * COALESCE(mrli_in.claim_rate, 0))
            ) AS naramt,
            COUNT(*) AS noofitems
        FROM jute_mr jm_in
        INNER JOIN jute_mr_li mrli_in
            ON mrli_in.jute_mr_id = jm_in.jute_mr_id
        INNER JOIN branch_mst bm_in ON bm_in.branch_id = jm_in.branch_id
        WHERE bm_in.co_id = :co_id
          AND jm_in.status_id IN ({approved_statuses_sql})
          AND jm_in.jute_mr_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR jm_in.branch_id = :branch_id)
          AND (mrli_in.active = 1 OR mrli_in.active IS NULL)
          AND (mrli_in.status IS NULL OR mrli_in.status NOT IN ('4', '6'))
        GROUP BY jm_in.jute_mr_id, jm_in.jute_mr_date
    """

    # Cumulative TDS window subquery per supplier from :fy_start (tds in legacy)
    tds_sql = f"""
        SELECT
            x.party_key,
            x.jute_mr_id,
            x.mrdate,
            x.naramt,
            ROUND(
                SUM(x.naramt) OVER (
                    PARTITION BY x.party_key
                    ORDER BY x.mrdate, x.jute_mr_id
                    ROWS UNBOUNDED PRECEDING
                ),
                2
            ) AS cumulative_naramt
        FROM (
            SELECT
                COALESCE(pm_t.supp_name, jsm_t.supplier_name, '') AS party_key,
                jm_t.jute_mr_id,
                jm_t.jute_mr_date AS mrdate,
                ROUND(
                    SUM(
                        ROUND(COALESCE(mrli_t.accepted_weight, 0) / 100.0
                              * COALESCE(mrli_t.rate, 0), 0)
                        - (COALESCE(mrli_t.accepted_weight, 0) / 100.0
                           * COALESCE(mrli_t.claim_rate, 0))
                    ),
                    2
                ) AS naramt
            FROM jute_mr jm_t
            INNER JOIN jute_mr_li mrli_t
                ON mrli_t.jute_mr_id = jm_t.jute_mr_id
            INNER JOIN branch_mst bm_t ON bm_t.branch_id = jm_t.branch_id
            LEFT JOIN jute_supplier_mst jsm_t
                ON jsm_t.supplier_id = jm_t.jute_supplier_id
            LEFT JOIN party_mst pm_t ON pm_t.party_id = jm_t.party_id
            WHERE bm_t.co_id = :co_id
              AND jm_t.status_id IN ({approved_statuses_sql})
              AND jm_t.jute_mr_date >= :fy_start
              AND jm_t.jute_mr_date <= :date_to
              AND (:branch_id IS NULL OR jm_t.branch_id = :branch_id)
              AND (mrli_t.active = 1 OR mrli_t.active IS NULL)
              AND (mrli_t.status IS NULL OR mrli_t.status NOT IN ('4', '6'))
            GROUP BY party_key, jm_t.jute_mr_id, jm_t.jute_mr_date
        ) x
    """

    # TDS Amount and TDS Deducted share the same case logic
    # (legacy: $tdscap = TDS_CAP_INR; 0.1% = 0.001)
    tds_amount_case = f"""
        CASE
            WHEN (COALESCE(tds.cumulative_naramt, 0) - COALESCE(smh2.naramt, 0)) > {tds_cap}
                THEN 0 - ROUND(COALESCE(smh2.naramt, 0) * 0.1 / 100, 0)
            WHEN (COALESCE(tds.cumulative_naramt, 0) - COALESCE(smh2.naramt, 0)) < {tds_cap}
                 AND COALESCE(tds.cumulative_naramt, 0) > {tds_cap}
                THEN 0 - ROUND(((COALESCE(tds.cumulative_naramt, 0) - {tds_cap}) * 0.1 / 100), 0)
            ELSE 0
        END
    """

    tds_deducted_case = f"""
        CASE
            WHEN (COALESCE(tds.cumulative_naramt, 0) - COALESCE(smh2.naramt, 0)) > {tds_cap}
                THEN ROUND(COALESCE(smh2.naramt, 0) * 0.1 / 100, 0)
            WHEN (COALESCE(tds.cumulative_naramt, 0) - COALESCE(smh2.naramt, 0)) < {tds_cap}
                 AND COALESCE(tds.cumulative_naramt, 0) > {tds_cap}
                THEN ROUND(((COALESCE(tds.cumulative_naramt, 0) - {tds_cap}) * 0.1 / 100), 0)
            ELSE 0
        END
    """

    # bales count for Item Description: sum when unit_conversion='BALE'
    bales_expr = (
        "CASE WHEN UPPER(COALESCE(mrli.unit_conversion,'')) = 'BALE' "
        "THEN COALESCE(mrli.actual_qty, 0) ELSE 0 END"
    )

    sql = f"""
        SELECT
            {mr_num_expr} AS `Vch No.`,
            'Purchase' AS `Vch Type`,
            DATE_FORMAT(smh2.mrdate, '%d-%m-%Y') AS `Date`,
            COALESCE(jm.invoice_no, '') AS `Supplier Inv No`,
            DATE_FORMAT(jm.invoice_date, '%d-%m-%Y') AS `Supplier Inv Date`,
            {mr_num_expr} AS `Receipt Note No`,
            DATE_FORMAT(smh2.mrdate, '%d-%m-%Y') AS `Receipt Note Date`,
            {po_num_expr} AS `Order No`,
            DATE_FORMAT(jp.po_date, '%d-%m-%Y') AS `Order Date`,
            COALESCE(pm.supp_name, jsm.supplier_name, '') AS `Party Name`,
            '' AS `Registration Type`,
            '' AS `GSTIN No`,
            '' AS `Country`,
            '' AS `State`,
            '' AS `Pincode`,
            '' AS `Address 1`,
            '' AS `Address 2`,
            '' AS `Address 3`,
            'Purchase of Raw Jute' AS `Purchase Ledger`,
            '' AS `Purchase Ledger Description`,
            COALESCE(im.item_name, '') AS `Item Name`,
            CASE
                WHEN {bales_expr} > 0
                    THEN CONCAT('Raw Jute: ', {bales_expr}, ' Bales')
                ELSE 'Raw Jute:  Loose'
            END AS `Item Description`,
            '' AS `UNITS.`,
            '' AS `Tracking No`,
            '' AS `Order No_1`,
            '' AS `Order Due Date`,
            COALESCE(bm.branch_name, '') AS `Godown`,
            {mr_num_expr} AS `Batch`,
            COALESCE(mrli.accepted_weight, 0) AS `Qty`,
            ROUND(COALESCE(mrli.rate, 0) / 100, 2) AS `Rate`,
            ROUND(
                COALESCE(mrli.rate, 0) / 100
                * COALESCE(mrli.accepted_weight, 0),
                0
            ) AS `Amt`,
            '' AS `Amount1`,
            '' AS `Discount Ledger`,
            '' AS `Discount Ledger Description`,
            '' AS `Amount1_1`,
            CASE
                WHEN COALESCE(mrli.claim_rate, 0) > 0
                    THEN 'Claim on Gross Purchase'
                ELSE ''
            END AS `Additional Ledger`,
            CASE
                WHEN COALESCE(mrli.claim_rate, 0) > 0
                    THEN CONCAT(
                        '(Q): ',
                        COALESCE(im.item_name, ''),
                        '-',
                        COALESCE(mrli.accepted_weight, 0),
                        ' X Rs. ',
                        COALESCE(mrli.claim_rate, 0),
                        ' /-'
                    )
                ELSE ''
            END AS `Additional Ledger Description`,
            CASE
                WHEN COALESCE(mrli.claim_rate, 0) > 0
                    THEN 0 - ROUND(
                        (COALESCE(mrli.claim_rate, 0) / 100)
                        * COALESCE(mrli.accepted_weight, 0),
                        0
                    )
                ELSE ''
            END AS `Amount`,
            '' AS `INPUT IGST`,
            '' AS `INPUT CGST`,
            '' AS `INPUT SGST`,
            '' AS `Roundoff amt`,
            '' AS `Total`,
            CONCAT(
                COALESCE(jm.invoice_no, ''),
                '/',
                {mr_num_expr}
            ) AS `Ref: No.`,
            180 AS `Due on`,
            CASE
                WHEN COALESCE(mrli.claim_rate, 0) > 0
                    THEN 0 - ROUND(
                        (COALESCE(mrli.claim_rate, 0) / 100)
                        * COALESCE(mrli.accepted_weight, 0),
                        0
                    )
                ELSE ''
            END AS `Amount (dup2)`,
            '' AS `e Way Bill No.`,
            '' AS `e Way Bill Date`,
            '' AS `Sub Type`,
            '' AS `Doc Type`,
            '' AS `Status Of eway Bill`,
            '' AS `Mode`,
            '' AS `Distance (In KM)`,
            '' AS `Transporter Name`,
            '' AS `Vehicle No.`,
            '' AS `Doc/Loading/RR/AirWay No.`,
            '' AS `Date_1`,
            '' AS `Transporter ID`,
            '' AS `Consignor:`,
            '' AS `Address 1_1`,
            '' AS `Address 2_1`,
            '' AS `Pin Code`,
            '' AS `Place`,
            '' AS `State_1`,
            '' AS `GSTIN/UIN`,
            '' AS `Consignee`,
            '' AS `Address 1_2`,
            '' AS `Address 2_2`,
            '' AS `To Place (Destination )`,
            '' AS `Pin`,
            '' AS `State_2`,
            '' AS `GSTIN/UIN_1`,
            CONCAT(
                'Being ', COALESCE(smh2.mrwt, 0), ' Kg. Raw Jute Purchase From ',
                COALESCE(pm.supp_name, jsm.supplier_name, ''),
                ' Against Inv: ', COALESCE(jm.invoice_no, ''),
                ' Dt :', IFNULL(DATE_FORMAT(smh2.mrdate, '%d-%m-%Y'), ''),
                ' CH: ', IFNULL(jm.challan_no, ''),
                ',Dt: ', IFNULL(DATE_FORMAT(jm.challan_date, '%d-%m-%Y'), ''),
                ',Ref.NO. ', {mr_num_expr},
                ' Amt Rs. ', COALESCE(smh2.naramt, 0), ' /-'
            ) AS `Narration`,
            '' AS `TALLYIMPORTSTATUS`,
            COALESCE(tds.cumulative_naramt, 0) AS `Cumulative Amount`,
            {tds_amount_case} AS `tds Amount`,
            COALESCE(smh2.noofitems, 0) AS `noofitems`,
            COALESCE(smh2.naramt, 0) AS `MR Amount`,
            {tds_deducted_case} AS `TDS Deducted`
        FROM jute_mr jm
        INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN item_mst im ON im.item_id = mrli.actual_item_id
        LEFT JOIN jute_po jp ON jp.jute_po_id = jm.po_id
        LEFT JOIN (
            {smh2_sql}
        ) smh2 ON smh2.jute_mr_id = jm.jute_mr_id
        LEFT JOIN (
            {tds_sql}
        ) tds ON tds.jute_mr_id = jm.jute_mr_id
        WHERE bm.co_id = :co_id
          AND jm.status_id IN ({approved_statuses_sql})
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR jm.branch_id = :branch_id)
          AND (mrli.active = 1 OR mrli.active IS NULL)
          AND (mrli.status IS NULL OR mrli.status NOT IN ('4', '6'))
        ORDER BY jm.invoice_date, jm.jute_mr_id, mrli.jute_mr_li_id
        LIMIT 10001
    """
    return text(sql)


def get_jute_tally_download_count_query():
    """
    Count query for the Jute Tally download — counts the number of output rows
    (one per MR line item) that would appear in get_jute_tally_download_query.

    Used to enforce the 10,000-row cap before running the (expensive) main query.

    Parameters (bind): :co_id, :branch_id, :date_from, :date_to (same as main).
    """
    from_clause = _jute_tally_base_from_clause()
    sql = f"""
        SELECT COUNT(*) AS total
        {from_clause}
    """
    return text(sql)


def get_jute_tally_download_items_per_mr_query():
    """
    Returns per-MR item counts for MRs in the tally-download scope.

    Used by the xlsx builder to compute the total number of emitted rows
    (sum of max(6, items_per_mr + 2)) and enforce the row cap before running
    the expensive main query.

    Parameters (bind): :co_id, :branch_id, :date_from, :date_to.

    Returns rows of (jute_mr_id, item_count).
    """
    from_clause = _jute_tally_base_from_clause()
    sql = f"""
        SELECT jm.jute_mr_id AS jute_mr_id, COUNT(*) AS item_count
        {from_clause}
        GROUP BY jm.jute_mr_id
    """
    return text(sql)


def get_jute_tally_check_list_query():
    """
    Check List sheet query for the Jute Purchase Tally download.

    Returns 12 columns per MR line item:
      company_id, mrdate, mr_print_no, invoice_no, invoice_date,
      supp_name (upper-cased), supptally (original casing),
      jute_quality, qualitytally, godowsntally,
      claimtally (literal 'Claim on Gross Purchase'),
      purtally (literal 'Purchase of Raw Jute').

    One row per MR × line-item, same scope filter as get_jute_tally_download_query.
    VoWERP3 doesn't carry a dedicated tally-link table, so `supptally` falls back
    to the VOW party/supplier name in original casing and `jute_quality` /
    `qualitytally` both map to `im.item_name` (no short/alt name available).

    Parameters (bind):
        :co_id (int, required)
        :branch_id (int or NULL) - optional branch filter
        :date_from (str YYYY-MM-DD, required)
        :date_to (str YYYY-MM-DD, required)
    """
    mr_num_expr = get_jute_mr_number_sql_expression()
    approved_statuses_sql = ", ".join(str(s) for s in JUTE_MR_APPROVED_STATUSES)
    sql = f"""
        SELECT
            bm.co_id AS company_id,
            jm.jute_mr_date AS mrdate,
            {mr_num_expr} AS mr_print_no,
            COALESCE(jm.invoice_no, '') AS invoice_no,
            jm.invoice_date AS invoice_date,
            UPPER(COALESCE(pm.supp_name, jsm.supplier_name, '')) AS supp_name,
            COALESCE(pm.supp_name, jsm.supplier_name, '') AS supptally,
            COALESCE(im.item_name, '') AS jute_quality,
            COALESCE(im.item_name, '') AS qualitytally,
            COALESCE(bm.branch_name, '') AS godowsntally,
            'Claim on Gross Purchase' AS claimtally,
            'Purchase of Raw Jute' AS purtally
        FROM jute_mr jm
        INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN party_mst pm ON pm.party_id = jm.party_id
        LEFT JOIN item_mst im ON im.item_id = mrli.actual_item_id
        WHERE bm.co_id = :co_id
          AND jm.status_id IN ({approved_statuses_sql})
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND (:branch_id IS NULL OR jm.branch_id = :branch_id)
          AND (mrli.active = 1 OR mrli.active IS NULL)
          AND (mrli.status IS NULL OR mrli.status NOT IN ('4', '6'))
        ORDER BY jm.invoice_date, jm.jute_mr_id, mrli.jute_mr_li_id
    """
    return text(sql)


def get_jute_qty_wise_report_query():
    """
    Jute Quantity Wise report (#2) — opening / receipt / issue / closing per
    jute quality (item) over a date range, in both weight (kg) and quantity.

    Also backs the Inventory Snapshot (#14): pass an early :date_from (e.g. the
    financial-year start) and :date_to = the as-of date.

    Receipts: jute_mr.out_date + jute_mr_li.actual_weight / actual_qty
              (status 1/3/13, active lines). Issues: jute_issue.issue_date +
              weight / quantity (status 1/3), item via
              COALESCE(ji.item_id, mrli.actual_item_id) — same conventions as
              get_jute_stock_report_query().

    Parameters: :branch_id (int), :date_from (str 'YYYY-MM-DD'),
                :date_to (str 'YYYY-MM-DD')
    """
    sql = _group_path_cte() + """,
        -- Net stock before date_from -> opening
        receipt_before AS (
            SELECT mrli.actual_item_id AS item_id,
                   ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(mrli.actual_qty), 0), 3) AS qty
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date < :date_from
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        issue_before AS (
            SELECT COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                   ROUND(COALESCE(SUM(ji.weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(ji.quantity), 0), 3) AS qty
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date < :date_from
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        -- Movement within [date_from, date_to]
        receipt_range AS (
            SELECT mrli.actual_item_id AS item_id,
                   ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(mrli.actual_qty), 0), 3) AS qty
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date BETWEEN :date_from AND :date_to
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        issue_range AS (
            SELECT COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                   ROUND(COALESCE(SUM(ji.weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(ji.quantity), 0), 3) AS qty
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date BETWEEN :date_from AND :date_to
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        )

        SELECT
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS item_group_name,
            im.item_id,
            im.item_name,
            ROUND(COALESCE(rb.wt, 0) - COALESCE(ib.wt, 0), 3) AS opening_weight,
            ROUND(COALESCE(rb.qty, 0) - COALESCE(ib.qty, 0), 3) AS opening_qty,
            ROUND(COALESCE(rr.wt, 0), 3) AS receipt_weight,
            ROUND(COALESCE(rr.qty, 0), 3) AS receipt_qty,
            ROUND(COALESCE(ir.wt, 0), 3) AS issue_weight,
            ROUND(COALESCE(ir.qty, 0), 3) AS issue_qty,
            ROUND(COALESCE(rb.wt, 0) - COALESCE(ib.wt, 0) + COALESCE(rr.wt, 0) - COALESCE(ir.wt, 0), 3) AS closing_weight,
            ROUND(COALESCE(rb.qty, 0) - COALESCE(ib.qty, 0) + COALESCE(rr.qty, 0) - COALESCE(ir.qty, 0), 3) AS closing_qty
        FROM item_mst im
        INNER JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        LEFT JOIN receipt_before rb ON rb.item_id = im.item_id
        LEFT JOIN issue_before ib ON ib.item_id = im.item_id
        LEFT JOIN receipt_range rr ON rr.item_id = im.item_id
        LEFT JOIN issue_range ir ON ir.item_id = im.item_id
        WHERE (
            rb.item_id IS NOT NULL OR ib.item_id IS NOT NULL
            OR rr.item_id IS NOT NULL OR ir.item_id IS NOT NULL
        )
        ORDER BY ig.item_grp_name, im.item_name
    """
    return text(sql)


def get_jute_percent_claims_query():
    """
    Jute Percent Claims (#7) — per-supplier pass/claim counts and percentages.

    An MR is a "claim" if ANY of its active lines has shortage_kgs > 0 OR
    claim_rate > 0; otherwise it "passes". Percentages are by MR count.

    Parameters: :branch_id (int), :date_from, :date_to (str 'YYYY-MM-DD')
    """
    sql = """
        WITH mr_claim AS (
            SELECT
                jm.jute_mr_id,
                jm.jute_supplier_id,
                MAX(CASE
                    WHEN COALESCE(mrli.shortage_kgs, 0) > 0
                      OR COALESCE(mrli.claim_rate, 0) > 0
                    THEN 1 ELSE 0 END) AS is_claim
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.jute_mr_date BETWEEN :date_from AND :date_to
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY jm.jute_mr_id, jm.jute_supplier_id
        )
        SELECT
            mc.jute_supplier_id AS supplier_id,
            COALESCE(jsm.supplier_name, CAST(mc.jute_supplier_id AS CHAR)) AS supplier_name,
            COUNT(*) AS total_mr,
            SUM(CASE WHEN mc.is_claim = 0 THEN 1 ELSE 0 END) AS pass_count,
            SUM(mc.is_claim) AS claim_count,
            ROUND(100 * SUM(CASE WHEN mc.is_claim = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pass_percent,
            ROUND(100 * SUM(mc.is_claim) / COUNT(*), 2) AS claim_percent
        FROM mr_claim mc
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = mc.jute_supplier_id
        GROUP BY mc.jute_supplier_id, supplier_name
        ORDER BY supplier_name
    """
    return text(sql)


def get_jute_mukham_moisture_query():
    """
    Mukham Moisture (#9) — per supplier + mukam, average supplied moisture vs
    allowed moisture and the deviation.

    Supplied moisture = AVG(jute_moisture_rdg.moisture_percentage) (authoritative
    numeric reading); allowed = AVG(jute_mr_li.allowable_moisture).

    Parameters: :branch_id (int), :date_from, :date_to (str 'YYYY-MM-DD')
    """
    sql = """
        SELECT
            jm.jute_supplier_id AS supplier_id,
            COALESCE(jsm.supplier_name, CAST(jm.jute_supplier_id AS CHAR)) AS supplier_name,
            COALESCE(mk.mukam_name, CAST(jm.mukam_id AS CHAR)) AS mukam_name,
            ROUND(AVG(jmr.moisture_percentage), 2) AS avg_supplied_moisture,
            ROUND(AVG(mrli.allowable_moisture), 2) AS avg_allowed_moisture,
            ROUND(AVG(jmr.moisture_percentage) - AVG(mrli.allowable_moisture), 2) AS deviation
        FROM jute_mr jm
        INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
        INNER JOIN jute_moisture_rdg jmr ON jmr.jute_mr_li_id = mrli.jute_mr_li_id
        LEFT JOIN jute_supplier_mst jsm ON jsm.supplier_id = jm.jute_supplier_id
        LEFT JOIN jute_mukam_mst mk ON mk.mukam_id = jm.mukam_id
        WHERE jm.branch_id = :branch_id
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND jm.status_id IN (1, 3, 13)
          AND (mrli.active = 1 OR mrli.active IS NULL)
        GROUP BY jm.jute_supplier_id, supplier_name, jm.mukam_id, mukam_name
        ORDER BY supplier_name, mukam_name
    """
    return text(sql)


def get_jute_txn_summary_query(txn_type: str = "ALL"):
    """
    Jute Issue & Receipt Summary (#3) — transaction-level rows (one per MR line
    for receipts, one per issue for issues) over a date range.

    txn_type: 'R' (receipts only), 'I' (issues only), or 'ALL' (both).
    Issue rate has no source column (jute_issue has no rate) -> NULL.
    # ponytail: issue 'rate' left NULL — derive from issue_value/weight later if needed.

    Parameters: :branch_id (int), :date_from, :date_to (str 'YYYY-MM-DD'),
                :search_like (str or NULL — matches formatted MR number)
    """
    mr_num = get_jute_mr_number_sql_expression()

    receipts = f"""
        SELECT
            'R' AS txn_type,
            jm.jute_mr_date AS txn_date,
            {mr_num} AS mr_number,
            im.item_name AS quality,
            ROUND(mrli.actual_weight, 3) AS weight,
            ROUND(mrli.actual_qty, 3) AS qty,
            ROUND(mrli.actual_rate, 2) AS rate,
            ROUND(mrli.total_price, 2) AS value,
            COALESCE(sm.status_name, CAST(jm.status_id AS CHAR)) AS status_name
        FROM jute_mr jm
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
        LEFT JOIN item_mst im ON im.item_id = mrli.actual_item_id
        LEFT JOIN status_mst sm ON sm.status_id = jm.status_id
        WHERE jm.branch_id = :branch_id
          AND jm.jute_mr_date BETWEEN :date_from AND :date_to
          AND jm.status_id IN (1, 3, 13)
          AND (mrli.active = 1 OR mrli.active IS NULL)
          AND (:search_like IS NULL OR {mr_num} LIKE :search_like)
    """

    issues = f"""
        SELECT
            'I' AS txn_type,
            ji.issue_date AS txn_date,
            {mr_num} AS mr_number,
            COALESCE(im.item_name, im2.item_name) AS quality,
            ROUND(ji.weight, 3) AS weight,
            ROUND(ji.quantity, 3) AS qty,
            NULL AS rate,
            ROUND(ji.issue_value, 2) AS value,
            COALESCE(sm.status_name, CAST(ji.status_id AS CHAR)) AS status_name
        FROM jute_issue ji
        LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
        LEFT JOIN jute_mr jm ON jm.jute_mr_id = mrli.jute_mr_id
        LEFT JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        LEFT JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN item_mst im ON im.item_id = ji.item_id
        LEFT JOIN item_mst im2 ON im2.item_id = mrli.actual_item_id
        LEFT JOIN status_mst sm ON sm.status_id = ji.status_id
        WHERE ji.branch_id = :branch_id
          AND ji.issue_date BETWEEN :date_from AND :date_to
          AND ji.status_id IN (1, 3)
          AND (:search_like IS NULL OR {mr_num} LIKE :search_like)
    """

    t = (txn_type or "ALL").upper()
    if t == "R":
        sql = receipts + "\n        ORDER BY txn_date, mr_number"
    elif t == "I":
        sql = issues + "\n        ORDER BY txn_date, mr_number"
    else:
        sql = f"""
        SELECT * FROM (
            {receipts}
            UNION ALL
            {issues}
        ) t
        ORDER BY t.txn_date, t.txn_type, t.mr_number
        """
    return text(sql)


def get_jute_period_wise_query(period: str = "month"):
    """
    Jute Month Wise (#10) / Day Wise (#11) — receipt vs issue weight & qty
    aggregated per period over a date range.

    period: 'month' -> 'YYYY-MM', 'day' -> 'YYYY-MM-DD' buckets.
    Receipts keyed on jute_mr.out_date; issues on jute_issue.issue_date.

    Parameters: :branch_id (int), :date_from, :date_to (str 'YYYY-MM-DD')
    """
    if (period or "month").lower() == "day":
        recv_p = "CAST(DATE(jm.out_date) AS CHAR)"
        iss_p = "CAST(DATE(ji.issue_date) AS CHAR)"
    else:
        recv_p = "CONCAT(YEAR(jm.out_date), '-', LPAD(MONTH(jm.out_date), 2, '0'))"
        iss_p = "CONCAT(YEAR(ji.issue_date), '-', LPAD(MONTH(ji.issue_date), 2, '0'))"

    sql = f"""
        WITH recv AS (
            SELECT {recv_p} AS period,
                   ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(mrli.actual_qty), 0), 3) AS qty
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date BETWEEN :date_from AND :date_to
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY period
        ),
        iss AS (
            SELECT {iss_p} AS period,
                   ROUND(COALESCE(SUM(ji.weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(ji.quantity), 0), 3) AS qty
            FROM jute_issue ji
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date BETWEEN :date_from AND :date_to
              AND ji.status_id IN (1, 3)
            GROUP BY period
        )
        SELECT
            p.period,
            ROUND(COALESCE(r.wt, 0), 3) AS receipt_weight,
            ROUND(COALESCE(r.qty, 0), 3) AS receipt_qty,
            ROUND(COALESCE(i.wt, 0), 3) AS issue_weight,
            ROUND(COALESCE(i.qty, 0), 3) AS issue_qty
        FROM (SELECT period FROM recv UNION SELECT period FROM iss) p
        LEFT JOIN recv r ON r.period = p.period
        LEFT JOIN iss i ON i.period = p.period
        ORDER BY p.period
    """
    return text(sql)


# ---------------------------------------------------------------------------
# Cluster B — outstanding-balance reports over vw_jute_stock_outstanding.
# The view nets ALL issues per MR line (no as-of date, no status filter), so
# these are CURRENT-position reports keyed on branch only.
# ponytail: view ignores issue status + as-of date; acceptable as the
# established stock source — add a status-aware view if exactness is needed.
# ---------------------------------------------------------------------------

def _outstanding_base_from_where():
    """Shared FROM/JOIN/WHERE for the Cluster B reports. Needs :branch_id."""
    return """
        FROM vw_jute_stock_outstanding v
        JOIN jute_mr_li li ON li.jute_mr_li_id = v.jute_mr_li_id
        JOIN jute_mr jm ON jm.jute_mr_id = li.jute_mr_id
        INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
        INNER JOIN co_mst cm ON cm.co_id = bm.co_id
        LEFT JOIN item_mst im ON im.item_id = li.actual_item_id
        WHERE v.branch_id = :branch_id
          AND jm.status_id IN (1, 3, 13)
    """


def get_jute_mr_in_stock_query():
    """
    Jute MR in Stock (#4) — per MR-line outstanding balance, only lines still
    holding stock. Parameters: :branch_id (int).
    """
    mr_num = get_jute_mr_number_sql_expression()
    sql = f"""
        SELECT
            v.jute_mr_li_id,
            {mr_num} AS mr_number,
            jm.jute_mr_date,
            v.jute_gate_entry_no,
            v.warehouse_name,
            COALESCE(im.item_name, v.actual_quality) AS quality,
            ROUND(v.actual_qty, 3) AS received_qty,
            ROUND(v.actual_weight, 3) AS received_weight,
            ROUND(v.bal_qty, 3) AS balance_qty,
            ROUND(v.bal_weight, 3) AS balance_weight
        {_outstanding_base_from_where()}
          AND (ROUND(v.bal_qty, 0) != 0 OR ROUND(v.bal_weight, 0) != 0)
        ORDER BY jm.jute_mr_date DESC, v.jute_mr_li_id
    """
    return text(sql)


def get_jute_mr_wise_query():
    """
    MR Wise (#6) — per MR-line received vs issued vs balance (all lines).
    Parameters: :branch_id (int).
    """
    mr_num = get_jute_mr_number_sql_expression()
    sql = f"""
        SELECT
            v.jute_mr_li_id,
            {mr_num} AS mr_number,
            jm.jute_mr_date,
            v.warehouse_name,
            COALESCE(im.item_name, v.actual_quality) AS quality,
            ROUND(v.actual_qty, 3) AS received_qty,
            ROUND(v.actual_weight, 3) AS received_weight,
            ROUND(v.actual_qty - v.bal_qty, 3) AS issued_qty,
            ROUND(v.actual_weight - v.bal_weight, 3) AS issued_weight,
            ROUND(v.bal_qty, 3) AS balance_qty,
            ROUND(v.bal_weight, 3) AS balance_weight
        {_outstanding_base_from_where()}
        ORDER BY jm.jute_mr_date DESC, v.jute_mr_li_id
    """
    return text(sql)


def get_jute_godown_wise_query():
    """
    Godown Wise Stock (#5) — outstanding balance grouped by warehouse + quality.
    Parameters: :branch_id (int).
    """
    sql = f"""
        SELECT
            COALESCE(v.warehouse_name, 'Unknown') AS warehouse_name,
            COALESCE(im.item_name, v.actual_quality) AS quality,
            ROUND(SUM(v.bal_qty), 3) AS balance_qty,
            ROUND(SUM(v.bal_weight), 3) AS balance_weight
        {_outstanding_base_from_where()}
        GROUP BY COALESCE(v.warehouse_name, 'Unknown'), COALESCE(im.item_name, v.actual_quality)
        HAVING ROUND(SUM(v.bal_qty), 0) != 0 OR ROUND(SUM(v.bal_weight), 0) != 0
        ORDER BY warehouse_name, quality
    """
    return text(sql)


def get_jute_with_value_query():
    """
    Jute with Value (#1) — opening/receipt/issue/closing per quality over a date
    range, plus receipt value, issue value and average issue rate.

    Sold columns are 0 — there is no raw-jute sale source in the current schema.
    # ponytail: sold_weight/sold_qty hardcoded 0 (no raw-jute sale table).

    Parameters: :branch_id (int), :date_from, :date_to (str 'YYYY-MM-DD')
    """
    sql = _group_path_cte() + """,
        receipt_before AS (
            SELECT mrli.actual_item_id AS item_id,
                   ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(mrli.actual_qty), 0), 3) AS qty
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id AND jm.out_date < :date_from
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        issue_before AS (
            SELECT COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                   ROUND(COALESCE(SUM(ji.weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(ji.quantity), 0), 3) AS qty
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id AND ji.issue_date < :date_from
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        ),
        receipt_range AS (
            SELECT mrli.actual_item_id AS item_id,
                   ROUND(COALESCE(SUM(mrli.actual_weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(mrli.actual_qty), 0), 3) AS qty,
                   ROUND(COALESCE(SUM(mrli.total_price), 0), 2) AS val
            FROM jute_mr jm
            INNER JOIN jute_mr_li mrli ON mrli.jute_mr_id = jm.jute_mr_id
            WHERE jm.branch_id = :branch_id
              AND jm.out_date BETWEEN :date_from AND :date_to
              AND jm.status_id IN (1, 3, 13)
              AND (mrli.active = 1 OR mrli.active IS NULL)
            GROUP BY mrli.actual_item_id
        ),
        issue_range AS (
            SELECT COALESCE(ji.item_id, mrli.actual_item_id) AS item_id,
                   ROUND(COALESCE(SUM(ji.weight), 0), 3) AS wt,
                   ROUND(COALESCE(SUM(ji.quantity), 0), 3) AS qty,
                   ROUND(COALESCE(SUM(ji.issue_value), 0), 2) AS val
            FROM jute_issue ji
            LEFT JOIN jute_mr_li mrli ON mrli.jute_mr_li_id = ji.jute_mr_li_id
            WHERE ji.branch_id = :branch_id
              AND ji.issue_date BETWEEN :date_from AND :date_to
              AND ji.status_id IN (1, 3)
            GROUP BY COALESCE(ji.item_id, mrli.actual_item_id)
        )

        SELECT
            im.item_grp_id,
            COALESCE(fgp.item_grp_name_path, ig.item_grp_name) AS item_group_name,
            im.item_id,
            im.item_name,
            ROUND(COALESCE(rb.wt, 0) - COALESCE(ib.wt, 0), 3) AS opening_weight,
            ROUND(COALESCE(rb.qty, 0) - COALESCE(ib.qty, 0), 3) AS opening_qty,
            ROUND(COALESCE(rr.wt, 0), 3) AS receipt_weight,
            ROUND(COALESCE(rr.qty, 0), 3) AS receipt_qty,
            ROUND(COALESCE(rr.val, 0), 2) AS receipt_value,
            ROUND(COALESCE(ir.wt, 0), 3) AS issue_weight,
            ROUND(COALESCE(ir.qty, 0), 3) AS issue_qty,
            ROUND(COALESCE(ir.val, 0), 2) AS issue_value,
            0 AS sold_weight,
            0 AS sold_qty,
            ROUND(COALESCE(rb.wt, 0) - COALESCE(ib.wt, 0) + COALESCE(rr.wt, 0) - COALESCE(ir.wt, 0), 3) AS closing_weight,
            ROUND(COALESCE(rb.qty, 0) - COALESCE(ib.qty, 0) + COALESCE(rr.qty, 0) - COALESCE(ir.qty, 0), 3) AS closing_qty,
            ROUND(COALESCE(ir.val, 0) / NULLIF(COALESCE(ir.wt, 0) / 100, 0), 2) AS avg_issue_rate
        FROM item_mst im
        INNER JOIN item_grp_mst ig ON ig.item_grp_id = im.item_grp_id
        LEFT JOIN full_group_paths fgp ON fgp.item_grp_id = im.item_grp_id
        LEFT JOIN receipt_before rb ON rb.item_id = im.item_id
        LEFT JOIN issue_before ib ON ib.item_id = im.item_id
        LEFT JOIN receipt_range rr ON rr.item_id = im.item_id
        LEFT JOIN issue_range ir ON ir.item_id = im.item_id
        WHERE (
            rb.item_id IS NOT NULL OR ib.item_id IS NOT NULL
            OR rr.item_id IS NOT NULL OR ir.item_id IS NOT NULL
        )
        ORDER BY ig.item_grp_name, im.item_name
    """
    return text(sql)
