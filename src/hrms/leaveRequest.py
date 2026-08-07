"""
HRMS Leave Request (transaction) API endpoints.

Backed by the `leave_transactions` table, which is scoped by `branch_id`
(the branch selected in the portal left sidebar). A leave request links an
employee (eb_id, validated by emp_code in hrms_ed_official_details *within the
selected branch*) to a leave type (hrms_leave_types_mst) for a date range.

Endpoints (registered under /api/hrms):
    GET  /leave_request_list
    GET  /leave_request_by_id/{id}
    POST /leave_request_create
    PUT  /leave_request_edit/{id}
    PUT  /leave_request_approve/{id}
    PUT  /leave_request_reject/{id}
    GET  /leave_ledger/{eb_no}
    GET  /worker_by_eb_no/{eb_no}
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.sql import text

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.common.utils import parse_json_body

router = APIRouter()

# Status workflow IDs (kept in sync with the frontend STATUS_LABELS map).
STATUS_PENDING_APPROVAL = 20
STATUS_APPROVED = 3
STATUS_REJECTED = 4
# Statuses from which a request can still be approved / rejected / edited.
PENDING_STATUSES = (1, 20, 21)
LOCKED_STATUSES = (STATUS_APPROVED, STATUS_REJECTED)


# ─── SQL Queries ────────────────────────────────────────────────────


def get_leave_request_list_query():
    return text("""
        SELECT
            lt.leave_transaction_id,
            lt.leave_transaction_id                          AS id,
            lt.eb_id,
            COALESCE(o.emp_code, '')                         AS eb_no,
            TRIM(CONCAT(
                COALESCE(p.first_name, ''), ' ',
                COALESCE(p.middle_name, ''), ' ',
                COALESCE(p.last_name, '')))                  AS worker_name,
            lt.leave_type_id,
            ltp.leave_type_description                       AS leave_type,
            lt.leave_from_date,
            lt.leave_to_date,
            lt.non_working_days,
            lt.leave_purpose,
            CAST(lt.status AS UNSIGNED)                      AS status
        FROM leave_transactions lt
        LEFT JOIN hrms_ed_official_details o   ON o.eb_id = lt.eb_id AND o.active = 1
        LEFT JOIN hrms_ed_personal_details  p  ON p.eb_id = lt.eb_id
        LEFT JOIN hrms_leave_types_mst      ltp ON ltp.leave_type_id = lt.leave_type_id
        WHERE lt.branch_id = :branch_id
          AND (:leave_type_id IS NULL OR lt.leave_type_id = :leave_type_id)
          AND (:eb_no IS NULL OR o.emp_code = :eb_no)
          AND (:status_id IS NULL OR CAST(lt.status AS UNSIGNED) = :status_id)
          AND (:search IS NULL
               OR p.first_name LIKE :search
               OR p.last_name LIKE :search
               OR o.emp_code LIKE :search)
        ORDER BY lt.leave_transaction_id DESC
    """)


def get_leave_request_by_id_query():
    return text("""
        SELECT
            lt.leave_transaction_id,
            lt.eb_id,
            lt.branch_id,
            COALESCE(o.emp_code, '')                         AS eb_no,
            TRIM(CONCAT(
                COALESCE(p.first_name, ''), ' ',
                COALESCE(p.middle_name, ''), ' ',
                COALESCE(p.last_name, '')))                  AS worker_name,
            lt.leave_type_id,
            ltp.leave_type_description                       AS leave_type,
            lt.leave_from_date,
            lt.leave_to_date,
            lt.non_working_days,
            lt.leave_purpose,
            CAST(lt.status AS UNSIGNED)                      AS status,
            lt.updated_by
        FROM leave_transactions lt
        LEFT JOIN hrms_ed_official_details o   ON o.eb_id = lt.eb_id AND o.active = 1
        LEFT JOIN hrms_ed_personal_details  p  ON p.eb_id = lt.eb_id
        LEFT JOIN hrms_leave_types_mst      ltp ON ltp.leave_type_id = lt.leave_type_id
        WHERE lt.leave_transaction_id = :leave_transaction_id
    """)


def get_worker_by_eb_no_query():
    """Validate an EB No (emp_code) against official details *within a branch*."""
    return text("""
        SELECT
            o.eb_id,
            o.emp_code                                       AS eb_no,
            o.branch_id,
            TRIM(CONCAT(
                COALESCE(p.first_name, ''), ' ',
                COALESCE(p.middle_name, ''), ' ',
                COALESCE(p.last_name, '')))                  AS worker_name,
            p.status_id                                      AS emp_status
        FROM hrms_ed_official_details o
        LEFT JOIN hrms_ed_personal_details p
               ON p.eb_id = o.eb_id AND (p.active = 1 OR p.active IS NULL)
        WHERE o.emp_code = :emp_code AND o.active = 1 AND o.branch_id = :branch_id
        LIMIT 1
    """)


def get_leave_taken_query():
    """Leaves already taken this month / year per leave type for an employee."""
    return text("""
        SELECT
            lt.leave_type_id,
            ltp.leave_type_description                       AS leave_type,
            SUM(CASE WHEN MONTH(lt.leave_from_date) = MONTH(CURDATE())
                      AND YEAR(lt.leave_from_date) = YEAR(CURDATE())
                     THEN DATEDIFF(lt.leave_to_date, lt.leave_from_date) + 1
                     ELSE 0 END)                             AS leaves_taken_this_month,
            SUM(CASE WHEN YEAR(lt.leave_from_date) = YEAR(CURDATE())
                     THEN DATEDIFF(lt.leave_to_date, lt.leave_from_date) + 1
                     ELSE 0 END)                             AS leaves_taken_this_year
        FROM leave_transactions lt
        LEFT JOIN hrms_leave_types_mst ltp ON ltp.leave_type_id = lt.leave_type_id
        WHERE lt.eb_id = :eb_id
          AND lt.branch_id = :branch_id
          AND CAST(lt.status AS UNSIGNED) NOT IN (4, 6)
        GROUP BY lt.leave_type_id, ltp.leave_type_description
    """)


# ─── Helpers ────────────────────────────────────────────────────────


def _require_branch_id(request: Request) -> int:
    branch_id = request.query_params.get("branch_id")
    if not branch_id:
        raise HTTPException(status_code=400, detail="branch_id is required")
    return int(branch_id)


def _next_leave_transaction_id(db: Session) -> int:
    row = db.execute(
        text("SELECT COALESCE(MAX(leave_transaction_id), 0) + 1 AS next_id FROM leave_transactions")
    ).fetchone()
    return int(row.next_id) if row else 1


# ─── Endpoints ──────────────────────────────────────────────────────


@router.get("/leave_request_list")
def leave_request_list(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated list of leave requests for the selected branch."""
    try:
        branch_id = _require_branch_id(request)

        search = request.query_params.get("search")
        leave_type_id = request.query_params.get("leave_type_id")
        eb_no = request.query_params.get("eb_no")
        status_id = request.query_params.get("status_id")

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))

        rows = db.execute(get_leave_request_list_query(), {
            "branch_id": branch_id,
            "search": f"%{search}%" if search else None,
            "leave_type_id": int(leave_type_id) if leave_type_id else None,
            "eb_no": eb_no or None,
            "status_id": int(status_id) if status_id else None,
        }).fetchall()

        all_data = [dict(r._mapping) for r in rows]
        total = len(all_data)
        start = (page - 1) * page_size
        paginated = all_data[start : start + page_size]

        return {"data": paginated, "total": total, "page": page, "page_size": page_size}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leave_request_by_id/{leave_transaction_id}")
def leave_request_by_id(
    leave_transaction_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Fetch a single leave request with header + approval flags."""
    try:
        row = db.execute(get_leave_request_by_id_query(), {
            "leave_transaction_id": leave_transaction_id,
        }).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Leave request not found")

        header = dict(row._mapping)
        status = int(header.get("status") or 0)
        can_act = status in PENDING_STATUSES

        return {
            "data": {
                "header": header,
                "lines": [],
                "approve_button": can_act,
                "reject_button": can_act,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/leave_request_create")
def leave_request_create(
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Create a new leave request under the selected branch."""
    try:
        body = parse_json_body(request)

        branch_id = body.get("branch_id")
        eb_id = body.get("eb_id")
        leave_type_id = body.get("leave_type_id")
        leave_from_date = body.get("leave_from_date")
        leave_to_date = body.get("leave_to_date")
        non_working_days = int(body.get("non_working_days") or 0)
        leave_purpose = body.get("leave_purpose")

        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")
        if not eb_id:
            raise HTTPException(status_code=400, detail="A valid employee (eb_id) is required")
        if not leave_type_id:
            raise HTTPException(status_code=400, detail="leave_type_id is required")
        if not leave_from_date or not leave_to_date:
            raise HTTPException(status_code=400, detail="From and To dates are required")
        if leave_from_date > leave_to_date:
            raise HTTPException(status_code=400, detail="From Date cannot be after To Date")

        # The employee must belong to the selected branch.
        belongs = db.execute(
            text("""SELECT 1 FROM hrms_ed_official_details
                    WHERE eb_id = :eb_id AND branch_id = :branch_id AND active = 1 LIMIT 1"""),
            {"eb_id": int(eb_id), "branch_id": int(branch_id)},
        ).fetchone()
        if not belongs:
            raise HTTPException(
                status_code=400,
                detail="Employee does not belong to the selected branch",
            )

        user_id = token_data.get("user_id") if token_data else None
        now = datetime.now()
        new_id = _next_leave_transaction_id(db)

        db.execute(text("""
            INSERT INTO leave_transactions
                (leave_transaction_id, branch_id, eb_id, leave_type_id,
                 leave_from_date, leave_to_date, non_working_days, leave_purpose,
                 remarks, status, updated_by, updated_date_time)
            VALUES
                (:leave_transaction_id, :branch_id, :eb_id, :leave_type_id,
                 :leave_from_date, :leave_to_date, :non_working_days, :leave_purpose,
                 :remarks, :status, :updated_by, :updated_date_time)
        """), {
            "leave_transaction_id": new_id,
            "branch_id": int(branch_id),
            "eb_id": int(eb_id),
            "leave_type_id": int(leave_type_id),
            "leave_from_date": leave_from_date,
            "leave_to_date": leave_to_date,
            "non_working_days": non_working_days,
            "leave_purpose": leave_purpose,
            "remarks": body.get("remarks"),
            "status": STATUS_PENDING_APPROVAL,
            "updated_by": user_id,
            "updated_date_time": now,
        })
        db.commit()

        return {
            "message": "Leave request created successfully",
            "leave_transaction_id": new_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/leave_request_edit/{leave_transaction_id}")
def leave_request_edit(
    leave_transaction_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update an existing (not yet approved/rejected) leave request."""
    try:
        body = parse_json_body(request)

        existing = db.execute(
            text("""SELECT CAST(status AS UNSIGNED) AS status
                    FROM leave_transactions WHERE leave_transaction_id = :id"""),
            {"id": leave_transaction_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Leave request not found")
        if int(existing.status or 0) in LOCKED_STATUSES:
            raise HTTPException(
                status_code=400,
                detail="An approved or rejected leave request cannot be edited",
            )

        leave_from_date = body.get("leave_from_date")
        leave_to_date = body.get("leave_to_date")
        if leave_from_date and leave_to_date and leave_from_date > leave_to_date:
            raise HTTPException(status_code=400, detail="From Date cannot be after To Date")

        user_id = token_data.get("user_id") if token_data else None

        db.execute(text("""
            UPDATE leave_transactions
            SET eb_id = :eb_id,
                leave_type_id = :leave_type_id,
                leave_from_date = :leave_from_date,
                leave_to_date = :leave_to_date,
                non_working_days = :non_working_days,
                leave_purpose = :leave_purpose,
                updated_by = :updated_by,
                updated_date_time = :updated_date_time
            WHERE leave_transaction_id = :id
        """), {
            "id": leave_transaction_id,
            "eb_id": int(body.get("eb_id")),
            "leave_type_id": int(body.get("leave_type_id")),
            "leave_from_date": leave_from_date,
            "leave_to_date": leave_to_date,
            "non_working_days": int(body.get("non_working_days") or 0),
            "leave_purpose": body.get("leave_purpose"),
            "updated_by": user_id,
            "updated_date_time": datetime.now(),
        })
        db.commit()

        return {
            "message": "Leave request updated successfully",
            "leave_transaction_id": leave_transaction_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


def _set_status(
    db: Session,
    leave_transaction_id: int,
    new_status: int,
    user_id,
    action: str,
):
    existing = db.execute(
        text("""SELECT CAST(status AS UNSIGNED) AS status
                FROM leave_transactions WHERE leave_transaction_id = :id"""),
        {"id": leave_transaction_id},
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Leave request not found")
    if int(existing.status or 0) in LOCKED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Leave request has already been {action}",
        )

    db.execute(text("""
        UPDATE leave_transactions
        SET status = :status, updated_by = :updated_by, updated_date_time = :updated_date_time
        WHERE leave_transaction_id = :id
    """), {
        "id": leave_transaction_id,
        "status": new_status,
        "updated_by": user_id,
        "updated_date_time": datetime.now(),
    })
    db.commit()


@router.put("/leave_request_approve/{leave_transaction_id}")
def leave_request_approve(
    leave_transaction_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Approve a leave request."""
    try:
        user_id = token_data.get("user_id") if token_data else None
        _set_status(db, leave_transaction_id, STATUS_APPROVED, user_id, "processed")
        return {"message": "Leave request approved", "leave_transaction_id": leave_transaction_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/leave_request_reject/{leave_transaction_id}")
def leave_request_reject(
    leave_transaction_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Reject a leave request."""
    try:
        user_id = token_data.get("user_id") if token_data else None
        _set_status(db, leave_transaction_id, STATUS_REJECTED, user_id, "processed")
        return {"message": "Leave request rejected", "leave_transaction_id": leave_transaction_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/worker_by_eb_no/{eb_no}")
def worker_by_eb_no(
    eb_no: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Validate an EB No against official details for the selected branch."""
    try:
        branch_id = _require_branch_id(request)
        row = db.execute(
            get_worker_by_eb_no_query(),
            {"emp_code": eb_no.strip(), "branch_id": branch_id},
        ).fetchone()
        if not row:
            raise HTTPException(
                status_code=404,
                detail="Employee not found for this EB No in the selected branch",
            )
        return {"data": dict(row._mapping)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/leave_ledger/{eb_no}")
def leave_ledger(
    eb_no: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Leave balance summary for an employee in the selected branch.

    There is no per-employee leave entitlement (max-per-month / per-year) table
    yet, so this returns leaves already *taken* this month / year per leave type
    with entitlement caps left at 0. Once an entitlement source exists, populate
    `max_leaves_per_month` / `leaves_per_year` here.
    """
    try:
        branch_id = _require_branch_id(request)

        worker = db.execute(
            get_worker_by_eb_no_query(),
            {"emp_code": eb_no.strip(), "branch_id": branch_id},
        ).fetchone()
        if not worker:
            return {"data": {"ledgers": []}}

        rows = db.execute(get_leave_taken_query(), {
            "eb_id": int(worker.eb_id),
            "branch_id": branch_id,
        }).fetchall()

        ledgers = [
            {
                "leave_type_id": int(r._mapping["leave_type_id"]),
                "leave_type": r._mapping["leave_type"],
                "max_leaves_per_month": 0,
                "leaves_per_year": 0,
                "leaves_taken_this_month": int(r._mapping["leaves_taken_this_month"] or 0),
                "leaves_taken_this_year": int(r._mapping["leaves_taken_this_year"] or 0),
            }
            for r in rows
        ]

        return {"data": {"ledgers": ledgers}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
