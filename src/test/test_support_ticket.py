# src/test/test_support_ticket.py
"""Tests for the support-ticket feature.

Covers the pure lifecycle helpers (constants) plus a few endpoint paths with the
console session mocked.
"""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.common.supportTicket import constants as C
from src.authorization.utils import get_current_user_with_refresh, verify_access_token
from src.config.db import get_tenant_db
from src.main import app

client = TestClient(app)


# ── Pure lifecycle helpers ──────────────────────────────────────────────────────
class TestLifecycleHelpers:
    def test_resolve_transition_valid(self):
        # Raised -> Open via "open"
        new_status, error = C.resolve_transition(C.STATUS_RAISED, "open")
        assert error is None
        assert new_status == C.STATUS_OPEN

    def test_resolve_transition_invalid_from_status(self):
        # Cannot "start" a ticket that is still Raised (must be Open/On-Hold first)
        new_status, error = C.resolve_transition(C.STATUS_RAISED, "start")
        assert new_status is None
        assert "Cannot 'start'" in error

    def test_resolve_transition_unknown_action(self):
        new_status, error = C.resolve_transition(C.STATUS_OPEN, "explode")
        assert new_status is None
        assert "Unknown action" in error

    def test_reopen_from_terminal_statuses(self):
        for terminal in (C.STATUS_RESOLVED, C.STATUS_CLOSED, C.STATUS_REJECTED):
            new_status, error = C.resolve_transition(terminal, "reopen")
            assert error is None
            assert new_status == C.STATUS_OPEN

    def test_close_and_reject_require_reason(self):
        assert C.transition_requires_reason("close") is True
        assert C.transition_requires_reason("reject") is True
        assert C.transition_requires_reason("open") is False
        assert C.transition_requires_reason("resolve") is False

    def test_validate_raise_fields(self):
        # valid
        C.validate_raise_fields(C.PRIORITY_HIGH, "bug")
        C.validate_raise_fields(C.PRIORITY_LOW, None)
        # invalid priority
        try:
            C.validate_raise_fields(99, "bug")
            assert False, "expected ValueError"
        except ValueError:
            pass
        # invalid category
        try:
            C.validate_raise_fields(C.PRIORITY_LOW, "not_a_category")
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_build_meta_shape(self):
        meta = C.build_meta()
        assert {"statuses", "priorities", "categories", "close_reasons", "actions"} <= set(meta)
        labels = {s["label"] for s in meta["statuses"]}
        assert {"Raised", "Open", "In Progress", "On Hold", "Resolved", "Closed", "Rejected"} == labels


# ── Endpoint: /meta ─────────────────────────────────────────────────────────────
class TestMetaEndpoint:
    def setup_method(self):
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.pop(verify_access_token, None)

    def test_meta_returns_reference_data(self):
        resp = client.get("/api/supportTicket/meta")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "statuses" in data
        assert "priorities" in data


# ── Endpoint: portal raise validation ───────────────────────────────────────────
class TestPortalRaiseValidation:
    def setup_method(self):
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 5, "type": "portal"}

        def _override_tenant():
            yield MagicMock()

        app.dependency_overrides[get_tenant_db] = _override_tenant

    def teardown_method(self):
        app.dependency_overrides.pop(get_current_user_with_refresh, None)
        app.dependency_overrides.pop(get_tenant_db, None)

    def test_invalid_priority_rejected_before_db(self):
        resp = client.post(
            "/api/supportTicket/portal/raise",
            json={"subject": "Page broken", "description": "It crashed", "priority": 99},
        )
        assert resp.status_code == 400
        assert "priority" in resp.json()["detail"].lower()


# ── Endpoint: manage transition with mocked console session ─────────────────────
def _ctx(mock_session):
    cm = MagicMock()
    cm.__enter__.return_value = mock_session
    cm.__exit__.return_value = False
    return cm


class TestManageTransition:
    def setup_method(self):
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.pop(verify_access_token, None)

    @patch("src.common.supportTicket.manage.Session")
    def test_unknown_action_returns_400(self, mock_session_cls):
        mock_session = MagicMock()
        # _actor() lookup of the acting user's name
        actor_row = MagicMock()
        actor_row._mapping = {"con_user_name": "VOW Dev"}
        mock_session.execute.return_value.fetchone.return_value = actor_row
        # ticket fetched via session.get
        ticket = MagicMock()
        ticket.active = 1
        ticket.status_id = C.STATUS_OPEN
        mock_session.get.return_value = ticket
        mock_session_cls.return_value = _ctx(mock_session)

        resp = client.post(
            "/api/supportTicket/manage/transition",
            json={"ticket_id": 1, "action": "explode"},
        )
        assert resp.status_code == 400
        assert "Unknown action" in resp.json()["detail"]

    @patch("src.common.supportTicket.manage.Session")
    def test_close_without_reason_returns_400(self, mock_session_cls):
        mock_session = MagicMock()
        actor_row = MagicMock()
        actor_row._mapping = {"con_user_name": "VOW Dev"}
        mock_session.execute.return_value.fetchone.return_value = actor_row
        ticket = MagicMock()
        ticket.active = 1
        ticket.status_id = C.STATUS_IN_PROGRESS
        mock_session.get.return_value = ticket
        mock_session_cls.return_value = _ctx(mock_session)

        resp = client.post(
            "/api/supportTicket/manage/transition",
            json={"ticket_id": 1, "action": "close"},
        )
        assert resp.status_code == 400
        assert "reason" in resp.json()["detail"].lower()


class TestManageList:
    def setup_method(self):
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.pop(verify_access_token, None)

    @patch("src.common.supportTicket.manage.Session")
    def test_list_returns_data_and_total(self, mock_session_cls):
        mock_session = MagicMock()
        result = MagicMock()
        result.scalar.return_value = 1
        row = MagicMock()
        row._mapping = {"ticket_id": 1, "ticket_no": "TKT-000001", "subject": "X", "status_id": 1}
        result.fetchall.return_value = [row]
        mock_session.execute.return_value = result
        mock_session_cls.return_value = _ctx(mock_session)

        resp = client.get("/api/supportTicket/manage/list?page=1&limit=20")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["data"][0]["ticket_no"] == "TKT-000001"


# ── Attachments ──────────────────────────────────────────────────────────────────
class TestAttachmentHelpers:
    def test_attachment_kind_ext_known(self):
        assert C.attachment_kind_ext("image/png") == ("image", "png")
        assert C.attachment_kind_ext("application/pdf") == ("document", "pdf")
        # case-insensitive
        assert C.attachment_kind_ext("IMAGE/JPEG") == ("image", "jpg")

    def test_attachment_kind_ext_unknown(self):
        assert C.attachment_kind_ext("application/x-msdownload") is None
        assert C.attachment_kind_ext(None) is None

    def test_public_attachment_shape(self):
        from src.common.supportTicket import attachment_utils as A

        mapping = {
            "attachment_id": 7,
            "ticket_id": 3,
            "kind": "image",
            "s3_key": "support/3/image_1.png",
            "original_filename": "shot.png",
            "mime_type": "image/png",
            "size_bytes": 1234,
            "uploaded_by_type": "reporter",
            "uploaded_by_name": "Jane",
            "uploaded_at": None,
        }
        out = A.public_attachment(mapping, with_url=False)
        # never leak the storage key
        assert "s3_key" not in out and "s3_bucket" not in out
        assert out["attachment_id"] == 7 and out["kind"] == "image"


class TestManageAttachmentUpload:
    def setup_method(self):
        app.dependency_overrides[verify_access_token] = lambda: {"user_id": 1}

    def teardown_method(self):
        app.dependency_overrides.pop(verify_access_token, None)

    @patch("src.common.supportTicket.attachment_utils.s3_client")
    @patch("src.common.supportTicket.manage.Session")
    def test_unsupported_type_rejected(self, mock_session_cls, mock_s3):
        # Validation happens before any DB/S3 work.
        resp = client.post(
            "/api/supportTicket/manage/ticket/1/attachment",
            files={"file": ("evil.exe", b"MZ\x90", "application/x-msdownload")},
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]
        mock_s3.upload_bytes.assert_not_called()

    @patch("src.common.supportTicket.attachment_utils.s3_client")
    @patch("src.common.supportTicket.manage.Session")
    def test_image_upload_success(self, mock_session_cls, mock_s3):
        mock_s3.get_bucket.return_value = "test-bucket"
        mock_s3.presigned_get_url.return_value = "https://signed.example/x"
        mock_session = MagicMock()
        actor_row = MagicMock()
        actor_row._mapping = {"con_user_name": "VOW Dev"}
        mock_session.execute.return_value.fetchone.return_value = actor_row
        ticket = MagicMock()
        ticket.active = 1
        mock_session.get.return_value = ticket

        # store_attachment flushes then reads attachment_id off the ORM object;
        # simulate the PK assignment on flush.
        def _flush():
            for obj in list(mock_session.add.call_args_list):
                pass
        mock_session.flush.side_effect = None
        mock_session_cls.return_value = _ctx(mock_session)

        resp = client.post(
            "/api/supportTicket/manage/ticket/1/attachment",
            files={"file": ("shot.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        )
        assert resp.status_code == 200
        mock_s3.upload_bytes.assert_called_once()
        assert resp.json()["data"]["kind"] == "image"
