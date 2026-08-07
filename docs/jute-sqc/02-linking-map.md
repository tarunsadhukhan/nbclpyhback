# 02 — Linking Map (what links to what)

Decision #4 = **link the lists to existing masters now; defer production-transaction pulls to Phase 2.**
This is the map of every report's selectable fields → the existing VOW master, plus the deferred links.

## Master sources (verified in built code)

| Concept | Master | Key columns | Used by built code |
|---------|--------|-------------|--------------------|
| Department | `dept_mst` | `dept_id, dept_desc, dept_code` (by `branch_id`) | Morrah setup |
| Machine / frame / loom / spreader / card / drawing head | `machine_mst` | `machine_id, mech_code, machine_name` | Spinning SQC (`mc_id`) |
| Spell / shift (A1/A2/B…) | `spell_mst` | `spell_id, spell_code, spell_name` (`status=1`) | Spinning count/RHMR |
| Raw jute quality (D/4, A/5, 8Lbs) | `item_mst` via `item_grp_mst` parent `item_type_id=2` | `item_id, item_name, item_code` | Morrah qualities |
| Yarn item / yarn quality (HSWP, SKWT, …) | `item_mst` (yarn) + `jute_yarn_mst` | `item_id`, `jute_yarn_mst.std_mr_pct` | Spinning count/QR-CV |
| Line/blend quality (HESSIAN, SACKING WARP/WEFT, 10Lbs) | `jute_quality_mst` *(confirm)* or item-based | — | ⚠️ confirm which master |
| Fabric/cloth quality (e.g. `38.00"-(11x10)-7.714`) | cloth/fabric quality master *(confirm exists)* | — | ⚠️ confirm |
| Inspector / "report prepared by" | `user_mst` (portal users) or free text | — | Morrah uses free `inspector_name` |

## Per-report link map

| Report | Header selectors → master | Std value → master (extend) | Phase-2 production link (deferred) |
|--------|---------------------------|-----------------------------|-----------------------------------|
| R-08-02 Emulsion | date; (oils/chemicals are quantities, not pickers) | recipe item names could become an emulsion-ingredient list | "rolls made" ← spreader production; oil% target |
| R-08-03 Spreader roll sliver wt | spreader `machine_mst`; spell `spell_mst`; quality | `std_mr_pct`, std sliver wt, CV band | spreader production rolls |
| R-08-04 Spreader roll wt | spreader `machine_mst`; spell; quality; feeder (`user_mst`?) | std weight bands, `std_mr_pct` | spreader production |
| R-08-05/06/07 Breaker card | breaker-card `machine_mst`; spell; quality | `std_mr_pct`, std wt, CV band | carding production |
| R-08-07A Inter card/tow breaker | inter-card `machine_mst`; spell; quality | `std_mr_pct`, std wt, CV band | carding production |
| R-08-08/09/10 Drawhead+finisher card | drawing `machine_mst`; spell; quality | `std_mr_pct`, std wt, CV band, DP/draft | drawing production |
| R-08-12/13/14 Finisher drawing | finisher-drawing `machine_mst`; spell; quality (Hess/SKWP/SWT) | std wt + range + CV band per quality | drawing production |
| R-08-17 Yarn TPI | spinning frame `machine_mst`; quality (yarn `item_mst`) | `std_tpi`, TP | spinning production |
| R-08-18 Beam MR% | beaming `machine_mst` (HS/S looms); spell; quality | `std_mr_pct` | beaming/winding production |
| R-08-19 Fabric construction | cloth quality master; (loom?) | std width/picks/ends/length/ozs/MR | weaving production |
| R-08-20 Cutting length | cloth quality; loom `machine_mst` | std cutting length | weaving production |
| R-08-21 Width & picks | cloth quality; loom `machine_mst` | std width, std picks | weaving production |
| R-08-22 Stitch | cloth quality; (machine) | std stitch params | weaving/finishing |
| R-08-23 Bag weight | bag/cloth quality | std bag weight, `std_mr_pct` | sewing/finishing production |
| R-08-24 Bag checking | bag/cloth quality; (defect list) | defect-type list (could be an enum/master) | finishing |
| R-08-25 Packing MR% | bale/quality | `std_mr_pct` | packing/bale production |
| R-08-28 Fabric fault | loom `machine_mst`; cloth quality; date-of-weaving | fault-type list + score weights | weaving production |
| Humidity | department `dept_mst`; time | std humidity/temp range (optional) | — |

## Notes on the deferred (Phase-2) links

These are where SQC inputs "finally go" in the live plant — the owner wants them linked eventually,
but **not in this phase** (decision #4):

- **R-08-16 count → spinning planning** is already wired in the built code (`JuteSqcSpinningCount`
  feeds the spinning grid). It is the model for how a later phase links SQC → production.
- **R-08-02 emulsion ↔ spreader production** ("rolls made" comes from the spreader run).
- **Morrah / spreader / card / drawing / spinning / weaving** each have a matching production module
  in `src/juteProduction/` (spreader, drawing, spinning, beaming, weaving, winding) — Phase 2 can
  default the machine/quality/shift on an SQC entry from that day's production run, and push QC
  results back as production attributes.

When Phase 2 starts, follow the existing `JuteSqcSpinningCount → spinning` precedent rather than
inventing a new linking mechanism.
