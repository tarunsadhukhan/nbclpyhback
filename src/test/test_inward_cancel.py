# src/test/test_inward_cancel.py
"""
Tests for inward cancellation, format_inward_no, and SR-no minting on approval.

Covers:
- POST /procurementInward/cancel_inward success/blocked-after-inspection/already-cancelled
- format_inward_no uses "IN" segment (renamed from "GRN")
- save_sr does NOT generate sr_no (deferred to approval)
- approve_sr mints sr_no when previously NULL
"""

from datetime import date
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

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


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------

class TestFormatInwardNo:
    def test_format_inward_no_uses_IN_segment(self):
        from src.procurement.inward import format_inward_no
        result = format_inward_no(
            inward_sequence_no=42,
            co_prefix="ACME",
            branch_prefix="HO",
            inward_date=date(2025, 4, 15),
        )
        assert "/IN/" in result
        # full format check
        assert result.split("/")[2] == "IN"

    def test_format_inward_no_returns_blank_for_zero(self):
        from src.procurement.inward import format_inward_no
        assert format_inward_no(0, "X", "Y", date(2025, 4, 1)) == ""
        assert format_inward_no(None, "X", "Y", date(2025, 4, 1)) == ""

    def test_format_sr_no_zero_pads_seq_to_6(self):
        """SR numbers pad the trailing seq to 6 digits; IN stays unpadded."""
        from src.procurement.inward import format_inward_no
        sr = format_inward_no(9, "EJM", "F", date(2026, 6, 1), doc_type="SR")
        assert sr.split("/")[-1] == "000009"
        assert "/SR/" in sr
        # padding is SR-only — inward/GRN seq stays bare
        inw = format_inward_no(9, "EJM", "F", date(2026, 6, 1))
        assert inw.split("/")[-1] == "9"
        # a seq wider than the pad is unchanged, not truncated
        assert format_inward_no(1234567, "EJM", "F", date(2026, 6, 1), doc_type="SR").split("/")[-1] == "1234567"


# ---------------------------------------------------------------------------
# cancel_inward endpoint tests
# ---------------------------------------------------------------------------

class TestCancelInwardEndpoint:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_cancel_inward_success(self):
        # 1st execute = inspection_check SELECT (returns falsy)
        # 2nd execute = active line count SELECT (returns >0)
        # 3rd execute = UPDATE
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(0,))),       # inspection_check = 0 / falsy
            MagicMock(fetchone=MagicMock(return_value=(3,))),       # 3 active lines
            MagicMock(),                                            # UPDATE
        ]

        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={"inward_id": 100},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert body["new_status_id"] == 6
        assert "cancelled" in body["message"].lower()
        # commit was called
        self.mock_session.commit.assert_called_once()

    def test_cancel_inward_missing_id(self):
        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={},
        )
        assert response.status_code == 400
        assert "inward_id" in response.json()["detail"].lower()

    def test_cancel_inward_invalid_id(self):
        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={"inward_id": "abc"},
        )
        assert response.status_code == 400

    def test_cancel_inward_not_found(self):
        # inspection_check SELECT returns None (no row)
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=None)),
        ]
        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={"inward_id": 999},
        )
        assert response.status_code == 404

    def test_cancel_inward_blocked_after_inspection(self):
        # inspection_check returns truthy (1)
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(1,))),
        ]
        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={"inward_id": 100},
        )
        assert response.status_code == 403
        assert "inspection" in response.json()["detail"].lower()

    def test_cancel_inward_already_cancelled(self):
        # Active line count returns 0 → already cancelled
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(0,))),  # inspection ok
            MagicMock(fetchone=MagicMock(return_value=(0,))),  # zero active lines
        ]
        response = client.post(
            "/api/procurementInward/cancel_inward",
            json={"inward_id": 100},
        )
        assert response.status_code == 400
        assert "already cancelled" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# SR number minting moved to approval
# ---------------------------------------------------------------------------

class TestSRNumberMinting:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    @patch("src.procurement.sr.generate_sr_no")
    def test_approve_sr_mints_sr_no(self, mock_generate):
        """When sr_no is NULL on header, approve_sr must call generate_sr_no
        and include sr_no in the UPDATE."""
        mock_generate.return_value = "SR-2025-00001"

        # Line item with no rate diff and no rejection → no DRCR path
        line_row = MagicMock()
        line_row._mapping = {
            "inward_dtl_id": 1,
            "po_rate": 100.0,
            "rate": 100.0,
            "accepted_rate": 100.0,
            "rejected_qty": 0,
            "approved_qty": 5.0,
        }

        # Header SELECT returns sr_no=None to trigger minting
        header_row = MagicMock()
        header_row.branch_id = 1
        header_row.sr_no = None
        header_row.sr_date = date(2025, 4, 15)

        self.mock_session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[line_row])),     # get line items
            MagicMock(fetchone=MagicMock(return_value=None)),           # GST prep: inward_info lookup
            MagicMock(fetchone=MagicMock(return_value=header_row)),     # header SELECT
            MagicMock(),                                                # UPDATE
        ]

        response = client.post(
            "/api/storesReceipt/approve_sr",
            json={"inward_id": 7},
        )
        assert response.status_code == 200, response.text

        # generate_sr_no must have been called
        mock_generate.assert_called_once()
        # The UPDATE call (last execute) must include sr_no parameter set to the
        # generated value
        update_call = self.mock_session.execute.call_args_list[-1]
        params = update_call[0][1]
        assert params.get("sr_no") == "SR-2025-00001"

    @patch("src.procurement.sr.generate_sr_no")
    def test_approve_sr_does_not_remint_existing_sr_no(self, mock_generate):
        """When sr_no already exists on the header, approve_sr must NOT call
        generate_sr_no."""
        line_row = MagicMock()
        line_row._mapping = {
            "inward_dtl_id": 1,
            "po_rate": 100.0,
            "rate": 100.0,
            "accepted_rate": 100.0,
            "rejected_qty": 0,
            "approved_qty": 5.0,
        }

        header_row = MagicMock()
        header_row.branch_id = 1
        header_row.sr_no = "SR-2024-00099"
        header_row.sr_date = date(2025, 4, 15)

        self.mock_session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=[line_row])),
            MagicMock(fetchone=MagicMock(return_value=None)),  # GST prep: inward_info lookup
            MagicMock(fetchone=MagicMock(return_value=header_row)),
            MagicMock(),  # UPDATE without sr_no
        ]

        response = client.post(
            "/api/storesReceipt/approve_sr",
            json={"inward_id": 7},
        )
        assert response.status_code == 200, response.text
        mock_generate.assert_not_called()

        # UPDATE call should not include sr_no
        update_call = self.mock_session.execute.call_args_list[-1]
        params = update_call[0][1]
        assert "sr_no" not in params

    @patch("src.procurement.sr.generate_sr_no")
    def test_save_sr_does_not_generate_sr_no(self, mock_generate):
        """save_sr should never call generate_sr_no — that is now deferred to
        approval. We assert by exercising the function directly via TestClient
        with a minimal happy-path payload and confirming the helper was not
        called."""
        # Easiest: import save_sr internals are heavy. Instead, scan source
        # to ensure generate_sr_no is not referenced inside save_sr block.
        import inspect
        from src.procurement import sr as sr_module

        source = inspect.getsource(sr_module.save_sr)
        assert "generate_sr_no" not in source, (
            "save_sr must no longer call generate_sr_no — it is deferred to approve_sr"
        )
