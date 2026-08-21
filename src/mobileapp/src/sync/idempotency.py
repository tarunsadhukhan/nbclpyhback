"""Replay guard for offline uploads.

A device that loses the response to a POST cannot know whether the row landed.
It retries, and without a guard that is a double punch. Every offline-queued
write therefore carries a `client_uuid` (UUID v4, generated once at capture on
the device and never regenerated on retry).

ponytail: this is ONE before/after_request pair on the mobile Flask app rather
than a decorator applied to every route plus a client_uuid column on every
transaction table. It covers all mobile blueprints, including routes that do not
exist yet.

Multi-tenant safe: get_db() resolves the database per request from X-Tenant /
the Host subdomain, so the ledger is written in whichever tenant DB the request
belongs to. The `sync_client_uuid` table therefore has to exist in each tenant
database — until it does, the guard fails open (see _ledger_known_missing) and
the API behaves exactly as it did before, re-probing periodically so a migration
applied while the service is running takes effect without a restart.

Ceiling: the ledger row is committed separately from the business INSERT, so a
process kill in the microseconds between the two can still let a replay through.
Upgrade path if that ever bites: move the ledger INSERT into the handler's own
transaction for the specific route that matters.
"""
import json
from datetime import datetime

from flask import g, jsonify, request

from src.mobileapp.db import get_db

# Routes that must never be de-duplicated: they are either idempotent already,
# read-only in effect, or need to run on every call.
_SKIP_PREFIXES = ('/login', '/sync/')

# Tenants whose database has no sync_client_uuid table yet: {tenant: last_seen}.
# Cached so a missing migration costs one failed query every RECHECK_SECS rather
# than one per request — but NOT cached forever, because the documented rollout
# is "deploy the code, migrate later", and a permanent cache would leave replay
# protection off until someone restarted the service.
_MISSING_LEDGER = {}
_RECHECK_SECS = 600


def _ledger_known_missing(tenant):
    seen = _MISSING_LEDGER.get(tenant)
    if seen is None:
        return False
    if (datetime.now() - seen).total_seconds() > _RECHECK_SECS:
        _MISSING_LEDGER.pop(tenant, None)   # re-probe: it may have been migrated
        return False
    return True


def _tenant_key():
    """Identifies the tenant DB for the missing-table cache."""
    return (request.headers.get('X-Tenant')
            or request.headers.get('subdomain')
            or request.host or 'default')


def _client_uuid():
    """The idempotency key, from the JSON body or the X-Client-Uuid header."""
    uuid = request.headers.get('X-Client-Uuid')
    if not uuid:
        try:
            body = request.get_json(silent=True) or {}
            uuid = body.get('client_uuid') if isinstance(body, dict) else None
        except Exception:
            uuid = None
    uuid = (uuid or '').strip()
    if not uuid:
        return None
    # A junk key is worse than no key: if a buggy client sent "1" for every
    # record, the ledger would collapse to one row and every write after the
    # first would be swallowed as a duplicate. Reject and say so loudly.
    if not (8 <= len(uuid) <= 36):
        print(f"WARN idempotency: ignoring malformed client_uuid {uuid!r} on {request.path}")
        return None
    return uuid


def _parse_captured_at():
    raw = request.headers.get('X-Captured-At')
    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def install_idempotency(app):
    """Attach the replay guard to [app]. Call once, after all blueprints."""

    @app.before_request
    def _claim_client_uuid():
        if request.method not in ('POST', 'PUT'):
            return None
        if any(request.path.startswith(p) for p in _SKIP_PREFIXES):
            return None
        tenant = _tenant_key()
        if _ledger_known_missing(tenant):
            return None
        uuid = _client_uuid()
        if not uuid:
            return None

        db = cursor = None
        try:
            db = get_db()
            cursor = db.cursor(dictionary=True)
            try:
                cursor.execute(
                    """INSERT INTO sync_client_uuid
                           (client_uuid, endpoint, device_id, captured_at, created_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (uuid, request.path[:160], request.headers.get('X-Device-Id'),
                     _parse_captured_at(), datetime.now()))
                db.commit()
            except Exception as exc:
                db.rollback()
                # Table not migrated in this tenant → stand aside, re-probe later.
                if '1146' in str(exc) or "doesn't exist" in str(exc).lower():
                    _MISSING_LEDGER[tenant] = datetime.now()
                    print(f"WARN idempotency: sync_client_uuid missing for tenant "
                          f"{tenant!r}; replay protection OFF, re-probing in "
                          f"{_RECHECK_SECS}s")
                    return None
                # Duplicate key → this uuid was seen before. Replay the verdict.
                cursor.execute(
                    "SELECT http_status, response_json FROM sync_client_uuid WHERE client_uuid=%s",
                    (uuid,))
                row = cursor.fetchone()
                if row is None:
                    return None  # not a duplicate-key error after all; let it run
                if row['http_status'] is None:
                    # Still in flight on another worker — tell the device to wait.
                    return jsonify({'status': 'error', 'message': 'Request already in progress',
                                    'retry': True}), 409
                body = row['response_json']
                try:
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {'status': 'success'}
                if isinstance(payload, dict):
                    payload['duplicate'] = True
                return jsonify(payload), row['http_status']
            g._sync_client_uuid = uuid
        except Exception as exc:
            # The guard must never take the API down; fall through unguarded.
            print(f"WARN idempotency: guard skipped ({exc})")
            g.pop('_sync_client_uuid', None)
        finally:
            if cursor is not None:
                try: cursor.close()
                except Exception: pass
            if db is not None:
                try: db.close()
                except Exception: pass
        return None

    @app.after_request
    def _store_response(response):
        uuid = g.pop('_sync_client_uuid', None)
        if not uuid:
            return response
        db = cursor = None
        try:
            db = get_db()
            cursor = db.cursor()
            if 200 <= response.status_code < 300:
                body = response.get_data(as_text=True)
                cursor.execute(
                    "UPDATE sync_client_uuid SET http_status=%s, response_json=%s WHERE client_uuid=%s",
                    (response.status_code, body[:16000000], uuid))
            else:
                # Failed → drop the claim so a corrected retry is allowed through.
                cursor.execute("DELETE FROM sync_client_uuid WHERE client_uuid=%s", (uuid,))
            db.commit()
        except Exception:
            pass
        finally:
            if cursor is not None:
                try: cursor.close()
                except Exception: pass
            if db is not None:
                try: db.close()
                except Exception: pass
        return response

    @app.teardown_request
    def _release_stale_claim(exc):
        # after_request does not run when the handler raised; release the claim
        # so the device's retry is not answered "already in progress" forever.
        uuid = g.pop('_sync_client_uuid', None)
        if not uuid or exc is None:
            return
        try:
            db = get_db()
            cursor = db.cursor()
            cursor.execute(
                "DELETE FROM sync_client_uuid WHERE client_uuid=%s AND http_status IS NULL",
                (uuid,))
            db.commit()
            cursor.close()
            db.close()
        except Exception:
            pass
