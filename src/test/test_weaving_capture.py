"""Weaving entry capture is allowed BEFORE the Loom->Quality map is done."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


class TestWeavingCaptureNoQuality:
    def test_entry_create_allowed_when_quality_unmapped(self):
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = None   # no existing row
        session.execute.return_value.scalar.return_value = None     # no beam
        session.execute.return_value.lastrowid = 555
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.weaving_entry._derive_branch_id", return_value=2), \
                 patch("src.juteProduction.weaving_entry._derive_co_id", return_value=1), \
                 patch("src.juteProduction.weaving_entry._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_entry._mapped_quality_id", return_value=None), \
                 patch("src.juteProduction.weaving_entry.require_edit_if_locked"), \
                 patch("src.juteProduction.weaving_entry._sync_jugar_chain_after_write"):
                resp = client.post("/api/weavingProd/entry_create", json={
                    "tran_date": "2026-07-07", "spell": "A1", "machine_id": 42,
                    "cuts": 3, "close_jugar": 1.0,
                })
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["weaving_daily_id"] == 555
        assert resp.json()["data"]["weaving_quality_id"] is None
