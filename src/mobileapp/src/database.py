"""
Database connection module.

Delegates to the root-level ``db.py`` so there is a single source of truth
for connection settings and the per-request dynamic database selection
(see ``current_db_name`` / ``DatabaseRouterMiddleware``).
"""
from src.mobileapp.db import get_db, get_auth_db, current_db_name, DB_CONFIG, AUTH_DB_CONFIG  # noqa: F401