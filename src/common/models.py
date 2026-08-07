# from sqlalchemy import Table, Column, Integer, String, Text, DateTime, Boolean, JSON
# from src.database import metadata
# from sqlalchemy.sql import func
# from src.database import Base  # Ensure Base is imported from your database setup

from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
from src.config.db import get_db, get_db_names

class ConOrgMaster(SQLModel, table=True):
    __tablename__ = "con_org_master"
    con_org_id: Optional[int] = Field(default=None, primary_key=True)
    con_org_name: str
    con_org_address: str
    con_org_pincode: Optional[str] = None
    con_org_state_id: Optional[int] = None
    con_org_country_id: Optional[int] = None
    con_org_email_id: Optional[str] = None
    con_org_mobile: Optional[str] = None
    con_org_contact_person: Optional[str] = None
    con_org_shortname: Optional[str] = None
    con_org_remarks: Optional[str] = None
    active: int = 1
    con_org_master_status: int = 1
    con_modules_selected: Optional[str] = None  # Store JSON as string
    custom_modules: Optional[str] = None
    created_date_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Academic_years(SQLModel, table=True):
    __tablename__ = "academic_years"
    hdr_id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int]
    display_label: Optional[str]
    string_label: Optional[str]
    year: Optional[int]
    from_date: Optional[datetime]
    to_date: Optional[datetime]
    
    
class DailyDrawingTransaction(SQLModel, table=True):
    __tablename__ = "daily_drawing_transaction"
    drg_tran_id: Optional[int] = Field(default=None, primary_key=True)
    tran_date: str
    spell: str
    drg_mc_id: int
    diff_meter: int

class MachineMaster(SQLModel, table=True):
    __tablename__ = "mechine_master"
    mechine_id: Optional[int] = Field(default=None, primary_key=True)
    mech_code: str = Field(nullable=False)
    mechine_name: str = Field(nullable=False)
    
    
class CompanyRequest(BaseModel):
    userId: int
