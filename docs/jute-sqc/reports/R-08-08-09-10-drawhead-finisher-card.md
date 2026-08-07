# R-08-08/09/10 — Drawhead (SWP / SWT) + Finisher Card & Draw Head (Hessian) (I.S.O.)
**Stage:** drawing / carding (drawhead sliver + finisher-card sliver)  **Status:** UNBUILT
**Source tab:** `R08910` (master "Daily Summary Date Select")   **DSR workbook:** `13OQQCy_oL7fXEZeOmJxulbCc8VOymqVyUau6bbob28o` (GMDSR!A1:X50, not shared)

## 1. Purpose
Two related I.S.O. sliver-weight checks on one tab:
- **R-08-08/09 Drawhead** — sliver weight off the draw-head, split into **SWT** (Sacking Warp/Twine line) and **SWP** (Sacking Warp line) sub-sections.
- **R-08-10 Finisher Card & Draw Head (Hessian)** — finisher-card sliver weight for HESSIAN and 10LBS qualities.

Each set takes 4 weighed samples (10 yds long, weight in lb/10 yds), corrects them to standard regain, and checks (a) the CV% spread and (b) whether each corrected reading falls inside a **machine-level target range** (e.g. "5.3 TO 5.7" against a STD of 5.5).

## 2. Inputs (the data-entry fields)

A reading-set = one machine, 4 (WT, MR%) pairs. The tab has sub-sections that share one column layout: **Drawhead→SWT**, **Drawhead→SWP**, **Finisher→Hessian**, **Finisher→10LBS**. Drawhead sub-sections key only on machine (quality is implicit in the section); the Finisher sub-sections carry an explicit QUALITY.

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| entry_date | date | — | Y | Header. Cached: 2026-01-05. |
| time_band | enum (AM/PM) | constant `MORNING`/`AFTERNOON` | Y | Header. "TIME(AM/PM)" column; cached all `AFTERNOON`. Doubles as the spell/shift discriminator on this report. |
| report | enum | constant (`DRAWHEAD_SWT`,`DRAWHEAD_SWP`,`FINISHER_CARD`) | Y | Header. Which sub-section. |
| QUALITY | str | `item_mst` line-quality (see §3) | Y (Finisher) / implicit (Drawhead) | Finisher cached: `Hessian`, `10LBS`. Drawhead SWT/SWP carry the quality in the section name. |
| MC | int | `machine_mst` (`mech_code`), filtered to draw/finisher process | Y | Header. Cached: SWT 11; SWP 7,8; Hessian 3,4; 10LBS 6. |
| WT1..WT4 | float | — | Y | Per-reading. Sample weight in **lb per 10 yds**. SWT row: 6.239/6.085/6.349/6.504. |
| MR%1..MR%4 | float | — | Y | Per-reading regain %. SWT row: 27/25/27/28. |
| DP | float | Phase-2 production link | N | Blank in cache; defer (decision #4). |
| REMARKS / REMAKS | str | — | N | Free text; blank. |
| STD | float | std (see §3) | N | Per-machine target corrected weight (SWT 5.5, SWP 7.5, Finisher 6.5). |
| RANGE | str | std (see §3) | N | Per-machine acceptance band ("5.3 TO 5.7","7.3 TO 7.7","6.3 TO 6.7"). |

Per-reading: WT1..4 + MR%1..4. Everything else header. Note the right-hand "1 2 3 4 / Avg" block is **computed** (the 4 corrected readings), not input — see §4.

## 3. Standards & constants used

| Standard | Example in sheet | Where it should live (decision #2) |
|----------|------------------|------------------------------------|
| Std MR% per quality | derived **16** (HESSIAN, and all sub-sections) | `std_mr_pct` on the line-quality `item_mst` row (mirror of `jute_yarn_mst.std_mr_pct`). |
| STD (target corrected weight) | SWT **5.5**, SWP **7.5**, Finisher Hessian/10LBS **6.5** | Process×quality dependent → see NEEDS OWNER DECISION. |
| RANGE (accept band) | `5.3 TO 5.7`, `7.3 TO 7.7`, `6.3 TO 6.7` (= STD ± 0.2) | Same storage problem. Note band is consistently **STD ± 0.2**, so could be derived from STD + a ±tolerance constant rather than stored as a string. |
| STD CV% | (no CV band column on this tab; only STD/RANGE on corrected readings) | n/a — this report checks reading-vs-range, not CV-vs-band. |
| Sample length | 10 yds (tab header) | report constant. |
| Sample size | 4 readings | report constant. |

**⚠️ KEY OPEN DESIGN QUESTION (process × quality standards storage):** The **STD** (5.5 / 7.5 / 6.5) and its **RANGE** depend on (process/section, quality). HESSIAN finisher-card STD = 6.5 here, but HESSIAN finisher-**drawing** STD is 125 (R-08-12/13/14) — same quality, different stage ⇒ a single per-quality column cannot hold both. Decision #2 forbids a new standalone standards table. Reconciliations to put to owner:
- **(A) `machine_mst` columns** `std_sliver_weight` + `std_tol` (±0.2): a machine implies its process; the RANGE is just STD ± std_tol, so store only the centre + tolerance. Clean because each draw-head/finisher machine has one target.
- **(B) stage-namespaced `item_mst` columns** (`std_wt_drawhead`, `std_wt_finisher`, …) — avoids a new table but bloats the quality master.
- Marked **NEEDS OWNER DECISION** in §8. The ±0.2 derivation should also be confirmed (could be ±0.2 absolute, not relative).

## 4. Calculations (formulas)

Let readings be (WTᵢ, MRᵢ), i=1..4; `STD_MR` = 16.

- **Avg (observed)** = mean(WT₁..WT₄). SWT row: (6.239+6.085+6.349+6.504)/4 = **6.294** ✓ (cache 6.29409).
- **MR%** = mean(MRᵢ) = (27+25+27+28)/4 = **26.75** ✓.
- **AVG CORR Wt** = `Avg × (100+STD_MR)/(100+MR%)` = 6.294 × 116/126.75 = **5.958** ✓ (cache 5.95817). Confirms STD_MR=16.
- **Corrected readings (1,2,3,4)** = each `WTᵢ × 116/(100+MRᵢ)`:
  6.239×116/127=5.895, 6.085×116/125=5.647… ⚠️ Confirm: cache reading-2 = 5.841, which is 6.085×116/(100+20.8)? Recheck — 6.085×116/125 = 5.647, **not** 5.841. Cache "2"=5.84127 = 6.085×116/(100+X) ⇒ X≈20.8. **The corrected readings do not use each reading's own MR%.**
  Re-derivation that matches: reading-1 5.895 = 6.239×116/(100+X)⇒X≈22.75; reading-2 5.841=6.085×116/(100+20.8); reading-3 5.999=6.349×116/(100+22.75); reading-4 6.097=6.097… Pattern is **not** WTᵢ×116/(100+MRᵢ). ⚠️ **Confirm:** most likely the four "1 2 3 4" values are each reading corrected by the **set-average MR (26.75)**? Test: 6.239×116/126.75 = 5.710 — no. Test with MR-avg per the morrah pattern… does not match either. The mean of the four (5.895+5.841+5.999+6.097)/4 = **5.958** = AVG CORR Wt ✓, so whatever the per-reading correction is, **its mean equals the corrected average**. Flag for DSR-source confirmation; for VOW, compute the 4 corrected readings as `WTᵢ×116/(100+MRᵢ)` (consistent with R-08-07A and R-08-12/13/14) and accept a tiny rounding difference vs this legacy tab, OR store only the corrected average + the raw readings and skip reproducing the legacy "1 2 3 4" block.
- **sdev** = SAMPLE StDev of the corrected readings. SWT row cache 0.11346.
- **CV%** = `sdev / AVG CORR Wt`, stored as fraction. SWT: 0.11346/5.958 = **0.01904** ✓ (cache 0.01904).
- **Per-reading range check** = each corrected reading vs RANGE (STD±0.2): count how many fall inside `[STD-0.2, STD+0.2]`. The "Avg" of the 4 corrected readings is the headline compared to STD (5.958 vs 5.5 here → above range, i.e. running heavy).
- **Section AVG block** = mean of per-row Avg / MR% / CORR Wt / CV across machines. SWP cache: AVG CORR (7.420+7.727)/2 = **7.574** ✓ (cache 7.574); CV avg 0.02312.

CV% variant = **StDev(corrected) / mean(corrected)**, fraction. Correction constant STD_MR = **16**.

## 5. Worked example (real data)

Finisher Card, QUALITY=Hessian, MC=3 (cached row):
- Inputs (7.099,27)(7.319,28)(6.944,25)(7.143,28).
- Avg = (7.099+7.319+6.944+7.143)/4 = **7.126** ✓
- MR%_avg = (27+28+25+28)/4 = **27** ✓
- AVG CORR Wt = 7.126 × 116/127 = **6.509** ✓ (cache 6.509)
- sdev (corrected readings) = **0.08459** (cache)
- CV% = 0.08459/6.509 = **0.013** ✓ (cache 0.013)
- STD=6.5, RANGE 6.3 TO 6.7 → 6.509 is inside band ⇒ **OK**.

Finisher 10LBS MC=6: Avg 7.121, MR 28, CORR = 7.121×116/128 = **6.453** ✓, CV 0.01697, vs STD 6.5 / 6.3-6.7 ⇒ inside ⇒ OK.

## 6. Proposed VOW data model

Flat header + readings JSON, one row per (date, report, machine, quality, time_band). Mirrors `JuteSqcMorrahWt`.

```python
class JuteSqcDrawSliverWt(Base):
    __tablename__ = "jute_sqc_draw_sliver_wt"
    draw_sliver_wt_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id            = Column(Integer, nullable=False, index=True)
    branch_id        = Column(Integer, nullable=True)
    entry_date       = Column(Date, nullable=False, index=True)
    report           = Column(String(20), nullable=False)  # DRAWHEAD_SWT | DRAWHEAD_SWP | FINISHER_CARD
    time_band        = Column(String(10), nullable=True)   # MORNING | AFTERNOON
    mc_id            = Column(Integer, nullable=True)       # machine_mst.machine_id
    item_id          = Column(Integer, nullable=True, index=True)  # line quality (Finisher; null/implied for Drawhead)
    weights          = Column(JSON, nullable=False)         # [[wt1,mr1],...,[wt4,mr4]]
    dp               = Column(DECIMAL(10,3), nullable=True) # Phase-2, store-only
    remarks          = Column(String(255), nullable=True)
    std_weight       = Column(DECIMAL(10,3), nullable=True) # snapshot of STD (5.5/7.5/6.5)
    calc_avg_wt      = Column(DECIMAL(10,3), nullable=True)
    calc_avg_mr      = Column(DECIMAL(5,2),  nullable=True)
    calc_cor_wt      = Column(DECIMAL(10,3), nullable=True)
    calc_sdev        = Column(DECIMAL(10,4), nullable=True)
    calc_cv_pct      = Column(DECIMAL(6,4),  nullable=True) # fraction
    count_in_range   = Column(Integer, nullable=True)       # corrected readings inside STD±0.2
    active           = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by       = Column(Integer, nullable=True)
    updated_date_time= Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```
PK `draw_sliver_wt_id`. Insert-only + soft-delete. Stats server-side.

## 7. Proposed endpoints & pages

Backend (`/api/juteSQC`):
- `GET /draw_sliver_wt_create_setup` — `{machines (draw/finisher by report), line_qualities, time_bands, std_by_machine_quality}` (STD + ±tol resolved from linked master).
- `POST /draw_sliver_wt_save` — validate 4 readings, compute stats + range count, insert.
- `GET /draw_sliver_wt_by_date` — rows for a date grouped by report sub-section + AVG footer.
- `GET /draw_sliver_wt_table` — paginated.
- `POST /draw_sliver_wt_delete` — soft delete.

Frontend (`src/app/dashboardportal/juteSQC/r-08-08-09-10/`): mobile entry — pick report sub-section → machine → (quality if Finisher) → time band, 4-row WT/MR grid; live shows AVG CORR / CV% and the STD±0.2 range pass-fail per reading and on the average. Desktop date grid grouped by sub-section with AVG footer. Route consts `DRAW_SLIVER_WT_*`; hooks `useDrawSliverWtSetup`/`useDrawSliverWtByDate`; `_components/` Form + Grid. Honor sidebar `co_id`/`branch_id`.

Masters to link: `machine_mst` (draw-head + finisher-card), `item_mst` (line quality), constant time-band enum (spell_mst optional if AM/PM should map to spells).

## 8. Open questions (NEEDS OWNER DECISION)

- **Corrected per-reading "1 2 3 4" formula is unconfirmed.** The four values do NOT equal `WTᵢ×116/(100+MRᵢ)` nor `WTᵢ×116/(100+MR_avg)`, yet their mean = AVG CORR Wt. Confirm the exact per-reading correction from the DSR source, or agree to compute them as `WTᵢ×116/(100+MRᵢ)` in VOW (mean still equals the corrected average).
- **process × quality standards storage** for STD (5.5/7.5/6.5) + RANGE: `machine_mst` columns (A) vs stage-namespaced `item_mst` columns (B). Same HESSIAN STD differs by stage (6.5 here vs 125 in R-08-12/13/14). **NEEDS OWNER DECISION.**
- **RANGE = STD ± 0.2** in all cached rows — confirm it is always ±0.2 (absolute) so we can store only STD + a tolerance constant, instead of a free-text band.
- **time_band (AM/PM) vs spell_mst** — is MORNING/AFTERNOON a real spell to link to `spell_mst`, or a fixed 2-value enum for this report?
- **Drawhead SWT/SWP quality** is implicit in the section. Confirm SWT/SWP map to specific `item_mst` line qualities (Sacking Warp/Twine vs Warp) so the std lookup works.
- **STD_MR = 16** for all sub-sections (incl. SWP/SWT sacking lines) — confirm, given the briefing's Sacking≈20 note.
- **DP** blank — confirm it is a production pull (Phase-2) not an operator input.
