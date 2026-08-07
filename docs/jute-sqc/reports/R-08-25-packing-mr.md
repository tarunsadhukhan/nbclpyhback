# R-08-25 — Packing MR% (I.S.O.)
**Stage:** finishing (packing / bale moisture control)  **Status:** UNBUILT
**Source tab:** `R025` (master "Daily Summary Date Select")   **DSR workbook:** `1g0uspDwIsD5GKGC3RPr9pqo8TfO1nHa6SB48F3WTVl8` (not shared)

## 1. Purpose
Records the **moisture regain (MR%)** of finished goods at the packing stage, sampled **per quality**
(10 readings each), to ensure jute fabric/bags are within the standard MR band before baling. It
rolls up per-quality averages and then a **group average** by fabric family (Hessian, Sacking) — the
packing-floor moisture summary.

## 2. Inputs (the data-entry fields)

The sheet is a **wide matrix**: each column is one **quality** (header = quality name + construction
code), with 10 MR% rows beneath it. In VOW, model each column as one **(quality) reading-set**.

| Field | Type | Source/Master | Required | Notes |
|---|---|---|---|---|
| entry_date | date | — | yes | header; `2026-01-05` |
| co_id / branch_id | header | sidebar | yes | scope |
| quality_name | select | fabric family / quality — see §3 | yes | per-column header; "HESSIAN", "SACKING" |
| construction_code | select/text | construction list | no | per-column header; "38(11X10)","40(8X8)","39(8X7)","SKG ATYPE" |
| mr_pct (×10) | decimal | operator | yes | per-reading; 10 readings per quality column, e.g. 21,18,19,17,20,18,22,22,17,18 |

Header vs per-reading: date is header; quality_name/construction are per **reading-set** (column);
the 10 MR% values are per-reading. The sheet had 3 Hessian columns + 1 Sacking column populated (and
spare blank columns). **No weights, no machine, no correction** on this report — MR% is recorded raw.

## 3. Standards & constants used

The cached snapshot shows **no STD MR% column and no pass/fail band** on this tab — it only reports
observed averages. The implied standard is the per-quality STD MR% (Hessian≈16–20, Sacking≈20) used
elsewhere, but it is **not displayed or compared here**.

| Standard | Example value | Where it should live in VOW (decision #2) |
|---|---|---|
| STD MR% per quality | not shown on tab (Hessian≈16/20, Sacking≈20 elsewhere) | per-quality `std_mr_pct` column on the quality master |

**Std-value storage (decision #2 = extend existing masters):**
- If the owner wants a STD MR% comparison added (the sheet currently has none), store `std_mr_pct`
  per quality on the **quality master** (yarn already has `jute_yarn_mst.std_mr_pct`; for
  fabric/bag qualities add the same column to whichever master holds Hessian/Sacking qualities —
  likely `item_mst` line/fabric rows or a fabric-quality master).
- **⚠️ Process×quality note:** unlike the weight reports, this report has **no CV% band and no
  weight standard**, so the process×quality standards-storage tension is *light* here — only a single
  `std_mr_pct` per quality is needed, which fits cleanly on an existing per-quality master. No new
  standalone table required. (Flagging it for consistency with the weight-based reports.)

## 4. Calculations (formulas)

- **Average MR% (per quality column)** = mean of the 10 MR% readings.
  Worked: Hessian 38(11×10): (21+18+19+17+20+18+22+22+17+18)/10 = 192/10 = **19.2** ✓.
  Worked: Hessian 40(8×8): (21+16+19+19+18+21+18+20+21+22)/10 = 195/10 = **19.5** ✓.
  Worked: Hessian 39(8×7): (21+18+17+20+20+18+19+21+20+21)/10 = 195/10 = **19.5** ✓.
  Worked: Sacking SKG ATYPE: (20+19+19+18+22+19+21+20+20+19)/10 = 197/10 = **19.7** ✓.
- **Average Hessian (group roll-up)** = average across all Hessian columns.
  ⚠️ Confirm aggregation method: sheet shows **19.4**. Mean of the three column averages =
  (19.2+19.5+19.5)/3 = 19.4 ✓ — so it is the **mean of per-column averages** (equivalently the mean
  of all 30 Hessian readings = 582/30 = 19.4, which coincides because all columns have 10 readings).
  ⚠️ If column sample sizes ever differ, mean-of-averages ≠ mean-of-all-readings; confirm which the
  owner wants (recommend mean of all readings, weighted).
- **Average Sacking (group roll-up)** = average across Sacking columns = **19.7** ✓ (single column here).
- StDev/CV% are **not** computed on this tab. ⚠️ Confirm whether to add CV% (would use the
  weight-CV variant `StDev/mean×100`); currently out of scope.

## 5. Worked example (real data)
Date 2026-01-05. Four quality columns:
- HESSIAN 38(11×10): 21,18,19,17,20,18,22,22,17,18 → **avg 19.2**
- HESSIAN 40(8×8): 21,16,19,19,18,21,18,20,21,22 → **avg 19.5**
- HESSIAN 39(8×7): 21,18,17,20,20,18,19,21,20,21 → **avg 19.5**
- SACKING SKG ATYPE: 20,19,19,18,22,19,21,20,20,19 → **avg 19.7**
Group roll-ups: **Average Hessian = 19.4** (mean of 19.2/19.5/19.5); **Average Sacking = 19.7**.

## 6. Proposed VOW data model

Header + JSON-readings per quality column (mirrors `JuteSqcMorrahWt` JSON style). One row = one
quality column for one date; the group averages (Hessian/Sacking) are computed at **read** by
grouping rows on the quality's fabric family — do not store the group roll-up.

`jute_sqc_packing_mr`
| Column | Type | Notes |
|---|---|---|
| packing_mr_id | INT PK autoincr | |
| co_id | INT NOT NULL idx | |
| branch_id | INT NULL | |
| entry_date | DATE NOT NULL idx | |
| item_id | INT NULL idx | quality (item_mst / fabric-quality) |
| quality_label | VARCHAR(100) NULL | "HESSIAN","SACKING" (fabric family) |
| construction_code | VARCHAR(50) NULL | "38(11X10)","SKG ATYPE" |
| readings | JSON / VARCHAR(500) NOT NULL | `[21,18,19,17,20,18,22,22,17,18]` |
| calc_avg_mr | DECIMAL(6,3) NULL | computed mean of readings |
| active | INT NOT NULL default 1 | soft-delete |
| updated_by | INT NULL | |
| updated_date_time | TIMESTAMP default now | |

⚠️ Confirm: fixed 10 readings per column (sheet) or open-ended. Group family (Hessian/Sacking) should
come from the quality master, not free text — see open questions.

## 7. Proposed endpoints & pages
Backend (prefix `/api/juteSQC`):
- `GET  /packing_mr_create_setup` — qualities (with fabric family + optional std_mr_pct), construction list.
- `POST /packing_mr_save` — validate readings, compute per-column avg, insert one row per quality column.
- `GET  /packing_mr_by_date` — all quality columns for a date + the computed **group averages**
  (Hessian/Sacking) aggregated server-side.
- `GET  /packing_mr_by_id` — single column (parse readings JSON).
- `POST /packing_mr_delete` — soft delete.

Frontend (`juteSQC/r-08-25/`): mobile-first entry — pick date + quality (+ construction), enter 10
MR% readings, show live average; "add another quality" to capture multiple columns in one session;
desktop date-driven summary grid (columns = qualities, per-column avg, plus Average Hessian /
Average Sacking footer rows). Route consts in `api.ts` (`PACKING_MR_*`); `fetchWithCookie`.

**Masters to link:** quality (`item_mst` / fabric-quality master) carrying the **fabric family**
(Hessian/Sacking) used for grouping; construction-code list; optional `std_mr_pct`.

## 8. Open questions (NEEDS OWNER DECISION)
- Where do fabric qualities (HESSIAN/SACKING) and their **fabric family** + construction codes live —
  `item_mst` line/fabric rows or a fabric-quality master? Group roll-up depends on a reliable family field.
- Should a **STD MR% comparison / pass-fail band** be added (the sheet has none today)? If yes, store
  `std_mr_pct` per quality on the quality master.
- Group average method when sample sizes differ: mean-of-column-averages (sheet, equal n) vs
  mean-of-all-readings (recommended)? Confirm.
- Fixed 10 readings per column or variable count?
- Add CV%/StDev to this report, or keep average-only (current sheet)?
- How many quality columns per day are expected (sheet showed 4 populated, ~9 column slots)? Drives UI.
