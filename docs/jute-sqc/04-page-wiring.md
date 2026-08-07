# 04 — Page Wiring (what each page does · inputs · outputs · master links)

> **Scope of this doc (per owner):** wire out, per page — *what it does, what inputs it needs, what
> it outputs, and which existing master each field links to.* Each page lists the standard it *uses*
> (with the value seen in the sheet) but marks storage as **▶ standards: later** — the agreed approach
> is an **`item_id`-keyed satellite table** (see `05-standards-storage.md`), decided per report.
> Full detail per page in `reports/*.md`.
>
> **Entry UX (per owner):** reports are grouped onto **one tabbed page per stage** (like the existing
> Spinning SQC page) and the **entry tabs are responsive** for phone/tablet floor use — so each "page"
> below = a **tab** on its stage page.

**Legend** — Inputs: `H`=header (once per entry), `R`=per-reading (the sample set). Masters in **bold**
are existing VOW tables to link the dropdown to (see `02-linking-map.md`). Outputs = the columns the
report/summary view computes & shows. Shared formulas: `01-standards-and-formulas.md`.

Already built — now specced as-built in `reports/`: **R-08-01 Morrah**, **R-08-15 / 15A QR&CV**,
**R-08-16 Count + Temp/Humidity (RHMR)**, **Speed/TPI entry**.

---

## Family A — Sliver / Roll weight (carding & drawing)

Common shape: header (machine, spell, quality) + N×(weight, MR%) readings → moisture-corrected
average, sample StDev, CV%, vs a std weight & CV% band. One shared model + stats helper, parameterised
per stage. Output correction = `Observed × (100+stdMR)/(100+MR%)`; CV% = `StDev(corrected)/mean(corrected)`.

### R-08-03 — Spreader Roll Sliver Weight
- **Does:** checks spreader sliver linear density (5-yd cut weighed lb/100yds) for uniformity.
- **Inputs:** `H` date, shift→**spell_mst**, category (master TBD), quality→**item_mst** (raw jute, type 2), machine→**machine_mst** (spreader). `R` observed_weight ×(up to 12), mr_pct ×(up to 12).
- **Outputs:** Avg Obs, Avg Corr, Avg MR%, StDev, CV%.
- **Link masters:** spell_mst · item_mst(raw jute) · machine_mst(spreader).
- ▶ **standards: later** — std MR% per quality (for correction); std sliver weight lb/100yds.

### R-08-04 — Spreader Roll Weight
- **Does:** weighs 10 finished spreader rolls (kg) + MR%; distribution across weight bands.
- **Inputs:** `H` date, shift→**spell_mst**, quality→**item_mst**(raw jute), machine→**machine_mst**(spreader), feeder name (free text / HRMS later). `R` roll_weight_1..10 (kg), mr_pct_1..10.
- **Outputs:** Avg MR%, Avg Roll Wt (Obs & Corr), StDev (Obs & Corr), CV%, count of rolls in each weight band (Obs & Corr columns).
- **Link masters:** spell_mst · item_mst(raw jute) · machine_mst(spreader).
- ▶ **standards: later** — std MR% (MESTA≈16); 6 weight bands (`<55…>75`; Spreader-2 uses `85…105`).

### R-08-05/06/07 — Breaker Card (coarse-side SWT)
- **Does:** breaker-card sliver weight (lb/5yds), 4 cuts per (machine, spell, quality), CV% vs band.
- **Inputs:** `R`-row = mc→**machine_mst**(breaker card), spell→**spell_mst**, quality→**item_mst**(line quality); wt1..4, mr1..4.
- **Outputs:** Avg Wt, Avg MR%, Corr Wt, StDev, CV%, CV-band pass/fail, per-quality grand averages (OBS/MR/CORR/CV%).
- **Link masters:** machine_mst(breaker) · spell_mst · item_mst(line quality).
- ▶ **standards: later** — std MR% per quality (HESSIAN 16 / SACKING WEFT 20); CV% band (`6-8%`, `8-10%`).

### R-08-07A — Inter Card & Tow Breaker Sliver Weight
- **Does:** inter-card / tow-breaker / hopper sliver weight (4×5-yd), corrected, CV% vs band.
- **Inputs:** `H` date, section enum (INTER_CARD/TOW_BREAKER/HOPPER), MC→**machine_mst**, spell→**spell_mst**, quality→**item_mst**(line); `R` WT1..4, MR%1..4; remarks; (Reqd Wt / DP / Draft = std or Phase-2, blank).
- **Outputs:** Avg, MR%, Corr Wt, StDev, CV%, band pass/fail, section average block.
- **Link masters:** machine_mst · spell_mst · item_mst(line quality).
- ▶ **standards: later** — std MR%; Reqd (std) weight; CV% band (`6-8%`).

### R-08-08/09/10 — Drawhead (SWP/SWT) + Finisher Card (Hess)
- **Does:** drawing/finisher-card sliver weight (4×10-yd), corrected, vs per-machine **STD ± 0.2** range.
- **Inputs:** `H` date, time band (AM/PM), report enum (DRAWHEAD_SWT / DRAWHEAD_SWP / FINISHER_CARD), quality→**item_mst**(line), MC→**machine_mst**(drawing); `R` WT1..4, MR%1..4; DP (Phase-2, blank).
- **Outputs:** Avg, MR%, Avg Corr Wt, StDev, CV%, last-4 corrected averages, vs STD±0.2 range (e.g. `5.3–5.7`, `7.3–7.7`).
- **Link masters:** machine_mst(drawing head) · item_mst(line quality).
- ▶ **standards: later** — std weight per machine + ±0.2 range.

### R-08-12/13/14 — Finisher Drawing Sliver Weight (HESS / SKWP / SWT)
- **Does:** finisher-drawing sliver weight (4×50-yd) across 3 line families, corrected, vs STD ± 1 lb & CV band; per-quality grand average.
- **Inputs:** `H` date, section (HESS/SWP/SWT), quality→**item_mst**(line), MC→**machine_mst**(finisher drawing); `R` (DLV NO, WT, MR%) ×4; DP (Phase-2); remarks.
- **Outputs:** C1..C4 corrected, AVG, AVGMR, AVGC, StDev, CV%, in-range flag (STD±1), CV-band flag, per-quality GRAND AVERAGE.
- **Link masters:** machine_mst(finisher drawing) · item_mst(line quality HESSIAN/10Lbs/SWP/SWT).
- ▶ **standards: later** — std MR%(16); STD(LB) 125/140/150/160; RANGE ±1; CV band `4-6/6-8/8-10%`.

---

## Family B/C/D — Spinning (yarn)

### R-08-17 — Yarn T.P.I & T.P.I. CV%
- **Does:** twist-per-inch consistency — 20 TPI readings per spinning frame + quality.
- **Inputs:** `H` date, spg frame→**machine_mst**(spinning), quality→**item_mst**(yarn), count(lbs); `R` reading_1..20 (TPI).
- **Outputs:** Average TPI, StDev, CV%, Min-TPI, Max-TPI, vs Std TPI.
- **Link masters:** machine_mst(spinning frame) · item_mst(yarn) (+ **jute_yarn_mst**).
- ▶ **standards: later** — std TPI, TP (turns/inch design value). Extends the existing Spinning tab.

---

## Family E — MR%-only (beaming, packing)

### R-08-18 — Beam MR%
- **Does:** warp-beam moisture regain before the loom — 5 MR% readings per machine, Hessian & Sacking blocks.
- **Inputs:** `H` date, quality group (HESSIAN / SACKING); `R`-machine = spell→**spell_mst**, quality→**quality master** (woven/line — confirm), machine→**machine_mst**(beaming HS/S); reading_1..5 (MR%).
- **Outputs:** per-machine average MR%, overall average per quality, deviation vs std MR.
- **Link masters:** machine_mst(beaming) · spell_mst · woven/line-quality master.
- ▶ **standards: later** — std MR% per quality (Hessian≈16 / Sacking≈20).

### R-08-25 — Packing MR%
- **Does:** finished-goods moisture at packing — 10 MR% readings per quality, rolled up by fabric family.
- **Inputs:** `H` date; per-column quality_name→**quality master**, construction_code; `R` mr_pct ×10.
- **Outputs:** avg MR% per quality, group average per family (Hessian / Sacking).
- **Link masters:** item_mst(fabric)/fabric-quality master (needs a reliable *family* field for the roll-up).
- ▶ **standards: later** — optional std MR% per quality (sheet shows no comparison today).

---

## Family F — Fabric construction / measures (weaving)

### R-08-19 — Fabric Construction
- **Does:** audits woven cloth construction vs the per-quality standard set; corrects weight to std MR.
- **Inputs:** `H` date, quality→**fabric-construction quality master**; `R` (sl, length_yds, width_cms, ends/dm, picks/dm, mr%, obs_wt_kg) ×5.
- **Outputs:** Obs Ozs, Corrected Oz, per-column AVG, Std-vs-Actual table (length/width/ends/picks/MR/oz).
- **Link masters:** fabric-construction quality master.
- ▶ **standards: later** — std length/width/ends/picks/MR/oz-per-yd per quality.

### R-08-20 — Cutting Length
- **Does:** daily cut-length consistency — 20 pieces measured vs the standard length.
- **Inputs:** `H` date, std length (header, e.g. 78); `R` reading_1..20 (cut length).
- **Outputs:** Average, StDev, CV.
- **Link masters:** product/quality master (preferred) or machine_mst(cutting).
- ▶ **standards: later** — std cut length; optional CV% band. (⚠️ unit: title "inch" vs label "cm" — confirm.)

### R-08-21 — Width & Picks Checking
- **Does:** on-loom width (cm) & picks/dm per cloth quality; avg width vs std ±0.5% band.
- **Inputs:** `H` date, cloth quality→**cloth-quality master**; `R` loom_no→**machine_mst**(weaving), width_cm, picks_dm (picks sampled on a subset).
- **Outputs:** avg width + tolerance band flag (`$` out-of-band), avg/StDev/Max/Min picks.
- **Link masters:** machine_mst(weaving loom) · cloth-quality master.
- ▶ **standards: later** — std width (cm, stored not derived), std picks; ±0.5% tolerance.

### R-08-22 — Stitch Report
- **Does:** sewing stitch density — 5 stitch counts (stitches/dm) per machine vs standard (9).
- **Inputs:** `H` date; `R`-set = mc_no→**machine_mst**(sewing), reading_1..5.
- **Outputs:** average stitches/dm, pass/fail vs std (OK / LOW <9 / HIGH >9 — proposed).
- **Link masters:** machine_mst(sewing/finishing).
- ▶ **standards: later** — std stitch/dm (= 9; confirm fixed vs per-quality).

---

## Family G — Bag QC (finishing)

### R-08-23 — Bag Weight Summary
- **Does:** finished-bag weights + MR%, corrected to std MR; judges Heavy/Light % and spread vs std weight.
- **Inputs:** `H` date, bag_type/quality→**item_mst**(bag)/bag-quality master; `R` (sl, mr_pct, obs_bag_weight_gm).
- **Outputs:** corrected bag weight, Avg MR, Avg Obs, Avg Corr, StDev, CV%, HY/LT% (obs & corr).
- **Link masters:** item_mst(finished bag) / bag-quality master.
- ▶ **standards: later** — std weight (580/730/767), std MR% (A-type 20), ±8/−6 tolerance.

### R-08-24 — Bag Checking Report
- **Does:** full dimensional + weight + defect inspection per vendor/bag type — the acceptance gate (replaces the sheet's STD VLOOKUP table).
- **Inputs:** `H` date, bag_type→**item_mst**(bag)/bag-quality, vendor→**party_mst**, id_code; `R` (sl, length_cm, width_cm, ends/dm, picks/dm, mr%, bag_wt_gm, stitch/dm, defects).
- **Outputs:** corrected wt, per-column AVG/StDev/CV%/Min/Max, HY/LT% (obs & corr).
- **Link masters:** item_mst(bag)/bag-quality master · party_mst(vendor).
- ▶ **standards: later** — 7 std values per bag type (weight, length 94, width 57, ends 46/64, picks 50/28, stitch 10, MR 20).

---

## Family H — Defect tally (weaving QC)

### R-08-28 — Fabric Fault
- **Does:** per-loom defect audit against a fixed 15-type checklist; totals → faults-per-piece score.
- **Inputs:** `H` date; per-inspected-piece = shift A/B→**spell_mst**, cloth quality→**cloth-quality master**, loom_no→**machine_mst**(weaving), date_of_weaving; fault counts ×15; remarks.
- **Outputs:** per-piece total, per-fault total, per-fault SCORE (= total ÷ pieces inspected), grand total + grand score.
- **Link masters:** machine_mst(loom) · spell_mst · cloth-quality master · fault-type list (15 names — enum or small lookup, TBD).
- ▶ **standards: later** — canonical fault-type list & order; any per-fault demerit weight (cached = uniform 1/N).

---

## Family I — Environment

### Humidity Recording
- **Does:** department-wide temperature/RH% at fixed spots, ~3 rounds/day (AM/noon/PM) vs per-dept band.
- **Inputs:** `H` date; per row = department→**dept_mst**, spot_no (1–3) + label, round (1–3), time, temp_c, rh_pct; prepared_by.
- **Outputs:** Avg Temp, Avg RH% per dept per round, status vs band (OK/LOW/HIGH).
- **Link masters:** dept_mst.
- ▶ **standards: later** — acceptable Temp & RH% bands per department; the fixed 3-spot config.
- **Note:** overlaps the already-built Spinning **RHMR** (`JuteSqcSpinningRhmr`, per date+spell) — decide whether this is the plant-wide superset that supersedes/feeds it, to avoid double entry.

---

## R-08-02 — Emulsion (batching recipe log) — *not a sampled QC report*

- **Does:** daily batching-emulsion recipe log (oil/additives/tank) + resulting OIL % IN EMULSION vs a target band. One row per date, no sample/StDev/CV%.
- **Inputs:** `H` date; oil_used_ltr, tank_capacity_ltr, oil_pct_in_emulsion (measured), additive quantities (P-40, glycerine, ADCO, eco-fin, RBO/JBO, urea, molasses, … — fixed nullable set); rolls_made (Phase-2); prepared_by→**user_mst**.
- **Outputs:** oil% status vs target band (OK/LOW/HIGH); theoretical oil% (oil_used/tank×100) as reference.
- **Link masters:** machine_mst(spreader/emulsion line) · user_mst.
- ▶ **standards: later** — target oil% band (≈16–17%); tank capacity & oil-charge defaults.

---

## Built reports (as-built wiring) — full specs in `reports/`

These already exist in VOW (the reference pattern). Wiring shown as-built; notable gaps vs the sheet flagged.

| Report | Does | Inputs | Outputs | Masters linked | Spec file |
|--------|------|--------|---------|----------------|-----------|
| **R-08-01 Morrah** | 10-sample raw-jute heap weight vs 1200–1400 g | date, inspector, dept, quality, trolley, avg MR%, weights[10] | avg/max/min/range, CV%, LT/OK/HY counts (+% on FE) | **dept_mst** · **item_mst**(raw jute) | `R-08-01-morrah.md` |
| **R-08-16 Count** | yarn count from 450-yd wt, MR-corrected vs std count | date, spell, frame, yarn, DP/TP, wt_450, MR% | observed_count, corrected_count, per-quality avgs | **machine_mst** · **spell_mst** · **item_mst**(yarn)+**jute_yarn_mst** | `R-08-16-yarn-count-param.md` |
| **R-08-16 RHMR** | spinning-shed temp/RH log | date, spell, temperature, humidity | raw store (no stats) | **spell_mst** | `R-08-16-temp-humidity-rhmr.md` |
| **Speed/TPI entry** | actual speed + TPI per date/machine/yarn (planning feed) | date, machine, yarn, actual_speed, actual_tpi | store-only (resolved downstream) | **machine_mst** · **item_mst**(yarn) | `spinning-speed-tpi-entry.md` |
| **R-08-15 QR&CV** | 30 b/s readings → QR%, CV% (layered on R-08-16) | date, yarn, frame, 6 spindle × 5 readings | max/min/SD, avg b/s, QR%, CV% | **machine_mst** · **item_mst**(yarn) · **jute_yarn_mst** · count table | `R-08-15-yarn-qr-cv.md` |
| **R-08-15A QR&CV (special)** | QR/CV keyed to 3rd-drawing + frame, 12 flat readings — **NOT BUILT** | date, drawing m/c, frame, yarn, 12 readings | QR%, CV%, QR%@min | **machine_mst** ×2 · **item_mst**(yarn) | `R-08-15A-yarn-qr-cv-special.md` |

**Notable as-built gaps vs the sheet** (see each spec's Open Questions): Morrah is **not** MR-corrected
though the sheet shows a Corrected row; count factor uses `14400/454` → 9.02 vs sheet 9.03 (g/lb divisor);
R-08-15 CV% = `SD/QR%×100` (build) vs `SD/mean×100` (sheet); `$$`/`$` count flags not computed;
**R-08-15A and the R-08-17 20-reading TPI CV% study are not built** (only single-value Speed/TPI exists).

## Cross-page master-link summary

| Master | Pages that link to it | What it provides |
|--------|----------------------|------------------|
| **machine_mst** (`mech_code`,`machine_name`) | 03,04,05/06/07,07A,08/09/10,12/13/14,17,18,20,21,22,24,28,02 | spreaders, cards, drawing heads, frames, looms, sewing m/cs — filtered by process/section |
| **spell_mst** | 03,04,05/06/07,07A,18,28 (+ humidity rounds?) | shift / spell (A1/A2/B) |
| **dept_mst** | humidity | department for env readings |
| **item_mst** (raw jute, type 2) | 03,04 | jute qualities D/4, A/5, 8Lbs |
| **item_mst** (line quality) / **jute_quality_mst** | 05/06/07,07A,08/09/10,12/13/14,18,19,20,21,22,28 | HESSIAN, SACKING WARP/WEFT, 10Lbs, cloth qualities |
| **item_mst** (yarn) + **jute_yarn_mst** | 17 | yarn count qualities (+ existing `std_mr_pct`) |
| **item_mst** (finished bag) / bag-quality master | 23,24,25 | bag / fabric finished qualities |
| **party_mst** | 24 | bag vendor |
| **user_mst** | 02 (+ "prepared by" on most) | inspector / prepared-by |

> Two master gaps to confirm before build (not a standards question): (1) which master holds the
> **line/cloth qualities** (`jute_quality_mst` vs item-based) used across the card/drawing/weaving
> reports; (2) which master holds **finished-bag** types for R-08-23/24/25. Everything else maps to a
> known existing master above.
