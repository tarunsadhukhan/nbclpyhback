"""Locked units serve the frozen log; unlocked units recompute live."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)


class TestFrozenReads:
    def test_locked_unit_reads_log(self):
        session = MagicMock()
        frozen = MagicMock()
        frozen._mapping = {"weaving_daily_id": 1, "machine_id": 42,
                           "production_yds": 100.0, "efficiency": 88.0,
                           "tran_date": "2026-07-07"}
        session.execute.return_value.fetchall.return_value = [frozen]
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.weaving_entry._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_entry.is_unit_locked", return_value=True):
                resp = client.get("/api/weavingProd/entries_by_date"
                                  "?co_id=1&branch_id=2&tran_date=2026-07-07&spell=A1")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"][0]["efficiency"] == 88.0
