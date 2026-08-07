"""
SQL query functions for the accounting module (CRUD operations).
Covers: ledger groups, ledgers, vouchers, bill references, and supporting tables.
"""

from sqlalchemy.sql import text


# =============================================================================
# CHART OF ACCOUNTS - LEDGER GROUPS
# =============================================================================

def get_ledger_groups(co_id: int = None):
    """Get ledger group tree with parent group info."""
    sql = """SELECT
        alg.acc_ledger_group_id,
        alg.co_id,
        alg.parent_group_id,
        pg.group_name AS parent_group_name,
        alg.group_name,
        alg.group_code,
        alg.nature,
        alg.affects_gross_profit,
        alg.is_revenue,
        alg.normal_balance,
        alg.is_party_group,
        alg.is_system_group,
        alg.sequence_no
    FROM acc_ledger_group alg
    LEFT JOIN acc_ledger_group pg ON pg.acc_ledger_group_id = alg.parent_group_id
    WHERE alg.active = 1
        AND (:co_id IS NULL OR alg.co_id = :co_id)
    ORDER BY alg.sequence_no, alg.group_name;"""
    return text(sql)


# =============================================================================
# CHART OF ACCOUNTS - LEDGERS
# =============================================================================

def get_ledgers(co_id: int = None):
    """Get ledgers with group name. Supports optional type filter and search."""
    sql = """SELECT
        al.acc_ledger_id,
        al.co_id,
        al.acc_ledger_group_id,
        alg.group_name,
        alg.nature AS group_nature,
        al.ledger_name,
        al.ledger_code,
        al.ledger_type,
        al.party_id,
        pm.supp_name AS party_name,
        al.credit_days,
        al.credit_limit,
        al.opening_balance,
        al.opening_balance_type,
        al.opening_fy_id,
        al.gst_applicable,
        al.hsn_sac_code,
        al.is_system_ledger,
        al.is_related_party
    FROM acc_ledger al
    LEFT JOIN acc_ledger_group alg ON alg.acc_ledger_group_id = al.acc_ledger_group_id
    LEFT JOIN party_mst pm ON pm.party_id = al.party_id
    WHERE al.active = 1
        AND (:co_id IS NULL OR al.co_id = :co_id)
        AND (:ledger_type IS NULL OR al.ledger_type = :ledger_type)
        AND (
            :search IS NULL
            OR al.ledger_name LIKE :search
            OR al.ledger_code LIKE :search
        )
    ORDER BY alg.group_name, al.ledger_name;"""
    return text(sql)


def get_ledger_by_id(ledger_id: int = None):
    """Get single ledger by ID with group details."""
    sql = """SELECT
        al.acc_ledger_id,
        al.co_id,
        al.acc_ledger_group_id,
        alg.group_name,
        alg.nature AS group_nature,
        alg.is_revenue,
        alg.normal_balance AS group_normal_balance,
        al.ledger_name,
        al.ledger_code,
        al.ledger_type,
        al.party_id,
        pm.supp_name AS party_name,
        al.credit_days,
        al.credit_limit,
        al.opening_balance,
        al.opening_balance_type,
        al.opening_fy_id,
        al.gst_applicable,
        al.hsn_sac_code,
        al.is_system_ledger,
        al.is_related_party
    FROM acc_ledger al
    LEFT JOIN acc_ledger_group alg ON alg.acc_ledger_group_id = al.acc_ledger_group_id
    LEFT JOIN party_mst pm ON pm.party_id = al.party_id
    WHERE al.active = 1
        AND al.acc_ledger_id = :ledger_id;"""
    return text(sql)


def get_ledger_by_party(co_id: int = None, party_id: int = None):
    """Find ledger linked to a specific party."""
    sql = """SELECT
        al.acc_ledger_id,
        al.ledger_name,
        al.ledger_code,
        al.ledger_type,
        al.acc_ledger_group_id,
        alg.group_name,
        al.party_id,
        al.credit_days,
        al.credit_limit,
        al.opening_balance,
        al.opening_balance_type
    FROM acc_ledger al
    LEFT JOIN acc_ledger_group alg ON alg.acc_ledger_group_id = al.acc_ledger_group_id
    WHERE al.active = 1
        AND al.co_id = :co_id
        AND al.party_id = :party_id;"""
    return text(sql)


def get_parties_for_dropdown():
    """Get active parties for dropdown/autocomplete in ledger creation.
    Returns party_id, supp_name, supp_code (up to 50 results).
    """
    sql = """SELECT
        pm.party_id,
        pm.supp_name,
        pm.supp_code
    FROM party_mst pm
    WHERE pm.active = 1
        AND (:co_id IS NULL OR pm.co_id = :co_id)
        AND (:search IS NULL OR pm.supp_name LIKE :search OR pm.supp_code LIKE :search)
    ORDER BY pm.supp_name
    LIMIT 50;"""
    return text(sql)


# =============================================================================
# VOUCHER TYPES & FINANCIAL YEAR
# =============================================================================

def get_voucher_types(co_id: int = None):
    """List voucher types for a company."""
    sql = """SELECT
        avt.acc_voucher_type_id,
        avt.co_id,
        avt.type_name,
        avt.type_code,
        avt.type_category,
        avt.auto_numbering,
        avt.prefix,
        avt.requires_bank_cash,
        avt.is_system_type
    FROM acc_voucher_type avt
    WHERE avt.active = 1
        AND (:co_id IS NULL OR avt.co_id = :co_id)
    ORDER BY avt.type_name;"""
    return text(sql)


def get_financial_years(co_id: int = None):
    """List financial years for a company."""
    sql = """SELECT
        afy.acc_financial_year_id,
        afy.co_id,
        afy.fy_start,
        afy.fy_end,
        afy.fy_label,
        afy.is_active,
        afy.is_locked,
        afy.locked_by,
        afy.locked_date_time
    FROM acc_financial_year afy
    WHERE (:co_id IS NULL OR afy.co_id = :co_id)
    ORDER BY afy.fy_start DESC;"""
    return text(sql)


# =============================================================================
# ACCOUNT DETERMINATION
# =============================================================================

def get_account_determinations(co_id: int = None):
    """List account determination rules with ledger names."""
    sql = """SELECT
        aad.acc_account_determination_id,
        aad.co_id,
        aad.doc_type,
        aad.line_type,
        aad.acc_ledger_id,
        al.ledger_name,
        al.ledger_code,
        aad.item_grp_id,
        igm.item_grp_name,
        aad.is_default
    FROM acc_account_determination aad
    LEFT JOIN acc_ledger al ON al.acc_ledger_id = aad.acc_ledger_id
    LEFT JOIN item_grp_mst igm ON igm.item_grp_id = aad.item_grp_id
    WHERE aad.active = 1
        AND (:co_id IS NULL OR aad.co_id = :co_id)
    ORDER BY aad.doc_type, aad.line_type, aad.is_default DESC;"""
    return text(sql)


# =============================================================================
# VOUCHER LIST & DETAIL
# =============================================================================

def get_vouchers_count():
    """Total row count for the voucher list (same filters as get_vouchers_list,
    without pagination). Binds: co_id, branch_id, voucher_type_id, from_date,
    to_date, party_id, source_doc_type, status_id, search.
    The avt/pm joins exist only so :search matches the same rows as the list.
    """
    sql = """SELECT COUNT(*) AS total
    FROM acc_voucher av
    LEFT JOIN acc_voucher_type avt ON avt.acc_voucher_type_id = av.acc_voucher_type_id
    LEFT JOIN party_mst pm ON pm.party_id = av.party_id
    WHERE av.active = 1
        AND (:co_id IS NULL OR av.co_id = :co_id)
        AND (:branch_id IS NULL OR av.branch_id = :branch_id)
        AND (:voucher_type_id IS NULL OR av.acc_voucher_type_id = :voucher_type_id)
        AND (:from_date IS NULL OR av.voucher_date >= :from_date)
        AND (:to_date IS NULL OR av.voucher_date <= :to_date)
        AND (:party_id IS NULL OR av.party_id = :party_id)
        AND (:source_doc_type IS NULL OR av.source_doc_type = :source_doc_type)
        AND (:status_id IS NULL OR av.status_id = :status_id)
        AND (:search IS NULL OR av.voucher_no LIKE :search
             OR pm.supp_name LIKE :search OR avt.type_name LIKE :search);"""
    return text(sql)


def get_vouchers_list(co_id: int = None):
    """List vouchers with filters and pagination.
    Filters: branch_id, voucher_type_id, from_date, to_date, party_id,
             source_doc_type, status_id, search.
    Pagination: page, limit -> LIMIT :limit OFFSET :offset.
    """
    sql = """SELECT
        av.acc_voucher_id,
        av.co_id,
        av.branch_id,
        bm.branch_name,
        av.acc_voucher_type_id,
        avt.type_name AS voucher_type_name,
        avt.type_code AS voucher_type_code,
        av.acc_financial_year_id,
        afy.fy_label,
        av.voucher_no,
        av.voucher_date,
        av.party_id,
        pm.supp_name AS party_name,
        av.ref_no,
        av.ref_date,
        av.narration,
        av.total_amount,
        av.source_doc_type,
        av.source_doc_id,
        av.is_auto_posted,
        av.is_reversed,
        av.status_id,
        sm.status_name,
        av.approval_level,
        av.updated_date_time
    FROM acc_voucher av
    LEFT JOIN acc_voucher_type avt ON avt.acc_voucher_type_id = av.acc_voucher_type_id
    LEFT JOIN acc_financial_year afy ON afy.acc_financial_year_id = av.acc_financial_year_id
    LEFT JOIN branch_mst bm ON bm.branch_id = av.branch_id
    LEFT JOIN party_mst pm ON pm.party_id = av.party_id
    LEFT JOIN status_mst sm ON sm.status_id = av.status_id
    WHERE av.active = 1
        AND (:co_id IS NULL OR av.co_id = :co_id)
        AND (:branch_id IS NULL OR av.branch_id = :branch_id)
        AND (:voucher_type_id IS NULL OR av.acc_voucher_type_id = :voucher_type_id)
        AND (:from_date IS NULL OR av.voucher_date >= :from_date)
        AND (:to_date IS NULL OR av.voucher_date <= :to_date)
        AND (:party_id IS NULL OR av.party_id = :party_id)
        AND (:source_doc_type IS NULL OR av.source_doc_type = :source_doc_type)
        AND (:status_id IS NULL OR av.status_id = :status_id)
        AND (:search IS NULL OR av.voucher_no LIKE :search
             OR pm.supp_name LIKE :search OR avt.type_name LIKE :search)
    ORDER BY av.voucher_date DESC, av.acc_voucher_id DESC
    LIMIT :limit OFFSET :offset;"""
    return text(sql)


def get_voucher_detail(voucher_id: int = None):
    """Full voucher header with type info, branch, party, and financial year."""
    sql = """SELECT
        av.acc_voucher_id,
        av.co_id,
        av.branch_id,
        bm.branch_name,
        bm.branch_prefix,
        av.acc_voucher_type_id,
        avt.type_name AS voucher_type_name,
        avt.type_code AS voucher_type_code,
        avt.type_category,
        avt.requires_bank_cash,
        av.acc_financial_year_id,
        afy.fy_label,
        afy.fy_start,
        afy.fy_end,
        av.voucher_no,
        av.voucher_date,
        av.party_id,
        pm.supp_name AS party_name,
        av.ref_no,
        av.ref_date,
        av.narration,
        av.total_amount,
        av.source_doc_type,
        av.source_doc_id,
        av.is_auto_posted,
        av.is_reversed,
        av.reversed_by_voucher_id,
        av.reversal_of_voucher_id,
        av.status_id,
        sm.status_name,
        av.approval_level,
        av.place_of_supply_state_code,
        av.branch_gstin,
        av.party_gstin,
        av.currency_id,
        av.exchange_rate,
        av.approved_by,
        av.approved_date_time,
        av.updated_by,
        av.updated_date_time
    FROM acc_voucher av
    LEFT JOIN acc_voucher_type avt ON avt.acc_voucher_type_id = av.acc_voucher_type_id
    LEFT JOIN acc_financial_year afy ON afy.acc_financial_year_id = av.acc_financial_year_id
    LEFT JOIN branch_mst bm ON bm.branch_id = av.branch_id
    LEFT JOIN party_mst pm ON pm.party_id = av.party_id
    LEFT JOIN status_mst sm ON sm.status_id = av.status_id
    WHERE av.active = 1
        AND av.acc_voucher_id = :voucher_id;"""
    return text(sql)


def get_voucher_lines(voucher_id: int = None):
    """Voucher lines with ledger names and group info."""
    sql = """SELECT
        avl.acc_voucher_line_id,
        avl.acc_voucher_id,
        avl.acc_ledger_id,
        al.ledger_name,
        al.ledger_code,
        al.ledger_type,
        alg.group_name AS ledger_group_name,
        avl.dr_cr,
        avl.amount,
        avl.branch_id,
        bm.branch_name AS line_branch_name,
        avl.party_id,
        pm.supp_name AS line_party_name,
        avl.narration,
        avl.source_line_type,
        avl.cost_center_id
    FROM acc_voucher_line avl
    LEFT JOIN acc_ledger al ON al.acc_ledger_id = avl.acc_ledger_id
    LEFT JOIN acc_ledger_group alg ON alg.acc_ledger_group_id = al.acc_ledger_group_id
    LEFT JOIN branch_mst bm ON bm.branch_id = avl.branch_id
    LEFT JOIN party_mst pm ON pm.party_id = avl.party_id
    WHERE avl.active = 1
        AND avl.acc_voucher_id = :voucher_id
    ORDER BY avl.acc_voucher_line_id;"""
    return text(sql)


def get_voucher_gst(voucher_id: int = None):
    """GST details for a voucher."""
    sql = """SELECT
        avg.acc_voucher_gst_id,
        avg.acc_voucher_id,
        avg.acc_voucher_line_id,
        avg.gst_type,
        avg.supply_type,
        avg.hsn_sac_code,
        avg.taxable_amount,
        avg.cgst_rate,
        avg.cgst_amount,
        avg.sgst_rate,
        avg.sgst_amount,
        avg.igst_rate,
        avg.igst_amount,
        avg.cess_rate,
        avg.cess_amount,
        avg.total_gst_amount,
        avg.is_rcm,
        avg.itc_eligibility
    FROM acc_voucher_gst avg
    WHERE avg.active = 1
        AND avg.acc_voucher_id = :voucher_id
    ORDER BY avg.acc_voucher_gst_id;"""
    return text(sql)


def get_voucher_bill_refs(voucher_id: int = None):
    """Bill references for a voucher."""
    sql = """SELECT
        abr.acc_bill_ref_id,
        abr.co_id,
        abr.acc_voucher_id,
        abr.acc_voucher_line_id,
        abr.party_id,
        abr.ref_type,
        abr.bill_no,
        abr.bill_date,
        abr.due_date,
        abr.amount,
        abr.pending_amount,
        abr.status
    FROM acc_bill_ref abr
    WHERE abr.active = 1
        AND abr.acc_voucher_id = :voucher_id
    ORDER BY abr.bill_date, abr.acc_bill_ref_id;"""
    return text(sql)


# =============================================================================
# DUPLICATE CHECK & SEQUENCING
# =============================================================================

def check_duplicate_voucher(source_doc_type: str = None, source_doc_id: int = None):
    """Check if a voucher already exists for a given source document (double-post prevention)."""
    sql = """SELECT
        av.acc_voucher_id,
        av.voucher_no,
        av.voucher_date,
        av.total_amount,
        av.status_id
    FROM acc_voucher av
    WHERE av.active = 1
        AND av.source_doc_type = :source_doc_type
        AND av.source_doc_id = :source_doc_id;"""
    return text(sql)


def get_next_voucher_number():
    """Lock and read the numbering row for a voucher type + financial year
    (company-level sequence: branch_id IS NULL). The caller should increment
    last_number via increment_voucher_numbering().
    Binds: co_id, voucher_type_id, fy_id.
    """
    sql = """SELECT
        avn.acc_voucher_numbering_id,
        avn.co_id,
        avn.acc_voucher_type_id,
        avn.acc_financial_year_id,
        avn.branch_id,
        avn.prefix,
        avn.last_number
    FROM acc_voucher_numbering avn
    WHERE avn.active = 1
        AND avn.co_id = :co_id
        AND avn.acc_voucher_type_id = :voucher_type_id
        AND avn.acc_financial_year_id = :fy_id
        AND avn.branch_id IS NULL
    FOR UPDATE;"""
    return text(sql)


def insert_voucher_numbering():
    """Create a company-level numbering sequence row (branch_id NULL).
    Binds: co_id, acc_voucher_type_id, acc_financial_year_id, prefix,
    last_number, updated_by.
    """
    sql = """INSERT INTO acc_voucher_numbering (
        co_id, acc_voucher_type_id, acc_financial_year_id, branch_id,
        prefix, last_number, active, updated_by
    ) VALUES (
        :co_id, :acc_voucher_type_id, :acc_financial_year_id, NULL,
        :prefix, :last_number, 1, :updated_by
    );"""
    return text(sql)


def increment_voucher_numbering():
    """Set last_number on a numbering row after consuming a sequence value.
    Binds: acc_voucher_numbering_id, last_number, updated_by.
    """
    sql = """UPDATE acc_voucher_numbering
    SET last_number = :last_number,
        updated_by = :updated_by,
        updated_date_time = CURRENT_TIMESTAMP
    WHERE acc_voucher_numbering_id = :acc_voucher_numbering_id
        AND active = 1;"""
    return text(sql)


# =============================================================================
# PERIOD LOCK
# =============================================================================

def get_period_lock_status(fy_id: int = None, period_month: int = None):
    """Check if a period is locked for a given financial year and month."""
    sql = """SELECT
        apl.acc_period_lock_id,
        apl.acc_financial_year_id,
        apl.period_month,
        apl.period_start,
        apl.period_end,
        apl.is_locked,
        apl.locked_by,
        apl.locked_date_time
    FROM acc_period_lock apl
    WHERE apl.acc_financial_year_id = :fy_id
        AND apl.period_month = :period_month;"""
    return text(sql)


# =============================================================================
# PARTY OUTSTANDING BILLS
# =============================================================================

def get_party_outstanding_bills(co_id: int = None, party_id: int = None):
    """Get open/partially settled bills for a party.
    Returns bills from acc_bill_ref (using its own party_id and pending_amount
    columns) with status OPEN or PARTIAL, plus opening bills from
    acc_opening_bill. Binds: co_id, party_id.
    """
    sql = """SELECT
        'BILL_REF' AS source,
        abr.acc_bill_ref_id AS bill_id,
        abr.bill_no,
        abr.bill_date,
        abr.due_date,
        abr.ref_type,
        abr.amount AS original_amount,
        abr.pending_amount,
        abr.status,
        av.voucher_no,
        av.voucher_date
    FROM acc_bill_ref abr
    JOIN acc_voucher av ON av.acc_voucher_id = abr.acc_voucher_id
    WHERE abr.active = 1
        AND av.active = 1
        AND abr.status IN ('OPEN', 'PARTIAL')
        AND abr.party_id = :party_id
        AND (:co_id IS NULL OR abr.co_id = :co_id)

    UNION ALL

    SELECT
        'OPENING' AS source,
        aob.acc_opening_bill_id AS bill_id,
        aob.bill_no,
        aob.bill_date,
        aob.due_date,
        aob.bill_type AS ref_type,
        aob.amount AS original_amount,
        aob.pending_amount,
        aob.status,
        NULL AS voucher_no,
        NULL AS voucher_date
    FROM acc_opening_bill aob
    JOIN acc_ledger al ON al.acc_ledger_id = aob.acc_ledger_id
    WHERE aob.active = 1
        AND aob.status IN ('OPEN', 'PARTIAL')
        AND al.party_id = :party_id
        AND (:co_id IS NULL OR aob.co_id = :co_id)

    ORDER BY bill_date, bill_id;"""
    return text(sql)


# =============================================================================
# INSERT OPERATIONS
# =============================================================================

def insert_voucher():
    """INSERT INTO acc_voucher."""
    sql = """INSERT INTO acc_voucher (
        co_id, branch_id, acc_voucher_type_id, acc_financial_year_id,
        voucher_no, voucher_date, party_id, ref_no, ref_date,
        narration, total_amount, source_doc_type, source_doc_id,
        is_auto_posted, is_reversed, status_id, approval_level,
        place_of_supply_state_code, branch_gstin, party_gstin,
        currency_id, exchange_rate, active, updated_by
    ) VALUES (
        :co_id, :branch_id, :acc_voucher_type_id, :acc_financial_year_id,
        :voucher_no, :voucher_date, :party_id, :ref_no, :ref_date,
        :narration, :total_amount, :source_doc_type, :source_doc_id,
        :is_auto_posted, :is_reversed, :status_id, :approval_level,
        :place_of_supply_state_code, :branch_gstin, :party_gstin,
        :currency_id, :exchange_rate, 1, :updated_by
    );"""
    return text(sql)


def insert_voucher_line():
    """INSERT INTO acc_voucher_line."""
    sql = """INSERT INTO acc_voucher_line (
        acc_voucher_id, acc_ledger_id, dr_cr, amount,
        branch_id, party_id, narration, source_line_type,
        cost_center_id, active, updated_by
    ) VALUES (
        :acc_voucher_id, :acc_ledger_id, :dr_cr, :amount,
        :branch_id, :party_id, :narration, :source_line_type,
        :cost_center_id, 1, :updated_by
    );"""
    return text(sql)


def insert_voucher_gst():
    """INSERT INTO acc_voucher_gst."""
    sql = """INSERT INTO acc_voucher_gst (
        acc_voucher_id, acc_voucher_line_id, gst_type, supply_type,
        hsn_sac_code, taxable_amount,
        cgst_rate, cgst_amount, sgst_rate, sgst_amount,
        igst_rate, igst_amount, cess_rate, cess_amount,
        total_gst_amount, is_rcm, itc_eligibility,
        active, updated_by
    ) VALUES (
        :acc_voucher_id, :acc_voucher_line_id, :gst_type, :supply_type,
        :hsn_sac_code, :taxable_amount,
        :cgst_rate, :cgst_amount, :sgst_rate, :sgst_amount,
        :igst_rate, :igst_amount, :cess_rate, :cess_amount,
        :total_gst_amount, :is_rcm, :itc_eligibility,
        1, :updated_by
    );"""
    return text(sql)


def insert_bill_ref():
    """INSERT INTO acc_bill_ref.
    Binds: co_id, acc_voucher_id, acc_voucher_line_id, party_id, ref_type,
    bill_no, bill_date, due_date, amount, pending_amount, status, updated_by.
    """
    sql = """INSERT INTO acc_bill_ref (
        co_id, acc_voucher_id, acc_voucher_line_id, party_id, ref_type,
        bill_no, bill_date, due_date, amount, pending_amount, status,
        active, updated_by
    ) VALUES (
        :co_id, :acc_voucher_id, :acc_voucher_line_id, :party_id, :ref_type,
        :bill_no, :bill_date, :due_date, :amount, :pending_amount, :status,
        1, :updated_by
    );"""
    return text(sql)


def insert_bill_settlement():
    """INSERT INTO acc_bill_settlement."""
    sql = """INSERT INTO acc_bill_settlement (
        acc_bill_ref_id, settled_against_bill_ref_id,
        settled_amount, settlement_date,
        active, updated_by
    ) VALUES (
        :acc_bill_ref_id, :settled_against_bill_ref_id,
        :settled_amount, :settlement_date,
        1, :updated_by
    );"""
    return text(sql)


def update_bill_ref_pending():
    """Set pending_amount and status on a bill reference after settlement.
    The caller computes the new pending amount and status in Python.
    Binds: acc_bill_ref_id, pending_amount, status, updated_by.
    """
    sql = """UPDATE acc_bill_ref
    SET pending_amount = :pending_amount,
        status = :status,
        updated_by = :updated_by,
        updated_date_time = CURRENT_TIMESTAMP
    WHERE acc_bill_ref_id = :acc_bill_ref_id
        AND active = 1;"""
    return text(sql)


# =============================================================================
# APPROVAL LOG & WARNINGS
# =============================================================================

def insert_approval_log():
    """INSERT INTO acc_voucher_approval_log."""
    sql = """INSERT INTO acc_voucher_approval_log (
        acc_voucher_id, action, from_status_id, to_status_id,
        from_level, to_level, remarks,
        action_by, active, updated_by
    ) VALUES (
        :acc_voucher_id, :action, :from_status_id, :to_status_id,
        :from_level, :to_level, :remarks,
        :action_by, 1, :updated_by
    );"""
    return text(sql)


def insert_voucher_warning():
    """INSERT INTO acc_voucher_warning."""
    sql = """INSERT INTO acc_voucher_warning (
        acc_voucher_id, warning_type, warning_message, severity,
        is_overridden, overridden_by, overridden_date_time,
        active, updated_by
    ) VALUES (
        :acc_voucher_id, :warning_type, :warning_message, :severity,
        :is_overridden, :overridden_by, :overridden_date_time,
        1, :updated_by
    );"""
    return text(sql)


# =============================================================================
# OPENING BILLS
# =============================================================================

def get_opening_bills(co_id: int = None, party_id: int = None, fy_id: int = None):
    """Get opening bills for a party in a financial year."""
    sql = """SELECT
        aob.acc_opening_bill_id,
        aob.co_id,
        aob.acc_ledger_id,
        al.ledger_name,
        aob.acc_financial_year_id,
        afy.fy_label,
        aob.bill_no,
        aob.bill_date,
        aob.due_date,
        aob.bill_type,
        aob.amount,
        aob.pending_amount,
        aob.status
    FROM acc_opening_bill aob
    JOIN acc_ledger al ON al.acc_ledger_id = aob.acc_ledger_id
    LEFT JOIN acc_financial_year afy ON afy.acc_financial_year_id = aob.acc_financial_year_id
    WHERE aob.active = 1
        AND (:co_id IS NULL OR aob.co_id = :co_id)
        AND (:party_id IS NULL OR al.party_id = :party_id)
        AND (:fy_id IS NULL OR aob.acc_financial_year_id = :fy_id)
    ORDER BY aob.bill_date, aob.acc_opening_bill_id;"""
    return text(sql)


def insert_opening_bill():
    """INSERT INTO acc_opening_bill.
    Binds: co_id, acc_ledger_id, acc_financial_year_id, bill_no, bill_date,
    due_date, bill_type, amount, pending_amount, status, updated_by.
    """
    sql = """INSERT INTO acc_opening_bill (
        co_id, acc_ledger_id, acc_financial_year_id,
        bill_no, bill_date, due_date, bill_type,
        amount, pending_amount, status,
        active, updated_by
    ) VALUES (
        :co_id, :acc_ledger_id, :acc_financial_year_id,
        :bill_no, :bill_date, :due_date, :bill_type,
        :amount, :pending_amount, :status,
        1, :updated_by
    );"""
    return text(sql)
