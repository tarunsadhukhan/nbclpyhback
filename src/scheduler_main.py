"""scheduler_main.py — Standalone bio-attendance scheduler service.

Runs the automated hourly bio-attendance pipeline (APScheduler) in its OWN
process, completely separate from the main API (src/main.py).

The pipeline builds ONLY bio_attendance_basic and bio_attendance_process from
the raw punches in bio_attendance_table — it never writes daily_attendance.

Why a separate process?
-----------------------
The pipeline does heavy SYNCHRONOUS work — row-by-row loops over thousands of
punch rows. Running it inside the main API process holds the GIL while it
works, freezing every API request until the run finishes. Hosting it here as a
separate OS process gives full isolation.

Config is read from env/database.env (loaded on import of the pipeline):
  BIO_ATT_AUTO_ENABLED, BIO_ATT_AUTO_TENANT, BIO_ATT_AUTO_BRANCH,
  BIO_ATT_AUTO_COMPANY_ID, BIO_ATT_AUTO_INTERVAL_MIN

Run it (separate terminal / service), single worker:
  uvicorn src.scheduler_main:app --host 0.0.0.0 --port 48480
or directly:
  python -m src.scheduler_main

IMPORTANT: run exactly ONE instance (single worker, no --reload in production).
The pipeline's MySQL named lock guards against overlap, but a single worker
keeps things simplest.
"""

import asyncio
import logging

from fastapi import FastAPI

from src.hrms.bio_att_auto_pipeline import (
    start_scheduler,
    stop_scheduler,
    _read_config,
    _scheduled_job,
)
from src.hrms import bio_att_auto_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scheduler_main")

app = FastAPI(title="Vowerp3 Bio-Attendance Scheduler")


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Scheduler service starting up...")
    try:
        scheduler = start_scheduler()
        if scheduler is None:
            logger.warning(
                "Scheduler did NOT start — BIO_ATT_AUTO_ENABLED is off or config "
                "is incomplete. Service is up but idle."
            )
    except Exception:
        logger.exception("Failed to start bio_att_auto scheduler")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Scheduler service shutting down...")
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Failed to stop bio_att_auto scheduler")


@app.get("/health")
async def health() -> dict:
    """Report whether the scheduler is running and its active config."""
    cfg = _read_config()
    running = bio_att_auto_pipeline._scheduler is not None
    return {
        "service": "bio_att_scheduler",
        "scheduler_running": running,
        "enabled": cfg is not None,
        "config": cfg,
    }


@app.post("/run-now")
async def run_now() -> dict:
    """Trigger one pipeline pass immediately, off the event loop."""
    cfg = _read_config()
    if cfg is None:
        return {"triggered": False, "reason": "disabled_or_misconfigured"}
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _scheduled_job)
    return {"triggered": True}


if __name__ == "__main__":
    import uvicorn

    # Single worker, no reload: exactly one scheduler instance.
    uvicorn.run("src.scheduler_main:app", host="0.0.0.0", port=48480, reload=False)
