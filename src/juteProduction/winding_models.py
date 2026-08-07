"""SQLAlchemy ORM models for the Jute Production — Winding sub-module.

Three entry tables mirror the spinning conventions (Column style, shared Base
from src/models/mst.py so they participate in existing metadata):

  jute_prod_winding_doff       -- one row per weighing per PERSON (eb_id)
  jute_prod_winding_jugar      -- spindle open/close leftover weight per person/spell
  jute_prod_winding_daily_qlty -- the person -> yarn-quality map (+ machine and
                                  spindle count)

Entry is PERSON-keyed (docs/winding-person-keyed-entry-spec.md): ``eb_id``
(hrms_ed_personal_details.eb_id) is the identity of every row and every write path
requires it. On the DOFF and JUGAR tables ``machine_id`` (and ``no_of_machines``)
are DEAD columns retained by decision D3/D4: no write path sets them and no row
uses them; they stay NULL-able and are not dropped. The quality map is the ONE
exception — its ``machine_id`` IS live (written by /quality_add and /quality_save,
carried forward by the auto-seed) and stays nullable because the machine may not be
known when a winder is added. Reads LEFT JOIN the worker (and the machine) so a row
whose ``eb_id`` no longer resolves to an active HRMS employee still shows with a
blank worker instead of disappearing.

Conventions: co_id + branch_id scoping, soft delete (active TINYINT default 1),
audit cols updated_by + updated_date_time (NOT created_*); spell stored as
spell_id (INT), resolved from spell_code at the boundary. Quality identity is the
yarn ITEM (item_id -> item_mst.item_id) — there is NO separate quality master.

The retired round-1 aggregate jute_prod_winding_prod is dropped by
create_jute_prod_winding_tables.sql; its model (formerly in spinning_models.py)
is superseded by the read-time reconciliation view. Reconciled production is
computed at READ time, never persisted.
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


class JuteProdWindingDoff(Base):
    """Doff production — one row per WINDER of one weighing.

    net_total = gross - trolly_wt - spool_wt (winding_rules.compute_winding_net),
    split equally over the winders sharing the weighing: production_qty and
    gross_input_wt hold that winder's share, trolly_wt / spool_wt stay whole (the
    tare comes off once for the weighing), row_gross_wt = production_qty +
    trolly_wt + spool_wt.

    ``weighing_id`` ties the shares of one weighing together so edit and delete
    act on all of them — a partial split would leave the spinning planning grid
    (which sums production_qty per item + shift) short by the missing share. It
    is the FIRST row's winding_doff_id. Rows written before the column existed
    keep NULL and count as a solo group via
    COALESCE(weighing_id, winding_doff_id).
    """

    __tablename__ = "jute_prod_winding_doff"

    winding_doff_id = Column(Integer, primary_key=True, autoincrement=True)
    weighing_id = Column(Integer, nullable=True, index=True)  # group key; NULL = solo (pre-column row)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    eb_id = Column(Integer, nullable=True, index=True)  # the winder (hrms_ed_personal_details.eb_id)
    machine_id = Column(Integer, nullable=True, index=True)  # dead column: never written, no row uses it
    item_id = Column(Integer, nullable=True, index=True)  # yarn item (item_mst.item_id)
    trolly_id = Column(Integer, nullable=True)
    trolly_wt = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    spool_id = Column(Integer, nullable=True)
    spool_wt = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    no_of_machines = Column(Integer, nullable=True)  # dead column: never written, no row uses it
    gross_input_wt = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    production_qty = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    row_gross_wt = Column(DECIMAL(12, 3), nullable=False, default=0, server_default="0.000")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWindingJugar(Base):
    """Jugar — yarn weight still on spindles at shift boundary, per person/spell.

    open_close: 'O' (opening) / 'C' (closing). Daily reconciliation subtracts the
    opening and adds the closing to convert "weight doffed" into "weight produced"
    net of spindle carryover (winding_rules.reconcile_production).
    """

    __tablename__ = "jute_prod_winding_jugar"

    winding_jugar_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    eb_id = Column(Integer, nullable=True, index=True)  # the winder
    machine_id = Column(Integer, nullable=True, index=True)  # dead column: never written, no row uses it
    weight = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    open_close = Column(String(1), nullable=False, default="O", server_default="O")  # 'O' | 'C'
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteProdWindingDailyQlty(Base):
    """The person -> quality map: yarn quality + spindle count per winder/spell.

    Auto-seeded by carrying the PERSONS of the previous spell forward (with their
    item_id + no_of_spindle) when no rows exist for a date/spell; winders are
    added/removed by hand from the Quality tab. Feeds the doff-form prefill and
    the reconciliation's quality fallback (COALESCE(doff.item_id, qmap.item_id)).
    """

    __tablename__ = "jute_prod_winding_daily_qlty"

    winding_daily_qlty_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    eb_id = Column(Integer, nullable=True, index=True)  # the winder
    machine_id = Column(Integer, nullable=True, index=True)  # LIVE here (unlike doff/jugar); NULL until known
    item_id = Column(Integer, nullable=True, index=True)  # yarn item (item_mst.item_id)
    no_of_spindle = Column(Integer, nullable=False, default=0, server_default="0")
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
