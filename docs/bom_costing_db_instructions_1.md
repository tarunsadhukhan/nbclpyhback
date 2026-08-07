# BOM Costing Database Design — Instruction Sheet

**Context:** AMCL Machineries, Nagpur — manufactures machines for cement, steel, rubber, and glass factories.  
**Key activities:** Casting, die casting, machining, assembly, fabrication, heat treatment, surface finishing, testing/QC.  
**Approach:** Flexible cost element tree (configurable hierarchy stored as data) + flattened materialized view for reporting.

> **Note for DB agent:** Follow existing database naming conventions already in practice in the VoWERP3 schema. The table/column names below are logical — adapt them to match the project's casing, prefix, and naming style. The existing `items` table and `bom` tables should be referenced via foreign keys, not recreated.

---

## 1. Tables to Create

### 1.1 Cost Element Master (the configurable taxonomy)

**Purpose:** Defines the entire cost classification hierarchy as data rows, not as fixed columns. This is the backbone — every cost category, sub-category, and line item is a row here. The tree can go to any depth. New cost heads are added by inserting rows, never by altering schema.

**Required fields:**

| Field | Type | Purpose |
|---|---|---|
| Primary key | UUID | Unique identifier |
| Code | Unique string | Short stable identifier (e.g., `CONV`, `MP`, `MP_DIRECT`). Used in queries and the reporting view. Should not change once set. |
| Name / Label | String | Human-readable display name (e.g., "Direct Labor"). Can be updated freely. |
| Parent reference | FK → self (nullable) | Points to the parent cost element. NULL = root-level element (Material, Conversion). |
| Level | Integer | Depth in the tree: 1 = root, 2 = category, 3 = sub-category, 4+ = detail. Denormalized for convenience. |
| Element type | String/enum | Broad classification tag — e.g., `material`, `conversion`, `overhead`. Useful for quick filtering independent of tree position. |
| Default basis | String/enum | The typical unit this cost is expressed in: `per_unit`, `per_machine_hour`, `per_kg`, `per_batch`, `per_month_allocated`, `fixed`, `percentage`. Individual BOM entries can override this. |
| Is leaf | Boolean | TRUE = this element accepts direct value entries. FALSE = its value is always computed as sum of children. Enforced at application layer. |
| Sort order | Integer | Display ordering among siblings. |
| Is active | Boolean | Soft delete / hide from new entries without breaking historical data. |
| Description | Text (optional) | Guidance for users on what costs belong under this element. |

**Key rules:**
- A non-leaf element (is_leaf = FALSE) should never have direct cost entries against it when child entries exist. Its value is always the sum of its children.
- A non-leaf element CAN accept a direct "assumed" entry when no child detail has been entered — this is the "skip detail" mechanism.
- The tree should be seeded with a standard structure (see Section 3) but is fully user-extensible.

---

### 1.2 BOM Cost Entries (the single cost data table)

**Purpose:** Stores ALL cost values at ANY level of the hierarchy for a given BOM. This is the only table where cost numbers are written. One row = one cost element's value for one BOM.

**Required fields:**

| Field | Type | Purpose |
|---|---|---|
| Primary key | UUID | Unique identifier |
| BOM reference | FK → existing BOM header table | Links to which BOM (and therefore which item + version) this cost belongs to. |
| Cost element reference | FK → cost element master | Which cost head this entry is for. |
| Amount | Numeric(15,4) | The cost value. Always stored in base currency (INR). |
| Source | String/enum | **Critical field.** How this value was determined. Values: `calculated` (rolled up from children), `assumed` (estimated/plugged number), `manual` (entered by user with supporting data), `imported` (from external system/sheet), `standard` (from standard rate cards). |
| Quantity / Hours | Numeric (nullable) | The volume driver — e.g., 8 machine hours, 12 man-hours, 450 kWh. NULL when the amount is a lump sum or assumption. |
| Rate | Numeric (nullable) | The rate applied to the quantity — e.g., ₹350/machine-hour, ₹180/man-hour. NULL when amount is directly entered. |
| Basis | String (nullable) | Override of the cost element's default basis for this specific entry. e.g., a maintenance cost might default to `per_month_allocated` but a specific BOM might use `per_machine_hour`. |
| Effective date | Date | When this cost entry is valid from. Enables point-in-time cost snapshots. |
| Entered by | FK → users (nullable) | Audit: who entered/approved this figure. |
| Remarks | Text (nullable) | Free-text justification, especially important for `assumed` entries. |

**Unique constraint:** (BOM reference + cost element reference + effective date) — only one value per element per BOM per date.

**Key rules:**
- When a user enters detail-level (leaf) costs, the application layer should automatically compute and upsert the parent element's entry with `source = 'calculated'`.
- When a user enters a value directly at a parent level (skipping detail), `source` should be `assumed` or `manual`.
- If leaf entries are later added under a previously-assumed parent, the parent's entry should be recomputed and its source changed to `calculated`.
- The `quantity × rate = amount` relationship should be validated at application layer when both qty and rate are provided, but amount can also exist standalone.

---

### 1.3 Standard Rate Cards (optional but recommended)

**Purpose:** Stores reusable rates that feed into cost calculations — machine hour rates, labor rates, power rates, etc. Avoids re-entering the same rates per BOM.

**Required fields:**

| Field | Type | Purpose |
|---|---|---|
| Primary key | UUID | Unique identifier |
| Rate type | String/enum | What this rate applies to: `machine_hour`, `labor_hour`, `power_kwh`, `floor_space_sqft`, `overhead_pct`. |
| Reference entity | String + FK (polymorphic, nullable) | What this rate is for — e.g., a specific work center, machine, department, or cost element. |
| Rate | Numeric(12,4) | The rate value. |
| UOM | String | Unit — `per_hour`, `per_kwh`, `per_kg`, `per_sqft`, `per_month`. |
| Currency | String | Default `INR`. |
| Valid from | Date | Effectivity start. |
| Valid to | Date (nullable) | NULL = currently active. |
| Is active | Boolean | Quick filter. |

**Usage:** When creating BOM cost entries, the application can look up the current rate from here and pre-populate the `rate` field. The user can override per-BOM if needed.

---

### 1.4 BOM Cost Rollup Snapshots (optional, for performance)

**Purpose:** Caches the fully rolled-up cost for a BOM at a point in time. Avoids recomputing the full tree on every read. Think of this as the "published" cost sheet.

**Required fields:**

| Field | Type | Purpose |
|---|---|---|
| Primary key | UUID | Unique identifier |
| BOM reference | FK → BOM header | Which BOM this rollup is for. |
| Material cost | Numeric(15,4) | Total material cost (from BOM lines × item costs). |
| Conversion cost | Numeric(15,4) | Total conversion cost (sum of all non-material elements). |
| Total cost | Numeric(15,4) | Material + conversion. |
| Cost per unit | Numeric(15,4) | Total cost ÷ BOM output quantity. |
| Detail snapshot | JSONB | Full breakdown tree as JSON — preserves the exact state at computation time. |
| Computed at | Timestamp | When this rollup was generated. |
| Computed by | FK → users (nullable) | Who triggered the rollup. |
| Is current | Boolean | Only one current rollup per BOM. Previous ones are historical. |
| Status | String/enum | `draft`, `approved`, `superseded`. |

**Key rules:**
- A new rollup should be created (not updated) each time costs are recomputed. Previous rollups are marked `is_current = FALSE` and `status = 'superseded'`.
- The JSONB snapshot should capture the full element tree with amounts, sources, and rates — this is the audit trail.

---

## 2. Reporting View

Create a materialized view that pivots the flexible tree into fixed columns for easy reporting. This gives the "Option A readability" on top of the "Option B flexibility."

**Logic:**

```
For each BOM:
  - Join cost entries with cost elements
  - Pivot the root-level and second-level element codes into named columns
  - Include the source field so reports show what's calculated vs assumed
```

**Suggested columns in the view:**

```
bom_reference, item_code, item_name, bom_version,
material_cost, material_source,
conversion_cost, conversion_source,
  manpower_cost, manpower_source,
  maintenance_cost, maintenance_source,
  power_cost, power_source,
  overhead_cost, overhead_source,
total_cost, cost_per_unit,
last_computed_at
```

**Implementation note:** Use `CASE WHEN element_code = 'XXX' THEN amount END` pivoting with a `GROUP BY bom_reference`. The exact element codes to pivot on should match the seeded cost element codes from Section 3.

**Refresh strategy:** Refresh the materialized view whenever a cost rollup snapshot is created, or on a schedule (e.g., nightly). For real-time needs, use it as a regular view instead.

---

## 3. Seed Data — Cost Element Hierarchy for AMCL

The following tree should be seeded into the cost element master. Codes are indicative — the DB agent should follow existing naming patterns.

```
Level 1 (Roots)
├── MATERIAL (is_leaf: false, type: material)
│   ├── RAW_MATERIAL (is_leaf: true, basis: per_kg)
│   ├── BOUGHT_OUT (is_leaf: true, basis: per_unit)
│   │   -- Bought-out components: bearings, motors, fasteners, seals, etc.
│   ├── CONSUMABLES (is_leaf: true, basis: per_unit)
│   │   -- Welding rods, cutting tools, grinding wheels, lubricants
│   └── PACKING (is_leaf: true, basis: per_unit)
│       -- Wooden crates, anti-rust oil, shrink wrap, foam
│
└── CONVERSION (is_leaf: false, type: conversion)
    ├── MANPOWER (is_leaf: false)
    │   ├── DIRECT_LABOR (is_leaf: true, basis: per_hour)
    │   │   -- Operators: machinists, welders, fitters, assemblers
    │   ├── SUPERVISORY (is_leaf: true, basis: per_hour)
    │   │   -- Shop floor supervisors, shift in-charges
    │   ├── CONTRACT_LABOR (is_leaf: true, basis: per_hour)
    │   │   -- Contract workers for specific jobs
    │   └── DESIGN_ENGINEERING (is_leaf: true, basis: per_hour)
    │       -- Design/drawing time for custom machines
    │
    ├── MACHINE_COSTS (is_leaf: false)
    │   ├── MACHINE_DEPRECIATION (is_leaf: true, basis: per_machine_hour)
    │   │   -- Depreciation allocated per machine hour
    │   ├── MACHINE_MAINTENANCE (is_leaf: true, basis: per_machine_hour)
    │   │   -- Preventive + breakdown maintenance
    │   ├── TOOLING (is_leaf: true, basis: per_unit)
    │   │   -- Cutting tools, dies, jigs, fixtures consumed
    │   └── MACHINE_CONSUMABLES (is_leaf: true, basis: per_machine_hour)
    │       -- Coolant, hydraulic oil, compressed air
    │
    ├── POWER (is_leaf: false)
    │   ├── MACHINE_POWER (is_leaf: true, basis: per_kwh)
    │   │   -- kWh consumed by machines during operation
    │   └── UTILITY_POWER (is_leaf: true, basis: per_month_allocated)
    │       -- Lighting, HVAC, cranes, compressors — allocated
    │
    ├── OUTSOURCED_PROCESSES (is_leaf: false)
    │   ├── HEAT_TREATMENT (is_leaf: true, basis: per_kg)
    │   ├── SURFACE_TREATMENT (is_leaf: true, basis: per_unit)
    │   │   -- Painting, galvanizing, powder coating, plating
    │   ├── EXTERNAL_MACHINING (is_leaf: true, basis: per_unit)
    │   │   -- Large boring, gear cutting sent outside
    │   └── TESTING_CERTIFICATION (is_leaf: true, basis: per_unit)
    │       -- Third-party NDT, material testing, calibration
    │
    └── OVERHEADS (is_leaf: false)
        ├── FACTORY_OVERHEAD (is_leaf: true, basis: per_month_allocated)
        │   -- Rent, insurance, property tax, security
        ├── ADMIN_OVERHEAD (is_leaf: true, basis: percentage)
        │   -- Admin staff, office costs, allocated as % of conversion
        ├── QC_COSTS (is_leaf: true, basis: per_unit)
        │   -- In-house inspection, gauging, QC staff time
        ├── LOGISTICS_INTERNAL (is_leaf: true, basis: per_unit)
        │   -- Internal material handling, cranes, forklifts
        └── SCRAP_REWORK (is_leaf: true, basis: percentage)
            -- Estimated scrap/rework allowance as % of material+conversion
```

**Note:** This is a starting point. AMCL can add, remove, or rearrange elements at any time through the application without touching the schema. For example, if they start tracking "paint shop costs" separately, they just add a new leaf under OUTSOURCED_PROCESSES or MACHINE_COSTS as appropriate.

---

## 4. How the "Skip Detail" Mechanism Works

This is the key flexibility feature. Three scenarios illustrated:

### Scenario A — Full Detail Available

A CNC-machined casting for a cement mill roller bearing housing:

```
CONVERSION = ₹18,500 (source: calculated)
├── MANPOWER = ₹6,200 (calculated)
│   ├── DIRECT_LABOR = ₹4,500 (manual: 25 hrs × ₹180/hr)
│   ├── SUPERVISORY = ₹1,200 (manual: 25 hrs × ₹48/hr allocation)
│   └── DESIGN_ENGINEERING = ₹500 (manual: 2 hrs × ₹250/hr)
├── MACHINE_COSTS = ₹7,800 (calculated)
│   ├── MACHINE_DEPRECIATION = ₹3,000 (manual: 12 hrs × ₹250/hr)
│   ├── MACHINE_MAINTENANCE = ₹1,800 (manual: 12 hrs × ₹150/hr)
│   └── TOOLING = ₹3,000 (manual: insert cost for this job)
├── POWER = ₹1,500 (calculated)
│   └── MACHINE_POWER = ₹1,500 (manual: 200 kWh × ₹7.50)
└── OVERHEADS = ₹3,000 (assumed: ~16% of above)
```

### Scenario B — Partial Detail, Rest Assumed

A simpler bought-out assembly where only broad estimates exist:

```
CONVERSION = ₹8,000 (source: calculated)
├── MANPOWER = ₹3,500 (assumed — no breakdown into direct/supervisory)
├── MACHINE_COSTS = ₹2,500 (assumed — no breakdown into depreciation/tooling)
├── POWER = ₹500 (assumed)
└── OVERHEADS = ₹1,500 (assumed)
```

### Scenario C — Minimal / Quotation Stage

Early estimation for a customer quote, only a lump conversion cost:

```
CONVERSION = ₹25,000 (source: assumed — single figure based on similar past jobs)
```

All three scenarios coexist in the same tables. The `source` field on each entry makes it transparent where data is solid and where assumptions live.

---

## 5. Application-Layer Behavior Guidelines

These rules should be implemented in the FastAPI service layer, not as database triggers:

### 5.1 Cost Entry Creation/Update

1. When a leaf-level entry is created or updated → walk up the tree and recompute every ancestor's amount as `SUM(children)`, setting their `source = 'calculated'`.
2. When an entry is created at a non-leaf level where children already exist → reject or warn. The user should enter at leaf level, or delete children first if they want to switch to an assumed lump sum.
3. When an entry is created at a non-leaf level where NO children exist → allow it, set `source = 'assumed'` or `manual`.
4. Always validate: if `quantity` and `rate` are both provided, `amount` must equal `quantity × rate` (within rounding tolerance).

### 5.2 Cost Rollup Computation

1. Walk the cost element tree bottom-up (leaves first).
2. For each leaf: use the direct entry amount from `bom_cost_entries`.
3. For each non-leaf: sum children. If no children have entries, use the direct entry if one exists.
4. Material cost comes from the existing BOM lines table (component quantities × their respective item costs). Write this as a cost entry under the MATERIAL element.
5. Write the full result into the rollup snapshot table with a JSONB detail.

### 5.3 Standard Rate Application

1. When creating a new BOM's cost entries, offer to pre-populate from standard rate cards.
2. The rate card lookup should match on: work center / machine (if specified on BOM operations), cost element type, and current date within validity range.
3. Pre-populated entries should have `source = 'standard'`. User edits change it to `manual`.

### 5.4 Reporting

1. Refresh the materialized view after any rollup snapshot creation.
2. The view should only reflect `is_current = TRUE` rollup data.
3. For historical cost comparison, query the rollup snapshot table directly using `computed_at` ranges.

---

## 6. Relationships to Existing Tables

The DB agent should create foreign key references to these existing tables (use actual table/column names from the current schema):

| This new table | References | Existing table |
|---|---|---|
| BOM cost entries | BOM reference | The existing BOM header/master table |
| BOM cost rollup snapshots | BOM reference | The existing BOM header/master table |
| Standard rate cards | Work center / machine reference | Work center or machine master (if exists; if not, use a string identifier for now) |
| BOM cost entries | Entered by | The existing users/auth table |

If a work center or machine master table does not yet exist, the DB agent should create one or use a simple string reference field, and flag it for future normalization.

---

## 7. Indexes to Create

| Table | Index on | Purpose |
|---|---|---|
| Cost element master | `parent_reference` | Tree traversal |
| Cost element master | `code` (unique) | Lookups by code |
| Cost element master | `element_type, is_active` | Filtered queries |
| BOM cost entries | `bom_reference, cost_element_reference` | Primary access pattern |
| BOM cost entries | `cost_element_reference, effective_date` | Rate history lookups |
| BOM cost entries | `source` | Filter calculated vs assumed |
| Rollup snapshots | `bom_reference, is_current` | Current cost lookup |
| Standard rate cards | `rate_type, valid_from, is_active` | Rate card lookups |

---

## 8. Summary of What to Create

| # | Table | Required? | Purpose |
|---|---|---|---|
| 1 | Cost element master | Yes | The configurable cost taxonomy tree |
| 2 | BOM cost entries | Yes | All cost values at any level |
| 3 | Standard rate cards | Recommended | Reusable rates for pre-population |
| 4 | BOM cost rollup snapshots | Recommended | Cached published cost sheets |
| 5 | Materialized view (flattened) | Yes | Reporting-friendly pivot of the tree |

Total: 4 tables + 1 materialized view, plus seed data for the cost element tree.
