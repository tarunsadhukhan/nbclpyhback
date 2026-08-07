# R-08-12/13/14 — Finisher Drawing Sliver Weight (HESS / SKWP / SWT) (I.S.O.)
**Stage:** drawing (finisher-drawing sliver)  **Status:** UNBUILT
**Source tab:** `R0121314` (legacy) + `NEWR0121314` (new layout) — master "Daily Summary Date Select"   **DSR workbook:** `1IRVuq3oPmerJMbzXLzoNIIXXsPxcFEa3V0S3y21oywg` (GMDSR!A1:Y160 / NEWGMDSR!A1:AC55, not shared)

## 1. Purpose
Measures the finisher-drawing sliver weight uniformity across three line families — **HESS** (Hessian + 10 Lbs), **SWP** (Sacking Warp), **SWT** (Sacking Warp/Twine). Per machine, 4 sliver samples (50 yds long, weight in lb/50 yds) are weighed and moisture-corrected; the report checks the corrected average against the per-quality STD (with a ±1 lb accept band) and the CV% against a per-quality CV% band. A GRAND AVERAGE block rolls each quality up across machines.

## 2. Inputs (the data-entry fields)

A reading-set = one machine row with 4 (WT, MR%) pairs. Three sub-sections (HESS / SWP / SWT) share one column layout. **Two layouts exist** — VOW should adopt the **NEW** layout (it adds a DLV NO per reading and a per-quality GRAND AVERAGE; weights are entered as integers):

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| DATE | date | — | Y | Header. Cached: 2026-01-05. |
| section | enum | constant (`HESS`,`SWP`,`SWT`) | Y | Header. Which sub-table. |
| QUALITY | str | `item_mst` line-quality (see §3) | Y | Header. Cached: HESS→`HESSIAN`/`10 Lbs`; SWP→`SWP`; SWT→`SWT`. |
| MC | int | `machine_mst` (`mech_code`), finisher-drawing process | Y | Header. Cached: 1,3,4,5,6,7 (HESS), 7,8 (SWP), 15 (SWT). |
| DLV NO 1..4 | int | constant | N (NEW layout only) | Per-reading delivery/can number. Cached 5,5,6,6 (HESS) / 19,19,20,20 (10 Lbs) — identifies which drawing delivery the sample came off. |
| WT1..WT4 | float | — | Y | Per-reading. Sample weight in **lb per 50 yds**. Legacy keeps decimals (142.2); NEW rounds to int (142). |
| MR%1..MR%4 | float | — | Y | Per-reading regain %. Cached HESS MC1: 25/25/23/24. |
| DP | float | Phase-2 production link | N | Blank in cache; defer (decision #4). |
| REMARKS / REAMARKS | str | — | N | Free text; blank. |
| STD(LB) | float | std (see §3) | N | Per-quality std sliver weight: HESSIAN 125, 10 Lbs 140, SWP 150, SWT 160. |
| RANGE(LB) | str | std (see §3) | N | STD ± 1 lb: "124-126","139-141","149-151","159-161". |
| STD CV% | str | std (see §3) | N | Per-quality CV band: HESSIAN/10Lbs "4-6%", SWP "6-8%", SWT "8-10%". |

Per-reading: (DLV NO), WT, MR% ×4. Everything else header. C1..C4, AVG, AVGMR, AVGC, STDEV, CV% are **computed** (see §4) — not input.

## 3. Standards & constants used

| Standard | Example in sheet | Where it should live (decision #2) |
|----------|------------------|------------------------------------|
| Std MR% per quality | derived **16** (HESSIAN, 10 Lbs, SWP, SWT all reconcile at 16) | `std_mr_pct` on line-quality `item_mst` row (mirror `jute_yarn_mst.std_mr_pct`). |
| STD(LB) std sliver weight | HESSIAN **125**, 10 Lbs **140**, SWP **150**, SWT **160** | Process×quality dependent → see NEEDS OWNER DECISION. |
| RANGE(LB) accept band | STD ± 1 ("124-126" etc.) | Derive from STD + ±1 constant rather than store a string. |
| STD CV% band | "4-6%" / "6-8%" / "8-10%" | Process×quality dependent → same storage problem. |
| Sample length | 50 yds (tab header) | report constant. |
| Sample size | 4 readings (4 deliveries) | report constant. |

**⚠️ KEY OPEN DESIGN QUESTION (process × quality standards storage):** STD(LB), RANGE(LB) and STD CV% are keyed by **(finisher-drawing process, quality)**. HESSIAN here = STD 125 / band 4-6%, but HESSIAN at finisher-**card** (R-08-10) = STD 6.5 — same quality, different stage. A single per-quality column on `item_mst` cannot hold both. Decision #2 forbids a new standalone standards table. Reconciliations to put to owner:
- **(A) `machine_mst` columns** `std_sliver_weight`, `std_wt_tol` (=1), `std_cv_low`, `std_cv_high` — a finisher-drawing machine implies its process; the quality run is the header selection. Range = STD±tol.
- **(B) stage-namespaced `item_mst` columns** (`std_wt_fdrawing`, `std_cv_low_fdrawing`, …) — no new table but bloats the master and must be repeated per stage.
- Marked **NEEDS OWNER DECISION** in §8.

## 4. Calculations (formulas)

Readings (WTᵢ, MRᵢ), i=1..4; `STD_MR` = 16.

- **C1..C4 (corrected readings)** = `WTᵢ × (100+STD_MR)/(100+MRᵢ)` = `WTᵢ × 116/(100+MRᵢ)`.
  Worked (legacy HESS MC1): C1 = 142.2×116/125 = **131.98** (cache C1 132.0 / NEW 131.78 from WT=142); C3 = 132.06×116/123 = **124.55** (cache 124.5) ✓. This report's per-reading correction IS the standard formula (unlike R-08-08/09/10).
- **AVG (observed)** = mean(WTᵢ) = (142.2+147.3+132.1+136.5)/4 = **139.52** ✓ (cache 139.524).
- **AVGMR** = mean(MRᵢ) = (25+25+23+24)/4 = **24.25** ✓.
- **AVGC (corrected average)** = mean(C1..C4) = (132+136.7+124.5+127.7)/4 = **130.2** ✓ (cache 130.23). Equivalently `AVG×116/(100+AVGMR)` = 139.52×116/124.25 = 130.25 ≈ AVGC (small diff because per-reading correction ≠ average correction; **AVGC is the mean of the corrected readings**, use that).
- **STDEV** = SAMPLE StDev of **C1..C4** (corrected readings). Worked: sample-stdev(132,136.7,124.5,127.7) = **5.278** ✓ (cache 5.27770). (Observed-weight stdev would be 6.71 — confirms STDEV is over corrected readings.)
- **CV%** = `STDEV / AVGC`, stored as **fraction**. Worked: 5.278/130.2 = **0.04053** ✓ (cache 0.0405255).
- **Accept checks:** corrected average AVGC vs RANGE(LB) (STD±1); CV%×100 vs STD CV% band. HESS MC1: AVGC 130.2 vs 124-126 → **above range (heavy)**; CV 4.05% within 4-6% → CV OK.
- **GRAND AVERAGE per quality** = across all rows of that quality: OBS = mean(AVG), MR% = mean(AVGMR), CORR = mean(AVGC), AVG CV% = mean(CV%).
  Worked HESSIAN (5 rows: MC1,3,4,5,6): CORR = (130.2+132.4+135+144.9+141.8)/5 = **136.86** ✓ (cache 136.886); OBS mean = **146.86** ✓ (cache 146.857).

CV% variant = **StDev(corrected) / mean(corrected)**, fraction. Correction constant STD_MR = **16**.

## 5. Worked example (real data)

HESS, QUALITY=HESSIAN, MC=4 (legacy cached row):
- Inputs (150.5,26)(148.6,26)(138.4,23)(143.5,24).
- C1..C4 = 150.5×116/126=138.5, 148.6×116/126=136.8, 138.4×116/123=130.5, 143.5×116/124=134.2 ✓ (cache 138.5/136.8/130.5/134.2).
- AVG = (150.5+148.6+138.4+143.5)/4 = **145.2** ✓
- AVGMR = (26+26+23+24)/4 = **24.75** ✓
- AVGC = (138.5+136.8+130.5+134.2)/4 = **135.0** ✓ (cache 135.0)
- STDEV(C1..C4) = **3.472** ✓ (cache 3.4723)
- CV% = 3.472/135.0 = **0.02572** ✓ (cache 0.025717) = 2.57% → within 4-6%? No, **below band** (very uniform). vs RANGE 124-126 → 135 is high.

SWT MC=15 (single row): AVG 171, MR 23.75, AVGC = corrected-mean **165.7** ✓ (cache 165.7), STDEV 5.626, CV 5.626/165.7 = **0.03394** ✓ vs STD 160 / 8-10%.

## 6. Proposed VOW data model

Flat header + readings JSON (4 readings, fixed). One row per (date, section, quality, machine). Adopt the NEW layout's DLV NO per reading.

```python
class JuteSqcFinDrawSliverWt(Base):
    __tablename__ = "jute_sqc_fin_draw_sliver_wt"
    fin_draw_sliver_wt_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id            = Column(Integer, nullable=False, index=True)
    branch_id        = Column(Integer, nullable=True)
    entry_date       = Column(Date, nullable=False, index=True)
    section          = Column(String(10), nullable=False)  # HESS | SWP | SWT
    item_id          = Column(Integer, nullable=False, index=True)  # line quality (item_mst)
    mc_id            = Column(Integer, nullable=True)       # machine_mst.machine_id
    readings         = Column(JSON, nullable=False)         # [[dlv,wt,mr],...] x4
    dp               = Column(DECIMAL(10,3), nullable=True) # Phase-2, store-only
    remarks          = Column(String(255), nullable=True)
    std_weight       = Column(DECIMAL(10,2), nullable=True) # snapshot STD(LB)
    calc_avg_wt      = Column(DECIMAL(10,2), nullable=True) # observed avg
    calc_avg_mr      = Column(DECIMAL(5,2),  nullable=True)
    calc_avg_corr    = Column(DECIMAL(10,2), nullable=True) # AVGC = mean(C1..C4)
    calc_stdev       = Column(DECIMAL(10,4), nullable=True) # over corrected readings
    calc_cv_pct      = Column(DECIMAL(6,4),  nullable=True) # fraction
    in_wt_range      = Column(Integer, nullable=True)       # 1 if AVGC within STD±1 else 0
    in_cv_band       = Column(Integer, nullable=True)       # 1 if CV%×100 within STD CV band
    active           = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by       = Column(Integer, nullable=True)
    updated_date_time= Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```
PK `fin_draw_sliver_wt_id`. Insert-only + soft-delete. Stats + grand-average computed server-side (grand average = aggregate at read, like the Spinning Count AVG pattern).

## 7. Proposed endpoints & pages

Backend (`/api/juteSQC`):
- `GET /fin_draw_sliver_wt_create_setup` — `{machines (finisher-drawing), line_qualities (per section), std_by_quality}` (STD(LB) + ±1 + CV band resolved from linked master).
- `POST /fin_draw_sliver_wt_save` — validate 4 readings, compute C1..C4 / AVGC / STDEV / CV% + range/band flags, insert.
- `GET /fin_draw_sliver_wt_by_date` — rows for a date grouped by section, plus per-quality GRAND AVERAGE block (compute at read).
- `GET /fin_draw_sliver_wt_table` — paginated list.
- `POST /fin_draw_sliver_wt_delete` — soft delete.

Frontend (`src/app/dashboardportal/juteSQC/r-08-12-13-14/`): mobile entry — pick section → quality → machine, 4-row (DLV/WT/MR) grid; live shows AVGC / CV% and STD±1 / CV-band pass-fail. Desktop date grid grouped by section + GRAND AVERAGE footer per quality. Route consts `FIN_DRAW_SLIVER_WT_*`; hooks `useFinDrawSliverWtSetup`/`useFinDrawSliverWtByDate`; `_components/` Form + Grid. Honor sidebar `co_id`/`branch_id`.

Masters to link: `machine_mst` (finisher-drawing), `item_mst` (line qualities HESSIAN/10 Lbs/SWP/SWT), DLV NO as a constant/int input (Phase-2 link to a delivery/can master if one exists).

## 8. Open questions (NEEDS OWNER DECISION)

- **process × quality standards storage** for STD(LB)/RANGE/STD CV% — `machine_mst` columns (A) vs stage-namespaced `item_mst` columns (B). HESSIAN STD differs by stage (125 finisher-drawing vs 6.5 finisher-card). **NEEDS OWNER DECISION** — no new standalone standards table per decision #2.
- **Legacy vs NEW layout** — adopt NEW (DLV NO per reading, integer weights, per-quality GRAND AVERAGE)? Confirm DLV NO is a required operator input and what master (if any) it maps to.
- **STD_MR = 16** for all four qualities incl. SWP/SWT sacking lines — confirm vs briefing's Sacking≈20.
- **AVGC = mean of corrected readings** (not `AVG×correction`). Confirm VOW computes AVGC as the per-reading-corrected mean (the two differ slightly).
- **RANGE = STD ± 1 lb** and **CV band** are fixed strings in the sheet — confirm we store STD + a ±1 tolerance + (cv_low, cv_high) rather than free text.
- **CV% stored as fraction** (0.04053) — confirm display ×100 and pass/fail compares CV%×100 to the band.
- **SWP/SWT quality mapping** — SWP and SWT appear both as section names and quality names. Confirm each maps to a distinct `item_mst` line quality (Sacking Warp vs Sacking Warp/Twine) so std lookup is unambiguous.
- **GRAND AVERAGE** is an unweighted mean of per-machine averages (as derived) — confirm it should not be weight/reading-count weighted.
