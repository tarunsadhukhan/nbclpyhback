from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.juteProduction.spinning_lock import (
    SPINNING_MENU_PATH,
    is_unit_locked,
    require_edit_if_locked,
    flag_reprocess_if_locked,
)


class TestSpinningLock:
    def test_menu_path(self):
        assert SPINNING_MENU_PATH == "juteProduction/spinning"

    def test_unlocked_unit_passes_gate(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)  # no raise

    def test_locked_unit_without_edit_403(self):
        db = MagicMock()
        lock_row = MagicMock(is_locked=1)
        db.execute.return_value.fetchone.return_value = lock_row
        db.execute.return_value.scalar.return_value = 3  # Write, not Edit
        with pytest.raises(HTTPException) as exc:
            require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)
        assert exc.value.status_code == 403

    def test_locked_unit_with_edit_passes(self):
        db = MagicMock()
        lock_row = MagicMock(is_locked=1)
        db.execute.return_value.fetchone.return_value = lock_row
        db.execute.return_value.scalar.return_value = 4
        require_edit_if_locked(db, {"user_id": 1}, 1, None, "2026-07-01", 5)  # no raise

    def test_flag_reprocess_noops_on_missing_ids(self):
        db = MagicMock()
        flag_reprocess_if_locked(db, None, "2026-07-01", 5)
        db.execute.assert_not_called()

    def test_is_unit_locked_false_when_no_row(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = None
        assert is_unit_locked(db, 1, None, "2026-07-01", 5) is False
