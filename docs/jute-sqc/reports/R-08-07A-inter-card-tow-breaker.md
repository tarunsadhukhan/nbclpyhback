# R-08-07A — Inter Card & Tow Breaker Sliver Weight
**Stage:** carding (inter-card / tow-breaker / hopper sliver)  **Status:** UNBUILT
**Source tab:** `R07A` (master "Daily Summary Date Select")   **DSR workbook:** `1SO7rvII2iVhVha4cDwPw0kgKjJMwAJ87jHrdcQnOAZ4` (GMADSR!A1:U136, not shared)

## 1. Purpose
Measures the sliver weight uniformity coming off the **Inter-Card**, **Tow-Breaker** and **Hopper** machines: 4 weighed samples (each 5 yds long, weight recorded in lb/5 yds) are taken per machine, moisture-corrected to standard regain, and the spread (StDev / CV%) is compared against the per-quality CV% band. It is the carding-stage analogue of the spreader/drawing sliver-weight checks.

## 2. Inputs (the data-entry fields)

One reading-set = one machine on one spell for one quality, with **4 weight+MR pairs** (WT1/MR%1 … WT4/MR%4). The tab has three independent sub-sections (Inter-Card / Tow-Breaker / Hopper) that share an identical column layout; treat the sub-section as a `section` header field.

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| entry_date | date | — | Y | Header. One date drives the whole tab (cached: 2026-01-05). |
| section | enum | constant (`INTER_CARD` / `TOW_BREAKER` / `HOPPER`) | Y | Header. Which sub-table the row belongs to; selects the machine process filter. |
| MC | int/str | `machine_mst` (`mech_code` / machine_name), filtered to carding section | Y | Header. Cached values: `2`,`4`,`` `9A ``,`11`. Note `` `9A `` has a leading back-tick → MC is a **string code**, not a pure int. |
| SPELL | str | `spell_mst` (spell_code) | Y | Header. Cached: `A1`. |
| Qlty | str | `item_mst` line-quality (see §3) | Y | Header. Cached: `SACKING WEFT`. |
| WT1..WT4 | float | — | Y | Per-reading. Sample weight in **lb per 5 yds**. Cached row1: 20.33 / 21.08 / 20.11 / 21.38. |
| MR%1..MR%4 | float | — | Y | Per-reading. Moisture regain % for each sample. Cached row1: 25 / 28 / 26 / 28. |
| Reqd Wt | float | std (see §3) | N | Header label "Reqd Wt" present but **blank** in cached data — the per-quality standard sliver weight. |
| DP (run) | float | Phase-2 production link | N | "Draft potential / draughts running" — blank in cache; do not wire yet. |
| Draft | float | Phase-2 production link | N | Blank in cache. |
| REMARKS | str | — | N | Free text; blank in cache. |

Only WT1..4 + MR%1..4 are per-reading; everything else is header. The Tow-Breaker section uses the same fields; Hopper section header shows `STD WT` instead of `COR WT` in the average block (see §4 ⚠️).

## 3. Standards & constants used

| Standard | Example in sheet | Where it should live (decision #2) |
|----------|------------------|------------------------------------|
| Std MR% per quality (correction target) | SACKING ⇒ **16** (derived; see §4 worked example) | Add `std_mr_pct` to the **line-quality master** = `item_mst` row for the quality (mirrors `jute_yarn_mst.std_mr_pct`). ⚠️ NOTE the universal-formula table claims Sacking≈20, but **this tab's corrected values only reconcile with stdMR=16** for SACKING WEFT at the inter-card stage — confirm with owner. |
| STD CV% band | `6-8%` (all rows, both sections) | Process×quality dependent → does **not** fit a single per-quality column. See **NEEDS OWNER DECISION** below. |
| Reqd Wt (std sliver weight) | column present, blank in cache | Same process×quality storage problem as CV band. |
| Sample length | 5 yds (fixed, from tab header) | Report-level constant in code; not a master. |
| Sample size | 4 readings per set | Report-level constant. |

**⚠️ KEY OPEN DESIGN QUESTION (process × quality standards storage):** "STD CV% = 6-8%" and "Reqd Wt" are keyed by **(process, quality)** — the SAME quality (SACKING WEFT) at a different stage would have a different std weight/band. A single `std_cv_low`/`std_cv_high`/`std_weight` column on the `item_mst` quality row cannot represent that. Decision #2 forbids a new standalone standards table. Two concrete reconciliations to put to the owner:
- **(A) Store on `machine_mst`:** add `std_sliver_weight`, `std_cv_low`, `std_cv_high` to each carding `machine_mst` row — a machine implies its process, and the quality run on it is the header selection, so the (machine→process, quality→band) pair is captured at entry time by reading the band off the machine row. Simple, but if one machine runs multiple qualities the band must be the same per machine.
- **(B) Store on the line-quality `item_mst` row but namespaced by stage** — add columns prefixed per stage (`std_cv_low_card`, `std_cv_high_card`). Ugly but avoids a new table.
- Marked **NEEDS OWNER DECISION** in §8.

## 4. Calculations (formulas)

Let the 4 readings be (WTᵢ, MRᵢ), i=1..4; `STD_MR` = the quality's std MR%.

- **Avg (observed)** = mean(WT₁..WT₄).
  Worked (row1 Inter-Card, SACKING WEFT): (20.326+21.076+20.106+21.384)/4 = **20.723** ✓ (cache: 20.72310).
- **MR%** (avg) = mean(MR₁..MR₄) = (25+28+26+28)/4 = **26.75** ✓.
- **COR WT** (corrected average weight) = `Avg × (100 + STD_MR) / (100 + MR%_avg)`.
  Worked: 20.723 × (100+16)/(100+26.75) = 20.723 × 116/126.75 = **19.617** ✓ (cache: 19.61704). → confirms **STD_MR = 16** for SACKING WEFT here.
- **sdev** = SAMPLE StDev of the **corrected** per-reading weights (Python `statistics.stdev`, SQL `STDDEV_SAMP`).
  ⚠️ Confirm: cached sdev=0.38128. Corrected per-reading weights = WTᵢ×116/(100+MRᵢ): 20.326×116/125=18.86, 21.076×116/128=19.10, 20.106×116/126=18.51, 21.384×116/128=19.38 → mean 18.96, sample stdev ≈ **0.379** ≈ 0.38128 ✓. So **sdev is over the corrected readings**, not the raw weights.
- **CV%** = `sdev / COR WT` (stored as a fraction, not ×100).
  Worked: 0.38128 / 19.617 = **0.01944** ✓ (cache: 0.01943613). NB the sheet stores CV% as a **decimal fraction** (0.01944 = 1.944%), divided by the **corrected average**. Display layer multiplies ×100.
- **STD CV%** = reference band string (`6-8%`) — pass/fail = CV%×100 within band.
- **Section AVG block** = mean of the per-row Avg / MR% / COR WT / sdev across all machines in the section. Worked (Inter-Card, 3 rows): COR WT avg = (19.617+14.991+19.032)/3 = **17.880** ✓ (cache: 17.87999).

CV% variant for this report = **StDev(corrected) / mean(corrected)** (the sliver-family definition), stored as a fraction.

## 5. Worked example (real data)

Inter-Card, MC=`` `9A ``, SPELL=A1, Qlty=SACKING WEFT (cached row 3):
- Inputs: (19.40,24) (18.30,23) (20.37,25) (20.94,26).
- Avg = (19.400+18.298+20.370+20.944)/4 = **19.753** ✓
- MR%_avg = (24+23+25+26)/4 = **24.5** ✓
- COR WT = 19.753 × 116/124.5 = **19.032** ✓
- Corrected readings: 19.40×116/124=18.15, 18.30×116/123=17.26, 20.37×116/125=18.90, 20.94×116/126=19.28 → sample stdev = **0.9254** ✓
- CV% = 0.9254 / 19.032 = **0.04862** (4.86%) ✓ vs band 6-8% → **below band** (good, low variation).

Tow-Breaker single row (MC=11, SACKING WEFT): Avg 22.211, MR 36.5, COR WT = 22.211×116/136.5 = **19.518** ✓, sdev 0.8862, CV% 0.8862/19.518 = **0.04540** ✓.

## 6. Proposed VOW data model

Flat header table + raw readings as JSON (mirrors `JuteSqcMorrahWt`, since the set is small and fixed at 4). One row per (date, section, machine, spell, quality).

```python
class JuteSqcCardSliverWt(Base):
    __tablename__ = "jute_sqc_card_sliver_wt"
    card_sliver_wt_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id            = Column(Integer, nullable=False, index=True)
    branch_id        = Column(Integer, nullable=True)
    entry_date       = Column(Date, nullable=False, index=True)
    section          = Column(String(20), nullable=False)   # INTER_CARD | TOW_BREAKER | HOPPER
    mc_id            = Column(Integer, nullable=True)        # machine_mst.machine_id (display mech_code)
    mc_code          = Column(String(20), nullable=True)     # keep raw code e.g. `9A (back-tick literal)
    spell_id         = Column(Integer, nullable=True)        # spell_mst.spell_id
    item_id          = Column(Integer, nullable=False, index=True)  # line quality (item_mst)
    weights          = Column(JSON, nullable=False)          # [[wt1,mr1],...,[wt4,mr4]]
    reqd_wt          = Column(DECIMAL(10,3), nullable=True)  # std sliver weight snapshot (optional)
    dp_run           = Column(DECIMAL(10,3), nullable=True)  # Phase-2 production link, store-only
    draft            = Column(DECIMAL(10,3), nullable=True)  # Phase-2, store-only
    remarks          = Column(String(255), nullable=True)
    calc_avg_wt      = Column(DECIMAL(10,3), nullable=True)
    calc_avg_mr      = Column(DECIMAL(5,2),  nullable=True)
    calc_cor_wt      = Column(DECIMAL(10,3), nullable=True)
    calc_sdev        = Column(DECIMAL(10,4), nullable=True)
    calc_cv_pct      = Column(DECIMAL(6,4),  nullable=True)  # fraction (0.01944), display ×100
    active           = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by       = Column(Integer, nullable=True)
    updated_date_time= Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
```
PK `card_sliver_wt_id`. Insert-only; soft-delete via `active`. Stats recomputed server-side at save (and recomputable at read) exactly like `compute_morrah_stats`.

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`):
- `GET /card_sliver_wt_create_setup` — returns `{machines (carding, by section), spells, line_qualities, std_by_quality}` (std MR% + CV band + reqd wt resolved from the linked masters).
- `POST /card_sliver_wt_save` — validates 4 readings, all WT/MR > 0, computes stats, inserts.
- `GET /card_sliver_wt_by_date` — rows for a date (grouped by section) + section-average block.
- `GET /card_sliver_wt_table` — paginated list (mirrors `get_morrah_wt_table`).
- `POST /card_sliver_wt_delete` — soft delete (`active=0`).

Frontend (`src/app/dashboardportal/juteSQC/r-08-07a/`): mobile-first entry form — pick section → machine → spell → quality, then a 4-row WT/MR grid; live shows Avg/COR WT/CV% and band pass/fail. Desktop date-driven summary grid grouped by section with the AVG footer. Route consts in `apiRoutesPortalMasters` (`CARD_SLIVER_WT_*`); hooks `useCardSliverWtSetup` / `useCardSliverWtByDate`; `_components/` Form + Grid. Honor `co_id`/`branch_id` from `SidebarContext`.

Masters to link: `machine_mst` (carding, by section/process), `spell_mst`, `item_mst` (line quality), `dept_mst` (optional, if a dept filter is wanted as in Morrah).

## 8. Open questions (NEEDS OWNER DECISION)

- **STD_MR for SACKING WEFT = 16 or 20?** This tab's corrected values reconcile only with **16**, but the universal briefing says Sacking≈20. Confirm whether carding-stage sliver uses 16 while later stages use 20.
- **process × quality standards storage** (STD CV band `6-8%` + Reqd Wt): option (A) `machine_mst` columns vs (B) stage-namespaced `item_mst` columns. **NEEDS OWNER DECISION** — no new standalone standards table per decision #2.
- **CV% stored as fraction vs percent** — sheet stores 0.01944. Confirm display layer multiplies ×100, and whether pass/fail compares the fraction to band/100.
- **Machine code is a string** (`` `9A ``, leading back-tick). Is the back-tick meaningful (a sub-machine designator) or a data-entry artifact to strip? Confirm `mc_code` vs `mc_id` mapping to `machine_mst`.
- **Hopper section header says "STD WT" not "COR WT".** Confirm whether Hopper compares observed-vs-std-weight rather than computing a corrected weight, or if it's just a label copy/paste (no Hopper rows exist in the cache to verify).
- **Reqd Wt / DP / Draft** are blank in cache — confirm they are operator inputs vs Phase-2 production pulls (DP/Draft look like production links; defer per decision #4).
- **No spell/dept aggregation rule** — confirm the section AVG is an unweighted mean of row averages (as derived) and not weight-weighted.
