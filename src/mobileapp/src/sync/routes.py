"""Sync endpoints used by the offline-first Android app.

Routes (mounted under /sync):
    GET  /sync/time             Server clock + client config + min_app_version
    GET  /sync/config           Client config only (thresholds, staleness ladder)
    GET  /sync/face-embeddings  Paged MobileFaceNet embeddings for a branch
    GET  /sync/review-count     Badge count of offline matches awaiting HR review

ponytail: there is deliberately no /sync/masters. Master reads are cached by
OkHttp on the device — the same GETs the screens already make are replayed from
disk when the network is gone, so no second, parallel copy of every master table
has to be defined, versioned and kept in step.

Everything here degrades to a plain answer when the tenant database has not had
database/migration_offline_sync.sql applied yet, so deploying this code before
migrating changes nothing for existing clients.
"""
import json
import os
from datetime import datetime, timedelta

from flask import jsonify, request

from src.mobileapp.db import get_db
from src.mobileapp.src.sync import sync_bp

# Bump this when the on-device .tflite weights change; the client re-pulls every
# embedding whose model_ver no longer matches its own.
MOBILE_MODEL_VER = 'mobilefacenet-v1'

# Offline capture JPEGs land here, one folder per month.
OFFLINE_PHOTO_SUBDIR = 'offline_verify'

_DEFAULT_CONFIG = {
    'face_accept_threshold': '0.62',
    'face_review_threshold': '0.55',
    'face_margin_threshold': '0.05',
    'perm_stale_warn_days': '7',
    'perm_stale_lock_days': '14',
    'offline_photo_keep_days': '30',
    'min_app_version': '1.0',
}

_last_purge = [None]  # module-level so the ledger sweep runs at most hourly


def _photo_dir():
    """Where offline capture JPEGs are stored, alongside the app's other media."""
    base = os.environ.get('PHOTO_DIR') or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'employee_photos')
    os.makedirs(base, exist_ok=True)
    return base


def _table_has(table, column):
    """Is [column] present on [table] in the CURRENT tenant database?

    Uses DATABASE() rather than a configured schema name, because the database
    is chosen per request from the tenant header. Lets every offline column be
    optional so an un-migrated tenant keeps working.
    """
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            """SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s""",
            (table, column))
        found = cursor.fetchone() is not None
        cursor.close()
        db.close()
        return found
    except Exception:
        return False


def _load_config():
    """Client config from sync_client_config, falling back to the defaults."""
    cfg = dict(_DEFAULT_CONFIG)
    try:
        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT config_key, config_value FROM sync_client_config")
        for row in cursor.fetchall():
            cfg[row['config_key']] = row['config_value']
        cursor.close()
        db.close()
    except Exception:
        pass  # table not migrated yet — defaults keep the client working
    return cfg


def _sweep_uuid_ledger():
    """Drop replay-guard rows older than 30 days. At most once an hour."""
    now = datetime.now()
    if _last_purge[0] and (now - _last_purge[0]) < timedelta(hours=1):
        return
    _last_purge[0] = now
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM sync_client_uuid WHERE created_at < %s",
                       (now - timedelta(days=30),))
        db.commit()
        cursor.close()
        db.close()
    except Exception:
        pass


# ── GET /sync/time ──────────────────────────────────────────────────────────

@sync_bp.route('/time', methods=['GET'])
def sync_time():
    """Server clock for skew detection, plus everything the client tunes on."""
    _sweep_uuid_ledger()
    now = datetime.now()
    cfg = _load_config()
    return jsonify({
        'status': 'success',
        'server_time': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'server_epoch_ms': int(now.timestamp() * 1000),
        'model_ver': MOBILE_MODEL_VER,
        'min_app_version': cfg.get('min_app_version', '1.0'),
        'config': cfg,
    })


@sync_bp.route('/config', methods=['GET'])
def sync_config():
    return jsonify({'status': 'success', 'config': _load_config(),
                    'model_ver': MOBILE_MODEL_VER})


# ── GET /sync/face-embeddings ───────────────────────────────────────────────

@sync_bp.route('/face-embeddings', methods=['GET'])
def sync_face_embeddings():
    """Paged mobile face embeddings for one branch.

    Query: branch_id (required), since=ISO8601 (optional), offset, limit.
    Rows whose mobile embedding has not been backfilled yet are skipped — run
    tools/backfill_mobile_embeddings.py to fill them from the enrolment photos.
    """
    try:
        branch_id = request.args.get('branch_id', type=int)
        if not branch_id:
            return jsonify({'status': 'error', 'message': 'branch_id is required'}), 400

        # Not migrated yet: answer honestly with an empty gallery instead of a
        # 500, so the app reports "no faces downloaded" rather than an error.
        if not _table_has('employee_face_mst', 'face_embedding_mobile'):
            return jsonify({
                'status': 'success',
                'server_time': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                'model_ver': MOBILE_MODEL_VER,
                'rows': [], 'deleted': [], 'count': 0,
                'has_more': False, 'next_offset': 0,
                'message': 'Mobile embeddings not migrated on this database yet',
            })

        since = request.args.get('since')
        offset = request.args.get('offset', default=0, type=int)
        limit = min(request.args.get('limit', default=200, type=int), 500)

        where = ["f.active = 1", "p.active = 1", "f.face_embedding_mobile IS NOT NULL",
                 "o.branch_id = %s"]
        params = [branch_id]
        if since:
            where.append("COALESCE(f.mobile_embed_updated, f.updated_date_time) > %s")
            params.append(since.replace('T', ' ')[:19])

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute(f"""
            SELECT f.emp_face_id, f.eb_id, o.emp_code,
                   TRIM(CONCAT(p.first_name, ' ', COALESCE(p.middle_name, ''), ' ',
                               COALESCE(p.last_name, ''))) AS name,
                   f.face_embedding_mobile, f.mobile_model_ver,
                   COALESCE(f.mobile_embed_updated, f.updated_date_time) AS updated_at,
                   o.branch_id
            FROM employee_face_mst f
            INNER JOIN hrms_ed_official_details o ON f.eb_id = o.eb_id
            INNER JOIN hrms_ed_personal_details p ON f.eb_id = p.eb_id
            WHERE {' AND '.join(where)}
            ORDER BY updated_at, f.emp_face_id
            LIMIT %s OFFSET %s
        """, tuple(params) + (limit + 1, offset))
        rows = cursor.fetchall()

        # Face rows deactivated since `since`, so the device drops them.
        deleted = []
        if since:
            cursor.execute("""
                SELECT f.emp_face_id FROM employee_face_mst f
                INNER JOIN hrms_ed_official_details o ON f.eb_id = o.eb_id
                INNER JOIN hrms_ed_personal_details p ON f.eb_id = p.eb_id
                WHERE o.branch_id = %s AND (f.active = 0 OR p.active = 0)
                  AND COALESCE(f.mobile_embed_updated, f.updated_date_time) > %s
            """, (branch_id, since.replace('T', ' ')[:19]))
            deleted = [r['emp_face_id'] for r in cursor.fetchall()]

        cursor.close()
        db.close()

        has_more = len(rows) > limit
        rows = rows[:limit]

        out = []
        for r in rows:
            try:
                vector = json.loads(r['face_embedding_mobile'])
            except Exception:
                continue
            out.append({
                'face_id': r['emp_face_id'],
                'eb_id': r['eb_id'],
                'emp_code': r['emp_code'],
                'name': (r['name'] or '').strip(),
                'branch_id': r['branch_id'],
                'embedding': vector,
                'model_ver': r['mobile_model_ver'] or MOBILE_MODEL_VER,
                'updated_at': r['updated_at'].strftime('%Y-%m-%dT%H:%M:%S') if r['updated_at'] else None,
            })

        return jsonify({
            'status': 'success',
            'server_time': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'model_ver': MOBILE_MODEL_VER,
            'rows': out,
            'deleted': deleted,
            'count': len(out),
            'has_more': has_more,
            'next_offset': offset + len(out),
        })
    except Exception as e:
        print(f"❌ sync/face-embeddings error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── GET /sync/review-count ──────────────────────────────────────────────────

@sync_bp.route('/review-count', methods=['GET'])
def sync_review_count():
    """How many offline face matches are flagged for HR review.

    The app only shows this as a badge — the resolve/override action lives in
    the web ERP where the reviewer has the full register next to the flag.
    """
    try:
        if not _table_has('daily_attendance', 'needs_review'):
            return jsonify({'status': 'success', 'count': 0})
        branch_id = request.args.get('branch_id', type=int)
        db = get_db()
        cursor = db.cursor(dictionary=True)
        if branch_id:
            cursor.execute("""SELECT COUNT(*) AS cnt FROM daily_attendance
                              WHERE needs_review = 1 AND is_active = 1 AND branch_id = %s""",
                           (branch_id,))
        else:
            cursor.execute("""SELECT COUNT(*) AS cnt FROM daily_attendance
                              WHERE needs_review = 1 AND is_active = 1""")
        cnt = cursor.fetchone()['cnt']
        cursor.close()
        db.close()
        return jsonify({'status': 'success', 'count': cnt})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Helpers used by /mark-attendance ────────────────────────────────────────

def parse_client_time(raw):
    """ISO-8601 (with or without offset/millis) -> naive local datetime, or None."""
    if not raw:
        return None
    text = str(raw).strip().replace('T', ' ')
    for cut in ('+', 'Z'):
        idx = text.find(cut, 11)
        if idx > 0:
            text = text[:idx]
    text = text.strip()[:19]
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def store_offline_photo(face_image_b64):
    """Persist an offline capture JPEG under PHOTO_DIR/offline_verify/<yyyy-mm>/."""
    import base64
    try:
        month = datetime.now().strftime('%Y-%m')
        folder = os.path.join(_photo_dir(), OFFLINE_PHOTO_SUBDIR, month)
        os.makedirs(folder, exist_ok=True)
        name = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}.jpg"
        path = os.path.join(folder, name)
        with open(path, 'wb') as fh:
            fh.write(base64.b64decode(face_image_b64))
        return os.path.join(OFFLINE_PHOTO_SUBDIR, month, name)
    except Exception:
        return None


def reverify_offline_face(face_image_b64, eb_id):
    """Re-run the authoritative dlib matcher on an offline capture.

    Returns 'MATCH' / 'MISMATCH' / 'NO_FACE', or None when face_recognition is
    not installed on this host (the verdict is then simply left unset).
    """
    import base64
    try:
        try:
            import face_recognition
        except ImportError:
            return None
        import numpy as np

        tmp = os.path.join(_photo_dir(), f'_offline_verify_{os.getpid()}.jpg')
        with open(tmp, 'wb') as fh:
            fh.write(base64.b64decode(face_image_b64))
        try:
            image = face_recognition.load_image_file(tmp)
            encodings = face_recognition.face_encodings(image)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

        if not encodings:
            return 'NO_FACE'

        db = get_db()
        cursor = db.cursor(dictionary=True)
        cursor.execute("""SELECT face_embedding FROM employee_face_mst
                          WHERE eb_id = %s AND active = 1 AND face_embedding IS NOT NULL""",
                       (eb_id,))
        known = cursor.fetchall()
        cursor.close()
        db.close()

        if not known:
            return None  # nothing enrolled server-side to compare against

        for row in known:
            try:
                vec = np.array(json.loads(row['face_embedding']))
                if face_recognition.face_distance([vec], encodings[0])[0] < 0.6:
                    return 'MATCH'
            except Exception:
                continue
        return 'MISMATCH'
    except Exception:
        return None
