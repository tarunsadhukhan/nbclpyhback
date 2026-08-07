"""
Jute Quality Check API endpoints.
Provides endpoints for QC/material inspection of jute MR entries.
Only shows entries where qc_check IS NULL OR qc_check = 0 (pending QC).

Updated (2026-01-16): 
- Renamed from "Material Inspection" to "Jute Quality Check"
- Now uses jute_mr table instead of deleted jute_gate_entry table
- QC data stored directly in jute_mr_li table
- When QC is complete, set qc_check = 1 on jute_mr
- Moisture readings stored in jute_moisture_rdg table
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
from src.common.utils import now_ist
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_material_inspection_table_query,
    get_material_inspection_table_count_query,
    get_material_inspection_by_id_query,
    get_material_inspection_line_items_query,
    update_material_inspection_qc_complete,
    insert_jute_mr_li_query,
    insert_jute_moisture_rdg_query,
    get_jute_items_query,
    get_jute_qualities_by_item_query,
    get_mukam_list_query,
)
from src.juteProcurement._excel_utils import (
    parse_iso_date,
    build_excel_response,
    enforce_row_cap,
)
from src.models.jute import JuteMrLi, JuteMoistureRdg

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class MoistureReading(BaseModel):
    """Single moisture reading."""
    moisture_percentage: float


class MRLineItemCreate(BaseModel):
    """Model for updating a jute_mr_li record with QC data."""
    jute_mr_li_id: int  # Line item ID from jute_mr_li table
    jute_po_li_id: Optional[int] = None  # Reference to PO line item
    # Challan data (from supplier)
    challan_item_id: Optional[int] = None
    challan_quantity: Optional[float] = None
    challan_weight: Optional[float] = None
    # Actual data (received/QC verified)
    actual_item_id: Optional[int] = None
    actual_qty: Optional[float] = None
    actual_weight: Optional[float] = None
    # Moisture
    allowable_moisture: Optional[float] = None
    actual_moisture: Optional[str] = None  # Can be comma-separated values
    moisture_readings: List[MoistureReading] = []
    # Pricing and storage
    accepted_weight: Optional[float] = None
    rate: Optional[float] = None
    warehouse_id: Optional[int] = None
    marka: Optional[str] = None
    crop_year: Optional[int] = None
    remarks: Optional[str] = None


class MaterialInspectionCompleteRequest(BaseModel):
    """Request model for completing quality check on a jute MR."""
    jute_mr_id: int  # Now uses jute_mr_id instead of gate_entry_id
    # Header-level data
    branch_id: Optional[int] = None
    jute_gate_entry_date: Optional[str] = None
    in_time: Optional[str] = None
    out_date: Optional[str] = None
    out_time: Optional[str] = None
    challan_no: Optional[str] = None
    challan_date: Optional[str] = None
    challan_weight: Optional[float] = None
    vehicle_no: Optional[str] = None
    vehicle_type_id: Optional[int] = None
    driver_name: Optional[str] = None
    transporter: Optional[str] = None
    po_id: Optional[int] = None
    jute_uom: Optional[str] = None
    mukam_id: Optional[int] = None
    jute_supplier_id: Optional[int] = None
    party_id: Optional[int] = None
    gross_weight: Optional[float] = None
    tare_weight: Optional[float] = None
    net_weight: Optional[float] = None
    variable_shortage: Optional[float] = None
    marketing_slip: Optional[int] = None
    remarks: Optional[str] = None
    # Line items with QC data
    line_items: List[MRLineItemCreate] = []
    # Save without marking QC complete
    save_only: Optional[bool] = False
    # Explicit "the user removed every line" marker — distinguishes an intentional
    # empty set (reconcile deactivates all rows) from a legacy caller omitting
    # line_items (reconcile skipped)
    lines_cleared: Optional[bool] = False


class MoistureReadingsRequest(BaseModel):
    """Request model for saving moisture readings for a MR line item."""

    moisture_readings: List[float]


class MoistureReadingsResponse(BaseModel):
    """Response model after saving moisture readings."""

    average_moisture: float
    readings: List[float]


# =============================================================================
# ENDPOINTS
# =============================================================================

JUTE_INSPECTION_DOWNLOAD_COLUMNS = [
    ("Gate Entry No", "gate_entry_num"),
    ("Gate Entry Date", "jute_gate_entry_date"),
    ("Branch", "branch_name"),
    ("Mukam", "mukam"),
    ("Vehicle No", "vehicle_no"),
    ("Challan No", "challan_no"),
    ("Challan Weight", "challan_weight"),
    ("Gross Weight", "gross_weight"),
    ("Tare Weight", "tare_weight"),
    ("Net Weight", "net_weight"),
    ("Variable Shortage", "variable_shortage"),
    ("Supplier", "supplier_name"),
    ("Party", "party_name"),
    ("Status", "status"),
]


def _parse_inspection_branch_ids(q_branch_ids: str):
    if not q_branch_ids:
        return []
    try:
        return [int(bid.strip()) for bid in q_branch_ids.split(",") if bid.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_ids format")


def _build_inspection_params(co_id: int, q_search: str, branch_ids, date_from, date_to):
    search_param = f"%{q_search}%" if q_search else None
    base = {
        "co_id": co_id,
        "date_from": date_from,
        "date_to": date_to,
    }
    if search_param:
        base["search"] = search_param
    for i, bid in enumerate(branch_ids):
        base[f"branch_id_{i}"] = bid
    return base


@router.get("/get_inspection_table")
def get_material_inspection_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of jute MR entries pending quality check (qc_check IS NULL OR qc_check = 0).

    Updated 2026-01-16: Now uses jute_mr table instead of jute_gate_entry.

    Query params:
    - co_id: Company ID (required)
    - branch_ids: Comma-separated branch IDs (optional)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term
    - from_date / to_date: Optional ISO dates (YYYY-MM-DD) bounding jute_gate_entry_date
    """
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_ids = request.query_params.get("branch_ids", "").strip()
        q_page = request.query_params.get("page", "1")
        q_limit = request.query_params.get("limit", "10")
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        branch_ids = _parse_inspection_branch_ids(q_branch_ids)
        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        try:
            page = max(1, int(q_page))
            limit = min(100, max(1, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit
        base_params = _build_inspection_params(co_id, q_search, branch_ids, date_from, date_to)

        count_query = get_material_inspection_table_count_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        count_result = db.execute(count_query, base_params).fetchone()
        total = count_result.total if count_result else 0

        data_query = get_material_inspection_table_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        data_params = {**base_params, "limit": limit, "offset": offset}

        result = db.execute(data_query, data_params).fetchall()
        rows = [dict(r._mapping) for r in result]

        for row in rows:
            row["id"] = row.get("jute_mr_id")

        for row in rows:
            if row.get("jute_gate_entry_date"):
                dt = row["jute_gate_entry_date"]
                if isinstance(dt, (datetime, date)):
                    row["jute_gate_entry_date"] = str(dt) if isinstance(dt, date) else dt.isoformat()
            if row.get("updated_date_time"):
                dt = row["updated_date_time"]
                if isinstance(dt, datetime):
                    row["updated_date_time"] = dt.isoformat()

        return {
            "data": rows,
            "total": total,
            "page": page,
            "page_size": limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching material inspection table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download_inspection_table")
def download_material_inspection_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Download Material Inspection list as .xlsx with same filters."""
    try:
        q_co_id = request.query_params.get("co_id")
        q_branch_ids = request.query_params.get("branch_ids", "").strip()
        q_search = request.query_params.get("search", "").strip()
        q_from_date = (request.query_params.get("from_date") or "").strip()
        q_to_date = (request.query_params.get("to_date") or "").strip()

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        branch_ids = _parse_inspection_branch_ids(q_branch_ids)
        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        base_params = _build_inspection_params(co_id, q_search, branch_ids, date_from, date_to)

        count_query = get_material_inspection_table_count_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        count_result = db.execute(count_query, base_params).fetchone()
        total = int(count_result.total) if count_result and count_result.total else 0
        enforce_row_cap(total)

        rows = []
        if total > 0:
            data_query = get_material_inspection_table_query(
                co_id=co_id,
                branch_ids=branch_ids if branch_ids else None,
                search=q_search if q_search else None,
            )
            data_params = {**base_params, "limit": total, "offset": 0}
            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        return build_excel_response(
            rows=rows,
            columns=JUTE_INSPECTION_DOWNLOAD_COLUMNS,
            sheet_title="Material Inspection",
            filename_prefix="jute_material_inspection",
            from_date_str=q_from_date,
            to_date_str=q_to_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading Material Inspection table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_inspection_by_id")
def get_material_inspection_by_id(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute MR entry with line items for quality check.
    
    Updated 2026-01-16: Now uses jute_mr_id instead of gate_entry_id.
    
    Query params:
    - id: Jute MR ID (required) - using jute_mr_id
    """
    try:
        q_id = request.query_params.get("id")
        if not q_id:
            raise HTTPException(status_code=400, detail="id is required")
        
        try:
            jute_mr_id = int(q_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid id")

        # Get header data
        header_query = get_material_inspection_by_id_query()
        header_result = db.execute(header_query, {"jute_mr_id": jute_mr_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="Jute MR entry not found")

        header = dict(header_result._mapping)

        # Check if already QC complete
        if header.get("qc_check") == 1 or header.get("qc_check") == "1":
            raise HTTPException(status_code=400, detail="This entry has already completed QC")

        # Format dates
        for field in ["jute_gate_entry_date", "challan_date", "updated_date_time"]:
            if header.get(field):
                dt = header[field]
                if isinstance(dt, (datetime, date)):
                    header[field] = str(dt) if isinstance(dt, date) else dt.isoformat()

        # Get line items from jute_mr_li
        line_items_query = get_material_inspection_line_items_query()
        line_items_result = db.execute(line_items_query, {"jute_mr_id": jute_mr_id}).fetchall()
        line_items = [dict(r._mapping) for r in line_items_result]

        return {
            "header": header,
            "line_items": line_items,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching material inspection by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_inspection_setup")
def get_material_inspection_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get dropdown options for material inspection form.
    Returns jute items, qualities, mukams, and warehouses.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Get jute groups (subgroups)
        items_query = get_jute_items_query()
        items_result = db.execute(items_query, {"co_id": co_id}).fetchall()
        jute_groups = [dict(r._mapping) for r in items_result]

        # Get mukams
        mukam_query = get_mukam_list_query()
        mukam_result = db.execute(mukam_query).fetchall()
        mukams = [dict(r._mapping) for r in mukam_result]

        # Get warehouses
        warehouse_query = text("""
            SELECT warehouse_id, warehouse_name
            FROM ware_house_master
            WHERE co_id = :co_id AND (active = 1 OR active IS NULL)
            ORDER BY warehouse_name
        """)
        warehouse_result = db.execute(warehouse_query, {"co_id": co_id}).fetchall()
        warehouses = [dict(r._mapping) for r in warehouse_result]

        return {
            "jute_groups": jute_groups,
            "mukams": mukams,
            "warehouses": warehouses,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching material inspection setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_mr_line_item/{mr_li_id}")
def get_mr_line_item(
    mr_li_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single jute MR line item with its moisture readings.

    This is useful when viewing or editing moisture readings after MR creation.
    """
    try:
        mr_li: Optional[JuteMrLi] = (
            db.query(JuteMrLi)
            .filter(JuteMrLi.jute_mr_li_id == mr_li_id)
            .first()
        )
        if not mr_li:
            raise HTTPException(status_code=404, detail="MR line item not found")

        readings: List[JuteMoistureRdg] = (
            db.query(JuteMoistureRdg)
            .filter(JuteMoistureRdg.jute_mr_li_id == mr_li_id)
            .order_by(JuteMoistureRdg.jute_moisture_rdg_id)
            .all()
        )
        moisture_values = [
            float(r.moisture_percentage)
            for r in readings
            if r.moisture_percentage is not None
        ]

        average = sum(moisture_values) / len(moisture_values) if moisture_values else 0.0

        line_item = {
            "jute_mr_li_id": mr_li.jute_mr_li_id,
            "jute_mr_id": mr_li.jute_mr_id,
            "jute_po_li_id": mr_li.jute_po_li_id,
            "challan_item_id": mr_li.challan_item_id,
            "challan_quantity": mr_li.challan_quantity,
            "challan_weight": mr_li.challan_weight,
            "actual_item_id": mr_li.actual_item_id,
            "actual_qty": mr_li.actual_qty,
            "actual_weight": mr_li.actual_weight,
            "allowable_moisture": mr_li.allowable_moisture,
            "actual_moisture": mr_li.actual_moisture,
            "accepted_weight": mr_li.accepted_weight,
        }

        return {
            "line_item": line_item,
            "moisture_readings": moisture_values,
            "average_moisture": average,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching MR line item with moisture readings")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save_moisture_readings/{mr_li_id}", response_model=MoistureReadingsResponse)
def save_moisture_readings(
    mr_li_id: int,
    body: MoistureReadingsRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Save moisture readings for a jute MR line item.

    - Deletes existing readings for the MR line item
    - Inserts new readings
    - Calculates average moisture and updates jute_mr_li.actual_moisture
    - Recalculates accepted_weight using:
        if actual_moisture > allowable_moisture:
            accepted_weight = actual_weight - (actual_weight * (actual_moisture - allowable_moisture) / 100)
        else:
            accepted_weight = actual_weight
    """
    try:
        mr_li: Optional[JuteMrLi] = (
            db.query(JuteMrLi)
            .filter(JuteMrLi.jute_mr_li_id == mr_li_id)
            .first()
        )
        if not mr_li:
            raise HTTPException(status_code=404, detail="MR line item not found")

        # Clear existing readings
        db.query(JuteMoistureRdg).filter(
            JuteMoistureRdg.jute_mr_li_id == mr_li_id
        ).delete()

        readings = [float(r) for r in body.moisture_readings if r is not None]

        # Insert new readings
        for value in readings:
            db.add(
                JuteMoistureRdg(
                    jute_mr_li_id=mr_li_id,
                    moisture_percentage=value,
                )
            )

        # Calculate average moisture
        average = sum(readings) / len(readings) if readings else 0.0
        mr_li.actual_moisture = f"{average:.2f}"

        # Recalculate accepted_weight
        actual_weight = float(mr_li.actual_weight or 0.0)
        allowable_moisture = (
            float(mr_li.allowable_moisture)
            if mr_li.allowable_moisture is not None
            else None
        )

        accepted_weight = actual_weight
        if (
            readings
            and allowable_moisture is not None
            and average > allowable_moisture
            and actual_weight > 0
        ):
            deduction_percentage = average - allowable_moisture
            accepted_weight = actual_weight - (
                actual_weight * deduction_percentage / 100.0
            )

        mr_li.accepted_weight = accepted_weight

        db.commit()

        return MoistureReadingsResponse(
            average_moisture=average,
            readings=readings,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error saving moisture readings for MR line item")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_qualities_by_item/{item_id}")
def get_qualities_by_item(
    item_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get jute qualities for a specific jute item.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        qualities_query = get_jute_qualities_by_item_query()
        qualities_result = db.execute(qualities_query, {"item_id": item_id, "co_id": co_id}).fetchall()
        qualities = [dict(r._mapping) for r in qualities_result]

        return {
            "qualities": qualities,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching qualities by item")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete_inspection")
def complete_material_inspection(
    request: Request,
    body: MaterialInspectionCompleteRequest,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Complete quality check for a jute MR entry.
    Updates jute_mr_li records with QC data and sets qc_check = 1 on jute_mr.
    
    Updated 2026-01-16: 
    - Now uses jute_mr_id instead of gate_entry_id
    - jute_mr already exists, we just update line items and mark QC complete
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        jute_mr_id = body.jute_mr_id
        
        # Verify jute_mr exists and is not already QC complete
        header_query = get_material_inspection_by_id_query()
        header_result = db.execute(header_query, {"jute_mr_id": jute_mr_id}).fetchone()
        
        if not header_result:
            raise HTTPException(status_code=404, detail="Jute MR entry not found")

        header = dict(header_result._mapping)
        if header.get("qc_check") == 1 or header.get("qc_check") == "1":
            raise HTTPException(status_code=400, detail="This entry has already completed QC")

        # Get user info for audit
        user_id = token_data.get("user_id")
        now = now_ist()

        # Update jute_mr header fields if provided
        mr_updates = []
        mr_params = {"jute_mr_id": jute_mr_id, "updated_by": user_id, "updated_date_time": now}
        
        # All header fields that can be updated during QC Complete
        if body.branch_id is not None:
            mr_updates.append("branch_id = :branch_id")
            mr_params["branch_id"] = body.branch_id
        if body.jute_gate_entry_date is not None:
            mr_updates.append("jute_gate_entry_date = :jute_gate_entry_date")
            mr_params["jute_gate_entry_date"] = body.jute_gate_entry_date
        if body.in_time is not None:
            mr_updates.append("in_time = :in_time")
            mr_params["in_time"] = body.in_time
        if body.out_date is not None:
            mr_updates.append("out_date = :out_date")
            mr_params["out_date"] = body.out_date
        if body.out_time is not None:
            mr_updates.append("out_time = :out_time")
            mr_params["out_time"] = body.out_time
        if body.challan_no is not None:
            mr_updates.append("challan_no = :challan_no")
            mr_params["challan_no"] = body.challan_no
        if body.challan_date is not None:
            mr_updates.append("challan_date = :challan_date")
            mr_params["challan_date"] = body.challan_date
        if body.challan_weight is not None:
            mr_updates.append("challan_weight = :challan_weight")
            mr_params["challan_weight"] = body.challan_weight
        if body.vehicle_no is not None:
            mr_updates.append("vehicle_no = :vehicle_no")
            mr_params["vehicle_no"] = body.vehicle_no
        # Note: vehicle_type_id column doesn't exist in jute_mr table, skipping
        if body.driver_name is not None:
            mr_updates.append("driver_name = :driver_name")
            mr_params["driver_name"] = body.driver_name
        if body.transporter is not None:
            mr_updates.append("transporter = :transporter")
            mr_params["transporter"] = body.transporter
        if body.po_id is not None:
            mr_updates.append("po_id = :po_id")
            # 0 = explicit detach (FE sends 0 when the user cleared the PO; None
            # still means "not provided" for legacy callers)
            mr_params["po_id"] = body.po_id if body.po_id > 0 else None
        if body.jute_uom is not None:
            mr_updates.append("unit_conversion = :jute_uom")
            mr_params["jute_uom"] = body.jute_uom
        if body.mukam_id is not None:
            mr_updates.append("mukam_id = :mukam_id")
            mr_params["mukam_id"] = body.mukam_id
        if body.jute_supplier_id is not None:
            mr_updates.append("jute_supplier_id = :jute_supplier_id")
            mr_params["jute_supplier_id"] = body.jute_supplier_id
        if body.party_id is not None:
            mr_updates.append("party_id = :party_id")
            mr_params["party_id"] = body.party_id
        if body.gross_weight is not None:
            mr_updates.append("gross_weight = :gross_weight")
            mr_params["gross_weight"] = body.gross_weight
        if body.tare_weight is not None:
            mr_updates.append("tare_weight = :tare_weight")
            mr_params["tare_weight"] = body.tare_weight
        if body.net_weight is not None:
            mr_updates.append("net_weight = :net_weight")
            mr_params["net_weight"] = body.net_weight
        if body.variable_shortage is not None:
            mr_updates.append("variable_shortage = :variable_shortage")
            mr_params["variable_shortage"] = body.variable_shortage
        if body.marketing_slip is not None:
            mr_updates.append("marketing_slip = :marketing_slip")
            mr_params["marketing_slip"] = body.marketing_slip
        if body.remarks is not None:
            mr_updates.append("remarks = :remarks")
            mr_params["remarks"] = body.remarks
        
        if mr_updates:
            mr_updates.append("updated_by = :updated_by")
            mr_updates.append("updated_date_time = :updated_date_time")
            mr_update_sql = f"UPDATE jute_mr SET {', '.join(mr_updates)} WHERE jute_mr_id = :jute_mr_id"
            db.execute(text(mr_update_sql), mr_params)

        # Update jute_mr_li records with QC data
        moisture_insert_query = insert_jute_moisture_rdg_query()

        # ids of rows the payload kept (updated or inserted) — used to reconcile below
        kept_li_ids: list[int] = []

        for item in body.line_items:
            # Determine average moisture from readings or provided value
            avg_moisture: Optional[float] = None
            if item.moisture_readings:
                values = [
                    float(r.moisture_percentage)
                    for r in item.moisture_readings
                    if r.moisture_percentage is not None
                ]
                if values:
                    avg_moisture = sum(values) / len(values)
            elif item.actual_moisture:
                try:
                    avg_moisture = float(item.actual_moisture)
                except (TypeError, ValueError):
                    avg_moisture = None

            actual_moisture_str = f"{avg_moisture:.2f}" if avg_moisture is not None else item.actual_moisture

            # The QC edit page does not load persisted moisture readings, so a
            # re-save carries no moisture context; recomputing accepted_weight then
            # silently replaces a moisture-deducted value with the full actual
            # weight. Only rewrite accepted_weight when the payload actually
            # carries moisture info; otherwise COALESCE keeps the stored value.
            has_moisture_info = bool(item.moisture_readings) or bool(item.actual_moisture)

            # Calculate accepted weight using average moisture and allowable moisture
            actual_weight = float(item.actual_weight or 0.0)
            allowable_moisture = float(item.allowable_moisture) if item.allowable_moisture is not None else None

            accepted_weight = actual_weight
            if (
                avg_moisture is not None
                and allowable_moisture is not None
                and avg_moisture > allowable_moisture
                and actual_weight > 0
            ):
                deduction_percentage = avg_moisture - allowable_moisture
                accepted_weight = actual_weight - (actual_weight * deduction_percentage / 100.0)

            # Reconcile a client-sent "new" line (id 0/None) that actually duplicates an
            # existing PO-linked row. The FE PO auto-fill rebuilds line items with a null
            # PK (serialized as 0), so a PO re-fill / double-submit resends an already-saved
            # line as new and this loop would INSERT a duplicate jute_mr_li row. If a line
            # for this MR already exists for the same PO line, adopt its id and UPDATE it.
            # ponytail: match on jute_po_li_id only (unique per PO line); manual lines with
            # no PO link still INSERT. Add an item-based key only if manual dupes surface.
            if (not item.jute_mr_li_id or item.jute_mr_li_id <= 0) and item.jute_po_li_id:
                existing_li_id = db.execute(text("""
                    SELECT jute_mr_li_id FROM jute_mr_li
                    WHERE jute_mr_id = :jute_mr_id
                      AND jute_po_li_id = :jute_po_li_id
                      AND (active = 1 OR active IS NULL)
                    ORDER BY jute_mr_li_id
                    LIMIT 1
                """), {
                    "jute_mr_id": jute_mr_id,
                    "jute_po_li_id": item.jute_po_li_id,
                }).scalar()
                if existing_li_id:
                    item.jute_mr_li_id = existing_li_id

            # Check if this is a new line item (jute_mr_li_id = 0 or None) or existing
            if not item.jute_mr_li_id or item.jute_mr_li_id <= 0:
                # INSERT new line item
                insert_li_sql = text("""
                    INSERT INTO jute_mr_li (
                        jute_mr_id, jute_po_li_id,
                        challan_item_id, challan_quantity, challan_weight,
                        actual_item_id, actual_qty, actual_weight,
                        allowable_moisture, actual_moisture, accepted_weight,
                        rate, warehouse_id, marka, crop_year, remarks,
                        active, updated_date_time
                    ) VALUES (
                        :jute_mr_id, :jute_po_li_id,
                        :challan_item_id, :challan_quantity, :challan_weight,
                        :actual_item_id, :actual_qty, :actual_weight,
                        :allowable_moisture, :actual_moisture, :accepted_weight,
                        :rate, :warehouse_id, :marka, :crop_year, :remarks,
                        1, :updated_date_time
                    )
                """)
                
                result = db.execute(insert_li_sql, {
                    "jute_mr_id": jute_mr_id,
                    "jute_po_li_id": item.jute_po_li_id,
                    "challan_item_id": item.challan_item_id,
                    "challan_quantity": item.challan_quantity,
                    "challan_weight": item.challan_weight,
                    "actual_item_id": item.actual_item_id,
                    "actual_qty": item.actual_qty,
                    "actual_weight": item.actual_weight,
                    "allowable_moisture": item.allowable_moisture,
                    "actual_moisture": actual_moisture_str,
                    "accepted_weight": accepted_weight,
                    "rate": item.rate,
                    "warehouse_id": item.warehouse_id,
                    "marka": item.marka,
                    "crop_year": item.crop_year,
                    "remarks": item.remarks,
                    "updated_date_time": now,
                })
                
                # Get the newly inserted ID for moisture readings
                new_li_id = result.lastrowid
                if new_li_id:
                    kept_li_ids.append(int(new_li_id))

                # Insert moisture readings for new line item
                if item.moisture_readings and new_li_id:
                    for reading in item.moisture_readings:
                        db.execute(moisture_insert_query, {
                            "jute_mr_li_id": new_li_id,
                            "moisture_percentage": reading.moisture_percentage,
                        })
            else:
                kept_li_ids.append(int(item.jute_mr_li_id))
                # UPDATE existing line item (including challan fields)
                update_li_sql = text("""
                    UPDATE jute_mr_li
                    SET jute_po_li_id = COALESCE(:jute_po_li_id, jute_po_li_id),
                        challan_item_id = COALESCE(:challan_item_id, challan_item_id),
                        challan_quantity = COALESCE(:challan_quantity, challan_quantity),
                        challan_weight = COALESCE(:challan_weight, challan_weight),
                        actual_item_id = COALESCE(:actual_item_id, actual_item_id),
                        actual_qty = COALESCE(:actual_qty, actual_qty),
                        actual_weight = COALESCE(:actual_weight, actual_weight),
                        allowable_moisture = COALESCE(:allowable_moisture, allowable_moisture),
                        actual_moisture = COALESCE(:actual_moisture, actual_moisture),
                        accepted_weight = COALESCE(:accepted_weight, accepted_weight),
                        rate = COALESCE(:rate, rate),
                        warehouse_id = COALESCE(:warehouse_id, warehouse_id),
                        marka = COALESCE(:marka, marka),
                        crop_year = COALESCE(:crop_year, crop_year),
                        remarks = COALESCE(:remarks, remarks),
                        updated_date_time = :updated_date_time
                    WHERE jute_mr_li_id = :jute_mr_li_id
                      AND jute_mr_id = :jute_mr_id
                """)
                
                db.execute(update_li_sql, {
                    "jute_mr_li_id": item.jute_mr_li_id,
                    "jute_mr_id": jute_mr_id,
                    "jute_po_li_id": item.jute_po_li_id,
                    "challan_item_id": item.challan_item_id,
                    "challan_quantity": item.challan_quantity,
                    "challan_weight": item.challan_weight,
                    "actual_item_id": item.actual_item_id,
                    "actual_qty": item.actual_qty,
                    "actual_weight": item.actual_weight,
                    "allowable_moisture": item.allowable_moisture,
                    "actual_moisture": actual_moisture_str,
                    "accepted_weight": accepted_weight if has_moisture_info else None,
                    "rate": item.rate,
                    "warehouse_id": item.warehouse_id,
                    "marka": item.marka,
                    "crop_year": item.crop_year,
                    "remarks": item.remarks,
                    "updated_date_time": now,
                })

                # Delete existing moisture readings and insert new ones
                if item.moisture_readings:
                    db.execute(
                        text("DELETE FROM jute_moisture_rdg WHERE jute_mr_li_id = :jute_mr_li_id"),
                        {"jute_mr_li_id": item.jute_mr_li_id}
                    )
                    for reading in item.moisture_readings:
                        db.execute(moisture_insert_query, {
                            "jute_mr_li_id": item.jute_mr_li_id,
                            "moisture_percentage": reading.moisture_percentage,
                        })

        # Reconcile to payload: the FE sends the record's FULL line set, so any active
        # row it did not send was removed in the UI (or is a phantom from an older
        # client) — soft-deactivate it. An empty set only reconciles when the FE
        # explicitly marks lines_cleared, so a legacy/defective caller (line_items
        # defaults to []) can't wipe a record.
        if body.line_items or body.lines_cleared:
            deactivate_sql = (
                "UPDATE jute_mr_li SET active = 0, updated_date_time = :updated_date_time"
                " WHERE jute_mr_id = :jute_mr_id AND (active = 1 OR active IS NULL)"
            )
            deactivate_params: dict = {"jute_mr_id": jute_mr_id, "updated_date_time": now}
            if kept_li_ids:
                placeholders = ", ".join(f":keep_{i}" for i in range(len(kept_li_ids)))
                deactivate_sql += f" AND jute_mr_li_id NOT IN ({placeholders})"
                deactivate_params.update({f"keep_{i}": li_id for i, li_id in enumerate(kept_li_ids)})
            db.execute(text(deactivate_sql), deactivate_params)

        # Mark jute_mr as QC complete (unless save_only mode)
        if not body.save_only:
            complete_query = update_material_inspection_qc_complete()
            db.execute(complete_query, {
                "jute_mr_id": jute_mr_id,
                "updated_by": user_id,
                "updated_date_time": now,
            })

        db.commit()

        message = "Quality check data saved successfully" if body.save_only else "Quality check completed successfully"
        return {
            "success": True,
            "message": message,
            "jute_mr_id": jute_mr_id,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error completing quality check")
        raise HTTPException(status_code=500, detail=str(e))
