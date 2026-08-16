"""Nightly sweep: delete offline capture JPEGs older than the retention window.

Only the verdict (daily_attendance.face_verify_status) is kept long term — the
image itself is biometric data and goes away. The window comes from
sync_client_config.offline_photo_keep_days so the client's data policy can be
shortened without a code change.

    python tools/offline_sync/purge_offline_photos.py --tenant nbcl            # honour the configured window
    python tools/offline_sync/purge_offline_photos.py --tenant nbcl --days 7
    python tools/offline_sync/purge_offline_photos.py --tenant nbcl --dry-run
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _db import add_tenant_arg, connect, photo_dir  # noqa: E402


def keep_days_from_config(tenant, default=30):
    try:
        db = connect(tenant)
        cursor = db.cursor()
        cursor.execute("SELECT config_value FROM sync_client_config WHERE config_key=%s",
                       ('offline_photo_keep_days',))
        row = cursor.fetchone()
        cursor.close()
        db.close()
        if row:
            return int(row[0])
    except Exception:
        pass
    return default


def main():
    ap = argparse.ArgumentParser()
    add_tenant_arg(ap)
    ap.add_argument('--days', type=int)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    from src.mobileapp.src.sync.routes import OFFLINE_PHOTO_SUBDIR

    days = args.days if args.days is not None else keep_days_from_config(args.tenant)
    cutoff = time.time() - days * 86400
    root = os.path.join(photo_dir(), OFFLINE_PHOTO_SUBDIR)
    if not os.path.isdir(root):
        print(f"nothing to do — {root} does not exist")
        return

    removed = kept = 0
    for folder, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(folder, name)
            if os.path.getmtime(path) < cutoff:
                if not args.dry_run:
                    os.remove(path)
                removed += 1
            else:
                kept += 1
        if not args.dry_run and not os.listdir(folder) and folder != root:
            os.rmdir(folder)

    print(f"retention {days} days: {removed} deleted, {kept} kept"
          + (" (dry run)" if args.dry_run else ""))


if __name__ == '__main__':
    main()
