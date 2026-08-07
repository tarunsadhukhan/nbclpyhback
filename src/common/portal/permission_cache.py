"""In-memory store for portal menu permission maps keyed by session token.

This avoids serialising large permission payloads into cookies while still
supporting stateless middleware checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Dict, Optional


@dataclass
class PermissionRecord:
    user_id: int
    permissions: Dict[str, int]
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


_STORE: Dict[str, PermissionRecord] = {}
_USER_INDEX: Dict[int, set[str]] = {}
_LOCK = Lock()
_DEFAULT_TTL_SECONDS = 3600


def _cleanup_expired() -> None:
    now = datetime.now(timezone.utc)
    expired_tokens = [token for token, record in _STORE.items() if record.expires_at <= now]
    for token in expired_tokens:
        record = _STORE.pop(token, None)
        if record:
            index = _USER_INDEX.get(record.user_id)
            if index and token in index:
                index.remove(token)
            if index and not index:
                _USER_INDEX.pop(record.user_id, None)


def store_permissions(token: str, user_id: int, permissions: Dict[str, int], ttl_seconds: int | None = None) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds or _DEFAULT_TTL_SECONDS)
    record = PermissionRecord(user_id=user_id, permissions=permissions, expires_at=expires_at)
    with _LOCK:
        _cleanup_expired()
        # ensure per-user index stays tidy
        existing_tokens = _USER_INDEX.setdefault(user_id, set())
        existing_tokens.add(token)
        _STORE[token] = record


def replace_permissions(user_id: int, permissions: Dict[str, int], ttl_seconds: int | None = None) -> str:
    """Replace all permission tokens for a user with a fresh one."""
    new_token = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    with _LOCK:
        _cleanup_expired()
        old_tokens = list(_USER_INDEX.get(user_id, set()))
        for token in old_tokens:
            _STORE.pop(token, None)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds or _DEFAULT_TTL_SECONDS)
        record = PermissionRecord(user_id=user_id, permissions=permissions, expires_at=expires_at)
        _STORE[new_token] = record
        _USER_INDEX[user_id] = {new_token}
    return new_token


def get_permissions(token: str) -> Optional[PermissionRecord]:
    with _LOCK:
        _cleanup_expired()
        record = _STORE.get(token)
        if record and not record.is_expired():
            return record
        if token in _STORE:
            # Remove expired entries lazily
            expired = _STORE.pop(token)
            index = _USER_INDEX.get(expired.user_id)
            if index and token in index:
                index.remove(token)
            if index and not index:
                _USER_INDEX.pop(expired.user_id, None)
        return None


def revoke_permissions(token: str) -> None:
    with _LOCK:
        record = _STORE.pop(token, None)
        if record:
            index = _USER_INDEX.get(record.user_id)
            if index and token in index:
                index.remove(token)
            if index and not index:
                _USER_INDEX.pop(record.user_id, None)


def revoke_user(user_id: int) -> None:
    with _LOCK:
        tokens = list(_USER_INDEX.pop(user_id, []))
        for token in tokens:
            _STORE.pop(token, None)