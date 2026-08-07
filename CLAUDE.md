# VoWERP3 Backend - Developer Guide for Claude

## Project Overview

VoWERP3 Backend is a **multi-tenant ERP system** built with **FastAPI** and **SQLAlchemy**. It serves a Next.js frontend (vowerp3ui) and handles procurement, inventory, sales, and jute/yarn management.

**Tech Stack:** Python 3.12+ | FastAPI 0.115.11 | SQLAlchemy 2.0.38 | MySQL/PyMySQL | JWT auth | Docker | Pytest

**Main Branch:** `main` | **Frontend:** `vowerp3ui` (sibling repo at `../vowerp3ui`)

---

## File-Path Registry

Everything discoverable from one place. Paths are repo-relative; the frontend repo is `../vowerp3ui`.

### Documentation map

| Path | Purpose |
|------|---------|
| `CLAUDE.md` | This guide |
| `DOCUMENTATION_INDEX.md` | Repo-wide index of all docs, agents, skills, tooling |
| `README.md` | Setup, Docker commands |
| `.github/copilot-instructions.md` | AI coding agent guide (patterns, pitfalls, hotspots) |
| `.github/WORKSPACE-INSTRUCTIONS.md` | Active vs legacy repos |
| `docs/procurement-inward-to-bill-pass-approval-flows.md` | Procurement approval chain deep-dive |
| `docs/GST_PROCUREMENT.md` | GST calculations in procurement |
| `docs/accounting-module-design.md` | Accounting module design |
| `docs/hrms-payroll-design.md` | HRMS payroll design |
| `docs/bom_costing_db_instructions_1.md` | BOM costing DB setup |
| `docs/TENANT_PROVISIONING.md` | New tenant provisioning |
| `docs/yarn-quality/` | Yarn-quality feature docs (index: `docs/yarn-quality/INDEX.md`) |
| `docs/winding-person-keyed-entry-spec.md` | Winding production entry — locked person-keyed (EB no) design, supersedes the machine-keyed original |
| `../vowerp3ui/docs/claude/TEAM.md` | Agent team roster + skills + team norms (cross-repo) |
| `../vowerp3ui/docs/claude/roles-and-users.md` | Users/roles/permissions across all dashboards |
| `../vowerp3ui/docs/claude/modules/{module}/` | Per-module page catalogs, backend maps, approval flows |

### Agents (`.claude/agents/`)

| Agent | Role |
|-------|------|
| `api-builder.md` | Scaffold new endpoints (persona-aware) |
| `dbmanager.md` | DB schema, ORM models, queries, dev3 tenancy rules |
| `migration-writer.md` | SQL migrations + paired ORM updates |
| `test-writer.md` | Pytest suites (mocked DB/auth) |
| `reviewer.md` | Convention review |
| `tenant-auditor.md` | Multi-tenant safety audit |
| `module-*.md` (11) | Module guides — pointers; full bodies in `../vowerp3ui/.claude/agents/` |

### Skills (`.claude/skills/`)

| Skill | Use for | Always asks |
|-------|---------|-------------|
| `add-menu` | Menu rows across the multi-level menu system | Which DBs/tenants, roles |
| `wire-api` | FE+BE endpoint wiring (most repeated process) | Persona, module, payload |
| `new-master` | New master end-to-end (DDL → ORM → CRUD → page → menu) | Fields, target DB, menu |
| `add-approval-workflow` | Standard approval lifecycle endpoints + UI bar | Transaction, levels |
| `tenant-schema-check` | Schema drift diff vs dev3 | Tenant; sync approval |
| `run-migration` | Execute migration via pymysql | **Target DB** (suggests dev3) |

### Key source files

| Path | Purpose |
|------|---------|
| `src/main.py` | All router registrations (prefix → module) |
| `src/config/db.py` | Multi-tenant DB config (`get_tenant_db`, `extract_subdomain_from_request`) |
| `src/authorization/utils.py` | JWT, token refresh, password hashing |
| `src/common/utils.py` | Shared utilities (`create_response`) |
| `src/models/` | Authoritative ORM schema (by domain) |
| `env/database.env` | DB credentials |

### Per-module entry points

| Module | BE source | Prefixes | FE pages (`../vowerp3ui/`) | Module agent |
|--------|-----------|----------|----------------------------|--------------|
| Masters | `src/masters/` | `/api/{x}Master`, `/api/hrmsMasters`, ... | `src/app/dashboardportal/masters/` | `module-masters` |
| Procurement | `src/procurement/` | `/api/procurementIndent`, `/api/procurementPO`, `/api/procurementInward`, `/api/materialInspection`, `/api/storesReceipt`, `/api/drcrNote`, `/api/billPass`, `/api/procurementReports` | `src/app/dashboardportal/procurement/` | `module-procurement` |
| Sales | `src/sales/` | `/api/salesQuotation`, `/api/salesOrder`, `/api/salesDeliveryOrder`, `/api/salesInvoice`, `/api/salesReports` | `src/app/dashboardportal/sales/` | `module-sales` |
| Jute Purchase | `src/juteProcurement/` | `/api/jutePO`, `/api/juteGateEntry`, `/api/juteMaterialInspection`, `/api/juteMR`, `/api/juteAgentMap`, `/api/juteBillPass`, `/api/juteIssue`, `/api/batchDailyAssign`, `/api/juteReports` | `src/app/dashboardportal/jutePurchase/` | `module-jute-purchase` |
| Jute Production + SQC | `src/juteProduction/`, `src/juteSQC/` | `/api/spreaderProd`, `/api/spreaderMasters`, `/api/drawingProd`, `/api/drawingMasters`, `/api/spinningProd`, `/api/spinningMasters`, `/api/juteProductionReports`, `/api/juteSQC` | `src/app/dashboardportal/juteProduction/`, `juteSQC/` | `module-jute-production` |
| Inventory | `src/inventory/` | `/api/inventoryIssue`, `/api/inventoryReports` | `src/app/dashboardportal/inventory/` | `module-inventory` |
| HRMS | `src/hrms/` | `/api/hrms` | `src/app/dashboardportal/hrms/`, `hrmsmasters/` | `module-hrms` |
| Accounting | `src/accounting/` | `/api/accounting` | `src/app/dashboardportal/accounting/` | `module-accounting` |
| BOM Costing | `src/bomcosting/` | `/api/bomCosting`, `/api/bomCostElement`, `/api/stdRateCard` | `src/app/dashboardportal/BomCosting/` | `module-bom-costing` |
| Control Desk | `src/common/ctrldskAdmin/` | `/api/ctrldskAdmin` | `src/app/dashboardctrldesk/` | `module-ctrldesk` |
| Tenant Admin | `src/common/companyAdmin/`, `src/common/portal/` | `/api/companyAdmin`, `/api/admin/PortalData` | `src/app/dashboardadmin/` | `module-tenant-admin` |

---

## Tenancy & Environments

The system is **multi-tenant**: each tenant (organisation) has its **own database** (name =
`con_org_master.con_org_shortname` = subdomain); within each tenant there are **companies
(`co_id`)** and **branches (`branch_id`)**, and portal users are scoped to combinations of both via
`user_role_map`.

```mermaid
flowchart TD
    T["Tenant / Organisation\n(own DB, e.g. dev3, sls)"] --> C["Companies (co_id)"] --> B["Branches (branch_id)"]
    B --> U["Portal users via user_role_map\n(user_id, co_id, branch_id, role_id)"]
```

- **`dev3` is the QA/dev tenant** — the default target for all new work, migrations, and testing.
- **Schema-drift rule:** production tenants may carry tables/columns dev3 lacks. When developing
  against or referencing another tenant, run the `tenant-schema-check` skill; if drift is found,
  **ask the user whether to incorporate it into dev3** — never sync silently.
- Dashboard purposes: `dashboardctrldesk` = the **VOW team's own** high-level control (vendor-internal);
  `dashboardadmin` = where **each tenant** configures companies/branches/departments/users/roles/
  approval hierarchy; `dashboardportal` = daily operations.
- Full roles/users/permissions model: `../vowerp3ui/docs/claude/roles-and-users.md`.

---

## Three-Persona Architecture (MOST IMPORTANT)

The system has **three distinct login types**, each with different databases, endpoints, and access scopes. Understanding this is critical before writing any code.

### Persona 1: VOW Admin (Control Desk) — `dashboardctrldesk`

**Purpose:** System-wide super admin managing all organizations/tenants — used by the **VOW team
itself** (vendor-internal); tenants never see this dashboard.

| Aspect | Details |
|--------|---------|
| **Login endpoint** | `POST /api/authRoutes/loginconsole` |
| **Login function** | `login_user_console()` in `src/authorization/auth.py` |
| **Database** | `vowconsole3` (default engine — the central/system database) |
| **User table** | `vowconsole3.con_user_master` |
| **Key filter** | `con_user_type = 0` AND `con_org_id IS NULL` |
| **Token payload** | `{"user_id": <id>}` |
| **Refresh token stored in** | `vowconsole3.con_user_master.refresh_token` |
| **Router prefix** | `/api/ctrldskAdmin` |
| **Code location** | `src/common/ctrldskAdmin/` (users, orgs, roles, menuportal) |
| **DB dependency** | Uses `default_engine` directly (`SessionLocal`) — **NOT** `get_tenant_db` |

**What Control Desk can do:** Manage all organizations, create tenants, system-wide role/user management, menu configuration.

### Persona 2: Tenant Admin — `dashboardadmin`

**Purpose:** Organization-level admin for a single tenant — where the tenant sets its own
configuration: companies, branches, departments, users, roles, approval hierarchy.

| Aspect | Details |
|--------|---------|
| **Login endpoint** | `POST /api/authRoutes/loginconsole` (same endpoint as Control Desk) |
| **Login function** | `login_user_console()` in `src/authorization/auth.py` |
| **Database** | `vowconsole3` (default engine) — same DB, but **scoped by org_id** |
| **User table** | `vowconsole3.con_user_master` |
| **Key filter** | `con_user_type = 1` AND `con_org_id = <specific_org_id>` |
| **Token payload** | `{"user_id": <id>}` |
| **Refresh token stored in** | `vowconsole3.con_user_master.refresh_token` |
| **Router prefix** | `/api/companyAdmin` |
| **Code location** | `src/common/companyAdmin/` (users, company, roles, branch, dept_subdept) |
| **DB dependency** | Uses `get_tenant_db` (resolves subdomain → queries `vowconsole3` scoped by org) |
| **Subdomain mapping** | `extract_subdomain_from_request()` → `con_org_master.con_org_shortname` → `con_org_id` |

**What Tenant Admin can do:** Manage companies, branches, departments, roles, and users within their organization.

### Persona 3: Tenant Portal — `dashboardportal`

**Purpose:** Day-to-day operational users (procurement, inventory, sales, etc.)

| Aspect | Details |
|--------|---------|
| **Login endpoint** | `POST /api/authRoutes/login` (DIFFERENT endpoint) |
| **Login function** | `login_user()` in `src/authorization/auth.py` |
| **Database** | **Tenant-specific DB** (e.g., `org1`, `dev3`, `sls`) — NOT vowconsole3 |
| **User table** | `{tenant_db}.user_mst` |
| **Key filter** | `email_id = :email` AND `active = TRUE` |
| **Token payload** | `{"user_id": <id>, "type": "portal"}` ← note `type` field |
| **Refresh token stored in** | `{tenant_db}.user_mst.refresh_token` |
| **Router prefix** | `/api/admin/PortalData` (admin functions) + all business routes |
| **Code location** | `src/common/portal/` (users, roles, menu, approval) + `src/masters/`, `src/procurement/`, etc. |
| **DB dependency** | Uses `get_tenant_db` → creates engine for `{subdomain}` database |
| **Access scope** | Filtered by `co_id`, `branch_id`, and `role_id` via `user_role_map` table |

**What Portal users can do:** All business operations — procurement (indent, PO, inward), inventory, masters, sales, jute purchase/production.

### Database Selection Flow Diagram

```
Request arrives → extract_subdomain_from_request(request)
                  ↓
                  Extracts subdomain from headers (priority: x-forwarded-host > host > referer > subdomain header)
                  ↓
    ┌─────────────┼─────────────────┐
    ↓             ↓                 ↓
  Control Desk  Tenant Admin     Portal
    ↓             ↓                 ↓
  vowconsole3   vowconsole3      {subdomain} DB
  (no org       (filtered by     (e.g., dev3, sls)
   filter)       con_org_id)      ↓
                  ↓              Also has secondary DBs:
                 get_org_id_     {subdomain}_c
                 from_subdomain  {subdomain}_c_1
                 ()              {subdomain}_c_2
                                 {subdomain}_c_3
```

### Key Database Functions (`src/config/db.py`)

| Function | Purpose | Used By |
|----------|---------|---------|
| `extract_subdomain_from_request(request)` | Extracts subdomain from headers | All personas |
| `get_db_names(request)` | Returns `db`, `db1`..`db4` names from subdomain | Portal (multi-DB queries) |
| `get_tenant_engine(db_name)` | Cached engine per DB (validates name, one pool per tenant) | Everything needing an engine — **never create engines per request** |
| `get_tenant_db(request)` | Yields SQLAlchemy session from cached tenant engine | Tenant Admin + Portal |
| `get_db(request)` | Returns dict with DB engines and names | Portal routes |
| `get_org_id_from_subdomain(subdomain, db)` | Maps subdomain → `con_org_id` | Tenant Admin |

### Token Verification & Refresh (`src/authorization/utils.py`)

```python
def get_current_user_with_refresh(request, response, access_token=None):
    # 1. Decode access token
    # 2. If expired, check token type:
    #    - If type != "portal" → fetch refresh_token from vowconsole3.con_user_master
    #    - If type == "portal" → fetch refresh_token from {tenant_db}.user_mst
    # 3. Generate new access token if refresh is valid
```

### Router Organization in `src/main.py`

**Control Desk routes** (`/api/ctrldskAdmin`):
```python
app.include_router(co_ctrldsk_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-roles"])
app.include_router(co_ctrldsk_users_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-users"])
app.include_router(co_ctrldsk_orgs_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-orgs"])
app.include_router(co_ctrldsk_menu_router, prefix="/api/ctrldskAdmin", tags=["ctrldsk-admin-menu"])
```

**Tenant Admin routes** (`/api/companyAdmin`):
```python
app.include_router(co_console_router, prefix="/api/companyAdmin", tags=["company-admin-menu"])
app.include_router(co_roles_router, prefix="/api/companyAdmin", tags=["company-admin-roles"])
app.include_router(co_users_router, prefix="/api/companyAdmin", tags=["company-admin-users"])
app.include_router(co_company_router, prefix="/api/companyAdmin", tags=["company-admin-company"])
app.include_router(co_branch_router, prefix="/api/companyAdmin", tags=["company-admin-branch"])
app.include_router(co_dept_subdept_router, prefix="/api/companyAdmin", tags=["company-admin-dept-subdept"])
```

**Portal routes** (`/api/admin/PortalData` + business routes):
```python
app.include_router(co_portal_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_users_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_menu_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
app.include_router(co_portal_approval_router, prefix="/api/admin/PortalData", tags=["PortalDataInAdmin"])
# Plus all business routers: /api/procurementIndent, /api/itemMaster, etc.
```

### Choosing the Right DB Dependency

| Writing code for... | Use this dependency | Connects to |
|---------------------|-------------------|-------------|
| Control Desk routes | `Session(default_engine)` directly | `vowconsole3` |
| Tenant Admin routes | `Depends(get_tenant_db)` | `vowconsole3` (org-scoped) |
| Portal routes | `Depends(get_tenant_db)` | `{subdomain}` tenant DB |
| Portal multi-DB queries | `Depends(get_db)` | Returns dict with multiple engines |

**❌ NEVER:**
- Hardcode database names
- Skip the correct DB dependency for the persona
- Use `default_engine` directly in Portal routes
- Use `get_tenant_db` in Control Desk routes (it's not needed)

### 2. Database Access Patterns

**Two Approaches (Use Both as Appropriate):**

#### A. ORM Models (Preferred for Simple CRUD)
**Location:** `src/models/`
- **Authoritative source** for database schema
- Use for straightforward operations
- Models organized by domain: `item.py`, `procurement.py`, `jute.py`, `inventory.py`, `sales.py`, `mst.py`

```python
from src.models.procurement import ProcInward, ProcInwardDtl

inward = db.query(ProcInward).filter(ProcInward.co_id == co_id).first()
```

#### B. Raw SQL (For Complex Queries)
**Location:** `src/{module}/query.py`
- Use `sqlalchemy.text()` with named bind parameters
- Required for complex joins, aggregations, conditional logic

```python
# In query.py
def get_item_table(co_id: int = None):
    sql = """
    SELECT * FROM item_mst
    WHERE co_id = :co_id
    AND (:search IS NULL OR item_code LIKE :search)
    """
    return text(sql)

# In router
query = get_item_table(int(co_id))
result = db.execute(query, {"co_id": int(co_id), "search": search}).fetchall()
data = [dict(r._mapping) for r in result]
```

**CRITICAL SQL Binding Rules:**
- ✅ Use `None` for SQL NULL: `{"item_id": None}`
- ❌ Never use string "null": `{"item_id": "null"}`
- ✅ Match parameter names exactly: `:co_id` → `{"co_id": value}`
- ✅ Always type-cast: `{"co_id": int(co_id)}`

### 3. API Response Format (MANDATORY)

**Standard Response Wrapper:**
```python
from src.common.utils import create_response

# Simple response
return {"data": results}

# With master data
return {"data": records, "master": options}

# Using helper
return create_response(data=results, master=options)
```

**❌ NEVER return raw lists:**
```python
return [{"id": 1}]  # WRONG
```

**✅ ALWAYS wrap in object:**
```python
return {"data": [{"id": 1}]}  # CORRECT
```

### 4. Authentication & Authorization

**Standard Dependency (works for all three personas):**
```python
token_data: dict = Depends(get_current_user_with_refresh)
```

**What it does:**
- Decodes JWT access token from `access_token` cookie
- If expired, checks token `type` field:
  - `type` absent or not "portal" → refreshes from `vowconsole3.con_user_master`
  - `type == "portal"` → refreshes from `{tenant_db}.user_mst`
- Returns user dict with `user_id` field
- Raises `HTTPException(401)` if invalid

**Key Database Schema Differences:**

| Field | Console Users (`con_user_master`) | Portal Users (`user_mst`) |
|-------|-----------------------------------|---------------------------|
| Primary key | `con_user_id` | `user_id` |
| Email | `con_user_login_email_id` | `email_id` |
| Password | `con_user_login_password` | `password` |
| User type | `con_user_type` (0=ctrldesk, 1=tenant admin) | N/A |
| Org scope | `con_org_id` (NULL=ctrldesk) | N/A (entire tenant DB) |
| Access scope | N/A | `user_role_map` (co_id, branch_id, role_id) |

**Dev Mode Bypass:**
```python
ENV=development  # Auto-bypass in .env
BYPASS_AUTH=1    # Explicit bypass flag
```

**Cookie:** `access_token` | Production domain: `.vowerp.co.in`

### 5. Error Handling Standards

**Always follow this pattern:**
```python
try:
    # 1. Validate required parameters FIRST
    co_id = request.query_params.get("co_id")
    if not co_id:
        raise HTTPException(status_code=400, detail="co_id is required")

    # 2. Type conversion with error handling
    try:
        branch_id = int(request.query_params.get("branch_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid branch_id format")

    # 3. Execute business logic
    result = db.execute(query, {"co_id": int(co_id)}).fetchall()

    # 4. Return standardized response
    return {"data": [dict(r._mapping) for r in result]}

except HTTPException:
    raise  # Re-raise HTTP exceptions as-is
except Exception as e:
    # Log the error (add logging if not present)
    raise HTTPException(status_code=500, detail=str(e))
```

**HTTP Status Code Standards:**
- `400` - Missing/invalid required parameters
- `401` - Authentication failures (handled by auth dependency)
- `403` - Authorization failures (permission denied)
- `404` - Resource not found
- `500` - Server errors, unexpected exceptions

---

## Module Structure Pattern

**Every feature module follows this convention:**

```
src/{module}/
├── {feature}.py      # FastAPI router with endpoints (APIRouter)
├── query.py          # SQL query functions returning text() objects
├── models.py         # SQLAlchemy ORM models (optional, may be in src/models/)
├── schemas.py        # Pydantic request/response schemas (optional)
└── constants.py      # Enums, status IDs, constants (optional)
```

**Example: Procurement Module**
```
src/procurement/
├── indent.py         # Procurement indent endpoints
├── po.py             # Purchase order endpoints
├── inward.py         # Goods receipt endpoints
├── query.py          # Shared SQL queries
└── constants.py      # INDENT_STATUS_IDS, PO_TYPES, etc.
```

**Router Registration (in `src/main.py`):**
```python
from src.procurement.indent import router as indent_router

app.include_router(
    indent_router,
    prefix="/api/procurementIndent",
    tags=["procurement-indent"]
)
```

---

## Naming Conventions

### Variables & Functions
**Use snake_case:**
- `co_id` (company ID)
- `item_grp_id` (item group ID)
- `get_item_table()`
- `check_duplicate_item()`

### Classes & Models
**Use PascalCase:**
- `ItemGrpMst` (Item Group Master)
- `ProcInward` (Procurement Inward)
- `YarnQualityMst` (Yarn Quality Master)

**Model Suffixes:**
- `*Mst` - Master tables (reference data)
- `*Dtl` - Detail/line item tables
- `*Response` - Pydantic response schemas
- `*Request` - Pydantic request schemas

### SQL Bind Parameters
**Standard parameter names:**
- `:co_id` - Company ID (most common)
- `:item_id` - Item ID
- `:item_grp_id` - Item Group ID
- `:branch_id` - Branch ID
- `:search` - Search term for LIKE queries
- `:user_id` - User ID

**Keep consistent across all queries!**

---

## Testing Requirements (MANDATORY)

### When to Write Tests
**ALWAYS write tests for:**
1. ✅ New API endpoints - request/response validation, auth, error cases
2. ✅ Query functions - parameter binding, SQL correctness, edge cases
3. ✅ Business logic functions - input/output validation, error handling
4. ✅ Bug fixes - add regression test before fixing

### Test Structure
**Location:** `src/test/`
**Naming:** `test_{module}_{feature}.py`

**Example: Testing an Endpoint**
```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app

client = TestClient(app)

class TestYarnQualityEndpoints:
    @patch("src.masters.yarnQuality.get_tenant_db")
    @patch("src.masters.yarnQuality.get_current_user_with_refresh")
    def test_yarn_quality_create_setup_success(self, mock_auth, mock_db):
        # Setup mocks
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {"jute_yarn_type_id": 1, "jute_yarn_type_name": "Polyester"}
        mock_session.execute.return_value.fetchall.return_value = [mock_row]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        # Execute request
        response = client.get("/api/yarnQualityMaster/yarn_quality_create_setup?co_id=1")

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert "yarn_types" in data
        assert len(data["yarn_types"]) > 0

    @patch("src.masters.yarnQuality.get_tenant_db")
    def test_yarn_quality_missing_co_id(self, mock_db):
        response = client.get("/api/yarnQualityMaster/yarn_quality_create_setup")
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()
```

### Running Tests
```bash
# Activate virtual environment (from the repo root; Windows venv layout)
source .venv/Scripts/activate

# Run all tests
pytest src/test/ -v

# Run specific file
pytest src/test/test_yarn_quality.py -v

# Run with pattern match
pytest src/test/ -k "test_po" -v

# Run with coverage
pytest src/test/ --cov=src --cov-report=html
```

### Browser / UI Testing (real Chrome, dev tenant)

For driving the **real app in Chrome** (login → select company/branch → open a menu → make
entries → probe errors → verify in DB), the URLs, portal logins, and company/branch are in the
**login registry `.claude/test-credentials.md`** — the single source of truth. Any agent or
`/loop` that needs to log a tenant in should read that file; **do not re-ask the user for creds
and do not hardcode them**. Default target is `dev3` (Empire / Factory).

- **Skill:** `/qa-portal-page` — pass the page path(s) (e.g. `sales/enquiry`, `juteSQC/spreader`)
  and an optional `tenant`. It dispatches the `portal-ui-flow-tester` agent.
- **Agent:** `portal-ui-flow-tester` — carries the browser methodology (Chrome DevTools MCP:
  navigate → snapshot → fill → save → check network 200 → pymysql-verify) and the negative-test
  matrix. Reads creds from the registry.
- **Loop pattern:** to test a menu repeatedly, dispatch the agent per iteration with
  `{tenant, page-path}`; it self-configures login + company/branch from the registry each run.

Prereq: frontend `:3000` and backend `:8000` must be up, with a Chrome window open.

---

## Common Pitfalls & How to Avoid Them

### 1. SQL NULL Handling
❌ **Wrong:**
```python
db.execute(query, {"item_id": "null", "search": "null"})
```

✅ **Correct:**
```python
db.execute(query, {"item_id": None, "search": None})
```

### 2. Schema Source Truth
❌ **Wrong:** Using `dbqueries/*.sql` files as reference (may be outdated)
✅ **Correct:** Use `src/models/*.py` ORM models as authoritative schema

### 3. Response Format
❌ **Wrong:**
```python
return items  # Returns list directly
```

✅ **Correct:**
```python
return {"data": items}
```

### 4. Wrong DB Dependency for Persona
❌ **Wrong:** Using `get_tenant_db` in Control Desk routes
```python
# Control Desk route — WRONG
@router.get("/get_org_data_all")
def get_orgs(db: Session = Depends(get_tenant_db)):  # WRONG!
```

✅ **Correct:** Use `default_engine` directly for Control Desk
```python
# Control Desk route — CORRECT
@router.get("/get_org_data_all")
def get_orgs(request: Request, token_data: dict = Depends(verify_access_token)):
    with Session(default_engine) as session:
        # Query vowconsole3 directly, no org filter
```

❌ **Wrong:** Using `SessionLocal()` directly in Portal routes
```python
db = SessionLocal()  # WRONG — this connects to vowconsole3, not tenant DB
```

✅ **Correct:** Use `get_tenant_db` for Portal and Tenant Admin routes
```python
db: Session = Depends(get_tenant_db)  # Correctly routes to tenant DB
```

### 5. Parameter Binding Mismatch
❌ **Wrong:**
```python
sql = "WHERE co_id = :company_id"
db.execute(text(sql), {"co_id": 1})  # Name mismatch!
```

✅ **Correct:**
```python
sql = "WHERE co_id = :co_id"
db.execute(text(sql), {"co_id": 1})  # Names match
```

### 6. Sync Handler Policy (async→sync conversion, 2026-07-06)

The whole API uses **sync SQLAlchemy/PyMySQL**, so handlers MUST be plain `def` — FastAPI
runs them in its threadpool and requests stay concurrent. An `async def` handler with sync
DB calls runs ON the event loop and freezes every other request while its query executes.

❌ **Wrong:**
```python
@router.post("/save")
async def save(request: Request, db: Session = Depends(get_tenant_db)):
    body = await request.json()          # forces async def; DB calls below block the loop
```

✅ **Correct:**
```python
from src.common.utils import parse_json_body

@router.post("/save")
def save(request: Request, db: Session = Depends(get_tenant_db)):
    body = parse_json_body(request)      # sync-safe body read (runs request.json() on the loop)
```

Rules:
- Handlers are `def`, never `async def`. Only real awaits justify async (today: only the
  middleware in `src/main.py` and `src/config/cors.py`).
- Raw JSON body: `parse_json_body(request)` from `src/common/utils.py` — `await request.json()`
  is impossible in a sync handler.
- File uploads: `file.file.read()`, not `await file.read()`.
- Engines: always `get_tenant_engine(db_name)` / `get_tenant_db` — never `create_engine` or
  `get_engine` per request (leaks one connection pool per call).
- Handlers run concurrently in threads — no module-level mutable state in request paths.

---

## Database Schema Conventions

### Table Naming Patterns

| Pattern | Meaning | Examples |
|---------|---------|---------|
| `{entity}_mst` | Master/reference table | `item_mst`, `branch_mst`, `party_mst` |
| `{module}_{entity}` | Transaction header | `proc_indent`, `proc_po`, `jute_mr` |
| `{module}_{entity}_dtl` | Transaction detail/line items | `proc_indent_dtl`, `proc_po_dtl` |
| `{module}_{entity}_dtl_cancel` | Cancellation records | `proc_indent_dtl_cancel` |
| `{entity}_additional` | Additional charges | `proc_po_additional` |
| `{entity}_gst` | GST tax breakup | `po_gst`, `proc_gst` |
| `{entity}_map` | Mapping/junction tables | `role_menu_map`, `uom_item_map_mst` |
| `vw_{name}` | Database views | `vw_approved_inward_qty` |
| `con_{entity}` | Console/vowconsole3 tables | `con_user_master`, `con_org_master` |

### Module Prefixes

| Module | Prefix | Examples |
|--------|--------|----------|
| Procurement | `proc_` | `proc_indent`, `proc_po`, `proc_inward` |
| Jute | `jute_` | `jute_mr`, `jute_quality_mst` |
| Sales | `sales_` / `invoice_` | `sales_invoice`, `sales_invoice_dtl` |
| Inventory | `issue_` | `issue_hdr`, `issue_li` |

### Column Naming

| Pattern | Usage | Examples |
|---------|-------|---------|
| `{entity}_id` | Primary key | `item_id`, `branch_id`, `po_id` |
| `{entity}_dtl_id` | Detail line PK | `indent_dtl_id`, `po_dtl_id` |
| `co_id` | Company/tenant reference | On all tenant-scoped tables |
| `branch_id` | Branch scope | On most transactional tables |
| `status_id` | Workflow state | On transaction headers |
| `active` | Soft-delete flag (1/0) | Use `Integer` type, not Boolean |
| `qty` / `rate` / `amount` | Financial amounts | Use `Double` type |

**Abbreviation Reference:**
```
mst=master, dtl=detail, li=line item, hdr=header, grp=group
dept=department, co=company, org=organisation, con=console
proc=procurement, po=purchase order, mr=material receipt
uom=unit of measure, gst=goods & services tax, tds=tax deducted at source
```

### Structural Database Patterns

**Header → Detail (1:N):** Every transaction has both tables:
```
proc_indent (header)           proc_indent_dtl (detail/line items)
├── indent_id PK         ───►  ├── indent_dtl_id PK
├── indent_date                ├── indent_id FK
├── branch_id                  ├── item_id, qty, uom_id
├── status_id                  └── ...
└── ...
```

**Cross-Entity Traceability (Procurement Chain):**
```
proc_indent_dtl.indent_dtl_id
    ← proc_po_dtl.indent_dtl_id          (PO traces to indent)
        ← proc_inward_dtl.po_dtl_id      (Inward traces to PO)
            ← issue_li.inward_dtl_id      (Issue traces to inward)
```

Always maintain this traceability when adding downstream tables.

**GST Parallel Tables:** GST breakup stored in separate tables linked to detail rows:
```
proc_po_dtl  ──►  po_gst (cgst_amount, sgst_amount, igst_amount, tax_pct)
```

**Cancellation per-line:** Tracked in `{entity}_dtl_cancel` tables (not header-level).

### ORM Model Style (SQLAlchemy 2.0)

```python
from sqlalchemy import Integer, String, ForeignKey, Double, Date
from sqlalchemy.orm import Mapped, mapped_column, relationship, DeclarativeBase

class Base(DeclarativeBase):
    pass

class ProcIndent(Base):
    __tablename__ = "proc_indent"
    indent_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indent_date: Mapped[str] = mapped_column(Date, nullable=True)
    branch_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("branch_mst.branch_id"))
    status_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("status_mst.status_id"))
    active: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    details: Mapped[list["ProcIndentDtl"]] = relationship(back_populates="indent")
```

**Do NOT use legacy `Column(Integer, ...)` with `declarative_base()` style.**

### Known Production Typos (NEVER FIX)

These typos exist in production tables. **Do NOT rename them** — it would break the app:

| Actual name | Should be | Table |
|-------------|-----------|-------|
| `mechine_spg_details` | `machine_spg_details` | Jute spindle |
| `frieght_paid` | `freight_paid` | `jute_mr` |
| `brokrage_rate` | `brokerage_rate` | `jute_mr` |
| `fatory_address` | `factory_address` | `party_branch_mst` |

Spell new tables and columns correctly.

---

## Three-Level Menu System

Access control uses a hierarchical menu architecture:

| Level | Table | Database | Used By |
|-------|-------|----------|---------|
| 1. Control Desk Menus | `control_desk_menu` | `vowconsole3` | Super admin sidebar |
| 2. Company Admin Menus | `con_menu_master` | `vowconsole3` | Tenant admin sidebar (via `con_role_menu_map`) |
| 3. Portal Menu Template | `portal_menu_mst` | `vowconsole3` | Master template for portal menus |
| 4. Tenant Portal Menus | `menu_mst` | `{tenant_db}` | Actual portal menus (via `role_menu_map`) |

**When adding a new feature/page:**
1. Add menu entry to `portal_menu_mst` (vowconsole3) as template
2. Ensure corresponding `menu_mst` entry in tenant DB
3. Map it to correct `module_mst` / `con_module_masters`
4. Set up `role_menu_map` entries for role-based access

---

## Approval Workflow (Backend APIs Required)

Each transaction type must implement these endpoints:

| Endpoint | Action | Status Change |
|----------|--------|---------------|
| `POST /api/{menu}/open` | Open document, generate doc number | 21 → 1 |
| `POST /api/{menu}/cancel` | Cancel draft | 21 → 6 |
| `POST /api/{menu}/send-for-approval` | Send for approval | 1 → 20 (level=1) |
| `POST /api/{menu}/approve` | Approve (increment level or finalize) | 20 → 20 (next level) or 20 → 3 |
| `POST /api/{menu}/reject` | Reject (accepts `reason`) | 20 → 4 |
| `POST /api/{menu}/reopen` | Reopen cancelled/rejected | 6 or 4 → 1 or 21 |

**Approval level logic:**
- `approval_level` tracks current level within status 20
- On approve: if not final level → increment level (stay 20); if final → move to 3

---

## Schema Changes / Migrations

**No Alembic** — schema changes via manual SQL scripts:

1. Write DDL in `dbqueries/migrations/` with descriptive name
2. Include rollback SQL as comment
3. Update ORM model in `src/models/`
4. Execute against target database using **pymysql** (see below)

**Running migrations:** There is no `mysql` CLI on this machine. Always use pymysql via the project venv to execute migration scripts:
```bash
source .venv/Scripts/activate && python -c "
import pymysql
conn = pymysql.connect(host='<HOST>', port=3306, user='<USER>', password='<PASS>', database='<TARGET_DB>')
cursor = conn.cursor()
with open('dbqueries/migrations/<migration_file>.sql', 'r') as f:
    for stmt in f.read().split(';'):
        stmt = stmt.strip()
        if stmt and not stmt.startswith('--'):
            cursor.execute(stmt)
conn.commit()
conn.close()
print('Migration applied successfully')
"
```
Read credentials from `env/database.env`. Ask the user which tenant database to target.

**Audit logging:** Handled via database triggers, NOT inline columns. Do not add `created_by`, `created_date` columns unless explicitly asked.

---

## Key Documentation Files

**Read these files for deep understanding:**

| File | Purpose | Priority |
|------|---------|----------|
| `.github/copilot-instructions.md` | AI agent guide with patterns | ⭐⭐⭐ ESSENTIAL |
| `.github/WORKSPACE-INSTRUCTIONS.md` | Repo structure, legacy vs current | ⭐⭐⭐ ESSENTIAL |
| `.claude/agents/dbmanager.md` | Database schema & conventions | ⭐⭐⭐ ESSENTIAL |
| `DOCUMENTATION_INDEX.md` | Repo-wide navigation to all docs/agents/skills | ⭐⭐ Important |
| `../vowerp3ui/docs/claude/TEAM.md` | Agent team roster + skills | ⭐⭐ Important |
| `src/config/db.py` | Multi-tenant database config | ⭐⭐⭐ ESSENTIAL |
| `src/authorization/utils.py` | JWT, password hashing | ⭐⭐ Important |
| `src/common/utils.py` | Shared utilities | ⭐ Reference |
| `README.md` | Setup, Docker commands | ⭐ Reference |

---

## Quick Reference: Adding a New Endpoint

**Step 0: Identify the persona.** This determines your DB dependency and code location.

| Persona | Code location | DB dependency | Router prefix |
|---------|--------------|---------------|---------------|
| Control Desk | `src/common/ctrldskAdmin/` | `Session(default_engine)` | `/api/ctrldskAdmin` |
| Tenant Admin | `src/common/companyAdmin/` | `Depends(get_tenant_db)` | `/api/companyAdmin` |
| Portal (admin) | `src/common/portal/` | `Depends(get_tenant_db)` | `/api/admin/PortalData` |
| Portal (business) | `src/{module}/` | `Depends(get_tenant_db)` | `/api/{moduleName}` |

### 1. Create Query Function (if needed)
**File:** `src/{module}/query.py`
```python
def get_my_data(co_id: int):
    sql = """
    SELECT * FROM my_table
    WHERE co_id = :co_id
    AND (:search IS NULL OR name LIKE :search)
    """
    return text(sql)
```

### 2. Create Endpoint (Portal business route example)
**File:** `src/{module}/{feature}.py`
```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from .query import get_my_data

router = APIRouter()

@router.get("/my_endpoint")
def my_endpoint(                                # ← plain def, NOT async def (see Sync Handler Policy)
    request: Request,
    db: Session = Depends(get_tenant_db),       # ← Portal: connects to tenant DB
    token_data: dict = Depends(get_current_user_with_refresh)
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        search = request.query_params.get("search")
        query = get_my_data(int(co_id))
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

### 3. Register Router
**File:** `src/main.py`
```python
from src.{module}.{feature} import router as my_router

app.include_router(my_router, prefix="/api/myModule", tags=["my-feature"])
```

### 4. Write Tests
**File:** `src/test/test_{module}_{feature}.py`
```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app

client = TestClient(app)

class TestMyEndpoint:
    @patch("src.{module}.{feature}.get_tenant_db")
    @patch("src.{module}.{feature}.get_current_user_with_refresh")
    def test_my_endpoint_success(self, mock_auth, mock_db):
        # Setup mocks
        mock_session = MagicMock()
        mock_row = MagicMock()
        mock_row._mapping = {"id": 1, "name": "Test"}
        mock_session.execute.return_value.fetchall.return_value = [mock_row]
        mock_db.return_value.__enter__.return_value = mock_session
        mock_auth.return_value = {"user_id": 1}

        # Test
        response = client.get("/api/myModule/my_endpoint?co_id=1")
        assert response.status_code == 200
        assert "data" in response.json()
```

### 5. Run and Verify
```bash
# Run tests
pytest src/test/test_{module}_{feature}.py -v

# Start dev server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Test manually
curl "http://localhost:8000/api/myModule/my_endpoint?co_id=1"
```

---

## Environment Configuration

**Files:**
- `env/database.env` - Database credentials
- `.env` or `env/keys.env` - Secret keys

**Required Variables:**
```bash
# Database
DATABASE_USER=root
DATABASE_PASSWORD=yourpassword
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_DEFAULT=default_db_name

# Environment
ENV=development  # or production
BYPASS_AUTH=1    # Optional: skip auth in dev

# JWT
SECRET_KEY=your-secret-key-here
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## Development Workflow

### Setup
```bash
# From the repo root

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running
```bash
# Development server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Docker
docker-compose up --build
```

### Before Committing
```bash
# 1. Run tests
pytest src/test/ -v

# 2. Check code quality
# (Add linting if available: black, flake8, mypy)

# 3. Verify no debug code
# Remove print statements, console.logs, breakpoints
```

---

## Best Practices Summary

### DO ✅
- **Identify which persona** you're writing code for FIRST (Control Desk / Tenant Admin / Portal)
- Use the **correct DB dependency** for the persona (see table above)
- Write handlers as plain **`def`** (threadpool) — read JSON bodies via `parse_json_body(request)`
- Validate all required parameters before processing
- Return responses in `{"data": [...]}` format
- Use `None` for SQL NULL values
- Write tests for all new endpoints and logic
- Use ORM models as schema reference
- Follow snake_case for functions/variables
- Follow PascalCase for classes/models
- Type-cast parameters before passing to queries
- Handle exceptions with appropriate HTTP status codes

### DON'T ❌
- Use the wrong DB dependency for the persona
- Declare handlers `async def` (blocks the event loop with sync DB calls) or use `await request.json()`
- Create engines per request — use `get_tenant_engine(db_name)` (cached, one pool per DB)
- Hardcode database names or `con_org_id` values
- Skip parameter validation
- Return raw lists from endpoints
- Use string "null" in SQL parameters
- Skip writing tests
- Use outdated `dbqueries/*.sql` as schema reference
- Mix naming conventions
- Trust user input without validation
- Catch exceptions without re-raising or proper handling
- Commit code without running tests

---

## Support & Resources

**For Questions:**
1. Check `.github/copilot-instructions.md` first
2. Review `DOCUMENTATION_INDEX.md` for specific topics
3. Look at existing similar endpoints as examples
4. Check test files for usage patterns

**Common Examples:**
- **Simple CRUD:** `src/masters/items.py`
- **Complex Transactions:** `src/procurement/indent.py`
- **Multi-table Queries:** `src/procurement/query.py`
- **Authentication Patterns:** `src/authorization/routers.py`
- **Testing Patterns:** `src/test/test_yarn_quality.py`

---

## Knowledge-Graph Index (secondary — may be stale)

Machine-generated indices for both repos live in `graphify-out/`: `graph.json` (structure),
`index_be.json` / `index_fe.json` (per-symbol summaries), `bridge.json` (FE-const → BE-endpoint
matches, `dead_routes`, `orphan_endpoints`), `GRAPH_REPORT.md`.

**Status: the graphify CLI is currently non-operational and the artifacts may be stale.** The module
guides (`../vowerp3ui/docs/claude/modules/` + the `module-*` agents in `.claude/agents/`) and the
actual source files are the PRIMARY reference — consult the graph only as a quick cross-check, and
verify every hit against router source before relying on it. Entries carry `hash` /
`last_indexed_at` staleness markers; if they don't match the current file, read the source instead.

Regenerate (when the CLI is fixed):

```
python tools/bridge_extractor.py       # rebuild bridge.json
python tools/index_extractor_be.py     # rebuild index_be.json
python tools/index_extractor_fe.py     # rebuild index_fe.json
```

The `.claude/commands/graph-{find,trace,reuse,bridge}.md` commands query these artifacts and carry
the same caveat.

---

## Version Info
- Python: 3.12+
- FastAPI: 0.115.11
- SQLAlchemy: 2.0.38
- Main Branch: `main`

**Last Updated:** 2026-06-12
