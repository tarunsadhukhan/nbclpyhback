"""Master CRUD for Drawing machine attributes (const_meter / mc_group / meter_wrap_limit)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import DEFAULT_METER_WRAP, DRAWING_MACHINE_TYPE_NAME
from src.juteProduction.drawing_query import get_drawing_machine_attr_list_query


router = APIRouter()


def _require_co_id(request: Request) -> int:
    raw = request.query_params.get("co_id")
    if not raw:
        raise HTTPException(status_code=400, detail="co_id is required")
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid co_id")


class DrawingMachineAttrCreate(BaseModel):
    co_id: int
    machine_id: int
    const_meter: float = Field(gt=0)
    mc_group: Optional[str] = None
    meter_wrap_limit: int = Field(default=DEFAULT_METER_WRAP, gt=0)
    active: int = 1


class DrawingMachineAttrUpdate(BaseModel):
    const_meter: Optional[float] = Field(default=None, gt=0)
    mc_group: Optional[str] = None
    meter_wrap_limit: Optional[int] = Field(default=None, gt=0)
    active: Optional[int] = None


@router.get("/drawing_machine_attr_list")
def drawing_machine_attr_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """ALL Drawing machines LEFT JOIN attr — rows with drawing_machine_attr_id IS NULL
    are unconfigured machines (used by the create dialog's machine dropdown)."""
    co_id = _require_co_id(request)
    try:
        rows = db.execute(
            get_drawing_machine_attr_list_query(),
            {"co_id": co_id, "drawing_type": DRAWING_MACHINE_TYPE_NAME},
        ).fetchall()
        data = []
        for r in rows:
            row = dict(r._mapping)
            if row.get("const_meter") is not None:
                row["const_meter"] = float(row["const_meter"])
            data.append(row)
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drawing_machine_attr_create")
def drawing_machine_attr_create(
    body: DrawingMachineAttrCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # Any row (active or not) blocks creation — matches the DB unique key;
        # re-activate a soft-deleted row via edit instead.
        dup = db.execute(
            text(
                "SELECT drawing_machine_attr_id FROM jute_prod_drawing_machine_attr "
                "WHERE co_id = :co_id AND machine_id = :machine_id"
            ),
            {"co_id": body.co_id, "machine_id": int(body.machine_id)},
        ).fetchone()
        if dup:
            raise HTTPException(
                status_code=400, detail="Drawing attributes already configured for this machine"
            )
        result = db.execute(
            text(
                """
                INSERT INTO jute_prod_drawing_machine_attr
                    (co_id, machine_id, const_meter, mc_group, meter_wrap_limit, active, updated_by)
                VALUES
                    (:co_id, :machine_id, :const_meter, :mc_group, :meter_wrap_limit, :active, :updated_by)
                """
            ),
            {
                "co_id": body.co_id,
                "machine_id": int(body.machine_id),
                "const_meter": float(body.const_meter),
                "mc_group": body.mc_group,
                "meter_wrap_limit": int(body.meter_wrap_limit),
                "active": int(body.active),
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"drawing_machine_attr_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/drawing_machine_attr_edit/{attr_id}")
def drawing_machine_attr_edit(
    attr_id: int,
    body: DrawingMachineAttrUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                "SELECT drawing_machine_attr_id FROM jute_prod_drawing_machine_attr "
                "WHERE drawing_machine_attr_id = :id AND co_id = :co_id"
            ),
            {"id": attr_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Drawing machine attributes not found")

        fields = []
        params: dict = {"id": attr_id}
        if body.const_meter is not None:
            fields.append("const_meter = :const_meter")
            params["const_meter"] = float(body.const_meter)
        if body.mc_group is not None:
            fields.append("mc_group = :mc_group")
            params["mc_group"] = body.mc_group
        if body.meter_wrap_limit is not None:
            fields.append("meter_wrap_limit = :meter_wrap_limit")
            params["meter_wrap_limit"] = int(body.meter_wrap_limit)
        if body.active is not None:
            fields.append("active = :active")
            params["active"] = int(body.active)
        if not fields:
            return {"data": {"message": "No fields to update"}}
        fields.append("updated_by = :updated_by")
        params["updated_by"] = token_data.get("user_id")
        db.execute(
            text(
                f"UPDATE jute_prod_drawing_machine_attr SET {', '.join(fields)} "
                "WHERE drawing_machine_attr_id = :id"
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
