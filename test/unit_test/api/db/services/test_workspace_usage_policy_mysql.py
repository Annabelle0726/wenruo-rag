"""G7 on an ISOLATED production-type SQL engine (MySQL 8.0, real InnoDB locking).

The SQLite suites cannot decide this gate: they have no row locks and no real
transaction isolation, so they can neither prove that two writers serialize on the
tenant row nor that a stale writer leaves the committed value alone.

This test connects ONLY to the isolated MySQL given by the `U3_TEST_MYSQL_*`
environment variables. It is skipped with an explicit reason when that engine is
absent - it never falls back to the shared, production-shaped instance, because
writing policy there is forbidden.
"""

import os
import threading
from contextlib import contextmanager

import pytest
from peewee import MySQLDatabase

from api.db.db_models import Tenant, UserTenant, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage
from api.db.services import workspace_budget_service as budget

HOST = os.environ.get("U3_TEST_MYSQL_HOST")
PORT = int(os.environ.get("U3_TEST_MYSQL_PORT", "3399"))
USER = os.environ.get("U3_TEST_MYSQL_USER", "root")
PASSWORD = os.environ.get("U3_TEST_MYSQL_PASSWORD", "")
DATABASE = os.environ.get("U3_TEST_MYSQL_DATABASE", "u3a_iso")

pytestmark = pytest.mark.skipif(
    not HOST,
    reason="U3_TEST_MYSQL_HOST must point at an ISOLATED MySQL 8.0 container",
)

# Every model `configure_budget` reaches, including the counter table its
# `usage_snapshot` reads: a model left out here stays bound to the application's
# own database and the block would then span two of them.
MODELS = [Tenant, UserTenant, WorkspaceBudget, WorkspaceUsage, WorkspaceAudit]


@contextmanager
def one_database(database):
    """Make every name that reaches the app database resolve to ONE object.

    A peewee transaction is a property of the `Database` object that opened it, and
    `Model._meta.database` decides which object issues a statement. Production has
    exactly one object -- `bind_ctx` appears nowhere in product code -- so
    `DB.atomic()` and every statement inside it share a connection and a
    transaction. A gate that binds the models to a SECOND object does not test
    that: the statements run on the second object, outside the transaction, and the
    tenant-row lock the service relies on is released with its own statement.

    `bind_ctx` covers the models; the service reaches its database through the
    module-level name it imported, so that name has to be re-pointed as well.
    """
    from api.db import db_models

    previous_models = db_models.DB
    previous_service = budget.DB
    db_models.DB = database
    budget.DB = database
    try:
        with database.bind_ctx(MODELS):
            yield database
    finally:
        db_models.DB = previous_models
        budget.DB = previous_service


@pytest.fixture(scope="module")
def mysql(tmp_path_factory):
    # The database is created FIRST, through a connection that does not name it:
    # pymysql connects on open, so naming a database that does not exist yet fails
    # before the CREATE could run.
    bootstrap = MySQLDatabase("mysql", host=HOST, port=PORT, user=USER, password=PASSWORD)
    bootstrap.connect(reuse_if_open=True)
    bootstrap.execute_sql(f"CREATE DATABASE IF NOT EXISTS {DATABASE}")
    bootstrap.close()
    db = MySQLDatabase(
        DATABASE,
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        charset="utf8mb4",
    )
    with one_database(db):
        db.create_tables(MODELS)
        assert "InnoDB" in str(db.execute_sql("SHOW TABLE STATUS LIKE 'workspace_budget'").fetchone())
        for model in MODELS:
            model.delete().execute()
        Tenant.create(id="ws-iso", name="ws-iso", llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        Tenant.create(id="ws-other", name="ws-other", llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        for user, role in (("owner-a", "owner"), ("admin-b", "admin")):
            UserTenant.create(id=f"{user}-ws-iso", tenant_id="ws-iso", user_id=user, role=role, status="1", invited_by="owner-a")
        yield db
        if not db.is_closed():
            db.close()


def test_the_isolated_engine_really_is_mysql(mysql):
    version = mysql.execute_sql("SELECT VERSION()").fetchone()[0]
    assert version.startswith("8.0"), version


def test_the_gate_really_did_bind_one_database_object(mysql):
    """The serialization the other two tests judge only exists under this wiring.

    Without it the tenant self-update runs on an autocommit connection, its lock is
    released with the statement, and two writers can both pass the revision check
    and commit -- which is what this gate reported before the binding was fixed.
    """
    from api.db import db_models

    assert budget.DB is mysql
    assert db_models.DB is mysql
    for model in MODELS:
        assert model._meta.database is mysql, model.__name__


def test_g7_two_writers_from_one_revision_lose_no_update(mysql):
    with mysql.bind_ctx(MODELS):
        baseline = budget.configure_budget(
            "ws-iso", "owner-a", {"calls_per_day": 100, "tokens_per_day": 1000}
        )
        revision = baseline["policy_revision"]
        WorkspaceAudit.delete().where(WorkspaceAudit.tenant_id == "ws-iso").execute()

        # Two administrators hold the SAME revision, as a UI that loaded before
        # either saved would.
        outcomes = {}
        barrier = threading.Barrier(2)

        def writer(operator, value):
            barrier.wait(timeout=30)
            try:
                budget.configure_budget(
                    "ws-iso", operator, {"calls_per_day": value}, expected_revision=revision
                )
                outcomes[operator] = "saved"
            except budget.PolicyConflict:
                outcomes[operator] = "conflict"
            except Exception as exc:  # noqa: BLE001 - a different failure must fail the gate
                outcomes[operator] = f"error:{type(exc).__name__}"

        threads = [
            threading.Thread(target=writer, args=("owner-a", 111)),
            threading.Thread(target=writer, args=("admin-b", 222)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        # Exactly one writer committed, and the other was told why.
        assert sorted(outcomes.values()) == ["conflict", "saved"], outcomes

        winner = "owner-a" if outcomes["owner-a"] == "saved" else "admin-b"
        expected = 111 if winner == "owner-a" else 222
        stored = WorkspaceBudget.get_by_id("ws-iso")

        # No lost update: the stored value is the winner's, not a blend and not the
        # loser's.
        assert stored.calls_per_day == expected
        # The loser is identifiable by the absence of ITS value.
        assert stored.calls_per_day != (222 if expected == 111 else 111)
        # Unrelated fields survive the partial update.
        assert stored.tokens_per_day == 1000

        # A refused write leaves no success audit; the committed one leaves exactly
        # one, from the writer that won.
        audits = list(WorkspaceAudit.select().where(WorkspaceAudit.tenant_id == "ws-iso"))
        assert len(audits) == 1
        assert audits[0].operator_id == winner

        # The committed revision moved on, and the loser can save after a refresh.
        refreshed = budget.configure_budget("ws-iso", "owner-a")
        assert refreshed["policy_revision"] != revision
        recovered = budget.configure_budget(
            "ws-iso",
            "admin-b",
            {"calls_per_month": 4321},
            expected_revision=refreshed["policy_revision"],
        )
        assert recovered["calls_per_month"] == 4321
        assert WorkspaceBudget.get_by_id("ws-iso").calls_per_day == expected


def test_g7_policy_writes_serialize_against_each_other_on_the_tenant_lock(mysql):
    with mysql.bind_ctx(MODELS):
        current = budget.configure_budget("ws-iso", "owner-a")
        revision = current["policy_revision"]

        # Ten concurrent writers on the same revision: exactly one may commit, and
        # the rest must be refused rather than merged or half-applied.
        results = []
        lock = threading.Lock()
        barrier = threading.Barrier(10)

        def writer(index):
            barrier.wait(timeout=30)
            try:
                budget.configure_budget(
                    "ws-iso",
                    "admin-b",
                    {"tokens_per_day": 5000 + index},
                    expected_revision=revision,
                )
                outcome = "saved"
            except budget.PolicyConflict:
                outcome = "conflict"
            except Exception as exc:  # noqa: BLE001
                outcome = f"error:{type(exc).__name__}"
            with lock:
                results.append((outcome, 5000 + index))

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        saved = [value for outcome, value in results if outcome == "saved"]
        errors = [outcome for outcome, _ in results if outcome.startswith("error")]
        assert errors == [], results
        assert len(saved) == 1, results
        assert WorkspaceBudget.get_by_id("ws-iso").tokens_per_day == saved[0]
