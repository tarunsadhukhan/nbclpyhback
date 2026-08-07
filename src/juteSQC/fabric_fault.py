"""R-08-28 Fabric Fault SQC API endpoints (jute SQC module).

Weaving woven-cloth defect tally. ONE save = ONE inspected piece (one loom/cloth column):
a flat header (entry_date, spell, cloth quality, loom, date_of_weaving, remarks, inspector)
plus a FIXED 15-fault checklist of integer counts stored as a JSON-string array of 15 ints
(FABRIC_FAULT_TYPES order; most counts are 0). NO detail table. piece_total = sum of the 15
counts, computed at save.

DAY roll-up (server-computed in get_fabric_fault_by_date over all pieces for the date):
  N = pieces_inspected (count of piece records). For each fault index i:
    fault_total[i] = sum over pieces of fault_counts[i]
    fault_score[i] = fault_total[i] / N
  grand_total = sum of all fault_totals (= sum of piece_totals); grand_score = grand_total / N.
No std, no CV%, no correction — counting/scoring only.

Pickers reused (not re-implemented): cloth quality = JUTE CLOTH items (item_type_id=5,
get_beaming_cloth_items_query), loom = WEAVING machines (get_weaving_entry_machines_query,
de-duped by machine_id), spell = spells (get_beaming_spells_query, de-duped by spell_code).
The 15 fault types are a CONSTANT (no master). Portal persona: get_tenant_db +
get_current_user_with_refresh, {"data": ...} responses.
"""

from typing import List, Optional
import logging
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StrictInt
from sqlalchemy.orm import Session

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteSQC.constants import FABRIC_FAULT_TYPES, FABRIC_FAULT_COUNT
from src.juteSQC.query import (
    get_fabric_fault_table_query,
    get_fabric_fault_table_count_query,
    get_fabric_fault_by_date_query,
    get_fabric_fault_by_id_query,
    soft_delete_fabric_fault_query,
)
from src.juteProduction.constants import WEAVING_MACHINE_TYPE_NAME
from src.juteProduction.beaming_query import (
    get_beaming_cloth_items_query,
    get_beaming_spells_query,
)
from src.juteProduction.weaving_query import get_weaving_entry_machines_query
from src.models.jute import JuteSqcFabricFault

logger = logging.getLogger(__name__)

router = APIRouter()


def _parse_counts(raw) -> List[int]:
    """Parse a stored fault_counts JSON string into a list of 15 ints (defensive: pad/clip
    to FABRIC_FAULT_COUNT so a malformed legacy row never breaks the day roll-up)."""
    vals = json.loads(raw) if isinstance(raw, str) else (raw or [])
    out = []
    for i in range(FABRIC_FAULT_COUNT):
        try:
            out.append(int(vals[i]))
        except (IndexError, TypeError, ValueError):
            out.append(0)
    return out


class FabricFaultCreateRequest(BaseModel):
    co_id: int
    branch_id: Optional[int] = None
    entry_date: str
    spell_id: Optional[int] = None
    item_id: Optional[int] = None
    loom_id: Optional[int] = None
    date_of_weaving: Optional[str] = None
    # StrictInt rejects bool/float/numeric-string at the schema boundary (422) so
    # `true`->1 and "5"->5 coercions can't slip a non-integer count past the guard.
    fault_counts: List[StrictInt]
    remarks: Optional[str] = None
    inspector_name: Optional[str] = None


class FabricFaultDeleteRequest(BaseModel):
    fabric_fault_id: int
    co_id: int


@router.get("/fabric_fault_create_setup")
def fabric_fault_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Pickers for the Fabric Fault entry form: cloth qualities (jute cloth items), WEAVING
    looms (de-duped by machine_id), spells (de-duped by spell_code), and the fixed 15-name
    fault-type list."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        branch_id = request.query_params.get("branch_id")
        branch_id_int = int(branch_id) if branch_id else None

        cloth_rows = db.execute(
            get_beaming_cloth_items_query(),
            {"co_id": int(co_id)},
        ).fetchall()
        qualities = [
            {
                "item_id": m["item_id"],
                "item_code": m.get("item_code"),
                "item_name": m.get("item_name"),
            }
            for m in (dict(r._mapping) for r in cloth_rows)
        ]

        loom_rows = db.execute(
            get_weaving_entry_machines_query(),
            {"loom_type": WEAVING_MACHINE_TYPE_NAME, "branch_id": branch_id_int},
        ).fetchall()
        looms = []
        seen_mc = set()
        for r in loom_rows:
            m = dict(r._mapping)
            mid = m["machine_id"]
            if mid in seen_mc:  # dev3 has duplicate loom rows — de-dup by machine_id
                continue
            seen_mc.add(mid)
            looms.append(
                {
                    "machine_id": mid,
                    "machine_name": m.get("machine_name"),
                    "mech_code": m.get("mech_code"),
                }
            )

        spell_rows = db.execute(
            get_beaming_spells_query(),
            {"branch_id": branch_id_int},
        ).fetchall()
        spells = []
        seen_spell = set()
        for r in spell_rows:
            m = dict(r._mapping)
            code = m.get("spell_code")
            if code in seen_spell:  # branch fanout can repeat a spell_code — keep first
                continue
            seen_spell.add(code)
            spells.append({"spell_id": m["spell_id"], "spell_code": code})

        return {
            "data": {
                "qualities": qualities,
                "looms": looms,
                "spells": spells,
                "fault_types": list(FABRIC_FAULT_TYPES),
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric fault create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create_fabric_fault")
def create_fabric_fault(
    body: FabricFaultCreateRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save ONE inspected piece: the 15-fault checklist + header. piece_total = sum(15).
    Counts default to 0 (a clean piece), so validate >= 0 (NOT > 0)."""
    try:
        if len(body.fault_counts) != FABRIC_FAULT_COUNT:
            raise HTTPException(
                status_code=400,
                detail=f"Exactly {FABRIC_FAULT_COUNT} fault counts are required, got {len(body.fault_counts)}",
            )

        # StrictInt already guarantees each count is a plain int (no bool/float/str);
        # here we only enforce the non-negative business rule with a clear 400.
        for idx, c in enumerate(body.fault_counts):
            if c < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Fault count at index {idx} must be an integer >= 0",
                )

        piece_total = sum(body.fault_counts)

        record = JuteSqcFabricFault(
            co_id=body.co_id,
            branch_id=body.branch_id,
            entry_date=body.entry_date,
            spell_id=body.spell_id,
            item_id=body.item_id,
            loom_id=body.loom_id,
            date_of_weaving=body.date_of_weaving if body.date_of_weaving else None,
            fault_counts=json.dumps(body.fault_counts),
            calc_piece_total=piece_total,
            remarks=body.remarks,
            inspector_name=body.inspector_name,
            updated_by=token_data.get("user_id"),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        return {
            "message": "Fabric Fault QC log created successfully",
            "fabric_fault_id": record.fabric_fault_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating fabric fault QC log")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fabric_fault_by_date")
def get_fabric_fault_by_date(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """All inspected pieces for one (co_id, branch_id, entry_date) plus the server-computed
    DAY roll-up matrix: per-fault totals + scores, grand total + score, pieces inspected."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        entry_date = request.query_params.get("entry_date")
        if not entry_date:
            raise HTTPException(status_code=400, detail="entry_date is required")

        branch_id = request.query_params.get("branch_id")

        result = db.execute(
            get_fabric_fault_by_date_query(),
            {
                "co_id": int(co_id),
                "entry_date": entry_date,
                "branch_id": int(branch_id) if branch_id else None,
            },
        ).fetchall()

        pieces = []
        fault_totals = [0] * FABRIC_FAULT_COUNT
        for r in result:
            row = dict(r._mapping)
            counts = _parse_counts(row.get("fault_counts"))
            for i in range(FABRIC_FAULT_COUNT):
                fault_totals[i] += counts[i]
            piece_total = (
                int(row["calc_piece_total"])
                if row.get("calc_piece_total") is not None
                else sum(counts)
            )
            pieces.append(
                {
                    "fabric_fault_id": row.get("fabric_fault_id"),
                    "spell_id": row.get("spell_id"),
                    "spell_code": row.get("spell_code"),
                    "item_id": row.get("item_id"),
                    "item_name": row.get("item_name"),
                    "loom_id": row.get("loom_id"),
                    "loom_name": row.get("loom_name"),
                    "mech_code": row.get("mech_code"),
                    "date_of_weaving": str(row["date_of_weaving"])
                    if row.get("date_of_weaving") is not None
                    else None,
                    "remarks": row.get("remarks"),
                    "inspector_name": row.get("inspector_name"),
                    "fault_counts": counts,
                    "piece_total": piece_total,
                }
            )

        n = len(pieces)
        # fault_score[i] = fault_total[i] / N; grand_total = sum of all fault_totals
        # (== sum of piece_totals); grand_score = grand_total / N. Guard N > 0 (empty date).
        fault_scores = [round(t / n, 4) if n > 0 else None for t in fault_totals]
        grand_total = sum(fault_totals)
        grand_score = round(grand_total / n, 4) if n > 0 else None

        return {
            "data": {
                "pieces": pieces,
                "fault_types": list(FABRIC_FAULT_TYPES),
                "fault_totals": fault_totals,
                "fault_scores": fault_scores,
                "grand_total": grand_total,
                "grand_score": grand_score,
                "pieces_inspected": n,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric fault by date")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_fabric_fault_table")
def get_fabric_fault_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Paginated history of inspected pieces for a company (entry_date, cloth, loom, spell,
    piece_total)."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        page = max(1, int(request.query_params.get("page", "1")))
        limit = max(1, min(100, int(request.query_params.get("limit", "10"))))
        offset = (page - 1) * limit
        search = request.query_params.get("search")

        params = {"co_id": int(co_id), "limit": limit, "offset": offset}
        if search:
            params["search"] = f"%{search}%"

        count_row = db.execute(
            get_fabric_fault_table_count_query(search=search), params
        ).fetchone()
        total = count_row.total if count_row else 0

        result = db.execute(
            get_fabric_fault_table_query(search=search), params
        ).fetchall()
        rows = [dict(r._mapping) for r in result]

        return {"data": rows, "total": total, "page": page, "page_size": limit}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching fabric fault table")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/delete_fabric_fault")
def delete_fabric_fault(
    body: FabricFaultDeleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Soft-delete (active=0) one inspected piece, scoped by co_id."""
    try:
        existing = db.execute(
            get_fabric_fault_by_id_query(),
            {"fabric_fault_id": body.fabric_fault_id, "co_id": body.co_id},
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Fabric Fault piece not found")

        db.execute(
            soft_delete_fabric_fault_query(),
            {
                "fabric_fault_id": body.fabric_fault_id,
                "co_id": body.co_id,
                "updated_by": token_data.get("user_id"),
            },
        )
        db.commit()
        return {"message": "Fabric Fault QC log deleted successfully"}

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error deleting fabric fault QC log")
        raise HTTPException(status_code=500, detail=str(e))
