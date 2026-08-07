"""Constants for the Jute Production (spreader) module."""

# Spreader machine type lookup — resolved against machine_type_mst.machine_type_name at runtime.
SPREADER_MACHINE_TYPE_NAME = "Spreader"

# Drawing machine type lookup — resolved against machine_type_mst.machine_type_name at runtime.
DRAWING_MACHINE_TYPE_NAME = "Drawing"

# Drawing efficiency base: const_meter is defined as meters per 8-hour shift at 100% eff.
EFF_BASE_HOURS = 8

# Default odometer wrap for drawing meter counters (legacy +10000 rollover).
DEFAULT_METER_WRAP = 10000

# item_grp_mst.item_type_id values that classify an item as jute or jute-waste
# (i.e. eligible to be produced on a spreader).
JUTE_ITEM_TYPE_IDS = (2, 3)

# Spell / shift codes (must match values stored in spell_mst).
SPELLS = ("A1", "A2", "B1", "B2", "C")
SHIFT_BUCKETS = ("A1", "A2", "B1", "B2", "C")
A_SHIFT = ("A1", "A2")
B_SHIFT = ("B1", "B2")

# 4-hour reuse window for entry_id_grp within a bin.
GROUP_WINDOW_HOURS = 4

# Default maturity (hrs) when no item_maturity_mst row exists for an item.
DEFAULT_MATURITY_HOURS = 48

# --- Spinning / Doff production ---------------------------------------------

# Spinning machine type lookup — resolved against machine_type_mst.machine_type_name
# at runtime (legacy type_of_mechine=36).
SPINNING_MACHINE_TYPE_NAME = "Spinning"

# Default working hours per shift used in the spinning daily roll-up.
SPIN_HRS_A, SPIN_HRS_B, SPIN_HRS_C = 8.0, 8.0, 7.5

# quality_type stamped on jute_prod_spinning_act_count rows.
SPIN_QUALITY_TYPE = 2

# Valid net-weight band (kg) for a single doff entry.
DOFF_NET_MIN, DOFF_NET_MAX = 5.0, 60.0

# Shift buckets for production roll-up: A=A1/A2, B=B1/B2, C=C
# (reuse A_SHIFT / B_SHIFT already defined above).
C_SHIFT = ("C",)

# --- Spinning planning refactor (time-versioned standards/targets) ----------

# 100% production formula constants (per-frame, per-spell):
#   p100prod = (std_speed * minutes * act_count * spindles)
#              / (SPNG_PROD_C1 * SPNG_PROD_C2 * SPNG_PROD_C3 * std_tpi)
# C3 kept at 2.2046 (matches existing p100_x; doc says 2.204 — negligible).
SPNG_PROD_C1 = 36
SPNG_PROD_C2 = 14400
SPNG_PROD_C3 = 2.2046

# Fallback shift minutes when spell_mst.working_hours is unavailable.
SPELL_MINUTES = {"A1": 300, "A2": 180}

# jute_prod_spng_target_map.id_type discriminator values.
ID_TYPE_MC = "mcid"
ID_TYPE_QLTY = "qid"

# jute_prod_spng_target_map.value_role discriminator values.
VALUE_ROLE_STANDARD = "standard"
VALUE_ROLE_TARGET = "target"
VALUE_ROLE_ACTUAL = "actual"

# jute_prod_spng_target_map.param discriminator values.
# Quality (qid) params: tpi, eff. Machine (mcid) params: speed, spindles, dc, tc, bobbin_wt.
PARAM_SPEED = "speed"
PARAM_TPI = "tpi"
PARAM_EFF = "eff"
PARAM_SPINDLES = "spindles"
PARAM_DC = "dc"
PARAM_TC = "tc"
PARAM_BOBBIN_WT = "bobbin_wt"

# --- Winding production -----------------------------------------------------

# Winding machine type lookup — resolved against machine_type_mst.machine_type_name
# at runtime (legacy type_of_mechine=39, dept_id=53).
WINDING_MACHINE_TYPE_NAME = "Winding"

# Valid per-machine net-weight band (kg) for a winding doff entry.
# Legacy view gate: 1 <= mc1netwt <= 500 (winding_doff_data.php).
WINDING_NET_MIN, WINDING_NET_MAX = 1, 500

# Jugar (spindle leftover) weight band (kg): 0 < weight <= 100.
# Legacy validation: 0 < jugarwt <= 100 (winding_jugar_entry.php).
JUGAR_MIN, JUGAR_MAX = 0, 100

# Spindle-count band per machine/spell on the winding quality entry.
# Legacy view gate is 1..30 (alert text says "1 to 16" — design resolves to 1..30).
SPINDLE_MIN, SPINDLE_MAX = 1, 30

# kg -> bundle divisor (14 kg/bundle). Kept as a constant only; reconciled
# production stays in KG (no per-quality UOM applied) per the locked design.
BUNDLE_KG = 14

# --- Beaming ----------------------------------------------------------------

# Beaming machine type — resolved against machine_type_mst.machine_type_name.
# APPLIED in dev3: machine_type_id 12 (§0.1).
BEAMING_MACHINE_TYPE_NAME = "Beaming"

# Jute-cloth item type for the Beaming item dropdown.
# APPLIED in dev3: item_type_master 'Jute Cloth' = 5 (§0.1); groups 625/626/640/642/1266/1716.
BEAMING_ITEM_TYPE_IDS = (5,)

# kg/cut formula constants (own values to avoid the 2.2046 vs 2.20462 drift).
# NB: "spyndle" here is the jute COUNT unit (14400 yd per spyndle, per the screenshot's
# "spnydle (constant) 14400") — NOT machine spindles. Beaming's grain is machine+quality (no spindles).
BEAMING_SPYNDLE_YDS = 14400       # jute spyndle = 14400 yards (count-system constant)
BEAMING_KG_TO_LB    = 2.20462     # kg -> lb (count-system conversion)

# Target-map discriminators. Beaming is now TWO-DIMENSIONAL (mcid + qid), mirroring
# spinning: machine-linked physical params live under id_type='mcid' (ref_id=machine_id),
# while quality-linked production params live under id_type='qid'
# (ref_id=jute_prod_bm_quality.bm_quality_id). This re-adds the 'qid' dimension the
# beaming target-map was originally stripped of.
BEAMING_ID_TYPE_MC      = "mcid"
BEAMING_ID_TYPE_QLTY    = "qid"
BEAMING_VALUE_ROLES     = ("standard", "target", "actual")

# --- MACHINE-linked (mcid, ref_id = machine_id) -----------------------------
# NB: the 'speed' param is RPM (rotations/min), NOT surface speed. Beaming surface
# speed (yd/min) = rpm × dia × π / 36 — use beaming_rules.act_speed(rpm, dia) for the
# std/target/act surface speeds. p100prod capacity uses the STD SURFACE speed.
# 'dia' = starch-roller diameter (machine-linked standard, fixed).
BEAMING_MC_PARAMS_STD      = ("speed", "dia")
BEAMING_MC_PARAMS_TARGET   = ("speed",)
# 'speed' = actual RPM captured on the Beaming SQC page; value_role=actual (mcid).
BEAMING_PARAMS_ACTUAL      = ("speed",)

# --- QUALITY-linked (qid, ref_id = bm_quality_id) ---------------------------
# laid_length / cuts_per_beam / eff are properties of the beaming QUALITY (the warp
# being beamed), NOT the machine, so they key off the Beaming Quality Master.
BEAMING_QID_PARAMS_STD     = ("laid_length", "cuts_per_beam", "eff")
BEAMING_QID_PARAMS_TARGET  = ("eff",)

# --- Weaving ----------------------------------------------------------------

# Loom machine type — resolved against machine_type_mst.machine_type_name at runtime
# (case-insensitive under MySQL's default collation, so 'Loom' = 'LOOM').
# dev3 REALITY (verified 2026-06-23): machine_type 'LOOM' = machine_type_id 6 (4 looms);
# SPEC Q1 said id 7 (from the code3i type_of_mechine=7 source DB) — that id does NOT
# exist in dev3. Resolution is by NAME, so the id is informational only.
WEAVING_MACHINE_TYPE_NAME = "Loom"
WEAVING_MACHINE_TYPE_ID = 6  # dev3 'LOOM' (SPEC said 7 from code3i; dev3 reality is 6)

# Woven jute-cloth item type for the Weaving quality item dropdown (reuse beaming's, Q2).
WEAVING_ITEM_TYPE_IDS = (5,)  # 'Jute Cloth'

# oz -> kg constant (Q13 RESOLVED): production_kg = production_yds * ozs_yds * 28.35 / 1000
# (28.35 g/oz; effective divisor 35.273). Confirmed by both authoritative loom calculators
# + code3i. Do NOT use the old 35.2 placeholder or the 4408/125=35.264 target variant.
WEAVING_GRAMS_PER_OZ = 28.35
WEAVING_OZ_TO_KG = 35.273  # = 1000 / 28.35 (reference/inverse only)
WEAVING_OZ_PER_LB = 16  # cut-weight (lbs) reference: finished_length * ozs_yds / 16
WEAVING_YARD_FACTOR = 36  # picks -> standard-yards conversion (std_prod_yds denominator)

# Target-map discriminators. Weaving is now TWO-DIMENSIONAL (mcid + qid), mirroring
# beaming/spinning: machine-linked physical params (speed) live under id_type='mcid'
# (ref_id = machine_id, a LOOM), while quality-linked production params (picks/eff)
# live under id_type='qid' (ref_id = jute_prod_weaving_quality.weaving_quality_id).
WEAVING_ID_TYPE_MC   = "mcid"
WEAVING_ID_TYPE_QLTY = "qid"
WEAVING_VALUE_ROLES = ("standard", "target", "actual")

# --- MACHINE-linked (mcid, ref_id = machine_id, a LOOM) ---------------------
# Loom refs come from get_weaving_entry_machines_query() bound :loom_type =
# WEAVING_MACHINE_TYPE_NAME. 'speed' is the loom speed; the actual loom speed is
# captured on the Weaving SQC "Actual Speed" tab (value_role=actual, mcid).
WEAVING_MC_PARAMS_STD    = ("speed",)
WEAVING_MC_PARAMS_TARGET = ("speed",)
WEAVING_MC_PARAMS_ACTUAL = ("speed",)

# --- QUALITY-linked (qid, ref_id = weaving_quality_id) ----------------------
# picks / eff are properties of the weaving QUALITY (the cloth being woven), NOT the
# loom, so they key off the Weaving Quality Master. There is NO qid actual param:
# actual picks are owned by vw_weaving_pick_act (Weaving Pick-SQC page) and actual
# speed is the mcid dimension above.
WEAVING_QID_PARAMS_STD    = ("picks", "eff")
WEAVING_QID_PARAMS_TARGET = ("eff",)

# Weaving spells in carry-forward order A1 -> B1 -> A2 -> B2 -> C (then day boundary).
# (SPELLS tuple above is ('A1','A2','B1','B2','C'); this is the jugar roll-forward order.)
WEAVING_SPELL_ORDER = ("A1", "B1", "A2", "B2", "C")

# --- Stoppage Hours ---------------------------------------------------------

# Fixed stoppage reasons (NOT a master table). reason_code stored on the row.
STOPPAGE_REASONS = ("mechanical", "electrical", "labor", "other")

# Optional display labels for the FE dropdown.
STOPPAGE_REASON_LABELS = {
    "mechanical": "Mechanical",
    "electrical": "Electrical",
    "labor": "Labor",
    "other": "Other",
}

# --- Finishing --------------------------------------------------------------
#
# The Finishing department is the post-weaving line that turns grey cloth into
# hessian cloth (rolls) and jute bags (bales) across NINE sub-processes. It reuses
# the Beaming/Spinning target-map EAV contract (id_type 'mcid'|'qid', value_role
# 'standard'|'target'|'actual') and adds ONE new dimension: `process`.
#
# Machine LINKING is intentionally unused: the per-process machine types exist for
# the future only, so id_type 'mcid' carries NO params for any process. SQC is
# dropped for now, so value_role 'actual' is EMPTY for every process — only a small
# set of qid 'standard'/'target' params remain (see FINISHING_PARAMS).

# Process tokens (= jute_prod_finishing_*.process column values). LOCKED CONTRACT —
# the FE and the spec sheet both key off these EXACT tokens.
FINISHING_PROCESSES = ("damping", "calendering", "lapping", "rolling", "cutting", "hemming", "herackle", "sacksewing", "balepress")

# id_type discriminators: 'mcid' (ref_id = machine_id) | 'qid' (ref_id = finishing_quality_id).
FINISHING_ID_TYPE_MC = "mcid"
FINISHING_ID_TYPE_QLTY = "qid"

# value_role discriminators. 'actual' is captured on the Finishing SQC page.
FINISHING_VALUE_ROLES = ("standard", "target", "actual")

# finishing_quality.quality_type values.
FINISHING_QUALITY_TYPE_CLOTH = 1   # Hessian qualities (Damping/Calendering/Lapping/Rolling)
FINISHING_QUALITY_TYPE_BAG = 2     # Sacking qualities (Cutting/Hemming/Herackle/Sack Sewing)

# Item-picker filter for the Finishing Quality Master: only 'Jute Cloth' items
# (item_grp_mst.item_type_id = 5), matching Beaming/Weaving (BEAMING/WEAVING_ITEM_TYPE_IDS).
FINISHING_ITEM_TYPE_ID = 5

# Quality applicability per process — filters qid (finishing_quality) refs by quality_type.
# Hessian-only processes (quality_type 1): damping/calendering/lapping/rolling.
# Sacking-only processes (quality_type 2): cutting/hemming/herackle/sacksewing.
# balepress is in NEITHER tuple, so quality_type_for_process('balepress') -> None -> BOTH
# qualities apply (no filter) via the existing code path.
FINISHING_CLOTH_PROCESSES = ("damping", "calendering", "lapping", "rolling")
FINISHING_BAG_PROCESSES = ("cutting", "hemming", "herackle", "sacksewing")

# Per-process applicable params — the single source of truth for grid_params_for()
# (SPEC §5.1). The grid renders exactly the params returned for a (process, id_type,
# value_role) combination; adding/removing a param is a one-line change here.
# Machine ('mcid') is unused -> NO mcid key for any process. SQC is dropped -> every
# 'actual' role is EMPTY. Each process's qid params are available under BOTH 'standard'
# and 'target' (the user sets a standard value and, optionally, a target value per param).
FINISHING_PARAMS = {
    "damping": {},
    "calendering": {},
    "lapping": {
        "qid": {"standard": ("std_prod_yds",), "target": ("std_prod_yds",), "actual": ()},
    },
    "rolling": {},
    "cutting": {
        "qid": {"standard": ("target_pcs",), "target": ("target_pcs",), "actual": ()},
    },
    "hemming": {
        "qid": {"standard": ("target_pcs",), "target": ("target_pcs",), "actual": ()},
    },
    "herackle": {
        "qid": {"standard": ("target_pcs",), "target": ("target_pcs",), "actual": ()},
    },
    "sacksewing": {
        "qid": {"standard": ("pcs_per_bundle", "bundles"), "target": ("pcs_per_bundle", "bundles"), "actual": ()},
    },
    "balepress": {
        "qid": {"standard": ("no_of_bales",), "target": ("no_of_bales",), "actual": ()},
    },
}

# Per-process machine-type name — resolved against machine_type_mst.machine_type_name
# at runtime (created by create_finishing_machine_types.sql), exactly like Beaming.
# Present for the future only; machine LINKING is intentionally unused (no mcid params).
FINISHING_MACHINE_TYPE_NAMES = {
    "damping": "Damping",
    "calendering": "Calendering",
    "lapping": "Lapping",
    "rolling": "Rolling",
    "cutting": "Cutting",
    "hemming": "Hemming",
    "herackle": "Herackle",
    "sacksewing": "Sack Sewing",
    "balepress": "Bale Press",
}

# Cloth production weight (F1) constant: total_yards × oz_per_yd / 35.2, where
# 35.2 = 16 oz/lb × 2.2046 lb/kg (carried verbatim from legacy Weaving/Beaming).
FINISHING_OZ_PER_KG = 35.2            # 16 × 2.2046
FINISHING_M_TO_YD = 1.09361           # metres -> yards (F1)
FINISHING_M_TO_IN = 39.3701           # metres -> inches (F5 cutting yield)
