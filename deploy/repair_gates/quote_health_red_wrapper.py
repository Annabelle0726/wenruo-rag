"""Test-only harness wrapper: prevent relational-store access, then run the unmodified RED probe.

It patches only infrastructure (peewee's connect entry points and the module-level DB handle), never
`async_chat`, its nested `decorate_answer`, the quote branch, reference construction or `structure_answer`.
"""
import runpy
import sys
import traceback

sys.path.insert(0, "/ragflow")

import peewee  # noqa: E402

PATCHED = []


def no_connect(self, *args, **kwargs):
    """No relational store in this environment: connecting becomes a no-op."""
    return None


for name in ("Database", "MySQLDatabase", "PooledMySQLDatabase", "SqliteDatabase"):
    cls = getattr(peewee, name, None)
    if cls is None or "connect" not in vars(cls):
        continue
    original = cls.connect
    cls.connect = no_connect
    cls._original_connect = original
    PATCHED.append(f"peewee.{name}.connect")

class _NullCursor:
    """A cursor that finds nothing: every remaining relational read returns 'no rows' instead of
    connecting, so service lookups resolve to absence rather than crashing. No relational store is
    contacted, and no code under test is replaced."""

    description = []
    rowcount = 0
    arraysize = 1
    lastrowid = None

    def execute(self, *args, **kwargs):
        return self

    def executemany(self, *args, **kwargs):
        return self

    def fetchone(self):
        return None

    def fetchmany(self, *args, **kwargs):
        return []

    def fetchall(self):
        return []

    def close(self):
        return None

    def __iter__(self):
        return iter(())


# Cursor / execute paths would raise on the None connection; make them return a null cursor instead so
# the coroutine can continue to the code under test.
for name in ("Database", "MySQLDatabase", "PooledMySQLDatabase"):
    cls = getattr(peewee, name, None)
    if cls is None:
        continue
    if "cursor" in vars(cls):
        cls.cursor = lambda self, *a, **k: _NullCursor()
        PATCHED.append(f"peewee.{name}.cursor")
    if "execute_sql" in vars(cls):
        cls.execute_sql = lambda self, *a, **k: _NullCursor()
        PATCHED.append(f"peewee.{name}.execute_sql")

# Neutralise ORM reads at the model level: every relational read resolves to absence instead of opening a
# connection. Service objects, `async_chat`, `decorate_answer`, the quote branch and reference
# construction are all left exactly as the product wrote them.
for name, replacement in (
    ("get_or_none", classmethod(lambda cls, *a, **k: None)),
    ("get_or_none_by_id", classmethod(lambda cls, *a, **k: None)),
    ("get_by_id", classmethod(lambda cls, *a, **k: None)),
    ("select", classmethod(lambda cls, *a, **k: [])),
    ("raw", classmethod(lambda cls, *a, **k: [])),
):
    if hasattr(peewee.Model, name):
        setattr(peewee.Model, name, replacement)
        PATCHED.append(f"peewee.Model.{name}")

try:
    from api.db.services import dialog_service as ds

    db_handle = getattr(ds, "DB", None)
    if db_handle is not None:
        for attribute in ("connect", "cursor", "execute_sql"):
            if hasattr(db_handle, attribute):
                try:
                    setattr(db_handle, attribute, (lambda *a, **k: None))
                    PATCHED.append(f"dialog_service.DB.{attribute}")
                except Exception:  # noqa: BLE001
                    pass
except Exception:  # noqa: BLE001
    traceback.print_exc()

print(f"PATCHED: {PATCHED}", flush=True)
print("=== running the unmodified RED probe ===", flush=True)
try:
    runpy.run_path("/tmp/quote_health_red_probe.py", run_name="__main__")
except SystemExit as exit_code:
    print(f"probe exited with {exit_code.code}", flush=True)
