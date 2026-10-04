"""Exercise the real queue function without database/Redis side effects."""
import ast
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
from contextvars import ContextVar
import pytest
import xxhash

def queue_function():
    source = Path(__file__).parents[4] / 'api/db/services/document_service.py'
    node = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'queue_raptor_o_graphrag_tasks')
    persisted, queued = [], []
    identity = ContextVar('test_execution_user', default=None)
    namespace = dict(execution_user=identity, xxhash=xxhash, datetime=datetime,
        MAXIMUM_TASK_PAGE_NUMBER=100000000, get_uuid=lambda: 'task', Task=object(),
        DocumentService=SimpleNamespace(get_chunking_config=lambda _: {}, begin2parse=lambda *a, **k: None),
        bulk_insert_into_db=lambda model, tasks, replace: persisted.extend(tasks),
        REDIS_CONN=SimpleNamespace(queue_product=lambda name, message: queued.append(message.copy()) or True),
        settings=SimpleNamespace(get_svr_queue_name=lambda *args: 'queue'))
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['queue_raptor_o_graphrag_tasks'], identity, persisted, queued

@pytest.mark.parametrize('caller', ['normal-member', 'workspace-owner', None])
def test_wiki_queue_persists_authenticated_identity(caller):
    queue, identity, persisted, queued = queue_function()
    identity.set(caller)
    queue({'id': 'source-doc', 'user_id': 'untrusted-tracing-user'}, 'wiki', 0, 'fake-doc', ['source-doc'])
    assert persisted[0]['initiator_user_id'] == caller
    assert queued[0]['initiator_user_id'] == caller

def test_unrelated_task_payload_is_unchanged():
    queue, identity, persisted, queued = queue_function()
    identity.set('normal-member')
    queue({'id': 'source-doc'}, 'mindmap', 0, 'fake-doc', ['source-doc'])
    assert 'initiator_user_id' not in persisted[0]
