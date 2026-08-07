"""SQLAlchemy ORM models for the Jute SQC module (spinning quality control).

Reuses the same declarative Base as src/models/mst.py. These tables feed the
spinning planning grid:
  * jute_sqc_spinning_entry - single-value actual speed/TPI, resolved by last-date
    (Actual Speed / Actual TPI columns; doc 6.2).
  * jute_sqc_spinning_count - multi-observation count; Act Count = AVG(observed_count)
    per date + quality (doc 6.1).
"""

from sqlalchemy import Column, Integer, Date, DECIMAL, TIMESTAMP, String, func

from src.models.mst import Base


class JuteSqcSpinningEntry(Base):
    """Single-value actual Speed + TPI (last-date <= planning date)."""

    __tablename__ = "jute_sqc_spinning_entry"

    spinning_sqc_entry_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    mc_id = Column(Integer, nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)  # yarn item (item_mst.item_id)
    actual_speed = Column(DECIMAL(10, 2), nullable=True)
    actual_tpi = Column(DECIMAL(10, 3), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteSqcSpinningCount(Base):
    """Multi-observation count. Act Count = AVG(observed_count) per date + quality."""

    __tablename__ = "jute_sqc_spinning_count"

    spinning_sqc_count_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=True)
    mc_id = Column(Integer, nullable=True)
    item_id = Column(Integer, nullable=False, index=True)  # yarn item (item_mst.item_id)
    # R-08-16 raw test inputs (DP/TP store-only; WT/450 + MR% feed the count calc).
    dp = Column(DECIMAL(10, 3), nullable=True)
    tp = Column(DECIMAL(10, 3), nullable=True)
    wt_450_gms = Column(DECIMAL(10, 3), nullable=True)
    mr_pct = Column(DECIMAL(5, 2), nullable=True)
    observed_count = Column(DECIMAL(10, 3), nullable=False, default=0, server_default="0.000")
    # corrected_count = observed/(100+mr_pct)*(100+std_mr_pct from jute_yarn_mst).
    corrected_count = Column(DECIMAL(10, 3), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteSqcSpinningRhmr(Base):
    """RHMR — Temperature + Humidity per (date, spell). Upsert one active row per
    (co_id, entry_date, spell_id); the router confirms before overwriting."""

    __tablename__ = "jute_sqc_spinning_rhmr"

    spinning_sqc_rhmr_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    spell_id = Column(Integer, nullable=False, index=True)
    temperature = Column(DECIMAL(5, 1), nullable=True)
    humidity = Column(DECIMAL(5, 1), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteSqcSpinningQrCv(Base):
    """R-08-15 QR/CV group header. One saved test per (date, machine, item_id);
    insert-only (duplicates allowed). observed_count/mr_pct are NOT stored — they
    are read from R-08-16's saved values in jute_sqc_spinning_count (AVG per item_id) at read."""

    __tablename__ = "jute_sqc_spinning_qr_cv"

    spinning_sqc_qr_cv_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    mc_id = Column(Integer, nullable=True)
    item_id = Column(Integer, nullable=False, index=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=False, server_default=func.current_timestamp())


class JuteSqcSpinningQrCvDtl(Base):
    """One spindle reading for a QR/CV group (6 spindles x 5 readings = 30 rows)."""

    __tablename__ = "jute_sqc_spinning_qr_cv_dtl"

    spinning_sqc_qr_cv_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    spinning_sqc_qr_cv_id = Column(Integer, nullable=False, index=True)
    spindle_no = Column(Integer, nullable=False)
    reading_no = Column(Integer, nullable=False)
    reading_val = Column(DECIMAL(10, 3), nullable=True)


class JuteSqcYarnTpi(Base):
    """R-08-17 Yarn TPI & TPI CV% group header. One saved 20-reading twist-uniformity
    study per (date, machine, item_id); insert-only (duplicates allowed). count_lbs /
    std_tpi / tp_value are snapshotted from the form. Stats (avg/std/cv/min/max) are
    computed server-side from the detail rows at read — NOT stored."""

    __tablename__ = "jute_sqc_yarn_tpi"

    yarn_tpi_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    mc_id = Column(Integer, nullable=True, index=True)  # spinning frame
    item_id = Column(Integer, nullable=True, index=True)  # yarn item (item_mst.item_id)
    count_lbs = Column(DECIMAL(10, 3), nullable=True)
    std_tpi = Column(DECIMAL(10, 3), nullable=True)
    tp_value = Column(DECIMAL(10, 3), nullable=True)
    prepared_by = Column(String(150), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=True, server_default=func.current_timestamp())


class JuteSqcYarnTpiDtl(Base):
    """One TPI reading for a R-08-17 study (20 flat readings = 20 rows)."""

    __tablename__ = "jute_sqc_yarn_tpi_dtl"

    yarn_tpi_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    yarn_tpi_id = Column(Integer, nullable=False, index=True)
    reading_no = Column(Integer, nullable=False)
    reading_val = Column(DECIMAL(10, 3), nullable=True)


class JuteSqcQrCv15a(Base):
    """R-08-15A Yarn QR% & CV% Special Purpose group header. One saved test (2 machines,
    flat 12 readings) per (date, machine, item_id); insert-only (duplicates allowed).
    observed_count / mr_pct are OPERATOR-ENTERED on the header (the special-purpose
    variant; NOT read from R-08-16). Stats are computed server-side at read using the
    R-08-15 _qr_cv_stats formula — NOT stored."""

    __tablename__ = "jute_sqc_qr_cv_15a"

    qr_cv_15a_id = Column(Integer, primary_key=True, autoincrement=True)
    co_id = Column(Integer, nullable=False, index=True)
    branch_id = Column(Integer, nullable=True)
    entry_date = Column(Date, nullable=False, index=True)
    drawing_mc_id = Column(Integer, nullable=True)  # 3rd-drawing machine
    mc_id = Column(Integer, nullable=True, index=True)  # spinning frame
    item_id = Column(Integer, nullable=True, index=True)  # yarn item (item_mst.item_id)
    observed_count = Column(DECIMAL(10, 3), nullable=True)
    mr_pct = Column(DECIMAL(5, 2), nullable=True)
    active = Column(Integer, nullable=False, default=1, server_default="1")
    updated_by = Column(Integer, nullable=True)
    updated_date_time = Column(TIMESTAMP, nullable=True, server_default=func.current_timestamp())


class JuteSqcQrCv15aDtl(Base):
    """One reading for a R-08-15A test (12 flat readings = 12 rows)."""

    __tablename__ = "jute_sqc_qr_cv_15a_dtl"

    qr_cv_15a_dtl_id = Column(Integer, primary_key=True, autoincrement=True)
    qr_cv_15a_id = Column(Integer, nullable=False, index=True)
    reading_no = Column(Integer, nullable=False)
    reading_val = Column(DECIMAL(10, 3), nullable=True)
