"""
Tests for SO-GOVT-001 / SO-GOVT-004:

Govt Sacking sales orders must be routed by canonical invoice-type CODE,
derived from the hard-coded id<->code mapping in `src.sales.constants`
which mirrors the `invoice_type_mst` seed:
    1 = Regular, 2 = Hessian, 3 = Govt Sacking,
    4 = Yarn, 5 = Raw Jute, 7 = Govt Sacking Freight.

The old `if invoice_type == 5` checks assumed an id layout that didn't
match the actual seed — so every Govt Sacking create/update silently
dropped `govtskg` header and `govtskg_dtl` line data on insert. This
suite guards the correct routing.

Covers:
  1. Govt Sacking POST persists header + line extension data.
  2. Backend rejects Govt Sacking POST missing the 5 header fields (by
     name, not by generic "object required").
  3. Backend rejects Govt Sacking POST missing the 3 per-line fields.
  4. Pure-Python resolver helper maps every canonical id to the right code.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh
from src.sales.constants import (
    INVOICE_TYPE_CODES,
    INVOICE_TYPE_IDS,
    resolve_invoice_type_code,
    is_govt_skg_invoice,
)


client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(mapping: dict):
    r = MagicMock()
    r._mapping = mapping
    return r


def _make_govt_skg_session():
    """Build a MagicMock Session whose `db.execute(...)` records the SQL text
    of every call so tests can assert which inserts ran.

    Header and detail INSERTs auto-assign incrementing lastrowid values.
    """
    session = MagicMock()

    executed: list[dict] = []
    counter = {"sales_order_id": 1000, "dtl_id": 5000}

    def fake_execute(query, params=None):
        sql_text = str(query).lower()
        executed.append({"sql": sql_text, "params": params or {}})

        result = MagicMock()

        # Header insert
        if "insert into sales_order" in sql_text and "sales_order_dtl" not in sql_text and "sales_order_govtskg" not in sql_text and "sales_order_jute" not in sql_text and "sales_order_additional" not in sql_text:
            counter["sales_order_id"] += 1
            result.lastrowid = counter["sales_order_id"]
            return result

        # Detail line insert
        if "insert into sales_order_dtl" in sql_text and "gst" not in sql_text and "hessian" not in sql_text and "govtskg" not in sql_text and "jute" not in sql_text:
            counter["dtl_id"] += 1
            result.lastrowid = counter["dtl_id"]
            return result

        # Anything else (gst, govtskg dtl, govtskg hdr, additional, etc.)
        result.lastrowid = 1
        result.fetchone.return_value = None
        result.fetchall.return_value = []
        return result

    session.execute.side_effect = fake_execute
    session._executed = executed  # exposed for assertions
    return session


def _valid_govt_skg_payload():
    return {
        "branch": 1,
        "party": 10,
        "date": "2026-04-08",
        "invoice_type": 3,  # dev3 id for Govt Sacking
        "items": [
            {
                "item": 100,
                "quantity": 5,
                "qty_uom": 1,
                "rate": 1000.0,
                "discount_type": 0,
                "net_amount": 5000.0,
                "total_amount": 5000.0,
                "govtskg_dtl": {
                    "pack_sheet": 10,
                    "net_weight": 250.5,
                    "total_weight": 260.0,
                },
            }
        ],
        "govtskg": {
            "pcso_no": "PCSO-2026-001",
            "pcso_date": "2026-04-01",
            "administrative_office_address": "DGS&D Kolkata, West Bengal",
            "destination_rail_head": "Howrah",
            "loading_point": "Titagarh Mill",
        },
    }


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestCreateGovtSkgSalesOrder:
    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._session = _make_govt_skg_session()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        app.dependency_overrides[get_tenant_db] = lambda: self._session
        yield
        app.dependency_overrides.clear()

    def test_govt_skg_create_persists_header_and_line_data(self):
        payload = _valid_govt_skg_payload()
        response = client.post("/api/salesOrder/create_sales_order", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("sales_order_id")

        # Find the govtskg header insert
        govtskg_hdr_calls = [
            e for e in self._session._executed
            if "insert into sales_order_govtskg" in e["sql"]
            and "sales_order_govtskg_dtl" not in e["sql"]
        ]
        assert len(govtskg_hdr_calls) == 1, (
            "Expected exactly one INSERT into sales_order_govtskg (header). "
            f"Got {len(govtskg_hdr_calls)}. "
            f"Bug SO-GOVT-001: routing was id-based and dropped govtskg silently."
        )
        hdr_params = govtskg_hdr_calls[0]["params"]
        assert hdr_params.get("pcso_no") == "PCSO-2026-001"
        assert hdr_params.get("pcso_date") == "2026-04-01"
        assert hdr_params.get("administrative_office_address") == "DGS&D Kolkata, West Bengal"
        assert hdr_params.get("destination_rail_head") == "Howrah"
        assert hdr_params.get("loading_point") == "Titagarh Mill"

        # Find the govtskg detail insert (per line)
        govtskg_dtl_calls = [
            e for e in self._session._executed
            if "insert into sales_order_govtskg_dtl" in e["sql"]
        ]
        assert len(govtskg_dtl_calls) == 1, (
            "Expected one INSERT into sales_order_govtskg_dtl. "
            f"Got {len(govtskg_dtl_calls)}."
        )
        dtl_params = govtskg_dtl_calls[0]["params"]
        assert dtl_params.get("pack_sheet") == 10
        assert dtl_params.get("net_weight") == 250.5
        assert dtl_params.get("total_weight") == 260.0

    def test_govt_skg_create_rejects_missing_header_fields(self):
        payload = _valid_govt_skg_payload()
        payload["govtskg"].pop("pcso_no")

        response = client.post("/api/salesOrder/create_sales_order", json=payload)

        assert response.status_code == 400, response.text
        detail = response.json().get("detail", "")
        assert "pcso_no" in detail
        # And no govtskg insert should have been executed
        assert not any(
            "insert into sales_order_govtskg" in e["sql"]
            for e in self._session._executed
        )

    def test_govt_skg_create_accepts_missing_line_fields(self):
        # pack_sheet / net_weight / total_weight are no longer required at the
        # line level — the UI removed those columns. Header validation still
        # applies; line-level extras are optional.
        payload = _valid_govt_skg_payload()
        payload["items"][0]["govtskg_dtl"].pop("pack_sheet")

        response = client.post("/api/salesOrder/create_sales_order", json=payload)

        assert response.status_code == 200, response.text

    def test_govt_skg_create_rejects_absent_govtskg_with_field_level_message(self):
        """Regression for the SO 11 edit bug: when the UI forwards no 'govtskg'
        header at all (or an empty dict, after JSON.stringify drops undefined
        values), the error should still name the 5 specific fields, not a
        generic 'object required' message."""
        payload = _valid_govt_skg_payload()
        payload.pop("govtskg")

        response = client.post("/api/salesOrder/create_sales_order", json=payload)
        assert response.status_code == 400, response.text
        detail = response.json().get("detail", "")
        for field in (
            "pcso_no",
            "pcso_date",
            "administrative_office_address",
            "destination_rail_head",
            "loading_point",
        ):
            assert f"govtskg.{field}" in detail, f"Missing field {field} not named in: {detail}"

    def test_govt_skg_create_rejects_empty_govtskg_dict_with_field_level_message(self):
        payload = _valid_govt_skg_payload()
        payload["govtskg"] = {}

        response = client.post("/api/salesOrder/create_sales_order", json=payload)
        assert response.status_code == 400, response.text
        detail = response.json().get("detail", "")
        assert "govtskg.pcso_no" in detail
        assert "govtskg.loading_point" in detail


# ---------------------------------------------------------------------------
# Resolver unit tests
# ---------------------------------------------------------------------------


class TestResolveInvoiceTypeCode:
    """Unit tests for the pure id->code resolver. Mirrors the canonical
    invoice_type_mst seed:
        1 = Regular, 2 = Hessian, 3 = Govt Sacking,
        4 = Yarn, 5 = Raw Jute, 7 = Govt Sacking Freight.
    """

    def test_canonical_ids_match_invoice_type_mst_seed(self):
        assert INVOICE_TYPE_IDS["REGULAR"] == 1
        assert INVOICE_TYPE_IDS["HESSIAN"] == 2
        assert INVOICE_TYPE_IDS["GOVT_SKG"] == 3
        assert INVOICE_TYPE_IDS["JUTE_YARN"] == 4
        assert INVOICE_TYPE_IDS["RAW_JUTE"] == 5
        assert INVOICE_TYPE_IDS["GOVT_SKG_FREIGHT"] == 7

    def test_resolve_invoice_type_code_all_known_ids(self):
        assert resolve_invoice_type_code(1) == INVOICE_TYPE_CODES["REGULAR"]
        assert resolve_invoice_type_code(2) == INVOICE_TYPE_CODES["HESSIAN"]
        assert resolve_invoice_type_code(3) == INVOICE_TYPE_CODES["GOVT_SKG"]
        assert resolve_invoice_type_code(4) == INVOICE_TYPE_CODES["JUTE_YARN"]
        assert resolve_invoice_type_code(5) == INVOICE_TYPE_CODES["RAW_JUTE"]
        assert resolve_invoice_type_code(7) == INVOICE_TYPE_CODES["GOVT_SKG_FREIGHT"]

    def test_resolve_invoice_type_code_accepts_string_id(self):
        assert resolve_invoice_type_code("3") == INVOICE_TYPE_CODES["GOVT_SKG"]

    def test_resolve_invoice_type_code_unknown_id(self):
        assert resolve_invoice_type_code(999) == INVOICE_TYPE_CODES["UNKNOWN"]
        assert resolve_invoice_type_code(None) == INVOICE_TYPE_CODES["UNKNOWN"]
        assert resolve_invoice_type_code("not-a-number") == INVOICE_TYPE_CODES["UNKNOWN"]
        # id 6 is intentionally unused in the seed
        assert resolve_invoice_type_code(6) == INVOICE_TYPE_CODES["UNKNOWN"]

    def test_is_govt_skg_invoice(self):
        assert is_govt_skg_invoice(3) is True
        assert is_govt_skg_invoice("3") is True
        assert is_govt_skg_invoice(2) is False
        assert is_govt_skg_invoice(7) is False  # Govt Sacking Freight is a distinct code
        assert is_govt_skg_invoice(None) is False
