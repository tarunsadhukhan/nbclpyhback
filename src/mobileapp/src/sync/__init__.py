"""Offline-first sync for the Android app.

Exposes:
    sync_bp             – blueprint mounted under /sync
    install_idempotency – app-wide replay guard for POST/PUT with a client_uuid

Both are registered in src/mobileapp/src/__init__.py::create_app.
"""
from flask import Blueprint

sync_bp = Blueprint('sync', __name__, url_prefix='/sync')

from src.mobileapp.src.sync import routes  # noqa: E402,F401  (registers the routes)
from src.mobileapp.src.sync.idempotency import install_idempotency  # noqa: E402,F401

__all__ = ['sync_bp', 'install_idempotency']
