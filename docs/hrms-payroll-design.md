# Pay Register — Create & Process Workflow

> Step-by-step documentation of how payroll data is collected, calculated, and posted in the **vowerp3be** (FastAPI) backend.

---

## Table of Contents

1. [Overview](#overview)
2. [Tables Involved](#tables-involved)
3. [Step 1 — Create Pay Period](#step-1--create-pay-period)
4. [Step 2 — Validate Pay Period](#step-2--validate-pay-period)
5. [Step 3 — Fetch Mapped Employees](#step-3--fetch-mapped-employees)
6. [Step 4 — Fetch Pay Scheme Formulas](#step-4--fetch-pay-scheme-formulas)
7. [Step 5 — Fetch Component Metadata](#step-5--fetch-component-metadata)
8. [Step 6 — Fetch Employee Base Structure](#step-6--fetch-employee-base-structure)
9. [Step 7 — Fetch Custom Component Values](#step-7--fetch-custom-component-values)
10. [Step 8 — Delete Previous Payroll Data (Re-process)](#step-8--delete-previous-payroll-data-re-process)
11. [Step 9 — Calculate Payroll Per Employee](#step-9--calculate-payroll-per-employee)
12. [Step 10 — Insert Payroll Records](#step-10--insert-payroll-records)
13. [Step 11 — Insert Pay Period Summary Records](#step-11--insert-pay-period-summary-records)
14. [Step 12 — Update Pay Period Status](#step-12--update-pay-period-status)
15. [Formula Evaluation Engine](#formula-evaluation-engine)
16. [Data Flow Diagram](#data-flow-diagram)
17. [API Endpoints Summary](#api-endpoints-summary)

---

## Overview

The Pay Register process has **two phases**:

| Phase | API Endpoint | Action |
|-------|-------------|--------|
| **Phase 1: Create** | `POST /api/hrms/pay_register_create` | Creates a `pay_period` record (defines the payroll period, scheme, and branch) |
| **Phase 2: Process** | `POST /api/hrms/pay_register_process` | Calculates salary for all mapped employees and inserts results into `pay_employee_payroll` and `pay_employee_payperiod` |

**File:** `src/hrms/payRegister.py`  
**Queries:** `src/hrms/query.py`  
**Models:** `src/models/hrms.py`

---

## Tables Involved

### Master / Reference Tables (READ only during processing)

| # | Table Name | ORM Model | Purpose | Key Columns |
|---|-----------|-----------|---------|-------------|
| 1 | `pay_components` | `PayComponents` | Component master — all salary components (BASIC, HRA, DA, PF, etc.) | `ID`, `CODE`, `NAME`, `TYPE`, `ROUNDOF`, `ROUNDOF_TYPE`, `IS_CUSTOM_COMPONENT`, `company_id` |
| 2 | `pay_scheme` | `PayScheme` | Pay scheme master — groups of components with formulas | `ID`, `NAME`, `CODE`, `WAGE_ID`, `BUSINESSUNIT_ID` |
| 3 | `pay_scheme_details` | `PaySchemeDetails` | Formulas for each component within a scheme | `ID`, `COMPONENT_ID`, `FORMULA`, `PAY_SCHEME_ID`, `TYPE`, `DEFAULT_VALUE` |
| 4 | `pay_employee_payscheme` | `PayEmployeePayscheme` | Maps employees → pay schemes | `ID`, `EMPLOYEEID`, `PAY_SCHEME_ID`, `STATUS` |
| 5 | `pay_employee_structure` | `PayEmployeeStructure` | Per-employee base values (overrides scheme defaults) | `ID`, `EMPLOYEEID`, `PAYSCHEME_ID`, `COMPONENT_ID`, `AMOUNT` |
| 6 | `pay_components_custom` | `PayComponentsCustom` | Custom/variable values per employee per period (e.g., from Excel upload) | `ID`, `COMPONENT_ID`, `VALUE`, `EMPLOYEEID`, `PAY_PERIOD_ID` |
| 7 | `hrms_ed_personal_details` | `HrmsEdPersonalDetails` | Employee personal details | `eb_id`, `first_name`, `middle_name`, `last_name` |
| 8 | `hrms_ed_official_details` | `HrmsEdOfficialDetails` | Employee official details (branch, dept, emp code) | `eb_id`, `branch_id`, `emp_code`, `sub_dept_id` |
| 9 | `branch_mst` | — | Branch master | `branch_id`, `branch_name`, `co_id` |
| 10 | `status_mst` | — | Status master | `status_id`, `status_name` |
| 11 | `sub_dept_mst` | — | Sub-department master | `sub_dept_id`, `sub_dept_desc` |

### Transaction Tables (Written during processing)

| # | Table Name | ORM Model | Purpose | Key Columns |
|---|-----------|-----------|---------|-------------|
| 1 | `pay_period` | `PayPeriod` | Pay register header — defines the payroll period | `ID`, `FROM_DATE`, `TO_DATE`, `PAYSCHEME_ID`, `STATUS`, `branch_id`, `COMPANY_ID` |
| 2 | `pay_employee_payroll` | `PayEmployeePayroll` | **Main output** — one row per employee per component | `ID`, `EMPLOYEEID`, `COMPONENT_ID`, `PAYPERIOD_ID`, `PAYSCHEME_ID`, `AMOUNT`, `STATUS`, `BUSINESSUNIT_ID`, `SOURCE` |
| 3 | `pay_employee_payperiod` | `PayEmployeePayperiod` | Summary per employee — aggregated BASIC, NET, GROSS | `ID`, `EMPLOYEEID`, `PAY_PERIOD_ID`, `PAY_SCHEME_ID`, `BASIC`, `NET`, `GROSS`, `STATUS` |

---

## Step 1 — Create Pay Period

**Endpoint:** `POST /api/hrms/pay_register_create?co_id={co_id}`

**Request Body:**
```json
{
  "from_date": "2025-03-01",
  "to_date": "2025-03-31",
  "payscheme_id": 5,
  "branch_id": 10
}
```

**What happens:**

1. **Validate inputs** — `from_date`, `to_date`, `payscheme_id` are required
2. **Duplicate check** — Query `pay_period` to ensure no active record exists for the same from/to/scheme:
   ```sql
   SELECT COUNT(*) AS cnt FROM pay_period
   WHERE FROM_DATE = :from_date AND TO_DATE = :to_date
     AND PAYSCHEME_ID = :payscheme_id AND COMPANY_ID = :co_id
     AND STATUS NOT IN (4, 6, 28)   -- Exclude Rejected, Cancelled, Deleted
   ```
3. **Insert into `pay_period`:**

| Column | Value |
|--------|-------|
| `FROM_DATE` | from request body |
| `TO_DATE` | from request body |
| `PAYSCHEME_ID` | from request body |
| `branch_id` | from request body (optional) |
| `COMPANY_ID` | from `co_id` query param |
| `STATUS` | `1` (Open) |
| `updated_by` | current user ID from JWT |

**Result:** Returns `{ "data": { "id": <new_period_id>, "message": "..." } }`

---

## Step 2 — Validate Pay Period

**Endpoint:** `POST /api/hrms/pay_register_process?co_id={co_id}`

**Request Body:**
```json
{
  "pay_period_id": 42,
  "pay_scheme_id": 5,
  "branch_id": 10
}
```

**What happens:**

Query the `pay_period` table using ORM:
```python
PayPeriod.id == pay_period_id AND PayPeriod.co_id == co_id
```

If not found → return `404`. If found → proceed to Step 3.

**Table read:** `pay_period`

---

## Step 3 — Fetch Mapped Employees

**Data collected from:** `pay_employee_payscheme` + `hrms_ed_personal_details` + `hrms_ed_official_details`

```sql
SELECT DISTINCT
    eps.EMPLOYEEID AS eb_id,
    p.first_name, p.middle_name, p.last_name,
    o.emp_code, o.branch_id
FROM pay_employee_payscheme eps
JOIN hrms_ed_personal_details p ON p.eb_id = eps.EMPLOYEEID AND p.active = 1
LEFT JOIN hrms_ed_official_details o ON o.eb_id = eps.EMPLOYEEID AND o.active = 1
WHERE eps.PAY_SCHEME_ID = :pay_scheme_id
  AND eps.STATUS = 1
  AND (:branch_id IS NULL OR o.branch_id = :branch_id)
```

**Result:** List of `eb_id` values — the employees who will be processed.

If no employees found → return `400` error.

---

## Step 4 — Fetch Pay Scheme Formulas

**Data collected from:** `pay_scheme_details`

```sql
SELECT
    psd.COMPONENT_ID AS component_id,
    psd.FORMULA AS formula,
    psd.TYPE AS type,
    psd.DEFAULT_VALUE AS default_value
FROM pay_scheme_details psd
WHERE psd.PAY_SCHEME_ID = :pay_scheme_id AND psd.STATUS = 1
ORDER BY psd.TYPE, psd.COMPONENT_ID
```

**Result:** A dictionary mapping `component_id → formula`:
```python
{
    101: "35000",           # BASIC — fixed value
    102: "BASIC*0.5",       # HRA — 50% of BASIC
    103: "BASIC*0.2",       # DA — 20% of BASIC
    104: "BASIC+HRA+DA",    # GROSS — sum of earnings
    105: "BASIC*0.12",      # PF — 12% of BASIC
    106: "GROSS-PF",        # NET — deduction from gross
}
```

The `formula` field can be:
- A **plain number** (e.g., `"35000"`) — used as-is
- A **mathematical expression** referencing other component codes (e.g., `"BASIC*0.5"`)
- A **complex expression** with functions (e.g., `"Math.floor(GROSS*0.0075)"`)

---

## Step 5 — Fetch Component Metadata

**Data collected from:** `pay_components`

```sql
SELECT
    pc.ID AS id, pc.CODE AS code, pc.NAME AS name,
    pc.TYPE AS type, pc.DEFAULT_VALUE AS default_value,
    pc.IS_CUSTOM_COMPONENT AS is_custom_component,
    pc.ROUNDOF AS roundof, pc.ROUNDOF_TYPE AS roundof_type
FROM pay_components pc
WHERE pc.company_id = :co_id AND pc.STATUS = 1
ORDER BY pc.TYPE, pc.ID
```

**Result:** A dictionary mapping `component_id → metadata`:
```python
{
    101: {"id": 101, "code": "BASIC",  "name": "Basic Pay",  "type": 0, "roundof": 0, "roundof_type": 1, "is_custom_component": 0},
    102: {"id": 102, "code": "HRA",    "name": "House Rent",  "type": 1, "roundof": 0, "roundof_type": 1, "is_custom_component": 0},
    103: {"id": 103, "code": "DA",     "name": "Dearness",    "type": 1, "roundof": 0, "roundof_type": 1, "is_custom_component": 0},
    105: {"id": 105, "code": "PF",     "name": "Provident Fund", "type": 2, "roundof": 0, "roundof_type": 1, "is_custom_component": 0},
    110: {"id": 110, "code": "BONUS",  "name": "Bonus",       "type": 1, "roundof": 0, "roundof_type": 1, "is_custom_component": 1},
}
```

Key fields used during calculation:
- **`code`** — used to substitute references in formulas (e.g., `"BASIC"` in `"BASIC*0.5"`)
- **`type`** — `0` = input/base, `1` = earning, `2` = deduction
- **`roundof`** — number of decimal places for rounding
- **`roundof_type`** — rounding method: `0/1` = HALF_EVEN, `2` = DOWN (floor), `3` = UP (ceil)
- **`is_custom_component`** — `1` means value comes from upload (pay_components_custom)

---

## Step 6 — Fetch Employee Base Structure

**Data collected from:** `pay_employee_structure`

```sql
SELECT
    pes.EMPLOYEEID AS eb_id,
    pes.COMPONENT_ID AS component_id,
    COALESCE(pes.AMOUNT, 0) AS amount
FROM pay_employee_structure pes
WHERE pes.PAYSCHEME_ID = :pay_scheme_id AND pes.STATUS = 1
  AND pes.EMPLOYEEID IN (
      SELECT eps.EMPLOYEEID FROM pay_employee_payscheme eps
      WHERE eps.PAY_SCHEME_ID = :pay_scheme_id AND eps.STATUS = 1
  )
```

**Result:** A nested dictionary mapping `eb_id → { component_id → amount }`:
```python
{
    1001: {101: 40000.0, 102: 20000.0},  # Employee 1001: BASIC=40000, HRA=20000
    1002: {101: 35000.0},                 # Employee 1002: Only BASIC override
}
```

**Purpose:** These are per-employee overrides. If an employee has a record in `pay_employee_structure` for a component of `type = 0` (input type), it replaces the scheme's default formula for that component.

Example:
- Scheme formula for BASIC = `"35000"` (default)
- Employee 1001's structure has BASIC = `40000`
- → For employee 1001, BASIC formula becomes `"40000"` instead of `"35000"`

---

## Step 7 — Fetch Custom Component Values

**Data collected from:** `pay_components_custom`

```sql
SELECT
    pcc.EMPLOYEEID AS eb_id,
    pcc.COMPONENT_ID AS component_id,
    pcc.VALUE AS value
FROM pay_components_custom pcc
WHERE pcc.PAY_PERIOD_ID = :pay_period_id AND pcc.STATUS = 1
```

**Result:** A nested dictionary mapping `eb_id → { component_id → value_string }`:
```python
{
    1001: {110: "5000"},   # Employee 1001: BONUS = 5000 for this period
    1002: {110: "3000"},   # Employee 1002: BONUS = 3000 for this period
}
```

**Purpose:** These are **variable/custom values** that change every pay period — often uploaded via Excel. They override the scheme formula for components where `is_custom_component = 1`.

---

## Step 8 — Delete Previous Payroll Data (Re-process)

Before inserting new calculated data, any existing records for this period+scheme are deleted. This allows re-processing.

**Table:** `pay_employee_payroll`
```sql
DELETE FROM pay_employee_payroll
WHERE PAYPERIOD_ID = :pay_period_id AND PAYSCHEME_ID = :pay_scheme_id
```

**Table:** `pay_employee_payperiod`
```sql
DELETE FROM pay_employee_payperiod
WHERE PAY_PERIOD_ID = :pay_period_id AND PAY_SCHEME_ID = :pay_scheme_id
```

---

## Step 9 — Calculate Payroll Per Employee

This is the **core calculation engine**. For each employee, it:

### 9a. Build Employee-Specific Formula Map

Start with a copy of the **scheme formulas** (from Step 4):
```python
emp_formulas = {
    101: "35000",        # BASIC
    102: "BASIC*0.5",    # HRA
    103: "BASIC*0.2",    # DA
    104: "BASIC+HRA+DA", # GROSS
    105: "BASIC*0.12",   # PF
    106: "GROSS-PF",     # NET
}
```

### 9b. Apply Employee Base Structure Overrides (Step 6 data)

For each component where the employee has a record in `pay_employee_structure` and the component `type = 0` (input type):

```python
# Employee 1001 has BASIC override = 40000
emp_formulas[101] = "40000"  # Was "35000", now "40000"
```

### 9c. Apply Custom Component Overrides (Step 7 data)

For each component where the employee has a custom value and `is_custom_component = 1`:

```python
# Employee 1001 has BONUS custom value = 5000
emp_formulas[110] = "5000"  # Override from pay_components_custom
```

### 9d. Iterative Formula Evaluation

The formula evaluation engine resolves dependencies iteratively (up to 100 iterations):

**Iteration 1:**
| Component | Formula | Resolved? | Value |
|-----------|---------|-----------|-------|
| BASIC (101) | `"40000"` | ✅ Plain number | **40000.0** |
| HRA (102) | `"BASIC*0.5"` | ❌ Has reference "BASIC" | — |
| DA (103) | `"BASIC*0.2"` | ❌ Has reference "BASIC" | — |
| GROSS (104) | `"BASIC+HRA+DA"` | ❌ Has references | — |
| PF (105) | `"BASIC*0.12"` | ❌ Has reference | — |
| NET (106) | `"GROSS-PF"` | ❌ Has references | — |

**Iteration 2:** (BASIC is now resolved → substitute its value)
| Component | Formula After Substitution | Resolved? | Value |
|-----------|---------------------------|-----------|-------|
| HRA (102) | `"40000.0*0.5"` | ✅ Evaluates | **20000.0** |
| DA (103) | `"40000.0*0.2"` | ✅ Evaluates | **8000.0** |
| GROSS (104) | `"40000.0+HRA+DA"` | ❌ Still has HRA, DA refs | — |
| PF (105) | `"40000.0*0.12"` | ✅ Evaluates | **4800.0** |
| NET (106) | `"GROSS-PF"` | ❌ Still has refs | — |

**Iteration 3:** (HRA, DA, PF now resolved → substitute)
| Component | Formula After Substitution | Resolved? | Value |
|-----------|---------------------------|-----------|-------|
| GROSS (104) | `"40000.0+20000.0+8000.0"` | ✅ Evaluates | **68000.0** |
| NET (106) | `"GROSS-4800.0"` | ❌ Still has GROSS ref | — |

**Iteration 4:** (GROSS now resolved → substitute)
| Component | Formula After Substitution | Resolved? | Value |
|-----------|---------------------------|-----------|-------|
| NET (106) | `"68000.0-4800.0"` | ✅ Evaluates | **63200.0** |

✅ **All components resolved!**

### 9e. Rounding

After each component is calculated, rounding is applied based on `pay_components.ROUNDOF` and `pay_components.ROUNDOF_TYPE`:

| `ROUNDOF_TYPE` | Python Rounding | Example (4800.5, digits=0) |
|----------------|----------------|---------------------------|
| `0` or `1` | `ROUND_HALF_EVEN` (Banker's rounding) | 4800 |
| `2` | `ROUND_DOWN` (Floor) | 4800 |
| `3` | `ROUND_UP` (Ceil) | 4801 |

### 9f. Division by Zero Handling

If a formula results in division by zero (e.g., `BASIC/0.0`), the engine:
1. Detects patterns like `X/0.0`, `(0.0/0.0)`, `/(0.0+0.0)`
2. Replaces them with `0.0`
3. Returns `0.0` instead of crashing

### 9g. NaN/Infinity Check

After evaluation, if the result is `NaN` or `Infinity`, it's replaced with `0.0`.

---

## Step 10 — Insert Payroll Records

**Table written:** `pay_employee_payroll`

For **each employee × each component**, one row is inserted:

| Column | Value | Source |
|--------|-------|--------|
| `EMPLOYEEID` | Employee's `eb_id` | From Step 3 |
| `COMPONENT_ID` | Component ID | From Step 4 formula map |
| `PAYPERIOD_ID` | Pay period ID | From request body |
| `PAYSCHEME_ID` | Pay scheme ID | From request body |
| `AMOUNT` | Calculated value | From Step 9 calculation |
| `STATUS` | `1` (Success) | Constant |
| `BUSINESSUNIT_ID` | Branch ID | From request body |
| `SOURCE` | `"PROCESSED"` | Constant string |
| `updated_by` | Current user ID | From JWT token |

**Example rows inserted for Employee 1001:**

| EMPLOYEEID | COMPONENT_ID | PAYPERIOD_ID | AMOUNT | SOURCE |
|-----------|-------------|-------------|--------|--------|
| 1001 | 101 (BASIC) | 42 | 40000.00 | PROCESSED |
| 1001 | 102 (HRA) | 42 | 20000.00 | PROCESSED |
| 1001 | 103 (DA) | 42 | 8000.00 | PROCESSED |
| 1001 | 104 (GROSS) | 42 | 68000.00 | PROCESSED |
| 1001 | 105 (PF) | 42 | 4800.00 | PROCESSED |
| 1001 | 106 (NET) | 42 | 63200.00 | PROCESSED |

---

## Step 11 — Insert Pay Period Summary Records

**Table written:** `pay_employee_payperiod`

For **each employee**, one summary row is inserted:

| Column | Value | Source |
|--------|-------|--------|
| `EMPLOYEEID` | Employee's `eb_id` | From Step 3 |
| `PAY_PERIOD_ID` | Pay period ID | From request body |
| `PAY_SCHEME_ID` | Pay scheme ID | From request body |
| `BASIC` | BASIC component value | From calculated values (component name containing "BASIC") |
| `NET` | NET component value | From calculated values (component name containing "NET") |
| `GROSS` | GROSS component value | From calculated values (component name containing "GROSS", excluding "DEDUCTION") |
| `STATUS` | `1` (Success) | Constant |
| `updated_by` | Current user ID | From JWT token |

**Example row for Employee 1001:**

| EMPLOYEEID | PAY_PERIOD_ID | PAY_SCHEME_ID | BASIC | NET | GROSS | STATUS |
|-----------|-------------|-------------|-------|-----|-------|--------|
| 1001 | 42 | 5 | 40000.00 | 63200.00 | 68000.00 | 1 |

---

## Step 12 — Update Pay Period Status

**Table updated:** `pay_period`

```sql
UPDATE pay_period SET STATUS = 32, updated_by = :user_id WHERE ID = :pay_period_id
```

| Status ID | Meaning |
|-----------|---------|
| `1` | Open (after creation) |
| `32` | Processed (after payroll calculation) |
| `3` | Approved |
| `4` | Rejected |
| `6` | Cancelled |

---

## Formula Evaluation Engine

The formula engine (function `_evaluate_employee_formulas`) works as follows:

```
Input:
  component_formulas = { comp_id: formula_string, ... }
  components_meta    = { comp_id: { code, roundof, roundof_type, ... }, ... }

Algorithm:
  resolved = {}
  FOR iteration = 1 to 100:
    FOR each unresolved component:
      1. Try parsing formula as plain number → if success, mark resolved
      2. Substitute all resolved component CODES with their values
         e.g., "BASIC*0.5" → "40000.0*0.5"
      3. Handle division by zero patterns
      4. Try evaluating with safe_eval (restricted Python eval)
         - Only allows: numbers, +, -, *, /, (), math.floor, math.ceil
         - Rejects any alphabetic tokens (prevents code injection)
      5. Apply rounding based on component metadata
      6. Check for NaN/Infinity → replace with 0.0
      7. Store result, mark resolved

Output:
  { comp_id: calculated_float_value, ... }
```

**Security:** The `_safe_eval()` function uses Python's `eval()` with:
- `__builtins__` set to empty dict (no access to built-in functions)
- Only `math` module exposed (for `math.floor`, `math.ceil`)
- Pre-validation rejects any unresolved alphabetic references

---

## Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                    PHASE 1: CREATE PAY PERIOD                        │
│                                                                      │
│  User selects: From Date, To Date, Pay Scheme, Branch                │
│                         │                                            │
│                         ▼                                            │
│              ┌─────────────────────┐                                 │
│              │    pay_period       │  ← INSERT (status = 1 Open)     │
│              │    (new record)     │                                 │
│              └─────────────────────┘                                 │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                    PHASE 2: PROCESS PAYROLL                          │
│                                                                      │
│  ┌──────────────────────┐   ┌──────────────────────────┐            │
│  │ pay_employee_payscheme│──▶│ List of Employee IDs     │            │
│  │ (employee ↔ scheme)  │   │ (eb_id list)             │            │
│  └──────────────────────┘   └──────────────────────────┘            │
│                                         │                            │
│  ┌──────────────────────┐               │                            │
│  │ pay_scheme_details   │──▶ Formulas   │                            │
│  │ (component formulas) │   per comp    │                            │
│  └──────────────────────┘               │                            │
│                                         │                            │
│  ┌──────────────────────┐               │                            │
│  │ pay_components       │──▶ Metadata   │                            │
│  │ (code, rounding)     │   (code,type) │                            │
│  └──────────────────────┘               │                            │
│                                         ▼                            │
│  ┌──────────────────────┐   ┌──────────────────────────┐            │
│  │pay_employee_structure│──▶│ Per-Employee Formula Map  │            │
│  │ (base overrides)     │   │                          │            │
│  └──────────────────────┘   │ scheme_formula            │            │
│                              │   + base structure        │            │
│  ┌──────────────────────┐   │   + custom values         │            │
│  │pay_components_custom │──▶│                          │            │
│  │ (period-specific)    │   └────────────┬─────────────┘            │
│  └──────────────────────┘                │                           │
│                                          ▼                           │
│                              ┌──────────────────────────┐            │
│                              │  FORMULA ENGINE           │            │
│                              │  Iterative resolution:    │            │
│                              │  BASIC → HRA/DA/PF →      │            │
│                              │  GROSS → NET              │            │
│                              └────────────┬─────────────┘            │
│                                           │                          │
│               ┌───────────────────────────┼─────────────────┐        │
│               ▼                           ▼                 ▼        │
│  ┌─────────────────────┐  ┌────────────────────┐  ┌──────────────┐  │
│  │pay_employee_payroll │  │pay_employee_       │  │ pay_period   │  │
│  │ (1 row per emp×comp)│  │payperiod           │  │ (status→32)  │  │
│  │                     │  │ (1 row per emp,    │  │              │  │
│  │ INSERT: AMOUNT per  │  │  BASIC/NET/GROSS)  │  │ UPDATE       │  │
│  │ component           │  │                    │  │              │  │
│  └─────────────────────┘  └────────────────────┘  └──────────────┘  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## API Endpoints Summary

| # | Endpoint | Method | Purpose | Tables Read | Tables Written |
|---|---------|--------|---------|------------|----------------|
| 1 | `/api/hrms/pay_register_list` | GET | List all pay registers with pagination | `pay_period`, `pay_components`, `branch_mst`, `status_mst` | — |
| 2 | `/api/hrms/pay_register_by_id/{id}` | GET | Get single pay register details | `pay_period`, `pay_components`, `branch_mst`, `status_mst` | — |
| 3 | `/api/hrms/pay_register_create_setup` | GET | Dropdowns for create form | `pay_components` (TYPE=0), `branch_mst` | — |
| 4 | `/api/hrms/pay_register_create` | POST | Create a new pay period | `pay_period` (dup check) | `pay_period` (INSERT) |
| 5 | `/api/hrms/pay_register_update/{id}` | PUT | Update status/fields | `pay_period` | `pay_period` (UPDATE) |
| 6 | `/api/hrms/pay_register_salary` | GET | Pivoted salary grid (employee × components) | `pay_employee_payperiod`, `pay_employee_payroll`, `pay_components`, `hrms_ed_personal_details`, `hrms_ed_official_details`, `sub_dept_mst` | — |
| 7 | `/api/hrms/pay_register_process` | POST | **Process payroll** (calculate & insert) | `pay_period`, `pay_employee_payscheme`, `pay_scheme_details`, `pay_components`, `pay_employee_structure`, `pay_components_custom`, `hrms_ed_personal_details`, `hrms_ed_official_details` | `pay_employee_payroll` (INSERT), `pay_employee_payperiod` (INSERT), `pay_period` (UPDATE status→32) |

---

## Status Flow

```
  ┌──────────┐    Process     ┌──────────────┐    Approve     ┌──────────┐
  │  1 Open  │───────────────▶│ 32 Processed │───────────────▶│3 Approved│
  └──────────┘                └──────────────┘                └──────────┘
       │                            │                              
       │ Cancel                     │ Reject                       
       ▼                            ▼                              
  ┌──────────┐               ┌──────────────┐                     
  │6 Cancelled│              │  4 Rejected  │                     
  └──────────┘               └──────────────┘                     
```

---

## Example: Full Process for One Employee

**Given:**
- Pay Scheme "Monthly Staff" has components: BASIC, HRA, DA, PF, EPFR, ESI, GROSS, NET_PAY
- Employee Ravi (eb_id=1001) has base structure: BASIC=40000

**Step-by-step:**

| Step | Action | Source Table | Data |
|------|--------|-------------|------|
| 1 | Create period Jan 2025 | → `pay_period` | ID=42, status=1 |
| 2 | Validate period 42 exists | `pay_period` | ✅ |
| 3 | Get employees for scheme | `pay_employee_payscheme` | [1001, 1002, 1003] |
| 4 | Get scheme formulas | `pay_scheme_details` | BASIC="35000", HRA="BASIC*0.5", ... |
| 5 | Get component metadata | `pay_components` | code mappings, rounding rules |
| 6 | Get Ravi's base structure | `pay_employee_structure` | BASIC=40000 (overrides 35000) |
| 7 | Get Ravi's custom values | `pay_components_custom` | BONUS=5000 for this period |
| 8 | Delete old payroll data | `pay_employee_payroll` | Cleaned |
| 9 | Calculate formulas | (in-memory) | BASIC=40000, HRA=20000, DA=8000, GROSS=68000, PF=4800, NET=63200 |
| 10 | Insert payroll rows | → `pay_employee_payroll` | 6 rows (one per component) |
| 11 | Insert summary row | → `pay_employee_payperiod` | BASIC=40000, NET=63200, GROSS=68000 |
| 12 | Update period status | → `pay_period` | status = 32 (Processed) |
