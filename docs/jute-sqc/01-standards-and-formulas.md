# 01 — Standards & Formulas (cross-cutting)

The jute-SQC math repeats across reports. This is the verified, reusable reference. Each report spec
points here for the shared formulas and lists only its own deviations. **Every constant here is one
the owner should confirm** — they are currently baked into the Google sheets (see `05-open-questions.md`).

## A. Moisture-Regain (MR%) correction — the single most-used formula

Jute is hygroscopic; weights are normalised to a **standard moisture regain**. The base textile
constant is **16% regain**, but the sheet stores **std MR% per quality** (Hessian ≈ 16, Sacking ≈ 20).
The correction always uses the *quality's own* std MR%:

```
Corrected = Observed × (100 + STD_MR_quality) / (100 + Observed_MR%)
```

Verified against cached values:

| Report | Observed | Obs MR% | STD MR% | Corrected (calc) | Corrected (sheet) |
|--------|----------|---------|---------|------------------|-------------------|
| R-08-04 roll wt | 69.40 kg | 38 | 16 | 69.40×116/138 = **58.34** | 58.34 ✓ |
| R-08-16 count | 9.03 lb | 17 | 16 | 9.03×116/117 = **8.95** | 8.95 ✓ |
| R-08-05/06/07 breaker HESSIAN | 20.32 | 29 | 16 | 20.32×116/129 = **18.27** | 18.26 ✓ |
| R-08-05/06/07 breaker SACKING WEFT | 20.40 | 32.25 | 20 | 20.40×120/132.25 = **18.51** | 18.51 ✓ |

**Where STD_MR lives in VOW:** `jute_yarn_mst.std_mr_pct` already exists (yarn). For raw-jute and
line/blend qualities, add `std_mr_pct` to the relevant quality master (see `04-inputs-and-masters.md`).
The built `JuteSqcSpinningCount` already documents `corrected = observed/(100+mr)*(100+std_mr)`.

> ⚠️ Confirm: is std MR truly per-quality (16 Hessian / 20 Sacking) everywhere, or per-stage? Cached
> values support per-quality. Roll/sliver use the same form; only the std value changes.

## B. Yarn count conversion (R-08-16 only)

Jute yarn count = **lb per spindle (14,400 yds)**. From a weighed sample of `N` yds:

```
Count(lb) = Sample_WT_g × (14400 / N) / 453.592
```

Verified: 450-yd sample, 128 g → 128 × 32 / 453.592 = **9.03 lb** ✓ (so the per-450yd factor = 0.070548).

- **Constants:** 14,400 yds/spindle; 453.592 g/lb; sample length **N from the report header**
  (e.g. count = 450 yds; sliver samples differ: spreader 5 yds, breaker 5 yds, drawing/finisher 50 yds).
- **Sliver/roll reports do NOT convert to count** — they record weight directly in the report's unit
  ("lb per N yds" or "kg") and compare to a **std weight** in that same unit. Conversion is yarn-count-only.

## C. CV% (Coefficient of Variation) — definition VARIES, state per report

```
CV% = Sample_StDev / Mean × 100        (Sample StDev = n-1 ; Python statistics.stdev / SQL STDDEV_SAMP)
```

- **Morrah (R-08-01):** mean = raw weights.
- **Sliver/roll family (03,04,05/06/07,07A,08/09/10,12/13/14):** mean = **corrected** weights
  (verified R-08-04: stdev_corr 2.26 / avg_corr 56.22 = 0.0402 = 4.02% ✓; R-08-05/06/07: 0.795/18.26 = 4.35% ✓).
- **TPI (R-08-17):** mean = TPI readings.
- **R-08-15 QR&CV (built, do NOT generalize):** `CV% = StDev / QR% × 100` (lab-specific).

> ⚠️ Confirm per report whether stdev is computed on **observed** or **corrected** readings, and that
> it is sample (n-1) not population. Cached values point to corrected + sample for the sliver family.

## D. Pass/fail buckets, bands & flags — each report has its own; capture exactly

| Report | Mechanism | Constants (from cached values) |
|--------|-----------|--------------------------------|
| R-08-01 Morrah | LT/OK/HY counts | LT `<1200`, OK `1200–1400`, HY `>1400` g |
| R-08-04 Spreader roll wt | 6 weight bands × {OBS, CORR} counts | `<55, 55-60, 61-65, 66-70, 71-75, >75`; `**` set `<85…>105` = **Spreader 2 only** |
| Sliver/card/drawing family | **CV% band** per quality+process | e.g. HESSIAN `8-10%`, SACKING WEFT `6-8%`, finisher drawing SWP `6-8%`/SWT `8-10%` — pass if CV% within band |
| Sliver/drawing | **Std weight** + **Range** per quality+process | e.g. finisher drawing HESS std 125 lb, SWP 150, SWT 160; "RANGE(LB)" e.g. 159-161 |
| R-08-16 Count | `$$` / `$` flags | `$$` = obs_count **higher** than std count by **+0.2** (heavy/coarse). Confirm `$` = light side & exact threshold |
| R-08-19/20/21/22 | **Std vs Actual** per fabric quality | width/picks/ends/length/ozs/MR all have a Std column to compare |
| R-08-28 Fabric fault | normalized **SCORE** | SCORE = total defects of a type ÷ pieces inspected (verified 93/16 = 5.8125 ✓; 11/16 = 0.6875 ✓) |

## E. Standard statistics block (sliver/roll family — reusable pseudo-code)

```python
# inputs: readings = [(wt_i, mr_i), ...]   (4 readings typical; 10 for roll wt)
#         std_mr = std MR% for the quality;  std_wt = std weight for (process, quality)
corr = [wt * (100 + std_mr) / (100 + mr) for wt, mr in readings]
avg_obs   = mean(wt_i)
avg_mr    = mean(mr_i)
avg_corr  = mean(corr)
stdev     = statistics.stdev(corr)        # sample (n-1)   ⚠️ confirm obs vs corr
cv_pct    = stdev / avg_corr * 100
# pass/fail: corr vs std_wt (+ band); cv_pct vs std CV% band for (process, quality)
```

This mirrors `compute_morrah_stats()` in `morrahWeight.py`. Reuse a single helper for the family.

## F. Where each standard should live in VOW → see `05-standards-storage.md`

Standards are stored in an **`item_id`-keyed satellite table** per stage (the quality is an `item_mst`
row; its standards live in a linked table — like the existing `jute_yarn_mst`). **Not** as columns on
`item_mst`. Reuse a satellite where one fits (`jute_yarn_mst` for yarn), create a new stage satellite
where none exists (drawing, batching, cloth, bag), and key it `(item_id)` — or `(item_id, process)`
when the same quality has different standards at different stages. This is **case-by-case** per report.

| Standard | Quality entity | Satellite (item_id-keyed) |
|----------|----------------|---------------------------|
| Std MR% (yarn), std count, std TPI | yarn `item_mst` | **`jute_yarn_mst`** (reuse; `std_mr_pct` exists) |
| Std MR% + sliver/roll **weight** + **CV% band** (process×quality) | raw/line `item_mst` | new stage satellite keyed `(item_id, process/machine)` |
| Std fabric construction (width/picks/ends/ozs, cut length, stitch) | cloth `item_mst` | new cloth satellite keyed `item_id` |
| Std bag weight/MR/dims | bag `item_mst` | new bag satellite keyed `item_id` |
| Emulsion oil% band; humidity temp/RH bands | process / dept (not an item) | on `machine_mst`/`dept_mst` row or a small env/batching satellite |

The per-(process × quality) weight/CV standards — same quality, different std by stage — are solved by
keying the satellite on `(item_id, process)`. Final table names/shape are a per-report decision
(`05-standards-storage.md`).
