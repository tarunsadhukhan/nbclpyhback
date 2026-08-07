"""process_status: unlocked -> false; locked + drift -> reprocess_needed."""
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.config.db import get_tenant_db
from src.authorization.utils import get_current_user_with_refresh

client = TestClient(app)

URL = "/api/weavingProd/process_status?co_id=1&branch_id=2&tran_date=2026-07-07&spell=A1"


class TestProcessStatus:
    def _run(self, session, lock):
        app.dependency_overrides[get_tenant_db] = lambda: session
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 1}
        try:
            with patch("src.juteProduction.weaving_process._resolve_spell", return_value=91), \
                 patch("src.juteProduction.weaving_process.get_process_lock", return_value=lock):
                return client.get(URL)
        finally:
            app.dependency_overrides.clear()

    def test_unlocked_returns_false(self):
        resp = self._run(MagicMock(), lock=None)
        assert resp.status_code == 200
        assert resp.json()["data"] == {"locked": False, "reprocess_needed": False}

    def test_locked_with_drift_flags_reprocess(self):
        session = MagicMock()
        session.execute.return_value.fetchone.return_value = MagicMock(weaving_log_id=1)  # drift
        lock = MagicMock(weaving_process_lock_id=9, is_locked=1, reprocess_needed=0)
        resp = self._run(session, lock=lock)
        assert resp.status_code == 200
        assert resp.json()["data"]["reprocess_needed"] is True
