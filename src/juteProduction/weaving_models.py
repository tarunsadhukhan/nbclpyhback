"""SQLAlchemy ORM models for the Jute Production — Weaving sub-module.

Six tables clone the beaming conventions (Column style, shared Base from
src/models/mst.py so they participate in existing metadata):

  jute_prod_weaving_quality      -- Weaving Quality Master: item -> weaving_quality (construction attrs)
  jute_prod_weaving_quality_dtl  -- composite-warp components (mirror jute_prod_bm_quality_dtl, Q6)
  jute_prod_weaving_target_map   -- effective-dated QUALITY-ONLY standards/targets/actuals (qid)
  jute_prod_weaving_quality_map  -- spinning-style Loom -> Quality assignment per (date, spell, loom) (§6.6)
  jute_prod_weaving_beam_map     -- beam -> loom assignment on beam change (§6.7)
  jute_prod_weaving_daily        -- daily per loom+quality+spell production snapshot

Conventions: co_id + branch_id scoping, soft delete (active TINYINT default 1),
audit cols updated_by + updated_date_time (NOT created_*, audit via DB triggers);
Portal persona; no approval workflow. Column names/types/nullability match the
create_weaving_tables.sql DDL exactly.

Weaving is the stage AFTER beaming: warp beams are mounted on looms and weft is
interlaced to weave jute cloth, measured per CUT (fixed finished length) and per
JUGAR (partial cut carried across spells A1->B1->A2->B2->C and the day boundary).
Standards are quality-only (qid) — there are NO loom (mcid) standards (Q5). The kg
constant is `ozs_yds * 28.35 / 1000` (Q13). Loom machine type resolves by NAME
'Loom' (dev3: machine_type_id 6 'LOOM', case-insensitive match).
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DECIMAL,
    TIMESTAMP,
    UniqueConstraint,
    func,
)

from src.models.mst import Base


class JuteProdWeavingQuality(Base):
    """Weaving Quality Master — maps one weaving_quality code to one jute-cloth item.

    Many qualities per item_id. Carries the fixed cloth construction: ``ends``,
    ``finished_length`` (yds/cut), ``ozs_yds`` (ACTUAL oz/yd -> production_kg),
    ``std_ozs_yds`` (STANDARD oz/yd -> std_prod_kg), and ``no_of_jugar_per_cut``
    (mandatory, >0; the jugar->yards divisor). ``is_composite=1`` marks a
    multi-component warp (rows live in jute_prod_weaving_quality_dtl, Q6).
    """

    __tablename__ = "jute_prod_weaving_quality"

    weaving_quality_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    item_id = Column(Integer, nullable=False, index=True)  # woven cloth (item_grp_mst.item_type_id=5)
    weaving_quality_code = Column(String(50), nullable=False)
    weaving_quality_name = Column(String(100), nullable=True)
    ends = Column(Integer, nullable=False)
    finished_length = Column(DECIMAL(12, 3), nullable=False)  # yds per full cut (= per piece, Q15)
    ozs_yds = Column(DECIMAL(10, 4), nullable=False)  # ACTUAL oz/yd -> production_kg (legacy q_ozs_yds)
    std_ozs_yds = Column(DECIMAL(10, 4), nullable=True)  # STANDARD oz/yd -> std_prod_kg (distinct)
    no_of_jugar_per_cut = Column(DECIMAL(10, 3), nullable=False)  # jugars per full cut (>0)
    width = Column(DECIMAL(10, 3), nullable=True)
    ports = Column(DECIMAL(10, 3), nullable=True)  # reed ports (distinct from reed_porter, Q16)
    reed_porter = Column(DECIMAL(10, 3), nullable=True)  # reed porter (ends-in-beam input; Q16)
    shrinkage_pct = Column(DECIMAL(6, 3), nullable=True)  # width-wise shrinkage % (reference, Q14)
    shots = Column(DECIMAL(10, 3), nullable=True)  # target shots/pick (reference)
    mc_teeth = Column(Integer, nullable=True)  # change-gear teeth
    jbo_rbo = Column(String(10), nullable=True)  # single/double-loom indicator (legacy jbo_rbo)
    reed_space = Column(DECIMAL(10, 3), nullable=True)  # reed space (legacy q_reed_space)
    tpi = Column(DECIMAL(10, 3), nullable=True)  # twist per inch (reporting)
    yarn_count = Column(String(20), nullable=True)  # reporting (legacy yarn_count)
    is_composite = Column(Integer, nullable=False, default=0, server_default="0")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWeavingQualityDtl(Base):
    """Components of a composite (multi-warp) weaving quality (Q6, mirror beaming).

    Only populated when the parent jute_prod_weaving_quality.is_composite=1; holds
    the real (ends, count) pairs per warp component (>=2 rows). Non-composite
    qualities keep ends on the parent and have NO rows here.
    """

    __tablename__ = "jute_prod_weaving_quality_dtl"

    weaving_quality_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    weaving_quality_id = Column(Integer, nullable=False, index=True)
    component_no = Column(Integer, nullable=False)
    ends = Column(Integer, nullable=False)
    yarn_item_id = Column(Integer, nullable=True)  # jute yarn supplying this component's count
    count = Column(DECIMAL(10, 3), nullable=False)
    active = Column(Integer, nullable=False, default=1, server_default="1")


class JuteProdWeavingTargetMap(Base):
    """Time-versioned weaving QUALITY standards/targets/actuals (last-date resolution).

    Structurally identical to jute_prod_beaming_target_map (PK renamed). Quality-only
    (Q5) — id_type is always 'qid' (ref_id = weaving_quality_id); there are NO loom
    (mcid) standards. grid_params_for (in code) is the single source of truth:
      qid standard -> ('speed','picks','eff')   qid target -> ('speed','eff')   qid actual -> ('speed','picks')  # SQC
    Resolution is branch-agnostic LAST-DATE (MAX effective_date <= on_date among active).
    """

    __tablename__ = "jute_prod_weaving_target_map"

    weaving_target_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)  # stored, NOT used in resolution (branch-agnostic)
    effective_date = Column(Date, nullable=False)
    ref_id = Column(Integer, nullable=False)  # weaving_quality_id (id_type='qid')
    id_type = Column(String(8), nullable=False)  # 'qid' (quality-only, Q5)
    value_role = Column(String(10), nullable=False)  # 'standard' | 'target' | 'actual'
    param = Column(String(20), nullable=False)  # 'speed' | 'picks' | 'eff'
    value = Column(DECIMAL(12, 4), nullable=False, default=0, server_default="0.0000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class WeavingSqcPick(Base):
    """SQC pick (picks-per-inch / width) readings per loom for a weaving quality.

    Insert-only readings table (no upsert): each row is one shop-floor observation
    of ``picks`` (and optional ``width``) taken on ``entry_date`` for a given
    (co_id, weaving_quality_id, machine_id). Soft-deleted via active=0. The view
    vw_weaving_pick_act aggregates active rows per (co_id, weaving_quality_id,
    entry_date) to supply act_picks into weaving production standards resolution.
    """

    __tablename__ = "jute_sqc_weaving_pick"

    weaving_sqc_pick_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False)
    weaving_quality_id = Column(Integer, nullable=False)
    machine_id = Column(Integer, nullable=False)  # loom (machine_type 'Loom')
    # Phase 1c join-key hygiene: optional spell of the reading (wage traceability);
    # NULL on legacy rows (no backfill source) and when the client omits it.
    spell_id = Column(Integer, nullable=True)
    width = Column(DECIMAL(10, 3), nullable=True)
    picks = Column(DECIMAL(10, 3), nullable=False)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWeavingQualityMap(Base):
    """Loom -> Quality assignment per (tran_date, spell_id, machine_id) (§6.6).

    Spinning-style (clone of the daily_doff_frames_winding S-row assignment): one
    ACTIVE row per (tran_date, spell_id, machine_id) (upsert). Production rows inherit
    weaving_quality_id from this map via COALESCE — quality is mapped, NOT selected
    inline per row. An unmapped loom produces no production/planning row.
    """

    __tablename__ = "jute_prod_weaving_quality_map"

    weaving_quality_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)  # loom (machine_type 'Loom')
    weaving_quality_id = Column(Integer, nullable=False)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWeavingBeamMap(Base):
    """Beam -> loom assignment recorded on each beam change, scoped by spell + date (§6.7).

    The production row's beam_no is resolved from the latest beam-change for
    (loom, spell, date). beam_no is NOT a per-production-row field (Q7).
    """

    __tablename__ = "jute_prod_weaving_beam_map"

    weaving_beam_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)  # loom
    beam_no = Column(String(50), nullable=False)  # physical beam mounted
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWeavingDaily(Base):
    """Daily per loom+quality+spell production entry — INPUTS ONLY (FREEZE NOTHING + VIEW).

    Grain: (co_id, tran_date, spell_id, machine_id, weaving_quality_id, active=1).
    STORAGE MODEL (2026-06-24): this table stores ONLY the operator inputs + identity.
    Every reproducible column — jugar, the resolved-standards snapshot
    (finished_length/ozs_yds/std_ozs_yds/no_of_jugar_per_cut, std/act speed+picks,
    std/target eff, working_hours) and every computed output (production_yds/kg/mt,
    std_prod_yds, target_prod_yds, efficiency, std_prod_kg, target_kg, actual_eff,
    aports) — has been DROPPED from the table and is recomputed on read by the
    day-slice SQL (weaving_query.weaving_day_slice_sql, oracle: ``vw_weaving_daily``).

    EXCEPTION (Phase 1b, 2026-07-07): ``open_jugar`` IS stored. It is the jugar-chain
    carry-forward (predecessor's close_jugar in the (co_id, machine_id,
    weaving_quality_id) chain ordered by tran_date, spell rank A1->B1->A2->B2->C,
    weaving_daily_id) — resolved at WRITE time by the weaving_entry writers, which
    also repair the single chain successor in the same transaction. Backfill/heal:
    dbqueries/migrations/backfill_weaving_open_jugar.sql (rerunnable). Drift check:
    dbqueries/check_weaving_open_jugar_parity.sql.

    ``cuts`` is the cut count (INT); ``close_jugar`` is the operator's closing-jugar
    reading (DECIMAL(10,3); enforced 0 <= cj <= no_of_jugar_per_cut at write time);
    ``less_production`` the operator deduction. weaving_quality_id is INHERITED from
    the §6.6 quality map (not entered); eb_id resolves via the attendance view; beam_no
    from the §6.7 beam map. Nothing is frozen — reads always reflect current masters.
    """

    __tablename__ = "jute_prod_weaving_daily"

    # Duplicate-active guard (2026-07-12): active uses NULL-soft-delete semantics
    # (1 = live, NULL = deleted) so this key blocks a second live row per unit+loom
    # while soft-deleted rows can repeat (MySQL unique keys never collide on NULL).
    __table_args__ = (
        UniqueConstraint(
            "co_id", "tran_date", "spell_id", "machine_id", "active",
            name="uq_weaving_daily_unit_machine",
        ),
    )

    weaving_daily_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)  # loom
    weaving_quality_id = Column(Integer, nullable=True, index=True)  # NULL until quality mapped; filled at Process (§6.6)
    eb_id = Column(Integer, nullable=True)  # resolved via attendance view (Q7)
    beam_no = Column(String(50), nullable=True)  # resolved from beam map (§6.7)
    # --- entry inputs ONLY (everything else is recomputed by vw_weaving_daily) ---
    cuts = Column(Integer, nullable=False)
    close_jugar = Column(DECIMAL(10, 3), nullable=True, default=0, server_default="0")  # operator cj (0 <= cj <= jc)
    less_production = Column(DECIMAL(12, 3), nullable=True, default=0, server_default="0")  # operator deduction
    # Stored jugar-chain carry-forward (Phase 1b): write-time resolved + successor-repaired
    # by weaving_entry; NULL only on inactive rows or pre-backfill data.
    open_jugar = Column(DECIMAL(10, 3), nullable=True)
    # NULL-soft-delete: 1 = live, NULL = deleted (NOT 0 — NULL keeps the unique key
    # above from colliding on deleted rows). Readers still filter active = 1.
    active = Column(Integer, nullable=True, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class WeavingLog(Base):
    """Frozen per-row Process snapshot (spec §4.2). Materialised set-based from
    weaving_day_slice_sql; served instead of the live slice once a unit is locked.
    The full computed column set is written/read via text() INSERT...SELECT and
    projection (mirroring the daily reads); only keyed/queried columns need ORM attrs."""

    __tablename__ = "jute_prod_weaving_log"

    weaving_log_id = Column(Integer, primary_key=True, autoincrement=True)
    weaving_daily_id = Column(Integer, nullable=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False)
    spell_id = Column(Integer, nullable=False)
    machine_id = Column(Integer, nullable=False)
    weaving_quality_id = Column(Integer, nullable=True)
    eb_id = Column(Integer, nullable=True)
    working_hours = Column(DECIMAL(10, 3), nullable=True)
    sqc_pick_avg = Column(DECIMAL(10, 3), nullable=True)
    sqc_pick_maxdate = Column(Date, nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class WeavingProcessLock(Base):
    """Per-(co,branch,date,spell) Process lock header (spec §4.3). is_locked gates
    weaving-page mutation behind Edit permission; reprocess_needed raised on SQC/
    stoppage drift after processing."""

    __tablename__ = "jute_prod_weaving_process_lock"

    weaving_process_lock_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False)
    spell_id = Column(Integer, nullable=False)
    is_locked = Column(Integer, nullable=False, default=1, server_default="1")
    reprocess_needed = Column(Integer, nullable=False, default=0, server_default="0")
    processed_by = Column(Integer, nullable=True)
    processed_date_time = Column(TIMESTAMP, nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
