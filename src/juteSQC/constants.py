"""Constants for the Jute SQC module."""

# Breaker-card machine type lookup — resolved against machine_type_mst.machine_type_name
# at runtime (seeded idempotently by seed_breaker_card_machine_type.sql). Mirrors the
# spreader precedent: filter machine_mst via the type NAME, no dedicated id.
BREAKER_CARD_MACHINE_TYPE_NAME = "Breaker Card"

# process key for the (item_id, process)-keyed jute_draw_quality_std satellite. The
# carding/drawing family shares the satellite; the SAME line quality carries a different
# band/MR per process, so the std lookup is scoped by this token.
BREAKER_PROCESS = "BREAKER"

# R-08-07A Inter Card & Tow Breaker Sliver Weight — the three carding sub-sections. Each
# value is BOTH the row's stored `section` label AND the (item_id, process) key into
# jute_draw_quality_std (the SAME line quality carries a different band/MR per sub-process).
# No machine type is seeded: the picker is the shared carding pool, the operator picks the
# section. std MR falls back to 20 when no satellite row exists (owner decision).
CARD_SECTION_INTER_CARD = "INTER_CARD"
CARD_SECTION_TOW_BREAKER = "TOW_BREAKER"
CARD_SECTION_HOPPER = "HOPPER"
CARD_SLIVER_SECTIONS = (
    CARD_SECTION_INTER_CARD,
    CARD_SECTION_TOW_BREAKER,
    CARD_SECTION_HOPPER,
)

# R-08-12/13/14 Finisher Drawing — the three sliver sections (HESS / SWP / SWT). Same
# batch-linked 4-cut sliver-weight shape as card_sliver; each reading also carries a
# delivery (DLV) number per cut. std MR falls back to 16 (drawing default).
FIN_DRAW_SECTIONS = ("HESS", "SWP", "SWT")

# R-08-08/09/10 Drawhead + Finisher Card — three sections plus an AM/PM time-band header.
# Same batch-linked 4-cut shape; time_band labels the morning/afternoon sheet column.
DRAW_SECTIONS = ("DRAWHEAD_SWT", "DRAWHEAD_SWP", "FINISHER_CARD")
DRAW_TIME_BANDS = ("MORNING", "AFTERNOON")

# R-08-18 Beam MR% — warp-beam moisture-regain QC. One reading-set per (date, quality
# group, beam machine) carries EXACTLY 5 MR% readings; avg_mr = mean of the 5. Two quality
# groups (JUTE CLOTH items, item_type_id=5) each carry a default std MR (editable on the form,
# snapshotted at save). deviation = avg_mr - std_mr_pct. No CV%, no pass/fail band.
BEAM_MR_READINGS_PER_SET = 5
BEAM_MR_QUALITY_GROUPS = ("HESSIAN", "SACKING")
BEAM_MR_STD_MR_BY_GROUP = {"HESSIAN": 16.0, "SACKING": 20.0}

# R-08-19 Fabric Construction — woven hessian cloth construction audit. One save = one quality
# block (header + up to 5 sample rows). std_mr_pct prefills 16 for hessian (editable, snapshotted).
# Per-row obs_ozs = (obs_wt_kg * 1000 / KG_TO_OZ) / length_yds; crcted_oz universal-MR-corrected.
FABRIC_CONSTRUCTION_SAMPLE_ROWS = 5
FABRIC_CONSTRUCTION_DEFAULT_STD_MR = 16.0
KG_TO_OZ = 28.3495

# R-08-20 Cutting Length — daily cut-piece length consistency. One save = one date's
# reading-set: EXACTLY 20 cut-length readings (inches). avg = mean(20); stdev = SAMPLE
# stdev (n-1, statistics.stdev); cv_pct = stdev/avg*100; deviation = avg - std_length.
# std_length entered on the form (prefilled 78, editable, snapshotted at save). No MR
# correction, no pass/fail band.
CUTTING_LENGTH_READINGS = 20
CUTTING_LENGTH_DEFAULT_STD = 78.0

# R-08-22 Stitch — finishing-stage sewing-stitch-density QC. One save = one
# (date, sewing machine) reading-set: EXACTLY 5 stitch counts (stitches/dm). avg =
# mean(5); flag = 'OK' when avg == std_stitch (EXACT, epsilon-tolerant), else 'LOW' if
# avg < std_stitch else 'HIGH' (so 9.4 vs 9 is HIGH, not OK). std_stitch is a fixed
# mill standard (9 stitches/dm) prefilled
# on the form, editable, snapshotted at save. No CV%, no MR correction, no quality column.
# Machine dropdown = SEWING machines resolved by machine_type_mst.machine_type_name
# = STITCH_MACHINE_TYPE_NAME ('HEMMING' in dev3 — the bag-sewing operation).
STITCH_READINGS = 5
STITCH_DEFAULT_STD = 9.0
STITCH_MACHINE_TYPE_NAME = "HEMMING"

# R-08-21 Width and Picks — on-loom dimensional QC of woven cloth. One save = one
# (date, cloth-quality) group: header (std_width_cm, std_picks snapshotted) + N loom
# reading rows (width_cm required, picks_dm optional). WIDTH remark = '$' when avg_width
# falls outside std_width_cm +/- 0.5% (two-sided). PICKS summary over non-null picks_dm:
# avg / SAMPLE stdev (n-1, statistics.stdev, needs >=2 values) / max / min / count. No CV%.
WIDTH_TOL_PCT = 0.005

# R-08-23 Bag Weight — finished-bag weight control. One save = one (date, bag type) block:
# header (std_bag_weight, std_mr_pct snapshotted) + N reading rows {mr, obs} (>=1, no upper
# cap). Per-row corr = obs * (100 + std_mr_pct) / (100 + mr). Block stats (avg_mr,
# avg_obs, row-wise avg_corr, SAMPLE stdev of obs (n-1), cv_pct, observed & corrected
# heavy/light percents vs std_bag_weight) computed server-side at save. std_mr_pct prefills
# 20 for jute bags (editable, snapshotted). Bag type = JUTE CLOTH item (item_type_id=5).
BAG_WEIGHT_DEFAULT_STD_MR = 20.0

# R-08-24 Bag Checking — finished-bag acceptance inspection. One save = one (date, bag type)
# block: header (7 std snapshots: bag_weight/length/width/ends/picks/stitch/mr) + N per-bag rows
# (variable >=1). Per-bag corr_wt = bag_wt * (100 + std_mr_pct) / (100 + mr_pct). Block aggregates
# (avg/SAMPLE stdev/cv%/min/max per numeric column + obs & corr heavy-light percents vs
# std_bag_weight) computed server-side on read. std_mr_pct prefills 20 (editable, snapshotted).
# Bag type = JUTE CLOTH item (item_type_id=5).
BAG_CHECK_DEFAULT_STD_MR = 20.0

# R-08-25 Packing MR% — finished-goods moisture at packing. One save = one (date, quality
# column) reading-set: EXACTLY 10 MR% readings stored as a JSON-string array. avg_mr =
# mean(10). No std, no CV%, no MR correction, no pass/fail (averages only). quality_group
# (HESSIAN / SACKING) drives the by_date roll-up: group_avg_mr = WEIGHTED mean of ALL readings
# across that group's columns (sum(all readings) / count(all readings)). Optional cloth-quality
# link = JUTE CLOTH item (item_type_id=5, beaming picker); construction_code is free text.
PACKING_MR_READINGS = 10
PACKING_MR_QUALITY_GROUPS = ("HESSIAN", "SACKING")

# R-08-28 Fabric Fault — weaving woven-cloth defect tally. One save = one inspected piece
# (one loom/cloth column): header + a FIXED 15-fault checklist of integer counts stored as
# a JSON-string array of 15 ints, in this FIXED order (index 0..14). piece_total = sum of
# the 15. Day roll-up (server-side over all pieces for the date): fault_total[i] = sum over
# pieces; fault_score[i] = fault_total[i] / N (N = pieces inspected); grand_total = sum of
# all fault_totals; grand_score = grand_total / N. No std, no CV%, no correction. The fault
# list is a CONSTANT (no master).
FABRIC_FAULT_TYPES = [
    "Single Broken Warp",
    "Minor Gaw",
    "Major Gaw",
    "Minor Multiple Broken Warp",
    "Major Multiple Broken Warp",
    "Minor Float",
    "Major Float",
    "Mildew Stain",
    "Hole/Snarl",
    "Weft Bar Minor",
    "Curled Selvage",
    "Weft Bar Major",
    "Cut Selvage",
    "Loopy Selvage",
    "Smash",
]
FABRIC_FAULT_COUNT = 15

# R-08-02 Emulsion — daily batching jute-oil emulsion recipe log. ONE flat row per date
# (no readings array, no StDev/CV). std_oil_pct_low/high is the target band prefilled on the
# form (16-17), editable, snapshotted at save. tank_capacity prefills 1000. Machine picker =
# SPREADER machines (SPREADER_MACHINE_TYPE_NAME, imported from juteProduction in the router).
EMULSION_DEFAULT_OIL_PCT_LOW = 16.0
EMULSION_DEFAULT_OIL_PCT_HIGH = 17.0
EMULSION_DEFAULT_TANK_CAPACITY = 1000.0

# Humidity Recording — plant-wide department temperature/RH log. One save = one
# (report_date, dept, round) reading-set: header + 1..3 SPOT readings stored as a JSON
# array of {spot_label, reading_time, temp_c, rh_pct}. round_no 1=Morning, 2=Noon,
# 3=Evening. avg_temp = mean(temp_c over spots), avg_rh = mean(rh_pct over spots), 2dp.
# No StDev/CV, no band. Department dropdown = dept_mst by branch.
HUMIDITY_SPOTS_PER_ROUND = 3
HUMIDITY_ROUNDS = [
    {"round_no": 1, "label": "Morning"},
    {"round_no": 2, "label": "Noon"},
    {"round_no": 3, "label": "Evening"},
]
