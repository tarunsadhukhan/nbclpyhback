"""SQLAlchemy ORM model for the Jute Production — Stoppage Hours sub-module.

A single tenant-DB table holds a machine stoppage event log (one row per
stoppage event):

  jute_prod_stoppage_hours -- reason-tagged downtime per machine/date/spell

Conventions mirror winding_models.py (Column style, shared Base from
src/models/mst.py so it participates in existing metadata): co_id NOT NULL,
nullable derived branch_id, tran_date, soft delete (active TINYINT default 1),
audit cols updated_by + updated_date_time (NOT created_*).

(machine_id, tran_date, spell_id) is intentionally NON-unique — multiple
stoppage events per machine/spell/day are allowed (the table is an
append/soft-delete event log). Department is NOT stored; it is a UI cascade
filter only and is derived via machine_mst.dept_id -> dept_mst.branch_id on
read. reason_code is a fixed app-level enum (STOPPAGE_REASONS in constants.py)
— there is no reason master table. spell_id is stored as INT FK to
spell_mst.spell_id (new convention) so the planned working_hours resolves
directly for the net-running-hours impact formula.

Schema source of truth (already created on dev3):
dbqueries/migrations/create_jute_prod_stoppage_hours.sql
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


class JuteProdStoppageHours(Base):
    """Machine stoppage event log (one row per stoppage event).

    (machine_id, tran_date, spell_id) is intentionally NON-unique — multiple
    stoppage events per machine/spell/day are allowed. Department is NOT stored;
    it is a UI cascade filter only and is derived via machine_mst.dept_id ->
    dept_mst.branch_id on read. reason_code is a fixed app-level enum
    (STOPPAGE_REASONS) — there is no reason master table.
    """

    __tablename__ = "jute_prod_stoppage_hours"

    stoppage_hours_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True, index=True)  # derived from machine->dept->branch
    tran_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)  # FK spell_mst.spell_id (new convention)
    machine_id = Column(Integer, nullable=False, index=True)  # FK machine_mst.machine_id
    stoppage_hours = Column(DECIMAL(5, 2), nullable=False)
    reason_code = Column(String(20), nullable=False)  # STOPPAGE_REASONS enum
    remarks = Column(String(255), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())
