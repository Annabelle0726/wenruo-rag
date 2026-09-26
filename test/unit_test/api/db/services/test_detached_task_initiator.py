"""A queued task records WHO caused it, so a worker can attribute its model calls.

The end-user id a request may carry is a TRACING value; only the authenticated
caller is persisted, and it is read back through the same join the worker uses.
"""

from types import SimpleNamespace

import pytest
from peewee import SqliteDatabase

from api.db.db_models import Document, Knowledgebase, Task, Tenant, User, UserTenant
from api.db.services import task_service
from common.workspace_context import execution_user


@pytest.fixture
def tasks_db(tmp_path, monkeypatch):
    models = [Tenant, User, UserTenant, Knowledgebase, Document, Task]
    db = SqliteDatabase(tmp_path / "tasks.sqlite", timeout=20)
    with db.bind_ctx(models):
        db.create_tables(models)
        queued = []
        monkeypatch.setattr(task_service, "DB", db)
        monkeypatch.setattr(task_service, "REDIS_CONN", SimpleNamespace(queue_product=lambda name, message: queued.append((name, message)) or True))
        monkeypatch.setattr(task_service, "settings", SimpleNamespace(get_svr_queue_name=lambda priority, suffix: f"queue-{suffix}"))
        monkeypatch.setattr(task_service.DocumentService, "begin2parse", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(task_service.DocumentService, "get_knowledgebase_id", lambda _doc_id: "kb")
        monkeypatch.setattr(task_service.DocumentService, "get_chunking_config", lambda _doc_id: {})
        monkeypatch.setattr(task_service, "seed_doc_chunking_counter", lambda _doc_id, _count: True)
        Tenant.create(id="workspace", name="workspace", llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        User.create(id="member", nickname="member", email="member@example.test")
        Knowledgebase.create(id="kb", tenant_id="workspace", name="kb", embd_id="", created_by="member")
        Document.create(id="doc1", kb_id="kb", parser_id="naive", type="txt", name="x.txt", suffix="txt", created_by="member")
        # The real helper writes through its own module-level DB handle.
        from api.db import db_utils

        monkeypatch.setattr(db_utils, "DB", db)
        yield db, queued
        if not db.is_closed():
            db.close()


def _run_as(user_id, function, *args, **kwargs):
    token = execution_user.set(user_id) if user_id else None
    try:
        return function(*args, **kwargs)
    finally:
        if token is not None:
            execution_user.reset(token)


def test_queue_tasks_records_the_authenticated_caller(tasks_db):
    _, queued = tasks_db
    doc = {"id": "doc1", "type": "txt", "parser_id": "naive", "parser_config": {}, "name": "x.txt"}

    _run_as("member", task_service.queue_tasks, doc, "bucket", "x.txt", 0)

    stored = [t for t in Task.select() if t.doc_id == "doc1"]
    assert len(stored) == 1 and stored[0].initiator_user_id == "member"
    assert stored[0].id == queued[0][1]["id"]
    assert queued[0][0] == "queue-common"


def test_queue_tasks_without_an_authenticated_caller_records_none(tasks_db):
    doc = {"id": "doc1", "type": "txt", "parser_id": "naive", "parser_config": {}, "name": "x.txt"}

    _run_as(None, task_service.queue_tasks, doc, "bucket", "x.txt", 0)

    assert {t.initiator_user_id for t in Task.select()} == {None}


def test_queue_dataflow_records_the_authenticated_caller(tasks_db):
    _, queued = tasks_db

    ok, message = _run_as("member", task_service.queue_dataflow, "workspace", "flow", "task-1", doc_id="doc1")

    assert ok and message == ""
    assert Task.get_by_id("task-1").initiator_user_id == "member"
    assert queued[0][1]["tenant_id"] == "workspace"


def test_get_task_returns_the_initiator_and_the_workspace(tasks_db):
    """The worker's contract: one read yields both the actor and its tenant."""
    task_service.TaskService.model.insert(id="task-9", doc_id="doc1", initiator_user_id="member", from_page=0, to_page=1).execute()

    task = task_service.TaskService.get_task("task-9")

    assert task["tenant_id"] == "workspace"
    assert task["initiator_user_id"] == "member"
    assert task["doc_id"] == "doc1"


def test_get_task_with_a_legacy_row_returns_no_initiator(tasks_db):
    task_service.TaskService.model.insert(id="task-legacy", doc_id="doc1", from_page=0, to_page=1).execute()

    task = task_service.TaskService.get_task("task-legacy")

    assert task["initiator_user_id"] is None
    assert task["tenant_id"] == "workspace"
