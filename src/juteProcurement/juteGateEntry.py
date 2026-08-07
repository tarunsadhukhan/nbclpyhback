"""
Jute Gate Entry API endpoints.
Provides CRUD operations for jute gate entry management.
"""

from fastapi import Depends, Request, HTTPException, APIRouter
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, datetime, time, timedelta
from src.common.utils import now_ist
import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.juteProcurement.query import (
    get_jute_gate_entry_table_query,
    get_jute_gate_entry_table_count_query,
    get_jute_gate_entry_by_id_query,
    get_jute_gate_entry_line_items_query,
    get_jute_gate_entry_moisture_readings_query,
    get_branches_query,
    get_mukam_list_query,
    get_all_suppliers_query,
    get_parties_by_supplier_query,
    get_jute_items_query,
    get_jute_qualities_by_item_query,
    get_open_jute_pos_query,
    get_jute_po_for_gate_entry_query,
    get_jute_po_line_items_for_gate_entry_query,
    get_vehicle_types_query,
)
from src.juteProcurement._excel_utils import (
    parse_iso_date,
    build_excel_response,
    enforce_row_cap,
)

logger = logging.getLogger(__name__)

router = APIRouter()


JUTE_GATE_ENTRY_DOWNLOAD_COLUMNS = [
    ("Gate Entry No", "gate_entry_num"),
    ("Gate Entry Date", "jute_gate_entry_date"),
    ("In Time", "in_time"),
    ("Out Date", "out_date"),
    ("Out Time", "out_time"),
    ("Challan No", "challan_no"),
    ("Challan Date", "challan_date"),
    ("Vehicle No", "vehicle_no"),
    ("Branch", "branch_name"),
    ("Challan Weight", "challan_weight"),
    ("Gross Weight", "gross_weight"),
    ("Tare Weight", "tare_weight"),
    ("Net Weight", "net_weight"),
    ("Status", "status"),
]


def _parse_branch_ids(q_branch_ids: str):
    if not q_branch_ids:
        return []
    try:
        return [int(b.strip()) for b in q_branch_ids.split(",") if b.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid branch_ids format")


def _build_gate_entry_params(co_id: int, q_search: str, branch_ids, date_from, date_to):
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


@router.get("/get_jute_gate_entry_table")
def get_jute_gate_entry_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get paginated list of Jute Gate Entries.

    Query params:
    - co_id: Company ID (required)
    - branch_ids: Comma-separated list of branch IDs to filter by (optional)
    - page: Page number (default: 1)
    - limit: Records per page (default: 10)
    - search: Search term for gate entry no, challan no, or vehicle no
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

        branch_ids = _parse_branch_ids(q_branch_ids)
        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        try:
            page = max(1, int(q_page))
            limit = min(100, max(1, int(q_limit)))
        except ValueError:
            page = 1
            limit = 10

        offset = (page - 1) * limit

        base_params = _build_gate_entry_params(co_id, q_search, branch_ids, date_from, date_to)

        count_query = get_jute_gate_entry_table_count_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        count_result = db.execute(count_query, base_params).fetchone()
        total = count_result.total if count_result else 0

        data_query = get_jute_gate_entry_table_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        data_params = {**base_params, "limit": limit, "offset": offset}

        result = db.execute(data_query, data_params).fetchall()
        rows = [dict(r._mapping) for r in result]

        for row in rows:
            if row.get("jute_gate_entry_date"):
                row["jute_gate_entry_date"] = str(row["jute_gate_entry_date"])
            if row.get("in_time"):
                row["in_time"] = str(row["in_time"])
            if row.get("out_date"):
                row["out_date"] = str(row["out_date"])
            if row.get("out_time"):
                row["out_time"] = str(row["out_time"])
            if row.get("challan_date"):
                row["challan_date"] = str(row["challan_date"])
            if row.get("updated_date_time"):
                row["updated_date_time"] = str(row["updated_date_time"])
            if row.get("jute_mr_id"):
                row["id"] = row["jute_mr_id"]

        return {
            "data": rows,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit if limit > 0 else 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching jute gate entry table")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/download_gate_entry_table")
def download_jute_gate_entry_table(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Download the Jute Gate Entry list as an .xlsx workbook with same filters."""
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

        branch_ids = _parse_branch_ids(q_branch_ids)
        date_from = parse_iso_date(q_from_date, "from_date")
        date_to = parse_iso_date(q_to_date, "to_date")

        base_params = _build_gate_entry_params(co_id, q_search, branch_ids, date_from, date_to)

        count_query = get_jute_gate_entry_table_count_query(
            co_id=co_id,
            branch_ids=branch_ids if branch_ids else None,
            search=q_search if q_search else None,
        )
        count_result = db.execute(count_query, base_params).fetchone()
        total = int(count_result.total) if count_result and count_result.total else 0
        enforce_row_cap(total)

        rows = []
        if total > 0:
            data_query = get_jute_gate_entry_table_query(
                co_id=co_id,
                branch_ids=branch_ids if branch_ids else None,
                search=q_search if q_search else None,
            )
            data_params = {**base_params, "limit": total, "offset": 0}
            result = db.execute(data_query, data_params).fetchall()
            rows = [dict(r._mapping) for r in result]

        return build_excel_response(
            rows=rows,
            columns=JUTE_GATE_ENTRY_DOWNLOAD_COLUMNS,
            sheet_title="Jute Gate Entry",
            filename_prefix="jute_gate_entry",
            from_date_str=q_from_date,
            to_date_str=q_to_date,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error downloading Jute Gate Entry table")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_jute_gate_entry_by_id/{jute_mr_id}")
def get_jute_gate_entry_by_id(
    jute_mr_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get a single Jute Gate Entry by ID with line items.
    
    Updated 2026-01-15: Now uses jute_mr table (merged gate entry + MR).
    The parameter is jute_mr_id which corresponds to the jute_mr table.
    """
    try:
        q_co_id = request.query_params.get("co_id")

        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        query = get_jute_gate_entry_by_id_query()
        result = db.execute(query, {"jute_mr_id": jute_mr_id, "co_id": co_id}).fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Jute Gate Entry not found")

        row = dict(result._mapping)

        # Format dates for JSON serialization
        for date_field in ["jute_gate_entry_date", "in_time", "out_date", "out_time", "challan_date", "updated_date_time"]:
            if row.get(date_field):
                row[date_field] = str(row[date_field])

        # Fetch line items
        line_items_query = get_jute_gate_entry_line_items_query()
        line_items_result = db.execute(line_items_query, {"jute_mr_id": jute_mr_id}).fetchall()
        line_items = [dict(r._mapping) for r in line_items_result]

        # Attach persisted moisture readings so QC edit re-saves carry moisture context
        readings_result = db.execute(
            get_jute_gate_entry_moisture_readings_query(), {"jute_mr_id": jute_mr_id}
        ).fetchall()
        readings_by_li: dict = {}
        for r in readings_result:
            m = r._mapping
            if m["moisture_percentage"] is not None:
                readings_by_li.setdefault(m["jute_mr_li_id"], []).append(
                    {"moisture_percentage": float(m["moisture_percentage"])}
                )
        for li in line_items:
            li["moisture_readings"] = readings_by_li.get(li["jute_mr_li_id"], [])

        row["line_items"] = line_items

        return row

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Jute Gate Entry by ID")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jute_gate_entry_create_setup")
def jute_gate_entry_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get setup data for creating a Jute Gate Entry.
    Returns branches, suppliers, mukams, jute items, open POs, and UOM options.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        # Get branches
        branches_result = db.execute(get_branches_query(), {"co_id": co_id}).fetchall()
        branches = [dict(r._mapping) for r in branches_result]

        # Get mukams
        mukams_result = db.execute(get_mukam_list_query(), {"co_id": co_id}).fetchall()
        mukams = [dict(r._mapping) for r in mukams_result]

        # Get all jute suppliers
        suppliers_result = db.execute(get_all_suppliers_query(), {"co_id": co_id}).fetchall()
        suppliers = [dict(r._mapping) for r in suppliers_result]

        # Get jute groups (subgroups with parent item_type_id = 2)
        jute_groups_result = db.execute(get_jute_items_query(), {"co_id": co_id}).fetchall()
        jute_groups = [dict(r._mapping) for r in jute_groups_result]

        # Get open Jute POs for selection
        open_pos_result = db.execute(get_open_jute_pos_query(), {"co_id": co_id}).fetchall()
        open_pos = []
        for r in open_pos_result:
            po = dict(r._mapping)
            if po.get("po_date"):
                po["po_date"] = str(po["po_date"])
            open_pos.append(po)

        # Static UOM options for jute
        uom_options = [
            {"value": "LOOSE", "label": "Loose"},
            {"value": "BALE", "label": "Bale"},
        ]

        # Get vehicle types
        vehicle_types_result = db.execute(get_vehicle_types_query(), {"co_id": co_id}).fetchall()
        vehicle_types = [dict(r._mapping) for r in vehicle_types_result]

        return {
            "branches": branches,
            "mukams": mukams,
            "suppliers": suppliers,
            "jute_groups": jute_groups,
            "open_pos": open_pos,
            "uom_options": uom_options,
            "vehicle_types": vehicle_types,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching Jute Gate Entry create setup")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_parties_by_supplier/{supplier_id}")
def get_parties_by_supplier(
    supplier_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get parties mapped to a jute supplier, scoped to the caller's company."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        try:
            co_id = int(q_co_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid co_id")

        query = get_parties_by_supplier_query()
        result = db.execute(
            query, {"supplier_id": supplier_id, "co_id": co_id}
        ).fetchall()
        parties = [dict(r._mapping) for r in result]

        return {"parties": parties}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching parties by supplier")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_qualities_by_item/{item_grp_id}")
def get_qualities_by_item(
    item_grp_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Get items (formerly qualities) for a specific jute subgroup."""
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)
        
        query = get_jute_qualities_by_item_query()
        result = db.execute(query, {"item_grp_id": item_grp_id}).fetchall()
        qualities = [dict(r._mapping) for r in result]
        
        return {"qualities": qualities}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching qualities by item")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/get_po_details/{po_id}")
def get_po_details(
    po_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Get PO details and line items for auto-filling gate entry.
    When a PO is selected, this returns the PO header and line items.
    """
    try:
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)
        
        # Get PO header
        po_query = get_jute_po_for_gate_entry_query()
        po_result = db.execute(po_query, {"po_id": po_id, "co_id": co_id}).fetchone()
        
        if not po_result:
            raise HTTPException(status_code=404, detail="PO not found")
        
        po_data = dict(po_result._mapping)
        if po_data.get("po_date"):
            po_data["po_date"] = str(po_data["po_date"])
        
        # Get PO line items
        line_items_query = get_jute_po_line_items_for_gate_entry_query()
        line_items_result = db.execute(line_items_query, {"po_id": po_id}).fetchall()
        po_data["line_items"] = [dict(r._mapping) for r in line_items_result]
        
        return po_data

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error fetching PO details for gate entry")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# JUTE GATE ENTRY CREATE / UPDATE MODELS
# =============================================================================

class JuteGateEntryLineItemCreate(BaseModel):
    """Schema for a Jute Gate Entry line item.
    
    Updated 2026-01-14: Added jute_po_li_id and allowable_moisture.
    When PO is referenced, jute_po_li_id links to PO line and allowable_moisture is copied from PO.
    When no PO, allowable_moisture can be manually entered.
    """
    jute_po_li_id: Optional[int] = None
    challan_item_id: Optional[int] = None
    challan_quantity: Optional[float] = None
    challan_weight: Optional[float] = None
    actual_item_id: Optional[int] = None
    actual_quantity: Optional[float] = None
    actual_weight: Optional[float] = None
    allowable_moisture: Optional[float] = None
    jute_uom: Optional[str] = None
    remarks: Optional[str] = None


class JuteGateEntryCreate(BaseModel):
    """Schema for creating a Jute Gate Entry."""
    co_id: int
    branch_id: int
    jute_gate_entry_date: date
    in_time: Optional[str] = None  # Time string like "14:30"
    challan_no: str
    challan_date: date
    challan_weight: float
    vehicle_no: str
    driver_name: str
    transporter: str
    po_id: Optional[int] = None
    jute_uom: Optional[str] = None  # LOOSE or BALE
    mukam_id: Optional[int] = None
    jute_supplier_id: Optional[int] = None
    party_id: Optional[int] = None
    gross_weight: float
    tare_weight: float
    net_weight: Optional[float] = None
    variable_shortage: Optional[float] = None
    vehicle_type_id: Optional[int] = None
    marketing_slip: Optional[int] = None  # 1 if checked, 0 if not
    remarks: Optional[str] = None
    line_items: Optional[List[JuteGateEntryLineItemCreate]] = None


class JuteGateEntryUpdate(BaseModel):
    """Schema for updating a Jute Gate Entry (including OUT action)."""
    branch_id: Optional[int] = None
    jute_gate_entry_date: Optional[date] = None
    in_time: Optional[str] = None
    out_date: Optional[date] = None
    out_time: Optional[str] = None  # Time string like "16:45"
    challan_no: Optional[str] = None
    challan_date: Optional[date] = None
    challan_weight: Optional[float] = None
    vehicle_no: Optional[str] = None
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
    vehicle_type_id: Optional[int] = None
    marketing_slip: Optional[int] = None  # 1 if checked, 0 if not
    remarks: Optional[str] = None
    line_items: Optional[List[JuteGateEntryLineItemCreate]] = None
    action: Optional[str] = None  # "OUT" to mark vehicle exit


# =============================================================================
# JUTE GATE ENTRY CREATE / UPDATE ENDPOINTS
# =============================================================================

# Gate Entry Status IDs
GATE_ENTRY_STATUS_IN = 1  # "IN" - Vehicle has entered
# Note: GATE_ENTRY_STATUS_OUT (5) is defined but no longer used.
# The out_time field presence determines if OUT is complete, not status_id.
# status_id remains in draft/IN state throughout the gate entry flow.
GATE_ENTRY_STATUS_OUT = 5  # Reserved - not actively used for status changes


@router.post("/jute_gate_entry_create")
def jute_gate_entry_create(
    payload: JuteGateEntryCreate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Create a new Jute Gate Entry (IN action).
    
    Updated 2026-01-16: Gate Entry table was merged into jute_mr table.
    This endpoint now directly inserts into jute_mr with gate entry fields.
    Gate entry number is generated based on branch + financial year.
    """
    try:
        from src.models.jute import JuteMr, JuteMrLi
        
        user_id = token_data.get("user_id")
        
        # Calculate financial year from jute_gate_entry_date
        # Financial year: April 1 to March 31
        # Example: January 20, 2025 → FY 2024-2025, April 15, 2025 → FY 2025-2026
        entry_date = payload.jute_gate_entry_date
        if entry_date.month >= 4:
            fy_start_year = entry_date.year
            fy_end_year = entry_date.year + 1
        else:
            fy_start_year = entry_date.year - 1
            fy_end_year = entry_date.year
        
        # Financial year starts on April 1 and ends on March 31
        fy_start_date = date(fy_start_year, 4, 1)
        fy_end_date = date(fy_end_year, 3, 31)
        
        # Generate gate entry sequence (get max jute_gate_entry_no for branch + financial year and increment)
        # Now querying jute_mr table since gate entry was merged
        max_seq_result = db.execute(
            text("""
                SELECT COALESCE(MAX(jute_gate_entry_no), 0) + 1 AS next_seq 
                FROM jute_mr 
                WHERE branch_id = :branch_id 
                  AND jute_gate_entry_date >= :fy_start 
                  AND jute_gate_entry_date <= :fy_end
            """),
            {
                "branch_id": payload.branch_id,
                "fy_start": fy_start_date,
                "fy_end": fy_end_date
            }
        ).fetchone()
        next_gate_entry_no = max_seq_result.next_seq if max_seq_result else 1
        
        # Calculate weights:
        # net_weight = gross_weight - tare_weight
        # actual_weight = net_weight - variable_shortage
        net_weight = payload.gross_weight - payload.tare_weight
        variable_shortage = payload.variable_shortage if payload.variable_shortage is not None else 0
        actual_weight = net_weight - variable_shortage
        
        # Parse in_time
        in_time_dt = None
        if payload.in_time:
            try:
                time_parts = payload.in_time.split(":")
                in_time_dt = datetime.combine(
                    payload.jute_gate_entry_date,
                    time(int(time_parts[0]), int(time_parts[1]))
                )
            except (ValueError, IndexError):
                in_time_dt = now_ist()
        else:
            in_time_dt = now_ist()
        
        # Create jute_mr record (combined gate entry + MR)
        # At gate entry stage: gate entry fields are populated, MR fields (branch_mr_no, jute_mr_date) are null
        jute_mr = JuteMr(
            branch_id=payload.branch_id,
            # Gate entry identification
            jute_gate_entry_no=next_gate_entry_no,
            jute_gate_entry_date=payload.jute_gate_entry_date,
            # MR fields - will be set later during MR processing
            branch_mr_no=None,
            jute_mr_date=None,
            # PO reference
            po_id=payload.po_id,
            # Supplier/Party
            jute_supplier_id=payload.jute_supplier_id,
            party_id=str(payload.party_id) if payload.party_id else None,
            # Challan details
            challan_no=payload.challan_no,
            challan_date=payload.challan_date,
            challan_weight=payload.challan_weight,
            # Weight measurements
            gross_weight=payload.gross_weight,
            tare_weight=payload.tare_weight,
            net_weight=net_weight,
            variable_shortage=variable_shortage,
            actual_weight=actual_weight,
            # Vehicle and transport details
            vehicle_no=payload.vehicle_no,
            transporter=payload.transporter,
            driver_name=payload.driver_name,
            # Time tracking
            in_time=in_time_dt,
            out_date=None,
            out_time=None,
            # Location and unit
            mukam_id=payload.mukam_id,
            unit_conversion=payload.jute_uom,
            # QC and status
            qc_check=0,  # Not checked yet
            marketing_slip=payload.marketing_slip or 0,
            status_id=GATE_ENTRY_STATUS_IN,  # IN status = 1
            remarks=payload.remarks,
            # Audit
            updated_by=user_id,
            updated_date_time=now_ist(),
        )
        
        db.add(jute_mr)
        db.flush()  # Get the generated ID
        
        # Create line items (if any provided)
        total_actual_weight = 0.0
        for li in (payload.line_items or []):
            mr_line_item = JuteMrLi(
                jute_mr_id=jute_mr.jute_mr_id,
                jute_po_li_id=li.jute_po_li_id,
                # Challan details
                challan_item_id=li.challan_item_id,
                challan_quantity=li.challan_quantity,
                challan_weight=li.challan_weight,
                # Actual details
                actual_item_id=li.actual_item_id,
                actual_qty=li.actual_quantity,
                actual_weight=li.actual_weight,
                # Moisture
                allowable_moisture=li.allowable_moisture,
                # Status and audit
                remarks=li.remarks,
                active=1,
                updated_date_time=now_ist(),
            )
            db.add(mr_line_item)
            total_actual_weight += float(li.actual_weight or 0)
        
        # Update mr_weight with sum of line item weights (if any)
        if total_actual_weight > 0:
            jute_mr.mr_weight = total_actual_weight
        
        db.commit()
        
        return {
            "success": True,
            "message": "Jute Gate Entry created successfully",
            "jute_mr_id": jute_mr.jute_mr_id,
            "jute_gate_entry_no": next_gate_entry_no,
            "net_weight": net_weight,
            "actual_weight": actual_weight,
            "status": "IN",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error creating Jute Gate Entry")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/jute_gate_entry_update/{jute_mr_id}")
def jute_gate_entry_update(
    jute_mr_id: int,
    payload: JuteGateEntryUpdate,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """
    Update a Jute Gate Entry. Use action='OUT' to mark vehicle exit.
    
    Updated 2026-01-16: Gate Entry table was merged into jute_mr table.
    This endpoint now directly updates jute_mr.
    """
    try:
        from src.models.jute import JuteMr, JuteMrLi
        
        q_co_id = request.query_params.get("co_id")
        if not q_co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        
        co_id = int(q_co_id)
        user_id = token_data.get("user_id")
        
        # Get existing jute_mr record
        existing = db.execute(
            text("""
                SELECT jm.jute_mr_id, jm.status_id, jm.in_time, jm.jute_gate_entry_date, jm.qc_check
                FROM jute_mr jm
                INNER JOIN branch_mst bm ON bm.branch_id = jm.branch_id
                WHERE jm.jute_mr_id = :id AND bm.co_id = :co_id
            """),
            {"id": jute_mr_id, "co_id": co_id}
        ).fetchone()
        
        if not existing:
            raise HTTPException(status_code=404, detail="Jute Gate Entry not found")
        
        # QC checkpoint: tare_weight, variable_shortage, out_time require QC completion
        qc_complete = existing.qc_check == 1 if existing.qc_check is not None else False
        
        if not qc_complete:
            if payload.tare_weight is not None and payload.tare_weight > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Tare Weight cannot be entered until Quality Check (QC) is completed"
                )
            if payload.variable_shortage is not None and payload.variable_shortage > 0:
                raise HTTPException(
                    status_code=400,
                    detail="Variable Shortage cannot be entered until Quality Check (QC) is completed"
                )
            if payload.out_time is not None:
                raise HTTPException(
                    status_code=400,
                    detail="Out Time cannot be recorded until Quality Check (QC) is completed"
                )
        
        # Handle OUT action
        if payload.action and payload.action.upper() == "OUT":
            if not qc_complete:
                raise HTTPException(
                    status_code=400,
                    detail="Vehicle cannot be marked as OUT until Quality Check (QC) is completed"
                )
            if not payload.out_time:
                raise HTTPException(status_code=400, detail="out_time is required for OUT action")
            
            # Validate out_time > in_time
            out_date = payload.out_date or date.today()
            try:
                time_parts = payload.out_time.split(":")
                out_time_obj = time(int(time_parts[0]), int(time_parts[1]))
                out_time_dt = datetime.combine(out_date, out_time_obj)
            except (ValueError, IndexError):
                raise HTTPException(status_code=400, detail="Invalid out_time format. Use HH:MM")
            
            # Get in_time and entry_date for comparison
            in_time_raw = existing.in_time
            entry_date = existing.jute_gate_entry_date or date.today()
            
            # Convert in_time to datetime for comparison
            # MySQL TIME columns may return as timedelta, datetime.time, or string
            in_time_dt = None
            if in_time_raw:
                if isinstance(in_time_raw, timedelta):
                    # Convert timedelta to time (total_seconds -> hours, minutes)
                    total_secs = int(in_time_raw.total_seconds())
                    hours = total_secs // 3600
                    minutes = (total_secs % 3600) // 60
                    in_time_obj = time(hours % 24, minutes)
                    in_time_dt = datetime.combine(entry_date, in_time_obj)
                elif isinstance(in_time_raw, time):
                    in_time_dt = datetime.combine(entry_date, in_time_raw)
                elif isinstance(in_time_raw, datetime):
                    in_time_dt = in_time_raw
                elif isinstance(in_time_raw, str):
                    try:
                        parts = in_time_raw.split(":")
                        in_time_obj = time(int(parts[0]), int(parts[1]))
                        in_time_dt = datetime.combine(entry_date, in_time_obj)
                    except (ValueError, IndexError):
                        pass
            
            # Validate out datetime > in datetime
            if in_time_dt and out_time_dt <= in_time_dt:
                raise HTTPException(status_code=400, detail="Out date/time must be after In date/time")
            
            # Build dynamic update for OUT action - include all weight fields that may be provided
            out_update_fields = ["out_date = :out_date", "out_time = :out_time"]
            out_update_params = {
                "out_date": out_date,
                "out_time": out_time_dt,
                "user_id": user_id,
                "updated_dt": now_ist(),
                "id": jute_mr_id,
            }
            
            # Include weight fields if provided in payload
            if payload.gross_weight is not None:
                out_update_fields.append("gross_weight = :gross_weight")
                out_update_params["gross_weight"] = payload.gross_weight
            
            if payload.tare_weight is not None:
                out_update_fields.append("tare_weight = :tare_weight")
                out_update_params["tare_weight"] = payload.tare_weight
            
            if payload.net_weight is not None:
                out_update_fields.append("net_weight = :net_weight")
                out_update_params["net_weight"] = payload.net_weight
            
            if payload.variable_shortage is not None:
                out_update_fields.append("variable_shortage = :variable_shortage")
                out_update_params["variable_shortage"] = payload.variable_shortage
            
            if payload.challan_weight is not None:
                out_update_fields.append("challan_weight = :challan_weight")
                out_update_params["challan_weight"] = payload.challan_weight
            
            # Calculate actual_weight if net_weight and variable_shortage are provided
            if payload.net_weight is not None:
                actual_weight = payload.net_weight - (payload.variable_shortage or 0)
                out_update_fields.append("actual_weight = :actual_weight")
                out_update_params["actual_weight"] = actual_weight
            
            out_update_fields.append("updated_by = :user_id")
            out_update_fields.append("updated_date_time = :updated_dt")
            
            # Update out date/time and weight fields
            # Note: status_id is NOT changed here - it remains in draft until QC complete
            out_update_sql = f"UPDATE jute_mr SET {', '.join(out_update_fields)} WHERE jute_mr_id = :id"
            db.execute(text(out_update_sql), out_update_params)
            db.commit()
            
            return {
                "success": True,
                "message": "Vehicle marked as OUT successfully",
                "jute_mr_id": jute_mr_id,
                "out_time": out_time_dt.strftime("%H:%M") if out_time_dt else None,
            }
        
        # Regular update (not OUT action)
        update_fields = []
        update_params = {"id": jute_mr_id, "user_id": user_id, "updated_dt": now_ist()}
        
        if payload.branch_id is not None:
            update_fields.append("branch_id = :branch_id")
            update_params["branch_id"] = payload.branch_id
        
        if payload.jute_gate_entry_date is not None:
            update_fields.append("jute_gate_entry_date = :entry_date")
            update_params["entry_date"] = payload.jute_gate_entry_date
        
        if payload.in_time is not None:
            try:
                time_parts = payload.in_time.split(":")
                entry_date = payload.jute_gate_entry_date or existing.jute_gate_entry_date or date.today()
                in_time_dt = datetime.combine(
                    entry_date,
                    time(int(time_parts[0]), int(time_parts[1]))
                )
                update_fields.append("in_time = :in_time")
                update_params["in_time"] = in_time_dt
            except (ValueError, IndexError):
                pass
        
        if payload.challan_no is not None:
            update_fields.append("challan_no = :challan_no")
            update_params["challan_no"] = payload.challan_no
        
        if payload.challan_date is not None:
            update_fields.append("challan_date = :challan_date")
            update_params["challan_date"] = payload.challan_date
        
        if payload.challan_weight is not None:
            update_fields.append("challan_weight = :challan_weight")
            update_params["challan_weight"] = payload.challan_weight
        
        if payload.vehicle_no is not None:
            update_fields.append("vehicle_no = :vehicle_no")
            update_params["vehicle_no"] = payload.vehicle_no
        
        if payload.driver_name is not None:
            update_fields.append("driver_name = :driver_name")
            update_params["driver_name"] = payload.driver_name
        
        if payload.transporter is not None:
            update_fields.append("transporter = :transporter")
            update_params["transporter"] = payload.transporter
        
        if payload.po_id is not None:
            update_fields.append("po_id = :po_id")
            update_params["po_id"] = payload.po_id
        
        if payload.jute_uom is not None:
            update_fields.append("unit_conversion = :jute_uom")
            update_params["jute_uom"] = payload.jute_uom
        
        if payload.mukam_id is not None:
            update_fields.append("mukam_id = :mukam_id")
            update_params["mukam_id"] = payload.mukam_id
        
        if payload.jute_supplier_id is not None:
            update_fields.append("jute_supplier_id = :supplier_id")
            update_params["supplier_id"] = payload.jute_supplier_id
        
        if payload.party_id is not None:
            update_fields.append("party_id = :party_id")
            update_params["party_id"] = str(payload.party_id) if payload.party_id else None
        
        if payload.gross_weight is not None:
            update_fields.append("gross_weight = :gross_weight")
            update_params["gross_weight"] = payload.gross_weight
        
        if payload.tare_weight is not None:
            update_fields.append("tare_weight = :tare_weight")
            update_params["tare_weight"] = payload.tare_weight
        
        if payload.net_weight is not None:
            update_fields.append("net_weight = :net_weight")
            update_params["net_weight"] = payload.net_weight
        elif payload.gross_weight is not None and payload.tare_weight is not None:
            # Auto-calculate net_weight = gross - tare
            update_fields.append("net_weight = :net_weight")
            update_params["net_weight"] = payload.gross_weight - payload.tare_weight
        
        if payload.variable_shortage is not None:
            update_fields.append("variable_shortage = :variable_shortage")
            update_params["variable_shortage"] = payload.variable_shortage
            # Recalculate actual_weight = net_weight - variable_shortage
            if "net_weight" in update_params:
                net_wt = update_params["net_weight"]
            elif payload.gross_weight is not None and payload.tare_weight is not None:
                net_wt = payload.gross_weight - payload.tare_weight
            else:
                # Fetch existing net_weight from DB
                existing_wt = db.execute(
                    text("SELECT net_weight FROM jute_mr WHERE jute_mr_id = :id"),
                    {"id": jute_mr_id}
                ).fetchone()
                net_wt = existing_wt.net_weight if existing_wt and existing_wt.net_weight else 0
            update_fields.append("actual_weight = :actual_weight")
            update_params["actual_weight"] = net_wt - payload.variable_shortage
        
        if payload.vehicle_type_id is not None:
            update_fields.append("vehicle_type_id = :vehicle_type_id")
            update_params["vehicle_type_id"] = payload.vehicle_type_id
        
        if payload.marketing_slip is not None:
            update_fields.append("marketing_slip = :marketing_slip")
            update_params["marketing_slip"] = payload.marketing_slip
        
        if payload.remarks is not None:
            update_fields.append("remarks = :remarks")
            update_params["remarks"] = payload.remarks
        
        # Handle out_date and out_time for regular SAVE (not just OUT action)
        if payload.out_date is not None:
            update_fields.append("out_date = :out_date")
            update_params["out_date"] = payload.out_date
        
        if payload.out_time is not None:
            try:
                time_parts = payload.out_time.split(":")
                out_date = payload.out_date or existing.out_date or date.today()
                out_time_dt = datetime.combine(
                    out_date,
                    time(int(time_parts[0]), int(time_parts[1]))
                )
                update_fields.append("out_time = :out_time")
                update_params["out_time"] = out_time_dt
            except (ValueError, IndexError):
                pass
        
        update_fields.append("updated_by = :user_id")
        update_fields.append("updated_date_time = :updated_dt")
        
        if update_fields:
            update_sql = f"UPDATE jute_mr SET {', '.join(update_fields)} WHERE jute_mr_id = :id"
            db.execute(text(update_sql), update_params)
        
        # Update line items if provided
        if payload.line_items is not None:
            # Delete existing line items
            db.execute(
                text("DELETE FROM jute_mr_li WHERE jute_mr_id = :id"),
                {"id": jute_mr_id}
            )
            
            # Insert new line items
            total_actual_weight = 0.0
            for li in payload.line_items:
                mr_line_item = JuteMrLi(
                    jute_mr_id=jute_mr_id,
                    jute_po_li_id=li.jute_po_li_id,
                    challan_item_id=li.challan_item_id,
                    challan_quantity=li.challan_quantity,
                    challan_weight=li.challan_weight,
                    actual_item_id=li.actual_item_id,
                    actual_qty=li.actual_quantity,
                    actual_weight=li.actual_weight,
                    allowable_moisture=li.allowable_moisture,
                    remarks=li.remarks,
                    active=1,
                    updated_date_time=now_ist(),
                )
                db.add(mr_line_item)
                total_actual_weight += float(li.actual_weight or 0)
            
            # Update mr_weight with sum of line item weights
            if total_actual_weight > 0:
                db.execute(
                    text("UPDATE jute_mr SET mr_weight = :mr_weight WHERE jute_mr_id = :id"),
                    {"mr_weight": total_actual_weight, "id": jute_mr_id}
                )
        
        db.commit()
        
        return {
            "success": True,
            "message": "Jute Gate Entry updated successfully",
            "jute_mr_id": jute_mr_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Error updating Jute Gate Entry")
        raise HTTPException(status_code=500, detail=str(e))
