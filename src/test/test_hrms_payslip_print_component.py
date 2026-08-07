"""Tests for tbl_payslip_print_component query functions and CRUD router."""

import pytest
from sqlalchemy import text
from src.hrms.query import (
    list_payslip_print_components,
    count_payslip_print_components,
    get_payslip_print_component_by_id,
    check_payslip_print_component_duplicate,
)


class TestPayslipPrintComponentQueries:
    def test_list_returns_text_with_binds(self):
        sql = str(list_payslip_print_components())
        assert isinstance(list_payslip_print_components(), type(text("")))
        assert "tbl_payslip_print_component" in sql
        for bind in (":company_id", ":branch_ids", ":payscheme_id", ":search", ":page_size", ":offset"):
            assert bind in sql
        # joins for display names
        assert "pay_scheme_master" in sql
        assert "pay_components" in sql
        assert "branch_mst" in sql

    def test_count_returns_text_with_binds(self):
        sql = str(count_payslip_print_components())
        assert "COUNT(" in sql.upper()
        for bind in (":company_id", ":branch_ids", ":payscheme_id", ":search"):
            assert bind in sql

    def test_by_id_returns_text_with_binds(self):
        sql = str(get_payslip_print_component_by_id())
        assert ":pay_id" in sql
        assert ":company_id" in sql
        assert "tbl_payslip_print_component" in sql

    def test_duplicate_check_returns_text_with_binds(self):
        sql = str(check_payslip_print_component_duplicate())
        for bind in (":payscheme_id", ":company_id", ":branch_id", ":component_id", ":exclude_pay_id"):
            assert bind in sql
        assert "is_active = 1" in sql


class TestPayslipPrintComponentRouter:
    """Route-surface and model-mapping tests for the payslip print component router."""

    def test_router_exposes_expected_routes(self):
        """Router must expose the specified CRUD paths (no toggle_active)."""
        from src.hrms.payslipPrintComponent import router

        paths = {r.path for r in router.routes}
        expected = {
            "/payslip_print_component_list",
            "/payslip_print_component_by_id/{pay_id}",
            "/payslip_print_component_setup",
            "/pay_scheme_components",
            "/payslip_print_component_create",
            "/payslip_print_component_update/{pay_id}",
            "/payslip_print_component_delete/{pay_id}",
        }
        assert expected.issubset(paths), f"Missing paths: {expected - paths}"
        assert "/payslip_print_component_toggle_active/{pay_id}" not in paths, (
            "toggle_active endpoint must not exist"
        )

    def test_delete_route_uses_delete_method(self):
        """The delete endpoint must be registered as an HTTP DELETE."""
        from src.hrms.payslipPrintComponent import router

        delete_routes = [
            r for r in router.routes
            if getattr(r, "path", None) == "/payslip_print_component_delete/{pay_id}"
        ]
        assert delete_routes, "delete route not found"
        assert "DELETE" in delete_routes[0].methods

    def test_model_maps_table(self):
        """ORM model must map to the correct table with required columns."""
        from src.models.hrms import TblPayslipPrintComponent

        assert TblPayslipPrintComponent.__tablename__ == "tbl_payslip_print_component"
        cols = {c.name for c in TblPayslipPrintComponent.__table__.columns}
        for col in ("pay_id", "payscheme_id", "company_id", "branch_id", "component_id",
                    "desc_print", "payslip_order", "fixed_var_cols", "total_print",
                    "payslip_print", "is_active", "updated_by", "updated_date_time"):
            assert col in cols, f"Missing column: {col}"
