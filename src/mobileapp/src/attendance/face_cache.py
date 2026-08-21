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
import time

import numpy as np

from src.mobileapp.db import DB_CONFIG, current_db_name, get_db


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

# Keyed by (db_name, branch_id) -> (encs, meta, loaded_at).  db_name is part of
# the key because the database is resolved per-request from the Host subdomain
# (see src/mobileapp/db.py) -- a single global slot would serve one tenant's
# faces to another.  That is why the original cache was left switched off.
_cache = {}

# Re-read from DB after this many seconds even without an explicit invalidate().
# register_face() invalidates immediately, so this only covers changes made
# outside that path (employee deactivated, branch transfer, direct SQL).
# ponytail: fixed TTL, not a change-feed -- 60 s of staleness is cheaper than
# wiring invalidation into every table that can affect the roster.
_TTL_SECONDS = 60


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


def load(branch_id=None):
    """Return (encs_ndarray, meta_list) for the current request's tenant DB,
    scoped to ``branch_id`` when given.

    Served from memory when a fresh entry exists.  The DB round-trip this
    replaces costs 1-3 s per call -- it ran on *every* /check-face and
    /attendance request, which is the single biggest slice of a punch."""
    key = (current_db_name(DB_CONFIG["database"]), branch_id)
    now = time.monotonic()

    # ponytail: the load happens under the lock, so N simultaneous punches on a
    # cold cache do one DB read between them instead of N.  It also means a slow
    # DB blocks other branches' punches for that one read -- acceptable while
    # the read is ~1-3 s and happens once a minute; split to a per-key lock if
    # that ever shows up in the latency numbers.
    with _lock:
        hit = _cache.get(key)
        if hit is not None and now - hit[2] < _TTL_SECONDS:
            return hit[0], hit[1]

        encs, meta = _load(branch_id)
        _cache[key] = (encs, meta, now)

    print(f"[face_cache] loaded {encs.shape[0]} embeddings "
          f"(db={key[0]}, branch_id={branch_id})")
    return encs, meta


def invalidate():
    """Drop every cached entry so the next load() re-reads from DB."""
    with _lock:
        _cache.clear()
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


if __name__ == "__main__":
    # Self-check: python -m src.mobileapp.src.attendance.face_cache
    # Fakes the DB read and the clock so the caching rules are checked without
    # a database.  Fails loudly if the cache ever serves the wrong tenant.
    import sys

    calls = []

    def _fake_load(branch_id=None):
        calls.append((_db_name, branch_id))
        return np.zeros((len(calls), 128)), [{"eb_id": len(calls)}]

    _db_name = "sls"
    _now = [1000.0]
    _load, time.monotonic = _fake_load, lambda: _now[0]
    current_db_name = lambda default: _db_name

    load(5); load(5)
    assert len(calls) == 1, f"second call should hit cache, got {calls}"

    load(7)
    assert len(calls) == 2, "a different branch must not reuse branch 5's faces"

    _db_name = "other_tenant"
    load(5)
    assert calls[-1] == ("other_tenant", 5), "tenant must not be served cached faces"

    _db_name = "sls"
    _now[0] += _TTL_SECONDS + 1
    load(5)
    assert len(calls) == 4, "entry older than the TTL must be re-read"

    _now[0] += 1
    invalidate()
    load(5)
    assert len(calls) == 5, "invalidate() must force a re-read"

    print("face_cache self-check OK", file=sys.stderr)
