# Finishing Department — Spec Sheet & Design Document

**Status:** DESIGN / SPEC ONLY (no code yet) · **Target tenant:** `dev3` (QA) first
**Repos:** `vowerp3be` (FastAPI) + `vowerp3ui` (Next.js) · **Module:** Jute Production + Jute SQC
**Author:** generated from cross-repo research (legacy `vow_backend_2.0` / `vow-ui-2.0` for formulas & parameters; `spngTargetMap` / `beamingTargetMap` for the pattern).
**Last updated:** 2026-06-22

> This document is the agreed spec for the Finishing department. It captures the data
> model, the **applicable-parameters ("spec sheet") pattern**, every formula and
> parameter carried over from the legacy system, and the page/endpoint plan across both
> repos. **No implementation has been done** — the next step is to review/red-line this
> document, then build in the sequence in §10.

---

## 0. Scope (decisions captured)

| Decision | Choice |
|----------|--------|
| Deliverable | **Spec document only** (this file). Build follows after review. |
| Finishing structure | **Per finishing sub-process** — six stages: Damping → Calendering → Lapping → Cutting → Hemming → Bale Press. |
| Finished products | **Hessian cloth** (rolls, measured in metres/yards + kg) and **Jute bags** (pieces + bales). |
| Actual parameter capture | Via a **new Finishing SQC page** in the Jute SQC module (`value_role='actual'`), exactly like Spinning/Beaming SQC. |
| Quality lab tests (GSM, width, strength, moisture, …) | **Deferred (out of scope here).** Will be added later and wired in if required. This spec covers only actual *operating-parameter* capture, not lab/quality-test sampling. |
| Pattern to reuse | `spngTargetMap` / `beamingTargetMap` — EAV, effective-dated, applicable-params, generic `TargetGrid`. |

The legacy system tracked finishing as a single flat production entry; this spec
**deliberately upgrades** it to a per-sub-process model so each stage carries its own
machines, parameters, efficiency and quality checks.

---

## 1. Domain background — the jute finishing line

After weaving, grey cloth flows through the finishing line. For the two products in scope:

```
                         ┌─────────── HESSIAN CLOTH (rolls) ───────────┐
Grey cloth ─► Damping ─► Calendering ─► Lapping ─► (cloth done: rolls in m + kg)
   (loom)                    │
                            (calendered cloth) ─► Cutting ─► Hemming ─► Bale Press ─► (bags done: bales)
                         └──────────────────── JUTE BAGS (pieces → bales) ─────────────┘
```

| # | Sub-process | What happens | Input → Output (UoM) | Primary measure |
|---|-------------|--------------|----------------------|-----------------|
| 1 | **Damping** | Spray water/JBO emulsion to raise moisture for calendering | cloth m → damped cloth m | metres, moisture % |
| 2 | **Calendering** | Heated/pressured bowls flatten & finish the cloth | cloth m → finished cloth m + kg | metres, kg |
| 3 | **Lapping** | Measure & roll cloth into laps/rolls of fixed length | cloth m → rolls | rolls, metres |
| 4 | **Cutting** | Cut calendered cloth to bag length | cloth m → cut pieces | pieces |
| 5 | **Hemming** | Sew mouth/sides to form bags | pieces → bags | bags |
| 6 | **Bale Press** | Count & press bags into bales for dispatch | bags → bales | bales, bags |

Steps 1–3 finish **hessian cloth**; steps 4–6 convert calendered cloth into **jute bags**.

---

## 2. Architecture overview

Three layers, mirroring the existing Beaming feature (`jute_prod_bm_quality` +
`jute_prod_beaming_target_map` + `jute_prod_beaming_daily`):

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. MASTERS (juteProduction/masters)                                        │
│    • Finishing Quality Master      jute_prod_finishing_quality             │
│      (cloth & bag qualities + fixed structural specs)                      │
│    • Finishing Spec Sheet          jute_prod_finishing_target_map  ◄── EAV │
│      (= the "spec sheet": standard & target params, applicable per         │
│       process × machine|quality, effective-dated)                          │
├──────────────────────────────────────────────────────────────────────────┤
│ 2. PRODUCTION (juteProduction/finishing)                                   │
│    • Per-sub-process daily entry   jute_prod_finishing_daily (+ _param)    │
│      (resolves std/target from the spec sheet, computes eff & weight)      │
├──────────────────────────────────────────────────────────────────────────┤
│ 3. SQC (juteSQC/finishing)                                                 │
│    • Actual params  → jute_prod_finishing_target_map (value_role='actual') │
│    • Quality lab tests (GSM/strength/…) — DEFERRED, add & wire in later     │
└──────────────────────────────────────────────────────────────────────────┘
```

**Why this shape:** the user's instruction — *"finishing parameters saving based on the
applicable parameters"* — is exactly the target-map EAV model. The spec sheet stores
**only the parameters that apply** to each (process, machine|quality, role) combination,
effective-dated, and the SQC page feeds the `actual` role into the same table. This is the
proven Spinning/Beaming contract, extended with one new dimension: **`process`**.

---

## 3. The applicable-parameters ("spec sheet") pattern

Recap of the locked contract from `spng_target_map.py` / `beaming_target_map.py`, **plus
the one finishing extension**:

- **EAV storage:** one row per `(process, ref_id, id_type, value_role, param, effective_date)`.
- **`id_type`** discriminates the reference: `'mcid'` (ref_id = `machine_id`) or `'qid'`
  (ref_id = `finishing_quality_id`).
- **`value_role`:** `'standard'` | `'target'` | `'actual'`.
- **`process`** (NEW): `'damping' | 'calendering' | 'lapping' | 'cutting' | 'hemming' | 'balepress'`.
- **Applicable params** are returned by a single function, mirrored on FE + BE:

  ```python
  grid_params_for(process, id_type, value_role) -> list[str]
  ```

  The grid renders exactly the params this returns — nothing more. Adding/removing a
  parameter is a one-line change here (plus a label), never a schema migration.
- **Resolution:** last-date `MAX(effective_date) <= on_date`, branch-agnostic (a cell shows
  the same value production logic uses). `is_exact=false` ⇒ inherited from an earlier date
  (rendered muted/italic, as today).
- **Bulk save:** one transaction; per cell upsert at the exact
  `(process, co_id, ref_id, id_type, value_role, param, effective_date)` key; `value=null`
  ⇒ soft-delete (`active=0`).

The generic **`TargetGrid.tsx`** is reused unchanged. Only the page header gains a
**Process** selector before the existing Type / Role / Effective-Date selectors, and a new
`TargetMapEditor` variant passes `process` through to the endpoints.

---

## 4. Data model

All tables: `co_id` + `branch_id` scoping, soft-delete `active TINYINT DEFAULT 1`, audit
`updated_by` + `updated_date_time` (triggers handle the rest — **no** `created_*`). DDL
style matches `create_beaming_tables.sql`. Target tenant `dev3` first.

### 4.1 `jute_prod_finishing_quality` — Finishing Quality Master

One row per finishing quality. `quality_type` splits cloth vs bag; type-specific columns
are nullable. Structural specs that **never** change per-date live here; variable/standard
operating params live in the spec sheet (§4.2).

```sql
CREATE TABLE jute_prod_finishing_quality (
    finishing_quality_id   INT          NOT NULL AUTO_INCREMENT,
    co_id                  INT          NOT NULL,
    branch_id              INT          NULL,
    quality_type           TINYINT      NOT NULL,            -- 1=cloth, 2=bag
    item_id                INT          NOT NULL,            -- finished item (cloth roll / bag) in item_mst
    fin_quality_code       VARCHAR(50)  NOT NULL,
    fin_quality_name       VARCHAR(100) NULL,
    -- cloth structural specs (quality_type=1) --------------------------------
    width_in               DECIMAL(10,3) NULL,               -- finished cloth width (inches)
    ports                  INT          NULL,                -- ends per dent / porter
    ends                   INT          NULL,                -- total warp ends
    shots                  DECIMAL(10,3) NULL,               -- picks per inch (weft)
    oz_per_yd              DECIMAL(10,3) NULL,               -- weight per linear yard (oz)
    std_oz_per_yd          DECIMAL(10,3) NULL,               -- reference/standard oz/yd
    lead_length            DECIMAL(12,4) NULL,               -- warp lead length
    finished_length        DECIMAL(12,4) NULL,               -- standard cut/roll length
    mc_teeth               INT          NULL,
    -- bag structural specs (quality_type=2) ----------------------------------
    cloth_quality_id       INT          NULL,                -- cloth quality the bag is made from (self-FK)
    bag_length_in          DECIMAL(10,3) NULL,
    bag_width_in           DECIMAL(10,3) NULL,
    mouth_type             VARCHAR(30)  NULL,                -- open / hemmed / B.Twill / overhead
    bags_per_bale          INT          NULL,
    active                 TINYINT      NOT NULL DEFAULT 1,
    updated_by             INT          NULL,
    updated_date_time      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_quality_id),
    KEY idx_fq_co_item (co_id, item_id),
    KEY idx_fq_type (co_id, quality_type),
    CONSTRAINT fk_fq_item FOREIGN KEY (item_id) REFERENCES item_mst (item_id)
);
```

### 4.2 `jute_prod_finishing_target_map` — the Spec Sheet (EAV)

Identical to `jute_prod_beaming_target_map` **plus a `process` column** and an index that
leads with `process`.

```sql
CREATE TABLE jute_prod_finishing_target_map (
    finishing_target_map_id INT          NOT NULL AUTO_INCREMENT,
    co_id                   INT          NOT NULL,
    branch_id               INT          NULL,
    process                 VARCHAR(20)  NOT NULL,   -- damping|calendering|lapping|cutting|hemming|balepress
    effective_date          DATE         NOT NULL,
    ref_id                  INT          NOT NULL,   -- machine_id (mcid) | finishing_quality_id (qid)
    id_type                 VARCHAR(8)   NOT NULL,   -- 'mcid' | 'qid'
    value_role              VARCHAR(10)  NOT NULL,   -- 'standard' | 'target' | 'actual'
    param                   VARCHAR(24)  NOT NULL,   -- see §5 matrix
    value                   DECIMAL(12,4) NOT NULL DEFAULT 0.0000,
    active                  TINYINT      NOT NULL DEFAULT 1,
    updated_by              INT          NULL,
    updated_date_time       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_target_map_id),
    KEY idx_ftm_lookup (co_id, process, ref_id, id_type, value_role, param, effective_date),
    KEY idx_ftm_co (co_id)
);
```

### 4.3 `jute_prod_finishing_daily` (+ `_param`) — Production Entry

**Recommended hybrid:** one header per `(date, spell, process, machine, quality)` with the
**universal** production/efficiency columns typed, plus a small EAV detail
(`jute_prod_finishing_daily_param`) for the **process-specific** captured inputs/measured
values (temperature, pressure, lap length, cut length, …). This keeps reporting math
consistent across all six stages while letting each stage capture its own parameters
without six near-duplicate wide tables. (Alternative — six per-process daily tables — is
noted in §11.)

```sql
CREATE TABLE jute_prod_finishing_daily (
    finishing_daily_id     INT NOT NULL AUTO_INCREMENT,
    co_id                  INT NOT NULL,
    branch_id              INT NULL,
    tran_date              DATE NOT NULL,
    spell_id               INT NOT NULL,
    process                VARCHAR(20) NOT NULL,           -- which sub-process
    machine_id             INT NOT NULL,
    finishing_quality_id   INT NOT NULL,
    eb_id                  INT NULL,                        -- worker (labour-based stages)
    -- inputs / outputs (UoM depends on process; see §5) ----------------------
    input_qty              DECIMAL(14,4) NULL,             -- e.g. cloth metres in / pieces in
    input_uom              VARCHAR(10)  NULL,              -- 'm' | 'pcs' | 'bag'
    prod_qty               DECIMAL(14,4) NOT NULL,         -- output (m / rolls / pcs / bags / bales)
    prod_uom               VARCHAR(10)  NOT NULL,          -- 'm' | 'roll' | 'pcs' | 'bag' | 'bale'
    prod_wt_kg             DECIMAL(14,3) NULL,             -- output weight (cloth stages)
    wastage_kg             DECIMAL(14,3) NULL,             -- net wastage (gross-tare resolved on entry)
    -- resolved standards snapshot (from spec sheet at save) ------------------
    std_speed              DECIMAL(12,4) NULL,
    target_speed           DECIMAL(12,4) NULL,
    act_speed              DECIMAL(12,4) NULL,
    std_eff                DECIMAL(6,2)  NULL,
    target_eff             DECIMAL(6,2)  NULL,
    working_hours          DECIMAL(5,2)  NULL,
    -- computed outputs (snapshot) -------------------------------------------
    p100prod               DECIMAL(14,3) NULL,             -- 100% production for the period
    std_prod               DECIMAL(14,3) NULL,
    target_prod            DECIMAL(14,3) NULL,
    act_eff                DECIMAL(6,2)  NULL,             -- prod_qty / p100prod × 100
    active                 TINYINT NOT NULL DEFAULT 1,
    updated_by             INT NULL,
    updated_date_time      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (finishing_daily_id),
    KEY idx_fd_co_branch_date (co_id, branch_id, tran_date),
    KEY idx_fd_key (co_id, tran_date, spell_id, process, machine_id, finishing_quality_id),
    CONSTRAINT fk_fd_machine FOREIGN KEY (machine_id) REFERENCES machine_mst (machine_id),
    CONSTRAINT fk_fd_spell   FOREIGN KEY (spell_id)   REFERENCES spell_mst   (spell_id),
    CONSTRAINT fk_fd_quality FOREIGN KEY (finishing_quality_id) REFERENCES jute_prod_finishing_quality (finishing_quality_id)
);

CREATE TABLE jute_prod_finishing_daily_param (
    finishing_daily_param_id INT NOT NULL AUTO_INCREMENT,
    finishing_daily_id       INT NOT NULL,
    param                    VARCHAR(24) NOT NULL,   -- e.g. bowl_temp, nip_pressure, lap_length, cut_length…
    value                    DECIMAL(14,4) NULL,
    active                   TINYINT NOT NULL DEFAULT 1,
    PRIMARY KEY (finishing_daily_param_id),
    KEY idx_fdp_parent (finishing_daily_id),
    CONSTRAINT fk_fdp_parent FOREIGN KEY (finishing_daily_id)
        REFERENCES jute_prod_finishing_daily (finishing_daily_id)
);
```

### 4.4 Jute SQC — actuals only (quality-test tables DEFERRED)

For actual operating parameters (speed, temp, pressure, …) the Finishing SQC page writes
`value_role='actual'` rows into `jute_prod_finishing_target_map` — **no new SQC table is
needed**. This is the entire SQC data model for this phase.

**Deferred:** lab/quality-test sampling on finished cloth & bags (GSM, width, ends/picks,
moisture, breaking strength, porosity, oil %, shrinkage, bag weight, …). When required,
add a header+detail pair mirroring `jute_sqc_spinning_qr_cv` (+`_dtl`) with server-side
stats computed at read, and a "Quality Tests" tab on the Finishing SQC page. Not built now.

---

## 5. Parameter & formula catalog (the heart of the spec)

> **Proposed defaults** drawn from legacy `WeavingQuality` / `WeavingProductionServiceImpl`
> / `BeamingProductionReportImpl` and jute-industry practice. **Please red-line** — these
> drive `grid_params_for()` and the SQC fields.

### 5.1 Applicable-parameter matrix (spec sheet)

`param` values returned by `grid_params_for(process, id_type, value_role)`. `mcid` =
machine, `qid` = finishing quality. `actual` is captured on the SQC page.

| Process | mcid · standard | mcid · target | qid · standard | qid · target | actual (mcid / qid) |
|---------|-----------------|---------------|----------------|--------------|---------------------|
| **Damping** | `speed`, `spray_rate` | `speed` | `moisture_add_pct`, `emulsion_pct` | `moisture_add_pct` | `speed` / `moisture_add_pct` |
| **Calendering** | `speed`, `bowl_temp`, `nip_pressure`, `no_of_bowls` | `speed` | `finished_width`, `oz_per_yd`, `eff` | `eff` | `speed`, `bowl_temp` / `finished_width`, `oz_per_yd` |
| **Lapping** | `speed` | `speed` | `lap_length`, `roll_width`, `eff` | `eff` | `speed` / `lap_length` |
| **Cutting** | `speed`, `eff` | `speed`, `eff` | `cut_length`, `pieces_per_100m` | `eff` | `speed` / `cut_length` |
| **Hemming** | `speed`, `stitches_per_in`, `eff` | `speed`, `eff` | `hem_allowance` | `eff` | `speed` / `hem_allowance` |
| **Bale Press** | `press_pressure`, `cycle_time` | `press_pressure` | `bags_per_bale`, `bale_weight`, `eff` | `bale_weight` | `press_pressure` / `bale_weight` |

**Param units & meaning**

| param | unit | notes |
|-------|------|-------|
| `speed` | m/min (cloth) or pcs/min (cutting) or bags/hr (hemming) | machine running speed; UoM by process |
| `spray_rate` | l/min | damping water/emulsion flow |
| `moisture_add_pct` | % | target moisture to add (damping) |
| `emulsion_pct` | % | JBO emulsion concentration |
| `bowl_temp` | °C | calender bowl temperature |
| `nip_pressure` | kg/cm² | calender nip pressure |
| `no_of_bowls` | count | active calender bowls |
| `finished_width` | inch | width after calendering |
| `oz_per_yd` | oz/yd | linear weight (GSM proxy) |
| `lap_length` | m/roll | metres per lap/roll |
| `roll_width` | inch | finished roll width |
| `cut_length` | inch | piece length = bag length + allowances |
| `pieces_per_100m` | count | yield of pieces per 100 m cloth |
| `stitches_per_in` | count | sewing density |
| `hem_allowance` | inch | hem/seam allowance |
| `press_pressure` | tonne | bale press force |
| `cycle_time` | sec | press cycle time |
| `bags_per_bale` | count | bags packed per bale |
| `bale_weight` | kg | finished bale weight |
| `eff` | % | standard/target efficiency |

### 5.2 Formulas (carried from legacy, adapted per process)

**F1 — Cloth production weight (kg)** — from `WeavingProductionServiceImpl:56` and
`BeamingProductionReportImpl:46` (identical, since 16 × 2.2 = 35.2):

```
total_yards   = prod_qty_metres × 1.09361            # if prod captured in metres
prod_wt_kg    = (total_yards × oz_per_yd) / 35.2
              ≡ (total_yards × oz_per_yd) / (16 × 2.2)
```
Used by Calendering/Lapping output weight. `oz_per_yd` from the quality (or its `actual`).

**F2 — 100% production for the period (`p100prod`)** — length-basis (cloth stages):

```
p100prod_m = std_speed_m_per_min × working_minutes × n_machines
```
Piece-basis (Cutting/Hemming/Bale Press): replace `std_speed_m_per_min` with the stage's
std speed in pcs/min (or bags/hr → ÷60). `working_minutes` from `spell_mst.working_hours`
(fallback constants as in `constants.py SPELL_MINUTES`).

**F3 — Actual efficiency** — length/piece basis (matches beaming `act_eff`):

```
act_eff_pct = (prod_qty / p100prod) × 100
std_prod    = p100prod × std_eff   / 100
target_prod = p100prod × target_eff / 100
```

**F4 — Legacy weaving efficiency** (kept for reference / optional cross-check on cloth):

```
eff = ((cuts × finished_length × 100)
       / (((speed × working_hours × 60) / actual_shots) × 36)) × no_of_loom
```
(`WeavingProductionServiceImpl:62`.) Our F2/F3 are the generalised form; F4 documented so
weaving-derived standards reconcile.

**F5 — Cutting yield (pieces)**:

```
pieces = floor( (cloth_length_in_per_unit) / cut_length )          # per cloth piece
or  pieces = prod_qty_metres × 39.3701 / cut_length                # metres → inches → pcs
```

**F6 — Bag → bale roll-up**:

```
bales      = floor(total_bags / bags_per_bale)
bale_wt_kg = bags_per_bale × avg_bag_weight_kg          # cross-check vs std bale_weight
```

**F7 — Damping moisture add** (operating parameter, not a lab test):

```
moisture_add_pct = (damped_wt - grey_wt) / grey_wt × 100
```

> Lab/quality-test formulas (regain, GSM, breaking strength, shrinkage, …) are **deferred**
> with the quality-testing feature (§4.4) and intentionally omitted here.

### 5.3 Finishing SQC quality-test parameters — DEFERRED

Lab/quality-test sampling on finished cloth & bags (GSM, width, ends/picks, moisture,
breaking strength, porosity, oil %, shrinkage, bag weight, …) is **out of scope for this
phase**. It will be added later and wired into the Finishing SQC page if required (see
§4.4). The legacy parameter list (from `SqcTestA` / `SqcTestB`) is preserved in git history
of this doc for when that work starts.

---

## 6. Backend design (`vowerp3be`)

### 6.1 File layout (mirrors beaming)

```
src/juteProduction/
  finishing_models.py      # ORM: JuteProdFinishingQuality, JuteProdFinishingTargetMap,
                           #      JuteProdFinishingDaily, JuteProdFinishingDailyParam
  finishing_masters.py     # Finishing Quality Master CRUD endpoints
  finishing_target_map.py  # Spec-sheet endpoints (setup/grid/bulk_save/list/CRUD) + grid_params_for
  finishing_entry.py       # Per-sub-process production entry endpoints
  finishing_query.py       # text() SQL builders (resolve_cell, find_exact, machines, qualities…)
  constants.py             # ADD finishing process/param constants (see below)
src/juteSQC/
  finishing_sqc.py         # Finishing SQC endpoints — ACTUALS ONLY (proxy to target_map)
                           # (quality-test endpoints/models DEFERRED — see §4.4)
src/test/
  test_juteProduction_finishing_target_map.py
  test_juteProduction_finishing_entry.py
  test_juteSQC_finishing.py   # covers the actuals proxy only
```

Add to `src/juteProduction/constants.py`:

```python
# --- Finishing --------------------------------------------------------------
FINISHING_PROCESSES = ("damping", "calendering", "lapping", "cutting", "hemming", "balepress")
FINISHING_ID_TYPE_MC   = "mcid"
FINISHING_ID_TYPE_QLTY = "qid"
FINISHING_VALUE_ROLES  = ("standard", "target", "actual")
# Per-process applicable params (drive grid_params_for) — see SPEC §5.1
FINISHING_PARAMS = {
  "damping":     {"mcid": {"standard": ("speed","spray_rate"), "target": ("speed",), "actual": ("speed",)},
                  "qid":  {"standard": ("moisture_add_pct","emulsion_pct"), "target": ("moisture_add_pct",), "actual": ("moisture_add_pct",)}},
  "calendering": {"mcid": {"standard": ("speed","bowl_temp","nip_pressure","no_of_bowls"), "target": ("speed",), "actual": ("speed","bowl_temp")},
                  "qid":  {"standard": ("finished_width","oz_per_yd","eff"), "target": ("eff",), "actual": ("finished_width","oz_per_yd")}},
  "lapping":     {"mcid": {"standard": ("speed",), "target": ("speed",), "actual": ("speed",)},
                  "qid":  {"standard": ("lap_length","roll_width","eff"), "target": ("eff",), "actual": ("lap_length",)}},
  "cutting":     {"mcid": {"standard": ("speed","eff"), "target": ("speed","eff"), "actual": ("speed",)},
                  "qid":  {"standard": ("cut_length","pieces_per_100m"), "target": ("eff",), "actual": ("cut_length",)}},
  "hemming":     {"mcid": {"standard": ("speed","stitches_per_in","eff"), "target": ("speed","eff"), "actual": ("speed",)},
                  "qid":  {"standard": ("hem_allowance",), "target": ("eff",), "actual": ("hem_allowance",)}},
  "balepress":   {"mcid": {"standard": ("press_pressure","cycle_time"), "target": ("press_pressure",), "actual": ("press_pressure",)},
                  "qid":  {"standard": ("bags_per_bale","bale_weight","eff"), "target": ("bale_weight",), "actual": ("bale_weight",)}},
}
```

### 6.2 Endpoints

**Spec sheet** — router prefix `/api/finishingTargetMap` (clone of `beamingTargetMap`, plus
`process` on every call):

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/target_map_setup` | machines (finishing dept) + finishing qualities + processes + roles + params |
| GET | `/target_map_grid` | inline grid: `co_id, process, id_type, value_role, effective_date[, branch_id]` |
| POST | `/target_map_bulk_save` | upsert/clear cells (body adds `process`) |
| GET | `/target_map_list` | flat list (filters incl. `process`) |
| POST/PUT/DELETE | `/target_map_create` · `/target_map_edit/{id}` · `/target_map_delete/{id}` | single-row CRUD |

**Finishing Quality Master** — prefix `/api/finishingMasters`: standard list/create/edit/
delete/setup (cloth & bag qualities; bag rows reference a cloth quality).

**Production entry** — prefix `/api/finishingProd`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/entry_setup` | for a `(process, date, branch)`: machines, qualities, spells, resolved std/target snapshot, existing rows |
| POST | `/entry_save` | insert/upsert daily rows; server resolves std/target from spec sheet & computes F1–F6; writes header + `_param` |
| GET | `/entry_by_date` | rows + computed columns for `(process, date)` |
| DELETE | `/entry_delete/{id}` | soft-delete |

**Finishing SQC** — prefix `/api/juteSQC` (shared with existing SQC) — **actuals only**:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/finishing_sqc_setup` | machines, qualities, processes, param defs |
| GET | `/finishing_sqc_actual_grid` | actuals grid (proxy → `finishing_target_map` grid, `value_role='actual'`) |
| POST | `/finishing_sqc_actual_save` | proxy → `finishing_target_map` bulk_save with `value_role='actual'` |

> Quality-test endpoints (`/finishing_sqc_test_*`) are **deferred** with the quality-testing
> feature (§4.4) and not built in this phase.

All Portal persona → `Depends(get_tenant_db)` + `get_current_user_with_refresh`, responses
wrapped `{"data": …}`. Register routers in `src/main.py` next to the beaming block.

### 6.3 Key query functions (`finishing_query.py`)

Clone the beaming/spng builders, adding `process` to every WHERE/key:
`resolve_finishing_grid_cell_query` (last-date, branch-agnostic),
`find_exact_finishing_grid_row_query`, `update/clear_finishing_grid_value_query`,
`get_finishing_machines_query` (finishing dept/machine-type), `get_finishing_qualities_query`.

---

## 7. Frontend design (`vowerp3ui`)

### 7.1 Pages & routes

```
src/app/dashboardportal/juteProduction/masters/
  finishingQualityMaster/         # cloth & bag qualities (master-page pattern)
  finishingSpecSheet/             # the spec sheet (target map) — Process+Type+Role+Date
    page.tsx
    _components/TargetMapEditor.tsx   # variant that passes `process`
    # reuse the shared generic TargetGrid (copy or lift to src/components)
src/app/dashboardportal/juteProduction/finishing/
  page.tsx                        # process hub (6 tiles) OR tabbed entry container
  damping/ calendering/ lapping/ cutting/ hemming/ balePress/
    page.tsx + _components + hooks + types     # per-sub-process entry
src/app/dashboardportal/juteSQC/
  finishing/                      # NEW SQC tile target
    page.tsx                      # Actual Params only (reuses TargetMapEditor, value_role='actual')
    _components/  hooks/  types/sqcFinishingTypes.ts
    # (a "Quality Tests" tab is DEFERRED — see §4.4)
```

Route constants in `src/utils/api.ts` (`apiRoutesPortalMasters`), e.g.
`FINISHING_TARGET_MAP_GRID`, `FINISHING_TARGET_MAP_BULK_SAVE`, `FINISHING_QUALITY_*`,
`FINISHING_PROD_*`, `FINISHING_SQC_*` (same naming style as `BEAMING_TARGET_MAP_*`).

### 7.2 Spec-sheet page wireframe

Mirror `beamingTargetMap/page.tsx`, adding the **Process** selector as the first control:

```
Finishing Spec Sheet (Standards / Targets)
[ Process ▾ ] [ Type ▾ ] [ Role ▾ ] [ Effective Date 📅 ]      (Actuals → Finishing SQC)
┌───────────────────────────────────────────────────────────────┐
│ Code   Name           <applicable params for process+type+role> │
│ CAL-1  Calender M/c 1   [speed][bowl_temp][nip_pressure][bowls]  │  (mcid·standard)
│ …                                                               │
└───────────────────────────────────────────────────────────────┘
                                              [ Save ]  (dirty cells highlighted)
```

`ready = coId && process && idType && valueRole && effectiveDate`. Grid auto-renders only
the params the backend returns; inherited cells muted/italic with source-date tooltip.

### 7.3 Per-sub-process entry wireframe (e.g. Calendering)

```
Calendering Production — [Date 📅] [Spell ▾] [Branch ▾]
Header: Machine ▾ · Quality ▾ · Operator(EB) ▾
Inputs: Input cloth (m) · Output cloth (m) · Output wt (kg, auto F1) · Wastage (kg)
Process params (from §5.1 mcid·actual + qid): bowl_temp · nip_pressure · finished_width · oz_per_yd
Auto (read-only): std_speed/target_speed (spec sheet) · p100prod (F2) · std/target prod (F3) · act_eff (F3)
[ Add row ]   grid of today's entries   [ Save ]
```

Every page honours `SidebarContext` `co_id`/`branch_id`; Zod schema per page; no `any`;
`fetchWithCookie` only. Cloth stages show weight & metres; bag stages show pieces/bags/bales.

### 7.4 SQC landing tile

Add a 4th tile to `src/app/dashboardportal/juteSQC/page.tsx`:

```ts
{ href: "/dashboardportal/juteSQC/finishing",
  title: "Finishing SQC",
  subtitle: "Actual finishing operating parameters by process & machine/quality",
  icon: <Layers size={32} className="text-blue-600" /> }
```

The Finishing SQC page captures **Actual Params** only: it reuses the `TargetMapEditor` with
`value_role='actual'` and Process+Type selectors → writes `finishing_target_map`. A
**Quality Tests** tab (GSM/width/strength/etc.) is **deferred** and will be wired in later if
required (§4.4).

---

## 8. Menu & permissions

Seed `menu_mst` rows in `dev3` (pattern from `seed_beaming_sqc_menu.sql` — `menu_mst` only,
roles granted by tenant admin afterwards):

| Menu | Parent | Path |
|------|--------|------|
| Finishing Quality Master | Jute Production masters | `juteProduction/masters/finishingQualityMaster` |
| Finishing Spec Sheet | Jute Production masters | `juteProduction/masters/finishingSpecSheet` |
| Finishing Production | Jute Production | `juteProduction/finishing` |
| Finishing SQC | Jute SQC | `juteSQC/finishing` |

Portal action-level permissions (view/print/create/edit) apply as for other portal pages.

---

## 9. Cross-entity traceability

```
weaving cloth (item) ─► finishing_daily(process=damping) ─► …calendering ─► …lapping  (cloth rolls)
                                         └► …cutting ─► …hemming ─► …balepress         (bags → bales)
finishing_quality(quality_type=2 bag).cloth_quality_id ─► finishing_quality(quality_type=1 cloth)
finishing_daily.* ─► spec sheet resolved snapshot (std/target) at save time
SQC actual (target_map value_role='actual') ─► resolved as act_speed on next entry
```

Keep the snapshot-at-save discipline used by `jute_prod_beaming_daily` so historical rows
are immune to later master/spec edits.

---

## 10. Build sequencing (after this spec is approved)

1. **Migrations** (`dbqueries/migrations/`, target `dev3`): `create_finishing_tables.sql`
   (quality, target_map, daily, daily_param), `seed_finishing_menu.sql`, plus finishing
   machine-type / dept rows if absent (cf. `create_beaming_item_type_and_machine_type.sql`).
   *(No SQC quality-test tables this phase — actuals reuse `finishing_target_map`.)*
2. **ORM models** — `finishing_models.py`, extend `juteSQC/models.py`.
3. **Backend** — `finishing_target_map.py` + `finishing_query.py` first (spec sheet),
   then `finishing_masters.py`, then `finishing_entry.py`, then `juteSQC/finishing_sqc.py`;
   register routers; add constants.
4. **Tests** — pytest per the repo pattern (mocked DB/auth).
5. **Frontend** — route constants → Finishing Quality Master → Finishing Spec Sheet
   (TargetMapEditor variant) → per-sub-process entry pages → Finishing SQC tab page.
6. **Verify** — `pytest`, `npx tsc --noEmit`, `pnpm lint`; manual smoke on `dev3`.

Recommended order of value: **Spec Sheet + Quality Master first** (they unblock everything),
then **Calendering** as the first production stage (richest params), then the rest.

---

## 11. Open decisions to confirm (red-line before build)

1. **§5.1 parameter matrix** — confirm/adjust params per process (these are proposed).
2. **§5.2 formulas** — confirm production UoM per stage (metres vs yards for cloth; pieces
   vs bags for bag stages) and that F1/F2/F3 match how the mill currently reports efficiency.
3. **Production table shape** — recommended hybrid (`finishing_daily` + `_param` EAV) vs the
   alternative of **six per-process daily tables** (more typed columns, more DDL). Default:
   hybrid.
4. **Damping/Lapping** — does the mill log these as separate production entries, or only
   record Calendering output + bag stages? (Affects which of the six entry pages we build.)
5. **Spec-sheet page name** — "Finishing Spec Sheet" vs "Finishing Standards / Targets"
   (the latter matches the Beaming page wording).
6. **Wastage** — capture gross/tare/net like legacy `WastageEntry`, or just net kg on the
   entry? Default: net kg on entry, with a note to add a dedicated wastage screen later.
7. **Dispatch** — legacy had a Finishing Dispatch register (vehicle/challan/bale detail).
   Out of scope here? Default: out of scope (handled by Sales/Dispatch).

---

## 12. Appendix — source references

**Pattern (vowerp3be / vowerp3ui):**
- `src/juteProduction/beaming_target_map.py`, `spng_target_map.py` — endpoints + `grid_params_for`
- `src/juteProduction/beaming_models.py`, `constants.py` (§104–143) — table & param constants
- `dbqueries/migrations/create_beaming_tables.sql` — DDL template (this doc's §4 follows it)
- `dbqueries/migrations/seed_beaming_sqc_menu.sql` — menu seed template
- `src/juteSQC/models.py`, `spinning_sqc.py` — SQC header/detail + server-side stats
- FE: `juteProduction/masters/beamingTargetMap/{page.tsx,_components/TargetMapEditor.tsx,_components/TargetGrid.tsx}`
- FE: `juteSQC/page.tsx` (landing tiles), `juteSQC/spinning` & `juteSQC/beaming` (actuals via TargetMapEditor)

**Legacy formulas & parameters (vow_backend_2.0 / vow-ui-2.0):**
- `sls-po_api-service/.../WeavingProductionServiceImpl.java:56,62` — production-kg (F1) & weaving eff (F4)
- `sls-vowjute_reports-service/.../BeamingProductionReportImpl.java:44–54` — yards/kg/eff
- `sls-entity-library/.../master/WeavingQuality.java` — width, ports, shots, ends, finished/lead length, oz/yd, std oz/yd, actual_shots, mc_teeth
- `sls-entity-library/.../po/FinishingEntries.java` — legacy flat finishing entry (spell, work_type, eb_no, production, machine_id)
- `sls-entity-library/.../vowjute/FinishedGoodEntry.java` — finished product types
- `sls-entity-library/.../po/WastageEntry.java` — gross/tare/net wastage
- `sls-entity-library/.../alm/SqcTestA.java`, `SqcTestB.java` — DEFERRED quality-test params (not used this phase; kept for the future quality-testing feature)
- `Pages/JuteProduction/FinishingEntry/`, `Pages/Master/WeavingQualityMaster/` (vow-ui-2.0) — legacy screens
```
