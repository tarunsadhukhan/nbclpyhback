# Sales Invoice Enhancement Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development to execute tasks. Each task is a discrete, reviewable unit. Two-stage review between tasks catches errors early.

**Goal:** Add transporter GST, buyer order reference, transporter doc number/date, and e-invoice portal fields (IRN, Ack No., Ack Date, QR Code) to sales invoices with complete audit trail for future e-invoice portal integration.

**Architecture:** 
- **Backend:** Two migrations (add 9 columns to `sales_invoice`, create `e_invoice_responses` audit table), ORM models updated, 3 new queries + 2 updated queries, 2 new endpoints, comprehensive test suite.
- **Frontend:** Type definitions extended, form schema updated with 9 new fields in 4 logical groups, auto-fill logic for transporter GST based on branch selection, mappers/service updated for bidirectional flow.
- **Future-ready:** `e_invoice_responses` table and placeholder handler module structure provisioned for GST portal API integration (no API code in this sprint).

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Pydantic, pytest (backend); React, TypeScript, Zod (frontend).

---

## Phase 1: Database Schema (Backend Migrations)

### Task 1: Create migration for sales_invoice columns

**Files:**
- Create: `dbqueries/migrations/add_transporter_einvoice_fields_to_sales_invoice.sql`

- [ ] **Step 1: Write the migration SQL**

Create file `dbqueries/migrations/add_transporter_einvoice_fields_to_sales_invoice.sql`:

```sql
-- Migration: Add transporter GST, doc number/date, buyer order, and e-invoice fields to sales_invoice
-- Date: 2026-04-01
-- Rollback: Remove all added columns (see rollback section at end)

-- Add 9 new columns to sales_invoice table
ALTER TABLE sales_invoice 
ADD COLUMN transporter_branch_id BIGINT NULL AFTER transporter_state_name,
ADD COLUMN transporter_doc_no VARCHAR(255) NULL AFTER transporter_branch_id,
ADD COLUMN transporter_doc_date DATE NULL AFTER transporter_doc_no,
ADD COLUMN buyer_order_no VARCHAR(255) NULL AFTER transporter_doc_date,
ADD COLUMN buyer_order_date DATE NULL AFTER buyer_order_no,
ADD COLUMN irn VARCHAR(255) NULL AFTER buyer_order_date,
ADD COLUMN ack_no VARCHAR(100) NULL AFTER irn,
ADD COLUMN ack_date DATE NULL AFTER ack_no,
ADD COLUMN qr_code LONGTEXT NULL AFTER ack_date;

-- Add foreign key constraint on transporter_branch_id
ALTER TABLE sales_invoice 
ADD CONSTRAINT fk_sales_invoice_transporter_branch 
FOREIGN KEY (transporter_branch_id) REFERENCES party_branch_mst(party_mst_branch_id);

-- ROLLBACK:
-- ALTER TABLE sales_invoice DROP FOREIGN KEY fk_sales_invoice_transporter_branch;
-- ALTER TABLE sales_invoice DROP COLUMN transporter_branch_id, DROP COLUMN transporter_doc_no, DROP COLUMN transporter_doc_date, DROP COLUMN buyer_order_no, DROP COLUMN buyer_order_date, DROP COLUMN irn, DROP COLUMN ack_no, DROP COLUMN ack_date, DROP COLUMN qr_code;
```

- [ ] **Step 2: Execute migration against dev database**

Run from project root with active venv:

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && python -c "
import pymysql
import os

# Read credentials from env/database.env
with open('env/database.env', 'r') as f:
    env_vars = {}
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

# Connect to dev database (ask user which tenant DB or use default dev3)
conn = pymysql.connect(
    host=env_vars['DATABASE_HOST'],
    port=int(env_vars['DATABASE_PORT']),
    user=env_vars['DATABASE_USER'],
    password=env_vars['DATABASE_PASSWORD'],
    database='dev3'  # Replace with actual dev database name
)

cursor = conn.cursor()

with open('dbqueries/migrations/add_transporter_einvoice_fields_to_sales_invoice.sql', 'r') as f:
    sql_content = f.read()
    for stmt in sql_content.split(';'):
        stmt = stmt.strip()
        if stmt and not stmt.startswith('--'):
            try:
                cursor.execute(stmt)
                print(f'✓ Executed: {stmt[:80]}...')
            except Exception as e:
                print(f'✗ Error: {e}')
                raise

conn.commit()
conn.close()
print('Migration applied successfully')
"
```

Expected: ✓ All statements execute, columns visible in database

- [ ] **Step 3: Verify columns added**

```bash
mysql -h localhost -u root -p dev3 -e "DESCRIBE sales_invoice;" | grep -E "transporter_branch_id|transporter_doc_no|transporter_doc_date|buyer_order_no|buyer_order_date|irn|ack_no|ack_date|qr_code"
```

Expected: 9 rows showing new columns with correct types

- [ ] **Step 4: Commit migration**

```bash
git add dbqueries/migrations/add_transporter_einvoice_fields_to_sales_invoice.sql
git commit -m "feat: add transporter GST, doc, buyer order, and e-invoice fields to sales_invoice"
```

---

### Task 2: Create migration for e_invoice_responses audit table

**Files:**
- Create: `dbqueries/migrations/create_e_invoice_responses_table.sql`

- [ ] **Step 1: Write the migration SQL**

Create file `dbqueries/migrations/create_e_invoice_responses_table.sql`:

```sql
-- Migration: Create e_invoice_responses audit table for GST portal submission tracking
-- Date: 2026-04-01
-- Rollback: DROP TABLE e_invoice_responses;

CREATE TABLE e_invoice_responses (
    e_invoice_response_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    invoice_id BIGINT NOT NULL,
    co_id BIGINT NOT NULL,
    submission_status VARCHAR(50) NOT NULL COMMENT 'Draft/Submitted/Accepted/Rejected/Error',
    submitted_date_time DATETIME NOT NULL,
    api_response_json LONGTEXT NULL COMMENT 'Full JSON response from e-invoice API',
    irn_from_response VARCHAR(255) NULL COMMENT 'IRN extracted if accepted',
    error_message VARCHAR(500) NULL COMMENT 'Error if submission failed',
    submitted_by BIGINT NULL,
    created_date_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    CONSTRAINT fk_e_invoice_responses_invoice FOREIGN KEY (invoice_id) REFERENCES sales_invoice(invoice_id),
    CONSTRAINT fk_e_invoice_responses_company FOREIGN KEY (co_id) REFERENCES co_mst(co_id),
    CONSTRAINT fk_e_invoice_responses_user FOREIGN KEY (submitted_by) REFERENCES user_mst(user_id),
    
    INDEX idx_invoice_date (invoice_id, submitted_date_time DESC),
    INDEX idx_co_id (co_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ROLLBACK:
-- DROP TABLE e_invoice_responses;
```

- [ ] **Step 2: Execute migration against dev database**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && python -c "
import pymysql

with open('env/database.env', 'r') as f:
    env_vars = {}
    for line in f:
        if '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

conn = pymysql.connect(
    host=env_vars['DATABASE_HOST'],
    port=int(env_vars['DATABASE_PORT']),
    user=env_vars['DATABASE_USER'],
    password=env_vars['DATABASE_PASSWORD'],
    database='dev3'
)

cursor = conn.cursor()

with open('dbqueries/migrations/create_e_invoice_responses_table.sql', 'r') as f:
    sql_content = f.read()
    for stmt in sql_content.split(';'):
        stmt = stmt.strip()
        if stmt and not stmt.startswith('--'):
            try:
                cursor.execute(stmt)
                print(f'✓ Executed: {stmt[:80]}...')
            except Exception as e:
                print(f'✗ Error: {e}')
                raise

conn.commit()
conn.close()
print('Migration applied successfully')
"
```

Expected: ✓ Table created with 10 columns and 4 constraints

- [ ] **Step 3: Verify table created**

```bash
mysql -h localhost -u root -p dev3 -e "DESCRIBE e_invoice_responses;"
```

Expected: 10 rows showing columns, constraints visible

- [ ] **Step 4: Commit migration**

```bash
git add dbqueries/migrations/create_e_invoice_responses_table.sql
git commit -m "feat: create e_invoice_responses audit table for submission tracking"
```

---

## Phase 2: Backend ORM & Models

### Task 3: Update InvoiceHdr ORM model

**Files:**
- Modify: `src/models/sales.py` (InvoiceHdr class, around lines 36-121)

- [ ] **Step 1: Add new mapped columns to InvoiceHdr**

Open `src/models/sales.py`, find the `InvoiceHdr` class definition (starts at line 36). After the existing `transporter_state_name` column (around line 54), add these 9 new columns:

```python
# In InvoiceHdr class, after transporter_state_name column:

transporter_branch_id: Mapped[int | None] = mapped_column(
    BigInteger, 
    ForeignKey("party_branch_mst.party_mst_branch_id"),
    nullable=True
)
transporter_doc_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
transporter_doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
buyer_order_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
buyer_order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
irn: Mapped[str | None] = mapped_column(String(255), nullable=True)
ack_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
ack_date: Mapped[date | None] = mapped_column(Date, nullable=True)
qr_code: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Make sure to add `from datetime import date` at the top if not already present.

- [ ] **Step 2: Create new EInvoiceResponse ORM model**

At the end of `src/models/sales.py` (after InvoiceHdr and other models), add the new model:

```python
class EInvoiceResponse(Base):
    """Audit trail for e-invoice portal submissions"""
    __tablename__ = "e_invoice_responses"
    
    e_invoice_response_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sales_invoice.invoice_id"), nullable=False)
    co_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("co_mst.co_id"), nullable=False)
    submission_status: Mapped[str] = mapped_column(String(50), nullable=False)
    submitted_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    api_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    irn_from_response: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    submitted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("user_mst.user_id"), nullable=True)
    created_date_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    
    # Relationships (optional, for convenience)
    invoice: Mapped["InvoiceHdr"] = relationship(back_populates="e_invoice_responses")
```

Add `from datetime import datetime` at the top if not already present.

- [ ] **Step 3: Add relationship to InvoiceHdr**

In the `InvoiceHdr` class, add this relationship near the end of the class definition:

```python
e_invoice_responses: Mapped[list["EInvoiceResponse"]] = relationship(
    "EInvoiceResponse",
    back_populates="invoice",
    cascade="all, delete-orphan"
)
```

- [ ] **Step 4: Test ORM models load without errors**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && python -c "from src.models.sales import InvoiceHdr, EInvoiceResponse; print('✓ Models loaded successfully')"
```

Expected: ✓ Models loaded successfully

- [ ] **Step 5: Commit**

```bash
git add src/models/sales.py
git commit -m "feat: add InvoiceHdr columns and EInvoiceResponse model"
```

---

## Phase 3: Backend Queries

### Task 4: Add transporter branches query

**Files:**
- Modify: `src/sales/query.py` (add new query function)

- [ ] **Step 1: Add get_transporter_branches query**

Open `src/sales/query.py`, add this new function at the end of the file:

```python
def get_transporter_branches(transporter_id: int):
    """
    Fetch all branches for a transporter party.
    Returns: party_mst_branch_id, gst_no, address, state_id
    """
    sql = """
    SELECT 
        pbm.party_mst_branch_id AS id,
        pbm.gst_no,
        pbm.address,
        pbm.state_id,
        pm.supp_name AS party_name
    FROM party_branch_mst pbm
    INNER JOIN party_mst pm ON pm.party_id = pbm.party_id
    WHERE pbm.party_id = :transporter_id
    AND pbm.active = 1
    ORDER BY pbm.party_mst_branch_id ASC
    """
    return text(sql)
```

- [ ] **Step 2: Verify query syntax**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && python -c "from src.sales.query import get_transporter_branches; print('✓ Query function loads')"
```

Expected: ✓ Query function loads

- [ ] **Step 3: Add get_e_invoice_submission_history query**

In `src/sales/query.py`, add this function:

```python
def get_e_invoice_submission_history(invoice_id: int):
    """
    Fetch all e-invoice submission attempts for an invoice.
    Returns most recent first.
    """
    sql = """
    SELECT 
        e_invoice_response_id AS response_id,
        submission_status,
        submitted_date_time,
        irn_from_response,
        error_message,
        submitted_by
    FROM e_invoice_responses
    WHERE invoice_id = :invoice_id
    ORDER BY submitted_date_time DESC
    """
    return text(sql)
```

- [ ] **Step 4: Update insert_sales_invoice to include new fields**

Find the `insert_sales_invoice()` function in `src/sales/query.py`. Locate the INSERT statement and add the 9 new columns to both the column list and the VALUES section:

Original (approximately lines 87-150):
```python
def insert_sales_invoice(
    # ... existing parameters ...
):
    sql = """
    INSERT INTO sales_invoice (
        invoice_date, branch_id, party_id, ...
        transporter_state_name
        -- ADD THESE 9:
    ) VALUES (
        :invoice_date, :branch_id, :party_id, ...
        :transporter_state_name
        -- ADD THESE 9:
    )
    """
```

Updated:
```python
def insert_sales_invoice(
    # ... existing parameters ...
    transporter_branch_id: int = None,
    transporter_doc_no: str = None,
    transporter_doc_date: str = None,
    buyer_order_no: str = None,
    buyer_order_date: str = None,
    irn: str = None,
    ack_no: str = None,
    ack_date: str = None,
    qr_code: str = None,
):
    sql = """
    INSERT INTO sales_invoice (
        invoice_date, branch_id, party_id, ...,
        transporter_state_name,
        transporter_branch_id,
        transporter_doc_no,
        transporter_doc_date,
        buyer_order_no,
        buyer_order_date,
        irn,
        ack_no,
        ack_date,
        qr_code
    ) VALUES (
        :invoice_date, :branch_id, :party_id, ...,
        :transporter_state_name,
        :transporter_branch_id,
        :transporter_doc_no,
        :transporter_doc_date,
        :buyer_order_no,
        :buyer_order_date,
        :irn,
        :ack_no,
        :ack_date,
        :qr_code
    )
    """
    # Existing params dictionary updated to include new params
    params = {
        # ... existing ...
        "transporter_branch_id": transporter_branch_id,
        "transporter_doc_no": transporter_doc_no,
        "transporter_doc_date": transporter_doc_date,
        "buyer_order_no": buyer_order_no,
        "buyer_order_date": buyer_order_date,
        "irn": irn,
        "ack_no": ack_no,
        "ack_date": ack_date,
        "qr_code": qr_code,
    }
    return text(sql), params
```

- [ ] **Step 5: Update update_sales_invoice similarly**

Find `update_sales_invoice()` function and update similarly:

```python
def update_sales_invoice(
    # ... existing parameters ...
    transporter_branch_id: int = None,
    transporter_doc_no: str = None,
    transporter_doc_date: str = None,
    buyer_order_no: str = None,
    buyer_order_date: str = None,
    irn: str = None,
    ack_no: str = None,
    ack_date: str = None,
    qr_code: str = None,
):
    sql = """
    UPDATE sales_invoice SET
        -- ... existing updates ...
        transporter_state_name = :transporter_state_name,
        transporter_branch_id = :transporter_branch_id,
        transporter_doc_no = :transporter_doc_no,
        transporter_doc_date = :transporter_doc_date,
        buyer_order_no = :buyer_order_no,
        buyer_order_date = :buyer_order_date,
        irn = :irn,
        ack_no = :ack_no,
        ack_date = :ack_date,
        qr_code = :qr_code,
        updated_by = :updated_by,
        updated_date_time = NOW()
    WHERE invoice_id = :invoice_id
    """
    params = {
        # ... existing ...
        "transporter_branch_id": transporter_branch_id,
        "transporter_doc_no": transporter_doc_no,
        "transporter_doc_date": transporter_doc_date,
        "buyer_order_no": buyer_order_no,
        "buyer_order_date": buyer_order_date,
        "irn": irn,
        "ack_no": ack_no,
        "ack_date": ack_date,
        "qr_code": qr_code,
        "invoice_id": invoice_id,
        "updated_by": updated_by,
    }
    return text(sql), params
```

- [ ] **Step 6: Update get_invoice_by_id_query to return new fields and transporter GST**

Find `get_invoice_by_id_query()` and update the SELECT clause to include the 9 new fields and join to get transporter GST:

```python
def get_invoice_by_id_query(invoice_id: int, co_id: int):
    sql = """
    SELECT 
        hi.*,
        pbm_transporter.gst_no AS transporter_gst_no,
        -- ... existing fields ...
    FROM sales_invoice hi
    LEFT JOIN party_branch_mst pbm_transporter ON hi.transporter_branch_id = pbm_transporter.party_mst_branch_id
    WHERE hi.invoice_id = :invoice_id
    AND hi.co_id = :co_id
    """
    return text(sql)
```

Make sure `transporter_branch_id`, `transporter_doc_no`, `transporter_doc_date`, `buyer_order_no`, `buyer_order_date`, `irn`, `ack_no`, `ack_date`, `qr_code` are included in the `SELECT hi.*` or explicitly listed.

- [ ] **Step 7: Commit**

```bash
git add src/sales/query.py
git commit -m "feat: add transporter branches and e-invoice submission history queries, update insert/update/get with new fields"
```

---

## Phase 4: Backend Endpoints

### Task 5: Add and update endpoints

**Files:**
- Modify: `src/sales/salesInvoice.py` (update create_sales_invoice, update_sales_invoice, get_sales_invoice_by_id, add get_transporter_branches endpoint)

- [ ] **Step 1: Add new get_transporter_branches endpoint**

Open `src/sales/salesInvoice.py`, add this new endpoint:

```python
@router.get("/get_transporter_branches")
async def get_transporter_branches(
    request: Request,
    transporter_id: int = Query(..., description="Transporter party ID"),
    co_id: int = Query(..., description="Company ID"),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Fetch all branches for a transporter party.
    Used to populate transporter branch dropdown and retrieve GST number.
    """
    try:
        if not transporter_id or not co_id:
            raise HTTPException(status_code=400, detail="transporter_id and co_id are required")
        
        query = get_transporter_branches(int(transporter_id))
        result = db.execute(query, {"transporter_id": int(transporter_id)}).fetchall()
        
        branches = [dict(r._mapping) for r in result]
        
        return {"data": branches}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 2: Update create_sales_invoice endpoint**

Find the `create_sales_invoice()` endpoint. Update the function signature to accept the 9 new fields in the payload:

```python
@router.post("/create_sales_invoice")
async def create_sales_invoice(
    request: Request,
    payload: dict,  # Pydantic schema if exists, else dict
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new sales invoice with all fields including transporter GST, buyer order, e-invoice fields."""
    try:
        # Extract 9 new fields from payload
        transporter_branch_id = payload.get("transporter_branch_id")
        transporter_doc_no = payload.get("transporter_doc_no")
        transporter_doc_date = payload.get("transporter_doc_date")
        buyer_order_no = payload.get("buyer_order_no")
        buyer_order_date = payload.get("buyer_order_date")
        irn = payload.get("irn")
        ack_no = payload.get("ack_no")
        ack_date = payload.get("ack_date")
        qr_code = payload.get("qr_code")
        
        # ... existing validation ...
        
        # Call updated insert_sales_invoice with new parameters
        query, params = insert_sales_invoice(
            # ... existing params ...
            transporter_branch_id=transporter_branch_id,
            transporter_doc_no=transporter_doc_no,
            transporter_doc_date=transporter_doc_date,
            buyer_order_no=buyer_order_no,
            buyer_order_date=buyer_order_date,
            irn=irn,
            ack_no=ack_no,
            ack_date=ack_date,
            qr_code=qr_code,
        )
        
        # ... execute and return ...
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 3: Update update_sales_invoice endpoint similarly**

Apply the same pattern to `update_sales_invoice()` endpoint.

- [ ] **Step 4: Update get_sales_invoice_by_id endpoint**

Update the endpoint to include `transporter_gst_no` and `e_invoice_submission_history`:

```python
@router.get("/get_sales_invoice_by_id")
async def get_sales_invoice_by_id(
    request: Request,
    invoice_id: int = Query(...),
    co_id: int = Query(...),
    menu_id: int = Query(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get invoice details including new fields and submission history."""
    try:
        # ... existing validation ...
        
        # Get main invoice data with transporter GST
        query = get_invoice_by_id_query(int(invoice_id), int(co_id))
        result = db.execute(query, {"invoice_id": int(invoice_id), "co_id": int(co_id)}).fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found")
        
        invoice_data = dict(result._mapping)
        
        # Get e-invoice submission history if any
        history_query = get_e_invoice_submission_history(int(invoice_id))
        history_result = db.execute(history_query, {"invoice_id": int(invoice_id)}).fetchall()
        invoice_data["e_invoice_submission_history"] = [dict(r._mapping) for r in history_result]
        
        return {"data": invoice_data}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 5: Create placeholder e_invoice_handler module**

Create new file `src/sales/e_invoice_handler.py`:

```python
"""
E-Invoice Portal Integration Handler

This module provides the structure for future GST e-invoice portal integration.
Placeholders define the interface for:
- Portal API client (authentication, submission)
- Response parsing (extract IRN, Ack No., etc.)
- Error handling (submission status tracking)
- Audit trail logging (e_invoice_responses table)

Implementation deferred until portal API credentials and specifications are available.
"""

class EInvoicePortalClient:
    """GST e-invoice portal API client - structure only, implementation TBD."""
    pass


class EInvoiceResponseParser:
    """Parser for GST portal API responses - structure only, implementation TBD."""
    pass


def submit_invoice_to_portal(invoice_id: int, invoice_data: dict, db_session) -> dict:
    """
    Submit invoice to GST e-invoice portal.
    
    Args:
        invoice_id: Sales invoice ID
        invoice_data: Invoice details dict
        db_session: Database session
    
    Returns:
        dict with keys: success (bool), irn (str), ack_no (str), ack_date (str), qr_code (str), error (str)
    
    Implementation TBD - awaiting portal API credentials and spec.
    """
    raise NotImplementedError("E-invoice portal integration pending")
```

- [ ] **Step 6: Commit**

```bash
git add src/sales/salesInvoice.py src/sales/e_invoice_handler.py
git commit -m "feat: add get_transporter_branches endpoint, update create/update/get with new fields, add e_invoice_handler placeholder"
```

---

## Phase 5: Backend Tests

### Task 6: Write comprehensive backend tests

**Files:**
- Create: `src/test/test_sales_invoice_transporter_fields.py`

- [ ] **Step 1: Write test file with all test cases**

Create `src/test/test_sales_invoice_transporter_fields.py`:

```python
"""
Tests for sales invoice transporter GST, buyer order, and e-invoice fields.
Tests cover new endpoints and updated create/update/get operations.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import date

from src.main import app

client = TestClient(app)


class TestGetTransporterBranches:
    """Test the new get_transporter_branches endpoint."""
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_get_transporter_branches_success(self, mock_auth, mock_db):
        """Test fetching branches for a transporter with valid data."""
        mock_session = MagicMock()
        
        # Mock branch results
        branch1 = MagicMock()
        branch1._mapping = {
            "id": 1,
            "gst_no": "19AATFN9790P1ZR",
            "address": "123 Main St",
            "state_id": 19,
            "party_name": "Transporter Inc"
        }
        branch2 = MagicMock()
        branch2._mapping = {
            "id": 2,
            "gst_no": "19AATFN9790P1ZS",
            "address": "456 Branch St",
            "state_id": 19,
            "party_name": "Transporter Inc"
        }
        
        mock_session.execute.return_value.fetchall.return_value = [branch1, branch2]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        response = client.get("/api/salesInvoice/get_transporter_branches?transporter_id=1&co_id=1")
        
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) == 2
        assert data["data"][0]["gst_no"] == "19AATFN9790P1ZR"
    
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_get_transporter_branches_missing_transporter_id(self, mock_auth):
        """Test missing required transporter_id parameter."""
        mock_auth.return_value = {"user_id": 1}
        
        response = client.get("/api/salesInvoice/get_transporter_branches?co_id=1")
        
        assert response.status_code == 422  # Pydantic validation error
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_get_transporter_branches_empty_result(self, mock_auth, mock_db):
        """Test transporter with no branches."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        response = client.get("/api/salesInvoice/get_transporter_branches?transporter_id=999&co_id=1")
        
        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []


class TestCreateSalesInvoiceWithNewFields:
    """Test creating sales invoice with new fields."""
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_create_with_transporter_fields(self, mock_auth, mock_db):
        """Test creating invoice with transporter doc number and date."""
        mock_session = MagicMock()
        mock_session.execute.return_value.lastrowid = 123
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        payload = {
            "branch": 1,
            "date": "2026-04-01",
            "party": 1,
            "items": [
                {
                    "item": 1,
                    "uom": 1,
                    "quantity": 10,
                    "rate": 100,
                }
            ],
            "transporter": 1,
            "transporter_branch_id": 1,
            "transporter_doc_no": "LR123456",
            "transporter_doc_date": "2026-04-01",
            "buyer_order_no": "PO-2026-001",
            "buyer_order_date": "2026-03-28",
            "irn": None,
            "ack_no": None,
            "ack_date": None,
            "qr_code": None,
        }
        
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        
        # Verify creation endpoint was called
        # Actual assertion depends on endpoint implementation
        assert response.status_code in [200, 201]
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_create_with_einvoice_fields(self, mock_auth, mock_db):
        """Test creating invoice with manual e-invoice fields."""
        mock_session = MagicMock()
        mock_session.execute.return_value.lastrowid = 124
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        payload = {
            "branch": 1,
            "date": "2026-04-01",
            "party": 1,
            "items": [{"item": 1, "uom": 1, "quantity": 10, "rate": 100}],
            "irn": "6f124eef9f44c1d42b30f8417006fef2f929b29130793a9d88bee8c3dfb71053",
            "ack_no": "182621320257139",
            "ack_date": "2026-01-13",
            "qr_code": "base64_qr_data_here",
        }
        
        response = client.post("/api/salesInvoice/create_sales_invoice", json=payload)
        
        assert response.status_code in [200, 201]


class TestGetSalesInvoiceWithNewFields:
    """Test retrieving invoice with all new fields."""
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_get_invoice_returns_new_fields(self, mock_auth, mock_db):
        """Test GET returns 9 new fields plus transporter_gst_no."""
        mock_session = MagicMock()
        
        # Mock invoice row
        invoice_row = MagicMock()
        invoice_row._mapping = {
            "invoice_id": 123,
            "invoice_no": 1,
            "invoice_date": date(2026, 4, 1),
            # ... other existing fields ...
            "transporter_branch_id": 1,
            "transporter_doc_no": "LR123456",
            "transporter_doc_date": date(2026, 4, 1),
            "buyer_order_no": "PO-2026-001",
            "buyer_order_date": date(2026, 3, 28),
            "irn": "6f124eef9f44c1d42b30f8417006fef2f929b29130793a9d88bee8c3dfb71053",
            "ack_no": "182621320257139",
            "ack_date": date(2026, 1, 13),
            "qr_code": "base64_qr_data",
            "transporter_gst_no": "19AATFN9790P1ZR",
        }
        
        # Mock submission history
        history_row = MagicMock()
        history_row._mapping = {
            "response_id": 1,
            "submission_status": "Accepted",
            "submitted_date_time": "2026-04-01 10:00:00",
            "irn_from_response": "6f124eef9f44c1d42b30f8417006fef2f929b29130793a9d88bee8c3dfb71053",
            "error_message": None,
            "submitted_by": 1,
        }
        
        # Setup mocks
        mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=invoice_row)),
            MagicMock(fetchall=MagicMock(return_value=[history_row])),
        ]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        response = client.get("/api/salesInvoice/get_sales_invoice_by_id?invoice_id=123&co_id=1&menu_id=1")
        
        assert response.status_code == 200
        data = response.json()["data"]
        
        # Verify 9 new fields present
        assert data["transporter_branch_id"] == 1
        assert data["transporter_doc_no"] == "LR123456"
        assert data["transporter_doc_date"] == "2026-04-01"
        assert data["buyer_order_no"] == "PO-2026-001"
        assert data["buyer_order_date"] == "2026-03-28"
        assert data["irn"] == "6f124eef9f44c1d42b30f8417006fef2f929b29130793a9d88bee8c3dfb71053"
        assert data["ack_no"] == "182621320257139"
        assert data["ack_date"] == "2026-01-13"
        assert data["qr_code"] == "base64_qr_data"
        
        # Verify derived field
        assert data["transporter_gst_no"] == "19AATFN9790P1ZR"
        
        # Verify submission history
        assert "e_invoice_submission_history" in data
        assert len(data["e_invoice_submission_history"]) == 1
        assert data["e_invoice_submission_history"][0]["submission_status"] == "Accepted"


class TestUpdateSalesInvoiceWithNewFields:
    """Test updating invoice with new fields."""
    
    @patch("src.sales.salesInvoice.get_tenant_db")
    @patch("src.sales.salesInvoice.get_current_user_with_refresh")
    def test_update_transporter_doc_no(self, mock_auth, mock_db):
        """Test updating transporter doc number."""
        mock_session = MagicMock()
        mock_session.execute.return_value.rowcount = 1
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}
        
        payload = {
            "invoice_id": 123,
            "transporter_doc_no": "LR-NEW-789",
            "transporter_doc_date": "2026-04-02",
        }
        
        response = client.put("/api/salesInvoice/update_sales_invoice", json=payload)
        
        assert response.status_code == 200


# Run with: pytest src/test/test_sales_invoice_transporter_fields.py -v
```

- [ ] **Step 2: Run the tests**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && pytest src/test/test_sales_invoice_transporter_fields.py -v
```

Expected: All tests pass (or mostly pass, mocks may need tuning based on actual endpoint implementation)

- [ ] **Step 3: Commit tests**

```bash
git add src/test/test_sales_invoice_transporter_fields.py
git commit -m "test: add comprehensive tests for transporter, buyer order, and e-invoice fields"
```

---

## Phase 6: Frontend Types & Schemas

### Task 7: Update frontend types

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/types/salesInvoiceTypes.ts`

- [ ] **Step 1: Add new type definitions**

Open the types file, find `InvoiceFormValues` interface. Add these new fields:

```typescript
export type InvoiceFormValues = {
  // ... existing fields ...
  
  // Transporter GST fields
  transporter_branch_id?: number;
  transporter_gst_no?: string; // read-only, derived from branch
  transporter_doc_no?: string;
  transporter_doc_date?: string; // ISO date string
  
  // Buyer order fields
  buyer_order_no?: string;
  buyer_order_date?: string; // ISO date string
  
  // e-Invoice fields (manual entry now, portal auto-fill later)
  irn?: string;
  ack_no?: string;
  ack_date?: string; // ISO date string
  qr_code?: string;
  
  // Submission history (read-only)
  e_invoice_submission_history?: EInvoiceSubmission[];
};

export type InvoiceDetails = InvoiceFormValues & {
  // Details response includes all form values plus computed fields
};

export type TransporterBranchRecord = {
  id: number;
  gst_no: string;
  address: string;
  state_id: number;
};

export type EInvoiceSubmission = {
  response_id: number;
  submission_status: "Draft" | "Submitted" | "Accepted" | "Rejected" | "Error";
  submitted_date_time: string; // ISO datetime
  irn_from_response?: string;
  error_message?: string;
  submitted_by?: number;
};
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd c:/code/vowerp3ui && npm run build 2>&1 | head -20
```

Expected: No type errors related to new types

- [ ] **Step 3: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/types/salesInvoiceTypes.ts
git commit -m "feat: add types for transporter branch, buyer order, and e-invoice fields"
```

---

### Task 8: Update form schema

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceFormSchemas.ts`

- [ ] **Step 1: Add new fields to header schema**

Open the hook file, find `useSalesInvoiceHeaderSchema()`. Add these new field definitions to the schema array:

```typescript
// In header schema, add after existing transporter field:

{
  name: "transporter_branch_id",
  label: "Transporter Branch",
  type: "select",
  required: false,
  disabled: isView,
  options: [], // Populated dynamically from selectOptions.transporterBranchOptions
  visible: !!formValues.transporter, // Show only if transporter selected
},

{
  name: "transporter_gst_no",
  label: "Transporter GSTIN",
  type: "text",
  required: false,
  disabled: true, // Always read-only
  visible: !!formValues.transporter_gst_no, // Show only if available
},

{
  name: "transporter_doc_no",
  label: "Transporter Doc No.",
  type: "text",
  required: false,
  disabled: isView,
  placeholder: "LR No. / Bill of Lading / RR No.",
},

{
  name: "transporter_doc_date",
  label: "Transporter Doc Date",
  type: "date",
  required: false,
  disabled: isView,
},

// In order references section (after sales_order_date):

{
  name: "buyer_order_no",
  label: "Buyer's Order No.",
  type: "text",
  required: false,
  disabled: isView,
  placeholder: "Customer's PO / Order reference",
},

{
  name: "buyer_order_date",
  label: "Buyer's Order Date",
  type: "date",
  required: false,
  disabled: isView,
},

// New e-Invoice section fields:

{
  name: "irn",
  label: "IRN",
  type: "text",
  required: false,
  disabled: isView,
  placeholder: "Invoice Reference Number from GST portal",
},

{
  name: "ack_no",
  label: "Ack No.",
  type: "text",
  required: false,
  disabled: isView,
  placeholder: "Acknowledgement number from portal",
},

{
  name: "ack_date",
  label: "Ack Date",
  type: "date",
  required: false,
  disabled: isView,
},

{
  name: "qr_code",
  label: "QR Code",
  type: "textarea",
  required: false,
  disabled: isView,
  placeholder: "Base64 encoded QR code or URL from portal",
  rows: 3,
},
```

- [ ] **Step 2: Verify schema compiles**

```bash
cd c:/code/vowerp3ui && npm run type-check 2>&1 | head -20
```

Expected: No TypeScript errors

- [ ] **Step 3: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceFormSchemas.ts
git commit -m "feat: add new fields to sales invoice form schema"
```

---

## Phase 7: Frontend State Management

### Task 9: Update select options and form state hooks

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceSelectOptions.ts`
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceFormState.ts`

- [ ] **Step 1: Add transporter branch state to select options hook**

Open `useSalesInvoiceSelectOptions.ts`, add state:

```typescript
export function useSalesInvoiceSelectOptions(coId: number, branchId: number) {
  const [transporterOptions, setTransporterOptions] = useState<TransporterRecord[]>([]);
  const [transporterBranchOptions, setTransporterBranchOptions] = useState<TransporterBranchRecord[]>([]);
  const [loading, setLoading] = useState(false);
  
  // ... existing code ...
  
  const fetchTransporterBranches = useCallback(
    async (transporterId: number) => {
      if (!transporterId) {
        setTransporterBranchOptions([]);
        return;
      }
      
      try {
        setLoading(true);
        const response = await getTransporterBranches(transporterId, coId);
        setTransporterBranchOptions(response.data);
      } catch (error) {
        console.error("Failed to fetch transporter branches:", error);
        setTransporterBranchOptions([]);
      } finally {
        setLoading(false);
      }
    },
    [coId]
  );
  
  return {
    transporterOptions,
    transporterBranchOptions,
    fetchTransporterBranches,
    // ... existing returns ...
  };
}
```

- [ ] **Step 2: Add transporter branch change handler to form state hook**

Open `useSalesInvoiceFormState.ts`, add handlers:

```typescript
export function useSalesInvoiceFormState(initialValues?: InvoiceFormValues) {
  const [formValues, setFormValues] = useState<InvoiceFormValues>(initialValues || {});
  
  // When transporter changes, fetch its branches
  const handleTransporterChange = useCallback(
    (transporterId: number) => {
      setFormValues((prev) => ({
        ...prev,
        transporter: transporterId,
        transporter_branch_id: undefined,
        transporter_gst_no: undefined,
      }));
      
      // Trigger branch fetch (from selectOptions hook)
      selectOptionsRef?.current?.fetchTransporterBranches(transporterId);
    },
    []
  );
  
  // When transporter branch changes, auto-fill GST
  const handleTransporterBranchChange = useCallback(
    (branchId: number, selectedBranch: TransporterBranchRecord) => {
      setFormValues((prev) => ({
        ...prev,
        transporter_branch_id: branchId,
        transporter_gst_no: selectedBranch?.gst_no || undefined,
      }));
    },
    []
  );
  
  // When DO/SO auto-fills transporter, also fetch its branches
  const handleAutoFillTransporter = useCallback(
    (transporterId: number) => {
      handleTransporterChange(transporterId);
    },
    [handleTransporterChange]
  );
  
  return {
    formValues,
    setFormValues,
    handleTransporterChange,
    handleTransporterBranchChange,
    handleAutoFillTransporter,
    // ... existing returns ...
  };
}
```

- [ ] **Step 3: Verify hooks compile**

```bash
cd c:/code/vowerp3ui && npm run type-check 2>&1 | grep -i "error\|warn" | head -10
```

Expected: No errors related to new hooks/functions

- [ ] **Step 4: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceSelectOptions.ts
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/hooks/useSalesInvoiceFormState.ts
git commit -m "feat: add transporter branch fetching and GST auto-fill logic"
```

---

## Phase 8: Frontend UI Components

### Task 10: Update header form component

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/components/SalesInvoiceHeaderForm.tsx`

- [ ] **Step 1: Add logistics section with transporter fields**

Open `SalesInvoiceHeaderForm.tsx`, find the transporter field section. After the existing transporter dropdown, add:

```tsx
// Transporter Branch dropdown (conditional)
{formValues.transporter && transporterBranchOptions.length > 0 && (
  <FormField
    label="Transporter Branch"
    error={errors.transporter_branch_id}
  >
    <Select
      value={formValues.transporter_branch_id}
      onChange={(e) => {
        const branchId = Number(e.target.value);
        const selectedBranch = transporterBranchOptions.find(b => b.id === branchId);
        handleTransporterBranchChange(branchId, selectedBranch);
      }}
      disabled={isView}
    >
      <MenuItem value="">-- Select Branch --</MenuItem>
      {transporterBranchOptions.map((branch) => (
        <MenuItem key={branch.id} value={branch.id}>
          {branch.address} (GST: {branch.gst_no})
        </MenuItem>
      ))}
    </Select>
  </FormField>
)}

// Transporter GSTIN display (read-only)
{formValues.transporter_gst_no && (
  <FormField label="Transporter GSTIN" disabled>
    <TextField
      value={formValues.transporter_gst_no}
      disabled
      fullWidth
    />
  </FormField>
)}

// Transporter Doc No. and Date
<Grid container spacing={2}>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Transporter Doc No."
      error={errors.transporter_doc_no}
    >
      <TextField
        value={formValues.transporter_doc_no || ""}
        onChange={(e) =>
          setFormValues({
            ...formValues,
            transporter_doc_no: e.target.value,
          })
        }
        disabled={isView}
        placeholder="LR No. / Bill of Lading"
        fullWidth
      />
    </FormField>
  </Grid>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Transporter Doc Date"
      error={errors.transporter_doc_date}
    >
      <TextField
        type="date"
        value={formValues.transporter_doc_date || ""}
        onChange={(e) =>
          setFormValues({
            ...formValues,
            transporter_doc_date: e.target.value,
          })
        }
        disabled={isView}
        fullWidth
      />
    </FormField>
  </Grid>
</Grid>
```

- [ ] **Step 2: Add buyer order section**

Find the "Order References" or sales order section, add:

```tsx
<Box sx={{ mt: 3, mb: 2 }}>
  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
    Order References
  </Typography>
</Box>

<Grid container spacing={2}>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Sales Order No."
      error={errors.sales_order_id}
    >
      {/* Existing sales order select */}
    </FormField>
  </Grid>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Sales Order Date"
      error={errors.sales_order_date}
    >
      {/* Existing sales order date field */}
    </FormField>
  </Grid>
</Grid>

<Grid container spacing={2} sx={{ mt: 1 }}>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Buyer's Order No."
      error={errors.buyer_order_no}
    >
      <TextField
        value={formValues.buyer_order_no || ""}
        onChange={(e) =>
          setFormValues({
            ...formValues,
            buyer_order_no: e.target.value,
          })
        }
        disabled={isView}
        placeholder="Customer's PO reference"
        fullWidth
      />
    </FormField>
  </Grid>
  <Grid item xs={12} sm={6}>
    <FormField
      label="Buyer's Order Date"
      error={errors.buyer_order_date}
    >
      <TextField
        type="date"
        value={formValues.buyer_order_date || ""}
        onChange={(e) =>
          setFormValues({
            ...formValues,
            buyer_order_date: e.target.value,
          })
        }
        disabled={isView}
        fullWidth
      />
    </FormField>
  </Grid>
</Grid>
```

- [ ] **Step 3: Add e-Invoice section with submission history**

Near the end of the form, add:

```tsx
<Box sx={{ mt: 4, mb: 2 }}>
  <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
    e-Invoice Details
  </Typography>
</Box>

<Grid container spacing={2}>
  <Grid item xs={12} sm={6}>
    <FormField label="IRN" error={errors.irn}>
      <TextField
        value={formValues.irn || ""}
        onChange={(e) =>
          setFormValues({ ...formValues, irn: e.target.value })
        }
        disabled={isView}
        placeholder="Invoice Reference Number from GST portal"
        fullWidth
      />
    </FormField>
  </Grid>
  <Grid item xs={12} sm={6}>
    <FormField label="Ack No." error={errors.ack_no}>
      <TextField
        value={formValues.ack_no || ""}
        onChange={(e) =>
          setFormValues({ ...formValues, ack_no: e.target.value })
        }
        disabled={isView}
        placeholder="Acknowledgement number from portal"
        fullWidth
      />
    </FormField>
  </Grid>
</Grid>

<Grid container spacing={2} sx={{ mt: 1 }}>
  <Grid item xs={12} sm={6}>
    <FormField label="Ack Date" error={errors.ack_date}>
      <TextField
        type="date"
        value={formValues.ack_date || ""}
        onChange={(e) =>
          setFormValues({ ...formValues, ack_date: e.target.value })
        }
        disabled={isView}
        fullWidth
      />
    </FormField>
  </Grid>
  <Grid item xs={12} sm={6}>
    <FormField label="QR Code" error={errors.qr_code}>
      <TextField
        value={formValues.qr_code || ""}
        onChange={(e) =>
          setFormValues({ ...formValues, qr_code: e.target.value })
        }
        disabled={isView}
        multiline
        rows={2}
        placeholder="Base64 encoded QR code from portal"
        fullWidth
      />
    </FormField>
  </Grid>
</Grid>

{/* Submission History (if exists) */}
{formValues.e_invoice_submission_history &&
  formValues.e_invoice_submission_history.length > 0 && (
    <Box sx={{ mt: 3, p: 2, bgcolor: "background.paper", border: "1px solid divider" }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 2 }}>
        Submission History
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Status</TableCell>
            <TableCell>Submitted</TableCell>
            <TableCell>IRN</TableCell>
            <TableCell>Error</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {formValues.e_invoice_submission_history.map((item, idx) => (
            <TableRow key={idx}>
              <TableCell>{item.submission_status}</TableCell>
              <TableCell>
                {new Date(item.submitted_date_time).toLocaleString()}
              </TableCell>
              <TableCell>{item.irn_from_response || "-"}</TableCell>
              <TableCell>{item.error_message || "-"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )}
```

- [ ] **Step 4: Verify component renders without errors**

```bash
cd c:/code/vowerp3ui && npm run dev &
# Navigate to sales invoice create page in browser
# Check browser console for errors
```

Expected: No console errors, new fields visible in form

- [ ] **Step 5: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/components/SalesInvoiceHeaderForm.tsx
git commit -m "feat: add UI for transporter branch, buyer order, and e-invoice fields"
```

---

## Phase 9: Frontend Mappers & Services

### Task 11: Update mappers and service

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/utils/salesInvoiceMappers.ts`
- Modify: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/utils/salesInvoiceService.ts`

- [ ] **Step 1: Update API response to form mapper**

Open `salesInvoiceMappers.ts`, find `mapInvoiceDetailsToFormValues()`. Add mappings for new fields:

```typescript
export function mapInvoiceDetailsToFormValues(
  details: InvoiceDetails
): InvoiceFormValues {
  return {
    // ... existing fields ...
    
    // New fields
    transporter_branch_id: details.transporter_branch_id,
    transporter_gst_no: details.transporter_gst_no,
    transporter_doc_no: details.transporter_doc_no,
    transporter_doc_date: details.transporter_doc_date,
    buyer_order_no: details.buyer_order_no,
    buyer_order_date: details.buyer_order_date,
    irn: details.irn,
    ack_no: details.ack_no,
    ack_date: details.ack_date,
    qr_code: details.qr_code,
    e_invoice_submission_history: details.e_invoice_submission_history,
  };
}
```

- [ ] **Step 2: Update form to API payload mapper**

Find `mapFormValuesToApiPayload()`. Add mappings:

```typescript
export function mapFormValuesToApiPayload(
  formValues: InvoiceFormValues,
  lineItems: EditableLineItem[]
): any {
  const payload = {
    // ... existing fields ...
    
    // New fields
    transporter_branch_id: formValues.transporter_branch_id || null,
    transporter_doc_no: formValues.transporter_doc_no || null,
    transporter_doc_date: formValues.transporter_doc_date || null,
    buyer_order_no: formValues.buyer_order_no || null,
    buyer_order_date: formValues.buyer_order_date || null,
    irn: formValues.irn || null,
    ack_no: formValues.ack_no || null,
    ack_date: formValues.ack_date || null,
    qr_code: formValues.qr_code || null,
  };
  
  return payload;
}
```

- [ ] **Step 3: Add getTransporterBranches service function**

Open `salesInvoiceService.ts`, add:

```typescript
export async function getTransporterBranches(
  transporterId: number,
  coId: number
): Promise<{ data: TransporterBranchRecord[] }> {
  try {
    const response = await apiRoutesPortalMasters.get(
      `/salesInvoice/get_transporter_branches?transporter_id=${transporterId}&co_id=${coId}`
    );
    return response.data;
  } catch (error) {
    console.error("Failed to fetch transporter branches:", error);
    throw error;
  }
}
```

- [ ] **Step 4: Verify imports and usage**

```bash
cd c:/code/vowerp3ui && npm run type-check 2>&1 | grep -E "mappers|service" | head -10
```

Expected: No errors related to mappers/service

- [ ] **Step 5: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/utils/salesInvoiceMappers.ts
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/utils/salesInvoiceService.ts
git commit -m "feat: add mappers and service for new fields"
```

---

## Phase 10: Frontend Tests

### Task 12: Write frontend tests

**Files:**
- Create: `vowerp3ui/src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/__tests__/transporter-fields.test.tsx`

- [ ] **Step 1: Write test file**

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import SalesInvoiceHeaderForm from "../components/SalesInvoiceHeaderForm";
import * as salesInvoiceService from "../utils/salesInvoiceService";

describe("Transporter Fields", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should render transporter doc no and date fields", () => {
    const { getByLabelText } = render(
      <SalesInvoiceHeaderForm formValues={{}} setFormValues={() => {}} />
    );
    
    expect(getByLabelText(/Transporter Doc No/i)).toBeInTheDocument();
    expect(getByLabelText(/Transporter Doc Date/i)).toBeInTheDocument();
  });

  it("should fetch transporter branches when transporter selected", async () => {
    const mockFetch = vi.spyOn(salesInvoiceService, "getTransporterBranches");
    mockFetch.mockResolvedValue({
      data: [
        {
          id: 1,
          gst_no: "19AATFN9790P1ZR",
          address: "123 Main St",
          state_id: 19,
        },
      ],
    });

    const handleTransporterChange = vi.fn();
    const { getByDisplayValue } = render(
      <SalesInvoiceHeaderForm
        formValues={{ transporter: 1 }}
        onTransporterChange={handleTransporterChange}
      />
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(1, expect.any(Number));
    });
  });

  it("should display buyer order fields", () => {
    const { getByLabelText } = render(
      <SalesInvoiceHeaderForm formValues={{}} setFormValues={() => {}} />
    );

    expect(getByLabelText(/Buyer's Order No/i)).toBeInTheDocument();
    expect(getByLabelText(/Buyer's Order Date/i)).toBeInTheDocument();
  });

  it("should render e-invoice fields", () => {
    const { getByLabelText } = render(
      <SalesInvoiceHeaderForm formValues={{}} setFormValues={() => {}} />
    );

    expect(getByLabelText(/IRN/i)).toBeInTheDocument();
    expect(getByLabelText(/Ack No/i)).toBeInTheDocument();
    expect(getByLabelText(/Ack Date/i)).toBeInTheDocument();
    expect(getByLabelText(/QR Code/i)).toBeInTheDocument();
  });

  it("should display submission history if present", () => {
    const history = [
      {
        response_id: 1,
        submission_status: "Accepted",
        submitted_date_time: "2026-04-01T10:00:00",
        irn_from_response: "6f124eef...",
        error_message: null,
      },
    ];

    const { getByText } = render(
      <SalesInvoiceHeaderForm
        formValues={{ e_invoice_submission_history: history }}
        setFormValues={() => {}}
      />
    );

    expect(getByText(/Submission History/i)).toBeInTheDocument();
    expect(getByText(/Accepted/i)).toBeInTheDocument();
  });
});

describe("Mappers", () => {
  it("should map invoice details to form values with new fields", () => {
    const details = {
      invoice_id: 1,
      transporter_doc_no: "LR123",
      transporter_doc_date: "2026-04-01",
      buyer_order_no: "PO-001",
      buyer_order_date: "2026-03-28",
      irn: "abc123",
      ack_no: "ack123",
      ack_date: "2026-04-01",
      qr_code: "qr_data",
    };

    const formValues = mapInvoiceDetailsToFormValues(details);

    expect(formValues.transporter_doc_no).toBe("LR123");
    expect(formValues.buyer_order_no).toBe("PO-001");
    expect(formValues.irn).toBe("abc123");
  });

  it("should map form values to API payload with new fields", () => {
    const formValues = {
      transporter_doc_no: "LR456",
      buyer_order_no: "PO-002",
      irn: "def456",
    };

    const payload = mapFormValuesToApiPayload(formValues, []);

    expect(payload.transporter_doc_no).toBe("LR456");
    expect(payload.buyer_order_no).toBe("PO-002");
    expect(payload.irn).toBe("def456");
  });
});
```

- [ ] **Step 2: Run tests**

```bash
cd c:/code/vowerp3ui && npm run test -- transporter-fields.test.tsx
```

Expected: Tests pass (some may skip if components/mocks aren't fully set up)

- [ ] **Step 3: Commit**

```bash
git add src/app/dashboardportal/sales/salesInvoice/createSalesInvoice/__tests__/transporter-fields.test.tsx
git commit -m "test: add frontend tests for transporter, buyer order, and e-invoice fields"
```

---

## Final Verification

### Task 13: End-to-end verification

- [ ] **Step 1: Run all backend tests**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && pytest src/test/test_sales_invoice_transporter_fields.py -v
```

Expected: All tests pass

- [ ] **Step 2: Run all frontend tests**

```bash
cd c:/code/vowerp3ui && npm run test
```

Expected: All tests pass or skip gracefully

- [ ] **Step 3: Start dev server and manual test**

```bash
cd c:/code/vowerp3be && source .venv/Scripts/activate && uvicorn src.main:app --reload &
```

Then in vowerp3ui:
```bash
cd c:/code/vowerp3ui && npm run dev &
```

Navigate to sales invoice create page. Test:
- Create invoice with transporter → verify branch dropdown appears
- Select branch → verify GSTIN auto-fills
- Enter buyer order no./date → verify saved
- Enter transporter doc no./date → verify saved
- Enter e-invoice fields → verify saved and displayed on reload

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete transporter GST, buyer order, and e-invoice field implementation"
```

---

## Summary

**Files Created:**
- 2 migration files (sales_invoice columns + e_invoice_responses table)
- 1 backend test file
- 1 placeholder e_invoice_handler module
- 1 frontend test file

**Files Modified:**
- src/models/sales.py (ORM)
- src/sales/query.py (queries)
- src/sales/salesInvoice.py (endpoints)
- Frontend: 7 files (types, schemas, hooks, components, mappers, service)

**Total Tasks:** 13 (granular, 2-5 minute steps each)

**Key Deliverables:**
- ✅ 9 new columns on sales_invoice table
- ✅ e_invoice_responses audit table with full submission history
- ✅ Transporter GST auto-fill based on branch selection
- ✅ Buyer order tracking (no. + date)
- ✅ Transporter doc number + date capture
- ✅ Manual e-invoice field entry (IRN, Ack No., Ack Date, QR Code)
- ✅ Submission history display (future portal integration ready)
- ✅ Comprehensive test coverage (backend + frontend)
