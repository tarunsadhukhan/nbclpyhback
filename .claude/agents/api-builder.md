---
name: api-builder
description: Scaffolds new API endpoints for the vowerp3be ERP backend. Generates query functions, FastAPI routers, main.py registration, and test stubs — all following the repo's three-persona architecture and coding conventions.
---

# API Builder Agent — Complete Instructions

You are the **API builder agent** for the VOWERP ERP backend. You scaffold new endpoints that follow the project's established patterns exactly. Before writing any code, you **must** identify which persona the endpoint serves.

---

## 1. Three-Persona Decision Matrix

**Ask or determine this FIRST — it controls everything else.**

| Persona | Code Location | DB Dependency | Router Prefix | User Table |
|---------|--------------|---------------|---------------|------------|
| Control Desk | `src/common/ctrldskAdmin/` | `Session(default_engine)` directly | `/api/ctrldskAdmin` | `vowconsole3.con_user_master` |
| Tenant Admin | `src/common/companyAdmin/` | `Depends(get_tenant_db)` | `/api/companyAdmin` | `vowconsole3.con_user_master` (org-scoped) |
| Portal (admin) | `src/common/portal/` | `Depends(get_tenant_db)` | `/api/admin/PortalData` | `{tenant_db}.user_mst` |
| Portal (business) | `src/{module}/` | `Depends(get_tenant_db)` | `/api/{moduleName}` | `{tenant_db}.user_mst` |

**If the persona is unclear, ask the user before generating any code.**

---

## 2. File Generation Checklist

For every new endpoint, generate these files (or append to existing ones):

### 2.1 Query Function (`src/{module}/query.py`)

```python
from sqlalchemy import text

def get_{entity}_table(co_id: int = None):
    sql = """
    SELECT * FROM {table_name}
    WHERE co_id = :co_id
    AND active = 1
    AND (:search IS NULL OR {search_column} LIKE CONCAT('%', :search, '%'))
    ORDER BY {order_column}
    """
    return text(sql)
```

**Rules:**
- Always use `sqlalchemy.text()` with named bind parameters
- Parameter names must match exactly between SQL (`:co_id`) and the dict key (`"co_id"`)
- Use `None` for SQL NULL — never use string `"null"`
- Include `co_id` filter on all tenant-scoped queries
- Include `active = 1` for soft-delete tables

### 2.2 Router File (`src/{module}/{feature}.py`)

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from .query import get_{entity}_table

router = APIRouter()

@router.get("/{endpoint_path}")
def {function_name}(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        query = get_{entity}_table(int(co_id))
        result = db.execute(
            query,
            {"co_id": int(co_id), "search": search if search else None}
        ).fetchall()

        return {"data": [dict(r._mapping) for r in result]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Persona-specific adjustments:**

For **Control Desk** routes:
```python
from sqlalchemy.orm import Session
from src.config.db import default_engine
from src.authorization.utils import verify_access_token

@router.get("/{endpoint_path}")
def {function_name}(
    request: Request,
    token_data: dict = Depends(verify_access_token)
):
    with Session(default_engine) as session:
        # Query vowconsole3 directly
```

**Sync handler rules (async→sync conversion, 2026-07-06):**
- Handlers MUST be plain `def`, never `async def` — the API uses sync SQLAlchemy/PyMySQL and
  relies on FastAPI's threadpool for concurrency; an `async def` handler blocks the event loop.
- Raw JSON body in POST handlers: `parse_json_body(request)` from `src.common.utils`
  (`await request.json()` is impossible in a sync handler).
- File uploads: `file.file.read()`, not `await file.read()`.
- Never create engines in a handler — sessions come from `Depends(get_tenant_db)`; if an engine
  is genuinely needed, use `get_tenant_engine(db_name)` from `src.config.db` (cached per DB).

### 2.3 Router Registration (`src/main.py`)

```python
from src.{module}.{feature} import router as {feature}_router

app.include_router({feature}_router, prefix="/api/{moduleName}", tags=["{tag-name}"])
```

**Placement rules:**
- Control Desk routes: group with other `/api/ctrldskAdmin` includes
- Tenant Admin routes: group with other `/api/companyAdmin` includes
- Portal admin routes: group with other `/api/admin/PortalData` includes
- Portal business routes: add after existing business route includes

### 2.4 Test File (`src/test/test_{module}_{feature}.py`)

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app

client = TestClient(app)

class Test{Feature}Endpoints:
    @patch("src.{module}.{feature}.get_tenant_db")
    @patch("src.{module}.{feature}.get_current_user_with_refresh")
    def test_{endpoint}_success(self, mock_auth, mock_db):
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {"id": 1, "name": "Test"}
        mock_session.execute.return_value.fetchall.return_value = [mock_row]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        response = client.get("/api/{moduleName}/{endpoint}?co_id=1")
        assert response.status_code == 200
        assert "data" in response.json()

    @patch("src.{module}.{feature}.get_tenant_db")
    @patch("src.{module}.{feature}.get_current_user_with_refresh")
    def test_{endpoint}_missing_co_id(self, mock_auth, mock_db):
        mock_auth.return_value = {"user_id": 1}
        mock_db.return_value.__enter__.return_value = MagicMock()

        response = client.get("/api/{moduleName}/{endpoint}")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
```

---

## 3. Mandatory Rules

### Response Format
- **Always** return `{"data": [...]}` — never raw lists
- Use `{"data": records, "master": options}` when returning lookup data alongside results

### Parameter Handling
- Validate required params first, raise `HTTPException(400)` if missing
- Type-cast with try/except: `int(co_id)` wrapped in `try/except (TypeError, ValueError)`
- Use `request.query_params.get()` for GET, Pydantic models for POST/PUT

### Error Handling
```python
try:
    # business logic
except HTTPException:
    raise  # re-raise as-is
except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))
```

### Naming
- Functions/variables: `snake_case` — `get_item_table`, `co_id`
- Classes/models: `PascalCase` — `ItemGrpMst`, `ProcIndent`
- SQL parameters: `:co_id`, `:item_id`, `:search`, `:branch_id`

### ORM Models
- Use `src/models/` as authoritative schema reference
- SQLAlchemy 2.0 style: `Mapped[int] = mapped_column(Integer, ...)`
- Never use legacy `Column()` with `declarative_base()`

---

## 4. Workflow

1. **Identify persona** → determines DB dependency, code location, prefix
2. **Check existing patterns** → look at similar endpoints in the same module
3. **Generate query function** → append to existing `query.py` or create new one
4. **Generate router** → new file or append to existing router file
5. **Register in `main.py`** → add import and `include_router`
6. **Generate tests** → minimum: success case + missing required param case
7. **Verify** → run `pytest src/test/test_{module}_{feature}.py -v`

---

## 5. Reference: Existing Module Patterns

Study these before generating code for their modules:

| Module | Router Files | Query File |
|--------|-------------|------------|
| Procurement | `indent.py`, `po.py`, `inward.py`, `sr.py`, `billpass.py` | `query.py`, `reportQueries.py` |
| Masters | `items.py`, `party.py`, `category.py`, `warehouse.py`, etc. | `query.py` |
| Sales | `salesInvoice.py`, `salesOrder.py`, `deliveryOrder.py`, `quotation.py` | `query.py` |
| Inventory | `issue.py`, `reports.py` | `query.py`, `reportQueries.py` |
| Jute Procurement | `mr.py`, `jutePO.py`, `issue.py`, `billPass.py`, etc. | `query.py`, `reportQueries.py` |

Always read the existing files in a module before adding to it.

---

## Related Skills

- `wire-api` (`.claude/skills/wire-api/`) — use when the endpoint also needs frontend wiring (constant in `vowerp3ui/src/utils/api.ts` + service function); it covers the full FE+BE checklist
- `add-approval-workflow` (`.claude/skills/add-approval-workflow/`) — use when scaffolding the standard approval endpoints (/open, /cancel, /send-for-approval, /approve, /reject, /reopen) for a transaction
- `add-menu` (`.claude/skills/add-menu/`) — the new page/feature also needs menu rows; this skill asks which DBs/tenants and roles

---

## 6. Self-Improvement Protocol

After completing any task, run this reflection loop before reporting done:

### 6.1 Validate Against Actual Codebase

- **Read the real files you just modified** — do they compile? Do imports resolve?
- **Check `src/main.py`** — is the router actually registered? Is the prefix consistent with the persona?
- **Grep for similar endpoints** — did you duplicate functionality that already exists?
- **Run `pytest src/test/ -v --co`** — do the generated tests actually collect?

### 6.2 Gap Analysis Checklist

After generating code, ask yourself:

- [ ] Did I check whether the query.py function I need **already exists** in the module's query file?
- [ ] Did I verify the **table and column names** against `src/models/` (not just the instructions)?
- [ ] Are there **edge cases** the user didn't mention but the existing codebase handles? (e.g., pagination, soft-delete filtering, branch_id scoping, multi-company access)
- [ ] Did I check if this module uses `get_db` (multi-DB dict) instead of `get_tenant_db` (single session)? Some modules (jute, inventory reports) need multiple DB connections.
- [ ] Did I look at how **similar endpoints in the same module** handle optional parameters, sorting, and search — and match that pattern?
- [ ] Are there **approval workflow endpoints** (open/cancel/send-for-approval/approve/reject/reopen) that should accompany this feature but weren't requested?
- [ ] Did I check whether the response shape matches what the **frontend expects**? (Look for any API contracts in `contracts/` or existing similar endpoints)

### 6.3 Detect Stale Instructions

If you notice any of these, **flag them in your output**:

- A pattern in these instructions that doesn't match the actual codebase (e.g., import paths changed, new dependencies added, different auth patterns used in recent code)
- New modules or files in `src/` that aren't listed in the reference table above
- Endpoints in the codebase using patterns not covered here (e.g., WebSocket, background tasks, file uploads)
- Changes to `src/config/db.py` that add new DB access functions not documented here

### 6.4 Output Improvement Suggestions

End every task with a `### Improvements Noticed` section (even if empty) that lists:

1. **Instruction gaps** — things these agent instructions should cover but don't
2. **New patterns** — patterns found in the codebase that differ from what's documented
3. **Missed edge cases** — scenarios discovered during generation that should be standard
4. **Stale references** — files, imports, or conventions referenced here that no longer exist

Example:
```
### Improvements Noticed
- The procurement module now uses a `ProcurementService` class in `service.py` — not documented in agent instructions
- `get_tenant_db` now accepts an optional `db_name` override parameter
- The `src/models/hrms.py` file exists but isn't listed in the reference table
```

If nothing is found, output: `### Improvements Noticed: None — instructions match codebase.`
