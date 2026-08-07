# Changes: Add Gate Entry No and Warehouse No to Stock Outstanding View

## Summary
Added `jute_gate_entry_no` and `warehouse_id` columns to the `vw_jute_stock_outstanding` view so that when users select jute issue items from stock, they can see the gate entry number and warehouse information in the table.

## Backend Changes

### 1. ORM Model Update (src/models/jute.py)
- Updated `VwJuteStockOutstanding` class to include two new mapped columns:
  - `jute_gate_entry_no: Mapped[Optional[int]]` - Gate entry number from jute_mr table
  - `warehouse_id: Mapped[Optional[int]]` - Warehouse ID from jute_mr_li table
- Updated the view definition SQL comment to reflect the new SELECT statement with these columns

### 2. Query Functions Update (src/juteProcurement/query.py)
Updated both stock outstanding query functions to select the new columns:
- `get_jute_stock_outstanding_query()` - Added `vso.jute_gate_entry_no` and `vso.warehouse_id` to SELECT
- `get_jute_stock_outstanding_by_item_query()` - Added `vso.jute_gate_entry_no` and `vso.warehouse_id` to SELECT

### 3. Database View Migration (dbqueries/migrations/update_vw_jute_stock_outstanding.sql)
Created a new migration script that:
- Drops the existing `vw_jute_stock_outstanding` view
- Recreates it with the new columns:
  - `jm.jute_gate_entry_no` (from jute_mr table)
  - `jml.warehouse_id` (from jute_mr_li table)

## Frontend Changes

### 1. Type Definition Update (src/app/dashboardportal/jutePurchase/juteIssue/edit/types/juteIssueTypes.ts)
Updated the `StockOutstandingItem` type to include:
```typescript
jute_gate_entry_no?: number;
warehouse_id?: number;
```

### 2. UI Table Update (src/app/dashboardportal/jutePurchase/juteIssue/edit/page.tsx)
Updated the stock selection dialog table to display the new columns:
- Added table header: "Gate Entry No" (position 1)
- Added table header: "Warehouse" (position 6)
- Added table cells to render:
  - `stock.jute_gate_entry_no || "-"` 
  - `stock.warehouse_id || "-"`

## Implementation Details

### Data Flow
1. User clicks "Add from Stock" button on jute issue page
2. Stock dialog opens and fetches available stock from API
3. API calls `get_jute_stock_outstanding_query()` which now includes gate_entry_no and warehouse_id
4. Stock items display in table with new columns showing gate entry and warehouse information
5. User selects stock item and confirming adds it to the issue

### Column Positions in Table
1. Checkbox (Radio selection)
2. **Gate Entry No** (NEW)
3. MR No
4. Jute Type
5. Quality
6. Unit
7. **Warehouse** (NEW)
8. Bal Qty
9. Bal Weight (kg)
10. Rate/Qtl

## Database Requirements
Run the migration to update the view:
```sql
-- Execute the migration file
source dbqueries/migrations/update_vw_jute_stock_outstanding.sql;
```

Or manually execute:
```sql
DROP VIEW IF EXISTS vw_jute_stock_outstanding;

CREATE VIEW vw_jute_stock_outstanding AS
SELECT
    jml.jute_mr_li_id,
    jm.jute_gate_entry_no,
    jml.warehouse_id,
    jm.branch_id,
    jm.branch_mr_no,
    jml.actual_quality,
    jml.actual_qty,
    jml.actual_weight,
    jm.unit_conversion,
    (jml.actual_qty - IFNULL(iss.issqty, 0)) AS bal_qty,
    ROUND((jml.actual_weight - IFNULL(iss.isswt, 0)), 3) AS bal_weight,
    jml.accepted_weight,
    ROUND((jml.accepted_weight / jml.actual_qty) * IFNULL(iss.issqty, 0), 3) AS bal_accepted_weight,
    jml.rate,
    jml.actual_rate
FROM jute_mr jm
JOIN jute_mr_li jml ON jm.jute_mr_id = jml.jute_mr_id
LEFT JOIN (
    SELECT ji.jute_mr_li_id, SUM(ji.quantity) AS issqty, SUM(ji.weight) AS isswt
    FROM jute_issue ji
    GROUP BY ji.jute_mr_li_id
) iss ON iss.jute_mr_li_id = jml.jute_mr_li_id;
```

## Testing
1. Create a jute issue in the portal
2. Click "Add from Stock" button
3. Verify the stock table displays:
   - Gate Entry No column with values from jute_mr.jute_gate_entry_no
   - Warehouse column with values from jute_mr_li.warehouse_id
4. Select a stock item and verify it can be added to the issue

## Notes
- `jute_gate_entry_no` comes from the `jute_mr` table (header/master record)
- `warehouse_id` comes from the `jute_mr_li` table (line item record)
- Both columns are optional (nullable) and show "-" if no value exists
- The view maintains backward compatibility with existing queries
