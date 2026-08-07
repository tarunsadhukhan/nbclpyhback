import os

import mysql.connector
from dotenv import load_dotenv
from flask import has_request_context, request

# Connection settings (host, user, password, port) come from the .env file;
# the database name is resolved per-request from the URL subdomain by
# DatabaseRouterMiddleware (see src/__init__.py) and current_db_name() below.
# e.g. a request to sls.192.168.0.133:8000 connects to the "sls" database.
try:
    load_dotenv("env/database.env")
except Exception as e:
    print(f"Warning: Could not load database.env file: {e}")

_BASE_DB_CONFIG = {
    "host":         os.getenv("DATABASE_HOST"),
    "port":         int(os.getenv("DATABASE_PORT", "3306")),
    "user":         os.getenv("DATABASE_USER"),
    "password":     os.getenv("DATABASE_PASSWORD"),
    "database":     os.getenv("DATABASE_DEFAULT"),
    "ssl_disabled": True,
}

# ── Main database (attendance, employees, masters) ────────────
DB_CONFIG = dict(_BASE_DB_CONFIG)

# ── Auth database (login / signup) ───────────────────────────
AUTH_DB_CONFIG = dict(_BASE_DB_CONFIG)

# Environ key set by DatabaseRouterMiddleware (see src/__init__.py).
# It holds the database name taken from the Host subdomain, e.g. a request to
# sls.localhost:8000/login connects to the "sls" database.
DB_NAME_ENVIRON_KEY = "hrms.db_name"


def current_db_name(default):
    """DB name for the active request, or `default` outside a request."""
    if has_request_context():
        name = request.environ.get(DB_NAME_ENVIRON_KEY)
        if name:
            return name
    return default


def _connect(base_config):
    config = dict(base_config)
    config["database"] = current_db_name(base_config["database"])
    return mysql.connector.connect(**config)


def get_db():
    return _connect(DB_CONFIG)

def get_auth_db():
    return _connect(AUTH_DB_CONFIG)

def init_db():
    """Create tables if they don't exist."""
    # ── auth db: users table (login/signup) ──────────────────
    auth_db     = get_auth_db()
    auth_cursor = auth_db.cursor()
    auth_cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_mst (
            user_id               INT AUTO_INCREMENT PRIMARY KEY,
            email_id              VARCHAR(255) NOT NULL UNIQUE,
            name                  VARCHAR(255),
            password              VARCHAR(255),
            refresh_token         VARCHAR(255),
            active                TINYINT(1)  NOT NULL DEFAULT 1,
            updated_by_con_user   INT         NOT NULL DEFAULT 0,
            updated_date_time     DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    auth_db.commit()
    auth_cursor.close()
    auth_db.close()

    # ── attendance db: occupations + attendance migrations ────
    db     = get_db()
    cursor = db.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS occupations (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            name        VARCHAR(100) NOT NULL UNIQUE,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

    # Add att_type column (R=Regular, O=OT, C=Cash)
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN att_type CHAR(1) DEFAULT 'R'")
        db.commit()
        print("   [OK] Added 'att_type' column to attendance table")
    except Exception:
        pass

    # Add photo_att column
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN photo_att LONGTEXT DEFAULT NULL")
        db.commit()
        print("   [OK] Added 'photo_att' column to attendance table")
    except Exception:
        pass

    # Add shift_hours column
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN shift_hours DECIMAL(5,2) DEFAULT 0")
        db.commit()
        print("   [OK] Added 'shift_hours' column to attendance table")
    except Exception:
        pass

    # Add working_hours column
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN working_hours DECIMAL(5,2) DEFAULT 0")
        db.commit()
        print("   [OK] Added 'working_hours' column to attendance table")
    except Exception:
        pass

    # Add idle_hours column
    try:
        cursor.execute("ALTER TABLE attendance ADD COLUMN idle_hours DECIMAL(5,2) DEFAULT 0")
        db.commit()
        print("   [OK] Added 'idle_hours' column to attendance table")
    except Exception:
        pass

    cursor.close()
    db.close()
