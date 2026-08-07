"""Tests for the generic attachment subsystem.

Patterns mirror src/test/test_hrms_employee.py — FastAPI TestClient + dependency
overrides for DB / auth. The S3 boto3 client is patched at the s3_client module
boundary so we never touch AWS.
"""

from unittest.mock import MagicMock, patch  # noqa: F401 — patch used below

import pytest
from fastapi.testclient import TestClient

from src.authorization.utils import get_current_user_with_refresh
from src.common.attachments import s3_client as s3_client_module
from src.config.db import get_tenant_db
from src.main import app

client = TestClient(app)


def _mock_row(mapping: dict):
    row = MagicMock()
    row._mapping = mapping
    return row


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch):
    """Provide fake AWS env vars so s3_client._build_client passes the guard."""
    monkeypatch.setenv("S3_AWS_ACCESS_KEY_ID", "AKIA-TEST")
    monkeypatch.setenv("S3_AWS_SECRET_ACCESS_KEY", "secret-test")
    monkeypatch.setenv("S3_AWS_REGION", "ap-south-1")
    monkeypatch.setenv("S3_BUCKET", "vow3-test")
    # Clear any previously-cached client so the patched boto3 is picked up.
    s3_client_module.reset_for_tests()
    yield
    s3_client_module.reset_for_tests()


@pytest.fixture
def mock_boto3():
    """Patch boto3.client so the lazy import inside _build_client picks up our mock.

    `s3_client._build_client` does `import boto3` lazily, so patching the
    module attribute on `s3_client_module` doesn't intercept it. Instead we
    patch `boto3.client` directly — the real boto3 module is on sys.modules.
    """
    with patch("boto3.client") as fake_client_factory:
        fake_s3 = MagicMock()
        fake_client_factory.return_value = fake_s3
        fake_s3.generate_presigned_url.return_value = (
            "https://vow3-test.s3.ap-south-1.amazonaws.com/fake-key?sig=abc"
        )
        # Reset cache so this run picks up the patched factory.
        s3_client_module.reset_for_tests()
        yield fake_s3


class TestAttachmentEndpoints:
    """Cases 1–9 from the plan's Verification section."""

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── Case 1: Upload valid PDF → 200 ───────────────────────────────

    def test_upload_valid_pdf(self, mock_boto3):
        # INSERT result returns lastrowid for the new attachment.
        insert_result = MagicMock()
        insert_result.lastrowid = 101
        # Each db.execute call returns either the soft-delete update result
        # (don't care) or the INSERT result. We sequence them via side_effect.
        self._mock_session.execute.side_effect = [
            MagicMock(),       # soft_delete_existing_active
            insert_result,     # insert_attachment
            MagicMock(),       # update_jute_mr_attachment_col
        ]

        response = client.post(
            "/api/attachments/upload?co_id=12",
            data={"module": "billpass", "entity_id": "4571", "file_type": "invoice"},
            files={"file": ("inv.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert "data" in body
        data = body["data"]
        assert data["attachment_id"] == 101
        assert data["module"] == "billpass"
        assert data["entity_id"] == 4571
        assert data["file_type"] == "invoice"
        assert data["original_filename"] == "inv.pdf"
        # S3 put + DB commit both invoked.
        mock_boto3.put_object.assert_called_once()
        self._mock_session.commit.assert_called_once()

    # ── Case 2: Non-PDF MIME → 400 ────────────────────────────────────

    def test_upload_non_pdf_rejected(self, mock_boto3):
        response = client.post(
            "/api/attachments/upload?co_id=12",
            data={"module": "billpass", "entity_id": "4571", "file_type": "invoice"},
            files={"file": ("foo.jpg", b"\xff\xd8\xff\xe0jpeg-bytes", "image/jpeg")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        assert "application/pdf" in response.json()["detail"]
        mock_boto3.put_object.assert_not_called()

    # ── Case 3: > 10 MB → 400 ────────────────────────────────────────

    def test_upload_too_large(self, mock_boto3):
        big = b"%PDF" + b"x" * (10 * 1024 * 1024 + 1)
        response = client.post(
            "/api/attachments/upload?co_id=12",
            data={"module": "billpass", "entity_id": "4571", "file_type": "invoice"},
            files={"file": ("big.pdf", big, "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        assert "10 MB" in response.json()["detail"]
        mock_boto3.put_object.assert_not_called()

    # ── Case 4: Missing co_id → 400 ──────────────────────────────────

    def test_upload_missing_co_id(self, mock_boto3):
        response = client.post(
            "/api/attachments/upload",
            data={"module": "billpass", "entity_id": "4571", "file_type": "invoice"},
            files={"file": ("inv.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        assert "co_id" in response.json()["detail"].lower()

    # ── Extra guard: SQL-injection-shaped file_type → 400 ────────────

    def test_upload_invalid_file_type_rejected(self, mock_boto3):
        response = client.post(
            "/api/attachments/upload?co_id=12",
            data={
                "module": "billpass",
                "entity_id": "4571",
                "file_type": "invoice; DROP TABLE jute_mr;--",
            },
            files={"file": ("inv.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        assert "Invalid file_type" in response.json()["detail"]
        mock_boto3.put_object.assert_not_called()

    # ── Case 5: Re-upload soft-deletes prior, inserts new ────────────

    def test_reupload_soft_deletes_and_inserts(self, mock_boto3):
        insert_result = MagicMock()
        insert_result.lastrowid = 102
        self._mock_session.execute.side_effect = [
            MagicMock(),       # soft_delete_existing_active
            insert_result,     # insert_attachment
            MagicMock(),       # update_jute_mr_attachment_col
        ]

        response = client.post(
            "/api/attachments/upload?co_id=12",
            data={"module": "billpass", "entity_id": "4571", "file_type": "invoice"},
            files={"file": ("inv2.pdf", b"%PDF-1.4 v2", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 200, response.text
        # First execute call is the soft-delete.
        assert self._mock_session.execute.call_count == 3
        first_call_args = self._mock_session.execute.call_args_list[0]
        params = first_call_args.args[1] if len(first_call_args.args) > 1 else first_call_args.kwargs
        assert params.get("module") == "billpass"
        assert params.get("entity_id") == 4571
        assert params.get("file_type") == "invoice"

    # ── Case 6: Download returns presigned URL ───────────────────────

    def test_download_returns_presigned_url(self, mock_boto3):
        row = _mock_row({
            "attachment_id": 101,
            "co_id": 12,
            "module": "billpass",
            "entity_id": 4571,
            "file_type": "invoice",
            "s3_bucket": "vow3-test",
            "s3_key": "dev3/billpass/12/4571/invoice_123.pdf",
            "original_filename": "inv.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "uploaded_by": 7,
            "uploaded_at": None,
            "active": 1,
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/attachments/101/download?co_id=12")
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert body["data"]["url"].startswith("https://")
        assert body["data"]["expires_in"] == 300
        mock_boto3.generate_presigned_url.assert_called_once()

    # ── Case 7: Download soft-deleted → 404 ──────────────────────────

    def test_download_soft_deleted_404(self, mock_boto3):
        row = _mock_row({
            "attachment_id": 101,
            "co_id": 12,
            "module": "billpass",
            "entity_id": 4571,
            "file_type": "invoice",
            "s3_bucket": "vow3-test",
            "s3_key": "dev3/billpass/12/4571/invoice_123.pdf",
            "original_filename": "inv.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "uploaded_by": 7,
            "uploaded_at": None,
            "active": 0,
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/attachments/101/download?co_id=12")
        assert response.status_code == 404

    def test_download_co_id_mismatch_404(self, mock_boto3):
        row = _mock_row({
            "attachment_id": 101,
            "co_id": 99,
            "module": "billpass",
            "entity_id": 4571,
            "file_type": "invoice",
            "s3_bucket": "vow3-test",
            "s3_key": "dev3/billpass/99/4571/invoice_123.pdf",
            "original_filename": "inv.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "uploaded_by": 7,
            "uploaded_at": None,
            "active": 1,
        })
        self._mock_session.execute.return_value.fetchone.return_value = row

        response = client.get("/api/attachments/101/download?co_id=12")
        assert response.status_code == 404

    # ── Case 8: Delete sets active=0 ─────────────────────────────────

    def test_delete_sets_active_zero(self, mock_boto3):
        row = _mock_row({
            "attachment_id": 101,
            "co_id": 12,
            "module": "billpass",
            "entity_id": 4571,
            "file_type": "invoice",
            "s3_bucket": "vow3-test",
            "s3_key": "dev3/billpass/12/4571/invoice_123.pdf",
            "original_filename": "inv.pdf",
            "mime_type": "application/pdf",
            "size_bytes": 100,
            "uploaded_by": 7,
            "uploaded_at": None,
            "active": 1,
        })
        # Calls: 1) get_attachment_by_id (fetchone), 2) soft_delete_by_id,
        # 3) clear_jute_mr_attachment_col.
        fetch_result = MagicMock()
        fetch_result.fetchone.return_value = row
        self._mock_session.execute.side_effect = [
            fetch_result,
            MagicMock(),
            MagicMock(),
        ]

        response = client.delete("/api/attachments/101?co_id=12")
        assert response.status_code == 200
        assert response.json() == {"data": {"message": "Attachment deleted"}}
        # commit was called.
        self._mock_session.commit.assert_called_once()

    def test_delete_not_found(self, mock_boto3):
        fetch_result = MagicMock()
        fetch_result.fetchone.return_value = None
        self._mock_session.execute.side_effect = [fetch_result]
        response = client.delete("/api/attachments/999?co_id=12")
        assert response.status_code == 404

    # ── Case 9: List filters by module + entity_id + active=1 ────────

    def test_list_active_by_entity(self, mock_boto3):
        rows = [
            _mock_row({
                "attachment_id": 101,
                "co_id": 12,
                "module": "billpass",
                "entity_id": 4571,
                "file_type": "invoice",
                "s3_bucket": "vow3-test",
                "s3_key": "dev3/billpass/12/4571/invoice_123.pdf",
                "original_filename": "inv.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 100,
                "uploaded_by": 7,
                "uploaded_at": None,
                "active": 1,
            }),
            _mock_row({
                "attachment_id": 102,
                "co_id": 12,
                "module": "billpass",
                "entity_id": 4571,
                "file_type": "challan",
                "s3_bucket": "vow3-test",
                "s3_key": "dev3/billpass/12/4571/challan_456.pdf",
                "original_filename": "chl.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 200,
                "uploaded_by": 7,
                "uploaded_at": None,
                "active": 1,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/attachments/?co_id=12&module=billpass&entity_id=4571"
        )
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 2
        # Verify the SQL was called with correct bind params.
        last_call = self._mock_session.execute.call_args
        params = last_call.args[1] if len(last_call.args) > 1 else last_call.kwargs
        assert params == {"module": "billpass", "entity_id": 4571}

    def test_list_missing_co_id(self, mock_boto3):
        response = client.get("/api/attachments/?module=billpass&entity_id=4571")
        assert response.status_code == 400

    def test_list_invalid_module(self, mock_boto3):
        response = client.get(
            "/api/attachments/?co_id=12&module=BAD&entity_id=4571"
        )
        assert response.status_code == 400


class TestProcBillpassAttachments:
    """Cases for the proc_billpass module (procurement bill pass).

    The proc_inward source table has no *_upload columns, so MODULE_COLUMN_MAP
    has no entry for ("proc_billpass", *). Uploads must therefore NOT execute
    any UPDATE against jute_mr or proc_inward — only the file_attachment
    INSERT + soft-delete are run.
    """

    @pytest.fixture(autouse=True)
    def setup_overrides(self):
        self._mock_session = MagicMock()
        app.dependency_overrides[get_current_user_with_refresh] = lambda: {"user_id": 7}
        app.dependency_overrides[get_tenant_db] = lambda: self._mock_session
        yield
        app.dependency_overrides.clear()

    # ── Case 1: Upload PDF with file_type=invoice → 200 ───────────────

    def test_upload_proc_billpass_invoice(self, mock_boto3):
        # Only TWO db.execute calls expected: soft-delete + insert.
        # NO jute_mr UPDATE because ("proc_billpass","invoice") is not in
        # MODULE_COLUMN_MAP.
        insert_result = MagicMock()
        insert_result.lastrowid = 201
        self._mock_session.execute.side_effect = [
            MagicMock(),       # soft_delete_existing_active
            insert_result,     # insert_attachment
        ]

        response = client.post(
            "/api/attachments/upload?co_id=1",
            data={
                "module": "proc_billpass",
                "entity_id": "12345",
                "file_type": "invoice",
            },
            files={"file": ("inv.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert "data" in body
        data = body["data"]
        assert data["module"] == "proc_billpass"
        assert data["entity_id"] == 12345
        assert data["file_type"] == "invoice"
        assert data["original_filename"] == "inv.pdf"
        # Only soft-delete + insert ran (no back-ref UPDATE).
        assert self._mock_session.execute.call_count == 2
        mock_boto3.put_object.assert_called_once()
        self._mock_session.commit.assert_called_once()

    # ── Case 2: Upload PDF with file_type=ewaybill → 200 ──────────────

    def test_upload_proc_billpass_ewaybill(self, mock_boto3):
        insert_result = MagicMock()
        insert_result.lastrowid = 202
        self._mock_session.execute.side_effect = [
            MagicMock(),
            insert_result,
        ]

        response = client.post(
            "/api/attachments/upload?co_id=1",
            data={
                "module": "proc_billpass",
                "entity_id": "12345",
                "file_type": "ewaybill",
            },
            files={
                "file": ("ewb.pdf", b"%PDF-1.4 ewaybill bytes", "application/pdf"),
            },
            headers={"host": "dev3.vowerp.co.in"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["data"]["module"] == "proc_billpass"
        assert body["data"]["file_type"] == "ewaybill"
        assert body["data"]["entity_id"] == 12345
        assert self._mock_session.execute.call_count == 2
        mock_boto3.put_object.assert_called_once()

    # ── Case 3: challan not allowed for proc_billpass → 400 ───────────

    def test_upload_proc_billpass_challan_rejected(self, mock_boto3):
        response = client.post(
            "/api/attachments/upload?co_id=1",
            data={
                "module": "proc_billpass",
                "entity_id": "12345",
                "file_type": "challan",
            },
            files={"file": ("chl.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "challan" in detail
        assert "proc_billpass" in detail
        # No S3 upload and no DB writes should occur on validation failure.
        mock_boto3.put_object.assert_not_called()
        self._mock_session.execute.assert_not_called()

    # ── Case 4: delivery_note rejected — canonical key is `ewaybill` ──

    def test_upload_proc_billpass_delivery_note_rejected(self, mock_boto3):
        response = client.post(
            "/api/attachments/upload?co_id=1",
            data={
                "module": "proc_billpass",
                "entity_id": "12345",
                "file_type": "delivery_note",
            },
            files={"file": ("dn.pdf", b"%PDF-1.4", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "delivery_note" in detail
        assert "proc_billpass" in detail
        mock_boto3.put_object.assert_not_called()
        self._mock_session.execute.assert_not_called()

    # ── Case 5: List filters by module=proc_billpass correctly ────────

    def test_list_proc_billpass_filters_by_module(self, mock_boto3):
        rows = [
            _mock_row({
                "attachment_id": 201,
                "co_id": 1,
                "module": "proc_billpass",
                "entity_id": 12345,
                "file_type": "invoice",
                "s3_bucket": "vow3-test",
                "s3_key": "dev3/proc_billpass/1/12345/invoice_111.pdf",
                "original_filename": "inv.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 100,
                "uploaded_by": 7,
                "uploaded_at": None,
                "active": 1,
            }),
            _mock_row({
                "attachment_id": 202,
                "co_id": 1,
                "module": "proc_billpass",
                "entity_id": 12345,
                "file_type": "ewaybill",
                "s3_bucket": "vow3-test",
                "s3_key": "dev3/proc_billpass/1/12345/ewaybill_222.pdf",
                "original_filename": "ewb.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 200,
                "uploaded_by": 7,
                "uploaded_at": None,
                "active": 1,
            }),
        ]
        self._mock_session.execute.return_value.fetchall.return_value = rows

        response = client.get(
            "/api/attachments/?co_id=1&module=proc_billpass&entity_id=12345"
        )
        assert response.status_code == 200
        body = response.json()
        assert "data" in body
        assert len(body["data"]) == 2
        assert {row["file_type"] for row in body["data"]} == {"invoice", "ewaybill"}
        # The SQL bind params must scope the query to module=proc_billpass.
        last_call = self._mock_session.execute.call_args
        params = last_call.args[1] if len(last_call.args) > 1 else last_call.kwargs
        assert params == {"module": "proc_billpass", "entity_id": 12345}

    # ── Case 6: NO jute_mr UPDATE happens for proc_billpass uploads ───

    def test_upload_proc_billpass_no_jute_mr_update(self, mock_boto3):
        """Inspect every executed statement to confirm jute_mr is never touched."""
        insert_result = MagicMock()
        insert_result.lastrowid = 203
        self._mock_session.execute.side_effect = [
            MagicMock(),
            insert_result,
        ]

        response = client.post(
            "/api/attachments/upload?co_id=1",
            data={
                "module": "proc_billpass",
                "entity_id": "12345",
                "file_type": "invoice",
            },
            files={"file": ("inv.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
            headers={"host": "dev3.vowerp.co.in"},
        )
        assert response.status_code == 200, response.text

        # Examine every text() executed during this request. None of them
        # should reference jute_mr.
        for call in self._mock_session.execute.call_args_list:
            stmt = call.args[0]
            # text() objects expose .text with the raw SQL string.
            sql_text = str(getattr(stmt, "text", stmt))
            assert "jute_mr" not in sql_text, (
                f"Unexpected jute_mr reference in SQL for proc_billpass: {sql_text}"
            )

        # Exactly two executes: soft-delete + insert.
        assert self._mock_session.execute.call_count == 2
