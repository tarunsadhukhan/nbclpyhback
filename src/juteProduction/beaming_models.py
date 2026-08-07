"""SQLAlchemy ORM models for the Jute Production — Beaming sub-module.

Three tables mirror the spinning / winding conventions (Column style, shared Base
from src/models/mst.py so they participate in existing metadata):

  jute_prod_bm_quality          -- Beaming Quality Master: item -> bm_quality (+ ends, std_count)
  jute_prod_beaming_target_map  -- effective-dated machine standards/targets (spngTargetMap clone)
  jute_prod_beaming_daily       -- daily per-machine/per-quality production snapshot

Conventions: co_id + branch_id scoping, soft delete (active TINYINT default 1),
audit cols updated_by + updated_date_time (NOT created_*, audit via DB triggers);
Portal persona; no approval workflow. Column names/types/nullability match the
beaming SPEC §A.3 / §B.3 / §C.3 DDL exactly.
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


class JuteProdBmQuality(Base):
    """Beaming Quality Master — maps one bm_quality code to one jute-cloth item.

    Many qualities per item_id. ``std_count`` is a snapshot taken from the linked
    jute yarn (jute_yarn_mst.jute_yarn_count, via yarn_item_id) so it survives
    later yarn-master edits (SPEC §A.8). ``is_composite=1`` marks a multi-component
    warp (needs jute_prod_bm_quality_dtl, §A.4) — production entry is blocked for
    composite qualities until that path exists (§C.5).
    """

    __tablename__ = "jute_prod_bm_quality"

    bm_quality_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    item_id = Column(Integer, nullable=False, index=True)
    bm_quality_code = Column(String(50), nullable=False)
    bm_quality_name = Column(String(100), nullable=True)
    ends = Column(Integer, nullable=False)
    std_count = Column(DECIMAL(10, 3), nullable=False)  # from jute_yarn_mst.jute_yarn_count (§A.8)
    yarn_item_id = Column(Integer, nullable=True)  # linked jute yarn supplying the count (§A.8)
    is_composite = Column(Integer, nullable=False, default=0, server_default="0")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdBmQualityDtl(Base):
    """Components of a composite (multi-warp) beaming quality (SPEC §A.4).

    Only populated when the parent jute_prod_bm_quality.is_composite=1; holds the
    real (ends, count) pairs per warp component (>=2 rows). For composite the parent's
    ends = SUM(component ends) and its std_count / yarn_item_id are NULL; the per-cut
    weight uses laid_length × SUM_n(ends_n × count_n) / (14400 × 2.20462). Non-composite
    qualities keep ends/std_count/yarn_item_id on the parent and have NO rows here.
    """

    __tablename__ = "jute_prod_bm_quality_dtl"

    bm_quality_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    bm_quality_id = Column(Integer, nullable=False, index=True)
    component_no = Column(Integer, nullable=False)
    ends = Column(Integer, nullable=False)
    yarn_item_id = Column(Integer, nullable=True)  # linked jute yarn supplying the count (optional per component)
    count = Column(DECIMAL(10, 3), nullable=False)
    active = Column(Integer, nullable=False, default=1, server_default="1")


class JuteProdBeamingTargetMap(Base):
    """Time-versioned beaming machine standards/targets (last-date resolution).

    Structurally identical to jute_prod_spng_target_map but a dedicated table to
    keep param namespaces / resolvers separate (SPEC §B.2). Machine-only (no qid):
      Std laid_length / cuts_per_beam / speed / eff = (id_type='mcid', value_role='standard', param)
      Target speed / eff                            = (id_type='mcid', value_role='target',  param)
    """

    __tablename__ = "jute_prod_beaming_target_map"

    beaming_target_map_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    effective_date = Column(Date, nullable=False)
    ref_id = Column(Integer, nullable=False)  # machine_id (id_type='mcid')
    id_type = Column(String(8), nullable=False)  # 'mcid'
    value_role = Column(String(10), nullable=False)  # 'standard' | 'target'
    param = Column(String(20), nullable=False)  # 'laid_length' | 'cuts_per_beam' | 'speed' | 'eff'
    value = Column(DECIMAL(12, 4), nullable=False, default=0, server_default="0.0000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdBeamingDaily(Base):
    """Daily per-machine/per-quality/per-spell production snapshot.

    Stores entered inputs (act_cuts, no_of_beam, roller rpm/dia), the resolved
    standards snapshot (ends, count, laid_length, speeds, effs, working_hours) and
    the server-computed outputs (yards/kg per cut/beam, p100prod, std/tgt/act prod,
    act_eff). Efficiency is length-basis only: act_eff = act_prod_yards / p100prod
    × 100 (SPEC §3). Derived from §C.3 DDL.
    """

    __tablename__ = "jute_prod_beaming_daily"

    beaming_daily_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    machine_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    bm_quality_id = Column(Integer, nullable=False, index=True)
    eb_id = Column(Integer, nullable=True)
    beam_no = Column(String(50), nullable=True)  # physical beam number holding material (like trolley no, §Q10)
    # --- entry inputs ---
    act_cuts = Column(Integer, nullable=False)
    no_of_beam = Column(Integer, nullable=False)
    rpm_roller = Column(DECIMAL(10, 3), nullable=True)
    dia_roller = Column(DECIMAL(10, 3), nullable=True)
    # --- resolved standards (snapshot) ---
    ends = Column(Integer, nullable=True)
    std_count = Column(DECIMAL(10, 3), nullable=True)
    act_count = Column(DECIMAL(10, 3), nullable=True)
    laid_length = Column(DECIMAL(12, 4), nullable=True)
    std_cuts_per_beam = Column(DECIMAL(10, 3), nullable=True)
    std_speed = Column(DECIMAL(12, 4), nullable=True)
    target_speed = Column(DECIMAL(12, 4), nullable=True)
    act_speed = Column(DECIMAL(12, 4), nullable=True)
    std_eff = Column(DECIMAL(6, 2), nullable=True)
    target_eff = Column(DECIMAL(6, 2), nullable=True)
    working_hours = Column(DECIMAL(5, 2), nullable=True)
    # --- computed outputs (snapshot) ---
    yards_per_beam = Column(DECIMAL(14, 4), nullable=True)
    kg_per_cut = Column(DECIMAL(14, 6), nullable=True)
    kg_per_beam = Column(DECIMAL(14, 4), nullable=True)
    p100prod = Column(DECIMAL(14, 3), nullable=True)  # yards; std_speed-based (single)
    std_prod = Column(DECIMAL(14, 3), nullable=True)  # yards
    target_prod = Column(DECIMAL(14, 3), nullable=True)  # yards
    act_prod_kg = Column(DECIMAL(14, 3), nullable=True)  # kg (weight report only)
    act_prod_yards = Column(DECIMAL(14, 3), nullable=True)  # yards (efficiency basis)
    act_eff = Column(DECIMAL(6, 2), nullable=True)  # act_prod_yards / p100prod × 100
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
