"""Master CRUD for Jute Production: bins, item-maturity, spreader-machine-wt."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.authorization.utils import get_current_user_with_refresh
from src.config.db import get_tenant_db
from src.juteProduction.constants import SPREADER_MACHINE_TYPE_NAME
from src.juteProduction.query import (
    get_jute_items_query,
    get_spreader_machines_query,
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
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_id")


# =============================================================================
# Bin master
# =============================================================================


class SpreaderBinCreate(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    bin_code: str
    bin_no: Optional[int] = None
    description: Optional[str] = None
    active: int = 1


class SpreaderBinUpdate(BaseModel):
    branch_id: Optional[int] = None
    bin_code: Optional[str] = None
    bin_no: Optional[int] = None
    description: Optional[str] = None
    active: Optional[int] = None


@router.get("/bin_list")
def bin_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        rows = db.execute(
            text(
                """
                SELECT b.bin_id, b.co_id, b.branch_id, b.bin_code, b.bin_no, b.description, b.active,
                       br.branch_name
                FROM spreader_bin_mst b
                LEFT JOIN branch_mst br ON br.branch_id = b.branch_id
                WHERE b.co_id = :co_id
                ORDER BY b.bin_code
                """
            ),
            {"co_id": co_id},
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bin_create")
def bin_create(
    body: SpreaderBinCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        if body.branch_id is None:
            raise HTTPException(status_code=400, detail="branch_id is required")
        dup = db.execute(
            text("SELECT bin_id FROM spreader_bin_mst WHERE co_id = :co_id AND bin_code = :code"),
            {"co_id": body.co_id, "code": body.bin_code.strip()},
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="Bin code already exists for this company")

        user_id = token_data.get("user_id")
        result = db.execute(
            text(
                """
                INSERT INTO spreader_bin_mst
                    (co_id, branch_id, bin_code, bin_no, description, active, updated_by)
                VALUES
                    (:co_id, :branch_id, :bin_code, :bin_no, :description, :active, :updated_by)
                """
            ),
            {
                "co_id": body.co_id,
                "branch_id": body.branch_id,
                "bin_code": body.bin_code.strip(),
                "bin_no": body.bin_no,
                "description": body.description,
                "active": int(body.active),
                "updated_by": user_id,
            },
        )
        db.commit()
        return {"data": {"bin_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/bin_edit/{bin_id}")
def bin_edit(
    bin_id: int,
    body: SpreaderBinUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text("SELECT bin_id, co_id FROM spreader_bin_mst WHERE bin_id = :id AND co_id = :co_id"),
            {"id": bin_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Bin not found")

        fields = []
        params: dict = {"id": bin_id}
        for col in ["branch_id", "bin_code", "bin_no", "description", "active"]:
            val = getattr(body, col)
            if val is not None:
                fields.append(f"{col} = :{col}")
                params[col] = val if col != "bin_code" else val.strip()
        if not fields:
            return {"data": {"message": "No fields to update"}}
        params["updated_by"] = token_data.get("user_id")
        fields.append("updated_by = :updated_by")
        db.execute(text(f"UPDATE spreader_bin_mst SET {', '.join(fields)} WHERE bin_id = :id"), params)
        db.commit()
        return {"data": {"message": "Updated"}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Item maturity master
# =============================================================================


class ItemMaturityCreate(BaseModel):
    co_id: int
    item_id: int
    maturity_hours: int = Field(gt=0)
    active: int = 1


class ItemMaturityUpdate(BaseModel):
    maturity_hours: Optional[int] = Field(default=None, gt=0)
    active: Optional[int] = None


@router.get("/item_maturity_create_setup")
def item_maturity_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        items = [dict(r._mapping) for r in db.execute(get_jute_items_query(), {"co_id": co_id}).fetchall()]
        return {"data": {"items": items}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/item_maturity_list")
def item_maturity_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        rows = db.execute(
            text(
                """
                SELECT mm.item_maturity_id, mm.co_id, mm.item_id, mm.maturity_hours, mm.active,
                       i.item_name, i.item_code
                FROM item_maturity_mst mm
                LEFT JOIN item_mst i ON i.item_id = mm.item_id
                WHERE mm.co_id = :co_id
                ORDER BY i.item_name
                """
            ),
            {"co_id": co_id},
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/item_maturity_create")
def item_maturity_create(
    body: ItemMaturityCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        dup = db.execute(
            text(
                "SELECT item_maturity_id FROM item_maturity_mst WHERE co_id = :co_id AND item_id = :item_id"
            ),
            {"co_id": body.co_id, "item_id": int(body.item_id)},
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="Maturity is already configured for this item")

        result = db.execute(
            text(
                """
                INSERT INTO item_maturity_mst (co_id, item_id, maturity_hours, active, updated_by)
                VALUES (:co_id, :item_id, :maturity_hours, :active, :updated_by)
                """
            ),
            {
                "co_id": body.co_id,
                "item_id": int(body.item_id),
                "maturity_hours": int(body.maturity_hours),
                "active": int(body.active),
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"item_maturity_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/item_maturity_edit/{item_maturity_id}")
def item_maturity_edit(
    item_maturity_id: int,
    body: ItemMaturityUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                "SELECT item_maturity_id FROM item_maturity_mst WHERE item_maturity_id = :id AND co_id = :co_id"
            ),
            {"id": item_maturity_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Maturity row not found")

        fields = []
        params: dict = {"id": item_maturity_id}
        if body.maturity_hours is not None:
            fields.append("maturity_hours = :maturity_hours")
            params["maturity_hours"] = int(body.maturity_hours)
        if body.active is not None:
            fields.append("active = :active")
            params["active"] = int(body.active)
        if not fields:
            return {"data": {"message": "No fields to update"}}
        fields.append("updated_by = :updated_by")
        params["updated_by"] = token_data.get("user_id")
        db.execute(
            text(f"UPDATE item_maturity_mst SET {', '.join(fields)} WHERE item_maturity_id = :id"),
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


# =============================================================================
# Spreader Machine Weight master
# =============================================================================


class SpreaderMachineWtCreate(BaseModel):
    co_id: int
    branch_id: int
    machine_id: int
    wt_per_roll: float = Field(gt=0)
    active: int = 1


class SpreaderMachineWtUpdate(BaseModel):
    wt_per_roll: Optional[float] = Field(default=None, gt=0)
    active: Optional[int] = None


@router.get("/spreader_machine_wt_create_setup")
def spreader_machine_wt_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        machines = [
            dict(r._mapping)
            for r in db.execute(
                get_spreader_machines_query(),
                {
                    "co_id": co_id,
                    "spreader_type": SPREADER_MACHINE_TYPE_NAME,
                    "branch_id": branch_id,
                },
            ).fetchall()
        ]
        return {"data": {"machines": machines}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spreader_machine_wt_list")
def spreader_machine_wt_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    branch_id = _optional_branch_id(request)
    try:
        rows = db.execute(
            text(
                """
                SELECT sma.spreader_machine_attr_id, sma.co_id, sma.branch_id, sma.machine_id,
                       sma.wt_per_roll, sma.active,
                       m.machine_name, m.mech_code, b.branch_name
                FROM spreader_machine_attr sma
                LEFT JOIN machine_mst m ON m.machine_id = sma.machine_id
                LEFT JOIN branch_mst b ON b.branch_id = sma.branch_id
                WHERE sma.co_id = :co_id
                  AND (:branch_id IS NULL OR sma.branch_id = :branch_id)
                ORDER BY m.machine_name
                """
            ),
            {"co_id": co_id, "branch_id": branch_id},
        ).fetchall()
        return {"data": [dict(r._mapping) for r in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/spreader_machine_wt_create")
def spreader_machine_wt_create(
    body: SpreaderMachineWtCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        # A machine belongs to exactly one branch (machine -> dept -> branch); the row is
        # saved against that branch so it can never attach to another branch's machine.
        owner = db.execute(
            text(
                """
                SELECT d.branch_id, b.co_id
                FROM machine_mst m
                INNER JOIN dept_mst d ON d.dept_id = m.dept_id
                INNER JOIN branch_mst b ON b.branch_id = d.branch_id
                WHERE m.machine_id = :machine_id
                """
            ),
            {"machine_id": int(body.machine_id)},
        ).fetchone()
        if not owner:
            raise HTTPException(status_code=404, detail="Machine not found")
        if int(owner.branch_id) != int(body.branch_id):
            raise HTTPException(status_code=400, detail="Machine does not belong to the selected branch")
        dup = db.execute(
            text(
                "SELECT spreader_machine_attr_id FROM spreader_machine_attr WHERE machine_id = :machine_id"
            ),
            {"machine_id": int(body.machine_id)},
        ).fetchone()
        if dup:
            raise HTTPException(status_code=400, detail="Weight is already configured for this machine")
        result = db.execute(
            text(
                """
                INSERT INTO spreader_machine_attr (co_id, branch_id, machine_id, wt_per_roll, active, updated_by)
                VALUES (:co_id, :branch_id, :machine_id, :wt_per_roll, :active, :updated_by)
                """
            ),
            {
                "co_id": int(owner.co_id),
                "branch_id": int(body.branch_id),
                "machine_id": int(body.machine_id),
                "wt_per_roll": float(body.wt_per_roll),
                "active": int(body.active),
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"data": {"spreader_machine_attr_id": result.lastrowid}}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/spreader_machine_wt_edit/{attr_id}")
def spreader_machine_wt_edit(
    attr_id: int,
    body: SpreaderMachineWtUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    co_id = _require_co_id(request)
    try:
        existing = db.execute(
            text(
                "SELECT spreader_machine_attr_id FROM spreader_machine_attr WHERE spreader_machine_attr_id = :id AND co_id = :co_id"
            ),
            {"id": attr_id, "co_id": co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Spreader machine weight not found")

        fields = []
        params: dict = {"id": attr_id}
        if body.wt_per_roll is not None:
            fields.append("wt_per_roll = :wt_per_roll")
            params["wt_per_roll"] = float(body.wt_per_roll)
        if body.active is not None:
            fields.append("active = :active")
            params["active"] = int(body.active)
        if not fields:
            return {"data": {"message": "No fields to update"}}
        fields.append("updated_by = :updated_by")
        params["updated_by"] = token_data.get("user_id")
        db.execute(
            text(f"UPDATE spreader_machine_attr SET {', '.join(fields)} WHERE spreader_machine_attr_id = :id"),
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
