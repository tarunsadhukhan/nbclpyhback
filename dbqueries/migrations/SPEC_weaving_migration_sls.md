# Spec — Weaving Quality & Weaving Daily migration into `sls`

Migration of legacy weaving data into the sls tenant, part of the vowsls→sls series
(sub-depts, HRMS employee DB, machines, designations, attendance, leave, weaving).

| | Source (legacy) | Target (sls) | Scope |
|---|---|---|---|
| Quality master | `vowsls.weaving_quality_master` | `sls.jute_prod_weaving_quality` | company 2 (513) + company 1 (48) |
| Daily production | `vowsls.cuts_jugar_buff_1` | `sls.jute_prod_weaving_daily` | `loom_date BETWEEN '2024-04-01' AND '2026-06-30'`, company 2 + company 1 |

> **Source correction:** the request named `empmill12.weaving_quality_master`; that table does not
> exist in EMPMILL12. `vowsls.weaving_quality_master` is the structural match and was used.

## Company → branch convention (established across the series)

| Legacy company | sls branch | sls co_id | id policy |
|---|---|---|---|
| 2 (EJM) | 29 | 2 | machine/eb ids preserved 1:1 |
| 1 (NJM) | 87 | 106 | remapped via map CSVs (branch-87 replica world) |

## 1. jute_prod_weaving_quality ← weaving_quality_master

New auto `weaving_quality_id`s; map file: `jute_prod_weaving_quality_sls_map.csv`
(`vowsls_company_id, vowsls_quality_id, quality_code → sls_weaving_quality_id`).

| Target column | Source / rule |
|---|---|
| co_id / branch_id | 2/29 (co 2) or 106/87 (co 1) |
| item_id | placeholder item "JUTE CLOTH (MIGRATED) CO{co}" — one per company (see §Masters); real item mapping to be fixed later in the master page |
| weaving_quality_code / _name | quality_code / quality_name |
| ends, finished_length, ozs_yds | same columns, `COALESCE(x, 0)` (target NOT NULL) |
| std_ozs_yds, width, ports, shots, mc_teeth, jbo_rbo, tpi | same columns |
| no_of_jugar_per_cut | `no_of_jugar_per_cut`; NULL or 0 → **1** (target NOT NULL and `vw_weaving_daily` divides by it) |
| yarn_count | `CAST(yarn_count AS CHAR)` (legacy double → varchar) |
| reed_porter, shrinkage_pct, reed_space | NULL — not present in this legacy source |
| is_composite / active / updated_by | 0 / 1 / 1 |

## 2. jute_prod_weaving_daily ← cuts_jugar_buff_1 (UNPIVOT)

Legacy row = one loom-day with 5 spell column groups (`_a1, _a2, _b1, _b2, _c`).
Target grain = one row per (co, tran_date, spell, machine, quality).

**Emission rule** — a spell cell becomes a row iff:
- `quality_code_<sp>` is non-empty AND resolves in the quality map for that company, and
- at least one of `cuts_<sp>`, `close_<sp>`, `production_<sp>`, `jugar_<sp>` is non-NULL.

Cells with data but no quality code are skipped (target `weaving_quality_id` is NOT NULL);
counts reported by the migration run.

| Target column | Source / rule |
|---|---|
| co_id / branch_id | per company table above |
| tran_date | loom_date |
| spell_id | spell code A1/A2/B1/B2/C → branch's `spell_mst` row (see §Masters) |
| machine_id | loom_id (= `vowsls.mechine_master.mechine_id`); branch 29 as-is, branch 87 via `machine_mst_sls_co1_branch87_map.csv` |
| weaving_quality_id | `quality_code_<sp>` → §1 map (per company) |
| eb_id | `ticket_no_<sp>` → `tbl_hrms_ed_official_details.emp_code` → eb (MAX eb per code); branch 87 additionally through `hrms_eb_id_co1_branch87_map.csv`; unmatched/blank → NULL |
| beam_no | NULL (legacy has no beam; the app resolves beam via jute_prod_weaving_beam_map) |
| cuts | `COALESCE(cuts_<sp>, 0)` |
| close_jugar | `close_<sp>` |
| less_production | `less_production_<sp>` |
| active / updated_by | `COALESCE(is_active,1)` / 1 |

Columns NOT migrated (recomputed on read by `vw_weaving_daily` per the 2026-06-24 storage model):
`open_*`, `jugar_*`, `production_*`, `efficiency_*`, `working_hrs_*`, `finished_length_*`,
`actual_shots_*`, `speed_*`, `total_*`.

## Masters created by this migration

- `item_type_master` row 5 (copied from dev3) if absent.
- `shift_mst`: 3 rows (A/B/C) for **branch 87**, copied from branch-29 definitions.
- `spell_mst`: 5 rows (A1/A2/B1/B2/C) for branch 87 under those shifts.
  Branch 29 uses the pre-existing spells 97–101.
- `item_grp_mst` "JUTE CLOTH (MIGRATED)" (`item_type_id=5`) + `item_mst`
  "JUTE CLOTH (MIGRATED) CO2 / CO106" — one pair per company.

Concrete generated ids: see the run log section at the bottom.

## Idempotency & verification

- Every daily INSERT is guarded by a LEFT JOIN on (branch, tran_date, spell, machine) —
  re-running the script only fills gaps.
- Verified after the run: quality counts 513/48, daily row counts per branch, 0 orphan
  daily rows (quality/machine/spell all resolve), and `vw_weaving_daily` returns computed
  rows for branch 87.

## Run log (generated ids & final counts) — run 2026-07-05/06

Generated masters:
- Branch-87 spells: A1=102, A2=103, B1=105, B2=106, C=108 (branch-29 set pre-existing: 97–101).
- Placeholder items: legacy co 2 → item_id **335522**, legacy co 1 → item_id **335523** (code `JCLOTH-MIG`).
- `item_type_master` row 5 copied from dev3.

Final counts (all verified):
| | branch 29 | branch 87 |
|---|---|---|
| jute_prod_weaving_quality | 513 | 48 |
| jute_prod_weaving_daily | 1,044,830 | 1,214,925 |
| …of which with eb_id resolved | 428,092 | 122,961 |

- Daily orphan check (quality/machine/spell all resolve): **0**.
- `vw_weaving_daily` verified computing for branch 87 (spell chain, quality join, masters resolve).
- Spell-cells skipped (had data but NO quality code — cannot satisfy NOT NULL weaving_quality_id):
  co 2: 38,730 · co 1: 55,775.
- Legacy has 4 duplicate quality codes within a company; both copies were migrated, but the daily
  join uses ONE id per (company, code) — the duplicate quality rows are simply unused.
- Source gaps reflected as-is: co 1 has no daily rows Jul 2024–Feb 2025; co 2 data ends 2026-01-27.
- The run survived two network outages; inserts are guarded by (branch, tran_date, spell, machine),
  so re-running the script only fills gaps.
