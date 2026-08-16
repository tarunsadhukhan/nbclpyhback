"""Tenant-aware database connection for the offline-sync tools.

The server picks the database per request from the X-Tenant header, which these
scripts have no equivalent of — so every tool takes an explicit `--tenant`
instead. Refusing to guess is deliberate: a backfill run against the wrong
tenant would write face embeddings into another mill's database.
"""
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def connect(tenant):
    """Connect to [tenant]'s database using the server's own credentials."""
    if not tenant:
        raise SystemExit("--tenant is required (e.g. --tenant nbcl)")
    import mysql.connector
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, 'env', 'database.env'))
    return mysql.connector.connect(
        host=os.getenv('DATABASE_HOST'),
        port=int(os.getenv('DATABASE_PORT', '3306')),
        user=os.getenv('DATABASE_USER'),
        password=os.getenv('DATABASE_PASSWORD'),
        database=tenant,
        ssl_disabled=True,
    )


def photo_dir():
    """Where the mobile app stores employee photos on this host."""
    base = os.environ.get('PHOTO_DIR') or os.path.join(_REPO_ROOT, 'employee_photos')
    os.makedirs(base, exist_ok=True)
    return base


def add_tenant_arg(parser):
    parser.add_argument('--tenant', required=True,
                        help='tenant database name, e.g. nbcl')
