# R-08-01 — Morrah Weight
**Stage:** selection/batching (raw-jute morrah weighing)  **Status:** BUILT
**Source tab:** R-08-01-MORAH REPORT (master "Daily Summary Date Select")   **DSR workbook:** `1qunzrcbuuPIqMedmL5iqt0MCacIYPyAoTZ7WNPLEHzg` / `DtSltRept!A1:R40` (not shared)

> AS-BUILT spec. The real implementation lives in:
> - BE router `src/juteSQC/morrahWeight.py`, queries `src/juteSQC/query.py`, ORM `JuteSqcMorrahWt` in `src/models/jute.py` (NOT `src/juteSQC/models.py`).
> - FE page `vowerp3ui/src/app/dashboardportal/juteSQC/r-08-01/page.tsx` (+ `documentation.md`).
> - Route constants `apiRoutesPortalMasters.MORRAH_WT_*` in `vowerp3ui/src/utils/api.ts`.

## 1. Purpose
Checks that hand-fed jute "morrahs" (heaps loaded into the trolley at selection/batching) weigh inside the standard band (1200–1400 g). The inspector weighs 10 samples per trolley; the system computes spread (avg/max/min/range), CV%, and counts how many readings are Light/OK/Heavy so the floor can correct feeding before downstream variation builds up.

## 2. Inputs (the data-entry fields)
Entry is a modal dialog on the Morrah page; one reading-set (one trolley) per save.

| Field | Type | Source/Master | Required | Header/per-reading | Notes |
|---|---|---|---|---|---|
| `entry_date` | date | sidebar/today default | yes | header | Date of inspection |
| `inspector_name` | string | free text (FE), no master | no | header | "NAME" row on the sheet; FE plain text input (handoff doc suggests worker dropdown — not built) |
| `dept_id` | int | `dept_mst` (by `branch_id`) | no | header | Defaults to SQC dept on the floor; dropdown |
| `item_id` | int | `item_mst` raw-jute quality (via `item_grp_mst` parent `item_type_id = 2`) | no | header | "QLTY OF JUTE" — e.g. D/4, A/5, 8Lbs |
| `trolley_no` | string | free text | no | header | "TROLLY NO." — batch identifier |
| `avg_mr_pct` | float | manual number | no | header | Avg moisture regain % of the trolley (stored, displayed; not used to correct weights — see §4) |
| `weights[1..10]` | int (g) | manual number pad | yes (exactly 10, all > 0) | per-reading | The 10 morrah sample weights in grams; stored as JSON array |
| `co_id`, `branch_id` | int | sidebar context | yes | header | Tenant company/branch scope |

Validation enforced server-side: `len(weights) == 10` (`SAMPLE_SIZE`) and every weight `> 0`, else HTTP 400.

## 3. Standards & constants used
Sheet header row: `STD MR%-16` and `STD MORRAH WT(GM)-1200 TO 1400 GM`.

| Standard | Example value | As-built location | Notes |
|---|---|---|---|
| `STANDARD_MIN_WEIGHT` | 1200 g | Python constant in `morrahWeight.py` | Hardcoded — not configurable |
| `STANDARD_MAX_WEIGHT` | 1400 g | Python constant in `morrahWeight.py` | Hardcoded — not configurable |
| `SAMPLE_SIZE` | 10 | Python constant in `morrahWeight.py` | Hardcoded |
| Std MR% (16) | 16% | **Not stored / not used in code** | Sheet shows STD MR%-16 and a "Corrected" row, but the as-built compute does NOT correct morrah weights for MR (raw weights only). `avg_mr_pct` is stored for reference only. |

**Std-storage note (briefing §9a — satellite-by-`item_id`):** the morrah quality is an `item_mst` row (raw jute, `item_type_id = 2`). There is currently **no** satellite std table for raw-jute morrah weight band / std MR%; the 1200–1400 band lives as Python constants. The analogous pattern is **`jute_yarn_mst`** (a satellite keyed by `item_id` holding `std_mr_pct`, std count) used by R-08-16. To make the morrah band per-quality, propose a **new raw-jute std satellite keyed by `item_id`** (e.g. `jute_raw_quality_std(item_id, std_morrah_wt_low, std_morrah_wt_high, std_mr_pct)`) — case-by-case, NEEDS OWNER DECISION (see §8).

## 4. Calculations (formulas)
All computed in `compute_morrah_stats(weights)` at **save** and stored; recomputable from the JSON `weights`.

| Output column | Formula | Worked (row below) |
|---|---|---|
| `calc_avg_weight` | `sum(weights) / 10` | mean of the 10 |
| `calc_max_weight` | `max(weights)` | |
| `calc_min_weight` | `min(weights)` | |
| `calc_range` | `max − min` | |
| `calc_cv_pct` | sample-StDev / avg × 100, where StDev = `statistics.stdev` (n−1) | CV% variant = **StDev/mean** (raw weights, NOT corrected) |
| `count_lt` | count of `w < 1200` | "LT(<1200)" |
| `count_ok` | count of `1200 ≤ w ≤ 1400` | "OK (1200-1400)" |
| `count_hy` | count of `w > 1400` | "HY(>1400)" |

LT%/OK%/HY% rows on the sheet = count/10×100; the as-built returns the raw counts and the FE derives the % preview (`computePreviewStats` in `page.tsx`). The sheet's "Corrected" row (MR-corrected weights) is **not implemented**.

⚠️ Confirm: the sheet labels a "Corrected" row and STD MR%-16; owner should confirm whether morrah weight is ever meant to be MR-corrected (correction = `Observed × (100 + 16) / (100 + avg_mr_pct)`). As-built does NOT correct.

## 5. Worked example (real data)
The cached R01 master tab for 2026-01-05 holds only the empty template (all `#DIV/0!` / 0 — the date had no morrah entry imported). Using a synthetic-but-representative reading-set to show the pipeline:

Inputs: `weights = [1350, 1280, 1410, 1190, 1320, 1300, 1450, 1250, 1360, 1290]`, `avg_mr_pct = 17.5`.
- avg = 13200/10 = **1320.0**
- max = **1450**, min = **1190**, range = **260**
- StDev (n−1) ≈ 75.6 → CV% = 75.6/1320×100 ≈ **5.73**
- count_lt (`<1200`): 1190 → **1**
- count_ok (`1200–1400`): 1350,1280,1320,1300,1250,1360,1290 → **7**
- count_hy (`>1400`): 1410,1450 → **2**
- LT% 10, OK% 70, HY% 20 (derived in FE).

## 6. As-built data model
Table `jute_sqc_morrah_wt` (ORM `JuteSqcMorrahWt`, `src/models/jute.py`, legacy `Mapped[...] mapped_column(...)` style, `extend_existing=True`).

| Column | Type | Notes |
|---|---|---|
| `morrah_wt_id` | Integer PK, autoincrement | |
| `co_id` | Integer, not null, indexed | tenant company |
| `branch_id` | Integer, not null, indexed | branch scope |
| `entry_date` | Date, not null | |
| `inspector_name` | String(100), null | |
| `dept_id` | Integer, null | → `dept_mst` |
| `item_id` | Integer, null | → `item_mst` (raw jute quality) |
| `trolley_no` | String(50), null | |
| `avg_mr_pct` | Double, null | stored, not used in calc |
| `weights` | String(500), not null | JSON array of 10 ints (`json.dumps`) |
| `calc_avg_weight` | Double, null | computed at save |
| `calc_max_weight` | Integer, null | computed |
| `calc_min_weight` | Integer, null | computed |
| `calc_range` | Integer, null | computed |
| `calc_cv_pct` | Double, null | computed |
| `count_lt` / `count_ok` / `count_hy` | Integer, null | computed bucket counts |
| `active` | Integer, not null, default 1 | soft-delete flag (set, but no delete endpoint built) |
| `updated_by` | Integer, null | `token_data.user_id` |
| `updated_date_time` | DateTime, server default `current_timestamp` | audit |

Flat header table with computed columns stored alongside (no `_dtl` — the 10 readings live in the `weights` JSON). Insert-only; `active` used by reads (`WHERE active = 1`).

## 7. As-built endpoints & pages
Router prefix `/api/juteSQC` (registered in `src/main.py`). All Portal persona (`get_tenant_db` + `get_current_user_with_refresh`), `{"data": ...}` responses.

| Endpoint | Method | What it returns / does |
|---|---|---|
| `/get_morrah_wt_create_setup` | GET | `{data:{departments, jute_qualities}}` — dropdowns. Needs `co_id`, `branch_id`. Departments from `dept_mst` by branch; qualities from `item_mst` join `item_grp_mst` parent `item_type_id=2`. |
| `/create_morrah_wt` | POST | Validates 10 positive weights, computes stats, inserts one row. Returns `{message, morrah_wt_id}`. |
| `/get_morrah_wt_table` | GET | Paginated list (`page`, `limit≤100`, `search`). Joins `dept_mst.dept_desc` (department) + `item_mst.item_name` (jute_quality). Returns `{data, total, page, page_size}`. |
| `/get_morrah_wt_by_id` | GET | Single record by `id`; parses `weights` JSON back to array. Returns `{data}`. |

No update / no soft-delete / no approval endpoints are built for morrah (the spinning reports have soft-delete; morrah does not yet).

**FE:** standalone route `dashboardportal/juteSQC/r-08-01/page.tsx` — a list grid + "create" modal with the 10 weight inputs and live preview (`computePreviewStats`) plus a read-only "view" dialog. Route consts: `MORRAH_WT_TABLE`, `MORRAH_WT_BY_ID`, `MORRAH_WT_CREATE_SETUP`, `MORRAH_WT_CREATE`. (Note: morrah is its own page, NOT a tab on a stage page — unlike the spinning reports which are tabbed.)

**Masters linked (as-built):** `dept_mst` (department), `item_mst`+`item_grp_mst` (raw-jute quality, `item_type_id=2`). Spell/shift is NOT linked on morrah.

## 8. Open questions (NEEDS OWNER DECISION)
- **Std band not configurable:** 1200/1400/10 are hardcoded Python constants. Move to a per-quality satellite keyed by `item_id` (proposed `jute_raw_quality_std`) so different jute qualities can carry different morrah-weight bands? — **case-by-case, NEEDS OWNER DECISION (briefing §3/§9a).**
- **MR correction not implemented:** sheet shows STD MR%-16 + a "Corrected" row, but as-built stores `avg_mr_pct` only and never corrects. Should morrah weight be MR-corrected, and per-quality std MR stored on the same satellite?
- **Inspector source:** as-built is free text; handoff doc wants a worker/inspector dropdown (link to an employee master). Confirm source master.
- **No soft-delete / edit / approval:** morrah has no delete or approval lifecycle (others do). Confirm whether a correction/delete path is needed.
- **Phase-2 link:** trolley → batching production transaction (which heap/lot) is not wired; deferred per decision #4.
