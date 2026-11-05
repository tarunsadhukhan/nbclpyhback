"""
NBJCL Reports (everything except the Attendance Register group, see nbjclAttendanceReports.py) — ports of the
legacy Smart-Eye Crystal reports of the report master ORPSMTEye (Reports/SmartEyeReportMulti/*_NJB.rpt).
Mounted at /api/hrmsReports/nbjcl/reports.

Each group module (wages, salary, loans, ...) exports REPORTS: {key: spec}; the registry key is
"<group>/<key>" = the menu path after hrms/nbjclreports/ (run_seed_nbjcl_reports_menu.py camel-cases the
legacy group and report names). A spec:

    title     report heading
    dates     "range" (From + To) | "single" (one date = legacy ToDate / FNE date) | "none"
    span      default period the page opens on: "day" | "fortnight" | "month"
    max_days  longest allowed From..To range (default 400)
    extra     None or {"label": str, "options": [{"value", "label"}] or callable(db, branch_id) -> that list}
    build     build(db, branch_id, from_date, to_date, extra) -> (columns, rows[, download])

columns / rows use nbjclAttendanceReports' _col / _num / _layout: rows are display-ordered dicts (group
headers, details, Total / Grand Total). `download` = {"filename", "text"} offers a file (pay slips for the
pre-printed stationery) beside the grid.
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.hrms.nbjclreports import loans, outsider, pf, registration, salary, wages

logger = logging.getLogger(__name__)
router = APIRouter()

REPORTS: dict[str, dict] = {
    f"{group}/{key}": spec
    for module, groups in ((wages, ("wages",)), (salary, ("salary",)), (loans, ("loanAndAdvances",)),
                           (outsider, ("outsider", "new")), (registration, ("registeration", "htmlReports")),
                           (pf, ("providentFundReports", "wagesMonthlyReports")))
    for group in groups
    for key, spec in module.REPORTS.get(group, {}).items()
}


def _date(value: str | None, name: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} is required (YYYY-MM-DD)")


@router.get("/nbjcl/reports/setup")
def nbjcl_reports_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
):
    """Every report of the registry with its date mode and filter options for the branch."""
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    out = {}
    for k, v in REPORTS.items():
        extra = v.get("extra")
        if extra:
            opts = extra["options"](db, int(branch_id)) if callable(extra["options"]) else extra["options"]
            extra = {"label": extra["label"], "options": [{"value": "", "label": "All"}, *opts]}
        out[k] = {"title": v["title"], "dates": v["dates"], "span": v.get("span", "fortnight"), "extra": extra}
    return {"data": out}


@router.get("/nbjcl/reports/{group}/{report}")
def nbjcl_report(
    group: str,
    report: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
    branch_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    extra: str = "",
):
    """One report as display-ordered rows plus its column list (and an optional file to download)."""
    spec = REPORTS.get(f"{group}/{report}")
    if not spec:
        raise HTTPException(status_code=404, detail=f"Unknown report '{group}/{report}'")
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    if spec["dates"] == "none":
        f = t = date.today()
    else:
        t = _date(date_to, "date_to")
        f = t if spec["dates"] == "single" else _date(date_from, "date_from")
    if f > t:
        raise HTTPException(status_code=400, detail="From date is after To date")
    if (t - f).days > spec.get("max_days", 400):
        raise HTTPException(status_code=400, detail=f"Select a period of {spec.get('max_days', 400)} days or less")
    try:
        built = spec["build"](db, int(branch_id), f, t, (extra or "").strip())
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surfaced to the page
        logger.error(f"NBJCL report {group}/{report} failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    columns, rows = built[0], built[1]
    fields = [c["field"] for c in columns]
    data = [{"id": i, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items() if k in fields}}
            for i, r in enumerate(rows)]
    return {"title": spec["title"], "columns": columns, "data": data, "total": len(data),
            "download": built[2] if len(built) > 2 else None}
