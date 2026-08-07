# Enquiry Costing — Overhead & Margin as %, Per-Line Costing-Done — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the BOM cost sheet stop at base cost (material + conversion), let the sales-enquiry person add overhead% + margin% per line as % of that base, and mark costing done per line — surfaced on the flow board — before the enquiry can move to quotation.

**Architecture:** Reuse the existing costing chain (cost sheet → snapshot → enquiry line → quotation). Add only two columns (`sales_enquiry_dtl.overhead_pct`, `margin_pct`); derive per-line "done" and the sell price rather than storing them. Extend `confirm_line_costing`, the enquiry read + board queries, and gate the `COSTING_REVIEW → QUOTATION` forward. Frontend surfaces the % inputs (costing review), the base-only totals (cost sheet), and the costed-count (board).

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (sync, PyMySQL), MySQL, pytest; Next.js + MUI (vowerp3ui). Spec: `docs/superpowers/specs/2026-07-16-enquiry-costing-overhead-margin-design.md`.

## Global Constraints

- Handlers are plain `def`, never `async def`; read JSON via `parse_json_body(request)` (CLAUDE.md Sync Handler Policy).
- Portal persona → `db: Session = Depends(get_tenant_db)`; auth `token_data: dict = Depends(get_current_user_with_refresh)`.
- Responses wrapped `{"data": ...}` / `{"data": ..., "message": ...}`; never raw lists.
- SQL NULL is Python `None`, never `"null"`; bind-param names match `:name` exactly; type-cast (`int(...)`, `float(...)`).
- ORM in `src/models/` is authoritative schema; PascalCase models, snake_case columns/functions.
- No Alembic — migrations are SQL in `dbqueries/migrations/`, run via pymysql (venv). Target `dev3` first; other tenants (esp. `sls`) migrated BEFORE code deploy.
- Margin formula (fixed): `sell = base × (1 + overhead_pct/100) × (1 + margin_pct/100)`.
- Per-line "done": `cost_snapshot_id IS NOT NULL AND overhead_pct IS NOT NULL AND margin_pct IS NOT NULL`. `0` is a valid pct (done); `NULL` = not priced.
- Run backend tests from repo root: `source .venv/Scripts/activate && pytest src/test/<file> -v`.

---

### Task 1: Migration + ORM columns (schema foundation)

**Files:**
- Create: `dbqueries/migrations/enquiry_costing_overhead_margin.sql`
- Modify: `src/models/enquiry.py` (class `SalesEnquiryDtl`, after `costing_confirmed_date`, ~line 182)
- Test: `src/test/test_enquiry_costing_margin.py`

**Interfaces:**
- Produces: `sales_enquiry_dtl.overhead_pct` (DOUBLE NULL), `sales_enquiry_dtl.margin_pct` (DOUBLE NULL); `vw_bom_cost_summary.total_cost` = material + conversion only. ORM attrs `SalesEnquiryDtl.overhead_pct`, `SalesEnquiryDtl.margin_pct`.

- [ ] **Step 1: Write the migration SQL**

Create `dbqueries/migrations/enquiry_costing_overhead_margin.sql`:

```sql
-- Enquiry costing: overhead% + margin% on the enquiry line; base cost excludes overhead.
-- Date: 2026-07-16 | Run against: TENANT database (dev3 first, then sls + others BEFORE code deploy)

-- 1) Per-line overhead% + margin% (set by the costing/enquiry person at COSTING_REVIEW).
ALTER TABLE sales_enquiry_dtl
    ADD COLUMN overhead_pct DOUBLE NULL AFTER confirmed_cost_per_unit,
    ADD COLUMN margin_pct   DOUBLE NULL AFTER overhead_pct;

-- 2) Cost-sheet base excludes overhead: total_cost = material + conversion only.
CREATE OR REPLACE VIEW vw_bom_cost_summary AS
SELECT
    bh.bom_hdr_id, bh.item_id, im.item_code, im.item_name,
    bh.bom_version, bh.version_label, bh.status_id,
    bce.co_id, bce.effective_date,
    SUM(CASE WHEN ce.element_type = 'material'   THEN bce.amount ELSE 0 END) AS material_cost,
    SUM(CASE WHEN ce.element_type = 'conversion' THEN bce.amount ELSE 0 END) AS conversion_cost,
    SUM(CASE WHEN ce.element_type = 'overhead'   THEN bce.amount ELSE 0 END) AS overhead_cost,
    SUM(CASE WHEN ce.element_type IN ('material','conversion') THEN bce.amount ELSE 0 END) AS total_cost,
    COUNT(*) AS entry_count
FROM bom_cost_entry bce
INNER JOIN cost_element_mst ce   ON bce.cost_element_id = ce.cost_element_id
INNER JOIN item_bom_hdr_mst bh   ON bce.bom_hdr_id = bh.bom_hdr_id
INNER JOIN item_mst im           ON bh.item_id = im.item_id
WHERE bce.active = 1
GROUP BY bh.bom_hdr_id, bh.item_id, im.item_code, im.item_name,
         bh.bom_version, bh.version_label, bh.status_id, bce.co_id, bce.effective_date;

-- ROLLBACK:
-- ALTER TABLE sales_enquiry_dtl DROP COLUMN margin_pct, DROP COLUMN overhead_pct;
-- (restore vw_bom_cost_summary from create_bom_costing_tables.sql: total_cost = SUM(bce.amount))
```

Note: confirm the `FROM ... WHERE ... GROUP BY` tail matches the current view in `dbqueries/migrations/create_bom_costing_tables.sql:245-260` before running; copy that tail verbatim if it differs, changing only the `total_cost` line.

- [ ] **Step 2: Add the ORM columns**

In `src/models/enquiry.py`, class `SalesEnquiryDtl`, immediately after the `costing_confirmed_date` mapped_column (~line 182):

```python
    overhead_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    margin_pct: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
```

- [ ] **Step 3: Write the failing ORM test**

Create `src/test/test_enquiry_costing_margin.py`:

```python
from src.models.enquiry import SalesEnquiryDtl


def test_enquiry_dtl_has_pricing_columns():
    cols = SalesEnquiryDtl.__table__.columns.keys()
    assert "overhead_pct" in cols
    assert "margin_pct" in cols
```

- [ ] **Step 4: Run test to verify it passes** (ORM edit already done in Step 2)

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py::test_enquiry_dtl_has_pricing_columns -v`
Expected: PASS

- [ ] **Step 5: Apply the migration to dev3**

Read creds from `env/database.env`, then:

```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='dev3')
cur = conn.cursor()
with open('dbqueries/migrations/enquiry_costing_overhead_margin.sql') as f:
    for stmt in f.read().split(';'):
        s = stmt.strip()
        if s and not s.startswith('--'):
            cur.execute(s)
conn.commit(); conn.close(); print('applied to dev3')
"
```
Expected: `applied to dev3`. Verify: `DESCRIBE sales_enquiry_dtl;` shows `overhead_pct`, `margin_pct`.

Note: the view body spans multiple lines with no inner `;`; the split-on-`;` loop handles it. A statement is skipped only when it starts with `--` — the two real statements here do not.

- [ ] **Step 6: Commit**

```bash
git add dbqueries/migrations/enquiry_costing_overhead_margin.sql src/models/enquiry.py src/test/test_enquiry_costing_margin.py
git commit -m "feat(enquiry): add overhead_pct/margin_pct columns; base cost excludes overhead in view"
```

---

### Task 2: Rollup — base total excludes overhead

**Files:**
- Modify: `src/bomcosting/bomCosting.py` (`compute_full_rollup`, line ~189) + a new module-level helper
- Test: `src/test/test_enquiry_costing_margin.py` (append)

**Interfaces:**
- Produces: `compute_base_total(material_cost, conversion_cost) -> float`. `compute_full_rollup` writes `total_cost = material + conversion` (overhead computed + stored on the snapshot but excluded from the total), `cost_per_unit` follows.

- [ ] **Step 1: Write the failing test**

Append to `src/test/test_enquiry_costing_margin.py`:

```python
from src.bomcosting.bomCosting import compute_base_total


def test_base_total_excludes_overhead():
    # material 100, conversion 40 -> base 140 (overhead entered separately, never summed)
    assert compute_base_total(100.0, 40.0) == 140.0
    assert compute_base_total(0.0, 0.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py::test_base_total_excludes_overhead -v`
Expected: FAIL — `ImportError: cannot import name 'compute_base_total'`

- [ ] **Step 3: Add the helper and use it**

In `src/bomcosting/bomCosting.py`, add near the other rollup helpers (above `compute_full_rollup`, ~line 106):

```python
def compute_base_total(material_cost, conversion_cost):
    """Base cost = material + conversion. Overhead is applied later as a % on the
    enquiry line (design 2026-07-16), so it is NOT part of the cost-sheet total."""
    return float(material_cost) + float(conversion_cost)
```

Then replace line ~189 `total_cost = material_cost + conversion_cost + overhead_cost` with:

```python
    total_cost = compute_base_total(material_cost, conversion_cost)
```

(Leave the `overhead_cost` computation and the `BomCostSnapshot(..., overhead_cost=overhead_cost, ...)` write unchanged — the column stays for reference.)

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py::test_base_total_excludes_overhead -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/bomcosting/bomCosting.py src/test/test_enquiry_costing_margin.py
git commit -m "feat(bomcosting): base cost total excludes overhead in rollup"
```

---

### Task 3: confirm_line_costing accepts overhead% + margin%

**Files:**
- Modify: `src/sales/enquiry.py` — `update_enquiry_dtl_costing()` (~line 229) and `confirm_line_costing()` (~line 1499)
- Test: `src/test/test_enquiry_costing_margin.py` (append)

**Interfaces:**
- Consumes: existing `confirm_line_costing` mock pattern (mocked `get_tenant_db` session).
- Produces: `POST /api/salesEnquiry/confirm_line_costing` body now also accepts `overhead_pct`, `margin_pct` (optional floats); persisted on the line. Response `data` includes them.

- [ ] **Step 1: Extend the UPDATE statement**

Replace `update_enquiry_dtl_costing()` (`src/sales/enquiry.py:229-238`) body SQL with:

```python
    sql = """UPDATE sales_enquiry_dtl SET
        bom_hdr_id = :bom_hdr_id,
        cost_snapshot_id = :cost_snapshot_id,
        confirmed_cost_per_unit = :confirmed_cost_per_unit,
        costing_confirmed_by = :costing_confirmed_by,
        costing_confirmed_date = :costing_confirmed_date,
        overhead_pct = :overhead_pct,
        margin_pct = :margin_pct
    WHERE enquiry_dtl_id = :enquiry_dtl_id;"""
```

- [ ] **Step 2: Parse + persist the pcts in the handler**

In `confirm_line_costing` (`src/sales/enquiry.py`), after `bom_hdr_id = to_int(...)` (~line 1513) add:

```python
        def _opt_pct(v, name):
            if v is None or v == "":
                return None
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"Invalid {name}")
            if f < 0:
                raise HTTPException(status_code=400, detail=f"{name} cannot be negative")
            return f

        overhead_pct = _opt_pct(body.get("overhead_pct"), "overhead_pct")
        margin_pct = _opt_pct(body.get("margin_pct"), "margin_pct")
```

Then in the `db.execute(update_enquiry_dtl_costing(), {...})` call (~line 1568) add the two binds:

```python
            "overhead_pct": overhead_pct,
            "margin_pct": margin_pct,
```

And extend the returned `data` dict (~line 1579) with:

```python
                "overhead_pct": overhead_pct,
                "margin_pct": margin_pct,
```

- [ ] **Step 3: Write the failing test**

Append to `src/test/test_enquiry_costing_margin.py`:

```python
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def _line_state_row(**over):
    row = MagicMock()
    row._mapping = {"enquiry_dtl_id": 5, "sales_enquiry_id": 9, "item_id": 3,
                    "status_id": 3, "hold_flag": 0, "active": 1, "stage_code": "COSTING_REVIEW"}
    row._mapping.update(over)
    return row


@patch("src.sales.enquiry.get_current_user_with_refresh", return_value={"user_id": 1})
@patch("src.sales.enquiry.get_tenant_db")
def test_confirm_line_costing_persists_pcts(mock_db, _auth):
    session = MagicMock()
    bom_row = MagicMock(); bom_row._mapping = {"item_id": 3}
    snap_row = MagicMock(); snap_row._mapping = {"bom_cost_snapshot_id": 77, "cost_per_unit": 140.0}
    # fetchone() sequence: line state, bom hdr, snapshot
    session.execute.return_value.fetchone.side_effect = [_line_state_row(), bom_row, snap_row]
    mock_db.return_value.__enter__.return_value = session
    mock_db.return_value.__exit__.return_value = False

    resp = client.post("/api/salesEnquiry/confirm_line_costing",
                       json={"enquiry_dtl_id": 5, "bom_hdr_id": 12, "overhead_pct": 10, "margin_pct": 20})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["overhead_pct"] == 10.0
    assert data["margin_pct"] == 20.0
```

Note: match the exact `get_tenant_db` mock shape already used by the enquiry tests in `src/test/` (context-manager vs generator) — copy from the nearest existing `confirm`/enquiry test. If `get_tenant_db` yields (generator) rather than context-manages, use a dependency override or mock `__next__` accordingly.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py::test_confirm_line_costing_persists_pcts -v`
Expected: PASS (adjust the mock to the repo's `get_tenant_db` pattern until green)

- [ ] **Step 5: Commit**

```bash
git add src/sales/enquiry.py src/test/test_enquiry_costing_margin.py
git commit -m "feat(enquiry): confirm_line_costing accepts + persists overhead_pct/margin_pct"
```

---

### Task 4: Enquiry read + board queries surface the % and costed-count

**Files:**
- Modify: `src/sales/enquiry_query.py` — `get_enquiry_dtl_by_id_query()` (~line 268), `get_enquiry_board_query()` (~line 112)
- Test: `src/test/test_enquiry_costing_margin.py` (append; string-contains assertions on the query SQL)

**Interfaces:**
- Produces: enquiry line dicts include `overhead_pct`, `margin_pct`, `sell_price_per_unit`; board card dicts include `costed_line_count`.

- [ ] **Step 1: Add columns to the line read query**

In `get_enquiry_dtl_by_id_query()` SELECT (`enquiry_query.py`), after `sed.confirmed_cost_per_unit,` add:

```sql
        sed.overhead_pct,
        sed.margin_pct,
        CASE
            WHEN sed.confirmed_cost_per_unit IS NOT NULL
                 AND sed.overhead_pct IS NOT NULL
                 AND sed.margin_pct IS NOT NULL
            THEN sed.confirmed_cost_per_unit
                 * (1 + sed.overhead_pct/100)
                 * (1 + sed.margin_pct/100)
            ELSE NULL
        END AS sell_price_per_unit,
```

- [ ] **Step 2: Add costed_line_count to the board query**

In `get_enquiry_board_query()`, next to the existing `line_count` subquery (`enquiry_query.py:153-158`), add:

```sql
        (
            SELECT COUNT(1)
            FROM sales_enquiry_dtl AS sed2
            WHERE sed2.sales_enquiry_id = se.sales_enquiry_id
                AND sed2.active = 1
                AND sed2.cost_snapshot_id IS NOT NULL
                AND sed2.overhead_pct IS NOT NULL
                AND sed2.margin_pct IS NOT NULL
        ) AS costed_line_count,
```

- [ ] **Step 3: Write the failing test**

Append to `src/test/test_enquiry_costing_margin.py`:

```python
from src.sales.enquiry_query import get_enquiry_dtl_by_id_query, get_enquiry_board_query


def test_line_query_exposes_sell_price():
    sql = str(get_enquiry_dtl_by_id_query())
    assert "overhead_pct" in sql and "margin_pct" in sql
    assert "sell_price_per_unit" in sql


def test_board_query_exposes_costed_count():
    assert "costed_line_count" in str(get_enquiry_board_query())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py -k "query" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sales/enquiry_query.py src/test/test_enquiry_costing_margin.py
git commit -m "feat(enquiry): expose overhead/margin/sell on line read and costed count on board"
```

---

### Task 5: Gate the COSTING_REVIEW → QUOTATION forward on all-lines-done

**Files:**
- Modify: `src/sales/enquiry_query.py` (new `get_enquiry_costing_pending_query()`), `src/sales/enquiry.py` (`move_stage`, ~line 1355 after `validate_transition`)
- Test: `src/test/test_enquiry_costing_margin.py` (append)

**Interfaces:**
- Consumes: `STAGE_COSTING_REVIEW`, `ACTION_FORWARD` (verify imported in `enquiry.py`).
- Produces: `get_enquiry_costing_pending_query()` → rows of not-done active lines; `move_stage` returns 400 with pending `enquiry_dtl_id`s when forwarding out of COSTING_REVIEW with incomplete lines.

- [ ] **Step 1: Add the pending-lines query**

In `src/sales/enquiry_query.py`:

```python
def get_enquiry_costing_pending_query():
    """Active enquiry lines NOT fully costed+priced (block Costing Complete).

    A line is done when cost_snapshot_id, overhead_pct and margin_pct are all
    set. Free-text/new-item lines (item_id IS NULL) can never be costed, so
    they are pending too. Binds: :sales_enquiry_id."""
    sql = """SELECT sed.enquiry_dtl_id, sed.item_id
    FROM sales_enquiry_dtl AS sed
    WHERE sed.sales_enquiry_id = :sales_enquiry_id
        AND sed.active = 1
        AND (
            sed.item_id IS NULL
            OR sed.cost_snapshot_id IS NULL
            OR sed.overhead_pct IS NULL
            OR sed.margin_pct IS NULL
        )
    ORDER BY sed.enquiry_dtl_id;"""
    return text(sql)
```

- [ ] **Step 2: Enforce the gate in move_stage**

In `src/sales/enquiry.py`, import the new query (add to the existing `from src.sales.enquiry_query import (...)` block):

```python
    get_enquiry_costing_pending_query,
```

Then in `move_stage`, immediately after the `validate_transition(...)` call (~line 1355) add:

```python
        # Costing completeness gate: leaving COSTING_REVIEW requires every active
        # line to be fully costed + priced (design 2026-07-16, D5).
        if action == ACTION_FORWARD and current_stage_code == STAGE_COSTING_REVIEW:
            pending = db.execute(
                get_enquiry_costing_pending_query(),
                {"sales_enquiry_id": sales_enquiry_id},
            ).fetchall()
            if pending:
                ids = ", ".join(str(dict(r._mapping)["enquiry_dtl_id"]) for r in pending)
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Costing is not complete — confirm cost and set overhead% + "
                        f"margin% (create the item + BOM for new-item lines) for line(s): {ids}"
                    ),
                )
```

(`STAGE_COSTING_REVIEW` and `ACTION_FORWARD` are already imported in `enquiry.py`; verify and add if missing.)

- [ ] **Step 3: Write the failing test**

Append to `src/test/test_enquiry_costing_margin.py`:

```python
from src.sales.enquiry_query import get_enquiry_costing_pending_query


def test_costing_pending_query_flags_unpriced():
    sql = str(get_enquiry_costing_pending_query())
    assert "overhead_pct IS NULL" in sql and "margin_pct IS NULL" in sql
    assert "item_id IS NULL" in sql


@patch("src.sales.enquiry.get_current_user_with_refresh", return_value={"user_id": 1})
@patch("src.sales.enquiry.get_tenant_db")
def test_forward_blocked_when_lines_pending(mock_db, _auth):
    session = MagicMock()
    state_row = MagicMock()
    state_row._mapping = {"stage_code": "COSTING_REVIEW", "current_stage_id": 2,
                          "hold_flag": 0, "status_id": 3}
    pending = MagicMock(); pending._mapping = {"enquiry_dtl_id": 5, "item_id": 3}
    session.execute.return_value.fetchone.return_value = state_row
    session.execute.return_value.fetchall.return_value = [pending]
    mock_db.return_value.__enter__.return_value = session
    mock_db.return_value.__exit__.return_value = False

    resp = client.post("/api/salesEnquiry/move_stage",
                       json={"sales_enquiry_id": 9, "action": "FORWARD", "to_stage_code": "QUOTATION"})
    assert resp.status_code == 400
    assert "Costing is not complete" in resp.json()["detail"]
```

Note: align the state-mock with `fetch_enquiry_flow_state` in `enquiry.py` (wraps `get_enquiry_flow_state_query`); copy field names from an existing `move_stage` test if one exists.

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py -k "pending or blocked" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sales/enquiry_query.py src/sales/enquiry.py src/test/test_enquiry_costing_margin.py
git commit -m "feat(enquiry): block COSTING_REVIEW->QUOTATION until all lines costed+priced"
```

---

### Task 6: Quotation prefill carries overhead% + margin% from the enquiry

**Files:**
- Modify: `src/sales/` — the query behind `GET QUOTATION_ENQUIRY_LINES` (grep for `confirmed_cost_per_unit` in `src/sales/quotation*.py` / `src/sales/query.py`; it is the `fetchEnquiryLinesForQuotation` source)
- Modify (FE): `vowerp3ui/src/app/dashboardportal/sales/quotation/createQuotation/page.tsx` — seed `overhead_pct`/`margin_pct` when mapping prefill lines
- Test: `src/test/test_enquiry_costing_margin.py` (append string assertion)

**Interfaces:**
- Consumes: `sales_enquiry_dtl.overhead_pct`, `margin_pct` (Task 1).
- Produces: quotation-enquiry-lines response includes `overhead_pct`, `margin_pct`; `insert_sales_quotation_dtl` (already binds both) persists them.

- [ ] **Step 1: Add the columns to the prefill query**

Grep: `grep -rn "confirmed_cost_per_unit" src/sales/*.py | grep -i quotation` to find the quotation-enquiry-lines SELECT. In that SELECT add `sed.overhead_pct,` and `sed.margin_pct,` alongside `sed.confirmed_cost_per_unit`.

- [ ] **Step 2: Seed them on the FE quotation prefill**

In `createQuotation/page.tsx`, where enquiry lines map into quotation line state (search `confirmed_cost_per_unit` / `base_cost`), set `overhead_pct: line.overhead_pct ?? 0` and `margin_pct: line.margin_pct ?? 0` so the existing rate formula (`base_cost*(1+oh/100)*(1+margin/100)`) prefills. Keep the fields editable (D4).

- [ ] **Step 3: Write the failing test**

Append to `src/test/test_enquiry_costing_margin.py` — assert the located query function exposes the columns (replace the import + function name with the actual one found in Step 1):

```python
def test_quotation_prefill_carries_pcts():
    from src.sales.query import get_enquiry_lines_for_quotation_query  # adjust to actual module/name
    sql = str(get_enquiry_lines_for_quotation_query())
    assert "overhead_pct" in sql and "margin_pct" in sql
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py::test_quotation_prefill_carries_pcts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sales/ src/test/test_enquiry_costing_margin.py
git commit -m "feat(quotation): prefill overhead/margin from the enquiry line"
```

---

### Task 7: Frontend service types + confirm signature

**Files:**
- Modify: `vowerp3ui/src/utils/enquiryService.ts`

**Interfaces:**
- Produces: `EnquiryLine` gains `overhead_pct`, `margin_pct`, `sell_price_per_unit`; `EnquirySourceLine` gains `overhead_pct`, `margin_pct`; `confirmLineCosting(enquiry_dtl_id, bom_hdr_id, overhead_pct?, margin_pct?)`.

- [ ] **Step 1: Extend the types**

In `EnquiryLine` (after `confirmed_cost_per_unit`) and `EnquirySourceLine` (after `confirmed_cost_per_unit`) add:

```ts
	overhead_pct?: number | null;
	margin_pct?: number | null;
	sell_price_per_unit?: number | null;   // EnquiryLine only (computed server-side)
```

- [ ] **Step 2: Extend confirmLineCosting**

Replace the `confirmLineCosting` function:

```ts
export async function confirmLineCosting(
	enquiry_dtl_id: number,
	bom_hdr_id: number,
	overhead_pct?: number | null,
	margin_pct?: number | null,
) {
	return postJson<{ status: string; message?: string; data?: Record<string, unknown> }>(
		apiRoutesPortalMasters.SALES_ENQUIRY_CONFIRM_LINE_COSTING,
		"POST",
		{ enquiry_dtl_id, bom_hdr_id, overhead_pct: overhead_pct ?? null, margin_pct: margin_pct ?? null },
		"Failed to confirm costing"
	);
}
```

- [ ] **Step 3: Typecheck**

Run (from `c:/code/vowerp3ui`): `npx tsc --noEmit` (or the repo's lint/build). Expected: no new errors from this file.

- [ ] **Step 4: Commit**

```bash
git -C c:/code/vowerp3ui add src/utils/enquiryService.ts
git -C c:/code/vowerp3ui commit -m "feat(enquiry-ui): service types + confirmLineCosting overhead/margin args"
```

---

### Task 8: Costing Review — per-line overhead%/margin% + sell preview + Done chips

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/BomCosting/costingReview/page.tsx`

**Interfaces:**
- Consumes: `confirmLineCosting(..., overhead_pct, margin_pct)` (Task 7); line fields `overhead_pct`, `margin_pct`, `sell_price_per_unit`, `cost_snapshot_id` (Task 4).

- [ ] **Step 1: Add OH%/margin% inputs + sell preview to ConfirmCostingDialog**

In `ConfirmCostingDialog`, add state `const [oh, setOh] = React.useState<string>(""); const [margin, setMargin] = React.useState<string>("");` seeded from `line.overhead_pct`/`line.margin_pct` in the load effect. Add two `TextField type="number"` inputs (Overhead %, Margin %) below the version select, and a computed preview:

```tsx
{selected !== "" && oh !== "" && margin !== "" ? (() => {
	const base = versions.find(v => v.bom_hdr_id === selected)?.cost_per_unit ?? 0;
	const sell = Number(base) * (1 + Number(oh)/100) * (1 + Number(margin)/100);
	return <Typography variant="body2">Sell / unit: ₹{sell.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</Typography>;
})() : null}
```

Update `handleConfirm` to require oh & margin and pass them: `await confirmLineCosting(line.enquiry_dtl_id, Number(selected), Number(oh), Number(margin));`. Disable Confirm unless version + oh + margin set.

- [ ] **Step 2: Line status chip → Costed/Priced/Done**

In the expanded lines table "Cost Basis" cell, replace the single chip with:

```tsx
{line.cost_snapshot_id && line.overhead_pct != null && line.margin_pct != null ? (
	<Chip size="small" color="success" label={line.sell_price_per_unit != null
		? `Done · ₹${Number(line.sell_price_per_unit).toLocaleString("en-IN")}/unit` : "Done"} />
) : line.cost_snapshot_id ? (
	<Chip size="small" color="warning" label="Costed · price pending" />
) : (
	<Chip size="small" variant="outlined" label="Pending" />
)}
```

- [ ] **Step 3: Surface the completion gate on "Costing Done → Sales"**

The button already calls `moveEnquiryStage({... action:"FORWARD", to_stage_code:"QUOTATION" ...})` and sets `errorMessage` on `error` — Task 5's 400 detail flows through. Verify it renders. Add a header count chip for the expanded enquiry: `Costed {lines.filter(done).length}/{lines.length}`.

- [ ] **Step 4: Verify in browser (dev3)**

Run vowerp3ui dev server; open Costing Review; confirm a line with OH%+margin%; see sell preview + Done chip; try Costing Done with one line unpriced → see the 400 message. (Full flow in Task 11.)

- [ ] **Step 5: Commit**

```bash
git -C c:/code/vowerp3ui add src/app/dashboardportal/BomCosting/costingReview/page.tsx
git -C c:/code/vowerp3ui commit -m "feat(costing-review): per-line overhead/margin + sell preview + done chips"
```

---

### Task 9: Flow Board — costed X/Y + Costing ✓

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/sales/enquiry/board/page.tsx`
- Modify: `vowerp3ui/src/utils/enquiryService.ts` (`EnquiryBoardStage.enquiries[]` item type += `costed_line_count?`, `line_count?`)

**Interfaces:**
- Consumes: board card `costed_line_count`, `line_count` (Task 4).

- [ ] **Step 1: Add the fields to the board card type**

In `enquiryService.ts`, extend the `EnquiryBoardStage.enquiries` element type with `costed_line_count?: number; line_count?: number;`.

- [ ] **Step 2: Render the costed chip**

In `board/page.tsx`, inside the card chip row, add:

```tsx
{Number(card.line_count) > 0 ? (
	<Chip size="small"
		color={Number(card.costed_line_count) >= Number(card.line_count) ? "success" : "default"}
		variant="outlined"
		label={Number(card.costed_line_count) >= Number(card.line_count)
			? "Costing ✓"
			: `Costed ${card.costed_line_count ?? 0}/${card.line_count}`} />
) : null}
```

- [ ] **Step 3: Verify in browser**

Board shows "Costed 1/2" for a partially-costed COSTING_REVIEW enquiry, "Costing ✓" once complete/forwarded.

- [ ] **Step 4: Commit**

```bash
git -C c:/code/vowerp3ui add src/app/dashboardportal/sales/enquiry/board/page.tsx src/utils/enquiryService.ts
git -C c:/code/vowerp3ui commit -m "feat(enquiry-board): show per-enquiry costed count / Costing done badge"
```

---

### Task 10: Cost sheet base-only totals + drop overhead type + enquiry chip

**Files:**
- Modify: `vowerp3ui/src/app/dashboardportal/BomCosting/bomCosting/costSheet/page.tsx` + `_components/CostEntrySummaryBar.tsx`
- Modify: `vowerp3ui/src/app/dashboardportal/BomCosting/costElementMaster/_components/CostElementForm.tsx`
- Modify: `vowerp3ui/src/app/dashboardportal/sales/enquiry/createEnquiry/page.tsx`

**Interfaces:** none new (display-only).

- [ ] **Step 1: Cost sheet total = material + conversion**

In `costSheet/page.tsx`, change `const totalCost = summaryTotals.material + summaryTotals.conversion + summaryTotals.overhead;` to:

```tsx
	const totalCost = summaryTotals.material + summaryTotals.conversion;
```

In `CostEntrySummaryBar.tsx`, render overhead as an "(excluded from total)" reference item rather than a summand (relabel its tile; keep showing the figure).

- [ ] **Step 2: Drop overhead from the new-element type picker**

In `CostElementForm.tsx` change `const ELEMENT_TYPES = ["material", "conversion", "overhead"];` to:

```tsx
const ELEMENT_TYPES = ["material", "conversion"];
```

(Existing overhead elements still load/display in edit mode — the `element_type` field is disabled on edit.)

- [ ] **Step 3: Show OH%/margin%/sell on the enquiry line chip**

In `createEnquiry/page.tsx` "Cost Basis" cell, when `detailLine?.cost_snapshot_id`, also show OH%/margin%/sell if present:

```tsx
{detailLine?.overhead_pct != null && detailLine?.margin_pct != null ? (
	<Typography variant="caption" color="text.secondary" display="block">
		OH {detailLine.overhead_pct}% · Margin {detailLine.margin_pct}%
		{detailLine.sell_price_per_unit != null ? ` · ₹${Number(detailLine.sell_price_per_unit).toLocaleString("en-IN")}/unit` : ""}
	</Typography>
) : null}
```

- [ ] **Step 4: Verify in browser**

Cost sheet total no longer includes overhead; new cost element form offers only material/conversion; enquiry view shows OH/margin/sell on a priced line.

- [ ] **Step 5: Commit**

```bash
git -C c:/code/vowerp3ui add src/app/dashboardportal/BomCosting/bomCosting/costSheet/page.tsx src/app/dashboardportal/BomCosting/bomCosting/costSheet/_components/CostEntrySummaryBar.tsx src/app/dashboardportal/BomCosting/costElementMaster/_components/CostElementForm.tsx src/app/dashboardportal/sales/enquiry/createEnquiry/page.tsx
git -C c:/code/vowerp3ui commit -m "feat(bomcosting-ui): base-only totals, drop overhead element type, enquiry price chip"
```

---

### Task 11: Tenant rollout + real-usage dev3 browser test

**Files:** none (ops + QA). Uses the migration from Task 1.

- [ ] **Step 1: Run all new backend tests**

Run: `source .venv/Scripts/activate && pytest src/test/test_enquiry_costing_margin.py -v`
Expected: all PASS. (Pre-existing unrelated failures in the wider suite are out of scope — see memory `project_sync_def_conversion`.)

- [ ] **Step 2: Apply the migration to sls (and any other live tenant) BEFORE deploying code**

Repeat Task 1 Step 5 with `database='sls'`. Confirm `DESCRIBE sales_enquiry_dtl;` shows the new columns and `vw_bom_cost_summary` total excludes overhead. Record which tenants were migrated.

- [ ] **Step 3: Real-usage end-to-end test on dev3 (portal-ui-flow-tester)**

Drive the browser as the dev3 Empire/Factory test user:
1. BOM Costing → create/open a cost sheet for an item; enter material + conversion leaf amounts (and one overhead element); Compute Rollup. Confirm total = material + conversion (overhead shown, excluded); note cost/unit.
2. Sales Enquiry → note an enquiry with that item; Open; approve; FORWARD to COSTING_REVIEW.
3. Costing Review → expand; per line Confirm Costing: pick version, enter overhead% + margin%; verify sell preview; save → line shows Done chip; board shows "Costed 1/1".
4. With a 2-line enquiry, leave one line unpriced → "Costing Done → Sales" must show the 400 (pending line ids); board shows "Costed 1/2".
5. Complete all lines → Costing Done → Sales → enquiry in QUOTATION; board "Costing ✓".
6. Create Quotation from the enquiry → verify overhead%/margin% prefilled and still editable; rate = base × (1+oh/100) × (1+margin/100).
7. Deliberately bad input: negative overhead% → 400; free-text/new-item line → confirm rejects ("create the item + BOM first").
Fix any bug found (root cause), re-run the failing step.

- [ ] **Step 4: Final commit (if fixes were made)**

```bash
git add -A && git commit -m "fix(enquiry-costing): address issues found in dev3 real-usage test"
```

---

## Self-Review

- **Spec coverage:** D1 → Tasks 1,3,4,7,8; D2 → Tasks 1,2,10; D3 → Task 8 preview + Task 4 formula (markup on cost); D4 → Task 6; D5 (per-line, reuse) → Tasks 4,5,8,9. Migration/rollout → Tasks 1,11. Testing → each task + Task 11. Spec §6–§9 all mapped.
- **Placeholders:** none — every code step carries real code; Tasks 6 requires a grep to locate one query name (instructed), acceptable.
- **Type consistency:** `overhead_pct`/`margin_pct`/`sell_price_per_unit` names identical across ORM, SQL, service types, UI; `confirmLineCosting` signature consistent between Task 7 (def) and Task 8 (call); `compute_base_total` consistent Task 2.
- **Risk:** only new DB writes are two nullable columns; back-compatible. Tenant-ordering risk covered in Task 11 Step 2 (migrate before deploy).
