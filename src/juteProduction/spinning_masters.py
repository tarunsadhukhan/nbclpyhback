"""Master CRUD for the Spinning / Doff feature.

Mirrors drawing_masters.py for structure, error-handling and the {"data": ...}
response wrapper:

- trolly_mst  (trolly master; busket_weight kept, aliased bucket_weight)

Machine standards/config (bobbin weight, spindles, speed) now live in the
time-versioned jute_prod_spng_target_map master (see spng_target_map.py); the old
jute_prod_spinning_machine_attr table and its CRUD were removed.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.spinning_query import get_trollies_query
from src.juteProduction.constants import (
    SPREADER_MACHINE_TYPE_NAME,
    DRAWING_MACHINE_TYPE_NAME,
    SPINNING_MACHINE_TYPE_NAME,
    WINDING_MACHINE_TYPE_NAME,
)


router = APIRouter()


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
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


# =============================================================================
# Trolly master (trolly_mst) — keep busket_weight column; alias bucket_weight.
# trolly_mst has no active column → hard delete.
# =============================================================================


class TrollyCreate(BaseModel):
    trolly_name: str
    trolly_weight: float = Field(ge=0)
    busket_weight: float = Field(default=0.0, ge=0)
    trolly_posting_code: Optional[str] = None
    branch_id: Optional[int] = None
    trolly_type: str = "T"  # 'T'=trolly, 'S'=spool (winding doff distinguishes them)
    machine_type_id: int  # required — production stage marker


class TrollyUpdate(BaseModel):
    trolly_name: Optional[str] = None
    trolly_weight: Optional[float] = Field(default=None, ge=0)
    busket_weight: Optional[float] = Field(default=None, ge=0)
    trolly_posting_code: Optional[str] = None
    branch_id: Optional[int] = None
    trolly_type: Optional[str] = None
    machine_type_id: Optional[int] = None


@router.get("/trolly_list")
def trolly_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return all trolly_mst rows for any machine type (machine_type_name=None); branch is
    optional. busket_weight is aliased to bucket_weight; machine_type_id/machine_type_name
    come from the LEFT JOIN on machine_type_mst."""
    _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        rows = db.execute(
            get_trollies_query(),
            {"branch_id": branch_id, "machine_type_name": None},
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            if row.get("trolly_weight") is not None:
                row["trolly_weight"] = float(row["trolly_weight"])
            if row.get("bucket_weight") is not None:
                row["bucket_weight"] = float(row["bucket_weight"])
            data.append(row)
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trolly_machine_types")
def trolly_machine_types(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Production machine types (4 stages) eligible for trolley tagging."""
    try:
        rows = db.execute(
            text(
                """
                SELECT machine_type_id, machine_type_name
                FROM machine_type_mst
                WHERE active = 1
                  AND machine_type_name IN (:t1, :t2, :t3, :t4)
                ORDER BY machine_type_name
                """
            ),
            {
                "t1": SPREADER_MACHINE_TYPE_NAME,
                "t2": DRAWING_MACHINE_TYPE_NAME,
                "t3": SPINNING_MACHINE_TYPE_NAME,
                "t4": WINDING_MACHINE_TYPE_NAME,
            },
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/trolly_create")
def trolly_create(
    body: TrollyCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        result = db.execute(
            text(
                """
                INSERT INTO trolly_mst
                    (trolly_name, trolly_weight, busket_weight, trolly_posting_code, branch_id, trolly_type, machine_type_id)
                VALUES
                    (:trolly_name, :trolly_weight, :busket_weight, :trolly_posting_code, :branch_id, :trolly_type, :machine_type_id)
                """
            ),
            {
                "trolly_name": body.trolly_name,
                "trolly_weight": float(body.trolly_weight),
                "busket_weight": float(body.busket_weight),
                "trolly_posting_code": body.trolly_posting_code,
                "branch_id": int(body.branch_id) if body.branch_id is not None else None,
                "trolly_type": (body.trolly_type or "T").upper()[:1],
                "machine_type_id": int(body.machine_type_id),
            },
        )
        db.commit()
        return {"data": {"trolly_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/trolly_edit/{trolly_id}")
def trolly_edit(
    trolly_id: int,
    body: TrollyUpdate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        existing = db.execute(
            text("SELECT trolly_id FROM trolly_mst WHERE trolly_id = :id"),
            {"id": trolly_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Trolly not found")

        fields = []
        params: dict = {"id": trolly_id}
        if body.trolly_name is not None:
            fields.append("trolly_name = :trolly_name")
            params["trolly_name"] = body.trolly_name
        if body.trolly_weight is not None:
            fields.append("trolly_weight = :trolly_weight")
            params["trolly_weight"] = float(body.trolly_weight)
        if body.busket_weight is not None:
            fields.append("busket_weight = :busket_weight")
            params["busket_weight"] = float(body.busket_weight)
        if body.trolly_posting_code is not None:
            fields.append("trolly_posting_code = :trolly_posting_code")
            params["trolly_posting_code"] = body.trolly_posting_code
        if body.branch_id is not None:
            fields.append("branch_id = :branch_id")
            params["branch_id"] = int(body.branch_id)
        if body.trolly_type is not None:
            fields.append("trolly_type = :trolly_type")
            params["trolly_type"] = (body.trolly_type or "T").upper()[:1]
        if body.machine_type_id is not None:
            fields.append("machine_type_id = :machine_type_id")
            params["machine_type_id"] = int(body.machine_type_id)
        if not fields:
            return {"data": {"message": "No fields to update"}}
        db.execute(
            text(
                f"UPDATE trolly_mst SET {', '.join(fields)} WHERE trolly_id = :id"
            ),
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


@router.delete("/trolly_delete/{trolly_id}")
def trolly_delete(
    trolly_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Hard delete — trolly_mst has no active column."""
    try:
        existing = db.execute(
            text("SELECT trolly_id FROM trolly_mst WHERE trolly_id = :id"),
            {"id": trolly_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Trolly not found")
        db.execute(
            text("DELETE FROM trolly_mst WHERE trolly_id = :id"),
            {"id": trolly_id},
        )
        db.commit()
        return {"data": {"message": "Deleted"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
