"""SQLAlchemy ORM models for the Jute Production — Finishing sub-module.

Four tables mirror the beaming conventions (Column style, shared Base from
src/models/mst.py so they participate in existing metadata), extended with ONE new
dimension — `process`:

  jute_prod_finishing_quality      -- Finishing Quality Master: item-is-identity (hessian/sacking)
  jute_prod_finishing_target_map   -- the Spec Sheet (effective-dated EAV standards/
                                      targets/actuals) — adds a `process` column
  jute_prod_finishing_daily        -- daily per-process/per-machine/per-quality snapshot
  jute_prod_finishing_daily_param  -- process-specific captured params (EAV child)

Conventions: co_id + branch_id scoping, soft delete (active TINYINT default 1),
audit cols updated_by + updated_date_time (NOT created_*, audit via DB triggers);
Portal persona; no approval workflow. Column names/types/nullability match the
finishing SPEC §4.1 / §4.2 / §4.3 DDL (create_finishing_tables.sql) exactly.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Date,
    DECIMAL,
    TIMESTAMP,
    func,
)

from src.models.mst import Base


class JuteProdFinishingQuality(Base):
    """Finishing Quality Master — one row per (co_id, item_id, quality_type).

    The ITEM is the identity: there is no separate quality code/name — the item_mst
    label IS the quality (joined at query time). ``quality_type`` splits Hessian (1) vs
    Sacking (2) — DISPLAY labels only; the stored value stays INT. The three operating
    params are ALL OPTIONAL: ``packsheet_wt`` (kg), ``std_bale_weight`` (kg),
    ``no_of_bags`` (pcs). App-level duplicate guard on (co_id, quality_type, item_id)
    among active=1 (no DB unique constraint — soft-delete pattern).
    """

    __tablename__ = "jute_prod_finishing_quality"

    finishing_quality_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    quality_type = Column(Integer, nullable=False)  # 1=hessian, 2=sacking
    item_id = Column(Integer, nullable=False, index=True)
    packsheet_wt = Column(DECIMAL(14, 3), nullable=True)     # kg
    std_bale_weight = Column(DECIMAL(14, 3), nullable=True)  # kg
    no_of_bags = Column(Integer, nullable=True)              # pcs
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdFinishingTargetMap(Base):
    """The Finishing Spec Sheet — time-versioned standards/targets/actuals (EAV).

    Identical to jute_prod_beaming_target_map plus a ``process`` column and an index
    that leads with ``process``. One row per
    (process, ref_id, id_type, value_role, param, effective_date). ``id_type='mcid'``
    -> ref_id = machine_id; ``id_type='qid'`` -> ref_id = finishing_quality_id.
    ``value_role='actual'`` rows are written by the Finishing SQC page. Mirrors SPEC §4.2.
    """

    __tablename__ = "jute_prod_finishing_target_map"

    finishing_target_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    process = Column(String(20), nullable=False)  # damping|calendering|lapping|cutting|hemming|balepress
    effective_date = Column(Date, nullable=False)
    ref_id = Column(Integer, nullable=False)  # machine_id (mcid) | finishing_quality_id (qid)
    id_type = Column(String(8), nullable=False)  # 'mcid' | 'qid'
    value_role = Column(String(10), nullable=False)  # 'standard' | 'target' | 'actual'
    param = Column(String(24), nullable=False)  # see SPEC §5 matrix
    value = Column(DECIMAL(12, 4), nullable=False, default=0, server_default="0.0000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdFinishingDaily(Base):
    """Daily per-process/per-machine/per-quality/per-spell production snapshot.

    Universal production/efficiency columns are typed here (input/prod qty + UoM,
    prod weight, resolved std/target speed & eff, computed p100prod / std_prod /
    target_prod / act_eff). Process-specific captured params (bowl_temp, nip_pressure,
    lap_length, cut_length, …) live in the EAV child jute_prod_finishing_daily_param.
    Standards are snapshotted at save (immune to later spec-sheet edits). Mirrors SPEC §4.3.
    """

    __tablename__ = "jute_prod_finishing_daily"

    finishing_daily_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    process = Column(String(20), nullable=False)  # which sub-process
    # NULL for labour-based processes (sacksewing) which have no machine; the row is
    # keyed by eb_id (worker) instead. All other processes set a machine_id.
    machine_id = Column(Integer, nullable=True, index=True)
    finishing_quality_id = Column(Integer, nullable=False, index=True)
    eb_id = Column(Integer, nullable=True)  # worker (labour-based stages, e.g. sacksewing)
    # --- inputs / outputs (UoM depends on process; see SPEC §5) ---
    input_qty = Column(DECIMAL(14, 4), nullable=True)
    input_uom = Column(String(10), nullable=True)  # 'm' | 'pcs' | 'bag'
    prod_qty = Column(DECIMAL(14, 4), nullable=False)
    prod_uom = Column(String(10), nullable=False)  # 'm' | 'roll' | 'pcs' | 'bag' | 'bale'
    prod_wt_kg = Column(DECIMAL(14, 3), nullable=True)
    wastage_kg = Column(DECIMAL(14, 3), nullable=True)
    # --- resolved standards snapshot (from spec sheet at save) ---
    std_speed = Column(DECIMAL(12, 4), nullable=True)
    target_speed = Column(DECIMAL(12, 4), nullable=True)
    act_speed = Column(DECIMAL(12, 4), nullable=True)
    std_eff = Column(DECIMAL(6, 2), nullable=True)
    target_eff = Column(DECIMAL(6, 2), nullable=True)
    working_hours = Column(DECIMAL(5, 2), nullable=True)
    # --- computed outputs (snapshot) ---
    p100prod = Column(DECIMAL(14, 3), nullable=True)
    std_prod = Column(DECIMAL(14, 3), nullable=True)
    target_prod = Column(DECIMAL(14, 3), nullable=True)
    act_eff = Column(DECIMAL(6, 2), nullable=True)  # prod_qty / p100prod × 100
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdFinishingDailyParam(Base):
    """Process-specific captured params for a finishing daily row (EAV child, §4.3).

    One row per (finishing_daily_id, param). Holds the process-specific measured/captured
    inputs (bowl_temp, nip_pressure, lap_length, cut_length, …) that don't warrant a typed
    column on every-process header. Soft-deleted via active=0 (replace-on-save).
    """

    __tablename__ = "jute_prod_finishing_daily_param"

    finishing_daily_param_id = Column(Integer, primary_key=True, autoincrement=True)
    finishing_daily_id = Column(Integer, nullable=False, index=True)
    param = Column(String(24), nullable=False)
    value = Column(DECIMAL(14, 4), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
