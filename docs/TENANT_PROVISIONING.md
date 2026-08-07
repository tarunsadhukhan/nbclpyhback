# Tenant Database Provisioning - Documentation & Design

## Status: DOCUMENTATION ONLY - No implementation yet

---

## 1. Current System Overview

### How Multi-Tenancy Works Today

VoWERP3 uses a **database-per-tenant** architecture:

| Database | Purpose | Used By |
|----------|---------|---------|
| `vowconsole3` | Central control database - organizations, console users, roles, menus | Control Desk + Tenant Admin |
| `{shortname}` (e.g., `sls`, `dev3`) | Tenant-specific business data | Portal users |
| `{shortname}_c`, `_c_1`, `_c_2`, `_c_3` | Secondary DBs (legacy, currently unused by business modules) | Legacy prototype code only |

### How a Tenant DB Name Is Determined

The `con_org_shortname` field in `vowconsole3.con_org_master` serves as both:
- The **subdomain** used by the frontend (e.g., `sls.vowerp.co.in`)
- The **database name** for that tenant

At runtime, `extract_subdomain_from_request()` in `src/config/db.py` extracts the subdomain from HTTP headers (priority: `X-Forwarded-Host` > `Host` > `Referer` > `subdomain` header) and uses it as the database name.

### What Happens Today When a New Org Is Created

1. Control Desk admin calls `POST /api/ctrldskAdmin/create_org_data`
2. A record is inserted into `vowconsole3.con_org_master` with `con_org_shortname` = the chosen acronym
3. **That's it.** The actual tenant database does NOT get created automatically.
4. A DBA must manually:
   - Create the MySQL database
   - Run SQL scripts to create all tables
   - Insert seed/reference data
   - Create views and triggers
   - Create the initial admin user

**This manual process is the gap this document aims to address.**

---

## 2. What a New Tenant Database Needs

### 2A. Tables (~169 across 7 model files)

All ORM models are defined in `src/models/`:

| File | Model Count | Domain |
|------|------------|--------|
| `mst.py` | ~36 | Master/reference tables (status, country, state, currency, UOM, party, item groups, branches, users, roles, menus, etc.) |
| `procurement.py` | ~26 | Indent, PO, inward, transfer, GST, TDS, debit/credit notes + views |
| `sales.py` | ~32 | Quotation, order, delivery, invoice (general + hessian + jute + yarn + govt sacking) |
| `jute.py` | ~23 | Jute MR, PO, issue, batch planning, SQC, yarn quality, supplier/mukam/lorry masters |
| `hrms.py` | ~44 | HR/payroll tables |
| `item.py` | ~4 | Item master, item group, item make |
| `inventory.py` | ~4 | Issue header/line items + views |

**Important:** Each model file currently declares its own independent `Base` class. They are NOT unified.

### 2B. Views (Created After Tables)

Views provide calculated/aggregated data and must be created after all tables exist:

| View | Purpose | Dependencies |
|------|---------|-------------|
| `vw_proc_indent_outstanding_new` | Outstanding indent quantities | `proc_indent`, `proc_indent_dtl`, `proc_po_dtl` |
| `vw_proc_po_outstanding_new` | Outstanding PO quantities | `proc_po`, `proc_po_dtl`, `proc_inward_dtl` |
| `vw_item_balance_qty_by_branch_new` | Item stock balance per branch | Multiple procurement + inventory tables |
| `vw_item_with_group_path` | Item with full group hierarchy path | `item_mst`, `item_grp_mst` |
| `vw_jute_stock_outstanding` | Jute stock in-process | Jute MR + issue tables |
| `vw_approved_inward_qty` | Approved inward with balances | `proc_inward`, `proc_inward_dtl` |

View SQL definitions are scattered across `dbqueries/migrations/` files. There is no centralized view directory.

### 2C. Seed Data (Reference/Master Data Required at Setup)

#### Critical - System Will Not Function Without These

| Table | Data | Source of Truth |
|-------|------|----------------|
| `status_mst` | IDs: 1=Open, 3=Approved, 4=Rejected, 5=Closed, 6=Cancelled, 20=Pending Approval, 21=Draft | `src/procurement/constants.py`, `src/sales/constants.py` |
| `country_mst` | India (+ optionally USA) | `dbqueries/usertables.sql` |
| `state_mst` | Indian states with state codes | `dbqueries/usertables.sql` |
| `currency_mst` | 15 standard currencies (USD, EUR, INR, GBP, JPY, CNY, AUD, CAD, CHF, SGD, NZD, ZAR, HKD, THB, AED) | `dbqueries/procurement.sql` |
| `module_mst` | Application modules (Procurement, Sales, Inventory, Jute, HRMS, etc.) | Extract from live tenant |
| `menu_mst` + `menu_type_mst` | Application navigation menu structure | Extract from live tenant |
| `access_type` | Access control types | Extract from live tenant |

#### Important - Recommended for Usability

| Table | Data |
|-------|------|
| `entity_type_mst` | Individual, Company, Partnership, etc. |
| `party_type_mst` | Supplier, Customer, Transporter, etc. (with module_id references) |
| `uom_mst` | Common units: pieces, kg, liters, meters, etc. |
| `item_type_master` | Item type classifications |
| `roles_mst` | At least one default "Admin" role |

#### Per-Tenant Setup (Done Via UI After Provisioning)

These are created by the Tenant Admin or Portal users through the application:
- `co_mst` (companies), `branch_mst` (branches), `dept_mst` / `sub_dept_mst`
- `user_mst` (portal users), `user_role_map`, `role_menu_map`
- `item_grp_mst`, `item_mst`, `party_mst`, `warehouse_mst`
- `approval_mst`, `tax_mst`, `tds_mst`
- All jute-specific masters (if jute module enabled)

### 2D. Initial Admin User

A new tenant needs at least one portal user to log in. This requires:
1. A record in `user_mst` (with hashed password)
2. A role in `roles_mst`
3. A mapping in `user_role_map` (linking user to role, company, and branch)
4. Menu access via `role_menu_map`

---

## 3. Existing Schema/Migration Assets

### SQL Files in `dbqueries/`

| File | Contains |
|------|----------|
| `usertables.sql` | Core tables: country, state, city, co_mst, branch_mst, user_mst, module_mst, roles_mst, menu_mst, role_menu_map, user_role_map, approval_mst. Includes seed INSERT for countries/states/cities. |
| `usertableconsole.sql` | Console tables: con_role_menu_map, control_desk_menu, portal_menu_mst |
| `procurement.sql` | All procurement tables + currency_mst seed data. **Has duplicate CREATE TABLE statements** (machine_mst x3, co_config x2, status_mst x2). |
| `create_yarn_quality_tables.sql` | Yarn quality master tables |

### Migration Files in `dbqueries/migrations/` (~40+ files)

- No naming convention (mix of descriptive names)
- No execution order tracking
- No record of which tenants have received which migrations
- Some include `-- Rollback:` comments, most don't

### Scripts

| Script | Purpose | Issues |
|--------|---------|--------|
| `scripts/migrate_view.py` | Applies view changes to a single DB | **Contains hardcoded credentials for production DB** |
| `scripts/generate_ddl_excel.py` | Exports DDL to Excel | Utility only |

---

## 4. Known Technical Issues

### 4A. Independent Base Classes (Blocks Automated Table Creation)

Each model file declares its own `Base`:

| File | Base Declaration Style |
|------|----------------------|
| `mst.py` | `Base = declarative_base()` (legacy SQLAlchemy style) |
| `procurement.py` | `class Base(DeclarativeBase): pass` (SQLAlchemy 2.0 style) |
| `sales.py` | `class Base(DeclarativeBase): pass` |
| `jute.py` | `class Base(DeclarativeBase): pass` |
| `item.py` | `class Base(DeclarativeBase): pass` |
| `inventory.py` | `class Base(DeclarativeBase): pass` |
| `hrms.py` | `class Base(DeclarativeBase): pass` |

**Impact:** `Base.metadata.create_all()` only creates tables registered on that specific Base. To create all tables at once, these must be unified into a single shared Base.

### 4B. Global Variable Concurrency Bug (`src/config/db.py:111-116`)

```python
global db, db1, db2, db3, db4
db = subdomain
db1 = f"{subdomain}_c"
# ...
```

These global variables are shared across all concurrent requests. Under load, one request can overwrite another's database name, potentially causing **cross-tenant data leakage**. These should be request-scoped.

### 4C. Duplicate ORM Model Definitions

Several models are defined in multiple files:
- `ItemGrpMst` - in `mst.py`, `item.py`, and `src/masters/models.py`
- `ItemMst` - in `mst.py`, `item.py`, and `src/masters/models.py`
- `DeptMst`, `SubDeptMst`, `WarehouseMst`, `PartyMst` - in multiple files

This would cause conflicts when unifying to a single Base.

### 4D. Schema Drift

The SQL files in `dbqueries/` and the ORM models in `src/models/` have diverged:
- SQL files contain duplicate `CREATE TABLE` statements
- ORM models have columns not in SQL files (e.g., `branch_prefix`, `mech_code`, `state_code`)
- Some SQL files are outdated and missing newer tables (all sales, HRMS, many jute tables)

**The ORM models in `src/models/` are the authoritative source of truth for schema.**

### 4E. Secondary Databases Are Unused

The `{name}_c`, `{name}_c_1`, `{name}_c_2`, `{name}_c_3` pattern:
- Defined in `src/config/db.py` (`get_db_names()`)
- Only referenced in `src/common/routers.py` for two prototype endpoints (`/fetch_joined_data`, `/fetch_joined_datas`) that use legacy models (`Academic_years`, `DailyDrawingTransaction`)
- **No actual business module** (procurement, sales, inventory, jute) references these
- **Recommendation:** Do not create these for new tenants

---

## 5. Expert Recommendations Summary

### From a Senior Full-Stack Developer Perspective

1. **Provisioning should be async** - Table creation + seeding takes 15-30s. Use FastAPI `BackgroundTasks`, not a synchronous endpoint. No need for Celery given low frequency (new tenants are rare events).

2. **Use `Base.metadata.create_all()` for table creation** - It's code-native, testable, and always in sync with the ORM models. But requires unifying the Base classes first.

3. **Create ALL tables regardless of selected modules** - Empty tables cost nothing (a few hundred KB of metadata). Conditional creation is fragile. Only vary seed data by module.

4. **Use a state machine for provisioning** - Track progress in a `con_org_provisioning_log` table in vowconsole3 with steps: PENDING -> DB_CREATED -> TABLES_CREATED -> VIEWS_CREATED -> SEED_DATA_LOADED -> ADMIN_USER_CREATED -> COMPLETED. On failure: `DROP DATABASE` is safe since it's brand new.

5. **Seed data as Python functions** - Type-safe, conditional on modules, testable. Better than SQL fixtures for this use case.

6. **Three-level testing** - Unit tests for seed functions, integration test for full provisioning, dry-run mode for production safety.

### From a Senior DB Manager Perspective

1. **Golden template database** - Create a `_vow_template` database that's always at the latest schema. New tenants can be provisioned by cloning via mysqldump. More reliable than generating from code.

2. **Schema versioning is critical** - Add a `_schema_version` table to every tenant DB to track applied migrations. Without this, you have no idea which tenants are at which version.

3. **Fixed IDs for seed data** - Status IDs (1, 3, 4, 5, 6, 20, 21) are hardcoded in business logic. Use explicit INSERT with fixed IDs, then reset AUTO_INCREMENT above the highest seeded value.

4. **Migration runner** - Script that queries `con_org_master` for all active tenants and applies a migration to each, tracking results in `_schema_version`.

5. **Separate MySQL users by access level:**
   - `vow_app` (SELECT/INSERT/UPDATE/DELETE) - application runtime
   - `vow_migrate` (ALL PRIVILEGES) - migrations and provisioning
   - `vow_readonly` (SELECT) - reporting/debugging

6. **Standardize charset** - All databases: `utf8mb4` with `utf8mb4_0900_ai_ci` collation.

7. **Centralize view definitions** - Create `dbqueries/views/` with one file per view using `CREATE OR REPLACE VIEW`. Document dependency order. Deploy separately from table migrations since views are idempotent.

8. **Scaling limits** - A single MySQL server (e.g., RDS r6g.xlarge) can handle 50-100 tenants comfortably. Beyond 200, consider splitting across instances.

---

## 6. Implementation Plan (FOR FUTURE REFERENCE - NOT IMPLEMENTING NOW)

### Phase 0: Prerequisites

**0A. Unify Base class** - Create `src/models/base.py`, update all 7 model files to import from it. Resolve duplicate model definitions.

**0B. Extract seed data** - Query an existing tenant (e.g., `dev3`) for current reference data in all seed tables. Encode into Python constants.

### Phase 1: Core Provisioning Module

```
src/provisioning/
    __init__.py
    service.py          # State machine orchestrator
    schema_manager.py   # CREATE DATABASE + create_all() + views
    seed_data.py        # All seed data functions with explicit IDs
    router.py           # API endpoints (trigger, status, retry)
    schemas.py          # Pydantic models
```

New table in vowconsole3: `con_org_provisioning_log` (tracks provisioning state per org).

API endpoints:
- `POST /api/ctrldskAdmin/provision_tenant/{org_id}` - trigger
- `GET /api/ctrldskAdmin/provision_status/{org_id}` - check status
- `POST /api/ctrldskAdmin/reprovision_tenant/{org_id}` - retry after failure

### Phase 2: Migration Management

- `_schema_version` table in every tenant DB
- `scripts/run_migration.py` - applies migrations across all tenants
- Rename existing migration files to `YYYYMMDD_HHMM_{description}.sql`

### Phase 3: Centralize Views

- `dbqueries/views/` directory with one file per view
- `scripts/deploy_views.py` for cross-tenant view deployment

### Phase 4: Golden Template (Optimization)

- Create `_vow_template` using the provisioning system
- Offer mysqldump clone as alternative provisioning path
- Keep template updated by applying every migration to it first

### Implementation Order

| Step | What | Depends On |
|------|------|-----------|
| 0A | Unify Base class | Nothing |
| 0B | Extract seed data | Nothing |
| 1A | Provisioning log table | Nothing |
| 1B | schema_manager.py | 0A |
| 1C | seed_data.py | 0B |
| 1D | service.py | 1A, 1B, 1C |
| 1E | router.py | 1D |
| 2A | _schema_version table | 1B |
| 2B | Migration runner script | 2A |
| 3A | Centralize views | Nothing |
| 3B | View deployment script | 3A |
| 4 | Golden template | All above |

---

## 7. Critical Files Reference

| File | Role | Lines of Interest |
|------|------|-------------------|
| `src/config/db.py` | Tenant DB routing, connection management | L111-116 (global vars bug) |
| `src/models/mst.py` | 36 master models | L20-22 (legacy Base) |
| `src/models/procurement.py` | 26 procurement models | L25-27 (independent Base) |
| `src/models/sales.py` | 32 sales models | Independent Base |
| `src/models/jute.py` | 23 jute models | Independent Base |
| `src/models/hrms.py` | 44 HRMS models | Independent Base |
| `src/models/item.py` | 4 item models | Independent Base |
| `src/models/inventory.py` | 4 inventory models | Independent Base |
| `src/common/ctrldskAdmin/orgs.py` | Org creation endpoint | L149-206 |
| `src/common/ctrldskAdmin/schemas.py` | OrgCreate schema | L21-35 |
| `src/procurement/constants.py` | Status ID constants | INDENT_STATUS_IDS |
| `src/sales/constants.py` | Status ID constants | SALES_STATUS_IDS |
| `dbqueries/usertables.sql` | Core DDL + country/state seed | Full file |
| `dbqueries/procurement.sql` | Procurement DDL + currency seed | Full file (has duplicates) |
| `scripts/migrate_view.py` | Existing view migration pattern | Has hardcoded credentials |
