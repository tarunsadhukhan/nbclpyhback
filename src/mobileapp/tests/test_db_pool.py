"""
Target: src/mobileapp/db.py — the connection pool that keeps a request off the
8-second MySQL handshake (skip_name_resolve=OFF on this server).

No database: the pool class and the direct-connect call are both stubbed, so
what is under test is the branching, not MySQL.

Run: python -m pytest src/mobileapp/tests/test_db_pool.py
"""
import time

from src.mobileapp import db as dbmod


class FakePool:
    """Stands in for MySQLConnectionPool; slow to build, like the real one."""
    built = 0

    def __init__(self, pool_name=None, pool_size=None, **config):
        FakePool.built += 1
        self.exhausted = False
        time.sleep(0.2)          # the real one opens pool_size connections here

    def get_connection(self):
        if self.exhausted:
            raise RuntimeError("pool exhausted")
        return "pooled"


def _reset(monkeypatch):
    dbmod._pools.clear()
    dbmod._building.clear()
    FakePool.built = 0
    monkeypatch.setattr(dbmod.pooling, "MySQLConnectionPool", FakePool)
    monkeypatch.setattr(dbmod, "current_db_name", lambda default: "tenant")
    monkeypatch.setattr(dbmod.mysql.connector, "connect", lambda **kw: "direct")


def _settle():
    for _ in range(50):
        if dbmod._pools.get("tenant") is not None:
            return
        time.sleep(0.05)


def test_first_call_does_not_wait_for_the_pool(monkeypatch):
    """The build runs on a background thread — the caller gets a direct connection."""
    _reset(monkeypatch)
    started = time.time()
    assert dbmod._connect(dbmod.DB_CONFIG) == "direct"
    assert time.time() - started < 0.15      # did not sit through the 0.2 s build
    _settle()
    assert dbmod._connect(dbmod.DB_CONFIG) == "pooled"


def test_pool_is_built_once_per_tenant(monkeypatch):
    """Concurrent misses must not each start their own build."""
    _reset(monkeypatch)
    for _ in range(5):
        dbmod._connect(dbmod.DB_CONFIG)
    _settle()
    for _ in range(5):
        dbmod._connect(dbmod.DB_CONFIG)
    assert FakePool.built == 1


def test_exhausted_pool_falls_back_instead_of_raising(monkeypatch):
    """A burst degrades to the slow path, never to a 500."""
    _reset(monkeypatch)
    dbmod._connect(dbmod.DB_CONFIG)
    _settle()
    dbmod._pools["tenant"].exhausted = True
    assert dbmod._connect(dbmod.DB_CONFIG) == "direct"
