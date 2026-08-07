# R-08-02 — Emulsion (Batching Oil Recipe & Oil %)
**Stage:** batching (selection/softening — spreader emulsion)  **Status:** UNBUILT
**Source tab:** `R-08-02-EMULSION` (master "Daily Summary Date Select")   **DSR workbook:** `1AJPvFasHh5fTGza869X7Sgq0m6sptV2eB6cKwEYt53Y` (DSR!A1:Z50, not shared)

## 1. Purpose
Daily log of the **batching emulsion (jute batching oil) recipe** applied at the spreader — how much oil, water/additives and emulsifier went into the tank, and the resulting **OIL % IN EMULSION**. It lets QC confirm the oil dosage stays inside the target band (so jute is softened consistently without over/under-oiling). This is a **recipe/consumption log, not a sampled-measurement report** — there is one row per date, no 10-reading sample, no StDev/CV%.

## 2. Inputs (the data-entry fields)
All fields are **header-level** (one record per date — there is no per-reading detail set). The cached sheet only ever populates a subset of the columns; the rest are alternative additive slots that stay blank for this mill but exist in the template.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| date | date | — (entry header) | yes | One row per calendar date (e.g. `2026-01-02`). Working days only — gaps in the cached data (no Sundays). |
| number_of_spreader_rolls_made | int | **Phase-2** link → spreader production txn | no | Blank in all cached rows. Note as Phase-2 production pull (briefing §4 decision #4). |
| oil_used_ltr | decimal | operator | yes | Jute batching oil charged, in litres. Cached = `170` every day. |
| tank_capacity_ltr | decimal | operator (or machine/tank master default) | yes | Emulsion tank size. Cached = `1000`. Effectively a constant → candidate default from a tank/machine master row. |
| adco_used_ml | decimal | operator | no | Cached = `0`. |
| eco_fin_used_ltr | decimal | operator | no | Cached = `0`. |
| oil_pct_in_emulsion | decimal | operator **or computed** | yes | Cached = `16`–`17` (e.g. `16.5`). ⚠️ See §4 — appears typed, not derived from oil_used/tank_capacity. |
| p40_gms | decimal | operator | no | "P-40 (Gms)". Cached = `500`. |
| efjl_kg | decimal | operator | no | "EFJL (Kg)". Blank in cached rows. |
| glycerine_gms | decimal | operator | no | Cached = `800`. |
| castrol_oil | decimal | operator | no | Blank. |
| diesel_ltr | decimal | operator | no | Blank. |
| others | text/decimal | operator | no | Blank — free additive slot. |
| citric_acid_ltr | decimal | operator | no | Blank. |
| enzyme_gms | decimal | operator | no | Blank. |
| treated_water_ltr | decimal | operator | no | Blank in cached rows, but conceptually the diluent that sets oil%. ⚠️ Confirm. |
| rbo_ltr | decimal | operator | no | "RBO (Ltr)" (rice bran oil). Blank. |
| jbo_ltr | decimal | operator | no | "JBO (Ltr)" (jute batching oil). Blank. |
| molasses_kg | decimal | operator | no | Blank. |
| urea_kg | decimal | operator | no | Blank. |
| biochemical_kg | decimal | operator | no | Blank. |
| jsp66 | decimal | operator | no | Blank. |
| feel_free_good_ve_kg | decimal | operator | no | Cached = `170` (mirrors oil_used — possibly the emulsifier brand). ⚠️ Confirm meaning. |
| prepared_by | text | user / `user_mst` | no | Footer "Report Prepared By" = "Sanjib Chakraborty". Default to logged-in user. |

The long additive tail (CASTROL…FEEL FREE) is a **fixed superset of recipe slots**; store them as nullable numeric columns (most stay NULL per mill) rather than a free EAV — they are a known, finite list.

## 3. Standards & constants used
| Standard / band | Example in sheet | Where it should live in VOW (decision #2: extend existing master) |
|---|---|---|
| Target **Oil % in emulsion** band | values cluster `16–17%` → implied target ≈ **16–17%** (jute batching norm ~ this range) | No existing per-quality key fits a *process-level* oil% target. Propose adding `std_oil_pct_low` / `std_oil_pct_high` to a **batching/spreader machine_mst row** (a machine implies its process) — see process×quality note below. |
| Standard tank capacity | `1000` ltr (constant) | Default value → store on the tank/spreader `machine_mst` row as `tank_capacity` (or keep as a typed input default). |
| Standard oil charge per batch | `170` ltr (constant) | Same machine row, `std_oil_charge_ltr`, as a recipe target. ⚠️ Confirm whether a hard target exists or it is just current practice. |

**⚠️ process×quality storage question (NEEDS OWNER DECISION):** the oil% target is a **batching-process** standard, not tied to a yarn/raw quality. It does not fit any existing per-quality master, yet decision #2 forbids a new standalone standards table. Two concrete reconciliations:
1. Add `std_oil_pct_low` / `std_oil_pct_high` (and optionally `tank_capacity`, `std_oil_charge_ltr`) columns to the **spreader/batching `machine_mst` row** — the machine fixes the process, so the band lives with the equipment. (Preferred — single emulsion line.)
2. If the band ever varies by jute blend/quality, instead key it on a **line-quality / batch master** row per blend. Mark as **NEEDS OWNER DECISION**.

## 4. Calculations (formulas)
This report is almost entirely **stored inputs**; the only candidate computed column is oil%.

- **oil_pct_in_emulsion** — *recorded directly* in the cached data (`16`, `16.5`, `17`). It is **not** reproducible from `oil_used_ltr / tank_capacity_ltr` (170/1000 = 17.0% would be constant, but cached values vary 16–17 on identical 170/1000 inputs). ⚠️ **Confirm:** oil% is measured/typed (e.g. lab titration of the live emulsion), NOT computed. Treat it as an **input**, optionally show `oil_used_ltr / tank_capacity_ltr × 100 = 17.0%` as a *reference* "theoretical oil%" beside the measured value.
- **oil_pct_status** (proposed, computed) = `OK` if `std_oil_pct_low ≤ oil_pct_in_emulsion ≤ std_oil_pct_high` else `LOW`/`HIGH`. Band from §3. Worked: `16.5` within `16–17` → **OK**.
- No StDev / CV% / bucket counts — single value per date, no sample (the universal CV% formula in briefing §4 does **not** apply here).

## 5. Worked example (real data)
Cached row dated **2026-01-05**:

| Input | Value |
|---|---|
| oil_used_ltr | 170 |
| tank_capacity_ltr | 1000 |
| adco_used_ml | 0 |
| eco_fin_used_ltr | 0 |
| oil_pct_in_emulsion (measured) | **16.5** |
| p40_gms | 500 |
| glycerine_gms | 800 |
| feel_free_good_ve_kg | 170 |

Outputs:
- theoretical oil% (reference) = 170 / 1000 × 100 = **17.0 %**
- measured oil% = **16.5 %** (stored input)
- oil_pct_status vs band 16–17 → **OK**

(Every cached working day is structurally identical: 170 / 1000 tank, oil% 16–17, P-40 500, glycerine 800, feel-free 170.)

## 6. Proposed VOW data model
Flat header table — no detail (one reading-set = one row). Recipe additives as nullable numeric columns.

```python
class JuteSqcEmulsion(Base):
    __tablename__ = "jute_sqc_emulsion"
    emulsion_id        = Column(Integer, primary_key=True, autoincrement=True)
    co_id              = Column(Integer, nullable=False, index=True)
    branch_id          = Column(Integer, nullable=True)
    entry_date         = Column(Date, nullable=False, index=True)   # one per date
    mc_id              = Column(Integer, nullable=True)             # spreader/emulsion machine_mst (process key)
    spreader_rolls_made= Column(Integer, nullable=True)            # Phase-2 production pull
    oil_used_ltr       = Column(DECIMAL(10, 2), nullable=True)
    tank_capacity_ltr  = Column(DECIMAL(10, 2), nullable=True)
    adco_used_ml       = Column(DECIMAL(10, 2), nullable=True)
    eco_fin_used_ltr   = Column(DECIMAL(10, 2), nullable=True)
    oil_pct_in_emulsion= Column(DECIMAL(5, 2), nullable=True)      # measured input
    p40_gms            = Column(DECIMAL(10, 2), nullable=True)
    efjl_kg            = Column(DECIMAL(10, 2), nullable=True)
    glycerine_gms      = Column(DECIMAL(10, 2), nullable=True)
    castrol_oil        = Column(DECIMAL(10, 2), nullable=True)
    diesel_ltr         = Column(DECIMAL(10, 2), nullable=True)
    citric_acid_ltr    = Column(DECIMAL(10, 2), nullable=True)
    enzyme_gms         = Column(DECIMAL(10, 2), nullable=True)
    treated_water_ltr  = Column(DECIMAL(10, 2), nullable=True)
    rbo_ltr            = Column(DECIMAL(10, 2), nullable=True)
    jbo_ltr            = Column(DECIMAL(10, 2), nullable=True)
    molasses_kg        = Column(DECIMAL(10, 2), nullable=True)
    urea_kg            = Column(DECIMAL(10, 2), nullable=True)
    biochemical_kg     = Column(DECIMAL(10, 2), nullable=True)
    jsp66              = Column(DECIMAL(10, 2), nullable=True)
    feel_free_good_ve_kg = Column(DECIMAL(10, 2), nullable=True)
    others             = Column(String(255), nullable=True)
    prepared_by        = Column(String(150), nullable=True)
    active             = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by         = Column(Integer, nullable=True)
    updated_date_time  = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```
- **PK** `emulsion_id`; one active row per `(co_id, entry_date)` (upsert-confirm like RHMR, since it is a daily singleton) — ⚠️ confirm with owner vs insert-only.
- Insert-only + soft-delete is acceptable too; given the daily-singleton nature, recommend **upsert-with-confirm** mirroring `JuteSqcSpinningRhmr`.

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC` (already registered).
- `GET /emulsion_create_setup` → dropdowns: spreader/emulsion machines (`machine_mst`, filtered to batching process), std oil% band + tank_capacity default from the machine row.
- `POST /emulsion_save` → insert/upsert one date's recipe; compute `oil_pct_status` server-side.
- `GET /emulsion_by_date?co_id&branch_id&entry_date` → single row for the date (+ theoretical oil% + status).
- `GET /emulsion_table?co_id&from&to` → date-range list for the summary grid (default month view).
- `POST /emulsion_delete` → soft delete (`active=0`).

**Frontend** (`juteSQC/emulsion/` or a tab in a batching SQC page):
- Mobile entry form: date + machine header, then oil_used / tank_capacity / oil% prominent, additives collapsed under "Additives (optional)". Default oil%-band hint and tank_capacity from setup.
- Desktop summary grid: one row per date over a chosen range, oil% column color-flagged vs band; route consts under `apiRoutesPortalMasters` (e.g. `EMULSION_SQC_*`); calls via `fetchWithCookie`.

**Masters to link:** `machine_mst` (spreader/emulsion line, process key + std columns), `user_mst` (prepared_by). No quality master needed (process-level recipe).

## 8. Open questions (NEEDS OWNER DECISION)
- Is **oil% measured/typed** (titration) or should VOW compute it? Cached values (16–17 on constant 170/1000) say **typed** — confirm.
- Exact **target oil% band** (16–17%? wider?) and whether it is a hard pass/fail or advisory.
- Where to store the oil% band + tank_capacity + std oil charge (decision #2): **batching `machine_mst` row** (preferred) vs a line-quality master — **process×quality storage question**.
- Meaning of `FEEL FREE GOOD VE (KG)` (= 170, mirrors oil_used) — is it the emulsifier and should it auto-fill from oil_used?
- Which additive columns are actually in use at this mill (most are blank) — keep full template superset or trim?
- One record per date enforced? Upsert-with-confirm vs insert-only-with-soft-delete.
- `number_of_spreader_rolls_made` — confirm Phase-2 pull from spreader production txn (decision #4).
- Confirm `treated_water_ltr` is the diluent that sets oil% even though blank in cached data.
