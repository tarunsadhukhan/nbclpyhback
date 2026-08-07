from fastapi import Depends, Request, HTTPException, APIRouter, Query, UploadFile, File, Form
from sqlalchemy.sql import text
from sqlalchemy import func
from sqlalchemy.orm import Session
from src.config.db import get_db_names, default_engine, get_tenant_db
from src.authorization.utils import verify_access_token
from src.common.ctrldskAdmin.schemas import MenuResponse, OrgCreate
from src.common.companyAdmin.models import ConMenuMaster, ConUserRoleMapping, ConRoleMenuMap, ConOrgMaster, CoMst, CoConfig, CurrencyMst
from src.common.companyAdmin.query import get_co_all_query, get_co_all_count_query, get_co_by_id_query, get_co_config_by_id_query
from src.common.companyAdmin.query import get_country_query, get_state_query
from src.common.companyAdmin.schemas import CoCreate, CoConfigCreate
from typing import Optional, List
from pydantic import BaseModel
import base64
import io
from PIL import Image


router = APIRouter()


class CoInvoiceTypeMapSavePayload(BaseModel):
    co_id: int
    invoice_type_ids: List[int] = []

@router.get("/get_co_data_all")
def getOrgsFull(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(1000, ge=1),
    search: Optional[str] = None,
    token_data: dict = Depends(verify_access_token),  # Use the new dependency  
    db: Session = Depends(get_tenant_db)
    ):
    offset = (page - 1) * limit
    try:

            query = get_co_all_query(search, offset, limit)
            # text(f"SELECT con_menu_id, con_menu_name, con_menu_parent_id FROM con_menu_master where active =1")
            params = {
                "search": f"%{search}%" if search else None,
                "limit": limit,
                "offset": offset
            }
            query_count = get_co_all_count_query(search)
            count_params = {
                "search": f"%{search}%" if search else None
            }
            coData = db.execute(query, params).fetchall()
            result_count = db.execute(query_count, count_params).scalar()
            # total_count = session.execute(count_query, count_params).scalar()
            result = [dict(r._mapping) for r in coData]
            return {
                "data": result,
                "total": result_count,
            }

    except HTTPException as he:
        print(f"HTTP Exception in get_users_tenant_admin: {str(he)}")
        raise
    except Exception as e:
        print(f"Unexpected error in get_users_tenant_admin: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/get_co_data_by_id/{co_id}")
def get_org_data_by_id(
    co_id: int,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    try:
            query = get_co_by_id_query(co_id)
            org_details = db.execute(query, {"co_id": co_id}).fetchone()
            countries   = db.execute(get_country_query()).fetchall()
            states      = db.execute(get_state_query()).fetchall()
            return {
                "data": dict(org_details._mapping),
                "countries":       [dict(c._mapping) for c in countries],
                "states":          [dict(s._mapping) for s in states],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_org_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")
    

@router.get("/create_co_setup_data")
def create_org_setup_data(
    # org_id: int,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    try:
        with Session(default_engine) as session:
            countries   = db.execute(get_country_query()).fetchall()
            states      = db.execute(get_state_query()).fetchall()
            return {
                "countries":       [dict(c._mapping) for c in countries],
                "states":          [dict(s._mapping) for s in states],
            }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_org_data_by_id: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Internal server error")
    
@router.post("/create_co_data")
def create_org_data(
    payload: CoCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Insert a new company record using the ORM model and return its id.
    """
    try:
        # Check for duplicate co_prefix
        existing = db.query(CoMst).filter(CoMst.co_prefix == payload.co_prefix).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Company prefix '{payload.co_prefix}' already exists")

        # Create the company using the tenant database
        new_company = CoMst(
            co_name=payload.co_name,
            co_prefix=payload.co_prefix,
            co_address1=payload.co_address1,
            co_address2=payload.co_address2,
            co_zipcode=payload.co_zipcode,
            country_id=payload.country_id,
            state_id=payload.state_id,
            city_id=None,
            co_logo=payload.co_logo,
            co_cin_no=payload.co_cin_no,
            co_email_id=payload.co_email_id,
            co_pan_no=payload.co_pan_no,
            s3bucket_name=payload.s3bucket_name,
            s3folder_name=payload.s3folder_name,
            tally_sync=payload.tally_sync,
            alert_email_id=payload.alert_email_id,
        )
        
        db.add(new_company)
        db.flush()  # Get the ID without committing
        db.commit()
        
        return {"message": "Company created successfully", "co_id": new_company.co_id}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in create_org_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
    
@router.post("/edit_co_data")
def edit_co_data(
    payload: CoCreate,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """
    Update an existing company record using the ORM model.
    co_id is expected to be included in the payload.
    """
    try:
        # Extract co_id from the payload
        co_id = payload.dict().get("co_id")
        if co_id is None:
            raise HTTPException(status_code=400, detail="co_id is required in the payload")
        
        # Convert co_id to int if it's a string
        if isinstance(co_id, str):
            try:
                co_id = int(co_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid co_id format")

        # Get the existing company
        company = db.query(CoMst).filter(CoMst.co_id == co_id).first()
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")

        # Update the company fields
        company.co_name = payload.co_name
        company.co_prefix = payload.co_prefix
        company.co_address1 = payload.co_address1
        company.co_address2 = payload.co_address2
        company.co_zipcode = payload.co_zipcode
        company.country_id = payload.country_id
        company.state_id = payload.state_id
        # co_logo managed by upload_co_logo / delete_co_logo endpoints — do not overwrite here
        company.co_cin_no = payload.co_cin_no
        company.co_email_id = payload.co_email_id
        company.co_pan_no = payload.co_pan_no
        company.s3bucket_name = payload.s3bucket_name
        company.s3folder_name = payload.s3folder_name
        company.tally_sync = payload.tally_sync
        company.alert_email_id = payload.alert_email_id
        
        # # Only update active status if it's provided in the payload
        # if payload.active is not None:
        #     company.active = payload.active
        db.commit()
        
        return {"message": "Company updated successfully", "co_id": company.co_id}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in edit_co_data: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
    

@router.get("/co_config")
def get_company_config(
    co_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(verify_access_token)
):
    """
    Get the configuration for a specific company, and all currencies.
    If config does not exist, return default values (0 for booleans, null for numbers).
    """
    try:
        query = get_co_config_by_id_query(co_id)
        result = db.execute(query, {"co_id": co_id}).fetchone()

        # Fetch all currencies
        currencies = db.query(CurrencyMst).all()
        currency_list = [
            {"currency_id": c.currency_id, "currency_prefix": c.currency_prefix}
            for c in currencies
        ]

        if not result:
            # No config: return default values
            config = {
                "co_id": co_id,
                "currency_id": None,
                "india_gst": 0,
                "india_tds": 0,
                "india_tcs": 0,
                "back_date_allowable": 0,
                "indent_required": 0,
                "po_required": 0,
                "material_inspection": 0,
                "quotation_required": 0,
                "do_required": 0,
                "gst_linked": 0
            }
        else:
            # Convert SQLAlchemy Row to dict and cast booleans to int (0/1)
            config = dict(result._mapping)
            for key in [
                "india_gst", "india_tds", "india_tcs", "back_date_allowable",
                "indent_required", "po_required", "material_inspection",
                "quotation_required", "do_required", "gst_linked"
            ]:
                config[key] = int(config[key]) if config[key] is not None else 0
            # For numbers, if None, keep as None

        return {"company": config, "currencies": currency_list}
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_company_config: {exc}")
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.post("/company_config")
def create_update_company_config(
    payload: CoConfigCreate,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(verify_access_token)
):
    """
    Create or update configuration for a specific company.
    """
    try:
        # Check if company exists
        company = db.query(CoMst).filter(CoMst.co_id == payload.co_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        # Use the query to check if config exists
        query = get_co_config_by_id_query(payload.co_id)
        result = db.execute(query, {"co_id": payload.co_id}).fetchone()

        if result:
            # Config exists, update using ORM
            config_obj = db.query(CoConfig).filter(CoConfig.co_id == payload.co_id).first()
            config_obj.currency_id = payload.currency_id
            config_obj.india_gst = payload.india_gst
            config_obj.india_tds = payload.india_tds
            config_obj.india_tcs = payload.india_tcs
            config_obj.back_date_allowable = payload.back_date_allowable
            config_obj.indent_required = payload.indent_required
            config_obj.po_required = payload.po_required
            config_obj.material_inspection = payload.material_inspection
            config_obj.quotation_required = payload.quotation_required
            config_obj.do_required = payload.do_required
            config_obj.gst_linked = payload.gst_linked
            config_obj.updated_by = token_data.get("user_id")
            config_obj.updated_date_time = func.current_timestamp()
            db.commit()
            return {"message": "Company configuration updated successfully", "co_id": payload.co_id}
        else:
            # Create new config
            new_config = CoConfig(
                co_id=payload.co_id,
                currency_id=payload.currency_id,
                india_gst=payload.india_gst,
                india_tds=payload.india_tds,
                india_tcs=payload.india_tcs,
                back_date_allowable=payload.back_date_allowable,
                indent_required=payload.indent_required,
                po_required=payload.po_required,
                material_inspection=payload.material_inspection,
                quotation_required=payload.quotation_required,
                do_required=payload.do_required,
                gst_linked=payload.gst_linked,
                updated_by=token_data.get("user_id"),
                updated_date_time=func.current_timestamp()
            )
            db.add(new_config)
            db.commit()
            return {"message": "Company configuration created successfully", "co_id": payload.co_id}

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in create_update_company_config: {exc}")
        import traceback; traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.get("/co_invoice_type_map_setup")
def get_co_invoice_type_map_setup(
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """Return companies, invoice types, and current company-to-invoice-type mappings."""
    try:
        companies = db.execute(
            text(
                """
                SELECT co_id, co_name
                FROM co_mst
                ORDER BY co_name
                """
            )
        ).fetchall()

        invoice_types = db.execute(
            text(
                """
                SELECT invoice_type_id, invoice_type_name
                FROM invoice_type_mst
                ORDER BY invoice_type_name
                """
            )
        ).fetchall()

        mappings = db.execute(
            text(
                """
                SELECT co_id, invoice_type_id
                FROM invoice_type_co_map
                WHERE active = 1
                """
            )
        ).fetchall()

        return {
            "companies": [dict(row._mapping) for row in companies],
            "invoice_types": [dict(row._mapping) for row in invoice_types],
            "mappings": [dict(row._mapping) for row in mappings],
        }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in get_co_invoice_type_map_setup: {exc}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.post("/co_invoice_type_map_save")
def save_co_invoice_type_map(
    payload: CoInvoiceTypeMapSavePayload,
    token_data: dict = Depends(verify_access_token),
    db: Session = Depends(get_tenant_db),
):
    """Replace company-to-invoice-type mappings for a given company."""
    try:
        co_exists = db.execute(
            text("SELECT co_id FROM co_mst WHERE co_id = :co_id LIMIT 1"),
            {"co_id": payload.co_id},
        ).fetchone()
        if not co_exists:
            raise HTTPException(status_code=404, detail="Company not found")

        valid_invoice_type_ids = db.execute(
            text(
                """
                SELECT invoice_type_id
                FROM invoice_type_mst
                """
            )
        ).fetchall()
        allowed_ids = {int(row._mapping["invoice_type_id"]) for row in valid_invoice_type_ids}

        requested_ids = sorted({int(value) for value in payload.invoice_type_ids})
        invalid_ids = [value for value in requested_ids if value not in allowed_ids]
        if invalid_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid invoice_type_ids: {invalid_ids}",
            )

        db.execute(
            text("DELETE FROM invoice_type_co_map WHERE co_id = :co_id"),
            {"co_id": payload.co_id},
        )

        user_id = token_data.get("user_id") if isinstance(token_data, dict) else None
        for invoice_type_id in requested_ids:
            db.execute(
                text(
                    """
                    INSERT INTO invoice_type_co_map (co_id, invoice_type_id, active, updated_by, updated_date_time)
                    VALUES (:co_id, :invoice_type_id, 1, :updated_by, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "co_id": payload.co_id,
                    "invoice_type_id": invoice_type_id,
                    "updated_by": user_id,
                },
            )

        db.commit()
        return {
            "message": "Invoice type mappings saved successfully",
            "co_id": payload.co_id,
            "invoice_type_ids": requested_ids,
        }
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Unexpected error in save_co_invoice_type_map: {exc}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


ALLOWED_LOGO_TYPES = {"image/jpeg", "image/png", "image/jpg"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_LOGO_DIMENSION = 500  # px — reject if either side exceeds this
TARGET_LOGO_DIMENSION = 300  # px — resize to fit within this


@router.post("/upload_co_logo")
def upload_co_logo(
    request: Request,
    file: UploadFile = File(...),
    co_id: int = Form(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(verify_access_token),
):
    try:
        # Validate content type
        if file.content_type not in ALLOWED_LOGO_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Only JPEG and PNG images are allowed",
            )

        # Read and validate file size
        file_bytes = file.file.read()
        if len(file_bytes) > MAX_LOGO_SIZE:
            raise HTTPException(
                status_code=400,
                detail="File size must not exceed 2 MB",
            )

        # Open and validate image dimensions
        img = Image.open(io.BytesIO(file_bytes))
        width, height = img.size
        if width > MAX_LOGO_DIMENSION or height > MAX_LOGO_DIMENSION:
            # Resize to fit within TARGET_LOGO_DIMENSION maintaining aspect ratio
            img.thumbnail((TARGET_LOGO_DIMENSION, TARGET_LOGO_DIMENSION), Image.LANCZOS)

        # Convert to base64 data URI
        buf = io.BytesIO()
        output_format = "PNG" if file.content_type == "image/png" else "JPEG"
        img.save(buf, format=output_format, quality=85)
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        mime = "image/png" if output_format == "PNG" else "image/jpeg"
        data_uri = f"data:{mime};base64,{encoded}"

        # Verify company exists and update
        company = db.query(CoMst).filter(CoMst.co_id == co_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        company.co_logo = data_uri
        db.commit()

        return {"message": "Logo uploaded successfully", "co_id": co_id, "co_logo": data_uri}

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.get("/get_co_logo/{co_id}")
def get_co_logo(
    co_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(verify_access_token),
):
    try:
        company = db.query(CoMst).filter(CoMst.co_id == co_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        return {"data": {"co_logo": company.co_logo}}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")


@router.delete("/delete_co_logo/{co_id}")
def delete_co_logo(
    co_id: int,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(verify_access_token),
):
    try:
        company = db.query(CoMst).filter(CoMst.co_id == co_id).first()
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        company.co_logo = None
        db.commit()

        return {"message": "Logo deleted successfully", "co_id": co_id}

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(exc)}")
