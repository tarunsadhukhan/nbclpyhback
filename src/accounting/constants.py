"""Accounting module constants — single source of truth."""

# Status IDs (same as procurement workflow)
ACC_STATUS_IDS = {
    "DRAFT": 21,
    "OPEN": 1,
    "PENDING_APPROVAL": 20,
    "APPROVED": 3,
    "REJECTED": 4,
    "CLOSED": 5,
    "CANCELLED": 6,
}


ACC_STATUS_LABELS = {
    21: "Draft",
    1: "Open",
    20: "Pending Approval",
    3: "Approved",
    4: "Rejected",
    5: "Closed",
    6: "Cancelled",
}

# Voucher Type Categories
VOUCHER_CATEGORIES = {
    "PAYMENT": {"code": "PAY", "requires_bank_cash": True},
    "RECEIPT": {"code": "RCT", "requires_bank_cash": True},
    "JOURNAL": {"code": "JRN", "requires_bank_cash": False},
    "CONTRA": {"code": "CTR", "requires_bank_cash": True},
    "SALES": {"code": "SAL", "requires_bank_cash": False},
    "PURCHASE": {"code": "PUR", "requires_bank_cash": False},
    "DEBIT_NOTE": {"code": "DRN", "requires_bank_cash": False},
    "CREDIT_NOTE": {"code": "CRN", "requires_bank_cash": False},
}

# Ledger Types
LEDGER_TYPES = {
    "GENERAL": "G",
    "PARTY": "P",
    "BANK": "B",
    "CASH": "C",
}

# Account Nature
ACCOUNT_NATURE = {
    "ASSET": "A",
    "LIABILITY": "L",
    "INCOME": "I",
    "EXPENSE": "E",
}

# Doc types for auto-posting
SOURCE_DOC_TYPES = {
    "PROC_BILLPASS": "PROC_BILLPASS",
    "JUTE_BILLPASS": "JUTE_BILLPASS",
    "JUTE_FREIGHT": "JUTE_FREIGHT",
    "SALES_INVOICE": "SALES_INVOICE",
    "DRCR_NOTE": "DRCR_NOTE",
    "PAYROLL": "PAYROLL",
    "PAYROLL_DISBURSEMENT": "PAYROLL_DISBURSEMENT",
    "STATUTORY_REMITTANCE": "STATUTORY_REMITTANCE",
}

# Per-company posting behaviour (acc_company_settings.posting_mode_*)
POSTING_MODES = {
    "OFF": "OFF",                      # no auto-posting; company keeps external books
    "AUTO_DRAFT": "AUTO_DRAFT",        # voucher created at Draft (21) for accountant review
    "AUTO_APPROVED": "AUTO_APPROVED",  # voucher created directly at Approved (3)
}

# Posting queue row states (acc_posting_queue.status)
POSTING_QUEUE_STATUSES = ["PENDING", "POSTED", "DRAFTED", "SKIPPED", "FAILED"]

# Due-date derivation rules (acc_company_settings.due_date_rule)
DUE_DATE_RULES = {
    "PO_CREDIT_DAYS": "PO_CREDIT_DAYS",    # doc due date, else doc date + PO/invoice credit days
    "MANUAL": "MANUAL",                    # only the manually entered due date
}

# Line types for account determination
LINE_TYPES = {
    "MATERIAL": "MATERIAL",
    "CGST_INPUT": "CGST_INPUT",
    "SGST_INPUT": "SGST_INPUT",
    "IGST_INPUT": "IGST_INPUT",
    "CGST_OUTPUT": "CGST_OUTPUT",
    "SGST_OUTPUT": "SGST_OUTPUT",
    "IGST_OUTPUT": "IGST_OUTPUT",
    "CREDITOR": "CREDITOR",
    "DEBTOR": "DEBTOR",
    "TDS": "TDS",
    "FREIGHT": "FREIGHT",
    "ROUND_OFF": "ROUND_OFF",
    "CLAIMS": "CLAIMS",
    "CASH": "CASH",
    "REVENUE": "REVENUE",
    "GROSS_SALARY": "GROSS_SALARY",
    "EMPLOYER_PF": "EMPLOYER_PF",
    "EMPLOYER_ESI": "EMPLOYER_ESI",
    "NET_SALARY": "NET_SALARY",
    "EMPLOYEE_PF": "EMPLOYEE_PF",
    "EMPLOYEE_ESI": "EMPLOYEE_ESI",
    "PT": "PT",
    "TDS_SALARY": "TDS_SALARY",
    "ADVANCE_RECOVERY": "ADVANCE_RECOVERY",
    "BANK": "BANK",
}

# Bill reference types
BILL_REF_TYPES = ["NEW", "AGAINST", "ADVANCE", "ON_ACCOUNT"]

# Bill statuses
BILL_STATUSES = ["OPEN", "PARTIAL", "CLOSED"]

# Warning codes
WARNING_CODES = {
    "LOCKED_PERIOD": {"severity": "HIGH", "message": "Period {month}/{year} is locked. Entry requires unlock approval."},
    "ABNORMAL_BALANCE": {"severity": "MEDIUM", "message": "Unusual: {ledger_name} normally has {normal_balance} balance."},
    "TDS_MISSING": {"severity": "HIGH", "message": "TDS under Section {section} may be applicable for {party_name}."},
    "PAYMENT_EXCEEDS_OUTSTANDING": {"severity": "MEDIUM", "message": "Payment Rs {amount} exceeds outstanding Rs {outstanding} for {party_name}."},
    "DUPLICATE_ENTRY": {"severity": "HIGH", "message": "Possible duplicate: Similar entry exists — Voucher #{existing_no}."},
    "WRONG_VOUCHER_TYPE": {"severity": "MEDIUM", "message": "Journal contains {ledger_type} ledger. Consider using {suggested_type} voucher."},
    "GST_STATE_MISMATCH": {"severity": "HIGH", "message": "GST type {gst_type} may be incorrect for state combination."},
    "RCM_NOT_APPLIED": {"severity": "HIGH", "message": "Vendor {party_name} has no GSTIN. RCM may apply under Section 9(4)."},
    "ADVANCE_UNADJUSTED": {"severity": "MEDIUM", "message": "Advance to {party_name} unadjusted for {days} days."},
    "CREDIT_LIMIT_EXCEEDED": {"severity": "HIGH", "message": "Credit limit for {party_name}: Rs {limit}. Outstanding: Rs {outstanding}."},
    "PAN_MISSING_TDS": {"severity": "HIGH", "message": "PAN not available for {party_name}. TDS at 20% under Section 206AA."},
    "NARRATION_MISSING": {"severity": "LOW", "message": "Narration is recommended on Journal vouchers for audit trail."},
    "NEGATIVE_CASH_BANK": {"severity": "HIGH", "message": "{ledger_name} balance would be negative after this entry."},
}

# Approval menu names per voucher type
APPROVAL_MENU_MAP = {
    "PAYMENT": "acc_payment",
    "RECEIPT": "acc_receipt",
    "JOURNAL": "acc_journal",
    "CONTRA": "acc_contra",
    "DEBIT_NOTE": "acc_debit_note",
    "CREDIT_NOTE": "acc_credit_note",
}
