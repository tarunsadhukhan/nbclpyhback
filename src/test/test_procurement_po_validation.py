# src/test/test_procurement_po_validation.py
"""
Tests for GET /procurementPO/validate_item_for_po endpoint
and the helper query functions added to support it.

Follows the same dependency-override pattern as test_procurement_indent_validation.py
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from sqlalchemy import text

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


def _override_auth():
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    def _override():
        yield mock_session
    return _override


def _mock_row(mapping):
    row = MagicMock()
    row._mapping = mapping
    return row


class TestValidateItemForPOParams:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_invalid_po_type_returns_400(self):
        # po_type must be 'Regular' or 'Open'
        response = client.get("/api/procurementPO/validate_item_for_po?branch_id=1&item_id=10&po_type=INVALID&expense_type_id=2")
        assert response.status_code == 400
        assert "po_type" in response.json()["detail"].lower()

    def test_missing_branch_id_returns_400(self):
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&item_id=10&po_type=Regular&expense_type_id=2")
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_missing_item_id_returns_400(self):
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&po_type=Regular&expense_type_id=2")
        assert response.status_code == 400
        assert "item_id" in response.json()["detail"].lower()

    def test_missing_expense_type_id_returns_400(self):
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular")
        assert response.status_code == 400
        assert "expense_type_id" in response.json()["detail"].lower()


class TestValidateItemForPOLogic3:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_regular_capital_returns_logic3(self):
        """Per PO spec, Regular + Capital -> Logic 3 (free entry, no validation)."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = _mock_row({"expense_type_name": "Capital"})
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=5")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 3
        assert data["errors"] == []
        assert data["warnings"] == []

    def test_unknown_expense_returns_logic3(self):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = _mock_row({"expense_type_name": "SomeUnknownType"})
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=99")
        assert response.status_code == 200
        assert response.json()["validation_logic"] == 3

    def test_expense_type_not_found_returns_400(self):
        """Unknown expense_type_id -> endpoint returns 400 (cannot determine logic)."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=999")
        assert response.status_code == 400
        assert "expense_type_id" in response.json()["detail"].lower()


class TestValidateItemForPOLogic1:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def _make_session(self, calls):
        mock_session = MagicMock()
        call_count = [0]
        def side_effect(query, params=None):
            idx = call_count[0]; call_count[0] += 1
            mock_result = MagicMock()
            mock_result.fetchone.return_value = calls.get(idx)
            return mock_result
        mock_session.execute.side_effect = side_effect
        return mock_session

    def test_open_indent_exists_blocks_item(self):
        """v2 call order: 0=expense_type, 1=vdata(includes all fields), 2=fy_indent_check"""
        session = self._make_session({
            0: _mock_row({"expense_type_name": "General"}),
            1: _mock_row({
                "minqty": 10, "maxqty": 100, "min_order_qty": 5,
                "branch_stock": 5, "outstanding_indent_qty": 0,
                "regular_bom_outstanding": 0, "open_indent_outstanding": 0,
                "outstanding_po_qty": 0, "open_po_outstanding": 0,
                "max_indent_qty": 95, "min_indent_qty": 10,
                "max_po_qty": 95, "min_po_qty": 10,
            }),
            2: _mock_row({"indent_id": 55, "indent_no": "IND/2025/001"}),
        })
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_open_indent"] is True
        assert len(data["errors"]) > 0

    def test_open_po_exists_is_warning_not_error(self):
        """Active PO for the same item should produce a warning (not an error)
        and validation should continue to compute max/min qty.
        v2 call order: 0=expense_type, 1=vdata(includes outstanding), 2=fy_indent_check, 3=open_po_check"""
        session = self._make_session({
            0: _mock_row({"expense_type_name": "Maintenance"}),
            1: _mock_row({
                "minqty": 5, "maxqty": 80, "min_order_qty": 5,
                "branch_stock": 10, "outstanding_indent_qty": 0,
                "regular_bom_outstanding": 0, "open_indent_outstanding": 0,
                "outstanding_po_qty": 5, "open_po_outstanding": 0,
                "max_indent_qty": 70, "min_indent_qty": 5,
                "max_po_qty": 70, "min_po_qty": 5,
            }),
            2: None,  # no open indent
            3: _mock_row({"po_id": 10, "po_no": "PO/2025/010"}),  # open PO exists
        })
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_open_po"] is True
        # Should be a warning, NOT an error
        assert len(data["warnings"]) > 0
        assert any("active po" in w.lower() for w in data["warnings"])
        # Errors should be empty (no blocking error from active PO)
        assert len(data["errors"]) == 0
        # Pre-computed from view — outstanding_po_qty now in vdata
        assert data["outstanding_po_qty"] == 5
        assert data["max_po_qty"] == 70

    def test_clean_path_computes_max_po_qty(self):
        """v2 call order: 0=expense_type, 1=vdata, 2=fy_indent_check, 3=open_po_check"""
        session = self._make_session({
            0: _mock_row({"expense_type_name": "General"}),
            1: _mock_row({
                "minqty": 10, "maxqty": 200, "min_order_qty": 10,
                "branch_stock": 20, "outstanding_indent_qty": 0,
                "regular_bom_outstanding": 0, "open_indent_outstanding": 0,
                "outstanding_po_qty": 0, "open_po_outstanding": 0,
                "max_indent_qty": 180, "min_indent_qty": 10,
                "max_po_qty": 180, "min_po_qty": 10,
            }),
            2: None,
            3: None,
        })
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Regular&expense_type_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["errors"] == []
        assert data["has_open_indent"] is False
        assert data["has_open_po"] is False
        assert data["max_po_qty"] == 180


class TestValidateItemForPOLogic2:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def _make_session(self, calls):
        mock_session = MagicMock()
        call_count = [0]
        def side_effect(query, params=None):
            idx = call_count[0]; call_count[0] += 1
            mock_result = MagicMock()
            mock_result.fetchone.return_value = calls.get(idx)
            return mock_result
        mock_session.execute.side_effect = side_effect
        return mock_session

    def test_fy_po_exists_blocks(self):
        # v2 call order: 0=expense_type, 1=vdata(all fields), 2=po_fy_check
        session = self._make_session({
            0: _mock_row({"expense_type_name": "General"}),
            1: _mock_row({
                "minqty": 100, "maxqty": 500, "min_order_qty": 10,
                "branch_stock": 50, "outstanding_indent_qty": 0,
                "regular_bom_outstanding": 0, "open_indent_outstanding": 0,
                "outstanding_po_qty": 0, "open_po_outstanding": 0,
                "max_indent_qty": 450, "min_indent_qty": 100,
                "max_po_qty": 450, "min_po_qty": 100,
            }),
            2: _mock_row({"po_id": 7, "po_no": "PO/2025/007"}),
        })
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Open&expense_type_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["fy_po_exists"] is True
        assert data["fy_po_no"] == "PO/2025/007"
        assert len(data["errors"]) > 0

    def test_missing_minmax_blocks(self):
        # v2 call order: 0=expense_type, 1=vdata(no minmax), 2=po_fy_check, 3=indent_fy_check
        # regular_bom_outstanding now comes from vdata directly (no separate call)
        session = self._make_session({
            0: _mock_row({"expense_type_name": "General"}),
            1: _mock_row({
                "minqty": None, "maxqty": None, "min_order_qty": None,
                "branch_stock": 0, "outstanding_indent_qty": 0,
                "regular_bom_outstanding": 0, "open_indent_outstanding": 0,
                "outstanding_po_qty": 0, "open_po_outstanding": 0,
                "max_indent_qty": -1, "min_indent_qty": -1,
                "max_po_qty": -1, "min_po_qty": -1,
            }),
            2: None,
            3: None,
        })
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(session)
        response = client.get("/api/procurementPO/validate_item_for_po?co_id=1&branch_id=1&item_id=10&po_type=Open&expense_type_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["has_minmax"] is False
        assert data["forced_qty"] is None
        assert len(data["errors"]) > 0


class TestPOQueryHelpers:
    def test_get_outstanding_po_qty_has_required_binds(self):
        from src.procurement.query import get_outstanding_po_qty
        sql = str(get_outstanding_po_qty())
        assert ":branch_id" in sql
        assert ":item_id" in sql

    def test_check_open_po_for_item_has_required_binds(self):
        from src.procurement.query import check_open_po_for_item
        sql = str(check_open_po_for_item())
        assert ":branch_id" in sql
        assert ":item_id" in sql

    def test_get_po_fy_check_has_required_binds(self):
        from src.procurement.query import get_po_fy_check
        sql = str(get_po_fy_check())
        assert ":branch_id" in sql
        assert ":item_id" in sql
        assert ":fy_start" in sql
        assert ":fy_end" in sql


class TestPOV2QueryHelpers:
    """Tests for v2 PO query functions that use aggregate views."""

    def test_get_outstanding_po_qty_v2_has_required_binds(self):
        from src.procurement.query import get_outstanding_po_qty_v2
        sql = str(get_outstanding_po_qty_v2())
        assert ":branch_id" in sql
        assert ":item_id" in sql

    def test_get_outstanding_po_qty_v2_references_new_view(self):
        from src.procurement.query import get_outstanding_po_qty_v2
        sql = str(get_outstanding_po_qty_v2())
        assert "vw_item_balance_qty_by_branch_new" in sql

    def test_check_open_po_for_item_v2_has_required_binds(self):
        from src.procurement.query import check_open_po_for_item_v2
        sql = str(check_open_po_for_item_v2())
        assert ":branch_id" in sql
        assert ":item_id" in sql

    def test_check_open_po_for_item_v2_references_new_view(self):
        from src.procurement.query import check_open_po_for_item_v2
        sql = str(check_open_po_for_item_v2())
        assert "vw_proc_po_outstanding_new" in sql

    def test_get_po_fy_check_v2_has_required_binds(self):
        from src.procurement.query import get_po_fy_check_v2
        sql = str(get_po_fy_check_v2())
        assert ":branch_id" in sql
        assert ":item_id" in sql
        assert ":fy_start" in sql
        assert ":fy_end" in sql

    def test_get_po_fy_check_v2_references_new_view(self):
        from src.procurement.query import get_po_fy_check_v2
        sql = str(get_po_fy_check_v2())
        assert "vw_proc_po_outstanding_new" in sql

    def test_get_po_fy_check_v2_checks_open_type(self):
        from src.procurement.query import get_po_fy_check_v2
        sql = str(get_po_fy_check_v2())
        assert "'Open'" in sql
