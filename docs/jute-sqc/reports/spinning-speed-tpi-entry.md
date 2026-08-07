# SPEED-TPI — Spinning Speed / Actual TPI single-value entry  (relation to R-08-17)
**Stage:** spinning  **Status:** BUILT (single-value entry only; the R-08-17 reading-set / CV% study is NOT built)
**Source tab:** `R-08-17 YARN T.P.I & T.P.I. CV%` (master "Daily Summary Date Select")   **DSR workbook:** `1QB_BA2rMwXZ-1bz4FsWXi7iEnNFABBdNy1zgcRYGz84` / `DSR!A1:M38` (not shared)

> AS-BUILT spec for the built **Speed / Actual TPI single-value entry** surface
> (`jute_sqc_spinning_entry`, Tab 2 of the Spinning SQC page). It captures **one actual_speed +
> one actual_tpi per (date, machine, yarn)** to feed the spinning planning grid. It is **related to
> but NOT the same as R-08-17** (Yarn TPI & TPI CV%), which is a **20-reading per-frame statistical
> study** (Avg TPI / Stdev / CV% / Min / Max vs Std.TPI) — that reading-set report is **NOT built.**

## What exists vs what R-08-17 needs

| | Speed/TPI entry (BUILT) | R-08-17 TPI & TPI CV% (NOT built) |
|---|---|---|
| Granularity | **single** `actual_speed` + `actual_tpi` per (date, machine, yarn) | **20 readings** per (date, frame, quality) |
| Save semantics | **upsert** one active row per key (last value wins) | insert-only reading set (per the SQC pattern) |
| Stats | none (raw single value) | Average TPI, Stdev, **CV%**, Min-TPI, Max-TPI vs Std.TPI / TP |
| Standard used | none | `STD.TPI`, `TP` (twist multiplier) |
| Purpose | feed planning grid (actual speed/TPI by last-date) | QC of twist uniformity per frame |
| Source tab dump | `R17.txt` is an **empty template** (labels only, no data) | same dump — no cached numbers |

## 1. Purpose

Record the **actual running speed** and **actual TPI (twist per inch)** for a spinning machine + yarn
on a date, so the spinning **planning grid** can resolve "what speed/TPI is this frame currently
running" by last-date ≤ the planning date. It is operational data capture, not a statistical QC study.

## 2. Inputs (the data-entry fields)

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| Date | date | n/a | Yes | **Header** — `entry_date`; required on setup/by_date. |
| Machine (MC No.) | dropdown | `machine_mst` (spinning-type) → `mc_id` | Yes | per-row key; `_fetch_machines`. |
| Yarn item | dropdown | `item_mst` (yarn, `item_type_id=4`) → `item_id` | Yes | per-row key; `_fetch_qualities`. |
| Actual Speed | number ≥0 | operator-entered | optional | `actual_speed` DECIMAL(10,2). |
| Actual TPI | number ≥0 | operator-entered | optional | `actual_tpi` DECIMAL(10,3). |

One row per (date, machine, yarn). Save is **upsert** on that key — re-saving overwrites the active row.

## 3. Standards & constants used

**None in the built entry surface** — it stores raw single values, no std comparison, no bands.

For R-08-17 (NOT built) the sheet needs: **`STD.TPI`** (standard twist per inch for the quality) and
**`TP`** (twist multiplier). Per briefing 9a these belong in a **satellite of `item_mst` keyed by
`item_id`** — the natural home is **`jute_yarn_mst`** (extend with `std_tpi`, `tp`), reused not
re-invented. **NEEDS OWNER DECISION** if/when R-08-17 is built.

## 4. Calculations (formulas)

**Built entry surface:** none — `actual_speed` / `actual_tpi` are stored verbatim. The planning grid
downstream resolves the latest value by last-date (no stat computed here).

**R-08-17 (NOT built), derived from the universal SQC formulas + sheet labels (no cached data to verify):**
- `Average TPI = mean(reading 1..20)`
- `Stdev = sample (n-1) stdev`
- `CV% = Stdev / Average TPI × 100` (TPI uses the **textbook** SD÷mean CV%, per briefing §4)
- `Min-TPI = min(readings)`, `Max-TPI = max(readings)`
- compared against `STD.TPI`.

⚠️ **Confirm:** R-08-17 formulas are derived — the `R17.txt` tab is an empty template (labels only,
all stat cells blank), so none can be verified against real numbers.

## 5. Worked example (real data)

**Built entry surface:** trivially store-only — e.g. (date 2026-01-05, machine 12, yarn 44,
actual_speed 180.0, actual_tpi 4.250) → one row, read back unchanged.

**R-08-17:** no worked example — the source tab carries no cached readings.

## 6. As-built data model

`jute_sqc_spinning_entry` — class `JuteSqcSpinningEntry` (`src/juteSQC/models.py`).

| Column | Type | Notes |
|--------|------|-------|
| `spinning_sqc_entry_id` | INT PK AI | |
| `co_id` | INT NOT NULL, idx | tenant scope |
| `branch_id` | INT NULL | optional scope |
| `entry_date` | DATE NOT NULL, idx | header date |
| `mc_id` | INT NOT NULL, idx | machine → `machine_mst.machine_id` |
| `item_id` | INT NOT NULL, idx | yarn → `item_mst.item_id` |
| `actual_speed` | DECIMAL(10,2) NULL | single value |
| `actual_tpi` | DECIMAL(10,3) NULL | single value |
| `active` | INT NOT NULL default 1 | soft-delete |
| `updated_by` | INT NULL | audit |
| `updated_date_time` | TIMESTAMP default CURRENT_TIMESTAMP | audit |

**Upsert** key = `(co_id, entry_date, mc_id, item_id)` with `active=1` (`get_sqc_entry_active_row_query`
→ update, else insert). **No detail table** — there is no reading set, so R-08-17's 20-reading study
has **no data model in the build** (would need a new `jute_sqc_spinning_tpi` header+detail).

## 7. As-built endpoints & pages

**Router:** `src/juteSQC/spinning_sqc.py`, prefix `/api/juteSQC` (`src/main.py:203`).
Queries: `src/juteSQC/spinning_sqc_query.py`.

| Method / path | Function | Returns |
|---------------|----------|---------|
| `GET /api/juteSQC/sqc_entry_setup` | `sqc_entry_setup` | `{data:{machines, yarn_items, entries}}` |
| `POST /api/juteSQC/sqc_entry_save` | `sqc_entry_save` | upsert per (co,date,mc,item) → `{data:{saved}}` |
| `GET /api/juteSQC/sqc_entry_by_date` | `sqc_entry_by_date` | `{data:[…entry rows…]}` |

Query builders: `get_sqc_entry_by_date_query`, `get_sqc_entry_active_row_query`,
`update_sqc_entry_query`, `insert_sqc_entry_query`. (No delete endpoint for entry rows in the build.)

**Frontend (Tab 2 of the Spinning SQC page):**
- Page: `vowerp3ui/src/app/dashboardportal/juteSQC/spinning/page.tsx` — `TABS[1] = "Actual Speed / TPI"`, rendered in the `tab === 1` block.
- Components: the Speed/TPI form + grid in `_components/` (alongside `CountForm`/`CountGrid`); hooks mirror `useSqcCountSetup`/`useSqcCountByDate`.
- Route consts (`src/utils/api.ts`): `SPINNING_SQC_*` block (the count block is at lines 824–828; the entry setup/save/by_date consts sit in the same Spinning SQC group). All calls via `fetchWithCookie`.

**Masters linked:** `machine_mst` (spinning frame, `mc_id`), `item_mst` (yarn item). No standards
satellite is used by the built surface.

## 8. Open questions (NEEDS OWNER DECISION)

- **Build R-08-17 (TPI & TPI CV%)?** The 20-reading-per-frame statistical study is **not built** —
  only the single-value Speed/TPI entry exists. Confirm whether R-08-17 is in scope as a separate
  reading-set tab (header+detail, like R-08-15 QR/CV) feeding Avg/Stdev/CV%/Min/Max vs `STD.TPI`.
- **Std TPI / TP storage:** if R-08-17 is built, `STD.TPI` and `TP` should extend the
  **`jute_yarn_mst` satellite (keyed by `item_id`)** — confirm column names (`std_tpi`, `tp`).
- **CV% variant:** TPI CV% is taken as **SD ÷ mean × 100** (textbook), unlike R-08-15's SD÷QR%.
  Confirm (no cached data to verify).
- **Relationship of `actual_tpi` to R-08-17:** the built single `actual_tpi` could be the *Average
  TPI* output of an R-08-17 study, or an independent operator entry. Confirm whether building R-08-17
  should auto-populate / supersede the single-value entry.
- **No delete / no audit-of-history** on entry rows (upsert overwrites). Confirm that "last value
  wins" with no history is acceptable.
