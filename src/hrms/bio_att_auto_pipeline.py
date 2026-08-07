"""bio_att_auto_pipeline.py — Automated bio-attendance pipeline.

Runs the bio data process chain automatically on a schedule for a single
configured tenant/branch:

    Prepare punches  ->  Bprocess (bio_attendance_basic)  ->  B Atten (bio_attendance_process)

Ported from the SJM deployment, minus the final-process step: this pipeline
builds ONLY bio_attendance_basic and bio_attendance_process — it never writes
daily_attendance.

The biometric device punches are assumed to be written into
``bio_attendance_table`` by an EXTERNAL process (roughly hourly) or manual
entry. This job does NOT fetch from any device — it only processes whatever
rows are present.

Key behaviours
--------------
* Fires every hour (interval configurable), hosted by src/scheduler_main.py.
* Skips a run when no new punches have arrived since the last run, detected via
  a high-water mark on ``bio_att_id`` (the auto-increment PK).
* When new punches exist it re-processes the affected date(s) AND each prior
  day (closes a night shift whose OUT punch arrives the next morning). Every
  step deletes-then-rebuilds the date, so re-processing is harmless.

Configuration (environment variables, read from env/database.env)
-----------------------------------------------------------------
  BIO_ATT_AUTO_ENABLED       master on/off (default "false")
  BIO_ATT_AUTO_TENANT        tenant/subdomain = MySQL DB name (e.g. dev3)
  BIO_ATT_AUTO_BRANCH        branch_id (state-table key)
  BIO_ATT_AUTO_COMPANY_ID    company id (default 2)
  BIO_ATT_AUTO_INTERVAL_MIN  minutes between runs (default 60)

Manual one-shot run (for verification)
--------------------------------------
  python -m src.hrms.bio_att_auto_pipeline --tenant dev3 --branch 1
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import traceback
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# The standalone scheduler process needs env/database.env loaded before any
# session is created (same file src/config/db.py loads for the main app).
load_dotenv("env/database.env")

from src.hrms.bioAttendance import (  # noqa: E402
    ensure_bio_tables,
    sync_punch_logs,
    prepare_punches,
    bprocess_core,
    b_atten_core,
)

log = logging.getLogger("bio_att_auto")

# Module-level scheduler handle (set by start_scheduler).
_scheduler = None


def make_session(tenant: str) -> Session:
    """Create a SQLAlchemy session bound to the tenant MySQL database."""
    user = os.environ["DATABASE_USER"]
    pwd = os.environ["DATABASE_PASSWORD"]
    host = os.environ["DATABASE_HOST"]
    port = os.environ.get("DATABASE_PORT", "3306")
    url = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{tenant}"
    engine = create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"init_command": "SET SESSION time_zone='+05:30'"},
    )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


# ── Config ───────────────────────────────────────────────────────────────────

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _read_config() -> dict | None:
    """Read pipeline config from env. Returns None if disabled or misconfigured."""
    if not _env_bool("BIO_ATT_AUTO_ENABLED", False):
        log.info("BIO_ATT_AUTO_ENABLED is not set — automated pipeline disabled.")
        return None

    tenant = (os.environ.get("BIO_ATT_AUTO_TENANT") or "").strip()
    branch_raw = (os.environ.get("BIO_ATT_AUTO_BRANCH") or "").strip()
    if not tenant or not branch_raw:
        log.error(
            "BIO_ATT_AUTO_ENABLED is true but BIO_ATT_AUTO_TENANT / "
            "BIO_ATT_AUTO_BRANCH are missing — pipeline NOT started."
        )
        return None
    try:
        branch_id = int(branch_raw)
    except ValueError:
        log.error("BIO_ATT_AUTO_BRANCH=%r is not an integer — pipeline NOT started.", branch_raw)
        return None

    try:
        company_id = int(os.environ.get("BIO_ATT_AUTO_COMPANY_ID", "2"))
    except ValueError:
        company_id = 2
    try:
        interval_min = max(1, int(os.environ.get("BIO_ATT_AUTO_INTERVAL_MIN", "60")))
    except ValueError:
        interval_min = 60

    return {
        "tenant": tenant,
        "branch_id": branch_id,
        "company_id": company_id,
        "interval_min": interval_min,
    }


# ── Pure helpers ─────────────────────────────────────────────────────────────

def compute_dates_to_process(new_dates) -> list[date]:
    """Each new date plus the day before it (closes night shifts), sorted,
    de-duplicated."""
    out: set[date] = set()
    for d in new_dates:
        out.add(d)
        out.add(d - timedelta(days=1))
    return sorted(out)


def should_skip(current_max, last_processed_id: int) -> bool:
    """True when there is no new data to process."""
    return current_max is None or int(current_max) <= int(last_processed_id)


def compute_high_water_mark(
    current_max: int, last_id: int, failed_min_new_id: int | None
) -> int:
    """New high-water mark after a pass: advance to current_max unless a date
    failed part-way, in which case stop just below its earliest new punch so it
    retries next tick. Never moves backward, never exceeds current_max."""
    if failed_min_new_id is None:
        return int(current_max)
    return max(int(last_id), min(int(current_max), int(failed_min_new_id) - 1))


# ── State table (high-water mark) ────────────────────────────────────────────

_CREATE_STATE_SQL = text(
    """
    CREATE TABLE IF NOT EXISTS bio_att_auto_state (
        branch_id        INT       NOT NULL PRIMARY KEY,
        last_bio_att_id  BIGINT    NOT NULL DEFAULT 0,
        last_run_at      DATETIME  NULL
    )
    """
)

_GET_LAST_ID_SQL = text(
    "SELECT last_bio_att_id FROM bio_att_auto_state WHERE branch_id = :branch_id"
)

_UPSERT_LAST_ID_SQL = text(
    """
    INSERT INTO bio_att_auto_state (branch_id, last_bio_att_id, last_run_at)
    VALUES (:branch_id, :last_id, NOW())
    ON DUPLICATE KEY UPDATE
        last_bio_att_id = VALUES(last_bio_att_id),
        last_run_at     = VALUES(last_run_at)
    """
)

# Heartbeat: bump last_run_at on every tick (even skipped ones) WITHOUT moving
# the high-water mark.
_TOUCH_RUN_AT_SQL = text(
    """
    INSERT INTO bio_att_auto_state (branch_id, last_bio_att_id, last_run_at)
    VALUES (:branch_id, 0, NOW())
    ON DUPLICATE KEY UPDATE last_run_at = NOW()
    """
)

_MAX_BIO_ATT_ID_SQL = text("SELECT MAX(bio_att_id) AS max_id FROM bio_attendance_table")

# MySQL named lock — guarantees a single concurrent run even across processes.
_LOCK_NAME = "bio_att_auto"
_GET_LOCK_SQL = text("SELECT GET_LOCK(:name, 0) AS got")
_RELEASE_LOCK_SQL = text("SELECT RELEASE_LOCK(:name)")

# ── Self-healing lock ─────────────────────────────────────────────────────────
# GET_LOCK is connection-scoped: a run KILLED mid-flight leaves its connection
# lingering server-side, holding the lock until wait_timeout. To self-heal:
# shrink the lock connection's idle wait_timeout and keep a LIVE run's
# connection fresh with a heartbeat. A killed run stops pinging, so the server
# reaps its connection within ~LOCK_WAIT_TIMEOUT_SEC and the lock frees itself.
LOCK_HEARTBEAT_SEC = 30
LOCK_WAIT_TIMEOUT_SEC = 120
_LOCK_HEARTBEAT_SQL = text("SELECT 1")
_SET_LOCK_WAIT_TIMEOUT_SQL = text("SET SESSION wait_timeout = :w")


def _lock_heartbeat(lock_db: Session, stop: threading.Event) -> None:
    """Ping the lock connection every LOCK_HEARTBEAT_SEC until ``stop`` is set."""
    while not stop.wait(LOCK_HEARTBEAT_SEC):
        try:
            lock_db.execute(_LOCK_HEARTBEAT_SQL)
        except Exception:
            log.warning("bio_att_auto lock heartbeat failed — stopping heartbeat.")
            break


_NEW_DATES_SQL = text(
    """
    SELECT DISTINCT DATE(log_date) AS d
    FROM bio_attendance_table
    WHERE bio_att_id > :last_id AND log_date IS NOT NULL
    ORDER BY d
    """
)

_DATES_SINCE_SQL = text(
    """
    SELECT DISTINCT DATE(log_date) AS d
    FROM bio_attendance_table
    WHERE log_date IS NOT NULL AND DATE(log_date) >= :since
    ORDER BY d
    """
)

# Smallest new (id > last_id) bio_att_id among a set of dates — holds the
# high-water mark below dates whose chain did not complete, so they retry.
_MIN_NEW_ID_FOR_DATES_SQL = text(
    """
    SELECT MIN(bio_att_id) AS min_id
    FROM bio_attendance_table
    WHERE bio_att_id > :last_id
      AND log_date IS NOT NULL
      AND DATE(log_date) IN :dates
    """
).bindparams(bindparam("dates", expanding=True))


def _get_last_bio_att_id(db: Session, branch_id: int) -> int:
    row = db.execute(_GET_LAST_ID_SQL, {"branch_id": branch_id}).first()
    return int(row[0]) if row and row[0] is not None else 0


def _get_max_bio_att_id(db: Session):
    row = db.execute(_MAX_BIO_ATT_ID_SQL).mappings().first()
    return row["max_id"] if row else None


def _rows_to_dates(rows) -> list[date]:
    out: list[date] = []
    for r in rows:
        d = r[0]
        out.append(d if isinstance(d, date) else date.fromisoformat(str(d)))
    return out


def _get_new_dates(db: Session, last_id: int) -> list[date]:
    return _rows_to_dates(db.execute(_NEW_DATES_SQL, {"last_id": last_id}).fetchall())


def _get_dates_since(db: Session, since: date) -> list[date]:
    return _rows_to_dates(
        db.execute(_DATES_SINCE_SQL, {"since": since.isoformat()}).fetchall()
    )


def _get_min_new_id_for_dates(db: Session, last_id: int, dates) -> int | None:
    if not dates:
        return None
    row = db.execute(
        _MIN_NEW_ID_FOR_DATES_SQL,
        {"last_id": int(last_id), "dates": list(dates)},
    ).first()
    return int(row[0]) if row and row[0] is not None else None


def _set_last_bio_att_id(db: Session, branch_id: int, last_id: int) -> None:
    db.execute(_UPSERT_LAST_ID_SQL, {"branch_id": branch_id, "last_id": int(last_id)})
    db.commit()


def _touch_last_run_at(db: Session, branch_id: int) -> None:
    """Best-effort heartbeat — never let a failure abort a run."""
    try:
        db.execute(_TOUCH_RUN_AT_SQL, {"branch_id": branch_id})
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


# ── Pipeline core ────────────────────────────────────────────────────────────

def _run_chain_for_date(db: Session, tran_date: str) -> None:
    """Bprocess + B Atten for a single date. Each step commits internally and
    is idempotent (delete-then-rebuild). Prepare runs once per pass (caller)."""
    bprocess_core(db, tran_date)
    b_atten_core(db, tran_date)


def run_once(
    tenant: str,
    branch_id: int,
    company_id: int = 2,
    since: date | None = None,
) -> dict:
    """One pipeline pass for the given tenant/branch.

    Normal mode (since=None): detects new punches via the bio_att_id high-water
    mark, processes the affected dates (+ prior day each), then advances the
    high-water mark.

    Seeding mode (since set): ignores the high-water mark and processes every
    distinct date on/after `since`. Use for a bounded first run.
    """
    db = make_session(tenant)
    # Dedicated session for the named lock: GET_LOCK is connection-scoped.
    lock_db = make_session(tenant)
    locked = False
    hb_stop = threading.Event()
    hb_thread = None
    try:
        try:
            lock_db.execute(_SET_LOCK_WAIT_TIMEOUT_SQL, {"w": LOCK_WAIT_TIMEOUT_SEC})
        except Exception:
            log.warning("Could not set wait_timeout on lock connection (continuing).")

        got = lock_db.execute(_GET_LOCK_SQL, {"name": _LOCK_NAME}).scalar()
        if not got:
            log.info(
                "Another bio_att_auto run holds the lock — skipping this tick "
                "(tenant=%s branch=%s).", tenant, branch_id,
            )
            return {"skipped": True, "reason": "locked"}
        locked = True

        hb_thread = threading.Thread(
            target=_lock_heartbeat, args=(lock_db, hb_stop),
            name="bio_att_lock_hb", daemon=True,
        )
        hb_thread.start()

        ensure_bio_tables(db)
        db.execute(_CREATE_STATE_SQL)
        db.commit()
        _touch_last_run_at(db, branch_id)

        # Pull new device punches from punch_logs BEFORE change detection, so
        # freshly-arrived rows bump max(bio_att_id) and their dates process.
        punch_sync = sync_punch_logs(db)
        if punch_sync.get("error"):
            log.warning("punch_logs sync failed (continuing): %s", punch_sync["error"])
        elif punch_sync.get("inserted"):
            log.info("punch_logs sync: %d new punch(es) from %s",
                     punch_sync["inserted"], punch_sync["source"])

        current_max = _get_max_bio_att_id(db)
        if current_max is None:
            log.info("bio_attendance_table is empty for tenant=%s — nothing to do.", tenant)
            return {"skipped": True, "reason": "empty"}
        current_max = int(current_max)

        last_id = _get_last_bio_att_id(db, branch_id)

        if since is not None:
            dates = sorted(set(_get_dates_since(db, since)))
            log.info(
                "tenant=%s branch=%s: SEEDING from %s -> processing %d date(s): %s",
                tenant, branch_id, since.isoformat(), len(dates),
                [d.isoformat() for d in dates],
            )
        else:
            if should_skip(current_max, last_id):
                log.info(
                    "No new data for tenant=%s branch=%s (max=%s, last=%s) — skipping.",
                    tenant, branch_id, current_max, last_id,
                )
                return {"skipped": True, "max_id": current_max, "last_id": last_id}

            new_dates = _get_new_dates(db, last_id)
            dates = compute_dates_to_process(new_dates)
            log.info(
                "tenant=%s branch=%s: %d new-date(s) -> processing %d date(s): %s",
                tenant, branch_id, len(new_dates), len(dates),
                [d.isoformat() for d in dates],
            )

        # Run the table-global pre-steps ONCE for the whole pass. If they fail,
        # abort without advancing the high-water mark so everything retries.
        try:
            prepare_punches(db)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            log.error(
                "tenant=%s branch=%s: prepare FAILED — aborting tick, "
                "high-water left at %d (retry next tick)\n%s",
                tenant, branch_id, last_id, traceback.format_exc(),
            )
            return {
                "skipped": False,
                "max_id": current_max,
                "high_water": last_id,
                "processed": [],
                "failed": [d.isoformat() for d in dates],
            }

        processed: list[str] = []
        failed: list[str] = []
        for d in dates:
            tran_date = d.isoformat()
            try:
                _run_chain_for_date(db, tran_date)
                processed.append(tran_date)
                log.info("tenant=%s branch=%s: %s OK", tenant, branch_id, tran_date)
            except Exception:
                log.error(
                    "tenant=%s branch=%s: pipeline FAILED for %s\n%s",
                    tenant, branch_id, tran_date, traceback.format_exc(),
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                failed.append(tran_date)
                # The connection may be dead — replace the session so one
                # failure doesn't poison the remaining dates.
                try:
                    db.close()
                except Exception:
                    pass
                db = make_session(tenant)

        # Advance the high-water mark ONLY across dates that completed the
        # whole chain. If we cannot safely compute/store the new mark, leave it
        # untouched so nothing is skipped.
        new_high = current_max
        try:
            if failed:
                failed_min_new_id = _get_min_new_id_for_dates(db, last_id, failed)
                new_high = compute_high_water_mark(
                    current_max, last_id, failed_min_new_id
                )
            _set_last_bio_att_id(db, branch_id, new_high)
            log.info(
                "tenant=%s branch=%s: high-water -> %d (processed=%d, failed=%d)",
                tenant, branch_id, new_high, len(processed), len(failed),
            )
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
            log.error(
                "tenant=%s branch=%s: could NOT advance high-water mark safely "
                "(left at %d so failed/unprocessed dates retry next tick)\n%s",
                tenant, branch_id, last_id, traceback.format_exc(),
            )
            new_high = last_id
        return {
            "skipped": False,
            "max_id": current_max,
            "high_water": new_high,
            "processed": processed,
            "failed": failed,
        }
    finally:
        hb_stop.set()
        if hb_thread is not None:
            hb_thread.join(timeout=LOCK_HEARTBEAT_SEC + 5)
        if locked:
            try:
                lock_db.execute(_RELEASE_LOCK_SQL, {"name": _LOCK_NAME})
            except Exception:
                pass
        try:
            lock_db.close()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass


# ── Scheduler wiring ─────────────────────────────────────────────────────────

def _scheduled_job() -> None:
    """Job body invoked by APScheduler. Reads config fresh each run; never
    raises (logs instead)."""
    cfg = _read_config()
    if cfg is None:
        return
    try:
        run_once(cfg["tenant"], cfg["branch_id"], cfg["company_id"])
    except Exception:
        log.error("bio_att_auto scheduled run crashed:\n%s", traceback.format_exc())


def start_scheduler():
    """Create and start the APScheduler job if enabled. Idempotent."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cfg = _read_config()
    if cfg is None:
        return None

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except Exception as exc:
        import sys
        log.error(
            "Cannot import APScheduler with interpreter %s — automated "
            "bio-attendance pipeline cannot start. Real error: %r. Install it "
            "into THIS interpreter:  %s -m pip install -r requirements.txt",
            sys.executable, exc, sys.executable,
        )
        return None

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _scheduled_job,
        trigger=IntervalTrigger(minutes=cfg["interval_min"]),
        id="bio_att_auto",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        # Fire once right after startup instead of waiting a full interval.
        next_run_time=datetime.now(),
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "bio_att_auto scheduler started: tenant=%s branch=%s every %d min.",
        cfg["tenant"], cfg["branch_id"], cfg["interval_min"],
    )
    return scheduler


def stop_scheduler() -> None:
    """Shut the scheduler down (called on app shutdown)."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
            log.info("bio_att_auto scheduler stopped.")
        except Exception:
            log.warning("bio_att_auto scheduler shutdown error:\n%s", traceback.format_exc())
        finally:
            _scheduler = None


# ── CLI (manual one-shot run) ────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="One-shot automated bio-attendance pipeline run.")
    p.add_argument("--tenant", required=True, help="MySQL tenant/subdomain DB name")
    p.add_argument("--branch", required=True, type=int, help="branch_id")
    p.add_argument("--company_id", default=2, type=int)
    p.add_argument(
        "--since",
        default=None,
        help="YYYY-MM-DD: bounded first run — process every date on/after this "
             "date, then seed the high-water mark so later runs are incremental.",
    )
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = p.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    since = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            p.error(f"--since {args.since!r} is not a valid YYYY-MM-DD date")

    result = run_once(args.tenant, args.branch, args.company_id, since=since)
    log.info("run_once result: %s", result)


if __name__ == "__main__":
    main()
