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


class OrgCreate(BaseModel):
    con_org_name: str
    con_org_shortname: str
    con_org_contact_person: str
    con_org_email_id: str
    con_org_mobile: str
    con_org_address: str
    con_org_pincode: int
    con_org_state_id: int
    con_org_remarks: Optional[str] = ""
    active: str
    con_org_master_status: int
    con_modules_selected: List[str]
    con_org_main_url: str
    con_org_id: Optional[int] = None  # For edit operations


class ControlDeskMenuSchema(BaseModel):
    control_desk_menu_id: Optional[int]
    control_desk_menu_name: str
    active: int
    parent_id: Optional[int]
    menu_path: Optional[str]
    menu_state: Optional[str]
    report_path: Optional[str]
    menu_icon_name: Optional[str]
    order_by: Optional[int]
    menu_type: Optional[int]

    class Config:
        orm_mode = True


class PortalMenuMstSchema(BaseModel):
    menu_id: Optional[int]
    menu_name: str
    menu_path: Optional[str]
    active: bool
    menu_parent_id: Optional[int]
    menu_type_id: int
    menu_icon: Optional[str]
    module_id: int
    order_by: Optional[int]
    menu_type: Optional[int] = None  # Add menu_type field

    class Config:
        orm_mode = True


