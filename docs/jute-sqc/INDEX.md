# Jute SQC — VOW Rollout Spec

Moving the **Empire Jute Mill "Daily SQC"** Google-Sheet system (reports **R-08-01 … R-08-28** +
humidity) into the VOW ERP `juteSQC` module so the whole quality-control desk runs from VOW, with
the standard parameters (machine lists, qualities, std weights/CV bands) made **dynamic/configurable**
and the inputs **linked to existing masters**.

> This folder is the **spec** (design + plan), not the implementation. It tells a developer exactly
> what each unbuilt report needs: inputs, formulas, constants, the data model, the masters to link,
> the entry/report pages, and the open decisions.

## How this folder is organised

**Start here → `04-page-wiring.md`** (per page: what it does · inputs · outputs · which master to link).

> **Scope:** all ~28 reports at full depth (unbuilt + already-built, as-built). **Owner refinements:**
> (1) **Standards** live in a **satellite table linked by `item_id`** (like `jute_yarn_mst`), reused or
> created per stage — **case-by-case**, see `05-standards-storage.md`; exact tables decided in
> discussion (`▶ standards: later`). (2) **Entry UX** = **tabbed pages per stage**, entry tabs built
> **responsive** for mobile/tablet. (3) **Linkages** = keep what's already linked, defer the rest.

| File | What it covers |
|------|----------------|
| `INDEX.md` | This file — map + report inventory + status |
| `04-page-wiring.md` | ⭐ **Start here** — per-page wiring: does / inputs / outputs / master links |
| `05-standards-storage.md` | The agreed standards approach: `item_id`-keyed satellite tables, case-by-case |
| `00-overview-and-architecture.md` | How the Google system works today, the VOW target, the decisions |
| `01-standards-and-formulas.md` | The cross-cutting jute-SQC math (the report *outputs*): MR correction, count conversion, CV%, buckets/flags (verified) |
| `02-linking-map.md` | What links to what — every report's lists → existing VOW masters; Phase-2 production links |
| `03-setup-guide.md` | How to build it: phasing, migrations, tabbed responsive pages, menu, tests |
| `reports/*.md` | One detailed spec per report (inputs, formulas, model, endpoints, pages, worked example) |

## Report inventory & status

Process flow (jute mill): **Selection → Batching/Softening → Carding → Drawing → Spinning → Winding/Beaming → Weaving → Finishing/Packing.**

| Report | Name | Stage | Status in VOW |
|--------|------|-------|---------------|
| R-08-01 | Morrah Weight | Selection | ✅ Built — as-built spec `reports/R-08-01-morrah.md` |
| R-08-02 | Emulsion (oil recipe & oil%) | Batching | ⬜ spec → `reports/R-08-02-emulsion.md` |
| R-08-03 | Spreader Roll Sliver Weight | Carding | ⬜ `reports/R-08-03-spreader-roll-sliver-weight.md` |
| R-08-04 | Spreader Roll Weight | Carding | ⬜ `reports/R-08-04-spreader-roll-weight.md` |
| R-08-05/06/07 | Breaker Card (coarse side SWT) | Carding | ⬜ `reports/R-08-05-06-07-breaker-card.md` |
| R-08-07A | Inter Card & Tow Breaker Sliver Weight | Carding | ⬜ `reports/R-08-07A-inter-card-tow-breaker.md` |
| R-08-08/09/10 | Drawhead (SWP/SWT) + Finisher Card | Drawing | ⬜ `reports/R-08-08-09-10-drawhead-finisher-card.md` |
| R-08-12/13/14 | Finisher Drawing Sliver Weight (Hess/SKWP/SWT) | Drawing | ⬜ `reports/R-08-12-13-14-finisher-drawing.md` |
| R-08-15 | Yarn QR% & CV% | Spinning | ✅ Built — as-built spec `reports/R-08-15-yarn-qr-cv.md` |
| R-08-15A | Yarn QR% & CV% (special purpose) | Spinning | ⚠️ as-built/gap spec `reports/R-08-15A-yarn-qr-cv-special.md` |
| R-08-16 | Yarn Count/Param | Spinning | ✅ Built — as-built spec `reports/R-08-16-yarn-count-param.md` |
| R-08-16 | Temp/Humidity (RHMR) | Spinning | ✅ Built — as-built spec `reports/R-08-16-temp-humidity-rhmr.md` |
| — | Spinning Speed / Actual TPI entry | Spinning | ✅ Built — `reports/spinning-speed-tpi-entry.md` (relates to R-08-17) |
| R-08-17 | Yarn T.P.I & T.P.I. CV% | Spinning | ⚠️ Partial (Speed/TPI single-value exists) → `reports/R-08-17-yarn-tpi.md` |
| R-08-18 | Beam MR% (Hessian/Sacking) | Winding/Beaming | ⬜ `reports/R-08-18-beam-mr.md` |
| R-08-19 | Fabric Construction | Weaving | ⬜ `reports/R-08-19-fabric-construction.md` |
| R-08-20 | Cutting Length | Weaving | ⬜ `reports/R-08-20-cutting-length.md` |
| R-08-21 | Width & Picks Checking | Weaving | ⬜ `reports/R-08-21-width-picks.md` |
| R-08-22 | Stitch Report | Weaving | ⬜ `reports/R-08-22-stitch.md` |
| R-08-23 | Bag Weight Summary | Finishing | ⬜ `reports/R-08-23-bag-weight.md` |
| R-08-24 | Bag Checking Report | Finishing | ⬜ `reports/R-08-24-bag-checking.md` |
| R-08-25 | Packing MR% | Finishing | ⬜ `reports/R-08-25-packing-mr.md` |
| R-08-28 | Fabric Fault | Finishing/QC | ⬜ `reports/R-08-28-fabric-fault.md` |
| — | Humidity Recording | All depts | ⬜ `reports/humidity-recording.md` |

## Source-of-truth note

The master Google workbook is **"Daily Summary Date Select"** (`1aUETk61DagSSHnI0bOsl_AM9R8bxXw6RPE-BRlAVY-Q`).
It is a **date-driven view** that `IMPORTRANGE`s from per-report **DSR source workbooks** (the real
entry sheets + formulas). Those DSR workbooks are **not shared** with us, so this spec is built from
the **cached computed values inside the master tabs** (real entries dated 05/01/2026), the two shared
response sheets (Morrah, R-08-15), and the already-built VOW reference code. Anything not 100%
confirmable from cached values is flagged in `05-open-questions.md`.
