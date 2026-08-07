"""Spreader Roll Issue endpoints."""

from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.query import (
    get_available_weights_for_group_query,
    get_bins_with_stock_for_issue_query,
    get_group_details_for_issue_query,
    get_issues_by_date_query,
)


router = APIRouter()


class SpreaderIssueCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    issue_date: date
    issue_time: int = Field(ge=0, le=23)
    spell: str
    entry_id_grp: int
    wt_per_roll: float = Field(gt=0)
    no_of_rolls: int = Field(gt=0)
    breaker_inter_no: Optional[str] = None
    remarks: Optional[str] = None


class SpreaderIssueUpdate(BaseModel):
    issue_date: Optional[date] = None
    issue_time: Optional[int] = Field(default=None, ge=0, le=23)
    spell: Optional[str] = None
    no_of_rolls: Optional[int] = Field(default=None, gt=0)
    wt_per_roll: Optional[float] = Field(default=None, gt=0)
    breaker_inter_no: Optional[str] = None
    remarks: Optional[str] = None


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id")


def _optional_branch_id(request: Request) -> Optional[int]:
    raw = request.query_params.get("branch_id")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


def _combine(d: date, h: int) -> datetime:
    return datetime.combine(d, time(hour=int(h)))


def _current_stock_for_group_weight(
    db: Session, co_id: int, grp: int, wt_per_roll: float, exclude_issue_id: Optional[int] = None
) -> int:
    produced = db.execute(
        text(
            """
            SELECT COALESCE(SUM(no_of_rolls), 0)
            FROM spreader_prod_entry
            WHERE co_id = :co_id AND active = 1
              AND entry_id_grp = :grp AND wt_per_roll = :wt
            """
        ),
        {"co_id": co_id, "grp": grp, "wt": float(wt_per_roll)},
    ).scalar() or 0
    issued_sql = """
        SELECT COALESCE(SUM(no_of_rolls), 0)
        FROM spreader_roll_issue
        WHERE co_id = :co_id AND active = 1
          AND entry_id_grp = :grp AND wt_per_roll = :wt
    """
    params = {"co_id": co_id, "grp": grp, "wt": float(wt_per_roll)}
    if exclude_issue_id is not None:
        issued_sql += " AND spreader_roll_issue_id != :exclude_id"
        params["exclude_id"] = exclude_issue_id
    issued = db.execute(text(issued_sql), params).scalar() or 0
    return int(produced) - int(issued)


# =============================================================================
# Setup + lookups
# =============================================================================


@router.get("/issue_create_setup")
def issue_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        bins = [
            dict(r._mapping)
            for r in db.execute(
                get_bins_with_stock_for_issue_query(), {"co_id": co_id, "branch_id": branch_id}
            ).fetchall()
        ]
        for row in bins:
            if row.get("current_rolls") is not None:
                row["current_rolls"] = int(row["current_rolls"])
        return {
            "data": {
                "bins_with_stock": bins,
                "spells": [
                    {"code": "A1", "label": "A1 (06-10)"},
                    {"code": "B1", "label": "B1 (11-13)"},
                    {"code": "A2", "label": "A2 (14-16)"},
                    {"code": "B2", "label": "B2 (17-21)"},
                    {"code": "C", "label": "C (22-05)"},
                ],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/issue_available_weights")
def issue_available_weights(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    grp = request.query_params.get("entry_id_grp")
    if not grp:
        raise HTTPException(status_code=400, detail="entry_id_grp is required")
    try:
        grp_i = int(grp)
        rows = db.execute(
            get_available_weights_for_group_query(), {"co_id": co_id, "grp": grp_i}
        ).fetchall()
        weights = [
            {
                "wt_per_roll": float(r._mapping["wt_per_roll"]),
                "produced_rolls": int(r._mapping["produced_rolls"]),
                "issued_rolls": int(r._mapping["issued_rolls"]),
                "available_rolls": int(r._mapping["available_rolls"]),
            }
            for r in rows
        ]
        details = db.execute(
            get_group_details_for_issue_query(), {"co_id": co_id, "grp": grp_i}
        ).fetchone()
        details_dict = dict(details._mapping) if details else {}
        if details_dict.get("first_entry_dt") and isinstance(details_dict["first_entry_dt"], datetime):
            details_dict["first_entry_dt"] = details_dict["first_entry_dt"].isoformat()
        return {"data": {"weights": weights, "group": details_dict}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CRUD
# =============================================================================


@router.post("/issue_create")
def issue_create(
    body: SpreaderIssueCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # Validate group exists and capture earliest production datetime + bin/branch
        details = db.execute(
            get_group_details_for_issue_query(), {"co_id": body.co_id, "grp": int(body.entry_id_grp)}
        ).fetchone()
        if not details or details._mapping.get("first_entry_dt") is None:
            raise HTTPException(status_code=404, detail="Spreader production group not found")

        first_dt = details._mapping["first_entry_dt"]
        if not isinstance(first_dt, datetime):
            first_dt = datetime.fromisoformat(str(first_dt))

        issue_dt = _combine(body.issue_date, body.issue_time)
        if issue_dt < first_dt:
            raise HTTPException(
                status_code=400,
                detail=f"Issue datetime ({issue_dt:%Y-%m-%d %H:00}) precedes the group's first production ({first_dt:%Y-%m-%d %H:00}).",
            )

        current_stock = _current_stock_for_group_weight(
            db, body.co_id, int(body.entry_id_grp), float(body.wt_per_roll)
        )
        if int(body.no_of_rolls) > current_stock:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot issue {body.no_of_rolls} rolls — only {current_stock} available at {body.wt_per_roll} kg.",
            )

        user_id = token_data.get("user_id")
        # Issue branch must match its production group's branch (dept-derived);
        # the body value is only a fallback for groups with no derivable branch.
        derived_branch_id = details._mapping.get("branch_id")
        branch_id = derived_branch_id if derived_branch_id is not None else body.branch_id
        ins = text(
            """
            INSERT INTO spreader_roll_issue
                (co_id, branch_id, issue_date, issue_time, issue_dt, spell,
                 entry_id_grp, wt_per_roll, no_of_rolls, breaker_inter_no, remarks,
                 active, updated_by)
            VALUES
                (:co_id, :branch_id, :issue_date, :issue_time, :issue_dt, :spell,
                 :entry_id_grp, :wt_per_roll, :no_of_rolls, :breaker_inter_no, :remarks,
                 1, :updated_by)
            """
        )
        result = db.execute(
            ins,
            {
                "co_id": body.co_id,
                "branch_id": branch_id,
                "issue_date": body.issue_date,
                "issue_time": int(body.issue_time),
                "issue_dt": issue_dt,
                "spell": body.spell,
                "entry_id_grp": int(body.entry_id_grp),
                "wt_per_roll": float(body.wt_per_roll),
                "no_of_rolls": int(body.no_of_rolls),
                "breaker_inter_no": body.breaker_inter_no,
                "remarks": body.remarks,
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"spreader_roll_issue_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/issues_by_date")
def issues_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    d = request.query_params.get("issue_date")
    if not d:
        raise HTTPException(status_code=400, detail="issue_date is required")
    try:
        rows = db.execute(
            get_issues_by_date_query(),
            {"co_id": co_id, "d": date.fromisoformat(d), "branch_id": branch_id},
        ).fetchall()
        data = [dict(r._mapping) for r in rows]
        for row in data:
            if row.get("issued_kg") is not None:
                row["issued_kg"] = float(row["issued_kg"])
            if row.get("wt_per_roll") is not None:
                row["wt_per_roll"] = float(row["wt_per_roll"])
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/issue_edit/{issue_id}")
def issue_edit(
    issue_id: int,
    body: SpreaderIssueUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT spreader_roll_issue_id, entry_id_grp, issue_date, issue_time, wt_per_roll, no_of_rolls
                FROM spreader_roll_issue
                WHERE spreader_roll_issue_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": issue_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Spreader issue not found")

        new_wt = float(body.wt_per_roll) if body.wt_per_roll is not None else float(existing.wt_per_roll)
        new_rolls = int(body.no_of_rolls) if body.no_of_rolls is not None else int(existing.no_of_rolls)
        # Stock cap excluding the current row's contribution
        stock_excluding_self = _current_stock_for_group_weight(
            db, co_id, int(existing.entry_id_grp), new_wt, exclude_issue_id=issue_id
        )
        if new_rolls > stock_excluding_self:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot issue {new_rolls} rolls — only {stock_excluding_self} available at {new_wt} kg.",
            )

        fields = []
        params: dict = {"id": issue_id}
        new_date = body.issue_date or existing.issue_date
        new_time = body.issue_time if body.issue_time is not None else existing.issue_time
        if body.issue_date is not None or body.issue_time is not None:
            new_dt = _combine(new_date, int(new_time))
            fields += ["issue_date = :issue_date", "issue_time = :issue_time", "issue_dt = :issue_dt"]
            params["issue_date"] = new_date
            params["issue_time"] = int(new_time)
            params["issue_dt"] = new_dt
        if body.spell is not None:
            fields.append("spell = :spell")
            params["spell"] = body.spell
        if body.no_of_rolls is not None:
            fields.append("no_of_rolls = :no_of_rolls")
            params["no_of_rolls"] = new_rolls
        if body.wt_per_roll is not None:
            fields.append("wt_per_roll = :wt_per_roll")
            params["wt_per_roll"] = new_wt
        if body.breaker_inter_no is not None:
            fields.append("breaker_inter_no = :breaker_inter_no")
            params["breaker_inter_no"] = body.breaker_inter_no
        if body.remarks is not None:
            fields.append("remarks = :remarks")
            params["remarks"] = body.remarks

        if not fields:
            return {"data": {"message": "No fields to update"}}

        user_id = token_data.get("user_id")
        fields.append("updated_by = :updated_by")
        params["updated_by"] = user_id

        db.execute(
            text(f"UPDATE spreader_roll_issue SET {', '.join(fields)} WHERE spreader_roll_issue_id = :id"),
            params,
        )
        db.commit()
        return {"data": {"message": "Updated"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/issue_delete/{issue_id}")
def issue_delete(
    issue_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                """
                SELECT spreader_roll_issue_id FROM spreader_roll_issue
                WHERE spreader_roll_issue_id = :id AND co_id = :co_id AND active = 1
                """
            ),
            {"id": issue_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Spreader issue not found")
        db.execute(
            text("UPDATE spreader_roll_issue SET active = 0 WHERE spreader_roll_issue_id = :id"),
            {"id": issue_id},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
