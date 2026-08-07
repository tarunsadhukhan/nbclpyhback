from pydantic import BaseModel
from typing import List, Optional

class SubMenuItem(BaseModel):
    id: int
    title: str
    path: Optional[str] = None  # Changed to Optional to allow None values
    icon: Optional[str] = None

class MenuItem(BaseModel):
    id: int
    title: str
    path: Optional[str] = None  # Changed to Optional to allow None values
    icon: Optional[str] = None
    submenu: Optional[List[SubMenuItem]] = None

class MenuResponse(BaseModel):
    data: List[MenuItem]

class CoCreate(BaseModel):
    co_name: str
    co_prefix: str
    co_address1: str
    co_address2: Optional[str] = None
    co_zipcode: int
    country_id: int
    state_id: int
    co_logo: Optional[str] = None
    co_cin_no: Optional[str] = None
    co_email_id: Optional[str] = None
    co_pan_no: Optional[str] = None
    s3bucket_name: Optional[str] = None
    s3folder_name: Optional[str] = None
    tally_sync: Optional[str] = None
    alert_email_id: Optional[str] = None
    co_id: Optional[str] = None  # Added for edit operations

class BranchCreate(BaseModel):
    branch_name: str
    branch_prefix: Optional[str] = None
    co_id: int
    branch_address1: str
    branch_address2: Optional[str] = None
    branch_zipcode: int
    country_id: int
    state_id: int
    gst_no: Optional[str] = None
    contact_no: Optional[int] = None
    contact_person: Optional[str] = None
    branch_email: Optional[str] = None
    active: Optional[bool] = True  # Default to True if not provided
    gst_verified: Optional[bool] = False  # Default to False if not provided
    branch_id: Optional[int] = None  # Added for edit operations



class DeptCreate(BaseModel):
    branch_id: Optional[int]
    dept_desc: Optional[str]
    dept_code: Optional[str]
    order_id: Optional[int]
    dept_id: Optional[int] = None  # Added for edit operations
    created_date: Optional[str] = None  # Added for edit operations
    class Config:
        orm_mode = True


class CoConfigCreate(BaseModel):
    co_id: int
    currency_id: int
    india_gst: Optional[bool] = False
    india_tds: Optional[bool] = False
    india_tcs: Optional[bool] = False
    back_date_allowable: Optional[bool] = False
    indent_required: Optional[bool] = False
    po_required: Optional[bool] = False
    material_inspection: Optional[bool] = False
    quotation_required: Optional[bool] = False
    do_required: Optional[bool] = False
    gst_linked: Optional[bool] = False
    updated_by: Optional[int] = None  # Added for edit operations
    updated_date_time: Optional[str] = None  # Added for edit operations