# R-08-16 (RHMR) — Temperature & Humidity / RHMR
**Stage:** spinning  **Status:** BUILT
**Source tab:** R-08-16 Yarn Test Parameter — header block `DATE / SPELL / TEMP(°C) / HUMIDITY%` (master "Daily Summary Date Select")   **DSR workbook:** spinning DSR (not shared)

> AS-BUILT spec. Real implementation:
> - BE router `src/juteSQC/spinning_sqc.py` (RHMR surface; also the Speed/TPI entry surface), queries `src/juteSQC/spinning_sqc_query.py`, ORM `JuteSqcSpinningRhmr` (and `JuteSqcSpinningEntry`) in `src/juteSQC/models.py`.
> - FE page `vowerp3ui/src/app/dashboardportal/juteSQC/spinning/page.tsx` → tab **"RHMR"** (tab index 2), components `_components/RhmrForm.tsx` + `_components/RhmrGrid.tsx`, hooks `useSqcRhmrSetup.ts` / `useSqcRhmrSearch.ts`. The Speed/TPI entry is tab **"Actual Speed / TPI"** (tab index 1).
> - Route consts `apiRoutesPortalMasters.SPINNING_SQC_RHMR_*` (and `SPINNING_SQC_*` count/qr-cv) in `vowerp3ui/src/utils/api.ts`.

## 1. Purpose
Records the spinning-shed ambient temperature (°C) and relative humidity (%) per date and spell. Jute spinning needs controlled humidity for yarn quality (MR, breakage); this is the RHMR ("relative humidity / moisture regain") environmental log that contextualises the yarn-count/MR readings taken the same day/spell on the R-08-16 sheet.

## 2. Inputs (the data-entry fields)
One reading-set per (date, spell). Upsert: one active row per `(co_id, entry_date, spell_id)`.

| Field | Type | Source/Master | Required | Header/per-reading | Notes |
|---|---|---|---|---|---|
| `entry_date` | date | sidebar/today | yes | header (the key) | "DATE" |
| `spell_id` | int | `spell_mst` (status=1) | yes | header (the key) | "SPELL" (A1/A2) |
| `temperature` | float (°C) | manual | no | reading | "TEMP(°C)" — e.g. 19 |
| `humidity` | float (%) | manual | no | reading | "HUMIDITY%" — e.g. 67 |
| `confirm` | bool | FE flag | — | control | False first call → returns existing row if one exists (overwrite guard); True → overwrites |
| `co_id`, `branch_id` | int | sidebar | yes | header | |

## 3. Standards & constants used
RHMR is a raw environmental log — **no per-quality standards, thresholds, or buckets** are stored or compared in the as-built. The sheet shows only the measured TEMP/HUMIDITY values (19 °C, 67 %); there is no std band, no pass/fail flag, no correction.

**Std-storage note (briefing §9a):** N/A — RHMR has no quality (`item_id`) dimension, so no satellite std table applies. If the owner later wants a target temp/humidity band, it would attach to the spinning **section/department or machine**, not to an `item_id` quality — out of the §9a item-keyed pattern; NEEDS OWNER DECISION.

## 4. Calculations (formulas)
None. `temperature` and `humidity` are stored verbatim and read back verbatim (`_rhmr_row_out`). No avg/StDev/CV/bucketing.

⚠️ Confirm: whether any acceptable humidity band (e.g. spinning RH target) should drive a pass/fail flag. Not implemented today.

## 5. Worked example (real data)
From the R16 cached tab header block, 2026-01-05:

Inputs: `entry_date = 2026-01-05`, `spell_id` = (A2), `temperature = 19`, `humidity = 67`.
- `sqc_rhmr_save` with `confirm=False`: if no active row for (co, 2026-01-05, A2) → inserts (`mode="insert"`, `saved=1`). If one exists → returns `{exists:True, existing:{temperature, humidity}}` without writing.
- Re-send with `confirm=True` → overwrites → `{saved:1, mode:"update"}`.
- `sqc_rhmr_search?entry_date=2026-01-05&spell_id=<A2>` → `{rows:[{... temperature:19.0, humidity:67.0, spell_code:"A2"}]}`.

## 6. As-built data model
Table `jute_sqc_spinning_rhmr` (ORM `JuteSqcSpinningRhmr`, `src/juteSQC/models.py`).

| Column | Type | Notes |
|---|---|---|
| `spinning_sqc_rhmr_id` | Integer PK, autoincrement | |
| `co_id` | Integer, not null, indexed | |
| `branch_id` | Integer, null | |
| `entry_date` | Date, not null, indexed | part of upsert key |
| `spell_id` | Integer, not null, indexed | part of upsert key |
| `temperature` | DECIMAL(5,1), null | °C |
| `humidity` | DECIMAL(5,1), null | % |
| `active` | Integer, not null, default 1 | soft-delete |
| `updated_by` | Integer, null | |
| `updated_date_time` | TIMESTAMP, server default now | |

Flat table; ONE active row per (co_id, entry_date, spell_id) maintained via update-if-exists.

### Companion: Speed / TPI entry (same tab group, partially built)
Table `jute_sqc_spinning_entry` (ORM `JuteSqcSpinningEntry`) backs the **"Actual Speed / TPI"** tab. Columns: `spinning_sqc_entry_id` PK, `co_id`, `branch_id`, `entry_date`, `mc_id` (frame), `item_id` (yarn), `actual_speed` DECIMAL(10,2), `actual_tpi` DECIMAL(10,3), `active`, `updated_by`, `updated_date_time`. Upsert one active row per (co, date, machine, item). **What exists:** capture of a single Actual Speed + Actual TPI value per frame/quality/date, resolved downstream by last-date for the spinning planning grid. **What the R-08-16 sheet needs but is NOT built:** the count sheet's DP/TP columns and a derived/standard-vs-actual TPI check, a TPI std band, and any CV% on speed/TPI — none are computed; the entry is a plain actual-value store with no standards comparison or pass/fail. So TPI is captured as a number but the SQC "parameter check" logic on TPI is **planned, not built**.

## 7. As-built endpoints & pages
Router prefix `/api/juteSQC`. Portal persona.

**RHMR:**
| Endpoint | Method | Returns / does |
|---|---|---|
| `/sqc_rhmr_setup` | GET | Needs `co_id` (branch opt). Returns `{data:{spells}}` — spell dropdown only. |
| `/sqc_rhmr_search` | GET | Optional filters `entry_date`, `spell_id` (the `:x IS NULL OR ...` idiom). Returns `{data:{rows:[...]}}` with spell_code/spell_name labels. |
| `/sqc_rhmr_save` | POST | Upsert per (co, date, spell). If active row exists and `confirm=False` → `{exists:True, existing:{...}}` (no write); else insert/update. Returns `{saved:1, mode}`. |
| `/sqc_rhmr_delete/{rhmr_id}` | DELETE | Soft-delete (active=0). |

Route consts: `SPINNING_SQC_RHMR_SETUP`, `SPINNING_SQC_RHMR_SEARCH`, `SPINNING_SQC_RHMR_SAVE`, `SPINNING_SQC_RHMR_DELETE` (base path; caller appends `/${id}`).

**Speed/TPI entry (companion):**
| Endpoint | Method | Returns / does |
|---|---|---|
| `/sqc_entry_setup` | GET | `{data:{machines, yarn_items, entries}}` for `co_id`+`entry_date`. |
| `/sqc_entry_save` | POST | Upsert actual_speed/actual_tpi per (co, date, mc_id, item_id). `{data:{saved}}`. |
| `/sqc_entry_by_date` | GET | `{data:[entries]}` for the date. |
(No delete endpoint for entry; no `SPINNING_SQC_ENTRY_*` route consts found in `api.ts` — the Speed/TPI tab calls these via the spinning-production speed/TPI wiring; confirm FE binding.)

**FE:** RHMR = tab 2 of `juteSQC/spinning/page.tsx`. `RhmrForm` = responsive entry (spell + temp + humidity, with the confirm-overwrite flow); `RhmrGrid` = filtered search by date/spell. Speed/TPI = tab 1 (`Actual Speed / TPI`).

**Masters linked (as-built):** RHMR → `spell_mst` (status=1). Speed/TPI entry → `machine_mst` (frames), `item_mst`/`jute_yarn_mst` (yarn).

## 8. Open questions (NEEDS OWNER DECISION)
- **No humidity/temp target band:** RHMR stores raw values with no pass/fail. If a target RH/temp band is wanted, where does it live (spinning section / department / machine — not an `item_id`)? — NEEDS OWNER DECISION.
- **Speed/TPI SQC logic only partially built:** `jute_sqc_spinning_entry` captures actual speed + actual TPI but there is NO std-TPI comparison, TPI band, DP/TP-derived TPI, or CV% on the SQC side. Confirm the intended TPI check (std TPI source, deviation flag) — **planned, not built.**
- **Speed/TPI FE route consts:** no `SPINNING_SQC_ENTRY_*` constants in `api.ts`; confirm how tab 1 binds to `/sqc_entry_save`.
- **One-row-per-spell upsert:** RHMR allows only one active reading per (date, spell). Confirm multiple readings/day per spell are never needed.
- **Phase-2 link:** RHMR is not yet correlated to the count/MR readings (same date+spell) for analysis; deferred per decision #4.
