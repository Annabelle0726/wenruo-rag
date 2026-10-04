import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location('wiki_generation_test_subject', Path(__file__).parents[3] / 'common/wiki_generation.py')
wg = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wg
spec.loader.exec_module(wg)


@pytest.fixture
def store():
    store = wg.ESGenerationStore(SimpleNamespace(es=object()))
    store.data = {'old': {'page': {'compile_kwd': 'wiki_page', 'content_with_weight': 'old'}},
                  'new': {'page': {'compile_kwd': 'wiki_page', 'content_with_weight': 'new'}}}
    store.rows = lambda index, kb, wiki_only=False: store.data[index]
    return store


def build(store):
    return wg.WikiBuild('tenant', 'kb', 'token', 'new', 'old', wg._digest(store.data['old']), completed=True)


@pytest.mark.parametrize('failed,completed', [(True, True), (True, False), (False, False)])
def test_incomplete_run_cannot_publish(store, failed, completed):
    b = build(store)
    b.failed, b.completed = failed, completed
    with pytest.raises(RuntimeError):
        store.validate(b)
    assert store.data['old']['page']['content_with_weight'] == 'old'


@pytest.mark.parametrize('rows', [{}, {'page': {'compile_kwd': 'wiki_page', 'content_with_weight': ''}}])
def test_empty_or_blank_result_is_not_a_success(store, rows):
    store.data['new'] = rows
    with pytest.raises(RuntimeError):
        store.validate(build(store))


def test_concurrent_manual_edit_refuses_publication(store):
    b = build(store)
    store.data['old']['page']['content_with_weight'] = 'manual edit'
    with pytest.raises(RuntimeError, match='changed'):
        store.validate(b)


def test_concurrent_clear_refuses_publication(store):
    b = build(store)
    store.data['old'] = {}
    with pytest.raises(RuntimeError, match='changed'):
        store.validate(b)


def test_valid_new_pages_leave_old_unchanged(store):
    assert store.validate(build(store)) == store.data['new']
    assert store.data['old']['page']['content_with_weight'] == 'old'


def test_context_scope_is_task_local(store):
    async def run():
        async def child(name):
            token = wg.BUILD.set(wg.WikiBuild(name, 'kb', 'token', name + '_stage', 'old', ''))
            await asyncio.sleep(0)
            assert wg.scoped_index(name) == name + '_stage'
            assert wg.scoped_index('other') == 'ragflow_other'
            wg.BUILD.reset(token)
        await asyncio.gather(child('a'), child('b'))
        assert wg.BUILD.get() is None
    asyncio.run(run())


def test_private_indexes_never_expand(monkeypatch):
    monkeypatch.setattr(wg, 'active_indexes', lambda *args: pytest.fail('must not query publication pointers'))
    assert wg.read_plan(['wiki_build_private'], ['kb'], {}) == (['wiki_build_private'], [])
    assert wg.read_plan(['ragflow_t'], ['kb'], {'must_not': {'exists': 'compile_kwd'}}) == (['ragflow_t'], [])


def test_published_read_hides_legacy_only_for_own_kb(monkeypatch):
    monkeypatch.setattr(wg, 'active_indexes', lambda *args: {'kb': 'wiki_build_new'})
    indexes, excluded = wg.read_plan(['ragflow_t'], ['kb', 'other'], {})
    assert indexes == ['ragflow_t', 'wiki_build_new']
    assert excluded == [{'bool': {'filter': [{'terms': {'_index': ['ragflow_t']}},
        {'term': {'kb_id': 'kb'}}, {'prefix': {'compile_kwd': 'wiki_'}}]}}]


def test_caught_write_failure_poisoned_build(store):
    b = build(store)
    token = wg.BUILD.set(b)
    try:
        wg.mark_failed()
        with pytest.raises(RuntimeError):
            store.validate(b)
    finally:
        wg.BUILD.reset(token)
