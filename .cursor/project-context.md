# Project Context - vowerp3be

> **Note:** This file provides additional context for Cursor AI. Keep it updated as your project evolves.

## Business Domain

**What this project does:**
- FastAPI backend for multi-tenant ERP system
- Supports procurement, master data, and reporting modules
- Each tenant has a separate MySQL database
- JWT-based authentication with refresh tokens

**Key Modules:**
- **Authorization:** Login, JWT tokens, user validation
- **Masters:** Items, branches, departments, projects, etc.
- **Procurement:** Indents, purchase orders, etc.
- **Common:** Shared utilities split by persona (companyAdmin, ctrldeskAdmin, portal)

## Technical Stack

- **Framework:** FastAPI
- **Database:** MySQL (multi-tenant, separate DB per company)
- **ORM:** SQLAlchemy (mix of ORM and raw SQL Text queries)
- **Auth:** JWT tokens with refresh mechanism
- **Validation:** Pydantic schemas

## Critical Requirements

### 1. Multi-Tenancy
- **Always** use `get_tenant_db()` to get the tenant-specific database session
- Tenant DB name is derived from request headers:
  - `subdomain` header (preferred)
  - `x-forwarded-host`
  - `referer` header
- Many endpoints require `co_id` as query parameter - validate early (return 400 if missing)

### 2. Database Access Patterns

**Using ORM Models:**
```python
from src.masters.models import Item
db.query(Item).filter(Item.co_id == co_id).all()
```

**Using Raw SQL Text Queries:**
```python
from src.masters.query import get_item_table
q = get_item_table(co_id)
rows = db.execute(q, {"co_id": int(co_id), "search": search_param}).fetchall()
data = [dict(r._mapping) for r in rows]
```

### 3. SQL Query Conventions
- Use named bind parameters: `:co_id`, `:item_id`, `:search`
- Pass `None` (not `"null"`) for SQL NULL values
- Query functions return `sqlalchemy.text()` objects
- Always execute with parameter dict matching named binds

### 4. Authentication
- Use `Depends(get_current_user_with_refresh)` for protected endpoints
- Refresh tokens stored in default DB (`con_user_master` table)
- Cookie name: `access_token`
- Production cookie domain: `.vowerp.co.in` when `ENV=production`

## Code Organization

### Directory Structure
```
src/
├── main.py                 # FastAPI app, mounts routers
├── config/
│   └── db.py              # Database engines, tenant resolution
├── authorization/         # Auth flows, JWT, user validation
├── masters/               # Master data APIs
│   ├── models.py         # SQLAlchemy ORM models
│   ├── query.py          # Raw SQL Text queries
│   └── items.py          # Item master router
├── procurement/           # Procurement module
│   ├── query.py          # SQL queries
│   ├── models.py         # ORM models (optional)
│   ├── schemas.py        # Pydantic schemas (optional)
│   └── indent.py         # Indent router
└── common/               # Shared utilities by persona
    ├── companyAdmin/
    ├── ctrldeskAdmin/
    └── portal/
```

### Module Pattern
When creating a new module (e.g., `inventory/`):
1. Create `query.py` for SQL queries
2. Optionally add `models.py` for ORM models
3. Optionally add `schemas.py` for Pydantic schemas
4. Create router file(s) (e.g., `stock.py`)
5. Mount router in `src/main.py`

## Common Patterns

### Endpoint Pattern
```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

router = APIRouter(prefix="/api/items", tags=["items"])

@router.get("/list")
async def get_items(
    co_id: int = Query(..., description="Company ID"),
    search: str = Query("", description="Search term"),
    db: Session = Depends(get_tenant_db),
    current_user = Depends(get_current_user_with_refresh)
):
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")
    
    q = get_item_table(co_id)
    rows = db.execute(q, {"co_id": co_id, "search": search}).fetchall()
    return [dict(r._mapping) for r in rows]
```

### Query Function Pattern
```python
# In query.py
def get_item_table(co_id: int) -> Text:
    return text("""
        SELECT item_id, item_code, item_name
        FROM con_item_master
        WHERE co_id = :co_id
        AND (:search = '' OR item_name LIKE :search)
    """)
```

### Using Query Function
```python
# In router file
from src.masters.query import get_item_table

q = get_item_table(co_id)
rows = db.execute(q, {"co_id": int(co_id), "search": f"%{search}%"}).fetchall()
data = [dict(r._mapping) for r in rows]
```

## Backend Implementation Patterns In Practice

- **Router files mirror business domains.** For example, `src/procurement/po.py` and `src/masters/items.py` each expose an `APIRouter`, define dependencies (`Request`, `Session = Depends(get_tenant_db)`, `token_data = Depends(get_current_user_with_refresh)`), and group related helper functions such as `format_po_no` or `sanitize_int`.
- **SQL lives next to the domain.** Every module has a `query.py` (e.g., `src/procurement/query.py`) that only returns `sqlalchemy.text()` clauses. Routers import these builders, execute them with `db.execute(query, params)`, and translate rows via `dict(row._mapping)`.
- **Mix of ORM and text queries.** CRUD-style operations (e.g., item creation in `src/masters/items.py`) use SQLAlchemy models, while reporting/list endpoints stay on raw SQL for predictable SQL and easier reuse across tenants.
- **Result shaping happens post-query.** Routes normalize values (dates via `.isoformat()`, decimals to `float`, always include keys like `po_value`, etc.) to keep the response contract stable across callers.
- **Logging & error handling.** Routers configure `logger = logging.getLogger(__name__)` and wrap handlers in `try/except`, raising `HTTPException` for expected failures and logging unexpected ones.
- **Helper utilities are centralized.** Cross-module helpers (responses, timestamp formatting, tenant validation) reside in `src/common/utils.py`, while domain-specific helpers stay near their usage for clarity.

## Maintainability, Readability & Reusability Guidelines

### General
- Keep new routers consistent: declare `router = APIRouter(...)`, enforce `co_id` early, and always depend on `get_tenant_db` and `get_current_user_with_refresh` unless a specific endpoint is public.
- Store every new SQL snippet inside the module’s `query.py` file (even small `SELECT`s) so routers stay focused on orchestration logic.
- When reading rows, prefer `.mappings()` or `dict(row._mapping)` and normalize types before returning. This prevents frontend conditionals sprinkled across pages like `createPO`.
- Use `create_response()` from `src/common/utils.py` (or mirror its `{ "data": [...] }` contract) so all APIs share the same shape.

### Smaller Functions & Helpers
- Favor **short, pure helper functions** (≤25 lines) for repeated transforms such as input sanitization, payload flattening, or GST math. Keep them typed and side-effect free so they can be re-used in other routers or hooks (see `format_po_no()` and `calculate_gst_amounts()` in `src/procurement/po.py`).
- If the helper is domain-agnostic (dates, numbers, dict merges), move it to `src/common/utils.py`. Otherwise co-locate directly under the router and export only when another module needs it.
- Document non-obvious helper behavior with a one-line comment (e.g., why sanitization allows strings, how financial year is derived) to reduce re-implementation risk.
- Avoid nesting large helper definitions inside route handlers. Define them at module scope so they can be unit-tested and imported elsewhere.
- Reuse validation helpers such as the `sanitize_int()` pattern in `src/masters/items.py` instead of inlining ad-hoc parsing inside each endpoint. This keeps request handling predictable and readable.

### Error Handling & Transactions
- Wrap DB writes in `try/except`, call `db.rollback()` on failure, and surface meaningful HTTP status codes. Reads can re-raise `HTTPException` untouched.
- When you need cross-cutting validations (headers, tenant IDs), rely on FastAPI dependencies (`Depends`) rather than manual checks inside each handler.

### Testing & Extensibility
- Extracting reusable helpers makes it trivial to add unit tests under `src/test/` without spinning up FastAPI. Keep signatures simple (`dict` / `TypedDict` in, `dict` out) to minimize fixtures.
- Whenever a route orchestrates multiple queries, consider a lightweight service function (pure python) that the route calls. This keeps request handling thin and lets the service be reused by background tasks or scheduled jobs.

## Key Files to Reference

### When building new endpoints:
- `src/masters/items.py` - Reference implementation
- `src/masters/query.py` - SQL query examples
- `src/config/db.py` - Database connection helpers
- `src/authorization/utils.py` - Auth helpers

### When understanding tenant resolution:
- `src/config/db.py` - `get_tenant_db()` function
- Check how headers are parsed to determine tenant DB

### When working with SQL:
- `dbqueries/procurement.sql` - Table structure reference
- `dbqueries/usertables.sql` - User table structures
- `src/masters/query.py` - Query examples

## Database Conventions

### Parameter Names
Common parameter names used across queries:
- `:co_id` - Company ID
- `:item_id` - Item ID
- `:item_grp_id` - Item Group ID
- `:search` - Search term
- `:branch_id` - Branch ID
- `:dept_id` - Department ID

### NULL Handling
- Use Python `None` (not string `"null"`)
- Example: `{"item_id": None}` for SQL NULL

### Query Execution
- Always use parameter dict: `db.execute(query, {"param": value})`
- Convert results: `[dict(r._mapping) for r in rows]`

## Development Workflow

### Local Development
```bash
# Activate venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Run server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker
```bash
# Build
docker build -t vowerp-backend .

# Run
docker run -d -p 8000:8000 --env-file .env --name vowerp3be vowerp3be-docker
```

### Testing
- Use `pytest` for unit tests
- Tests in `test/` directory
- Run tests inside Docker container for consistency

## Common Gotchas

1. **Don't call `int("null")`** - Use `None` for SQL NULL
2. **Always validate `co_id`** - Return 400 if missing
3. **Use correct parameter names** - Match query bind parameters exactly
4. **Text queries need execution** - `get_item_table()` returns `text()`, must call `db.execute()`
5. **Tenant DB resolution** - Test with different headers to ensure correct DB selection
6. **Refresh token location** - Stored in default DB, not tenant DB

## When to Use ORM vs Raw SQL

### Use Raw SQL (`text()`) when:
- Complex recursive CTEs (e.g., hierarchical item groups)
- Performance-critical queries
- Existing codebase pattern uses raw SQL

### Use ORM when:
- Simple CRUD operations
- Adding new models
- Consistent with surrounding code

## API Response Patterns

### Success Response
```python
return {
    "data": [...],
    "message": "Success"
}
```

### Error Response
```python
from fastapi import HTTPException

raise HTTPException(
    status_code=400,
    detail="co_id is required"
)
```

### Setup Endpoint Response
```python
# Setup endpoints return multiple option arrays
return {
    "departments": [...],
    "projects": [...],
    "expense_types": [...],
    "item_groups": [...]
}
```

## Testing Checklist

When adding new endpoints:
- [ ] Test with valid `co_id`
- [ ] Test with missing `co_id` (should return 400)
- [ ] Test with different tenant headers (correct DB selection)
- [ ] Test with authenticated user
- [ ] Test with expired token (refresh should work)
- [ ] Test NULL parameter handling
- [ ] Test SQL injection prevention (parameterized queries)

---

**Last Updated:** 2025-11-26

