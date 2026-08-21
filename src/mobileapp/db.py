import os
import threading

import mysql.connector
from mysql.connector import pooling
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


# ── Connection pool ──────────────────────────────────────────
# This MySQL server runs with skip_name_resolve=OFF, so it spends ~8 s doing a
# reverse-DNS lookup on the client before it even sends its greeting packet.
# Queries themselves take ~40 ms. A handler that opened three connections was
# therefore ~25 s of handshake and ~0.1 s of work - that is where the 34 s
# /sync/face-embeddings response went. Pooling pays the 8 s once per connection
# and reuses it for the life of the process.
#
# The proper fix is skip_name_resolve=ON in the server's my.cnf (it is read-only,
# so it needs a MySQL restart). Pooling is worth having regardless.
#
# One pool per tenant database, created on first use - the database name is
# per-request (see current_db_name), so a single shared pool cannot work.
# ponytail: pool_size 4, built on a background thread. MySQLConnectionPool opens
# all of its connections in the constructor, so building it inline would have
# moved the wait rather than removed it - 4 x 8 s = 33 s on whichever request
# happened to be first. Requests during the build use a direct connection, i.e.
# the old behaviour, and every request after it is served from the pool.
# Raise pool_size if more than 4 mobile requests are ever genuinely in flight
# at once; anything over that falls back to a direct connect, never an error.
_POOL_SIZE = 4
_pools = {}
_building = set()
_pools_lock = threading.Lock()


def _build_pool(db_name):
    try:
        config = dict(_BASE_DB_CONFIG)
        config["database"] = db_name
        pool = pooling.MySQLConnectionPool(
            pool_name=f"hrms_{db_name}", pool_size=_POOL_SIZE, **config
        )
        with _pools_lock:
            _pools[db_name] = pool
        print(f"[db] connection pool ready for {db_name} ({_POOL_SIZE} connections)")
    except Exception as e:
        print(f"[db] could not build pool for {db_name}: {e}")
    finally:
        with _pools_lock:
            _building.discard(db_name)


def _pool_for(db_name):
    """The tenant's pool, or None while it is still being built."""
    pool = _pools.get(db_name)
    if pool is not None:
        return pool
    with _pools_lock:
        if db_name not in _building:
            _building.add(db_name)
            threading.Thread(
                target=_build_pool, args=(db_name,), daemon=True
            ).start()
    return None


def _connect(base_config):
    db_name = current_db_name(base_config["database"])
    pool = _pool_for(db_name)
    if pool is not None:
        try:
            connection = pool.get_connection()
            # The server drops idle connections (wait_timeout 8 h). Revive here
            # rather than letting the caller's first query fail.
            try:
                connection.ping(reconnect=True, attempts=2, delay=0)
            except Exception:
                pass
            return connection
        except Exception as e:
            # Pool exhausted: degrade to the slow path instead of a 500.
            print(f"[db] pool busy for {db_name} ({e}); direct connect")
    config = dict(base_config)
    config["database"] = db_name
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
