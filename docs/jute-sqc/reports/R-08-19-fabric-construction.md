# R-08-19 — Fabric Construction (I.S.O.)

**Stage:** weaving / finishing (woven hessian cloth — finished fabric construction audit)  **Status:** UNBUILT
**Source tab:** `R19` ("R-08-19 FABRIC CONSTRUCTION (I.S.O.)", master "Daily Summary Date Select")   **DSR workbook:** `1U9-oOYQ6bYJUcUR9awg82wb1XUniDr1SMiczkZNhOmk` (DSR!A9:N52, not shared)

## 1. Purpose
Audits the **construction of woven Hessian cloth** against its quality standard: physical dimensions (length, width), thread density (ends/dm, picks/dm), moisture (MR%) and **weight per yard (oz/yd)**. It confirms that the cloth actually woven matches the contracted construction spec, and corrects observed weight to standard MR before comparing to the standard oz/yd. The tab carries up to 4 sample blocks (5 rolls each) plus a final **Std vs Actual** comparison table.

## 2. Inputs (the data-entry fields)

The tab repeats a 5-row sample block (SL 1..5 + AVG) up to 4 times; each row is one cloth sample of a quality. The cached snapshot is **empty/zero** (all `#N/A`/`0` — no readings entered for 5/1/2026), so column *meaning* is taken from the headers and the universal correction formula (§4). Header columns observed: `QUALITY | LENGTH (YDS) | WIDTH (cms) | ENDS / dm | PICKS / dm | MR% | OBS. WT. (Kg.) | OBS OZS | CRCTED OZ | STD WT(KG)`.

| Field | Type | Source/Master | Required | Notes |
|-------|------|---------------|----------|-------|
| `entry_date` | date | — (header) | yes | Header. "LAST STUDY DONE ON 2023-07-21" is a reference date, not the entry date. |
| `sl` | int | auto (1..5 per block) | yes | Per-reading row index within a block. |
| `quality` | FK | **fabric-construction quality master** (see §3) | yes | Per-row. Drives all the Std.* values (length/width/ends/picks/MR/oz). Cached: `#N/A` (no quality picked). |
| `length_yds` | number | operator entry | yes | Measured fabric length (yds). |
| `width_cms` | number | operator entry | yes | Measured fabric width (cms). |
| `ends_per_dm` | number | operator entry (count) | yes | Warp ends per decimetre. |
| `picks_per_dm` | number | operator entry (count) | yes | Weft picks per decimetre. |
| `mr_pct` | number(5,2) | operator entry | yes | Fabric MR% (moisture regain). |
| `obs_wt_kg` | number | operator entry | yes | Observed sample weight (Kg). |

**Derived/printed (not entered):** `OBS OZS`, `CRCTED OZ`, `STD WT(KG)`, and all per-column averages — see §4.
**Header vs per-reading:** `entry_date` + `quality` are effectively header (one quality per block); `sl`, `length_yds`, `width_cms`, `ends_per_dm`, `picks_per_dm`, `mr_pct`, `obs_wt_kg` are per-reading (per sample row).

## 3. Standards & constants used

The final "FABRIC CONSTRUCTION CHECKING OF HESSIAN CLOTH" table is a **Std. vs Actual** grid across six dimensions: Fabric length (yds), Fabric Width (cms), Ends/dm, Picks/dm, Fabric MR%, Fabric Ozs./Yds. Every "Std." value is keyed by the **quality** — i.e. the construction spec for that hessian quality.

| Standard | Example in sheet | Where it should live in VOW (decision #2) |
|---|---|---|
| Std fabric **length (yds)** | `#N/A` (no quality picked in cache); the Hessian Qlty string in R-08-18 encodes it as `38.00"` width etc. | Per-quality columns on the **fabric-construction quality master** (the master backing the `QUALITY` dropdown). Add `std_length_yds`. |
| Std fabric **width (cms)** | `#N/A` | Add `std_width_cms` to the same quality master. |
| Std **ends/dm** | `#N/A` (e.g. "11" in the `(11x10)` construction code) | Add `std_ends_dm`. |
| Std **picks/dm** | `#N/A` (e.g. "10" in `(11x10)`) | Add `std_picks_dm`. |
| Std **MR%** | `#N/A` (Hessian ≈ 16, briefing §4) | Add `std_mr_pct` (same column family as yarn `jute_yarn_mst.std_mr_pct`). |
| Std **weight oz/yd** & **STD WT(KG)** | `#N/A` (e.g. `7.714` oz in `38.00"-(11x10)-7.714`) | Add `std_oz_per_yd` (and/or `std_wt_kg`). |

**⚠️ Process×quality standards-storage question (RAISED):** the six standards above are all **per-quality construction parameters** — they belong to the *fabric quality*, not to a machine or a single generic per-quality MR column. Decision #2 forbids a new standalone "standard parameter" table, yet a hessian quality needs **six** std columns (length/width/ends/picks/MR/oz). Proposed reconciliations:
1. **Extend the fabric-construction quality master** (the master that already encodes the `38.00"-(11x10)-7.714` strings — likely an `item_mst` finished-cloth row or a dedicated woven-quality master; confirm which) with the six `std_*` columns above. This is the natural home: one quality row = one construction spec. **PREFERRED.**
2. If those qualities live only as free-text in `item_mst.item_name`, add the six `std_*` columns to that `item_mst` finished-goods row (still "extend existing master").
Both are "extend existing master" compliant. **NEEDS OWNER DECISION:** which master holds the hessian construction qualities, and confirm the six std column names.

## 4. Calculations (formulas)

The cache is all zeros, so formulas are **derived** from the column names + the universal MR correction (briefing §4) and flagged.

- **OBS OZS** = observed sample weight converted from Kg to oz **per the sample's length**, i.e. oz per yard.
  - ⚠️ Confirm: `OBS OZS = (OBS_WT_KG × 1000 / 28.3495) / LENGTH_YDS` (g→oz then per yd). Cannot verify against cache (all 0); confirm whether OBS OZS is total oz of the sample or oz **per yard** (header on the comparison table says "Fabric Ozs./ Yds", implying per-yard).
- **CRCTED OZ** = OBS OZS corrected to standard MR for the quality (universal jute correction):
  - **CRCTED OZ = OBS_OZS × (100 + STD_MR_quality) / (100 + MR%)**  (briefing §4 form; for Hessian STD_MR≈16)
  - Worked (illustrative, OBS_OZS=7.9 @ MR=29, stdMR=16): 7.9 × 116/129 = **7.10** oz/yd. (No cached non-zero row to verify — ⚠️ Confirm.)
- **STD WT(KG)** = the quality's standard weight (the target), pulled from the quality master `std_wt_kg`/derived from `std_oz_per_yd × length`. Reference value, not computed from readings.
- **Per-column AVG** = arithmetic mean of the 5 sample rows for that column (length, width, ends, picks, MR, obs wt, obs oz, crcted oz). Standard mean; no stdev/CV on this tab.
- **Comparison (Std vs Actual)**: Actual = the block's AVG for each of the six dimensions; Std = the quality's stored standard. Pass = Actual within owner tolerance of Std (tolerance not printed — see §8).

**CV% variant:** none on this tab (no CV%/stdev columns). Correction constant: per-quality **STD_MR** (Hessian ≈ 16), applied to oz/weight via the universal multiplicative MR correction.

## 5. Worked example (real data)

The cached 5/1/2026 snapshot has **no entered readings** — every QUALITY is `#N/A` and every numeric cell is `0`/`#N/A` (the IMPORTRANGE pulled an empty DSR for that date). So no end-to-end numeric example exists in the cache. Illustrative (to be confirmed once a populated date is available):

- Inputs (one sample row): quality = a 38" hessian, length = 100 yds, width = 96.5 cms, ends/dm = 11, picks/dm = 10, MR% = 29, obs wt = 22.5 Kg.
- OBS OZS (per yd) ≈ (22.5 × 1000 / 28.3495) / 100 = **7.94 oz/yd** ⚠️
- CRCTED OZ = 7.94 × (100+16)/(100+29) = 7.94 × 116/129 = **7.14 oz/yd** ⚠️
- Compare to STD oz/yd (e.g. 7.714) → Actual 7.14 vs Std 7.714 → under-weight by ~0.57 oz/yd (flag).

**Action:** request one populated R-08-19 date so the OBS OZS and CRCTED OZ formulas can be locked against real numbers before build.

## 6. Proposed VOW data model

Header + detail. One header per (date, quality) sample block; 5 detail rows of readings. Mirrors `JuteSqcSpinningQrCv`/`...Dtl`. Insert-only + soft-delete.

```python
class JuteSqcFabricConstruction(Base):
    """R-08-19 Fabric Construction — header per (date, quality) sample block."""
    __tablename__ = "jute_sqc_fabric_construction"

    fabric_const_id   = Column(Integer, primary_key=True, autoincrement=True)
    co_id             = Column(Integer, nullable=False, index=True)
    branch_id         = Column(Integer, nullable=True)
    entry_date        = Column(Date, nullable=False, index=True)
    quality_id        = Column(Integer, nullable=True)        # FK -> fabric-construction quality master
    quality_text      = Column(String(120), nullable=True)    # snapshot e.g. 38.00"-(11x10)-7.714
    # snapshots of the quality standards at save time (so historic reports stay reproducible)
    std_length_yds    = Column(DECIMAL(10, 2), nullable=True)
    std_width_cms     = Column(DECIMAL(10, 2), nullable=True)
    std_ends_dm       = Column(DECIMAL(10, 2), nullable=True)
    std_picks_dm      = Column(DECIMAL(10, 2), nullable=True)
    std_mr_pct        = Column(DECIMAL(6, 2), nullable=True)
    std_oz_per_yd     = Column(DECIMAL(10, 3), nullable=True)
    active            = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by        = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteSqcFabricConstructionDtl(Base):
    """One sample row (SL 1..5) of a fabric-construction block."""
    __tablename__ = "jute_sqc_fabric_construction_dtl"

    fabric_const_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    fabric_const_id     = Column(Integer, nullable=False, index=True)
    sl                  = Column(Integer, nullable=False)         # 1..5
    length_yds          = Column(DECIMAL(10, 2), nullable=True)
    width_cms           = Column(DECIMAL(10, 2), nullable=True)
    ends_per_dm         = Column(DECIMAL(10, 2), nullable=True)
    picks_per_dm        = Column(DECIMAL(10, 2), nullable=True)
    mr_pct              = Column(DECIMAL(6, 2), nullable=True)
    obs_wt_kg           = Column(DECIMAL(10, 3), nullable=True)
    obs_ozs             = Column(DECIMAL(10, 3), nullable=True)   # computed, cached
    crcted_oz           = Column(DECIMAL(10, 3), nullable=True)   # computed, cached
```

- **PK:** `fabric_const_id` / `fabric_const_dtl_id`. Scoping: `co_id`, `branch_id`, `entry_date`, `active`, `updated_by` on the header. Per-column AVG and the Std-vs-Actual comparison are computed at read.

## 7. Proposed endpoints & pages

Backend (prefix `/api/juteSQC`, `src/juteSQC/fabricConstruction.py` + `query.py`):
- `GET /fabric_construction_create_setup` — quality dropdown (fabric-construction master) **with its six std values**, so the form can prefill the Std column.
- `POST /create_fabric_construction` — validates rows, snapshots std_* from the quality, computes `obs_ozs`/`crcted_oz` per row, inserts header+detail.
- `GET /get_fabric_construction_by_date` — blocks for a date with per-column AVG + Std-vs-Actual comparison computed server-side.
- `GET /get_fabric_construction_table` — paginated list.
- `POST /delete_fabric_construction` — soft delete.

Frontend (`src/app/dashboardportal/juteSQC/r-08-19/`):
- **Entry form** (mobile): pick quality (auto-loads its six standards as the read-only "Std." column) → enter 5 sample rows → live AVG + live CRCTED OZ. Honors `co_id`/`branch_id`.
- **Summary view** (date-driven): per-block 5-row table + AVG, then the **Std vs Actual** comparison grid (length/width/ends/picks/MR/oz). Route consts `FABRIC_CONSTRUCTION_*` in `api.ts`; `fetchWithCookie`.

**Masters to link:** the **fabric-construction quality master** (quality dropdown + six std columns). No spell/machine columns appear on this tab (sample-based, not machine-based).

## 8. Open questions (NEEDS OWNER DECISION)

- **Which master holds the fabric-construction qualities** (the `38.00"-(11x10)-7.714` strings)? `item_mst` finished-cloth rows, or a dedicated woven-quality master? This decides where the six `std_*` columns are added.
- **Confirm the six std column names/values** and whether the construction code string should be *parsed* into width/ends/picks/oz or stored as discrete master columns (preferred: discrete columns).
- **OBS OZS definition:** total oz of sample vs **oz per yard** (header says "Ozs./Yds"). And the exact Kg→oz factor (28.3495 g/oz assumed). Cannot verify — cache is empty.
- **CRCTED OZ formula:** confirm it's the universal MR correction `OBS_OZS × (100+STD_MR)/(100+MR%)` and which MR (fabric MR per row) is the divisor. Need one **populated** date to lock it.
- **Std MR per quality** (Hessian ≈ 16) — confirm value(s); does sacking fabric also use this report (tab title says Hessian only)?
- **Pass/fail tolerances** for the Std-vs-Actual comparison (e.g. ±x% on each dimension) — not printed on the tab.
- **Number of sample blocks** (cache shows 4 empty blocks, 5 rows each) — is it always 4 qualities × 5 samples, or variable?
- **"LAST STUDY DONE ON"** (2023-07-21) — is this a per-quality field to carry forward (last audit date), and should VOW track it?
