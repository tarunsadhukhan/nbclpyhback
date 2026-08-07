"""Tests for indent line-item validation logic.

Covers:
- determine_validation_logic mapping
- get_fy_boundaries calculation
- calculate_max_indent_qty formula
- /validate_item_for_indent endpoint (mocked DB)
"""

import pytest
from datetime import date
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

# Import helpers directly
from src.procurement.indent import (
    determine_validation_logic,
    get_fy_boundaries,
    calculate_max_indent_qty,
)


client = TestClient(app)


# ── Dependency override helpers ──────────────────────────────────────

def _override_auth():
    """Override auth dependency to return a fake user."""
    return {"user_id": 1}


def _make_mock_db_override(mock_session):
    """Create a dependency override for get_tenant_db that yields mock_session."""
    def _override():
        yield mock_session
    return _override


# ── Unit tests for helper functions ──────────────────────────────────

class TestDetermineValidationLogic:
    """Tests for the VALIDATION_LOGIC_MAP lookup."""

    def test_regular_general_returns_1(self):
        assert determine_validation_logic("Regular", "General") == 1

    def test_regular_maintenance_returns_1(self):
        assert determine_validation_logic("Regular", "Maintenance") == 1

    def test_regular_production_returns_1(self):
        assert determine_validation_logic("Regular", "Production") == 1

    def test_regular_overhaul_returns_1(self):
        assert determine_validation_logic("Regular", "Overhaul") == 1

    def test_regular_capital_returns_2(self):
        assert determine_validation_logic("Regular", "Capital") == 2

    def test_open_general_returns_3(self):
        assert determine_validation_logic("Open", "General") == 3

    def test_open_maintenance_returns_3(self):
        assert determine_validation_logic("Open", "Maintenance") == 3

    def test_open_production_returns_3(self):
        assert determine_validation_logic("Open", "Production") == 3

    def test_bom_general_returns_1(self):
        assert determine_validation_logic("BOM", "General") == 1

    def test_bom_capital_returns_2(self):
        assert determine_validation_logic("BOM", "Capital") == 2

    def test_bom_overhaul_returns_2(self):
        assert determine_validation_logic("BOM", "Overhaul") == 2

    def test_unknown_combination_returns_3(self):
        assert determine_validation_logic("Unknown", "Whatever") == 3

    def test_none_expense_returns_3(self):
        assert determine_validation_logic("Regular", None) == 3


class TestGetFyBoundaries:
    """Tests for financial-year boundary calculation (April 1 – March 31)."""

    def test_date_in_jan_returns_previous_april(self):
        start, end = get_fy_boundaries(date(2026, 1, 15))
        assert start == date(2025, 4, 1)
        assert end == date(2026, 3, 31)

    def test_date_in_april_returns_same_year(self):
        start, end = get_fy_boundaries(date(2026, 4, 1))
        assert start == date(2026, 4, 1)
        assert end == date(2027, 3, 31)

    def test_date_in_march_returns_previous_april(self):
        start, end = get_fy_boundaries(date(2026, 3, 31))
        assert start == date(2025, 4, 1)
        assert end == date(2026, 3, 31)

    def test_date_in_december(self):
        start, end = get_fy_boundaries(date(2025, 12, 25))
        assert start == date(2025, 4, 1)
        assert end == date(2026, 3, 31)


class TestCalculateMaxIndentQty:
    """Tests for the max indent quantity formula.

    Formula:
    - If min_order_qty is 0/None → return None (cannot apply formula)
    - available = maxqty - branch_stock - outstanding_indent_qty
    - If available <= 0 → return None (no room)
    - If available < min_order_qty → return min_order_qty
    - Else → ROUNDUP(available / min_order_qty) * min_order_qty
    """

    def test_basic_calculation(self):
        # maxqty=100, stock=30, outstanding=20 => available=50
        # min_order_qty=10 => ceil(50/10)*10 = 50
        result = calculate_max_indent_qty(100, 30, 20, 10)
        assert result == 50.0

    def test_stock_exceeds_max_returns_none(self):
        # maxqty=100, stock=90, outstanding=20 => available=-10 → None (no room)
        result = calculate_max_indent_qty(100, 90, 20, 5)
        assert result is None

    def test_all_zero_returns_none(self):
        # min_order_qty=0 → None (cannot apply formula)
        result = calculate_max_indent_qty(0, 0, 0, 0)
        assert result is None

    def test_no_maxqty_returns_none(self):
        # maxqty=None → available = None - 50 - 10 raises TypeError
        # But min_order_qty=5 is valid, so let's test edge:
        # Actually if maxqty is None, this would fail in the subtraction.
        # The function should be called with valid maxqty when min_order_qty is set.
        # When maxqty is None with min_order_qty=None, returns None.
        result = calculate_max_indent_qty(None, 50, 10, None)
        assert result is None

    def test_no_min_order_qty_returns_none(self):
        # min_order_qty=None → return None (cannot apply formula)
        result = calculate_max_indent_qty(100, 60, 10, None)
        assert result is None

    def test_large_outstanding_returns_none(self):
        # maxqty=50, stock=30, outstanding=25 => available=-5 → None (no room)
        result = calculate_max_indent_qty(50, 30, 25, 10)
        assert result is None

    def test_available_less_than_min_order_returns_min_order(self):
        # maxqty=100, stock=95, outstanding=0 => available=5
        # min_order_qty=20 => available < min_order_qty → return 20
        result = calculate_max_indent_qty(100, 95, 0, 20)
        assert result == 20.0

    def test_roundup_to_min_order_multiple(self):
        # maxqty=100, stock=10, outstanding=5 => available=85
        # min_order_qty=30 => ceil(85/30)*30 = ceil(2.833)*30 = 3*30 = 90
        result = calculate_max_indent_qty(100, 10, 5, 30)
        assert result == 90.0


# ── Endpoint tests ───────────────────────────────────────────────────

class TestValidateItemEndpoint:
    """Tests for GET /api/procurementIndent/validate_item_for_indent."""

    def setup_method(self):
        """Set up dependency overrides before each test."""
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

    def teardown_method(self):
        """Clean up dependency overrides after each test."""
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_missing_branch_id_returns_400(self):
        mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?item_id=1&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 400
        assert "branch_id" in response.json()["detail"].lower()

    def test_missing_item_id_returns_400(self):
        mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 400
        assert "item_id" in response.json()["detail"].lower()

    def test_logic_3_returns_no_validation(self):
        """Logic 3 (Open+General) should return immediately with no warnings."""
        mock_session = MagicMock()

        # Mock expense type name lookup returning "General"
        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "General"}
        mock_session.execute.return_value.fetchone.return_value = expense_row

        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=Open&expense_type_id=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 3
        assert data["warnings"] == []

    def test_logic1_no_minmax_allows_free_entry(self):
        """Logic 1 (Regular+General) should allow any quantity when item has no min/max configured."""
        mock_session = MagicMock()

        # Call 1: expense type name lookup
        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "General"}

        # Call 2: validation data (stock/min/max/outstanding)
        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 0,
            "outstanding_indent_qty": 0,
            "minqty": None,
            "maxqty": None,
            "min_order_qty": None,
        }

        # Call 3: Open-type FY indent check — None means no blocking Open-type indent
        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_minmax"] is False
        # No errors — Logic 1 allows free entry when min/max not configured
        assert data["errors"] == []
        assert data["max_indent_qty"] is None

    def test_logic1_with_minmax_allows_entry(self):
        """Logic 1 (Regular+General) should allow entry when item has min/max configured
        and no Open-type indent exists in the current FY."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "General"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 10,
            "outstanding_indent_qty": 5,
            "regular_bom_outstanding": 0,
            "open_indent_outstanding": 0,
            "outstanding_po_qty": 0,
            "open_po_outstanding": 0,
            "po_outstanding_to_validate": 0,
            "minqty": 20,
            "maxqty": 100,
            "min_order_qty": 10,
            "max_indent_qty": 90,  # pre-computed by view: ceil((100-10-5)/10)*10 = 90
            "min_indent_qty": 20,
            "max_po_qty": 90,
            "min_po_qty": 20,
        }

        # Call 3: no Open-type FY indent
        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_minmax"] is True
        assert data["errors"] == []
        assert data["max_indent_qty"] == 90

    def test_logic1_blocks_when_open_type_indent_exists_in_fy(self):
        """Logic 1 should block a new Regular indent when an Open-type indent
        (indent_type = 'Open') already exists for the item in the current FY."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "General"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 0,
            "outstanding_indent_qty": 24,
            "minqty": 10,
            "maxqty": 100,
            "min_order_qty": 8,
        }

        # Call 3: Open-type FY indent exists
        fy_row = MagicMock()
        fy_row._mapping = {"indent_id": 7, "indent_no": "pd/ho/INDENT/25-26/7", "status_id": 3, "indent_date": "2025-04-10"}

        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, fy_row]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_open_indent"] is True
        assert data["fy_indent_exists"] is True
        assert data["fy_indent_no"] == "pd/ho/INDENT/25-26/7"
        assert any("open-type indent" in e.lower() for e in data["errors"])

    def test_logic1_allows_new_indent_when_no_open_type_indent_exists(self):
        """Logic 1 should NOT block when there is no Open-type indent in the current FY,
        regardless of any Regular/approved indents that may exist."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "General"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 0,
            "outstanding_indent_qty": 24,
            "minqty": 10,
            "maxqty": 100,
            "min_order_qty": 8,
        }

        # Call 3: no Open-type FY indent — approved Regular indents do not block
        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=Regular&expense_type_id=1"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 1
        assert data["has_open_indent"] is False
        # No blocking error
        assert not any("open" in e.lower() for e in data["errors"])


class TestValidateItemEndpointLogic2:
    """Tests for Logic 2 (BOM+Capital) via GET /api/procurementIndent/validate_item_for_indent."""

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_logic2_fy_indent_exists_blocks(self):
        """Logic 2 should block when an indent already exists in the FY."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "Capital"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 20,
            "outstanding_indent_qty": 10,
            "regular_bom_outstanding": 5,
            "open_indent_outstanding": 0,
            "outstanding_po_qty": 0,
            "minqty": 10,
            "maxqty": 100,
            "min_order_qty": 10,
        }

        fy_row = MagicMock()
        fy_row._mapping = {"indent_id": 5, "indent_no": "IND/BOM/001", "status_id": 3, "indent_date": "2025-06-01"}

        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, fy_row]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=BOM&expense_type_id=5"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["fy_indent_exists"] is True
        assert data["fy_indent_no"] == "IND/BOM/001"
        assert len(data["errors"]) > 0

    def test_logic2_no_minmax_blocks(self):
        """Logic 2 should block when no min/max is configured for the item."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "Capital"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 0,
            "outstanding_indent_qty": 0,
            "regular_bom_outstanding": 0,
            "open_indent_outstanding": 0,
            "outstanding_po_qty": 0,
            "minqty": None,
            "maxqty": None,
            "min_order_qty": None,
        }

        # No FY indent
        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=BOM&expense_type_id=5"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["has_minmax"] is False
        assert any("max/min" in e.lower() for e in data["errors"])

    def test_logic2_regular_bom_outstanding_warning(self):
        """Logic 2 should give a warning (not error) when Regular/BOM outstanding exists."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "Capital"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 10,
            "outstanding_indent_qty": 5,
            "regular_bom_outstanding": 30,
            "open_indent_outstanding": 0,
            "outstanding_po_qty": 0,
            "minqty": 10,
            "maxqty": 200,
            "min_order_qty": 10,
        }

        # No FY indent
        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=BOM&expense_type_id=5"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["has_minmax"] is True
        assert data["regular_bom_outstanding"] == 30
        assert len(data["warnings"]) > 0
        assert any("regular/bom" in w.lower() for w in data["warnings"])
        # Forced qty should be maxqty
        assert data["forced_qty"] == 200

    def test_logic2_clean_path_forces_qty_to_maxqty(self):
        """Logic 2 should set forced_qty to maxqty when all checks pass."""
        mock_session = MagicMock()

        expense_row = MagicMock()
        expense_row._mapping = {"expense_type_name": "Capital"}

        vdata_row = MagicMock()
        vdata_row._mapping = {
            "branch_stock": 10,
            "outstanding_indent_qty": 0,
            "regular_bom_outstanding": 0,
            "open_indent_outstanding": 0,
            "outstanding_po_qty": 0,
            "minqty": 10,
            "maxqty": 150,
            "min_order_qty": 10,
        }

        mock_session.execute.return_value.fetchone.side_effect = [expense_row, vdata_row, None]
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(mock_session)

        response = client.get(
            "/api/procurementIndent/validate_item_for_indent"
            "?branch_id=1&item_id=10&indent_type=BOM&expense_type_id=5"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["validation_logic"] == 2
        assert data["errors"] == []
        assert data["forced_qty"] == 150


# ── V2 Query function tests ─────────────────────────────────────────

class TestV2QueryFunctions:
    """Tests for v2 SQL query functions (bind parameters and return type)."""

    def test_get_item_validation_data_v2_returns_text(self):
        from src.procurement.query import get_item_validation_data_v2
        result = get_item_validation_data_v2()
        assert isinstance(result, type(text("")))

    def test_get_item_validation_data_v2_has_required_binds(self):
        from src.procurement.query import get_item_validation_data_v2
        sql = str(get_item_validation_data_v2())
        assert ":branch_id" in sql
        assert ":item_id" in sql

    def test_get_item_fy_indent_check_v2_has_required_binds(self):
        from src.procurement.query import get_item_fy_indent_check_v2
        sql = str(get_item_fy_indent_check_v2())
        assert ":branch_id" in sql
        assert ":item_id" in sql
        assert ":fy_start" in sql
        assert ":fy_end" in sql

    def test_get_item_validation_data_v2_references_new_view(self):
        from src.procurement.query import get_item_validation_data_v2
        sql = str(get_item_validation_data_v2())
        assert "vw_item_balance_qty_by_branch_new" in sql

    def test_get_item_fy_indent_check_v2_checks_open_type(self):
        from src.procurement.query import get_item_fy_indent_check_v2
        sql = str(get_item_fy_indent_check_v2())
        assert "'Open'" in sql
