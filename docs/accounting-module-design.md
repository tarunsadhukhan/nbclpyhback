# VoWERP3 Accounting Module — Full Design Specification

**Date:** 2026-03-30
**Status:** Design — Awaiting Approval
**Module Prefix:** `acc_`
**Router Prefix:** `/api/accounting`

---

## 1. Purpose & Goals

Build a complete, production-grade accounting module that can **replace Tally entirely** for VoWERP3 tenants. The module must:

- Maintain full double-entry books of accounts per company
- Auto-post accounting entries from procurement bill pass, jute bill pass, and sales invoice approval
- Provide branch-level visibility within company-level books
- Handle Indian statutory compliance: GST (GSTR-1, GSTR-3B), TDS
- Generate all standard financial reports: Trial Balance, P&L, Balance Sheet, Ledger, Day Book
- Track receivables/payables bill-wise with ageing analysis
- Support bank reconciliation
- Scale to handle any business type (trading, manufacturing, services)

**Non-goals for Phase 1:** Perpetual inventory accounting, fixed asset depreciation, cost center accounting, multi-company consolidation, e-invoicing.

---

## 2. Architecture Decision: Hybrid (Tally + SAP)

### Philosophy

**Tally's voucher-based double-entry** (familiar to Indian accountants) combined with **SAP's account determination** (configurable GL mapping for auto-posting) and **branch as a first-class dimension** (company-level books with branch-level filtering).

### Key Principles

1. **Balances are never stored.** All balances (trial balance, ledger balance, outstanding) are computed on-the-fly from voucher lines. This eliminates reconciliation problems and ensures perfect auditability.

2. **Vouchers are immutable after approval.** Corrections via reversal vouchers only. No UPDATE on approved voucher data.

3. **Ledgers are company-scoped.** One chart of accounts per `co_id`. No branch-level ledger partitioning.

4. **Branch is a dimension, not a partition.** Every voucher carries `branch_id` (mandatory for auto-posted, optional for company-wide entries). Reports filter by branch when needed. Line-level `branch_id` overrides enable inter-branch journals.

5. **Party ledgers are regular ledgers with a party link.** `ledger_type = 'P'` + `party_id` FK. No separate sub-ledger system — the same query model works for all reports.

6. **Account determination drives auto-posting.** A rules table maps document types to GL accounts. The accountant configures these rules per company. No hardcoded GL accounts in business logic.

7. **Periodic inventory method.** Stock valuation is adjusted at period-end via closing stock journal entry (Tally default). Perpetual inventory is a Phase 3 upgrade.

### Branch vs Company Scoping

```
Statutory Books (Company Level)         Management Views (Branch Level)
================================        ================================
Trial Balance   → co_id = X             Branch Trial Balance → co_id = X AND branch_id = Y
P&L Statement   → co_id = X             Branch P&L          → co_id = X AND branch_id = Y
Balance Sheet   → co_id = X             Branch Outstanding   → co_id = X AND branch_id = Y
GST Returns     → grouped by GSTIN      GST per GSTIN        → WHERE branch_gstin = 'ABC123'
                  (from branch_mst.gst_no)
```

**Inter-branch transactions:** A single Journal voucher with line-level `branch_id` overrides.
- Line 1: DR Stock Transfer In (branch_id = B)
- Line 2: CR Stock Transfer Out (branch_id = A)

**GST returns:** Grouped by GSTIN. Since each branch can have its own `gst_no` in `branch_mst`, GSTR-1/3B queries group vouchers by `branch_gstin` (denormalized on `acc_voucher` for query performance).

---

## 3. Auto-Posting Trigger Points

### 3.1 Procurement Bill Pass Complete

**Trigger:** `billpass_status` set to `1` on `proc_inward` WHERE `sr_status = 3`
**Code location:** `src/procurement/billpass.py` — `update_bill_pass()` endpoint
**Integration:** Add call to `auto_post_procurement_billpass(db, inward_id, user_id)` after current update logic

**Data read from existing tables:**
- `proc_inward`: `branch_id`, `supplier_id`, `invoice_no`, `invoice_date`, `net_amount`, `round_off_value`
- `proc_inward_dtl` + `proc_gst`: `approved_qty * accepted_rate - discount_amount` per line, CGST/SGST/IGST amounts
- `drcr_note` (approved, `status_id = 3`): `adjustment_type` (1=Debit, 2=Credit), `net_amount`
- `proc_inward_additional` + `proc_gst`: additional charges (freight, insurance) with GST

**Accounting entry generated:**

```
Purchase Voucher (type = PURCHASE)
  DR  Purchase A/c                   [sum of taxable line amounts + additional charges]
  DR  CGST Input A/c                 [sum of c_tax_amount from proc_gst — intra-state]
  DR  SGST Input A/c                 [sum of s_tax_amount from proc_gst — intra-state]
  DR  IGST Input A/c                 [sum of i_tax_amount from proc_gst — inter-state]
  DR  Round Off A/c                  [round_off_value, if positive]
      CR  Sundry Creditors (party)   [net payable = taxable + tax + round-off]
      CR  Round Off A/c              [round_off_value, if negative]

If approved Debit Notes exist (supplier owes us):
  DR  Sundry Creditors (party)       [DR note net_amount]
      CR  Purchase Returns A/c       [DR note base amount]
      CR  CGST Input A/c             [DR note CGST reversal]
      CR  SGST/IGST Input A/c        [DR note SGST/IGST reversal]

If approved Credit Notes exist (we owe supplier more):
  DR  Purchase A/c                   [CR note base amount]
  DR  CGST/SGST/IGST Input A/c      [CR note GST]
      CR  Sundry Creditors (party)   [CR note net_amount]
```

**Bill reference created:** `acc_bill_ref` with `ref_name = invoice_no`, `ref_amount = net_payable`, `due_date = invoice_due_date`.

### 3.2 Jute Procurement Bill Pass Complete

**Trigger:** `bill_pass_complete` set to `1` on `jute_mr` WHERE `status_id = 3`
**Code location:** `src/juteProcurement/billPass.py` — `update_bill_pass()` endpoint

**Accounting entry generated:**

```
Purchase Voucher (type = PURCHASE)
  DR  Jute Purchase A/c             [total_amount]
  DR  Round Off A/c                  [roundoff, if positive]
      CR  Sundry Creditors (party)   [net_total]
      CR  TDS Payable A/c            [tds_amount]
      CR  Round Off A/c              [roundoff, if negative]

If claim_amount exists:
  DR  Claims Receivable A/c          [claim_amount]
      CR  Sundry Creditors (party)   [claim_amount]

If freight_paid exists:
  DR  Freight Inward A/c             [frieght_paid]  (note: existing typo in DB)
      CR  Cash/Bank A/c              [frieght_paid]
```

### 3.3 Sales Invoice Approved

**Trigger:** `status_id` set to `3` on `sales_invoice`
**Code location:** `src/sales/salesInvoice.py` — `approve_sales_invoice()` endpoint

**Data read:**
- `sales_invoice` (InvoiceHdr): `branch_id`, `party_id`, `invoice_amount`, `intra_inter_state`, `round_off`
- `sales_invoice_dtl` + `sales_invoice_dtl_gst`: line amounts with CGST/SGST/IGST
- `sales_invoice_additional` + `sales_invoice_additional_gst`: additional charges

**Accounting entry generated:**

```
Sales Voucher (type = SALES)
  DR  Sundry Debtors (party)         [invoice total including tax]
      CR  Sales A/c                  [sum of taxable line amounts]
      CR  CGST Output A/c           [sum of cgst_amount — intra-state]
      CR  SGST Output A/c           [sum of sgst_amount — intra-state]
      CR  IGST Output A/c           [sum of igst_amount — inter-state]
      CR  Round Off A/c             [round_off, if applicable]
```

**Bill reference created:** `acc_bill_ref` with `ref_name = invoice_no`, `ref_amount = invoice total`, `due_date = due_date`.

### 3.4 Payroll Auto-Posting

**Trigger:** Payroll finalized for a pay period (`pay_period_status` marked as finalized)
**Code location:** To be created — `src/accounting/auto_post.py` → `auto_post_payroll()`
**Integration:** Call after payroll finalization in HRMS pay period processing

**Data read from existing tables:**
- `pay_employee_payperiod`: `basic`, `gross_salary`, `net_salary` per employee for the period
- `pay_employee_payroll`: Component-wise breakup (earnings, deductions) per employee
- `pay_employee_structure`: Employee pay structure with component amounts
- `pay_components`: Component definitions (type 0=INPUT, 1=EARNING, 2=DEDUCTION, 3=SUMMARY)

**Accounting entry generated (Salary Journal):**

```
Journal Voucher (type = JOURNAL, source_doc_type = PAYROLL)
  DR  Salary & Wages A/c               [sum of gross salary across employees]
  DR  Employer PF Contribution A/c     [employer's share of PF — 12% of basic or as configured]
  DR  Employer ESI Contribution A/c    [employer's share of ESI — 3.25% of gross or as per rate]
      CR  Salary Payable A/c           [sum of net salary — to be disbursed]
      CR  PF Payable A/c              [employee PF + employer PF combined]
      CR  ESI Payable A/c             [employee ESI + employer ESI combined]
      CR  Professional Tax Payable A/c [PT deducted from employees]
      CR  TDS on Salary Payable A/c   [income tax deducted — Section 192]
      CR  Employee Advance Recovery A/c [advance/loan deductions, if any]
```

**Account determination entries:**

| doc_type | line_type | Default Ledger |
|----------|-----------|----------------|
| PAYROLL | GROSS_SALARY | Salary & Wages |
| PAYROLL | EMPLOYER_PF | Employer PF Contribution |
| PAYROLL | EMPLOYER_ESI | Employer ESI Contribution |
| PAYROLL | NET_SALARY | Salary Payable |
| PAYROLL | EMPLOYEE_PF | PF Payable |
| PAYROLL | EMPLOYEE_ESI | ESI Payable |
| PAYROLL | PT | Professional Tax Payable |
| PAYROLL | TDS_SALARY | TDS on Salary Payable |
| PAYROLL | ADVANCE_RECOVERY | Employee Advance Recovery |

**Salary Disbursement (when salary is paid via bank):**

```
Payment Voucher (type = PAYMENT, source_doc_type = PAYROLL_DISBURSEMENT)
  DR  Salary Payable A/c               [net salary amount]
      CR  Bank A/c                     [amount transferred]
```

| doc_type | line_type | Default Ledger |
|----------|-----------|----------------|
| PAYROLL_DISBURSEMENT | NET_SALARY | Salary Payable |
| PAYROLL_DISBURSEMENT | BANK | (resolved from selected bank account) |

**Statutory Remittance (PF/ESI/TDS deposit to government):**

```
Payment Voucher (type = PAYMENT, source_doc_type = STATUTORY_REMITTANCE)
  DR  PF Payable A/c                   [total PF remitted]
      CR  Bank A/c                     [amount deposited]

  DR  ESI Payable A/c                  [total ESI remitted]
      CR  Bank A/c                     [amount deposited]

  DR  TDS on Salary Payable A/c        [TDS deposited with government]
      CR  Bank A/c                     [amount deposited]
```

| doc_type | line_type | Default Ledger |
|----------|-----------|----------------|
| STATUTORY_REMITTANCE | PF | PF Payable |
| STATUTORY_REMITTANCE | ESI | ESI Payable |
| STATUTORY_REMITTANCE | TDS | TDS on Salary Payable |
| STATUTORY_REMITTANCE | BANK | (resolved from selected bank account) |

**Note:** Contractor/labour payments follow a different path — they are treated as vendor payments with TDS under Section 194C, not as salary. Use standard Purchase/Payment voucher flow for contractor invoices.

### 3.5 Advance Payment Lifecycle

Advances (supplier advances, customer advances) are a critical accounting workflow that bridges the gap between payment and invoice.

#### 3.5.1 Supplier Advance Payment

**Trigger:** Manual Payment voucher created with `ref_type = ADVANCE` for a supplier party

**Accounting entry:**
```
Payment Voucher (type = PAYMENT)
  DR  Sundry Creditors (party)         [advance amount]
      CR  Bank A/c                     [advance amount]
```

**Bill reference created:** `acc_bill_ref` with `ref_type = 'ADVANCE'`, `ref_name = 'ADV-{voucher_no}'`, `ref_amount = advance`, `pending_amount = advance`, `status = 'OPEN'`.

**TDS on advance:** If TDS is applicable for the party's nature of payment (Sec 194C, 194J, etc.), TDS should be deducted at the time of advance itself (not just at invoice). The warning system should flag if TDS is not deducted on an advance payment exceeding the threshold.

#### 3.5.2 Customer Advance Receipt

**Trigger:** Manual Receipt voucher created with `ref_type = ADVANCE` for a customer party

**Accounting entry:**
```
Receipt Voucher (type = RECEIPT)
  DR  Bank A/c                         [advance amount]
      CR  Sundry Debtors (party)       [advance amount]
```

**Bill reference created:** `acc_bill_ref` with `ref_type = 'ADVANCE'`, `ref_name = 'ADV-{voucher_no}'`, `ref_amount = advance`, `pending_amount = advance`, `status = 'OPEN'`.

**GST on advance receipt:** Under GST law, tax is payable on advances received for services (not goods, post Nov 2017 notification). The system should warn if advance is received for a service party without GST.

#### 3.5.3 Advance Adjustment Against Invoice

**When procurement bill pass auto-posts:**
1. Before creating the Purchase voucher, query `acc_bill_ref` for the supplier where `ref_type = 'ADVANCE'` AND `status IN ('OPEN', 'PARTIAL')`
2. If open advances exist, present them for adjustment (API returns advance list with pending amounts)
3. On adjustment:
   - Create `acc_bill_settlement` linking the advance `acc_bill_ref_id` to the invoice `acc_bill_ref_id`
   - Reduce `pending_amount` on the advance bill_ref
   - Reduce `pending_amount` on the invoice bill_ref by the same amount
   - Update `status` to 'PARTIAL' or 'CLOSED' as appropriate on both refs

**When sales invoice auto-posts:**
- Same logic in reverse — check for customer advances and adjust against the sales invoice bill_ref

#### 3.5.4 Advance Ageing

Unadjusted advances older than 365 days are an audit concern. The ageing report (Section 5.5) should include a filter for `ref_type = 'ADVANCE'` to show advance-specific ageing.

### 3.6 Double-Posting Prevention

Before creating an auto-posted voucher, the engine checks:
```sql
SELECT 1 FROM acc_voucher
WHERE source_doc_type = :doc_type AND source_doc_id = :doc_id AND active = 1
```
If a voucher already exists for this source document, skip (idempotent).

---

## 4. Database Schema

All tables use the `acc_` prefix. All tables in the **tenant database** (not vowconsole3). All tables use `Depends(get_tenant_db)` for Portal persona access.

### 4.1 Phase 1 — Core Tables

#### acc_ledger_group (Tally's 28 predefined groups + custom)

```sql
CREATE TABLE acc_ledger_group (
    acc_ledger_group_id   INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    parent_group_id       INT NULL,
    group_name            VARCHAR(100) NOT NULL,
    group_code            VARCHAR(20) NULL,
    nature                ENUM('A','L','I','E') NOT NULL COMMENT 'Asset, Liability, Income, Expense',
    affects_gross_profit  TINYINT DEFAULT 0 COMMENT '1=Trading P&L, 0=General P&L',
    is_revenue            TINYINT NOT NULL COMMENT '1=P&L side, 0=Balance Sheet side',
    normal_balance        CHAR(1) NOT NULL COMMENT 'D=Debit, C=Credit',
    is_party_group        TINYINT DEFAULT 0 COMMENT '1=Sundry Debtors/Creditors',
    is_system_group       TINYINT DEFAULT 0 COMMENT '1=predefined, cannot delete',
    sequence_no           INT DEFAULT 0,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_co_group (co_id, group_name),
    KEY idx_parent (parent_group_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (parent_group_id) REFERENCES acc_ledger_group(acc_ledger_group_id)
);
```

**28 Predefined Groups (seed data per company):**

| # | Group Name | Parent | Nature | BS/PL | Normal Bal | Party? |
|---|-----------|--------|--------|-------|------------|--------|
| 1 | Capital Account | ROOT | L | BS | C | No |
| 2 | Reserves & Surplus | Capital Account | L | BS | C | No |
| 3 | Loans (Liability) | ROOT | L | BS | C | No |
| 4 | Bank OD Accounts | Loans (Liability) | L | BS | C | No |
| 5 | Secured Loans | Loans (Liability) | L | BS | C | No |
| 6 | Unsecured Loans | Loans (Liability) | L | BS | C | No |
| 7 | Current Liabilities | ROOT | L | BS | C | No |
| 8 | Duties & Taxes | Current Liabilities | L | BS | C | No |
| 9 | Provisions | Current Liabilities | L | BS | C | No |
| 10 | Sundry Creditors | Current Liabilities | L | BS | C | **Yes** |
| 11 | Fixed Assets | ROOT | A | BS | D | No |
| 12 | Investments | ROOT | A | BS | D | No |
| 13 | Current Assets | ROOT | A | BS | D | No |
| 14 | Bank Accounts | Current Assets | A | BS | D | No |
| 15 | Cash-in-Hand | Current Assets | A | BS | D | No |
| 16 | Deposits (Asset) | Current Assets | A | BS | D | No |
| 17 | Loans & Advances (Asset) | Current Assets | A | BS | D | No |
| 18 | Stock-in-Hand | Current Assets | A | BS | D | No |
| 19 | Sundry Debtors | Current Assets | A | BS | D | **Yes** |
| 20 | Misc. Expenses (Asset) | ROOT | A | BS | D | No |
| 21 | Sales Accounts | ROOT | I | PL | C | No |
| 22 | Purchase Accounts | ROOT | E | PL | D | No |
| 23 | Direct Expenses | ROOT | E | PL | D | No |
| 24 | Direct Incomes | ROOT | I | PL | C | No |
| 25 | Indirect Expenses | ROOT | E | PL | D | No |
| 26 | Indirect Incomes | ROOT | I | PL | C | No |
| 27 | Branch / Divisions | ROOT | A | BS | D | No |
| 28 | Suspense Account | ROOT | A | BS | D | No |

#### acc_ledger (Individual accounts / GL accounts)

```sql
CREATE TABLE acc_ledger (
    acc_ledger_id         INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_ledger_group_id   INT NOT NULL,
    ledger_name           VARCHAR(150) NOT NULL,
    ledger_code           VARCHAR(20) NULL COMMENT 'Optional numeric code',
    ledger_type           CHAR(1) NOT NULL DEFAULT 'G' COMMENT 'G=General, P=Party, B=Bank, C=Cash',
    party_id              INT NULL COMMENT 'FK to party_mst when ledger_type=P',
    credit_days           INT NULL COMMENT 'Default credit period for party ledgers',
    credit_limit          DECIMAL(15,2) NULL COMMENT 'Credit limit for party ledgers',
    opening_balance       DECIMAL(15,2) DEFAULT 0.00,
    opening_balance_type  CHAR(1) NULL COMMENT 'D or C',
    opening_fy_id         INT NULL COMMENT 'FK to acc_financial_year for which opening applies',
    gst_applicable        TINYINT DEFAULT 0,
    hsn_sac_code          VARCHAR(20) NULL,
    is_system_ledger      TINYINT DEFAULT 0 COMMENT '1=auto-created, do not delete',
    is_related_party      TINYINT DEFAULT 0 COMMENT '1=Related party per AS-18/Ind AS 24 — for disclosure reporting',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_co_ledger (co_id, ledger_name),
    KEY idx_group (co_id, acc_ledger_group_id),
    KEY idx_party (co_id, party_id),
    KEY idx_type (co_id, ledger_type),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_ledger_group_id) REFERENCES acc_ledger_group(acc_ledger_group_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

**System ledgers auto-created per company:**
- Cash (Cash-in-Hand group, type=C)
- CGST Input, SGST Input, IGST Input (Duties & Taxes / sub-group under Current Assets)
- CGST Output, SGST Output, IGST Output (Duties & Taxes)
- TDS Payable (Duties & Taxes)
- Purchase Account (Purchase Accounts)
- Jute Purchase Account (Purchase Accounts)
- Purchase Returns (Purchase Accounts)
- Sales Account (Sales Accounts)
- Freight Inward (Direct Expenses)
- Round Off (Indirect Expenses)
- Claims Receivable (Loans & Advances)
- Opening Stock (Stock-in-Hand)
- Closing Stock (Stock-in-Hand)
- Profit & Loss A/c (special — for year-end transfer)

**Party ledgers:** Auto-created for all active parties in `party_mst` on module activation. Vendors → Sundry Creditors group. Customers → Sundry Debtors group. Parties that are both get one ledger under Sundry Creditors (adjustable by accountant).

#### acc_voucher_type (Voucher type configuration)

```sql
CREATE TABLE acc_voucher_type (
    acc_voucher_type_id   INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    type_name             VARCHAR(50) NOT NULL,
    type_code             VARCHAR(10) NOT NULL,
    type_category         VARCHAR(20) NOT NULL COMMENT 'PAYMENT, RECEIPT, JOURNAL, CONTRA, SALES, PURCHASE, DEBIT_NOTE, CREDIT_NOTE',
    auto_numbering        TINYINT DEFAULT 1,
    prefix                VARCHAR(10) NULL,
    requires_bank_cash    TINYINT DEFAULT 0 COMMENT '1=Payment/Receipt/Contra must have Bank or Cash ledger',
    is_system_type        TINYINT DEFAULT 1,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_co_type (co_id, type_name),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id)
);
```

**Predefined voucher types:**

| Type Name | Code | Category | Requires Bank/Cash |
|-----------|------|----------|--------------------|
| Payment | PAY | PAYMENT | Yes |
| Receipt | RCT | RECEIPT | Yes |
| Journal | JRN | JOURNAL | No |
| Contra | CTR | CONTRA | Yes |
| Sales | SAL | SALES | No |
| Purchase | PUR | PURCHASE | No |
| Debit Note | DRN | DEBIT_NOTE | No |
| Credit Note | CRN | CREDIT_NOTE | No |

**Validation rules by type:**
- Payment/Receipt/Contra: At least one line must reference a Bank or Cash type ledger
- Journal: No Bank or Cash ledger allowed (use Contra for that)
- Sales/Purchase: Must have a party ledger line (Sundry Debtors/Creditors)

#### acc_financial_year

```sql
CREATE TABLE acc_financial_year (
    acc_financial_year_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    fy_start              DATE NOT NULL,
    fy_end                DATE NOT NULL,
    fy_label              VARCHAR(10) NOT NULL COMMENT 'e.g., 2025-26',
    is_active             TINYINT DEFAULT 1 COMMENT 'Only one active per company',
    is_locked             TINYINT DEFAULT 0 COMMENT 'No more postings when locked',
    locked_by             INT NULL,
    locked_date_time      TIMESTAMP NULL,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_co_fy (co_id, fy_start),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id)
);
```

#### acc_period_lock (Monthly period locking)

```sql
CREATE TABLE acc_period_lock (
    acc_period_lock_id    INT PRIMARY KEY AUTO_INCREMENT,
    acc_financial_year_id INT NOT NULL,
    period_month          INT NOT NULL COMMENT '1-12 where 1=April, 12=March',
    period_start          DATE NOT NULL,
    period_end            DATE NOT NULL,
    is_locked             TINYINT DEFAULT 0,
    locked_by             INT NULL,
    locked_date_time      TIMESTAMP NULL,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_fy_period (acc_financial_year_id, period_month),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id)
);
```

#### acc_account_determination (SAP-inspired auto-posting rules)

```sql
CREATE TABLE acc_account_determination (
    acc_account_determination_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    doc_type              VARCHAR(30) NOT NULL COMMENT 'PURCHASE, JUTE_PURCHASE, SALES, PURCHASE_RETURN, SALES_RETURN',
    line_type             VARCHAR(30) NOT NULL COMMENT 'MATERIAL, CGST_INPUT, SGST_INPUT, IGST_INPUT, CGST_OUTPUT, SGST_OUTPUT, IGST_OUTPUT, CREDITOR, DEBTOR, TDS, FREIGHT, ROUND_OFF, CLAIMS',
    acc_ledger_id         INT NOT NULL,
    item_grp_id           INT NULL COMMENT 'Optional override by item group (NULL = default for all)',
    is_default            TINYINT DEFAULT 1,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_co_doc_line (co_id, doc_type, line_type, is_default),
    KEY idx_item_grp (co_id, doc_type, line_type, item_grp_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id)
);
```

**Default determination rules per company:**

| doc_type | line_type | Default Ledger |
|----------|-----------|----------------|
| PURCHASE | MATERIAL | Purchase Account |
| PURCHASE | CGST_INPUT | CGST Input |
| PURCHASE | SGST_INPUT | SGST Input |
| PURCHASE | IGST_INPUT | IGST Input |
| PURCHASE | CREDITOR | (resolved from party_id → party ledger) |
| PURCHASE | ROUND_OFF | Round Off |
| JUTE_PURCHASE | MATERIAL | Jute Purchase Account |
| JUTE_PURCHASE | TDS | TDS Payable |
| JUTE_PURCHASE | FREIGHT | Freight Inward |
| JUTE_PURCHASE | CLAIMS | Claims Receivable |
| SALES | REVENUE | Sales Account |
| SALES | CGST_OUTPUT | CGST Output |
| SALES | SGST_OUTPUT | SGST Output |
| SALES | IGST_OUTPUT | IGST Output |
| SALES | DEBTOR | (resolved from party_id → party ledger) |
| SALES | ROUND_OFF | Round Off |

Note: CREDITOR and DEBTOR line_types resolve to the party's `acc_ledger` (found via `party_id` → `acc_ledger WHERE party_id = X AND ledger_type = 'P'`), not a fixed ledger.

#### acc_voucher (Core transaction document)

```sql
CREATE TABLE acc_voucher (
    acc_voucher_id        BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    branch_id             INT NULL COMMENT 'Mandatory for auto-posted, optional for company-wide entries',
    acc_voucher_type_id   INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    voucher_no            VARCHAR(30) NOT NULL,
    voucher_date          DATE NOT NULL,
    party_id              INT NULL COMMENT 'Primary party (supplier/customer)',
    ref_no                VARCHAR(50) NULL COMMENT 'External ref (vendor invoice no, cheque no)',
    ref_date              DATE NULL,
    narration             VARCHAR(500) NULL,
    total_amount          DECIMAL(15,2) NOT NULL COMMENT 'Sum of all DR lines = sum of all CR lines',
    source_doc_type       VARCHAR(30) NULL COMMENT 'PROC_BILLPASS, JUTE_BILLPASS, SALES_INVOICE, NULL for manual',
    source_doc_id         BIGINT NULL COMMENT 'FK to source document',
    is_auto_posted        TINYINT DEFAULT 0,
    is_reversed           TINYINT DEFAULT 0,
    reversed_by_voucher_id BIGINT NULL,
    reversal_of_voucher_id BIGINT NULL,
    status_id             INT DEFAULT 3 COMMENT 'Auto-posted = 3 (approved). Manual = 21 (draft) → workflow',
    approval_level        INT DEFAULT 0,
    place_of_supply_state_code INT NULL COMMENT 'State code for GST',
    branch_gstin          VARCHAR(20) NULL COMMENT 'Denormalized from branch_mst.gst_no',
    party_gstin           VARCHAR(20) NULL COMMENT 'Denormalized from party_branch_mst.gst_no',
    currency_id           INT NULL COMMENT 'NULL = INR (default). FK to currency master if multi-currency enabled',
    exchange_rate         DECIMAL(12,6) NULL COMMENT 'Exchange rate to INR at voucher date. NULL = 1.0',
    approved_by           INT NULL COMMENT 'user_id who gave final approval',
    approved_date_time    TIMESTAMP NULL COMMENT 'Timestamp of final approval',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_date (co_id, voucher_date),
    KEY idx_co_type_date (co_id, acc_voucher_type_id, voucher_date),
    KEY idx_branch_date (branch_id, voucher_date),
    KEY idx_source (source_doc_type, source_doc_id),
    KEY idx_party (party_id),
    KEY idx_fy (acc_financial_year_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (acc_voucher_type_id) REFERENCES acc_voucher_type(acc_voucher_type_id),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

#### acc_voucher_line (Debit/Credit entries)

```sql
CREATE TABLE acc_voucher_line (
    acc_voucher_line_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    acc_ledger_id         INT NOT NULL,
    dr_cr                 CHAR(1) NOT NULL COMMENT 'D=Debit, C=Credit',
    amount                DECIMAL(15,2) NOT NULL COMMENT 'Always positive',
    branch_id             INT NULL COMMENT 'Line-level override for inter-branch journals',
    party_id              INT NULL COMMENT 'Sub-ledger party for this line',
    narration             VARCHAR(255) NULL,
    source_line_type      VARCHAR(30) NULL COMMENT 'MATERIAL, CGST, SGST, IGST, TDS, FREIGHT, ROUND_OFF etc.',
    cost_center_id        INT NULL COMMENT 'Reserved for Phase 3',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_voucher (acc_voucher_id),
    KEY idx_ledger (acc_ledger_id, dr_cr),
    KEY idx_branch (branch_id),
    KEY idx_party (party_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

**Invariant (enforced in application):** `SUM(amount WHERE dr_cr='D') = SUM(amount WHERE dr_cr='C')` for every voucher.

#### acc_voucher_gst (GST detail per voucher)

```sql
CREATE TABLE acc_voucher_gst (
    acc_voucher_gst_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    hsn_sac_code          VARCHAR(20) NULL,
    taxable_amount        DECIMAL(15,2) NOT NULL,
    cgst_rate             DECIMAL(5,2) DEFAULT 0,
    cgst_amount           DECIMAL(15,2) DEFAULT 0,
    sgst_rate             DECIMAL(5,2) DEFAULT 0,
    sgst_amount           DECIMAL(15,2) DEFAULT 0,
    igst_rate             DECIMAL(5,2) DEFAULT 0,
    igst_amount           DECIMAL(15,2) DEFAULT 0,
    cess_amount           DECIMAL(15,2) DEFAULT 0,
    total_tax             DECIMAL(15,2) DEFAULT 0,
    gst_type              ENUM('INTRA','INTER') NOT NULL,
    supply_type           VARCHAR(10) NULL COMMENT 'B2B, B2C, B2CL, EXPORT, NIL, EXEMPT',
    is_rcm                TINYINT DEFAULT 0 COMMENT '1=Reverse Charge Mechanism applicable',
    itc_eligibility       VARCHAR(15) DEFAULT 'ELIGIBLE' COMMENT 'ELIGIBLE, INELIGIBLE, PARTIAL — for ITC claim tracking',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_voucher (acc_voucher_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**RCM (Reverse Charge):** When `is_rcm = 1`, the buyer (not seller) is liable to pay GST. Auto-posting must create: DR Input GST (claimable), CR RCM GST Payable. This is reported separately in GSTR-3B Table 3.1(d).

**ITC Eligibility:** Blocked credits under Section 17(5) (motor vehicles, food & beverages, health insurance, etc.) should be marked `INELIGIBLE`. Partial credits apply when goods/services are used for both taxable and exempt supplies (Rule 42/43 reversal).

#### acc_bill_ref (Bill-wise tracking for AR/AP)

```sql
CREATE TABLE acc_bill_ref (
    acc_bill_ref_id       BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_voucher_id        BIGINT NOT NULL,
    acc_voucher_line_id   BIGINT NOT NULL,
    party_id              INT NOT NULL,
    ref_type              ENUM('NEW','AGAINST','ADVANCE','ON_ACCOUNT') NOT NULL,
    ref_name              VARCHAR(50) NOT NULL COMMENT 'Invoice number / bill reference',
    ref_amount            DECIMAL(15,2) NOT NULL,
    ref_date              DATE NULL COMMENT 'Invoice date',
    due_date              DATE NULL COMMENT 'Payment due date',
    pending_amount        DECIMAL(15,2) NOT NULL COMMENT 'Outstanding = ref_amount - settled',
    status                ENUM('OPEN','PARTIAL','CLOSED') DEFAULT 'OPEN',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_party_status (party_id, status),
    KEY idx_voucher (acc_voucher_id),
    KEY idx_co_party (co_id, party_id),
    KEY idx_ref_name (ref_name),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id),
    FOREIGN KEY (acc_voucher_line_id) REFERENCES acc_voucher_line(acc_voucher_line_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

#### acc_bill_settlement (Payment ↔ Bill linkage)

```sql
CREATE TABLE acc_bill_settlement (
    acc_bill_settlement_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_bill_ref_id       BIGINT NOT NULL COMMENT 'The original bill being settled',
    settlement_voucher_id BIGINT NOT NULL COMMENT 'The payment/receipt voucher',
    settled_amount        DECIMAL(15,2) NOT NULL,
    settlement_date       DATE NOT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_bill_ref (acc_bill_ref_id),
    KEY idx_settlement_voucher (settlement_voucher_id),
    FOREIGN KEY (acc_bill_ref_id) REFERENCES acc_bill_ref(acc_bill_ref_id),
    FOREIGN KEY (settlement_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

#### acc_voucher_numbering (Auto-numbering sequence per type/branch/FY)

```sql
CREATE TABLE acc_voucher_numbering (
    acc_voucher_numbering_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_voucher_type_id   INT NOT NULL,
    branch_id             INT NULL COMMENT 'NULL = company-wide numbering',
    acc_financial_year_id INT NOT NULL,
    prefix                VARCHAR(20) NULL COMMENT 'e.g., PAY/MN01/25-26/',
    current_number        INT DEFAULT 0,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_type_branch_fy (co_id, acc_voucher_type_id, branch_id, acc_financial_year_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_voucher_type_id) REFERENCES acc_voucher_type(acc_voucher_type_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id)
);
```

#### acc_voucher_approval_log (Audit trail for voucher approvals)

```sql
CREATE TABLE acc_voucher_approval_log (
    acc_voucher_approval_log_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    action                VARCHAR(20) NOT NULL COMMENT 'OPEN, SEND_FOR_APPROVAL, APPROVE, REJECT, REOPEN, REVERSE',
    from_status_id        INT NULL,
    to_status_id          INT NOT NULL,
    from_approval_level   INT NULL,
    to_approval_level     INT NULL,
    action_by             INT NOT NULL COMMENT 'user_id who performed the action',
    action_date_time      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    remarks               VARCHAR(500) NULL,
    active                TINYINT DEFAULT 1,
    KEY idx_voucher (acc_voucher_id),
    KEY idx_action_by (action_by),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

#### acc_voucher_warning (Compliance warning acknowledgment trail)

```sql
CREATE TABLE acc_voucher_warning (
    acc_voucher_warning_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    warning_code          VARCHAR(30) NOT NULL COMMENT 'e.g., DUPLICATE_ENTRY, TDS_MISSING, CREDIT_LIMIT_EXCEEDED',
    warning_severity      VARCHAR(10) NOT NULL COMMENT 'HIGH, MEDIUM, LOW',
    warning_message       VARCHAR(500) NOT NULL,
    acknowledged_by       INT NOT NULL,
    acknowledged_date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active                TINYINT DEFAULT 1,
    KEY idx_voucher (acc_voucher_id),
    KEY idx_code (warning_code),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

#### acc_opening_bill (Bill-wise opening balance for party ledgers)

```sql
CREATE TABLE acc_opening_bill (
    acc_opening_bill_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_ledger_id         INT NOT NULL COMMENT 'Party ledger',
    party_id              INT NOT NULL,
    acc_financial_year_id INT NOT NULL COMMENT 'FY for which this is the opening',
    ref_name              VARCHAR(50) NOT NULL COMMENT 'Invoice number / bill reference',
    ref_amount            DECIMAL(15,2) NOT NULL,
    ref_date              DATE NULL COMMENT 'Original invoice date',
    due_date              DATE NULL COMMENT 'Payment due date',
    pending_amount        DECIMAL(15,2) NOT NULL COMMENT 'Amount still outstanding at FY start',
    dr_cr                 CHAR(1) NOT NULL COMMENT 'D=Receivable, C=Payable',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_party (co_id, party_id),
    KEY idx_ledger (acc_ledger_id),
    KEY idx_fy (acc_financial_year_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id)
);
```

**Validation:** On import, `SUM(pending_amount)` for a party ledger must equal the ledger's `opening_balance`. The system should warn (not block) if there is a mismatch.

### 4.2 Phase 2 — Additional Tables

#### acc_bank_account

```sql
CREATE TABLE acc_bank_account (
    acc_bank_account_id   INT PRIMARY KEY AUTO_INCREMENT,
    acc_ledger_id         INT NOT NULL UNIQUE,
    co_id                 INT NOT NULL,
    branch_id             INT NULL,
    bank_name             VARCHAR(100) NOT NULL,
    account_no            VARCHAR(30) NOT NULL,
    ifsc_code             VARCHAR(15) NULL,
    account_type          VARCHAR(20) NULL COMMENT 'CURRENT, SAVINGS, OD, CC',
    od_limit              DECIMAL(15,2) NULL COMMENT 'Overdraft/CC sanctioned limit',
    interest_rate         DECIMAL(5,2) NULL COMMENT 'Annual interest rate for OD/CC',
    min_balance           DECIMAL(15,2) NULL COMMENT 'Minimum balance requirement',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);
```

#### acc_bank_reconciliation

```sql
CREATE TABLE acc_bank_reconciliation (
    acc_bank_recon_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_bank_account_id   INT NOT NULL,
    acc_voucher_line_id   BIGINT NOT NULL,
    book_date             DATE NOT NULL,
    bank_date             DATE NULL COMMENT 'Date cleared in bank',
    instrument_no         VARCHAR(30) NULL,
    instrument_date       DATE NULL,
    is_reconciled         TINYINT DEFAULT 0,
    reconciled_by         INT NULL,
    reconciled_date_time  TIMESTAMP NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_bank_recon (acc_bank_account_id, is_reconciled),
    FOREIGN KEY (acc_bank_account_id) REFERENCES acc_bank_account(acc_bank_account_id),
    FOREIGN KEY (acc_voucher_line_id) REFERENCES acc_voucher_line(acc_voucher_line_id)
);
```

#### acc_tds_detail

```sql
CREATE TABLE acc_tds_detail (
    acc_tds_detail_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    party_id              INT NOT NULL,
    tds_section           VARCHAR(10) NOT NULL COMMENT '194C, 194J, 194I, etc.',
    tds_rate              DECIMAL(5,2) NOT NULL,
    tds_base_amount       DECIMAL(15,2) NOT NULL,
    tds_amount            DECIMAL(15,2) NOT NULL,
    pan_of_deductee       VARCHAR(15) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_voucher (acc_voucher_id),
    KEY idx_party (party_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

#### acc_payment_detail (Cheque/instrument tracking)

```sql
CREATE TABLE acc_payment_detail (
    acc_payment_detail_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_voucher_id        BIGINT NOT NULL,
    payment_mode          VARCHAR(10) NOT NULL COMMENT 'CASH, CHEQUE, NEFT, RTGS, UPI, DD',
    instrument_no         VARCHAR(30) NULL,
    instrument_date       DATE NULL,
    drawn_on_bank         VARCHAR(100) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

#### acc_ageing_slab (Configurable ageing buckets)

```sql
CREATE TABLE acc_ageing_slab (
    acc_ageing_slab_id    INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    slab_name             VARCHAR(30) NOT NULL,
    from_days             INT NOT NULL,
    to_days               INT NULL COMMENT 'NULL for open-ended (e.g., 180+)',
    sequence_no           INT NOT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id)
);
```

**Default slabs:** 0-30, 31-60, 61-90, 91-180, 180+

#### acc_cheque_register (Cheque book and per-cheque tracking)

```sql
CREATE TABLE acc_cheque_register (
    acc_cheque_register_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_bank_account_id   INT NOT NULL,
    cheque_no             VARCHAR(20) NOT NULL,
    cheque_date           DATE NULL,
    party_id              INT NULL COMMENT 'Issued to / received from',
    amount                DECIMAL(15,2) NULL,
    acc_voucher_id        BIGINT NULL COMMENT 'Linked payment/receipt voucher',
    status                VARCHAR(15) NOT NULL DEFAULT 'BLANK' COMMENT 'BLANK, ISSUED, CLEARED, BOUNCED, CANCELLED, STALE, STOP_PAYMENT',
    status_date           DATE NULL COMMENT 'Date of last status change',
    bounce_charges        DECIMAL(10,2) NULL,
    remarks               VARCHAR(255) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_bank_cheque (acc_bank_account_id, cheque_no),
    KEY idx_co_status (co_id, status),
    KEY idx_party (party_id),
    KEY idx_voucher (acc_voucher_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_bank_account_id) REFERENCES acc_bank_account(acc_bank_account_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**Cheque lifecycle:** BLANK → ISSUED (linked to Payment voucher) → CLEARED (bank reconciliation confirms) or BOUNCED (creates reversal + bank charges) or CANCELLED or STALE (>3 months uncleared).

#### acc_pdc_register (Post-dated cheque tracking)

```sql
CREATE TABLE acc_pdc_register (
    acc_pdc_register_id   BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    pdc_type              VARCHAR(10) NOT NULL COMMENT 'RECEIVED, ISSUED',
    party_id              INT NOT NULL,
    cheque_no             VARCHAR(20) NOT NULL,
    cheque_date           DATE NOT NULL COMMENT 'Future date on cheque',
    amount                DECIMAL(15,2) NOT NULL,
    drawn_on_bank         VARCHAR(100) NULL,
    acc_bank_account_id   INT NULL COMMENT 'Our bank for deposit/issue',
    deposit_date          DATE NULL COMMENT 'Date deposited to bank',
    realization_date      DATE NULL COMMENT 'Date actually cleared',
    acc_voucher_id        BIGINT NULL COMMENT 'Linked voucher when realized',
    status                VARCHAR(15) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING, DEPOSITED, REALIZED, BOUNCED, RETURNED',
    remarks               VARCHAR(255) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_status (co_id, status),
    KEY idx_party (party_id),
    KEY idx_cheque_date (cheque_date),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id),
    FOREIGN KEY (acc_bank_account_id) REFERENCES acc_bank_account(acc_bank_account_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**PDC workflow:** PENDING → DEPOSITED (on cheque date or before) → REALIZED (bank confirms clearing) or BOUNCED (reversal + charges). Received PDCs are not accounting entries until realized — they are contingent/off-balance-sheet until then.

#### acc_tds_challan (TDS deposit challan tracking for returns)

```sql
CREATE TABLE acc_tds_challan (
    acc_tds_challan_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    challan_date          DATE NOT NULL,
    bsr_code              VARCHAR(10) NULL COMMENT 'BSR code of collecting bank branch',
    challan_serial_no     VARCHAR(10) NULL COMMENT 'Serial number of challan',
    challan_amount        DECIMAL(15,2) NOT NULL,
    tds_section           VARCHAR(10) NOT NULL COMMENT '194C, 194J, 192, etc.',
    assessment_year       VARCHAR(10) NOT NULL COMMENT 'e.g., 2026-27',
    quarter               INT NOT NULL COMMENT '1=Apr-Jun, 2=Jul-Sep, 3=Oct-Dec, 4=Jan-Mar',
    acc_voucher_id        BIGINT NULL COMMENT 'Payment voucher for TDS deposit',
    remarks               VARCHAR(255) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_quarter (co_id, assessment_year, quarter),
    KEY idx_section (tds_section),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**Usage:** When TDS is deposited with the government, create a challan record linking to the payment voucher. This data feeds into 26Q/27Q quarterly return preparation.

#### acc_lower_deduction_cert (Section 197 certificates)

```sql
CREATE TABLE acc_lower_deduction_cert (
    acc_lower_deduction_cert_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    party_id              INT NOT NULL,
    certificate_no        VARCHAR(30) NOT NULL,
    tds_section           VARCHAR(10) NOT NULL,
    normal_rate           DECIMAL(5,2) NOT NULL COMMENT 'Standard TDS rate for this section',
    certificate_rate      DECIMAL(5,2) NOT NULL COMMENT 'Lower/nil rate per certificate',
    valid_from            DATE NOT NULL,
    valid_to              DATE NOT NULL,
    limit_amount          DECIMAL(15,2) NULL COMMENT 'Max amount covered by certificate',
    utilized_amount       DECIMAL(15,2) DEFAULT 0 COMMENT 'Amount already utilized',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_party (co_id, party_id),
    KEY idx_validity (valid_from, valid_to),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id)
);
```

**Usage:** When deducting TDS on a payment, check if party has a valid lower deduction certificate. If yes, apply the certificate rate instead of the normal rate. Update `utilized_amount`. Warn if certificate is expired or limit is exhausted. If party has no PAN, override to 20% (Sec 206AA) and warn.

#### acc_gst_reconciliation (GSTR-2A/2B matching)

```sql
CREATE TABLE acc_gst_reconciliation (
    acc_gst_recon_id      BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    tax_period            VARCHAR(10) NOT NULL COMMENT 'e.g., 032026 for March 2026',
    supplier_gstin        VARCHAR(20) NOT NULL,
    supplier_name         VARCHAR(150) NULL,
    invoice_no            VARCHAR(50) NOT NULL,
    invoice_date          DATE NOT NULL,
    taxable_amount        DECIMAL(15,2) NOT NULL,
    cgst_amount           DECIMAL(15,2) DEFAULT 0,
    sgst_amount           DECIMAL(15,2) DEFAULT 0,
    igst_amount           DECIMAL(15,2) DEFAULT 0,
    total_tax             DECIMAL(15,2) DEFAULT 0,
    source                VARCHAR(10) NOT NULL COMMENT '2A or 2B',
    acc_voucher_id        BIGINT NULL COMMENT 'Matched purchase voucher in books',
    match_status          VARCHAR(15) NOT NULL DEFAULT 'UNMATCHED' COMMENT 'MATCHED, UNMATCHED, PARTIAL, MISMATCH',
    mismatch_reason       VARCHAR(100) NULL COMMENT 'e.g., AMOUNT_DIFF, NOT_IN_BOOKS, NOT_IN_GSTR',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_period (co_id, tax_period),
    KEY idx_supplier (supplier_gstin),
    KEY idx_match (match_status),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**Workflow:** Import GSTR-2A/2B data (via CSV upload or API). Auto-match against purchase vouchers by supplier GSTIN + invoice number. Flag mismatches for review. This is essential for ITC claim validation.

#### acc_loan_account (Loan and overdraft tracking)

```sql
CREATE TABLE acc_loan_account (
    acc_loan_account_id   INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_ledger_id         INT NOT NULL COMMENT 'GL ledger for this loan',
    loan_type             VARCHAR(20) NOT NULL COMMENT 'TERM, OD, CC, VEHICLE, UNSECURED, EMPLOYEE',
    loan_name             VARCHAR(100) NOT NULL,
    loan_account_no       VARCHAR(30) NULL COMMENT 'Bank loan account number',
    lender_name           VARCHAR(100) NULL COMMENT 'Bank or lender name',
    party_id              INT NULL COMMENT 'Lender party (if in party_mst)',
    sanctioned_amount     DECIMAL(15,2) NOT NULL,
    disbursed_amount      DECIMAL(15,2) DEFAULT 0,
    interest_rate         DECIMAL(5,2) NOT NULL COMMENT 'Annual rate',
    interest_type         VARCHAR(10) NOT NULL DEFAULT 'FIXED' COMMENT 'FIXED, FLOATING',
    start_date            DATE NOT NULL,
    maturity_date         DATE NULL,
    emi_amount            DECIMAL(15,2) NULL,
    repayment_frequency   VARCHAR(10) NULL COMMENT 'MONTHLY, QUARTERLY, BULLET',
    interest_ledger_id    INT NULL COMMENT 'GL ledger for interest expense',
    status                VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE, CLOSED, RESTRUCTURED',
    branch_id             INT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_type (co_id, loan_type),
    KEY idx_ledger (acc_ledger_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (party_id) REFERENCES party_mst(party_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);
```

#### acc_loan_schedule (EMI / repayment schedule)

```sql
CREATE TABLE acc_loan_schedule (
    acc_loan_schedule_id  BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_loan_account_id   INT NOT NULL,
    installment_no        INT NOT NULL,
    due_date              DATE NOT NULL,
    principal_amount      DECIMAL(15,2) NOT NULL,
    interest_amount       DECIMAL(15,2) NOT NULL,
    total_amount          DECIMAL(15,2) NOT NULL,
    opening_balance       DECIMAL(15,2) NOT NULL,
    closing_balance       DECIMAL(15,2) NOT NULL,
    acc_voucher_id        BIGINT NULL COMMENT 'Payment voucher when installment paid',
    status                VARCHAR(10) NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING, PAID, OVERDUE',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_loan (acc_loan_account_id),
    KEY idx_due_date (due_date, status),
    FOREIGN KEY (acc_loan_account_id) REFERENCES acc_loan_account(acc_loan_account_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

**Interest accrual:** Monthly auto-journal — DR Interest on Loans A/c, CR Interest Payable A/c (or directly CR Loan A/c depending on configuration). On payment: DR Loan A/c (principal) + DR Interest Payable (interest), CR Bank A/c.

### 4.3 Phase 3 — Additional Tables

#### acc_cost_center

```sql
CREATE TABLE acc_cost_center (
    acc_cost_center_id    INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    parent_cost_center_id INT NULL,
    cost_center_name      VARCHAR(100) NOT NULL,
    cost_center_code      VARCHAR(20) NULL,
    branch_id             INT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (parent_cost_center_id) REFERENCES acc_cost_center(acc_cost_center_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);
```

#### acc_fixed_asset

```sql
CREATE TABLE acc_fixed_asset (
    acc_fixed_asset_id    INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    branch_id             INT NULL,
    asset_name            VARCHAR(150) NOT NULL,
    asset_code            VARCHAR(30) NULL,
    asset_class           VARCHAR(50) NOT NULL COMMENT 'PLANT_MACHINERY, FURNITURE, VEHICLE, BUILDING, COMPUTER',
    acc_ledger_id         INT NOT NULL COMMENT 'Asset GL account',
    accum_dep_ledger_id   INT NOT NULL COMMENT 'Accumulated depreciation GL',
    dep_expense_ledger_id INT NOT NULL COMMENT 'Depreciation expense GL',
    purchase_date         DATE NOT NULL,
    purchase_value        DECIMAL(15,2) NOT NULL,
    salvage_value         DECIMAL(15,2) DEFAULT 0,
    useful_life_months    INT NOT NULL,
    depreciation_method   ENUM('SLM','WDV') NOT NULL,
    depreciation_rate     DECIMAL(5,2) NOT NULL,
    status                ENUM('ACTIVE','DISPOSED','TRANSFERRED') DEFAULT 'ACTIVE',
    disposal_date         DATE NULL,
    disposal_value        DECIMAL(15,2) NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_branch (co_id, branch_id),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id)
);
```

#### acc_depreciation_run

```sql
CREATE TABLE acc_depreciation_run (
    acc_depreciation_run_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    period_start          DATE NOT NULL,
    period_end            DATE NOT NULL,
    run_date              DATE NOT NULL,
    acc_voucher_id        BIGINT NULL COMMENT 'The JV created for this depreciation',
    total_depreciation    DECIMAL(15,2) NOT NULL,
    status                ENUM('DRAFT','POSTED','REVERSED') DEFAULT 'DRAFT',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id),
    FOREIGN KEY (acc_voucher_id) REFERENCES acc_voucher(acc_voucher_id)
);
```

#### acc_depreciation_detail

```sql
CREATE TABLE acc_depreciation_detail (
    acc_dep_detail_id     BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_depreciation_run_id INT NOT NULL,
    acc_fixed_asset_id    INT NOT NULL,
    opening_value         DECIMAL(15,2) NOT NULL,
    depreciation_amount   DECIMAL(15,2) NOT NULL,
    closing_value         DECIMAL(15,2) NOT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (acc_depreciation_run_id) REFERENCES acc_depreciation_run(acc_depreciation_run_id),
    FOREIGN KEY (acc_fixed_asset_id) REFERENCES acc_fixed_asset(acc_fixed_asset_id)
);
```

#### acc_budget / acc_budget_line

```sql
CREATE TABLE acc_budget (
    acc_budget_id         INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_financial_year_id INT NOT NULL,
    budget_name           VARCHAR(100) NOT NULL,
    branch_id             INT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_financial_year_id) REFERENCES acc_financial_year(acc_financial_year_id)
);

CREATE TABLE acc_budget_line (
    acc_budget_line_id    BIGINT PRIMARY KEY AUTO_INCREMENT,
    acc_budget_id         INT NOT NULL,
    acc_ledger_id         INT NOT NULL,
    period_start          DATE NOT NULL,
    period_end            DATE NOT NULL,
    budget_amount         DECIMAL(15,2) NOT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (acc_budget_id) REFERENCES acc_budget(acc_budget_id),
    FOREIGN KEY (acc_ledger_id) REFERENCES acc_ledger(acc_ledger_id)
);
```

#### acc_schedule_iii_map (Balance Sheet / P&L to Companies Act Schedule III mapping)

```sql
CREATE TABLE acc_schedule_iii_map (
    acc_schedule_iii_map_id INT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    acc_ledger_group_id   INT NOT NULL COMMENT 'Maps ledger group to Schedule III line',
    report_type           VARCHAR(5) NOT NULL COMMENT 'BS or PL',
    schedule_section      VARCHAR(50) NOT NULL COMMENT 'e.g., EQUITY, NON_CURRENT_ASSETS, CURRENT_ASSETS, REVENUE_FROM_OPERATIONS',
    line_item             VARCHAR(100) NOT NULL COMMENT 'e.g., Trade Receivables, Inventories, Revenue from Sale of Products',
    sequence_no           INT NOT NULL COMMENT 'Display order within section',
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_report (co_id, report_type),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (acc_ledger_group_id) REFERENCES acc_ledger_group(acc_ledger_group_id)
);
```

**Usage:** Seed with default mappings per the 28 predefined groups. Accountant can customize for the company. Schedule III reports query this mapping to format the Balance Sheet and P&L per Companies Act 2013 requirements. Reports should show current year and previous year comparative columns.

#### acc_prepaid_schedule (Prepaid expense amortization)

```sql
CREATE TABLE acc_prepaid_schedule (
    acc_prepaid_schedule_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    co_id                 INT NOT NULL,
    description           VARCHAR(150) NOT NULL COMMENT 'e.g., Annual insurance premium 2025-26',
    prepaid_ledger_id     INT NOT NULL COMMENT 'Prepaid expense ledger (BS side)',
    expense_ledger_id     INT NOT NULL COMMENT 'Expense ledger to amortize into (PL side)',
    total_amount          DECIMAL(15,2) NOT NULL,
    start_date            DATE NOT NULL,
    end_date              DATE NOT NULL,
    frequency             VARCHAR(10) NOT NULL DEFAULT 'MONTHLY' COMMENT 'MONTHLY, QUARTERLY',
    total_periods         INT NOT NULL,
    amortized_periods     INT DEFAULT 0,
    amortized_amount      DECIMAL(15,2) DEFAULT 0,
    remaining_amount      DECIMAL(15,2) NOT NULL,
    source_voucher_id     BIGINT NULL COMMENT 'Original payment voucher',
    status                VARCHAR(10) NOT NULL DEFAULT 'ACTIVE' COMMENT 'ACTIVE, COMPLETED, CANCELLED',
    branch_id             INT NULL,
    active                TINYINT DEFAULT 1,
    updated_by            INT NOT NULL,
    updated_date_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_co_status (co_id, status),
    FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    FOREIGN KEY (prepaid_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (expense_ledger_id) REFERENCES acc_ledger(acc_ledger_id),
    FOREIGN KEY (source_voucher_id) REFERENCES acc_voucher(acc_voucher_id),
    FOREIGN KEY (branch_id) REFERENCES branch_mst(branch_id)
);
```

**Amortization auto-journal:** Monthly (or quarterly), for each active prepaid schedule:
```
Journal Voucher (type = JOURNAL, source_doc_type = PREPAID_AMORTIZATION)
  DR  Insurance Expense A/c (or relevant expense)    [total_amount / total_periods]
      CR  Prepaid Insurance A/c (or relevant prepaid) [same amount]
```

---

## 5. Report Queries (Phase 1)

### 5.1 Trial Balance

```sql
SELECT
    l.acc_ledger_id,
    l.ledger_name,
    g.group_name,
    g.nature,
    COALESCE(ob.opening_balance, 0) AS opening_balance,
    ob.opening_balance_type,
    SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END) AS period_debit,
    SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS period_credit,
    COALESCE(ob.opening_balance, 0)
        + SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE 0 END)
        - SUM(CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE 0 END) AS closing_balance
FROM acc_ledger l
JOIN acc_ledger_group g ON l.acc_ledger_group_id = g.acc_ledger_group_id
LEFT JOIN acc_voucher_line vl ON vl.acc_ledger_id = l.acc_ledger_id AND vl.active = 1
LEFT JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
    AND v.status_id = 3
    AND v.active = 1
    AND v.voucher_date BETWEEN :from_date AND :to_date
    AND (:branch_id IS NULL OR v.branch_id = :branch_id)
LEFT JOIN (
    SELECT acc_ledger_id, opening_balance,
           opening_balance_type
    FROM acc_ledger WHERE opening_fy_id = :fy_id
) ob ON ob.acc_ledger_id = l.acc_ledger_id
WHERE l.co_id = :co_id AND l.active = 1
GROUP BY l.acc_ledger_id
HAVING period_debit != 0 OR period_credit != 0 OR opening_balance != 0
ORDER BY g.sequence_no, l.ledger_name
```

### 5.2 Profit & Loss Statement

Derived from Trial Balance by filtering `g.is_revenue = 1` (P&L side groups) and grouping by `g.affects_gross_profit` (Trading vs P&L proper).

### 5.3 Balance Sheet

Derived from Trial Balance by filtering `g.is_revenue = 0` (BS side groups). Schedule III format mapped via group hierarchy.

### 5.4 Party Outstanding (Debtors/Creditors)

```sql
SELECT
    p.party_id,
    p.supp_name AS party_name,
    br.ref_name AS bill_no,
    br.ref_date AS bill_date,
    br.due_date,
    br.ref_amount AS bill_amount,
    br.pending_amount AS outstanding,
    DATEDIFF(CURDATE(), br.due_date) AS overdue_days
FROM acc_bill_ref br
JOIN party_mst p ON br.party_id = p.party_id
JOIN acc_voucher v ON br.acc_voucher_id = v.acc_voucher_id
WHERE br.co_id = :co_id
  AND br.status IN ('OPEN', 'PARTIAL')
  AND br.active = 1
  AND (:party_type IS NULL OR
       (:party_type = 'CREDITOR' AND v.acc_voucher_type_id IN (SELECT acc_voucher_type_id FROM acc_voucher_type WHERE type_category = 'PURCHASE'))
       OR
       (:party_type = 'DEBTOR' AND v.acc_voucher_type_id IN (SELECT acc_voucher_type_id FROM acc_voucher_type WHERE type_category = 'SALES'))
      )
  AND (:branch_id IS NULL OR v.branch_id = :branch_id)
ORDER BY br.due_date ASC
```

### 5.5 Ageing Analysis

```sql
SELECT
    p.party_id,
    p.supp_name AS party_name,
    SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) <= 0 THEN br.pending_amount ELSE 0 END) AS not_due,
    SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 1 AND 30 THEN br.pending_amount ELSE 0 END) AS days_1_30,
    SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 31 AND 60 THEN br.pending_amount ELSE 0 END) AS days_31_60,
    SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) BETWEEN 61 AND 90 THEN br.pending_amount ELSE 0 END) AS days_61_90,
    SUM(CASE WHEN DATEDIFF(CURDATE(), br.due_date) > 90 THEN br.pending_amount ELSE 0 END) AS above_90,
    SUM(br.pending_amount) AS total_outstanding
FROM acc_bill_ref br
JOIN party_mst p ON br.party_id = p.party_id
WHERE br.co_id = :co_id
  AND br.status IN ('OPEN', 'PARTIAL')
  AND br.active = 1
GROUP BY p.party_id
ORDER BY total_outstanding DESC
```

### 5.6 Ledger Report

```sql
SELECT
    v.voucher_date,
    v.voucher_no,
    vt.type_name AS voucher_type,
    vl.dr_cr,
    vl.amount,
    CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE NULL END AS debit,
    CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE NULL END AS credit,
    v.narration,
    v.ref_no,
    -- Contra ledger (the "other side")
    GROUP_CONCAT(DISTINCT cl.ledger_name) AS contra_ledgers
FROM acc_voucher_line vl
JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
LEFT JOIN acc_voucher_line cvl ON cvl.acc_voucher_id = v.acc_voucher_id
    AND cvl.acc_voucher_line_id != vl.acc_voucher_line_id
LEFT JOIN acc_ledger cl ON cvl.acc_ledger_id = cl.acc_ledger_id
WHERE vl.acc_ledger_id = :ledger_id
  AND v.status_id = 3
  AND v.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:branch_id IS NULL OR v.branch_id = :branch_id)
GROUP BY vl.acc_voucher_line_id
ORDER BY v.voucher_date, v.voucher_no
```

### 5.7 Day Book

```sql
SELECT
    v.voucher_date,
    v.voucher_no,
    vt.type_name AS voucher_type,
    v.total_amount,
    v.narration,
    v.ref_no,
    p.supp_name AS party_name,
    bm.branch_name,
    v.is_auto_posted,
    v.source_doc_type
FROM acc_voucher v
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
LEFT JOIN party_mst p ON v.party_id = p.party_id
LEFT JOIN branch_mst bm ON v.branch_id = bm.branch_id
WHERE v.co_id = :co_id
  AND v.status_id = 3
  AND v.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:branch_id IS NULL OR v.branch_id = :branch_id)
  AND (:voucher_type_id IS NULL OR v.acc_voucher_type_id = :voucher_type_id)
ORDER BY v.voucher_date, vt.type_name, v.voucher_no
```

### 5.8 Cash Book

```sql
SELECT
    v.voucher_date,
    v.voucher_no,
    vt.type_name AS voucher_type,
    vl.dr_cr,
    vl.amount,
    CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE NULL END AS receipt,
    CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE NULL END AS payment,
    v.narration,
    v.ref_no,
    GROUP_CONCAT(DISTINCT cl.ledger_name) AS contra_ledgers
FROM acc_voucher_line vl
JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_ledger cash_l ON vl.acc_ledger_id = cash_l.acc_ledger_id AND cash_l.ledger_type = 'C'
LEFT JOIN acc_voucher_line cvl ON cvl.acc_voucher_id = v.acc_voucher_id
    AND cvl.acc_voucher_line_id != vl.acc_voucher_line_id
LEFT JOIN acc_ledger cl ON cvl.acc_ledger_id = cl.acc_ledger_id
WHERE cash_l.co_id = :co_id
  AND v.status_id = 3
  AND v.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:branch_id IS NULL OR v.branch_id = :branch_id)
GROUP BY vl.acc_voucher_line_id
ORDER BY v.voucher_date, v.voucher_no
```

### 5.9 Bank Book

```sql
SELECT
    v.voucher_date,
    v.voucher_no,
    vt.type_name AS voucher_type,
    ba.bank_name,
    ba.account_no,
    vl.dr_cr,
    vl.amount,
    CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE NULL END AS deposit,
    CASE WHEN vl.dr_cr = 'C' THEN vl.amount ELSE NULL END AS withdrawal,
    v.narration,
    v.ref_no,
    pd.payment_mode,
    pd.instrument_no,
    br.is_reconciled,
    br.bank_date AS cleared_date,
    GROUP_CONCAT(DISTINCT cl.ledger_name) AS contra_ledgers
FROM acc_voucher_line vl
JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_ledger bank_l ON vl.acc_ledger_id = bank_l.acc_ledger_id AND bank_l.ledger_type = 'B'
JOIN acc_bank_account ba ON bank_l.acc_ledger_id = ba.acc_ledger_id
LEFT JOIN acc_payment_detail pd ON pd.acc_voucher_id = v.acc_voucher_id
LEFT JOIN acc_bank_reconciliation br ON br.acc_voucher_line_id = vl.acc_voucher_line_id
LEFT JOIN acc_voucher_line cvl ON cvl.acc_voucher_id = v.acc_voucher_id
    AND cvl.acc_voucher_line_id != vl.acc_voucher_line_id
LEFT JOIN acc_ledger cl ON cvl.acc_ledger_id = cl.acc_ledger_id
WHERE bank_l.co_id = :co_id
  AND v.status_id = 3
  AND v.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:bank_account_id IS NULL OR ba.acc_bank_account_id = :bank_account_id)
  AND (:branch_id IS NULL OR v.branch_id = :branch_id)
GROUP BY vl.acc_voucher_line_id
ORDER BY v.voucher_date, v.voucher_no
```

### 5.10 TDS Register

```sql
SELECT
    td.tds_section,
    p.supp_name AS party_name,
    p.party_pan_no AS pan,
    v.voucher_date,
    v.voucher_no,
    td.tds_base_amount,
    td.tds_rate,
    td.tds_amount,
    tc.challan_date,
    tc.bsr_code,
    tc.challan_serial_no,
    tc.challan_amount,
    QUARTER(v.voucher_date) AS quarter
FROM acc_tds_detail td
JOIN acc_voucher v ON td.acc_voucher_id = v.acc_voucher_id
JOIN party_mst p ON td.party_id = p.party_id
LEFT JOIN acc_tds_challan tc ON tc.co_id = v.co_id
    AND tc.tds_section = td.tds_section
    AND tc.quarter = CASE
        WHEN MONTH(v.voucher_date) BETWEEN 4 AND 6 THEN 1
        WHEN MONTH(v.voucher_date) BETWEEN 7 AND 9 THEN 2
        WHEN MONTH(v.voucher_date) BETWEEN 10 AND 12 THEN 3
        ELSE 4
    END
WHERE v.co_id = :co_id
  AND v.status_id = 3
  AND v.active = 1
  AND td.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:tds_section IS NULL OR td.tds_section = :tds_section)
  AND (:party_id IS NULL OR td.party_id = :party_id)
ORDER BY td.tds_section, v.voucher_date
```

### 5.11 GSTR-1 Detail (B2B Outward Supplies)

```sql
-- B2B Invoices (for registered recipients)
SELECT
    v.party_gstin AS recipient_gstin,
    p.supp_name AS recipient_name,
    v.voucher_no AS invoice_no,
    v.voucher_date AS invoice_date,
    v.total_amount AS invoice_value,
    vg.hsn_sac_code,
    vg.taxable_amount,
    vg.cgst_rate, vg.cgst_amount,
    vg.sgst_rate, vg.sgst_amount,
    vg.igst_rate, vg.igst_amount,
    vg.cess_amount,
    vg.gst_type,
    vg.supply_type,
    vg.is_rcm,
    v.place_of_supply_state_code
FROM acc_voucher v
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_voucher_gst vg ON v.acc_voucher_id = vg.acc_voucher_id
LEFT JOIN party_mst p ON v.party_id = p.party_id
WHERE v.co_id = :co_id
  AND vt.type_category = 'SALES'
  AND v.status_id = 3
  AND v.active = 1
  AND vg.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:branch_gstin IS NULL OR v.branch_gstin = :branch_gstin)
  AND v.party_gstin IS NOT NULL -- B2B only (has GSTIN)
ORDER BY v.voucher_date, v.voucher_no
```

**Additional GSTR-1 sections (separate queries):**
- **B2CS:** Same as above but `v.party_gstin IS NULL AND v.total_amount <= 250000`
- **B2CL:** `v.party_gstin IS NULL AND v.total_amount > 250000` (inter-state only)
- **HSN Summary:** `GROUP BY vg.hsn_sac_code` with SUM of quantities, taxable, and tax amounts
- **Document Summary:** `GROUP BY vt.type_category` with count and number ranges
- **Credit/Debit Notes:** `vt.type_category IN ('CREDIT_NOTE', 'DEBIT_NOTE')`

### 5.12 GSTR-3B Summary

```sql
-- Table 3.1: Outward supplies
SELECT
    'Outward taxable (other than zero/nil/exempt)' AS description,
    SUM(vg.taxable_amount) AS taxable_value,
    SUM(vg.igst_amount) AS igst,
    SUM(vg.cgst_amount) AS cgst,
    SUM(vg.sgst_amount) AS sgst,
    SUM(vg.cess_amount) AS cess
FROM acc_voucher v
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_voucher_gst vg ON v.acc_voucher_id = vg.acc_voucher_id
WHERE v.co_id = :co_id
  AND vt.type_category = 'SALES'
  AND v.status_id = 3
  AND v.active = 1
  AND vg.active = 1
  AND vg.supply_type NOT IN ('NIL', 'EXEMPT')
  AND v.voucher_date BETWEEN :from_date AND :to_date
  AND (:branch_gstin IS NULL OR v.branch_gstin = :branch_gstin)

UNION ALL

-- Table 3.1(d): Inward supplies liable to reverse charge
SELECT
    'Inward supplies (RCM)' AS description,
    SUM(vg.taxable_amount),
    SUM(vg.igst_amount),
    SUM(vg.cgst_amount),
    SUM(vg.sgst_amount),
    SUM(vg.cess_amount)
FROM acc_voucher v
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_voucher_gst vg ON v.acc_voucher_id = vg.acc_voucher_id
WHERE v.co_id = :co_id
  AND vt.type_category = 'PURCHASE'
  AND vg.is_rcm = 1
  AND v.status_id = 3
  AND v.active = 1
  AND vg.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date

UNION ALL

-- Table 4: Eligible ITC
SELECT
    'ITC Available (from invoices)' AS description,
    SUM(vg.taxable_amount),
    SUM(vg.igst_amount),
    SUM(vg.cgst_amount),
    SUM(vg.sgst_amount),
    SUM(vg.cess_amount)
FROM acc_voucher v
JOIN acc_voucher_type vt ON v.acc_voucher_type_id = vt.acc_voucher_type_id
JOIN acc_voucher_gst vg ON v.acc_voucher_id = vg.acc_voucher_id
WHERE v.co_id = :co_id
  AND vt.type_category = 'PURCHASE'
  AND v.status_id = 3
  AND v.active = 1
  AND vg.active = 1
  AND vg.itc_eligibility = 'ELIGIBLE'
  AND v.voucher_date BETWEEN :from_date AND :to_date
```

### 5.13 Cash Flow Statement (Indirect Method)

Derived from Trial Balance movement between two dates. Not a single SQL query — computed in application logic:

1. **Net Profit:** Sum of P&L side closing balances (Income - Expense groups)
2. **Operating Activities:** Net Profit + Non-cash adjustments (Depreciation, Provisions) + Working capital changes (Debtors, Creditors, Stock movement)
3. **Investing Activities:** Movement in Fixed Assets group, Investments group
4. **Financing Activities:** Movement in Loans (Liability) group, Capital Account group, Dividends paid

```sql
-- Working capital movement helper
SELECT
    g.group_name,
    g.nature,
    SUM(CASE WHEN vl.dr_cr = 'D' THEN vl.amount ELSE -vl.amount END) AS net_movement
FROM acc_voucher_line vl
JOIN acc_voucher v ON vl.acc_voucher_id = v.acc_voucher_id
JOIN acc_ledger l ON vl.acc_ledger_id = l.acc_ledger_id
JOIN acc_ledger_group g ON l.acc_ledger_group_id = g.acc_ledger_group_id
WHERE v.co_id = :co_id
  AND v.status_id = 3
  AND v.active = 1
  AND v.voucher_date BETWEEN :from_date AND :to_date
GROUP BY g.acc_ledger_group_id
ORDER BY g.nature, g.sequence_no
```

**Previous year comparatives:** All report queries above should accept an optional `:prev_from_date` and `:prev_to_date` parameter pair. When provided, run the same query twice and return both current and previous period data side by side.

---

## 6. API Endpoints

### Phase 1 Endpoints (registered at `/api/accounting`)

**Setup & Masters:**
| Method | Path | Description |
|--------|------|-------------|
| POST | `/activate_company` | Seed ledger groups, system ledgers, voucher types, party ledgers for a company |
| GET | `/ledger_groups` | List ledger group tree for a company |
| POST | `/ledger_groups` | Create custom sub-group |
| GET | `/ledgers` | List/search ledgers (with group filter, type filter) |
| POST | `/ledgers` | Create ledger |
| PUT | `/ledgers/{id}` | Update ledger |
| GET | `/voucher_types` | List voucher types |
| GET | `/financial_years` | List financial years |
| POST | `/financial_years` | Create financial year |
| GET | `/account_determinations` | List account determination rules |
| PUT | `/account_determinations` | Update rules |

**Voucher Operations:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/vouchers` | List vouchers with filters (branch, type, date, party, source) |
| GET | `/vouchers/{id}` | Full voucher detail (lines, GST, bill refs) |

**Reports:**
| Method | Path | Description |
|--------|------|-------------|
| GET | `/reports/trial_balance` | Trial balance (params: co_id, from_date, to_date, branch_id) |
| GET | `/reports/profit_loss` | P&L statement |
| GET | `/reports/balance_sheet` | Balance sheet |
| GET | `/reports/ledger_report` | Ledger-wise transactions |
| GET | `/reports/day_book` | All vouchers for date range |
| GET | `/reports/cash_book` | Cash ledger transactions |
| GET | `/reports/party_outstanding` | Debtor/Creditor outstanding with bill details |
| GET | `/reports/ageing_analysis` | AR/AP ageing by configurable slabs |
| GET | `/reports/gst_summary` | GST input/output summary by period/GSTIN |

### Phase 2 Additional Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/vouchers` | Create manual voucher (Payment, Receipt, Journal, Contra) |
| PUT | `/vouchers/{id}` | Edit draft voucher |
| POST | `/vouchers/{id}/approve` | Approve manual voucher |
| POST | `/vouchers/{id}/reverse` | Create reversal voucher |
| POST | `/vouchers/{id}/settle_bills` | Link payment to outstanding bills |
| GET | `/reports/bank_book` | Bank-wise transactions |
| POST | `/bank_reconciliation` | Mark entries as reconciled |
| GET | `/reports/bank_recon_statement` | BRS report |
| GET | `/reports/gstr1_data` | GSTR-1 preparation data |
| GET | `/reports/gstr3b_data` | GSTR-3B summary |
| GET | `/reports/tds_register` | TDS deduction report |

### Phase 3 Additional Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/fixed_assets` | Register new asset |
| POST | `/depreciation_run` | Calculate and post depreciation |
| GET | `/reports/depreciation_schedule` | Projected depreciation |
| GET | `/reports/budget_vs_actual` | Budget variance |
| GET | `/reports/cost_center_report` | Expense by cost center |
| POST | `/year_end_close` | Close financial year, carry forward balances |

---

## 7. File Structure

```
src/
  accounting/
    __init__.py
    constants.py              # Voucher types, doc types, line types, status mappings
    models.py                 # SQLAlchemy ORM models for all acc_* tables
    query.py                  # Raw SQL queries (trial balance, ledger report, etc.)
    routers.py                # FastAPI router — all /api/accounting endpoints
    auto_post.py              # Auto-posting service functions
    voucher_service.py        # Voucher creation, validation, reversal, numbering
    ledger_service.py         # Ledger CRUD, party ledger auto-creation
    seed_data.py              # Default groups, system ledgers, voucher types
    gst_service.py            # GST computation, GSTR-1/3B data
    report_queries.py         # Report-specific SQL (separate from query.py for clarity)

src/models/
    accounting.py             # ORM models also importable from here (re-exports from accounting/models.py)

dbqueries/migrations/
    create_accounting_phase1.sql   # DDL for Phase 1 tables
    seed_accounting_defaults.sql   # Default groups, voucher types, system ledgers
```

**Changes to existing files:**

| File | Change |
|------|--------|
| `src/main.py` | Register accounting router at `/api/accounting` |
| `src/procurement/billpass.py` | Call `auto_post_procurement_billpass()` when `billpass_status = 1` |
| `src/juteProcurement/billPass.py` | Call `auto_post_jute_billpass()` when `bill_pass_complete = 1` |
| `src/sales/salesInvoice.py` | Call `auto_post_sales_invoice()` when `status_id = 3` |

---

## 8. Seed Data Strategy

### On Module Activation (`/activate_company`)

1. **Create financial year** for current period (April 1 to March 31)
2. **Create 12 period locks** (all unlocked initially)
3. **Insert 28 ledger groups** from the predefined list
4. **Insert system ledgers:**

   **Core (Phase 1):**
   - Cash (Cash-in-Hand, type=C)
   - CGST Input, SGST Input, IGST Input (Duties & Taxes under Current Assets)
   - CGST Output, SGST Output, IGST Output (Duties & Taxes under Current Liabilities)
   - TDS Payable (Duties & Taxes)
   - Purchase Account, Jute Purchase Account, Purchase Returns (Purchase Accounts)
   - Sales Account (Sales Accounts)
   - Freight Inward (Direct Expenses)
   - Round Off (Indirect Expenses)
   - Claims Receivable (Loans & Advances)
   - Opening Stock, Closing Stock (Stock-in-Hand)
   - Profit & Loss A/c (special — year-end transfer)

   **Payroll / HRMS (Phase 2):**
   - Salary & Wages (Direct Expenses or Indirect Expenses — configurable)
   - Salary Payable (Current Liabilities)
   - PF Payable (Current Liabilities)
   - ESI Payable (Current Liabilities)
   - Professional Tax Payable (Duties & Taxes)
   - TDS on Salary Payable (Duties & Taxes)
   - Employer PF Contribution (Direct Expenses)
   - Employer ESI Contribution (Direct Expenses)
   - Employee Advance Recovery (Loans & Advances)

   **Financial (Phase 2-3):**
   - Interest on Loans (Indirect Expenses)
   - Interest Received (Indirect Incomes)
   - Discount Allowed (Indirect Expenses)
   - Discount Received (Indirect Incomes)
   - Bad Debts (Indirect Expenses)
   - Bank Charges (Indirect Expenses)
   - RCM GST Payable (Duties & Taxes)

   **Audit & Year-End (Phase 4):**
   - Depreciation (Indirect Expenses)
   - Accumulated Depreciation (Fixed Assets — contra)
   - Audit Fees (Indirect Expenses)
   - Bonus Payable (Provisions)
   - Gratuity Payable (Provisions)
   - Leave Encashment Payable (Provisions)

5. **Insert 8 voucher types** (Payment, Receipt, Journal, Contra, Sales, Purchase, Debit Note, Credit Note)
6. **Auto-create party ledgers** for all active parties in `party_mst`:
   - `party_type_id` contains "Supplier" → Sundry Creditors group, `ledger_type = 'P'`
   - `party_type_id` contains "Customer" → Sundry Debtors group, `ledger_type = 'P'`
   - Both → Sundry Creditors (accountant can adjust)
   - Ledger name = `party_mst.supp_name`
7. **Insert default account determination rules** (including PAYROLL, PAYROLL_DISBURSEMENT, STATUTORY_REMITTANCE doc_types)
8. **Insert default ageing slabs:** 0-30, 31-60, 61-90, 91-180, 180+
9. **Create voucher numbering sequences** per type per branch per FY
10. **Insert default Schedule III mappings** (Phase 4 — `acc_schedule_iii_map` seed data)

### On New Party Creation (ongoing)

When a party is created in `party_mst` after the accounting module is active, automatically create a corresponding `acc_ledger` in the appropriate group.

---

## 9. Year-End Closing Process

1. **Lock all 12 periods** of the closing FY
2. **Create closing stock journal:** DR Closing Stock, CR Trading A/c (or P&L A/c)
3. **Compute net profit:** Sum of all Income group balances - Sum of all Expense group balances
4. **Transfer to Reserves:** Journal voucher DR Profit & Loss A/c, CR Reserves & Surplus (for profit) or vice versa (for loss)
5. **Create next FY** with `fy_start = closing_fy_end + 1 day`
6. **Carry forward opening balances:** For each BS-side ledger, compute closing balance and write as `opening_balance` for the new FY. P&L ledgers start at zero.
7. **Lock the closed FY** (`is_locked = 1`)

---

## 10. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Performance on large voucher volumes | Composite indexes on (co_id, voucher_date), (acc_ledger_id, dr_cr). BIGINT PKs for high-volume tables. |
| Double-posting on retry | Unique check on (source_doc_type, source_doc_id) before auto-posting |
| Unbalanced voucher | Application-level validation: SUM(DR) = SUM(CR). Reject if not balanced. |
| GST rate changes mid-year | Rates stored on acc_voucher_gst at time of posting, not looked up dynamically |
| Existing bill passes without accounting | Backfill script for historical data |
| DECIMAL vs DOUBLE | All accounting tables use DECIMAL(15,2). Never FLOAT or DOUBLE for monetary amounts. |
| Voucher immutability | Application enforces: no UPDATE on acc_voucher/acc_voucher_line WHERE status_id = 3 |

---

## 11. Warning System (Compliance Guardrails)

### Philosophy

The system allows entries that may not be strictly correct but provides **contextual warnings** with severity levels. Warnings are never blockers (except hard rules: DR != CR, missing mandatory fields). The goal is to give accountants flexibility while maintaining an audit trail of acknowledged deviations.

### Warning Conditions

| # | Code | Condition | Severity | Message Template |
|---|------|-----------|----------|------------------|
| 1 | `LOCKED_PERIOD` | Voucher date falls in a locked period | HIGH | "Period {month}/{year} is locked. Entry requires unlock approval." |
| 2 | `ABNORMAL_BALANCE` | Posting creates opposite-of-normal balance on a ledger | MEDIUM | "Unusual: {ledger_name} normally has {normal_balance} balance. This entry creates a {opposite} balance." |
| 3 | `TDS_MISSING` | Payment to a party where TDS is applicable but not deducted | HIGH | "TDS under Section {section} may be applicable for {party_name}. No TDS deducted on this payment." |
| 4 | `PAYMENT_EXCEEDS_OUTSTANDING` | Payment amount exceeds party's total outstanding | MEDIUM | "Payment Rs {amount} exceeds outstanding Rs {outstanding} for {party_name}. Excess Rs {diff} will be treated as advance." |
| 5 | `DUPLICATE_ENTRY` | Same party + similar amount + same date exists in another voucher | HIGH | "Possible duplicate: Similar entry exists — Voucher #{existing_no} dated {date} for Rs {amount}." |
| 6 | `WRONG_VOUCHER_TYPE` | Journal voucher has a Cash/Bank ledger line (should be Payment/Receipt/Contra) | MEDIUM | "Journal contains {ledger_type} ledger '{ledger_name}'. Consider using {suggested_type} voucher type." |
| 7 | `GST_STATE_MISMATCH` | Intra/inter state GST type doesn't match party's state vs branch state | HIGH | "Party state is {party_state}. Branch state is {branch_state}. GST type {gst_type} may be incorrect." |
| 8 | `RCM_NOT_APPLIED` | Purchase from unregistered vendor (no GSTIN) without RCM | HIGH | "Vendor {party_name} has no GSTIN. Reverse Charge Mechanism may apply under Section 9(4)." |
| 9 | `ADVANCE_UNADJUSTED` | Advance outstanding > 365 days for a party | MEDIUM | "Advance to {party_name} of Rs {amount} unadjusted for {days} days. Consider adjustment or write-off." |
| 10 | `CREDIT_LIMIT_EXCEEDED` | New invoice/debit pushes party outstanding beyond credit limit | HIGH | "Credit limit for {party_name}: Rs {limit}. Outstanding after this entry: Rs {outstanding}." |
| 11 | `PAN_MISSING_TDS` | TDS deducted but party PAN not available | HIGH | "PAN not available for {party_name}. TDS should be at higher rate (20%) under Section 206AA." |
| 12 | `BS_EXPENSE_POSTING` | Expense-like narration but posting to Balance Sheet group ledger | MEDIUM | "Posting to Balance Sheet group '{group_name}'. Verify this is not an expense that belongs in P&L." |
| 13 | `BUDGET_EXCEEDED` | Expense exceeds budget for the ledger/period | MEDIUM | "Budget for {ledger_name} in {period}: Rs {budget}. Actual including this entry: Rs {actual}." |
| 14 | `NARRATION_MISSING` | Journal voucher saved without narration | LOW | "Narration is recommended on Journal vouchers for audit trail." |
| 15 | `NEGATIVE_CASH_BANK` | Cash or Bank balance would go negative after this entry | HIGH | "{ledger_name} balance would be Rs {balance} (negative) after this entry." |

### Warning Table

`acc_voucher_warning` (defined in Section 4.1) stores acknowledged warnings.

### API Behavior

1. **Pre-save validation:** Before saving a voucher, run all applicable warning checks
2. **Return warnings array:** `{"warnings": [{"code": "TDS_MISSING", "severity": "HIGH", "message": "..."}]}`
3. **Require acknowledgment:** For HIGH severity warnings, the save request must include `acknowledged_warnings: ["TDS_MISSING", ...]`
4. **Store acknowledgment:** Write to `acc_voucher_warning` table with user_id and timestamp
5. **Audit query:** Auditors can query all acknowledged warnings by severity, code, or date range

---

## 12. Approval Flow for Accounting Vouchers

### Integration with Existing Approval Framework

Accounting vouchers use the same `approval_mst` + `process_approval()` framework as procurement. Key differences:

### Separate Menu per Voucher Type

Each voucher type gets its own `menu_id` in `approval_mst`:

| Voucher Type | Menu Name | Approval Considerations |
|-------------|-----------|------------------------|
| Payment | `acc_payment` | **Value-based escalation** — `max_amount_single`, `day_max_amount`, `month_max_amount` enforced |
| Receipt | `acc_receipt` | Lower risk — approval above threshold only |
| Journal | `acc_journal` | **Maker-checker mandatory** — always requires at least 2 users regardless of amount |
| Contra | `acc_contra` | Moderate risk — approval above threshold |
| Debit Note | `acc_debit_note` | Affects party balances — requires approval with mandatory reason/narration |
| Credit Note | `acc_credit_note` | Affects party balances — requires approval with mandatory reason/narration |
| Reversal | `acc_reversal` | **Higher-level approval** required than the original voucher's highest approval level |

### Voucher Status Lifecycle

Same as procurement:

```
21 (Draft) → 1 (Open) → 20 (Pending Approval, level 1) → 20 (level 2) → ... → 3 (Approved)
                                     ↓
                                 4 (Rejected) → 1 (Reopen)

21 (Draft) → 6 (Cancelled) → 21 (Reopen)
```

### Auto-Posted Vouchers

Auto-posted vouchers bypass the approval workflow entirely — they are created directly with `status_id = 3` since the source document (bill pass, sales invoice) has already gone through its own approval.

### Approval Log

Every status transition is recorded in `acc_voucher_approval_log` (defined in Section 4.1):
- `action`: OPEN, SEND_FOR_APPROVAL, APPROVE, REJECT, REOPEN, REVERSE
- `from_status_id`, `to_status_id`, `from_approval_level`, `to_approval_level`
- `action_by` (user_id), `action_date_time`, `remarks`

### Implementation Pattern

```python
# In src/accounting/routers.py — follow the same pattern as procurement/indent.py

@router.post("/approve_voucher")
async def approve_voucher(payload, db, token_data):
    result = process_approval(
        doc_id=voucher_id,
        user_id=user_id,
        menu_id=menu_id,  # Different per voucher type category
        db=db,
        get_doc_fn=get_voucher_with_approval_info,
        update_status_fn=update_voucher_status,
        id_param_name="acc_voucher_id",
        doc_name="Voucher",
        document_amount=total_amount,
        get_consumed_amounts_fn=get_voucher_consumed_amounts,  # For Payment type
    )
    # On successful final approval, set approved_by and approved_date_time
    return result
```

---

## 13. Opening Balance Migration

### Single-Value Opening (Balance Sheet Ledgers)

For non-party BS ledgers (Cash, Bank, Fixed Assets, etc.), set `opening_balance` and `opening_balance_type` directly on `acc_ledger`.

### Bill-wise Opening (Party Ledgers)

Party ledgers (Sundry Debtors / Sundry Creditors) need **individual invoice-level opening balances** for:
- Ageing analysis to work correctly from Day 1
- Bill-wise outstanding tracking
- Payment matching against specific invoices

Use `acc_opening_bill` table (defined in Section 4.1):

| Field | Purpose |
|-------|---------|
| `ref_name` | Original invoice number |
| `ref_date` | Original invoice date |
| `due_date` | Payment due date (critical for ageing) |
| `ref_amount` | Original invoice amount |
| `pending_amount` | Amount still outstanding at FY start |
| `dr_cr` | D for receivables (Debtors), C for payables (Creditors) |

### Bulk Import Endpoint

```
POST /api/accounting/opening_bills/import
Body: {
  "co_id": 1,
  "acc_financial_year_id": 1,
  "bills": [
    {"party_id": 101, "ref_name": "INV-2025-001", "ref_date": "2025-01-15", "due_date": "2025-02-14", "ref_amount": 50000, "pending_amount": 30000, "dr_cr": "C"},
    ...
  ]
}
```

### Validation Rules

1. `SUM(pending_amount WHERE dr_cr = 'D') - SUM(pending_amount WHERE dr_cr = 'C')` for a party ledger must equal the ledger's `opening_balance` — **warn if mismatch** (don't block)
2. `pending_amount <= ref_amount` — warn if pending exceeds original
3. `due_date` should not be in the future relative to FY start — warn if it is
4. Party must have a corresponding `acc_ledger` with `ledger_type = 'P'`

### On Year-End Closing

When closing a financial year:
1. All `acc_bill_ref` entries with `status IN ('OPEN', 'PARTIAL')` become the opening bills for the next FY
2. System auto-generates `acc_opening_bill` records for the new FY from these carry-forward bills
3. No manual re-import needed for subsequent years

---

## 14. Compliance Notes

### Design Philosophy

This accounting module follows the principle of **flexibility with accountability**:

- **Allow all entries:** The system never prevents an accountant from making an entry, even if it appears incorrect. Business scenarios can be complex and edge cases exist that software cannot fully anticipate.
- **Warn on deviations:** When an entry looks unusual, non-compliant, or risky, the system raises a warning (see Section 11). The accountant must acknowledge the warning to proceed.
- **Audit trail:** Every warning acknowledgment, approval, and status change is logged permanently. This ensures that auditors can review decisions and the reasoning behind them.
- **Corrections via reversal:** Approved vouchers cannot be edited — only reversed and re-entered. This maintains a clean, tamper-proof ledger.

### Compliance Areas Covered

| Area | Approach |
|------|----------|
| **GST** | Auto-compute from source documents. GSTR-1 and GSTR-3B data preparation. RCM flagging. ITC eligibility tracking. GSTR-2A/2B reconciliation for ITC validation |
| **TDS** | TDS detail per voucher. Challan tracking. Lower deduction certificate support. Warning when TDS not deducted. 26Q/27Q data preparation |
| **Companies Act** | Schedule III formatted reports. Related party disclosures. Comparative previous year columns |
| **Audit** | Immutable approved vouchers. Approval logs. Warning acknowledgments. Year-end closing process. Audit adjustment voucher type (Phase 4) |
| **Indian Accounting Standards** | Double-entry with computed balances (no stored balances). Party bill-wise tracking per Ind AS 109. Prepaid amortization |

### What This Module Does NOT Cover (Phase 1-4)

- E-invoicing / e-way bill integration
- Multi-company consolidation
- Foreign currency (schema-ready with nullable columns, but no FX logic)
- GST composition scheme
- Tax audit (Form 3CD) data preparation
- Direct tax computation (income tax return)
- Statutory audit report generation

These can be added as future phases without schema changes.

---

## 15. Table Summary by Phase

### Phase 1 — Foundation + Auto-Posting + Reports: 15 tables

**Goal:** Module activation, auto-posting from procurement/sales/jute, read-only reports, manual voucher CRUD with approval flow, warning system.

| # | Table | Purpose |
|---|-------|---------|
| 1 | acc_ledger_group | Hierarchical group structure (28 predefined) |
| 2 | acc_ledger | Individual accounts / GL accounts |
| 3 | acc_voucher_type | Voucher type configuration |
| 4 | acc_financial_year | Financial year management |
| 5 | acc_period_lock | Monthly period locking |
| 6 | acc_account_determination | Auto-posting GL rules |
| 7 | acc_voucher | Voucher headers |
| 8 | acc_voucher_line | Debit/Credit entries |
| 9 | acc_voucher_gst | GST detail per voucher |
| 10 | acc_bill_ref | Bill-wise AR/AP tracking |
| 11 | acc_bill_settlement | Payment ↔ Bill linkage |
| 12 | acc_voucher_numbering | Auto-numbering sequences |
| 13 | acc_voucher_approval_log | Approval audit trail |
| 14 | acc_voucher_warning | Warning acknowledgment trail |
| 15 | acc_opening_bill | Bill-wise opening balance import |

### Phase 2 — Manual Vouchers + HRMS + Advance Payments: +5 tables

**Goal:** Full manual voucher lifecycle (Payment, Receipt, Journal, Contra). Bill settlement. Advance payment/receipt flow. HRMS/payroll auto-posting. Warning system active.

| # | Table | Purpose |
|---|-------|---------|
| 16 | acc_bank_account | Bank account details (with OD limit, interest rate) |
| 17 | acc_bank_reconciliation | BRS entries |
| 18 | acc_tds_detail | TDS per voucher |
| 19 | acc_payment_detail | Cheque/instrument tracking |
| 20 | acc_ageing_slab | Configurable ageing buckets |

### Phase 3 — Bank, TDS & GST Compliance: +7 tables

**Goal:** Bank reconciliation, cheque management, TDS compliance (challan, returns), GST compliance (RCM, ITC, GSTR-2A matching), loan tracking.

| # | Table | Purpose |
|---|-------|---------|
| 21 | acc_cheque_register | Cheque book and per-cheque tracking |
| 22 | acc_pdc_register | Post-dated cheque management |
| 23 | acc_tds_challan | TDS deposit challan tracking |
| 24 | acc_lower_deduction_cert | Section 197 lower deduction certificates |
| 25 | acc_gst_reconciliation | GSTR-2A/2B matching |
| 26 | acc_loan_account | Loan / OD / CC tracking |
| 27 | acc_loan_schedule | EMI / repayment schedule |

### Phase 4 — Advanced Features & Audit Readiness: +8 tables

**Goal:** Fixed assets, depreciation, cost centers, budgets, Schedule III reports, cash flow statement, year-end closing, prepaid amortization.

| # | Table | Purpose |
|---|-------|---------|
| 28 | acc_cost_center | Cost center hierarchy |
| 29 | acc_fixed_asset | Fixed asset register |
| 30 | acc_depreciation_run | Depreciation calculation runs |
| 31 | acc_depreciation_detail | Per-asset depreciation |
| 32 | acc_budget | Budget definitions |
| 33 | acc_budget_line | Budget per ledger per period |
| 34 | acc_schedule_iii_map | Balance Sheet / P&L → Schedule III mapping |
| 35 | acc_prepaid_schedule | Prepaid expense amortization |

**Total: 35 tables across 4 phases.**
