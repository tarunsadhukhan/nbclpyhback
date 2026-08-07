"""Tests for MR approval-permission assembly (_build_mr_permissions).

get_mr_by_id returns level-aware permissions so the UI action buttons follow
the approval hierarchy: Approve/Reject only for the current-level approver, and
(frontend) Pending only at the highest level. This helper wraps the shared
calculate_approval_permissions and adds the MR-specific rules.
"""

from unittest.mock import MagicMock, patch

from src.juteProcurement.mr import _build_mr_permissions, MR_STATUS_OPEN, MR_STATUS_PENDING_APPROVAL


def _row(mapping):
    r = MagicMock()
    r._mapping = mapping
    return r


class TestBuildMrPermissions:
    def test_no_menu_id_returns_empty_and_skips_db(self):
        db = MagicMock()
        perms, max_level = _build_mr_permissions(db, None, 2, MR_STATUS_OPEN, None, 10)
        assert perms == {}
        assert max_level is None
        db.execute.assert_not_called()

    def test_missing_branch_or_user_returns_empty(self):
        db = MagicMock()
        assert _build_mr_permissions(db, 55, None, MR_STATUS_OPEN, None, 10) == ({}, None)
        assert _build_mr_permissions(db, 55, 2, MR_STATUS_OPEN, None, None) == ({}, None)
        db.execute.assert_not_called()

    @patch("src.juteProcurement.mr.calculate_approval_permissions")
    def test_open_permissions_returned_verbatim(self, mock_calc):
        # Reject is NOT surfaced in Open — it only appears in Pending Approval
        # (status 20), matching the shared bar. Helper must not add canReject.
        mock_calc.return_value = {"canSave": True, "canApprove": True}
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = _row({"max_level": 3})

        perms, max_level = _build_mr_permissions(db, 55, 2, MR_STATUS_OPEN, None, 10)

        assert perms["canApprove"] is True
        assert "canReject" not in perms  # never force-added for Open
        assert max_level == 3

    @patch("src.juteProcurement.mr.calculate_approval_permissions")
    def test_pending_approval_uses_calc_permissions_verbatim(self, mock_calc):
        # In status 20 the helper must NOT tamper with reject — it reflects the
        # current-level match computed by calculate_approval_permissions.
        mock_calc.return_value = {"canApprove": False, "canReject": False, "canViewApprovalLog": True}
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = _row({"max_level": 3})

        perms, max_level = _build_mr_permissions(db, 55, 2, MR_STATUS_PENDING_APPROVAL, 2, 10)

        assert perms["canApprove"] is False
        assert perms["canReject"] is False
        assert max_level == 3

    @patch("src.juteProcurement.mr.calculate_approval_permissions")
    def test_calc_error_falls_back_to_empty(self, mock_calc):
        mock_calc.side_effect = RuntimeError("boom")
        db = MagicMock()
        assert _build_mr_permissions(db, 55, 2, MR_STATUS_OPEN, None, 10) == ({}, None)
