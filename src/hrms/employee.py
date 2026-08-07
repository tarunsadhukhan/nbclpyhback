"""HRMS Employee endpoints — list, detail, create, section-save, setup, photo."""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.models.hrms import (
    HrmsEdPersonalDetails,
    HrmsEdContactDetails,
    HrmsEdAddressDetails,
    HrmsEdOfficialDetails,
    HrmsEdBankDetails,
    HrmsEdPf,
    HrmsEdEsi,
    HrmsExperienceDetails,
    HrmsEdResignDetails,
)
from .query import (
    get_employee_list,
    get_employee_list_count,
    get_employee_personal_by_id,
    get_employee_contact_by_eb_id,
    get_employee_address_by_eb_id,
    get_employee_official_by_eb_id,
    get_employee_bank_by_eb_id,
    get_employee_pf_by_eb_id,
    get_employee_esi_by_eb_id,
    get_employee_experience_by_eb_id,
    get_employee_create_setup,
    get_designations_by_branch,
    get_designations_by_sub_dept,
    get_reporting_employees,
    get_employee_photo_by_eb_id,
    upsert_employee_photo,
    delete_employee_photo,
    get_employee_by_emp_code,
    check_emp_code_duplicate,
    get_active_pay_scheme_dropdown,
    get_employee_payscheme_by_eb_id,
    get_employee_structure_by_eb_id,
    get_pay_scheme_details_by_scheme_id,
)
from .schemas import SectionSaveRequest
from .constants import EMPLOYEE_SECTIONS, EMPLOYEE_LIFECYCLE_STATUS, RESIGN_DETAIL_STATUSES
from sqlalchemy import inspect as sa_inspect, String as SAString
from src.common.utils import parse_json_body

router = APIRouter()


def _sanitize_empty_values(model_cls, data: dict) -> dict:
    """Convert empty-string values to None for non-string columns.

    MySQL rejects '' for Integer, BigInteger, Date, Float, DECIMAL, etc.
    Only string columns (String, Text) can legitimately hold ''.
    """
    non_string_cols = {
        col.key
        for col in sa_inspect(model_cls).columns
        if not isinstance(col.type, SAString)
    }
    for key in non_string_cols:
        if key in data and data[key] == "":
            data[key] = None
    return data


def _optional_auth(request: Request):
    """Dev bypass helper — mirrors yarnQuality.py pattern."""
    import os
    if os.getenv("BYPASS_AUTH") == "1" or os.getenv("ENV") == "development":
        return {"user_id": 0}
    return get_current_user_with_refresh(request, request)


# ─── Employee List ──────────────────────────────────────────────────

@router.get("/employee_list")
def employee_list(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        raw_branch_id = request.query_params.get("branch_id")
        if not raw_branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        try:
            branch_ids = [int(b) for b in raw_branch_id.split(",") if b.strip()]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid branch_id format")
        if not branch_ids:
            raise HTTPException(status_code=400, detail="branch_id is required")

        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        search_raw = request.query_params.get("search")
        search = f"%{search_raw}%" if search_raw else None
        status_id = request.query_params.get("status_id")
        sub_dept_id = request.query_params.get("sub_dept_id")
        is_active_raw = request.query_params.get("is_active")
        try:
            is_active = int(is_active_raw) if is_active_raw is not None else None
        except (ValueError, TypeError):
            is_active = None

        # Column-specific filters (from DataGrid column filter)
        def _like_param(key):
            v = request.query_params.get(key)
            return f"%{v}%" if v else None

        params = {
            "search": search,
            "status_id": int(status_id) if status_id else None,
            "sub_dept_id": int(sub_dept_id) if sub_dept_id else None,
            "is_active": is_active,
            "f_emp_code": _like_param("f_emp_code"),
            "f_full_name": _like_param("f_full_name"),
            "f_designation": _like_param("f_designation"),
            "f_branch": _like_param("f_branch"),
            "f_mobile": _like_param("f_mobile"),
            "f_email": _like_param("f_email"),
            "page_size": page_size,
            "offset": (page - 1) * page_size,
        }

        rows = db.execute(get_employee_list(branch_ids=branch_ids), params).fetchall()
        data = [dict(r._mapping) for r in rows]

        count_params = {k: v for k, v in params.items() if k not in ("page_size", "offset")}
        count_row = db.execute(get_employee_list_count(branch_ids=branch_ids), count_params).fetchone()
        total = count_row._mapping["total"] if count_row else 0

        return {
            "data": data,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee By ID (all sections) ─────────────────────────────────

@router.get("/employee_by_id/{eb_id}")
def employee_by_id(
    eb_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        params = {"eb_id": eb_id, "branch_id": int(branch_id)}

        personal = db.execute(get_employee_personal_by_id(), params).fetchone()
        if not personal:
            raise HTTPException(status_code=404, detail="Employee not found")

        contact = db.execute(get_employee_contact_by_eb_id(), {"eb_id": eb_id}).fetchone()
        addresses = db.execute(get_employee_address_by_eb_id(), {"eb_id": eb_id}).fetchall()
        official = db.execute(get_employee_official_by_eb_id(), {"eb_id": eb_id}).fetchone()
        bank = db.execute(get_employee_bank_by_eb_id(), {"eb_id": eb_id}).fetchone()
        pf = db.execute(get_employee_pf_by_eb_id(), {"eb_id": eb_id}).fetchone()
        esi = db.execute(get_employee_esi_by_eb_id(), {"eb_id": eb_id}).fetchone()
        experience = db.execute(get_employee_experience_by_eb_id(), {"eb_id": eb_id}).fetchall()

        # Check if employee has a photo
        has_photo = bool(dict(personal._mapping).get("has_photo", 0))

        # Build personal dict without the has_photo helper column
        personal_dict = dict(personal._mapping)
        personal_dict.pop("has_photo", None)

        return {
            "data": {
                "personal": personal_dict,
                "contact": dict(contact._mapping) if contact else None,
                "address": [dict(r._mapping) for r in addresses],
                "official": dict(official._mapping) if official else None,
                "bank": dict(bank._mapping) if bank else None,
                "pf": dict(pf._mapping) if pf else None,
                "esi": dict(esi._mapping) if esi else None,
                "experience": [dict(r._mapping) for r in experience],
                "has_photo": has_photo,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Create Setup (dropdown options) ───────────────────────────────

@router.get("/employee_create_setup")
def employee_create_setup(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = request.query_params.get("branch_id")

        rows = db.execute(get_employee_create_setup(), {"co_id": int(co_id), "branch_id": int(branch_id) if branch_id else None}).fetchall()

        result: dict[str, list] = {
            "blood_groups": [],
            "sub_departments": [],
            "branches": [],
            "categories": [],
            "contractors": [],
        }
        for r in rows:
            m = r._mapping
            source = m["source"]
            if source in result:
                result[source].append({"label": m["name"], "value": str(m["id"])})

        # Reporting employees — filtered by branch_id if provided, otherwise co_id fallback
        if branch_id:
            emp_rows = db.execute(get_reporting_employees(), {"branch_id": int(branch_id)}).fetchall()
        else:
            emp_rows = []
        result["reporting_employees"] = [
            {"label": f"{dict(r._mapping)['name']} ({dict(r._mapping).get('emp_code', '')})", "value": str(dict(r._mapping)["id"])}
            for r in emp_rows
        ]

        return {"data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Designations by Branch ────────────────────────────────────────

@router.get("/get_designations_by_branch")
def get_designations_by_branch_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        rows = db.execute(
            get_designations_by_branch(), {"branch_id": int(branch_id)}
        ).fetchall()

        designations = [
            {"label": dict(r._mapping)["desig"], "value": str(dict(r._mapping)["designation_id"])}
            for r in rows
        ]

        return {"data": designations}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Designations by Sub Department ───────────────────────────────

@router.get("/get_designations_by_sub_dept")
def get_designations_by_sub_dept_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        sub_dept_id = request.query_params.get("sub_dept_id")
        if not sub_dept_id:
            raise HTTPException(status_code=400, detail="sub_dept_id is required")

        rows = db.execute(
            get_designations_by_sub_dept(), {"sub_dept_id": int(sub_dept_id)}
        ).fetchall()

        designations = [
            {"label": dict(r._mapping)["desig"], "value": str(dict(r._mapping)["designation_id"])}
            for r in rows
        ]

        return {"data": designations}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Check Duplicate Emp Code ──────────────────────────────────────

@router.get("/check_emp_code_duplicate")
def check_emp_code_duplicate_endpoint(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        emp_code = request.query_params.get("emp_code")
        if not emp_code:
            raise HTTPException(status_code=400, detail="emp_code is required")
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        exclude_eb_id = request.query_params.get("exclude_eb_id")

        row = db.execute(
            check_emp_code_duplicate(),
            {
                "emp_code": emp_code.strip(),
                "branch_id": int(branch_id),
                "exclude_eb_id": int(exclude_eb_id) if exclude_eb_id else None,
            },
        ).fetchone()

        cnt = dict(row._mapping)["cnt"] if row else 0
        return {"data": {"duplicate": cnt > 0}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Lookup Previous Employee by emp_code ───────────────────────────

@router.get("/employee_lookup_by_code")
def employee_lookup_by_code(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Validate emp_code exists in hrms_ed_official_details and return personal data for pre-fill."""
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        emp_code = request.query_params.get("emp_code")
        if not emp_code:
            raise HTTPException(status_code=400, detail="emp_code is required")

        row = db.execute(get_employee_by_emp_code(), {"emp_code": emp_code.strip()}).fetchone()
        if not row:
            return {"data": None, "found": False}

        return {"data": dict(row._mapping), "found": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Create Employee (personal details → returns eb_id) ────────────

@router.post("/employee_create")
def employee_create(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        body = parse_json_body(request)
        user_id = token_data.get("user_id", 0)
        _sanitize_empty_values(HrmsEdPersonalDetails, body)

        employee = HrmsEdPersonalDetails(
            first_name=body.get("first_name"),
            middle_name=body.get("middle_name"),
            last_name=body.get("last_name"),
            gender=body.get("gender"),
            date_of_birth=body.get("date_of_birth"),
            blood_group=body.get("blood_group"),
            mobile_no=body.get("mobile_no"),
            email_id=body.get("email_id"),
            marital_status=body.get("marital_status", 0),
            country_id=body.get("country_id", 73),
            relegion_name=body.get("relegion_name"),
            fixed_eb_id=body.get("fixed_eb_id"),
            father_spouse_name=body.get("father_spouse_name"),
            passport_no=body.get("passport_no"),
            driving_licence_no=body.get("driving_licence_no"),
            pan_no=body.get("pan_no"),
            aadhar_no=body.get("aadhar_no"),
            branch_id=int(branch_id),
            updated_by=user_id,
            status_id=21,  # Draft
            active=1,
        )
        db.add(employee)
        db.flush()

        eb_id = employee.eb_id
        db.commit()

        return {"data": {"eb_id": eb_id, "message": "Employee created successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Section Save (upsert any section after personal) ──────────────

SECTION_MODEL_MAP = {
    "personal": HrmsEdPersonalDetails,
    "contact": HrmsEdContactDetails,
    "address": HrmsEdAddressDetails,
    "official": HrmsEdOfficialDetails,
    "bank": HrmsEdBankDetails,
    "pf": HrmsEdPf,
    "esi": HrmsEdEsi,
    "experience": HrmsExperienceDetails,
}

SECTION_PK_MAP = {
    "personal": "eb_id",
    "contact": "contact_detail_id",
    "address": "tbl_hrms_ed_contact_details_id",
    "official": "tbl_hrms_ed_official_detail_id",
    "bank": "tbl_hrms_ed_bank_detail_id",
    "pf": "tbl_hrms_ed_pf_id",
    "esi": "tbl_hrms_ed_esi_id",
    "experience": "auto_id",
}


@router.post("/employee_section_save")
def employee_section_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        body = parse_json_body(request)
        eb_id = body.get("eb_id")
        section = body.get("section")
        section_data = body.get("data")

        if not eb_id:
            raise HTTPException(status_code=400, detail="eb_id is required")
        if section not in SECTION_MODEL_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid section '{section}'. Must be one of: {list(SECTION_MODEL_MAP.keys())}",
            )

        user_id = token_data.get("user_id", 0)
        Model = SECTION_MODEL_MAP[section]
        pk_field = SECTION_PK_MAP[section]

        # For list-based sections (address, experience) — handle arrays
        if section in ("address", "experience"):
            items = section_data if isinstance(section_data, list) else [section_data]
            saved_ids = []
            for item in items:
                item["eb_id"] = int(eb_id)
                item["updated_by"] = user_id
                item["active"] = 1
                _sanitize_empty_values(Model, item)
                existing_id = item.pop(pk_field, None)
                if existing_id:
                    db.query(Model).filter(
                        getattr(Model, pk_field) == int(existing_id)
                    ).update(item)
                    saved_ids.append(existing_id)
                else:
                    record = Model(**item)
                    db.add(record)
                    db.flush()
                    saved_ids.append(getattr(record, pk_field))
            db.commit()
            return {"data": {"section": section, "ids": saved_ids}}

        # Single-record sections — upsert
        section_data["eb_id"] = int(eb_id)
        section_data["updated_by"] = user_id
        section_data["active"] = 1
        _sanitize_empty_values(Model, section_data)

        existing = db.query(Model).filter(Model.eb_id == int(eb_id), Model.active == 1).first()
        if existing:
            for key, val in section_data.items():
                if hasattr(existing, key) and key != pk_field:
                    setattr(existing, key, val)
            db.commit()
            return {"data": {"section": section, "id": getattr(existing, pk_field)}}
        else:
            record = Model(**section_data)
            db.add(record)
            db.flush()
            record_id = getattr(record, pk_field)
            db.commit()
            return {"data": {"section": section, "id": record_id}}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Progress (which sections are complete) ────────────────

@router.get("/employee_progress/{eb_id}")
def employee_progress(
    eb_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")
        branch_id = request.query_params.get("branch_id")
        if not branch_id:
            raise HTTPException(status_code=400, detail="branch_id is required")

        progress: dict[str, bool] = {}

        # Personal — always exists if eb_id exists
        personal = db.execute(
            get_employee_personal_by_id(), {"eb_id": eb_id, "branch_id": int(branch_id)}
        ).fetchone()
        progress["personal"] = personal is not None

        for section, Model in SECTION_MODEL_MAP.items():
            exists = db.query(Model).filter(Model.eb_id == eb_id, Model.active == 1).first()
            progress[section] = exists is not None

        return {"data": progress}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Photo Upload ──────────────────────────────────────────

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/jpg"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/employee_photo_upload")
def employee_photo_upload(
    request: Request,
    file: UploadFile = File(...),
    eb_id: int = Form(...),
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type '{file.content_type}'. Allowed: jpeg, png",
            )

        image_bytes = file.file.read()
        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds 5 MB limit")

        file_ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else "jpg"
        user_id = token_data.get("user_id", 0)

        branch_id = request.query_params.get("branch_id", "0")

        # Insert or update photo in hrms_employee_face
        db.execute(
            upsert_employee_photo(),
            {
                "eb_id": eb_id,
                "face_image": image_bytes,
                "file_name": file.filename or "photo",
                "file_extension": file_ext,
                "branch_id": int(branch_id),
                "updated_by": user_id,
            },
        )

        db.commit()
        return {"data": {"message": "Photo uploaded successfully", "eb_id": eb_id}}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Photo Get (returns image) ─────────────────────────────

@router.get("/employee_photo/{eb_id}")
def employee_photo_get(
    eb_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        row = db.execute(
            get_employee_photo_by_eb_id(),
            {"eb_id": eb_id},
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="No photo found for this employee")

        mapping = row._mapping
        image_bytes = mapping["face_image"]
        ext = (mapping.get("file_extension") or "jpg").lower()
        media_type = "image/png" if ext == "png" else "image/jpeg"

        return Response(content=image_bytes, media_type=media_type)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Photo Delete ───────────────────────────────────────────

@router.delete("/employee_photo/{eb_id}")
def employee_photo_delete(
    eb_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    try:
        co_id = request.query_params.get("co_id")
        if not co_id:
            raise HTTPException(status_code=400, detail="co_id is required")

        db.execute(
            delete_employee_photo(),
            {"eb_id": eb_id},
        )
        db.commit()
        return {"data": {"message": "Photo deleted successfully"}}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Status Update (Joined / Rejected / Blacklist / Terminate / Resign / Retire) ───

@router.post("/employee_status_update")
def employee_status_update(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Update employee lifecycle status. For terminate/resign/retire/blacklist, also saves resign details."""
    try:
        body = parse_json_body(request)
        eb_id = body.get("eb_id")
        new_status_id = body.get("status_id")
        if not eb_id or new_status_id is None:
            raise HTTPException(status_code=400, detail="eb_id and status_id are required")

        user_id = token_data.get("user_id", 0)

        # Validate status_id is a known lifecycle status
        valid_statuses = set(EMPLOYEE_LIFECYCLE_STATUS.values())
        if int(new_status_id) not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status_id: {new_status_id}")

        # Update personal details status
        personal = db.query(HrmsEdPersonalDetails).filter(
            HrmsEdPersonalDetails.eb_id == int(eb_id)
        ).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Employee not found")

        personal.status_id = int(new_status_id)

        # For statuses that deactivate the employee
        if int(new_status_id) in {
            EMPLOYEE_LIFECYCLE_STATUS["BLACKLISTED"],
            EMPLOYEE_LIFECYCLE_STATUS["TERMINATED"],
            EMPLOYEE_LIFECYCLE_STATUS["RETIRED"],
            EMPLOYEE_LIFECYCLE_STATUS["RESIGNED"],
        }:
            personal.active = 0

        # Save resign details if applicable
        if int(new_status_id) in RESIGN_DETAIL_STATUSES:
            # Deactivate any existing active resign record
            db.query(HrmsEdResignDetails).filter(
                HrmsEdResignDetails.eb_id == int(eb_id),
                HrmsEdResignDetails.active == 1,
            ).update({"active": 0})

            resign_record = HrmsEdResignDetails(
                eb_id=int(eb_id),
                type_of_resign=str(new_status_id),
                resigned_date=body.get("date"),
                date_of_inactive=body.get("date"),
                resign_reasons=body.get("reason"),
                resign_remarks=body.get("remarks"),
                updated_by=user_id,
                active=1,
            )
            db.add(resign_record)

        db.commit()
        return {"data": {"message": "Status updated successfully", "status_id": int(new_status_id)}}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# ─── Employee Salary Structure ─────────────────────────────────────────

@router.get("/employee_salary_schemes")
def employee_salary_schemes(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return active pay schemes for the salary structure dropdown."""
    try:
        co_id = request.query_params.get("co_id")
        rows = db.execute(get_active_pay_scheme_dropdown(), {"co_id": int(co_id) if co_id else None}).fetchall()
        return {
            "data": [
                {"label": r._mapping["payscheme_name"], "value": str(r._mapping["payscheme_id"])}
                for r in rows
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/employee_salary/{eb_id}")
def employee_salary_get(
    eb_id: int,
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Return the employee's current salary structure: scheme mapping + scheme components + saved input amounts."""
    try:
        co_id = request.query_params.get("co_id")
        branch_id = request.query_params.get("branch_id")  # accepted for forward compatibility; not yet used for filtering

        # 1. Current scheme mapping
        mapping_row = db.execute(get_employee_payscheme_by_eb_id(), {"eb_id": eb_id}).fetchone()
        if not mapping_row:
            return {"data": None}
        mapping = dict(mapping_row._mapping)
        pay_scheme_id = mapping["pay_scheme_id"]

        # 2. Scheme component definitions
        detail_rows = db.execute(get_pay_scheme_details_by_scheme_id(), {"payscheme_id": pay_scheme_id}).fetchall()

        # 3. Employee's saved input values
        struct_rows = db.execute(get_employee_structure_by_eb_id(), {"eb_id": eb_id, "pay_scheme_id": pay_scheme_id}).fetchall()
        saved_amounts: dict[int, float] = {r._mapping["component_id"]: float(r._mapping["amount"]) for r in struct_rows}

        components = []
        for r in detail_rows:
            m = dict(r._mapping)
            comp_id = m["component_id"]
            components.append({
                "component_id": comp_id,
                "component_name": m["component_name"],
                "component_code": m.get("component_code"),
                "type": m["type"],
                "formula": m.get("formula"),
                "default_value": m.get("default_value"),
                "roundof": m.get("roundof"),
                "roundof_type": m.get("roundof_type"),
                "amount": saved_amounts.get(comp_id, m.get("default_value") or 0),
            })

        return {"data": {**mapping, "components": components}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/employee_salary_check")
def employee_salary_check(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Preview salary calculation without saving. Returns components grouped by type."""
    from .payRegister import _evaluate_employee_formulas
    try:
        body = parse_json_body(request)
        pay_scheme_id = int(body.get("pay_scheme_id", 0))
        input_values: dict[str, float] = body.get("input_values", {})

        if not pay_scheme_id:
            raise HTTPException(status_code=400, detail="pay_scheme_id is required")

        # Scheme formulas — JOIN already supplies code/roundof/roundof_type
        # for every component referenced by this scheme, regardless of which
        # company owns the component. (A company-scoped query would miss
        # components belonging to a different / null company_id.)
        formula_rows = db.execute(get_pay_scheme_details_by_scheme_id(), {"payscheme_id": pay_scheme_id}).fetchall()
        if not formula_rows:
            raise HTTPException(status_code=404, detail="No scheme details found")

        # Build formula map; override type-0 with supplied input values
        component_formulas: dict[int, str] = {}
        for r in formula_rows:
            m = r._mapping
            comp_id = int(m["component_id"])
            if int(m["type"]) == 0 and str(comp_id) in input_values:
                component_formulas[comp_id] = str(input_values[str(comp_id)])
            else:
                component_formulas[comp_id] = m["formula"] or str(m.get("default_value") or 0)

        # Component metadata sourced from the scheme's own JOIN — guarantees
        # every code referenced by a formula in this scheme is resolvable.
        components_meta: dict[int, dict] = {}
        for r in formula_rows:
            m = r._mapping
            cid = int(m["component_id"])
            components_meta[cid] = {
                "id": cid,
                "code": m.get("component_code"),
                "name": m.get("component_name"),
                "type": int(m["type"]),
                "roundof": m.get("roundof"),
                "roundof_type": m.get("roundof_type"),
            }

        # Evaluate (returns cooked values + per-component errors and warnings)
        calculated, eval_errors, eval_warnings = _evaluate_employee_formulas(
            component_formulas, components_meta,
        )

        # Build response grouped by type; attach per-component error when present.
        # Warnings (unknown identifiers) do NOT block the value — they only
        # surface in the top-level warnings array so the user can fix the scheme.
        result: dict[str, list] = {"inputs": [], "earnings": [], "deductions": [], "summary": []}
        type_map = {0: "inputs", 1: "earnings", 2: "deductions", 3: "summary"}
        for r in formula_rows:
            m = r._mapping
            comp_id = int(m["component_id"])
            comp_type = int(m["type"])
            group = type_map.get(comp_type, "inputs")
            entry = {
                "component_id": comp_id,
                "component_name": m["component_name"],
                "type": comp_type,
                "amount": calculated.get(comp_id, 0),
            }
            if comp_id in eval_errors:
                entry["error"] = eval_errors[comp_id]
            result[group].append(entry)

        # Top-level warnings — combine fatal errors and soft warnings so the UI
        # banner shows all formula issues in one place
        warnings_out: list[str] = []
        for r in formula_rows:
            m = r._mapping
            cid = int(m["component_id"])
            name = m["component_name"]
            if cid in eval_errors:
                warnings_out.append(f"{name} (id {cid}): {eval_errors[cid]}")
            elif cid in eval_warnings:
                warnings_out.append(f"{name} (id {cid}): {eval_warnings[cid]}")

        return {"data": result, "warnings": warnings_out}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/employee_salary_save")
def employee_salary_save(
    request: Request,
    db: Session = Depends(get_tenant_db),
    token_data: dict = Depends(get_current_user_with_refresh),
):
    """Save or update employee salary structure (scheme mapping + input values)."""
    from src.models.hrms import PayEmployeePayscheme, PayEmployeeStructure
    try:
        co_id = request.query_params.get("co_id")
        body = parse_json_body(request)
        eb_id = int(body.get("eb_id", 0))
        pay_scheme_id = int(body.get("pay_scheme_id", 0))
        effective_date = body.get("effective_date")
        input_values: list[dict] = body.get("input_values", [])
        user_id = token_data.get("user_id", 0)

        if not eb_id or not pay_scheme_id:
            raise HTTPException(status_code=400, detail="eb_id and pay_scheme_id are required")

        # Upsert pay_employee_payscheme
        existing_mapping = db.query(PayEmployeePayscheme).filter(
            PayEmployeePayscheme.eb_id == eb_id,
            PayEmployeePayscheme.status_id == 1,
        ).first()

        if existing_mapping:
            existing_mapping.pay_scheme_id = pay_scheme_id
            existing_mapping.updated_by = user_id
        else:
            mapping = PayEmployeePayscheme(
                eb_id=eb_id,
                pay_scheme_id=pay_scheme_id,
                status_id=1,
                updated_by=user_id,
            )
            db.add(mapping)

        # Deactivate old structure entries for this scheme
        db.query(PayEmployeeStructure).filter(
            PayEmployeeStructure.eb_id == eb_id,
            PayEmployeeStructure.pay_scheme_id == pay_scheme_id,
            PayEmployeeStructure.status_id == 1,
        ).update({"status_id": 0})

        # Insert new input values
        for iv in input_values:
            struct = PayEmployeeStructure(
                eb_id=eb_id,
                pay_scheme_id=pay_scheme_id,
                component_id=int(iv["component_id"]),
                amount=float(iv.get("amount", 0)),
                effective_from=effective_date,
                status_id=1,
                updated_by=user_id,
            )
            db.add(struct)

        db.commit()
        return {"data": {"message": "Salary structure saved successfully"}}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
