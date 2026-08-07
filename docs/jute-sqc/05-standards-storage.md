# 05 — Standards Storage (the approach) — *case-by-case, decide in discussion*

> Owner direction: **standards extend existing masters, but NOT as columns on `item_mst` itself.**
> A quality's standards live in a **separate satellite/extension table linked by `item_id`** — exactly
> like the existing `jute_yarn_mst` does for yarn. **Reuse** a satellite where one already fits; **create
> a new stage-specific one** where none exists (e.g. drawing, batching). **Handle it report-by-report,
> not one composite table for everything.** Where storage is still open, the per-page docs say
> `▶ standards: later` — this file is the agreed *pattern*, the exact tables are a per-report decision.

## The pattern

```
item_mst (item_id, item_code, item_name, item_type_id, …)     ← the quality/entity itself
   │  item_id
   ▼
<stage>_quality_std  (item_id PK/FK, std_*, …)                 ← satellite: standards for that quality
        e.g. jute_yarn_mst (item_id → std_mr_pct, std count)   ← ALREADY EXISTS, reuse for yarn
```

- The **quality is an `item_mst` row** (raw jute = type 2; yarn; line/cloth; bag — each an `item_id`).
- Its **standards live in a satellite keyed by `item_id`** — never as new columns on `item_mst`.
- When a standard is **process-specific** (same quality, different std at breaker vs drawing vs
  weaving), the satellite is keyed by **`(item_id, process)`** or **`(item_id, machine_id)`** — one
  satellite row per stage. This is how the per-(process × quality) problem is solved cleanly without
  bloating `item_mst` and without one giant composite standards table.
- **Reuse vs create is per report.** Don't force a single scheme across all 28.

## Why this (vs columns on item_mst / one composite table)

- `item_mst` stays lean and generic; SQC concerns don't leak into the core item master.
- Mirrors the **existing precedent** (`jute_yarn_mst` is already an item_id-keyed satellite holding
  `std_mr_pct` and std count) — so the spinning reports need *no new table*.
- Per-stage satellites keep each stage's standards together and let the same quality carry different
  standards at different stages.

## Per-report storage proposal (case-by-case — to confirm with owner)

| Report(s) | Quality entity (`item_mst` type) | Satellite table | New? | Key | Std fields it holds |
|-----------|----------------------------------|-----------------|------|-----|---------------------|
| R-08-01 Morrah, R-08-03/04 Spreader | raw jute (type 2) | `jute_raw_quality_std` *(name TBD)* | **new** | `item_id` | `std_mr_pct`, std morrah/roll/sliver wt, weight bands |
| R-08-05/06/07, R-08-07A, R-08-08/09/10, R-08-12/13/14 | line quality (HESSIAN/SACKING/10Lbs) | `jute_draw_quality_std` *(name TBD)* | **new** | `(item_id, process/machine)` | `std_mr_pct`, `std_weight`, `std_wt_tol`, `std_cv_low/high` per stage |
| R-08-15/15A QR&CV, R-08-16 count, R-08-17 TPI | yarn | **`jute_yarn_mst`** | reuse | `item_id` | `std_mr_pct` *(exists)*, std count, `std_tpi`, std QR/CV band (add cols here) |
| R-08-18 Beam, R-08-19/20/21/22 weaving, R-08-25 packing | cloth/fabric quality | `jute_cloth_quality_std` *(name TBD)* | **new** | `item_id` | `std_mr_pct`, std width/picks/ends/length/oz, std cut length, std stitch |
| R-08-23/24 Bag | finished bag | `jute_bag_quality_std` *(name TBD)* | **new** | `item_id` | std weight + tol, `std_mr_pct`, std length/width/ends/picks/stitch |
| R-08-02 Emulsion | (process, not a quality) | on the batching `machine_mst` row OR a small `batching_std` keyed by machine/line | **new** | `machine_id`/line | target oil% band, tank capacity, oil-charge target |
| R-08-28 Fabric fault | fault-type checklist | `jute_sqc_fault_type_mst` (lookup) | **new** | `fault_type_id` | fault name, order, optional demerit weight |
| Humidity | department (not item) | on `dept_mst` or a `dept_env_std` keyed by `dept_id` | **new** | `dept_id` | temp band, RH% band, spot config |

*(Table names are placeholders — final names/shape are the per-report discussion. Spinning reports
reuse `jute_yarn_mst`; everything else is a new item_id- (or dept/machine-) keyed satellite created
**only when that report's build starts**, so we add tables incrementally, not all at once.)*

## What this means for the per-report `reports/*.md`

The detailed report files (written before this refinement) sometimes phrase storage as "add column to
`item_mst`/`machine_mst`." **This file supersedes that phrasing:** read those as "store on the
`item_id`-keyed satellite for that stage (reuse `jute_yarn_mst` / create a stage satellite)." The
*inputs, outputs, formulas, and master links* in those files are unaffected — only the standards-home
detail defers to this pattern, decided per report.
