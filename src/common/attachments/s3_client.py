"""Thin boto3 S3 client wrapper for the attachment subsystem.

Design notes:
- Lazy singleton: client is built on first use, NOT at import time. This
  prevents the app from crashing on import when AWS env vars are absent
  (e.g. local dev where the user has not set up S3 yet).
- Env vars are read once at first client construction. To pick up rotated
  credentials, restart the process.
- All boto3 ClientError / BotoCoreError exceptions are mapped to
  HTTPException(500) with a brief, non-leaking hint. Full details are
  logged server-side.
"""

import logging
import os

from fastapi import HTTPException

logger = logging.getLogger(__name__)

_S3_CLIENT = None  # boto3.client('s3') — built lazily


def _ensure_env_loaded() -> None:
    """Load `.env` and `env/keys.env` from project root if the AWS vars are not
    already present in `os.environ`. The rest of the app loads
    `env/database.env` via `src/config/db.py`; AWS creds live in either `.env`
    or `env/keys.env` per the deployment convention. `load_dotenv` does not
    override existing values, so this is safe to call repeatedly."""
    if os.getenv("S3_AWS_ACCESS_KEY_ID") and os.getenv("S3_BUCKET"):
        return
    try:
        from dotenv import load_dotenv as _load_dotenv
    except ImportError:  # pragma: no cover — python-dotenv is a hard dep
        return
    for path in (".env", "env/keys.env"):
        try:
            _load_dotenv(path)
        except Exception:
            pass


def _build_client():
    """Construct a boto3 S3 client from env vars. Called once."""
    try:
        import boto3  # imported lazily so missing dep doesn't break app import
    except ImportError as exc:  # pragma: no cover — boto3 is a hard dep at runtime
        logger.error("boto3 is not installed: %s", exc)
        raise HTTPException(status_code=500, detail="S3 client unavailable: boto3 not installed")

    _ensure_env_loaded()

    access_key = os.getenv("S3_AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("S3_AWS_SECRET_ACCESS_KEY")
    region = os.getenv("S3_AWS_REGION")

    if not (access_key and secret_key and region):
        logger.error(
            "S3 not configured: missing one of S3_AWS_ACCESS_KEY_ID / S3_AWS_SECRET_ACCESS_KEY / S3_AWS_REGION"
        )
        raise HTTPException(status_code=500, detail="S3 not configured")

    # Force SigV4 + virtual-hosted addressing. Without this, boto3's default
    # auto-detected config in ap-south-1 (and some other v4-only regions)
    # produces presigned URLs whose signatures S3 rejects with
    # SignatureDoesNotMatch on GET, even though direct PUT/DELETE work.
    from botocore.config import Config  # local import to keep top-level light
    s3_config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    )

    return boto3.client(
        "s3",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=s3_config,
    )


def get_client():
    """Return cached boto3 S3 client, building it on first call."""
    global _S3_CLIENT
    if _S3_CLIENT is None:
        _S3_CLIENT = _build_client()
    return _S3_CLIENT


def get_bucket() -> str:
    """Return the configured S3 bucket name."""
    _ensure_env_loaded()
    bucket = os.getenv("S3_BUCKET")
    if not bucket:
        logger.error("S3 not configured: missing S3_BUCKET env var")
        raise HTTPException(status_code=500, detail="S3 not configured")
    return bucket


def _wrap_client_error(action: str, exc: Exception) -> HTTPException:
    """Map a boto3 exception to an HTTPException. Logs details server-side."""
    error_code = "Unknown"
    try:
        from botocore.exceptions import ClientError  # local import
        if isinstance(exc, ClientError):
            error_code = exc.response.get("Error", {}).get("Code", "Unknown")
    except ImportError:  # pragma: no cover
        pass
    logger.exception("S3 %s failed (code=%s): %s", action, error_code, exc)
    return HTTPException(status_code=500, detail=f"S3 operation failed: {error_code}")


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    """Upload `data` to S3 at `key` under the configured bucket."""
    client = get_client()
    bucket = get_bucket()
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise _wrap_client_error("upload", exc)


def presigned_get_url(key: str, expires_in: int = 300) -> str:
    """Generate a presigned GET URL for `key`. Default 5-minute expiry."""
    client = get_client()
    bucket = get_bucket()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _wrap_client_error("presign", exc)


def delete_object(key: str) -> None:
    """Delete the S3 object at `key`."""
    client = get_client()
    bucket = get_bucket()
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except HTTPException:
        raise
    except Exception as exc:
        raise _wrap_client_error("delete", exc)


def reset_for_tests() -> None:
    """Test helper: clear the cached client so a patched boto3 is picked up."""
    global _S3_CLIENT
    _S3_CLIENT = None
