# 00 — Overview & Architecture

## What we're replacing

The Empire Jute Mill SQC (Statistical Quality Control) desk runs entirely on Google Sheets +
Google Forms. Every day, lab/floor staff record quality readings at each manufacturing stage; the
numbers roll up into ISO quality records (R-08-01 … R-08-28). The goal is to run this **from VOW**,
make the embedded standards **configurable**, and **link the inputs to existing VOW masters**.

## How the Google system works today

```
┌─────────────────┐   Google Form (phone)   ┌──────────────────────────┐
│  Lab / floor    │ ───── OR manual ──────▶ │  Per-report "DSR" source │
│  staff          │        typing           │  workbook (real entry +  │
└─────────────────┘                         │  the LIVE formulas)      │
                                            └────────────┬─────────────┘
                                                IMPORTRANGE │ (by report)
                                                            ▼
                              ┌───────────────────────────────────────────────┐
                              │  Master "Daily Summary Date Select"            │
                              │  • one tab per report (R01, R02, … R28, HUMIDITY)│
                              │  • a green date cell drives which day shows     │
                              │  • computes Avg / Corrected / StDev / CV% /     │
                              │    LT-OK-HY buckets vs the report's STANDARDS   │
                              └───────────────────────────────────────────────┘
```

- **Only 3 reports are Form-fed** (R-08-01 Morrah, R-08-02 Emulsion, R-08-04 Spreader Roll Weight have
  `forms.gle` links). The rest are **typed directly** into their DSR workbooks.
- The **DSR source workbooks hold the real formulas** (MR correction, CV%, count conversion, band
  lookups). They are **not shared** with us. The master only caches their output. So we reverse-engineer
  the formulas from the cached numbers (done — see `01-standards-and-formulas.md`) and flag the rest.
- The standards that make the sheet "smart" — machine lists, qualities, std weights, std MR%, std
  counts, CV% bands, emulsion recipe items — are **typed into the sheets**. Making them dynamic =
  moving them onto VOW masters.

## The VOW target

```
Portal user (mobile/desktop)
   │  enters a reading-set on a juteSQC entry page (date + machine/quality/spell from masters)
   ▼
/api/juteSQC/<report>_save   ──▶  jute_sqc_<report> (+ _dtl)   [insert-only, soft-delete, like the built ones]
   │  stats computed in Python at save/read (avg, corrected, stdev, CV%, buckets) vs std from masters
   ▼
/api/juteSQC/<report>_by_date  ──▶  date-driven summary/report view (the "master tab" equivalent)
```

- **Module:** `juteSQC` (already exists). Backend `src/juteSQC/`, prefix `/api/juteSQC` (registered).
  Frontend `src/app/dashboardportal/juteSQC/`.
- **Persona:** Tenant **Portal** — `Depends(get_tenant_db)`, scoped by `co_id`/`branch_id` from the
  sidebar, auth via `get_current_user_with_refresh`. (See repo `CLAUDE.md` three-persona rules.)
- **Pattern to copy:** the built reports — Morrah (`morrahWeight.py`, single report) and Spinning
  (`spinning_sqc.py`, multi-tab with count/RHMR/QR-CV). Same insert-only + compute-on-read style.

## The 4 locked decisions (product owner, this engagement)

| # | Decision | Consequence for the spec |
|---|----------|--------------------------|
| 1 | **Scope = unbuilt reports only** | Spec R-08-02→14, 17, 18→28, humidity. R-08-01 + Spinning are the *reference pattern*. |
| 2 | **Standards live on existing masters (extend, don't add new tables)** | Add std columns (`std_mr_pct`, `std_weight`, `std_cv_low/high`, `std_count`, …) to existing masters. New *entry* tables are still created. ⚠️ Per-(process×quality) standards don't fit one master cleanly — see open questions. |
| 3 | **Mobile-friendly portal entry pages** | Each report gets a phone-friendly entry form (one reading-set at a time) + a desktop date summary view. Replaces Google Forms inside VOW. |
| 4 | **Masters only for now (no production-transaction pulls)** | Link machine/quality/yarn/dept/spell lists to existing masters. "Rolls made", "frames running", count→spinning, etc. are **Phase-2** links (documented, not built). |

## Report families (so the build reuses one pattern per family)

| Family | Reports | Shared shape |
|--------|---------|--------------|
| **A — Sliver/Roll weight** | 03, 04, 05/06/07, 07A, 08/09/10, 12/13/14 | header (m/c, spell, quality) + 4 (or 10) weight + MR% readings → avg, **corrected wt**, stdev, CV%, vs **std weight** + **CV% band**; per-quality grand averages |
| **B — Count / parameter** | 16 *(built)* | WT/450yds → **count**, corrected count, `$$/$` flags |
| **C — Strength QR/CV** | 15, 15A *(built)* | 30 strength readings → QR%, CV% |
| **D — Twist** | 17 | 20 TPI readings → avg/stdev/CV%, std TPI, min/max |
| **E — MR% only** | 18 (beam), 25 (packing) | a few MR% readings averaged per machine/quality (no weight correction) |
| **F — Fabric construction/measure** | 19, 20, 21, 22 | physical fabric measures (width, picks, ends, length, ozs, MR, cutting len, stitch) std-vs-actual |
| **G — Bag QC** | 23 (weight), 24 (checking) | finished bag weight/MR vs std; defect checklist |
| **H — Defect tally** | 28 (fabric fault) | matrix fault-type × loom, counts → normalized score |
| **I — Environment** | humidity | temp/humidity by department & time |

Each `reports/*.md` documents one report against this shared family logic.
