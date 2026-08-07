# src/test/test_inward_update_qty.py
"""
Regression tests for PUT /procurementInward/update_inward line-qty persistence.

Bug: lines were matched ONLY by po_dtl_id, so no-PO inwards (po_dtl_id NULL)
were silently skipped — API returned 200 but challan_qty/inward_qty never
changed. Also the UPDATE never set challan_qty at all.

Covers:
- update matches line by inward_dtl_id when payload carries it (no po_dtl_id)
- update falls back to po_dtl_id when inward_dtl_id absent
- unmatched line -> 400 (no silent skip)
- update_proc_inward_dtl SQL sets BOTH challan_qty and inward_qty
"""

from unittest.mock import MagicMock

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


class TestUpdateProcInwardDtlQuery:
    def test_sql_updates_both_qty_columns(self):
        from src.procurement.query import update_proc_inward_dtl
        sql = str(update_proc_inward_dtl())
        assert "challan_qty = :inward_qty" in sql
        assert "inward_qty = :inward_qty" in sql
        assert "WHERE inward_dtl_id = :inward_dtl_id" in sql


class TestUpdateInwardEndpoint:

    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = _override_auth
        self.mock_session = MagicMock()
        app.dependency_overrides[get_tenant_db] = _make_mock_db_override(self.mock_session)

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    @staticmethod
    def _payload(items):
        return {
            "id": "106",
            "branch": "12",
            "supplier": "100000077",
            "inward_date": "2026-07-14",
            "challan_no": "122",
            "challan_date": "2026-07-14",
            "items": items,
        }

    def _run(self, items, find_dtl_row):
        """Drive update_inward with mocked execute sequence and return response.

        Execute order: inspection SELECT, cancelled-count SELECT, header UPDATE,
        find-dtl SELECT, dtl UPDATE.
        """
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(0,))),          # inspection_check falsy
            MagicMock(fetchone=MagicMock(return_value=(1,))),          # 1 active line
            MagicMock(),                                               # header UPDATE
            MagicMock(fetchone=MagicMock(return_value=find_dtl_row)),  # find dtl
            MagicMock(),                                               # dtl UPDATE
        ]
        return client.put("/api/procurementInward/update_inward", json=self._payload(items))

    def test_update_matches_by_inward_dtl_id_without_po(self):
        """No-PO inward: payload has inward_dtl_id, no po_dtl_id — line must update."""
        response = self._run(
            [{"inward_dtl_id": "273", "item": "269919", "quantity": 90, "uom": "143"}],
            find_dtl_row=(273,),
        )
        assert response.status_code == 200, response.text

        # find-dtl SELECT keyed on inward_dtl_id
        find_sql = str(self.mock_session.execute.call_args_list[3].args[0])
        assert "inward_dtl_id = :inward_dtl_id" in find_sql
        find_params = self.mock_session.execute.call_args_list[3].args[1]
        assert find_params["inward_dtl_id"] == 273

        # dtl UPDATE ran with the new qty
        upd_params = self.mock_session.execute.call_args_list[4].args[1]
        assert upd_params["inward_dtl_id"] == 273
        assert upd_params["inward_qty"] == 90.0
        self.mock_session.commit.assert_called_once()

    def test_update_falls_back_to_po_dtl_id(self):
        response = self._run(
            [{"po_dtl_id": "55", "item": "269919", "quantity": 42, "uom": "143"}],
            find_dtl_row=(273,),
        )
        assert response.status_code == 200, response.text
        find_sql = str(self.mock_session.execute.call_args_list[3].args[0])
        assert "po_dtl_id = :po_dtl_id" in find_sql
        upd_params = self.mock_session.execute.call_args_list[4].args[1]
        assert upd_params["inward_qty"] == 42.0

    def test_update_with_no_line_identifier_is_400_not_silent_success(self):
        """Old bug: no identifier -> silent skip + 200. Must now be 400."""
        self.mock_session.execute.side_effect = [
            MagicMock(fetchone=MagicMock(return_value=(0,))),  # inspection_check falsy
            MagicMock(fetchone=MagicMock(return_value=(1,))),  # 1 active line
            MagicMock(),                                       # header UPDATE
        ]
        response = client.put(
            "/api/procurementInward/update_inward",
            json=self._payload([{"item": "269919", "quantity": 90, "uom": "143"}]),
        )
        assert response.status_code == 400
        assert "matched" in response.json()["detail"].lower()
        self.mock_session.commit.assert_not_called()
        self.mock_session.rollback.assert_called_once()

    def test_update_unmatched_inward_dtl_id_is_400(self):
        response = self._run(
            [{"inward_dtl_id": "999", "item": "269919", "quantity": 90, "uom": "143"}],
            find_dtl_row=None,
        )
        assert response.status_code == 400
        self.mock_session.commit.assert_not_called()
