# HUMIDITY — Humidity Recording (Department-wide Temperature & RH%)
**Stage:** plant-wide (batching / preparing / spinning / weaving / finishing)  **Status:** UNBUILT
**Source tab:** `DEPARTMENT WISE TEMPERATURE & RH%` (master "Daily Summary Date Select")   **DSR workbook:** `18uia3cprcm6pjoItt_26V8m7j8CBqQHybtmcSG293Ao` (REPORT!V3:AF46, not shared)

## 1. Purpose
Records ambient **temperature (°C) and relative humidity (RH%)** across every production department, three fixed spots per department, three times a day (morning/noon/evening). Jute processing is humidity-sensitive (fibre moisture affects spinning/weaving), so this confirms each department's conditions stay in band throughout the shift. This is the **plant-wide** humidity log — distinct from the already-built spinning-only RHMR (`JuteSqcSpinningRhmr`), which it generalises to all departments and to per-spot detail.

## 2. Inputs (the data-entry fields)
One report = one **date**. Within it, a fixed set of **departments**, each with **3 named spots**, and **3 time-rounds** (morning/noon/evening). Per spot per round the operator enters TIME, TEMP, RH%. AVG TEMP / AVG RH% across the 3 spots are computed.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| report_date | date | entry header | yes | "FOR THE DATED" = `2026-01-05`. One report per date. |
| department | int | **`dept_mst`** (`dept_id`, `dept_desc`) by `branch_id` (morrah uses it) | yes (section header) | Cached depts: BATCHING, PREPARING, SPINNING, WEAVING, SEWING (FINISHING), BALE PRESS (FINISHING). ⚠️ Some are sub-areas of one dept_mst row — see §3. |
| spot_no | int (1–3) | per-department spot definition | yes | Three spots per department. |
| spot_label | text | spot master / config | yes | e.g. "1st spot-Near Spdr.1", "2nd spot-Near fr.no. 28", "3rd spot-Near S-4 Loom no.68". A fixed named location per (dept, spot_no). |
| round_no | int (1–3) | — | yes | 1=morning, 2=noon, 3=evening (cached ≈ 07:55 / 12:17 / 16:24). |
| reading_time | time | operator | yes (per-reading) | e.g. `07:55:09`. Stored in sheet as Google fractional-day (`0.32996…` = 07:55:09) — store as SQL `TIME`. |
| temp_c | decimal | operator (per-reading) | yes | °C, e.g. `17`, `17.6`, `18.4`. |
| rh_pct | decimal | operator (per-reading) | yes | %, e.g. `75`, `72`, `70`. |
| prepared_by | text | `user_mst` | no | (footer in sibling reports). |

Header = report_date. Per-reading = one (department, spot_no, round_no) row with time/temp/rh. **AVG TEMP / AVG RH%** columns are computed (not entered).

## 3. Standards & constants used
| Standard / band | Example in sheet | Where it should live in VOW (decision #2: extend existing master) |
|---|---|---|
| **Spots per department** | 3 named spots (e.g. "Near fr.no. 2/28/66" for spinning) | These spot labels are **configuration**, not free text. Store on a **`dept_mst`-keyed spot config** (extend dept master with child spot rows) OR as a small per-dept spot list. ⚠️ Decision #2 forbids a new standalone master — propose linking spots to `dept_mst` (3 spot label columns or a dept-spot map keyed by `dept_id`). |
| **Rounds per day** | 3 (morning/noon/evening) | Constant `3` (or link to `spell_mst` if rounds map to spells A1/A2/B). ⚠️ Confirm rounds = spells. |
| **Acceptable Temp band per department** | not shown numerically in cache; jute target typically narrow | No existing per-dept slot. See process×quality note. |
| **Acceptable RH% band per department** | not shown numerically; spinning runs higher RH (cached spinning RH ~80% AM vs weaving ~74%) | No existing per-dept slot. See note. |

**⚠️ process×quality (here process×department) storage question (NEEDS OWNER DECISION):** the acceptable Temp/RH% bands differ **per department** (spinning needs higher RH than weaving), and the existing built `JuteSqcSpinningRhmr` carries no band columns. Decision #2 forbids a standalone standards master. Concrete reconciliations:
1. Add `std_temp_low`/`std_temp_high`/`std_rh_low`/`std_rh_high` columns to **`dept_mst`** rows (department fixes the band) — preferred, since the report is department-keyed.
2. If bands vary by season/shift too, key them on a dept×spell combination using existing `dept_mst` + `spell_mst` rather than a new table. Mark **NEEDS OWNER DECISION**.

Also: the cached department list mixes true departments with named **sub-areas** ("SEWING DEPARTMENT(FINISHING)", "BALE PRESS (FINISHING)" are both finishing). ⚠️ Confirm mapping of these section labels to actual `dept_mst.dept_id` rows.

## 4. Calculations (formulas)
Per department, per round, across the 3 spots:
- **AVG TEMP** = `(temp_spot1 + temp_spot2 + temp_spot3) / 3`.
- **AVG RH%** = `(rh_spot1 + rh_spot2 + rh_spot3) / 3`.
Rounded to 2 decimals (sheet shows `16.67`, `76.33`).

Verified against cached BATCHING morning round (07:55):
- temps 17, 16, 17 → AVG = (17+16+17)/3 = **16.67** ✓ (matches cached `16.67`)
- RH% 75, 78, 76 → AVG = (75+78+76)/3 = **76.33** ✓ (matches cached `76.33`)
And BATCHING noon: temps 17.6, 17.5, 17.4 → (52.5)/3 = **17.5** ✓ ; RH 72,72,73 → 217/3 = **72.33** ✓.

Proposed status columns (not in sheet):
- **temp_status** = `OK` if `std_temp_low ≤ AVG TEMP ≤ std_temp_high` else `LOW`/`HIGH` (band from §3, per department).
- **rh_status** = `OK` if `std_rh_low ≤ AVG RH% ≤ std_rh_high`.
- No StDev/CV% (simple 3-spot mean per round). The universal CV% formula (§4) does **not** apply.
- ⚠️ Confirm: AVG is a plain 3-spot mean (verified above). TIME is a stored input, not computed.

## 5. Worked example (real data)
Cached **SPINNING DEPARTMENT**, date 2026-01-05:

| Round | Spot1 (fr.2) | Spot2 (fr.28) | Spot3 (fr.66) | AVG TEMP | AVG RH% |
|---|---|---|---|---|---|
| morning ~07:57 | 17°C / 81% | 17°C / 80% | 17°C / 81% | (17+17+17)/3 = **17.0** | (81+80+81)/3 = **80.5** |
| noon ~12:22 | 18.2 / 69 | 18.2 / 68 | 18.1 / 68 | (54.5)/3 = **18.15** | (205)/3 = **68.0** |
| evening ~16:28 | 18.9 / 66 | 18.7 / 64 | 18.8 / 65 | (56.4)/3 = **18.75** | (195)/3 = **64.5** |

All AVG values match the cached `AVG TEMP` / `AVG RH%` columns (17.0/80.5, 18.15/68.0, 18.75/64.5) ✓. RH falls through the day as temperature rises — the expected diurnal pattern.

## 6. Proposed VOW data model
Header (per date) + detail (one row per department×spot×round). Avoid a wide table — readings vary in count by department.

```python
class JuteSqcHumidity(Base):
    __tablename__ = "jute_sqc_humidity"
    humidity_id   = Column(Integer, primary_key=True, autoincrement=True)
    co_id         = Column(Integer, nullable=False, index=True)
    branch_id     = Column(Integer, nullable=True)
    report_date   = Column(Date, nullable=False, index=True)   # one per date
    prepared_by   = Column(String(150), nullable=True)
    active        = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by    = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

class JuteSqcHumidityDtl(Base):
    __tablename__ = "jute_sqc_humidity_dtl"
    humidity_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    humidity_id     = Column(Integer, nullable=False, index=True)
    dept_id         = Column(Integer, nullable=True, index=True)  # dept_mst.dept_id (section)
    spot_no         = Column(Integer, nullable=False)             # 1..3
    spot_label      = Column(String(120), nullable=True)          # "1st spot-Near fr.no. 2"
    round_no        = Column(Integer, nullable=False)             # 1=AM,2=noon,3=PM
    reading_time    = Column(TIME, nullable=True)                 # 07:55:09
    temp_c          = Column(DECIMAL(5, 1), nullable=True)
    rh_pct          = Column(DECIMAL(5, 1), nullable=True)
```
- **PK** header `humidity_id`; one active row per `(co_id, report_date)` → **upsert-with-confirm** like `JuteSqcSpinningRhmr` (daily singleton), or insert-only + soft delete. Recommend upsert-confirm.
- **AVG TEMP / AVG RH% recomputed server-side** per (dept, round) from the 3 detail rows at read — not stored.
- `dept_id` + `spot_no` + `round_no` uniquely place each reading. `spot_label` denormalised from the dept-spot config for display.

## 7. Proposed endpoints & pages
Prefix `/api/juteSQC`.
- `GET /humidity_create_setup` → departments (`dept_mst` by branch) each with its 3 spot labels + std temp/RH bands; round labels (AM/noon/PM).
- `POST /humidity_save` → upsert header + all detail rows for the date; validate each dept has 3 spots × the entered rounds.
- `GET /humidity_by_date?co_id&branch_id&report_date` → full department grid with computed AVG TEMP / AVG RH% per dept×round + status vs bands.
- `GET /humidity_table?co_id&from&to` → range summary (e.g. daily AVG per department for trend).
- `POST /humidity_delete` → soft delete.

**Frontend** (`juteSQC/humidity/`): mobile entry — pick date, then a per-department card: 3 spots × current round (TIME auto-fillable from device clock, TEMP/RH numeric keypad); operator walks dept→dept and round→round. Live AVG preview per dept. Desktop summary: the full department × spot × round grid for a date (mirrors the sheet), AVG columns color-flagged vs band; trend view across dates. Route consts under `apiRoutesPortalMasters` (`HUMIDITY_SQC_*`); calls via `fetchWithCookie`.

**Masters to link:** `dept_mst` (departments + std temp/RH bands + spot config), `user_mst` (prepared_by). Optionally `spell_mst` if rounds map to spells.

## 8. Open questions (NEEDS OWNER DECISION)
- Acceptable **Temp band** and **RH% band per department** (numbers not in cache) — and store on `dept_mst` (decision #2, **process×department storage question**).
- Are the **3 spots per department** fixed config? Where to store spot labels — `dept_mst`-linked spot rows vs config. Do spots ever change?
- Map the section labels (BATCHING, PREPARING, SPINNING, WEAVING, **SEWING(FINISHING)**, **BALE PRESS(FINISHING)**) to real `dept_mst.dept_id` rows — the two finishing sub-areas need a decision (same dept_id with a sub-area field, or separate rows?).
- Are **rounds fixed at 3** (morning/noon/evening) and do they map to `spell_mst` spells, or is the count/time free?
- Is **TIME** required and operator-entered, or auto-captured from the device clock at save?
- Relationship to the **already-built spinning RHMR** (`JuteSqcSpinningRhmr`) — should this plant-wide report supersede/feed it for the spinning department, or coexist? (Avoid double entry of spinning temp/RH.)
- One record per date enforced (upsert-with-confirm) vs insert-only + soft-delete.
- Should AVG be a plain 3-spot mean (verified) — confirm no weighting.
