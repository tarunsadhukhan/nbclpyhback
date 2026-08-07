# Design: Sales Invoice — Transporter GST, Transporter Doc No., Buyer Order, e-Invoice Fields

**Date:** 2026-04-01  
**Status:** Approved  
**Scope:** Backend (vowerp3be) + Frontend (vowerp3ui)

---

## Context

The sales invoice currently stores minimal transporter data (name, address, state) and has no fields for e-invoice portal details. Comparing against a standard GST tax invoice (e-invoice format), the following are missing:

- Transporter branch linkage (needed to derive transporter GSTIN from `party_branch_mst`)
- Transporter document number + date (LR No. / Bill of Lading / RR No. + corresponding date)
- Buyer's order reference (customer's PO number, distinct from internal sales order)
- e-Invoice fields: IRN, Ack No., Ack Date, QR Code (manual entry now; portal auto-fill in future)
- e-Invoice submission audit trail (separate table to log submission attempts for compliance)

**Not in scope:**
- Delivery Note No./Date → reuse existing `sales_delivery_order_id` (DO)
- Dispatch Doc No. → covered by existing `challan_no`
- Reference No. & Date → covered by existing `consignment_no` / `buyer_order_no`
- e-Invoice portal API integration code (future work; structure provisioned now)

---

## Database Changes

### 1. New columns on `sales_invoice` table (9 columns added)

| Column | Type | Purpose |
|---|---|---|
| `transporter_branch_id` | BIGINT, FK → `party_branch_mst.party_mst_branch_id` | Links transporter to branch for GST lookup |
| `transporter_doc_no` | VARCHAR(255) | LR No. / Bill of Lading / RR No. |
| `transporter_doc_date` | DATE | Date of transporter document (LR/BoL date) |
| `buyer_order_no` | VARCHAR(255) | Customer's purchase order / order reference |
| `buyer_order_date` | DATE | Date of buyer's order |
| `irn` | VARCHAR(255) | e-Invoice IRN (manual entry; portal auto-fill later) |
| `ack_no` | VARCHAR(100) | e-Invoice Acknowledgement Number from GST portal |
| `ack_date` | DATE | e-Invoice Acknowledgement Date from GST portal |
| `qr_code` | LONGTEXT | QR Code data (base64 from portal) |

### 2. New table: `e_invoice_responses` (audit trail for portal submissions)

| Column | Type | Purpose |
|---|---|---|
| `e_invoice_response_id` | BIGINT PK autoincrement | |
| `invoice_id` | BIGINT, FK → `sales_invoice.invoice_id` | |
| `co_id` | BIGINT, FK → `co_mst.co_id` | Tenant scope |
| `submission_status` | VARCHAR(50) | Draft / Submitted / Accepted / Rejected / Error |
| `submitted_date_time` | DATETIME | When the submission was attempted |
| `api_response_json` | LONGTEXT | Full JSON response from e-invoice API (for audit) |
| `irn_from_response` | VARCHAR(255) | IRN extracted from response (if accepted) |
| `error_message` | VARCHAR(500) | Error message if submission failed |
| `submitted_by` | BIGINT, FK → `user_mst.user_id` | User who triggered submission |
| `created_date_time` | DATETIME | Record creation timestamp |

**Indexes:** Create composite index on `(invoice_id, submitted_date_time DESC)` for quick audit trail lookup.

**Migration files:**
- `dbqueries/migrations/add_transporter_einvoice_fields_to_sales_invoice.sql` (ALTER TABLE)
- `dbqueries/migrations/create_e_invoice_responses_table.sql` (CREATE TABLE)

---

## Backend Changes (`vowerp3be`)

### `src/models/sales.py`
- Add 9 new `mapped_column` fields to `InvoiceHdr`: `transporter_branch_id`, `transporter_doc_no`, `transporter_doc_date`, `buyer_order_no`, `buyer_order_date`, `irn`, `ack_no`, `ack_date`, `qr_code`
- **New ORM model:** `EInvoiceResponse` with fields: `e_invoice_response_id`, `invoice_id`, `co_id`, `submission_status`, `submitted_date_time`, `api_response_json`, `irn_from_response`, `error_message`, `submitted_by`, `created_date_time`

### `src/sales/query.py`
- `insert_sales_invoice()` — add 9 new fields to INSERT statement
- `update_sales_invoice()` — add 9 new fields to UPDATE statement
- `get_invoice_by_id_query()` — return 9 new fields + JOIN `party_branch_mst` on `transporter_branch_id` for `transporter_gst_no`
- Add new `get_transporter_branches(transporter_id)` query — returns `party_mst_branch_id`, `gst_no`, `address`, `state_id` from `party_branch_mst`
- Add new `get_e_invoice_submission_history(invoice_id)` query — returns list of submission attempts from `e_invoice_responses` ordered by date DESC

### `src/sales/salesInvoice.py`
- `create_sales_invoice()` — accept and persist 9 new fields
- `update_sales_invoice()` — accept and persist 9 new fields
- `get_sales_invoice_by_id()` — return 9 new fields + `transporter_gst_no` (derived from joined branch) + `e_invoice_submission_history` array
- **New endpoint:** `GET /salesInvoice/get_transporter_branches?transporter_id=&co_id=` — returns list of branches for a transporter
- **Future endpoint (structure only):** `POST /salesInvoice/submit_for_einvoice?invoice_id=&co_id=` — will call e-invoice portal, log response in `e_invoice_responses`, update invoice on success

### `src/sales/e_invoice_handler.py` (new file — structure only)

```python
"""
Placeholder module for future e-invoice portal integration.
When implemented, will contain:
- GST e-invoice portal API client
- Response parser (IRN, Ack No., Ack Date, QR Code extraction)
- Error handling (map API errors to submission_status)
- Log submissions in e_invoice_responses table
- Update sales_invoice with portal response data
"""
```

### `src/test/test_sales_invoice_transporter_fields.py` (new)
- Test `get_transporter_branches` endpoint (success, missing param, empty result)
- Test `create_sales_invoice` with all 9 new fields persisted correctly
- Test `update_sales_invoice` with transporter branch change
- Test `get_sales_invoice_by_id` returns `transporter_gst_no` and `e_invoice_submission_history`
- Test `transporter_doc_date` persists correctly

---

## Frontend Changes (`vowerp3ui`)

### `types/salesInvoiceTypes.ts`
- Add to `InvoiceFormValues` and `InvoiceDetails`: `transporter_branch_id`, `transporter_doc_no`, `transporter_doc_date`, `buyer_order_no`, `buyer_order_date`, `irn`, `ack_no`, `ack_date`, `qr_code`, `transporter_gst_no` (display only), `e_invoice_submission_history` (array)
- Add type `TransporterBranchRecord { id: number; gst_no: string; address: string; state_id: number }`
- Add type `EInvoiceSubmission { response_id: number; submission_status: string; submitted_date_time: string; irn_from_response: string; error_message: string }`

### `hooks/useSalesInvoiceFormSchemas.ts`
- Add new fields to header schema with correct types and optional validation

### `hooks/useSalesInvoiceSelectOptions.ts`
- Add `transporterBranchOptions: TransporterBranchRecord[]` state
- Add `fetchTransporterBranches(transporterId: number)` — calls new API endpoint
  - If 1 branch returned: auto-select it, auto-fill `transporter_gst_no`
  - If multiple branches: populate dropdown for user to choose
  - If 0 branches: clear branch + GST fields

### `hooks/useSalesInvoiceFormState.ts`
- On transporter field change → call `fetchTransporterBranches`
- On transporter branch change → set `transporter_gst_no` from selected branch record (read-only display)
- On DO/SO auto-fill → also trigger branch fetch if transporter is auto-filled

### `components/SalesInvoiceHeaderForm.tsx`
New fields added in 4 logical groups:

**Logistics section (near existing transporter field):**
1. Transporter Branch — searchable select (visible only when transporter is selected and has branches)
2. Transporter GSTIN — read-only text display (auto-filled from branch)
3. Transporter Doc No. — text input (LR No. / Bill of Lading No.)
4. Transporter Doc Date — date input (date of LR/BoL)

**Order References section (near existing sales order field):**
5. Buyer's Order No. — text input
6. Buyer's Order Date — date input

**e-Invoice section (new collapsible section at bottom of header):**
7. IRN — text input
8. Ack No. — text input
9. Ack Date — date input
10. QR Code — textarea (for base64 or URL string)
11. e-Invoice Submission History — read-only collapsible table (if invoice has submission attempts) showing status, date, IRN, error messages

### `utils/salesInvoiceMappers.ts`
- Map all 8 new fields in both directions (form values ↔ API payload / API response ↔ form values)
- Map `transporter_gst_no` from `get_sales_invoice_by_id` response to display state

### `utils/salesInvoiceService.ts`
- Add `getTransporterBranches(transporterId: number, coId: number)` API call

---

## Data Flow: Transporter GST

```
User selects transporter
  → fetchTransporterBranches(transporter_id, co_id)
    → GET /salesInvoice/get_transporter_branches
      → Returns party_branch_mst rows for that party
  → If 1 branch: auto-select, set transporter_gst_no (read-only display)
  → If >1 branch: show Transporter Branch dropdown
    → User selects branch → set transporter_gst_no (read-only display)
  → transporter_branch_id saved to sales_invoice on submit
  → On load (edit/view): transporter_gst_no shown from joined query result
```

## Data Flow: e-Invoice Fields & Submission (Now + Future)

### Current Phase (This Sprint)
```
User enters invoice data
  ↓
User manually enters: IRN, Ack No., Ack Date, QR Code
(or leaves empty for now)
  ↓
Invoice saved to sales_invoice table with e-invoice fields
  ↓
On view/edit: e-invoice fields displayed as read-only or editable (depends on approval status)
  ↓
Invoice preview renders QR code if present
```

### Future Phase (e-Invoice Portal Integration)
```
User clicks "Submit for e-Invoice" button
  ↓
POST /salesInvoice/submit_for_einvoice
  ↓
Backend:
  1. Validate invoice is in correct status
  2. Call GST e-invoice portal API with invoice data
  3. Portal returns: IRN, Ack No., Ack Date, QR Code + raw JSON response
  4. Log submission in e_invoice_responses table
     - Set status = "Accepted" (or "Error"/"Rejected")
     - Store full api_response_json
     - Extract and store irn_from_response, error_message
  5. Update sales_invoice with portal response
     - Update irn, ack_no, ack_date, qr_code
  6. Return success/error to frontend
  ↓
Frontend displays:
  - Updated e-invoice fields (read-only after submission)
  - Submission history collapsible section showing all attempts
  - Retry button if submission failed
```

### Submission History Visibility
- When invoice has `e_invoice_submission_history` with entries, show collapsible table in e-Invoice section
- Table columns: Submission Status | Submitted Date | IRN (if Accepted) | Error Message | Attempted By
- Allows users to see full audit trail of portal submission attempts and any errors

---

## Verification

### Database Migrations
1. Run migration: `add_transporter_einvoice_fields_to_sales_invoice.sql`
   - Verify all 9 columns added to `sales_invoice` table
2. Run migration: `create_e_invoice_responses_table.sql`
   - Verify `e_invoice_responses` table created with all 10 columns
   - Verify composite index created on (invoice_id, submitted_date_time DESC)
3. Run full test suite: `pytest src/test/ -v`

### Backend Tests
- Run: `pytest src/test/test_sales_invoice_transporter_fields.py -v`
- Verify:
  - `get_transporter_branches` endpoint returns correct data
  - `create_sales_invoice` with all 9 new fields persists correctly
  - `update_sales_invoice` with transporter branch change works
  - `get_sales_invoice_by_id` returns `transporter_gst_no` and `e_invoice_submission_history`
  - `transporter_doc_date` field persists as DATE correctly

### Frontend Tests
4. Start dev server: `uvicorn src.main:app --reload`
5. Create new invoice:
   - Select transporter with 1 branch → verify branch auto-selected and GSTIN auto-fills
   - Select transporter with >1 branch → verify dropdown shown, selecting branch fills GSTIN
   - Enter transporter_doc_no and transporter_doc_date → verify persisted on save
   - Enter buyer_order_no and buyer_order_date → verify persisted on save
6. Save and reload invoice:
   - Verify all 9 new fields display correctly
   - Verify transporter GSTIN shown (derived from branch)
   - Verify e-Invoice fields shown as empty initially
7. Manually enter IRN, Ack No., Ack Date, QR Code:
   - Save → verify persisted
   - Reload → verify values retained
8. Verify e-Invoice section collapsible behavior (empty submission history initially)

### Data Integrity
9. Verify transporter branch FK constraint works (delete branch → invoice should fail or cascade as configured)
10. Verify co_id scoping on `e_invoice_responses` table (multi-tenant isolation)
