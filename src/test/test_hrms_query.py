"""
Tests for HRMS query functions.
Tests for src/hrms/query.py
"""

import pytest
from sqlalchemy import text
from src.hrms.query import (
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
    get_reporting_employees,
    get_pay_scheme_list,
    get_pay_scheme_by_id,
    get_pay_scheme_components,
    get_pay_scheme_create_setup,
    get_pay_param_list,
    get_employee_photo_by_eb_id,
    upsert_employee_photo,
    delete_employee_photo,
)


class TestEmployeeQueries:
    """Tests for employee SQL query functions."""

    def test_get_employee_list_returns_text(self):
        result = get_employee_list()
        assert isinstance(result, type(text("")))

    def test_get_employee_list_has_required_binds(self):
        sql_str = str(get_employee_list())
        assert ":branch_id" in sql_str
        assert ":search" in sql_str
        assert ":page_size" in sql_str
        assert ":offset" in sql_str

    def test_get_employee_list_count_returns_text(self):
        result = get_employee_list_count()
        assert isinstance(result, type(text("")))

    def test_get_employee_personal_by_id_returns_text(self):
        result = get_employee_personal_by_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_contact_by_eb_id_returns_text(self):
        result = get_employee_contact_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_address_by_eb_id_returns_text(self):
        result = get_employee_address_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_official_by_eb_id_returns_text(self):
        result = get_employee_official_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_bank_by_eb_id_returns_text(self):
        result = get_employee_bank_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_pf_by_eb_id_returns_text(self):
        result = get_employee_pf_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_esi_by_eb_id_returns_text(self):
        result = get_employee_esi_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_experience_by_eb_id_returns_text(self):
        result = get_employee_experience_by_eb_id()
        assert isinstance(result, type(text("")))
        assert ":eb_id" in str(result)

    def test_get_employee_create_setup_returns_text(self):
        result = get_employee_create_setup()
        assert isinstance(result, type(text("")))
        assert ":co_id" in str(result)

    def test_get_reporting_employees_returns_text(self):
        result = get_reporting_employees()
        assert isinstance(result, type(text("")))
        assert ":branch_id" in str(result)


class TestPaySchemeQueries:
    """Tests for pay scheme SQL query functions."""

    def test_get_pay_scheme_list_returns_text(self):
        result = get_pay_scheme_list()
        assert isinstance(result, type(text("")))
        assert ":co_id" in str(result)

    def test_get_pay_scheme_by_id_returns_text(self):
        result = get_pay_scheme_by_id()
        assert isinstance(result, type(text("")))
        assert ":id" in str(result)
        assert ":co_id" in str(result)

    def test_get_pay_scheme_components_returns_text(self):
        result = get_pay_scheme_components()
        assert isinstance(result, type(text("")))
        assert ":co_id" in str(result)

    def test_get_pay_scheme_create_setup_returns_text(self):
        result = get_pay_scheme_create_setup()
        assert isinstance(result, type(text("")))
        assert ":co_id" in str(result)

    def test_get_pay_param_list_returns_text(self):
        result = get_pay_param_list()
        assert isinstance(result, type(text("")))
        assert ":co_id" in str(result)


class TestEmployeePhotoQueries:
    """Tests for employee photo SQL query functions (stored in hrms_ed_personal_details)."""

    def test_get_employee_photo_by_eb_id_returns_text(self):
        result = get_employee_photo_by_eb_id()
        assert isinstance(result, type(text("")))
        sql_str = str(result)
        assert ":eb_id" in sql_str
        assert "hrms_ed_personal_details" in sql_str
        assert "face_image" in sql_str

    def test_upsert_employee_photo_returns_text(self):
        result = upsert_employee_photo()
        assert isinstance(result, type(text("")))
        sql_str = str(result)
        assert ":eb_id" in sql_str
        assert ":face_image" in sql_str
        assert ":file_name" in sql_str
        assert ":updated_by" in sql_str
        assert "hrms_ed_personal_details" in sql_str

    def test_delete_employee_photo_returns_text(self):
        result = delete_employee_photo()
        assert isinstance(result, type(text("")))
        sql_str = str(result)
        assert ":eb_id" in sql_str
        assert "face_image" in sql_str
        assert "NULL" in sql_str
