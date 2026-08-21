"""Self-check for the client_uuid replay guard.

Target: src/mobileapp/src/sync/idempotency.py — the guard that actually runs in
production. It is the piece the offline plan calls non-negotiable.

This is the piece the offline plan calls non-negotiable: without it, a response
lost on a flaky link turns one punch into two on the retry. It runs against a
throwaway SQLite database through a small shim, so it needs no MySQL and no
server.

    python tools/test_idempotency.py
"""
import datetime as _dt
import os
import sqlite3
import sys
import tempfile

# repo root, so `import src.mobileapp...` resolves the same way the server does
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

# Python 3.12+ dropped the implicit datetime adapters; MySQL binds datetimes
# natively, so this is shim scaffolding, not something the product needs.
sqlite3.register_adapter(_dt.datetime, lambda v: v.isoformat(sep=' ', timespec='seconds'))
sqlite3.register_adapter(_dt.date, lambda v: v.isoformat())

DB_PATH = os.path.join(tempfile.gettempdir(), 'hrms_idempotency_test.sqlite')

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_client_uuid (
    client_uuid   TEXT PRIMARY KEY,
    endpoint      TEXT NOT NULL,
    http_status   INTEGER,
    response_json TEXT,
    device_id     TEXT,
    captured_at   TEXT,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS widget (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT
);
"""


# ── mysql-connector-shaped shim over sqlite3 ────────────────────────────────

class _Cursor:
    def __init__(self, cursor, dictionary):
        self._c = cursor
        self._dict = dictionary

    def execute(self, sql, params=()):
        return self._c.execute(sql.replace('%s', '?'), params)

    def _row(self, row):
        if row is None or not self._dict:
            return row
        return {d[0]: row[i] for i, d in enumerate(self._c.description)}

    def fetchone(self):
        return self._row(self._c.fetchone())

    def fetchall(self):
        return [self._row(r) for r in self._c.fetchall()]

    @property
    def lastrowid(self):
        return self._c.lastrowid

    def close(self):
        self._c.close()


class _Conn:
    def __init__(self, path):
        self._db = sqlite3.connect(path)

    def cursor(self, dictionary=False):
        return _Cursor(self._db.cursor(), dictionary)

    def commit(self):
        self._db.commit()

    def rollback(self):
        self._db.rollback()

    def close(self):
        self._db.close()


def _fresh_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def _widget_count():
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM widget").fetchone()[0]
    conn.close()
    return n


def main():
    _fresh_db()

    from flask import Flask, jsonify, request

    from src.mobileapp.src.sync import idempotency as idem

    # The guard does `from src.mobileapp.db import get_db` at import time, so the
    # name to patch lives in the guard's own module namespace.
    idem.get_db = lambda: _Conn(DB_PATH)
    idem._MISSING_LEDGER.clear()
    install_idempotency = idem.install_idempotency

    test_app = Flask(__name__)

    @test_app.route('/save-widget', methods=['POST'])
    def save_widget():
        data = request.get_json() or {}
        if data.get('bad'):
            return jsonify({'status': 'error', 'message': 'validation failed'}), 400
        db = _Conn(DB_PATH)
        cur = db.cursor()
        cur.execute("INSERT INTO widget (label) VALUES (%s)", (data.get('label'),))
        new_id = cur.lastrowid
        db.commit()
        cur.close()
        db.close()
        return jsonify({'status': 'success', 'id': new_id})

    install_idempotency(test_app)
    client = test_app.test_client()

    # 1. First call goes through and inserts exactly one row.
    r1 = client.post('/save-widget', json={'client_uuid': '11111111-1111-4111-8111-111111111111', 'label': 'first'})
    assert r1.status_code == 200, r1.status_code
    assert r1.get_json()['status'] == 'success'
    assert r1.get_json().get('duplicate') is None
    assert _widget_count() == 1, _widget_count()
    first_id = r1.get_json()['id']

    # 2. The retry a flaky link forces must NOT insert a second row, and must
    #    replay the original verdict verbatim (same server id).
    r2 = client.post('/save-widget', json={'client_uuid': '11111111-1111-4111-8111-111111111111', 'label': 'first'})
    assert r2.status_code == 200, r2.status_code
    assert r2.get_json()['duplicate'] is True, r2.get_json()
    assert r2.get_json()['id'] == first_id
    assert _widget_count() == 1, 'replay created a duplicate row'

    # 3. The key travelling as a header instead of in the body works the same.
    r3 = client.post('/save-widget', json={'label': 'first'},
                     headers={'X-Client-Uuid': '11111111-1111-4111-8111-111111111111'})
    assert r3.get_json()['duplicate'] is True
    assert _widget_count() == 1

    # 4. A genuinely different record still gets through.
    r4 = client.post('/save-widget', json={'client_uuid': '22222222-2222-4222-8222-222222222222', 'label': 'second'})
    assert r4.get_json()['status'] == 'success'
    assert _widget_count() == 2, _widget_count()

    # 5. A rejected request must release its claim, so a corrected retry with the
    #    same key is allowed to run — otherwise a typo would be unfixable forever.
    bad = client.post('/save-widget', json={'client_uuid': '33333333-3333-4333-8333-333333333333', 'bad': True})
    assert bad.status_code == 400
    fixed = client.post('/save-widget', json={'client_uuid': '33333333-3333-4333-8333-333333333333', 'label': 'third'})
    assert fixed.get_json()['status'] == 'success', fixed.get_json()
    assert fixed.get_json().get('duplicate') is None
    assert _widget_count() == 3, _widget_count()

    # 6. No key (an online-only endpoint) → guard stays out of the way entirely.
    plain = client.post('/save-widget', json={'label': 'fourth'})
    assert plain.get_json()['status'] == 'success'
    assert _widget_count() == 4
    conn = sqlite3.connect(DB_PATH)
    ledger = conn.execute("SELECT COUNT(*) FROM sync_client_uuid").fetchone()[0]
    conn.close()
    assert ledger == 3, f'ledger should hold the three test uuids only, got {ledger}'

    print('idempotency self-check OK — replays are safe, rejections stay retryable')


if __name__ == '__main__':
    main()
