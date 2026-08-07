"""SQLAlchemy ORM models for the Jute Production (spinning / doff) module.

These reuse the same declarative Base as src/models/mst.py so they participate
in the existing metadata if anyone runs create_all().

The first block defines the NEW spinning tables. The second block defines
lightweight read models over reused mobile-app tables (daily_doff_tbl,
daily_doff_frames_winding, trolly_mst, spinning_quality_mst) — note that
trolly_mst keeps the production typo ``busket_weight`` (alias to bucket_weight
only in API responses, never rename the column).
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DateTime,
    DECIMAL,
    TIMESTAMP,
    Index,
    func,
)

from src.models.mst import Base


# --- NEW spinning tables -----------------------------------------------------


class JuteProdSpngTargetMap(Base):
    """Time-versioned standards/targets (last-date resolution).

    Replaces the standards that previously lived as single current values in
    yarn_quality_param / yarn_quality_master. Resolution map (doc 2.5):
      Std/Target Speed = (id_type='mcid', value_role, param='speed')
      Std/Target TPI   = (id_type='qid',  value_role, param='tpi')
      Std/Target Eff   = (id_type='qid',  value_role, param='eff')
    """

    __tablename__ = "jute_prod_spng_target_map"

    spng_target_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    effective_date = Column(Date, nullable=False)
    ref_id = Column(Integer, nullable=False)  # machine_id (mcid) or yarn item_id (qid = yarn item id)
    id_type = Column(String(8), nullable=False)  # 'mcid' | 'qid' (qid = yarn item id)
    value_role = Column(String(10), nullable=False)  # 'standard' | 'target' | 'actual'
    param = Column(String(20), nullable=False)  # 'speed' | 'tpi' | 'eff' | 'spindles' | 'dc' | 'tc' | 'bobbin_wt'
    value = Column(DECIMAL(12, 4), nullable=False, default=0, server_default="0.0000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdSpinningDaily(Base):
    """Per-frame-per-spell planning-grid snapshot (rebuilt from the old per-quality
    shift rollup). One row per (tran_date, spell, frame). Shift rollups are derived
    by query (SUM prod / SUM p100prod), not stored. See doc 4 / 5.3."""

    __tablename__ = "jute_prod_spinning_daily"

    spinning_daily_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)  # yarn item (item_mst.item_id)
    spindles = Column(Integer, nullable=False, default=0, server_default="0")
    minutes = Column(Integer, nullable=False, default=0, server_default="0")
    act_count = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    std_count = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    std_speed = Column(DECIMAL(10, 2), nullable=False, default=0, server_default="0.00")
    actual_speed = Column(DECIMAL(10, 2), nullable=False, default=0, server_default="0.00")
    target_speed = Column(DECIMAL(10, 2), nullable=False, default=0, server_default="0.00")
    std_tpi = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    actual_tpi = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    target_tpi = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    std_eff = Column(DECIMAL(8, 2), nullable=False, default=0, server_default="0.00")
    target_eff = Column(DECIMAL(8, 2), nullable=False, default=0, server_default="0.00")
    p100prod = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    std_prod = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    target_prod = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    act_prod_doff = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    winding_total = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    act_prod_wind = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    eff_doff = Column(DECIMAL(8, 2), nullable=False, default=0, server_default="0.00")
    eff_winding = Column(DECIMAL(8, 2), nullable=False, default=0, server_default="0.00")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    __table_args__ = (
        Index("idx_jpsd_unit", "co_id", "tran_date", "spell_id", "machine_id", "item_id"),
    )


class JuteProdSpinningProcessLock(Base):
    """One lock header per (co, branch, tran_date, spell) spinning unit.

    Mirror of jute_prod_weaving_process_lock. is_locked gates mutations via
    spinning_lock.require_edit_if_locked; reprocess_needed is raised by
    flag_reprocess_if_locked and by on-read drift detection (process_status)."""

    __tablename__ = "jute_prod_spinning_process_lock"

    spinning_process_lock_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False)
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

    __table_args__ = (Index("idx_slock_unit", "co_id", "tran_date", "spell_id"),)


class SpgQualityHelper(Base):
    """Current quality mapping — ONE row per machine (spec 5.1).

    Cache of "what is Frame X spinning right now". Written ONLY by the
    mapper-save code path (no CRUD endpoint of its own) — derived data.
    Never an oracle for history; as-of resolution uses SpgQualityMapper."""

    __tablename__ = "spg_quality_helper"

    quality_helper_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, nullable=True, index=True)  # denormalized from machine's dept; display/scope only
    mc_id = Column(Integer, nullable=False, unique=True)  # uq_sqh_mc — grain PENDING D9: (mc_id, spell_id) if per-spell qualities
    item_id = Column(Integer, nullable=False)  # yarn item (item_mst.item_id)
    effective_from_date = Column(Date, nullable=False)  # copy of the producing mapper row
    effective_from_spell_id = Column(Integer, nullable=True)
    quality_mapper_id = Column(Integer, nullable=False)  # provenance: mapper row that produced this state
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class SpgQualityMapper(Base):
    """Append-only quality change log (spec 5.1). Owns history, as-of
    resolution, retro updates. active=0 only voids a mistaken entry."""

    __tablename__ = "spg_quality_mapper"

    quality_mapper_id = Column(Integer, primary_key=True, autoincrement=True)
    branch_id = Column(Integer, nullable=True)
    mc_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=False)  # yarn item (item_mst.item_id)
    effective_from_date = Column(Date, nullable=False)
    effective_from_spell_id = Column(Integer, nullable=True)  # NULL = start of day; else from that spell onward
    retro_mode = Column(String(10), nullable=False, default="fill", server_default="fill")  # fill | synced | all
    retro_rows = Column(Integer, nullable=False, default=0, server_default="0")  # doff rows the retro update touched
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())

    __table_args__ = (
        Index("idx_sqm_lookup", "mc_id", "effective_from_date", "quality_mapper_id"),
        Index("idx_sqm_branch_date", "branch_id", "effective_from_date"),
    )


class SpinningQualityXref(Base):
    __tablename__ = "spinning_quality_xref"

    xref_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=True, index=True)
    spg_quality_mst_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False)  # yarn item (item_mst.item_id)
    active = Column(Integer, nullable=False, default=1, server_default="1")


# --- Lightweight read models over reused mobile-app tables -------------------


class DailyDoffTbl(Base):
    __tablename__ = "daily_doff_tbl"

    daily_doff_tbl_id = Column(Integer, primary_key=True, autoincrement=True)
    doff_date = Column(Date, nullable=True)
    spell = Column(Integer, nullable=True)  # holds spell_id (INT), NOT the spell_code string
    mc_id = Column(Integer, nullable=True)  # = machine_mst.machine_id
    quality_id = Column(Integer, nullable=True)  # = spinning_quality_mst.spg_quality_mst_id
    trolly_id = Column(Integer, nullable=True)
    gross_weight = Column(DECIMAL(12, 3), nullable=True)
    tare_weight = Column(DECIMAL(12, 3), nullable=True)
    net_weight = Column(DECIMAL(12, 3), nullable=True)
    weight_type = Column(String(20), nullable=True)
    active = Column(Integer, nullable=True)
    branch_id = Column(Integer, nullable=True)
    # Nullable columns added by the spinning migration:
    item_id = Column(Integer, nullable=True)  # yarn item (item_mst.item_id)
    eb_id = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(DateTime, nullable=True)
    # Added by add_spg_quality_helper_mapper.sql (spec 5.1):
    item_source = Column(String(8), nullable=True)  # 'helper' | 'mapper' | 'manual' | 'import'
    eb_source = Column(String(8), nullable=True)  # 'sync' | 'manual' | 'import'


class DailyDoffFramesWinding(Base):
    __tablename__ = "daily_doff_frames_winding"

    daily_doff_frm_wdg_id = Column(Integer, primary_key=True, autoincrement=True)
    tran_date = Column(Date, nullable=True)
    spell = Column(String(10), nullable=True)
    spell_id = Column(Integer, nullable=True)
    mc_eb_id = Column(Integer, nullable=True)  # machine_id when spg_wdg='S'
    quality_id = Column(Integer, nullable=True)  # = spg_quality_mst_id
    eb_id = Column(Integer, nullable=True)
    spg_wdg = Column(String(1), nullable=True)  # 'S' spinning / 'W' winding
    branch_id = Column(Integer, nullable=True)
    active = Column(Integer, nullable=True)
    sc_type = Column(String(20), nullable=True)
    trolly_id = Column(Integer, nullable=True)
    gross_weight = Column(DECIMAL(12, 3), nullable=True)
    tare_weight = Column(DECIMAL(12, 3), nullable=True)
    net_weight = Column(DECIMAL(12, 3), nullable=True)
    user_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True)
    # Nullable columns added by the spinning migration:
    item_id = Column(Integer, nullable=True)  # yarn item (item_mst.item_id)
    # Added by add_updated_cols_daily_doff_frames_winding.sql:
    updated_by = Column(Integer, nullable=True)  # user_mst.user_id of last saver
    updated_date_time = Column(DateTime, nullable=True)  # timestamp of last save


class TrollyMst(Base):
    __tablename__ = "trolly_mst"

    trolly_id = Column(Integer, primary_key=True, autoincrement=True)
    trolly_name = Column(String(100), nullable=True)
    trolly_weight = Column(DECIMAL(10, 3), nullable=True)
    busket_weight = Column(DECIMAL(10, 3), nullable=True)  # TYPO kept — alias AS bucket_weight in responses
    trolly_posting_code = Column(String(50), nullable=True)
    branch_id = Column(Integer, nullable=True)
    trolly_type = Column(String(1), nullable=True)  # 'T'=trolly, 'S'=spool
    machine_type_id = Column(Integer, nullable=True)  # FK machine_type_mst — production stage marker


class SpinningQualityMst(Base):
    __tablename__ = "spinning_quality_mst"

    spg_quality_mst_id = Column(Integer, primary_key=True, autoincrement=True)
    spg_quality = Column(String(100), nullable=True)
    spg_type_id = Column(Integer, nullable=True)
    no_of_spindles = Column(Integer, nullable=True)
    speed = Column(DECIMAL(10, 2), nullable=True)
    tpi = Column(DECIMAL(10, 3), nullable=True)
    std_count = Column(DECIMAL(10, 3), nullable=True)
