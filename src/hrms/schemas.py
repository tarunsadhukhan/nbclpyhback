"""Pydantic schemas for HRMS employee and pay scheme endpoints."""
from pydantic import BaseModel
from datetime import date
from typing import Optional


# --- Employee Schemas ---

class PersonalDetailsPayload(BaseModel):
    first_name: str
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    blood_group: Optional[str] = None
    email_id: Optional[str] = None
    marital_status: Optional[int] = 0
    country_id: Optional[int] = 73
    relegion_name: Optional[str] = None  # matches DB column typo
    father_spouse_name: Optional[str] = None
    passport_no: Optional[str] = None
    driving_licence_no: Optional[str] = None
    pan_no: Optional[str] = None
    aadhar_no: Optional[str] = None


class ContactDetailsPayload(BaseModel):
    mobile_no: str
    emergency_no: Optional[str] = None


class AddressDetailsPayload(BaseModel):
    address_type: int = 1
    country_id: Optional[int] = None
    state_id: Optional[int] = None
    city_name: Optional[str] = None
    address_line_1: str
    address_line_2: Optional[str] = None
    pin_code: int
    is_correspondent_address: int = 0


class OfficialDetailsPayload(BaseModel):
    sub_dept_id: int
    branch_id: int
    catagory_id: int  # matches DB column typo
    designation_id: int
    date_of_join: Optional[date] = None
    probation_period: Optional[int] = None
    minimum_working_commitment: int = 0
    reporting_eb_id: int
    emp_code: str
    legacy_code: Optional[str] = None
    contractor_id: Optional[int] = None
    office_mobile_no: Optional[str] = None
    office_email_id: Optional[str] = None


class BankDetailsPayload(BaseModel):
    ifsc_code: str
    bank_acc_no: str
    bank_name: str
    bank_branch_name: str
    is_verified: int = 0


class PfDetailsPayload(BaseModel):
    pf_no: str
    pf_uan_no: str
    pf_previous_no: str
    pf_transfer_no: Optional[str] = None
    nominee_name: Optional[str] = None
    relationship_name: Optional[str] = None
    pf_date_of_join: Optional[date] = None


class EsiDetailsPayload(BaseModel):
    esi_no: Optional[str] = None
    medical_policy_no: Optional[str] = None


class ExperienceDetailsPayload(BaseModel):
    company_name: Optional[str] = None
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    designation: Optional[str] = None
    project: Optional[str] = None
    contact: Optional[str] = None


class SectionSaveRequest(BaseModel):
    eb_id: int
    section: str  # one of EMPLOYEE_SECTIONS
    data: dict


# --- Pay Scheme Schemas ---

class PaySchemeCreatePayload(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    wage_type: Optional[str] = None
    designation_id: Optional[int] = None
    work_location_id: Optional[int] = None
    copy_from_scheme_id: Optional[int] = None
    components: list[dict] = []


class PayParamCreatePayload(BaseModel):
    name: str
    description: Optional[str] = None
    param_type: Optional[str] = None
    value: Optional[str] = None
