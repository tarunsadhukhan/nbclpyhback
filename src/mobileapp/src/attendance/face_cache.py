"""
In-process cache of registered face embeddings.

Loading every employee's embedding + photo_html on each /check-face or
/attendance call costs ~1-3 s.  This module keeps the embeddings in memory
as a stacked ndarray so face_distance() runs against a pre-parsed matrix
and the SQL round-trip is avoided.

photo_html is NOT cached -- it's heavy (often 100-300 KB per employee) and
only the matched employee's photo is ever returned.  The matched photo
is fetched in a single small SELECT after the match is decided.

Invalidation: call invalidate() whenever a face is registered, deleted,
or has its embedding updated.  See onboarding.register_face() for the
hook point.
"""

import json
import threading

import numpy as np

from src.mobileapp.db import get_db


# Bulk fetch *without* photo_html -- keeps the cache small.
_BULK_SQL = """
    SELECT p.eb_id,
           o.emp_code,
           CONCAT(p.first_name, ' ',
                  COALESCE(p.middle_name, ''), ' ',
                  COALESCE(p.last_name, '')) AS name,
           o.sub_dept_id,
           o.designation_id,
           o.branch_id,
           f.face_embedding,
           s.sub_dept_desc AS department_name,
           d.desig         AS designation_name
    FROM employee_face_mst f
    INNER JOIN hrms_ed_official_details o ON f.eb_id = o.eb_id
    INNER JOIN hrms_ed_personal_details p ON f.eb_id = p.eb_id
    LEFT JOIN sub_dept_mst    s ON o.sub_dept_id    = s.sub_dept_id
    LEFT JOIN designation_mst d ON o.designation_id = d.designation_id
    WHERE p.active = 1 AND f.active = 1
"""

# Fetch photo_html only for the matched employee (latest active face).
_PHOTO_SQL = """
    SELECT photo_html
    FROM   employee_face_mst
    WHERE  eb_id = %s AND active = 1
    ORDER BY updated_date_time DESC, emp_face_id DESC
    LIMIT 1
"""


_lock = threading.Lock()
_cache = {"encs": None, "meta": None}


def _load(branch_id=None):
    """Pull rows from DB and parse embeddings into a stacked ndarray.
    Rows with a bad / empty embedding are dropped so they don't crash
    face_distance().  When ``branch_id`` is given, only employees of that
    branch are loaded so face matching is scoped to the selected branch."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    if branch_id is not None:
        cursor.execute(_BULK_SQL + " AND o.branch_id = %s", (branch_id,))
    else:
        cursor.execute(_BULK_SQL)
    rows = cursor.fetchall()
    cursor.close()
    db.close()

    encs = []
    meta = []
    for r in rows:
        emb_json = r.get("face_embedding")
        if not emb_json:
            continue
        try:
            vec = np.asarray(json.loads(emb_json), dtype=np.float64)
        except (ValueError, TypeError):
            continue
        if vec.size == 0:
            continue
        encs.append(vec)
        meta.append({
            "eb_id":            r["eb_id"],
            "emp_code":         r["emp_code"],
            "name":             r["name"],
            "sub_dept_id":      r["sub_dept_id"],
            "designation_id":   r["designation_id"],
            "branch_id":        r["branch_id"],
            "department_name":  r["department_name"],
            "designation_name": r["designation_name"],
        })

    if encs:
        stacked = np.vstack(encs)
    else:
        stacked = np.zeros((0, 128), dtype=np.float64)
    return stacked, meta


def get():
    """Return (encs_ndarray, meta_list).  Loads from DB on first call /
    after invalidate().  Thread-safe."""
    with _lock:
        if _cache["encs"] is None:
            _cache["encs"], _cache["meta"] = _load()
            print(f"[face_cache] loaded {_cache['encs'].shape[0]} embeddings")
        return _cache["encs"], _cache["meta"]


def load(branch_id=None):
    """Return (encs_ndarray, meta_list) loaded fresh from the *current* request's
    database, bypassing the cross-request cache.  Used by the face-match
    endpoints so matching always runs against the live tenant DB -- the same
    process as the reference backend (no stale / cross-tenant data).  When
    ``branch_id`` is given, only that branch's employees are considered."""
    encs, meta = _load(branch_id)
    print(f"[face_cache] live-loaded {encs.shape[0]} embeddings (branch_id={branch_id})")
    return encs, meta


def invalidate():
    """Drop the cache so the next get() reloads from DB."""
    with _lock:
        _cache["encs"] = None
        _cache["meta"] = None
    print("[face_cache] invalidated")


def get_photo_html(eb_id):
    """Fetch the latest active photo_html for one employee.  Used only for
    the matched employee, never as part of the bulk match path."""
    db = get_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute(_PHOTO_SQL, (eb_id,))
    row = cursor.fetchone()
    cursor.close()
    db.close()
    return row["photo_html"] if row else None
