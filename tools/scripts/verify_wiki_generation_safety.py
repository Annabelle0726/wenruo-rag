"""Controlled fault tests against a TEST stack; never invoke a real provider.

Run with the candidate source on PYTHONPATH and test-only service_conf. Fixtures
have fresh IDs, use their own valid Wiki template and are removed on completion.
The existing six-document KB, its invalid template and its binding are not edited.
"""
import asyncio
import copy
import json
import uuid
from unittest.mock import patch

from common import settings
settings.init_settings()
from api.db.db_models import (DB, Knowledgebase, Document, UserCanvas, CompilationTemplate,
                             CompilationTemplateGroup, WikiGeneration, FileCommit, FileCommitItem, File, File2Document)
from api.db.services.compilation_template_group_service import CompilationTemplateGroupService
from api.db.services.wiki_readiness_service import wiki_readiness
from common.wiki_generation import ESGenerationStore, BUILD, generate_safely, readable_index
from common.doc_store.doc_store_base import OrderByExpr
from rag.svr.task_executor_refactor.task_context import TaskContext, TaskLimiters, TaskCallbacks
from rag.svr.task_executor_refactor.dataset_wiki_generator import run_wiki_incremental, _wiki_reset_all_wiki_state


def uid():
    return uuid.uuid4().hex


async def main():
    # Refuse accidental use of the production network/configuration.
    assert DB.connect_params.get('host') == 'mysql', 'Use the isolated wrt network only'
    original = Knowledgebase.get_by_id('9463d93eb97511f1938f2592e9bc6fe4')
    tenant = original.tenant_id
    kb_id, doc_id, pipeline_id, file_id = uid(), uid(), uid(), uid()
    store = ESGenerationStore(settings.docStoreConn)
    WikiGeneration.create_table(safe=True)
    base = f'ragflow_{tenant}'
    baseline = store.rows(base, original.id)
    reports = {}
    group = None
    try:
        builtin = CompilationTemplate.get_by_id('wiki')
        group = CompilationTemplateGroupService.create_group(tenant, 'Wiki safety regression (temporary)', '',
            [{'name': 'Wiki safety regression', 'kind': 'wiki', 'config': copy.deepcopy(builtin.config)}])
        template_id = group['templates'][0]['id']
        model = 'deepseek-v4-flash@DS@DeepSeek'
        canvas = {'components': {'Compiler:test': {'obj': {'component_name': 'Compiler', 'params': {
            'llm_id': model, 'compilation_template_group_ids': [group['id']]}}}}}
        UserCanvas.create(id=pipeline_id, tenant_id=tenant, user_id=original.created_by, title='Wiki safety temporary pipeline',
                          canvas_category='dataflow_canvas', dsl=canvas)
        kb_fields = dict(original.__data__)
        kb_fields.update(id=kb_id, name='Wiki safety regression (temporary)', pipeline_id=pipeline_id,
                         wiki_task_id=None, wiki_task_finish_at=None, doc_num=1, chunk_num=1)
        kb = Knowledgebase.create(**kb_fields)
        source_doc = Document.select().where(Document.kb_id == original.id).first()
        fields = dict(source_doc.__data__)
        fields.update(id=doc_id, kb_id=kb_id, name='Wiki safety source.txt', pipeline_id=pipeline_id,
                      parser_config={}, progress=1, chunk_num=1)
        Document.create(**fields)
        source_link = File2Document.select().where(File2Document.document_id == source_doc.id).first()
        file_fields = dict(File.get_by_id(source_link.file_id).__data__)
        file_fields.update(id=file_id, name='Wiki safety source.txt')
        File.create(**file_fields)
        File2Document.create(id=uid(), file_id=file_id, document_id=doc_id)
        old_page = {'id': f'{kb_id}-page', 'compile_kwd': 'wiki_page', 'kb_id': kb_id,
                    'slug_kwd': 'entity/test', 'page_type_kwd': 'entity', 'title_kwd': 'Old page',
                    'content_with_weight': 'Previous validated Wiki', 'q_1024_vec': [0.01] * 1024}
        assert not settings.docStoreConn.insert([old_page, {'id': f'{kb_id}-source', 'doc_id': doc_id,
            'content_with_weight': 'Source evidence', 'available_int': 1}], base, kb_id)
        ready = wiki_readiness(kb, kb.created_by)
        assert ready['ready'], ready
        reports['valid_own_template_ready'] = True

        events = []
        ctx = TaskContext({'id': uid(), 'tenant_id': tenant, 'kb_id': kb_id, 'language': 'Chinese'},
                          TaskLimiters(), TaskCallbacks(progress=lambda *a, **kw: events.append((a, kw))))

        def visible():
            result = settings.docStoreConn.search(['content_with_weight'], [], {'compile_kwd': ['wiki_page']},
                [], OrderByExpr(), 0, 100, base, [kb_id])
            return [r['content_with_weight'] for r in settings.docStoreConn.get_fields(result, ['content_with_weight']).values()]

        for case in ('model_change_429', 'midway_failure', 'reported_incomplete', 'cancelled'):
            async def fail():
                assert visible() == ['Previous validated Wiki']
                from api.apps.services.dataset_api_service import clear_wiki
                allowed, _ = await clear_wiki(kb_id, kb.created_by)
                assert not allowed, 'manual clear must not race a build'
                if case == 'cancelled':
                    ctx.callbacks.has_canceled = lambda task_id: True
                    ctx.progress_cb(1, 'finished before cancellation')
                    return
                if case == 'model_change_429':
                    await _wiki_reset_all_wiki_state(tenant, kb_id)
                    assert visible() == ['Previous validated Wiki']
                    raise RuntimeError('429 RESOURCE_EXHAUSTED')
                new = dict(old_page, content_with_weight='Unfinished draft')
                assert not settings.docStoreConn.insert([new], BUILD.get().index, kb_id)
                assert visible() == ['Previous validated Wiki']
                if case == 'reported_incomplete':
                    ctx.progress_cb(-1, 'MAP incomplete')
                    return
                raise RuntimeError('controlled halfway failure')
            try:
                await generate_safely(ctx, fail)
                raise AssertionError('failure was published')
            except RuntimeError:
                pass
            ctx.callbacks.has_canceled = lambda task_id: False
            assert visible() == ['Previous validated Wiki']
            assert not WikiGeneration.get_by_id(kb_id).active_index
            assert FileCommit.select().where(FileCommit.folder_id == kb_id).count() == 0
            reports[case] = 'old body + index pointer + history unchanged'

        # A queued job must re-check the template, not trust the earlier readiness.
        CompilationTemplateGroup.update(status='0').where(CompilationTemplateGroup.id == group['id']).execute()
        assert not wiki_readiness(kb, kb.created_by)['ready']
        async def chunks(*args, **kwargs):
            yield []
        try:
            await run_wiki_incremental(ctx, object(), chunks)
            raise AssertionError('invalid template accepted')
        except RuntimeError:
            pass
        assert visible() == ['Previous validated Wiki']
        reports['template_invalidated_after_queue'] = 'blocked; old Wiki readable'
        CompilationTemplateGroup.update(status='1').where(CompilationTemplateGroup.id == group['id']).execute()

        async def success():
            await _wiki_reset_all_wiki_state(tenant, kb_id)
            new = {k: v for k, v in old_page.items() if k != 'q_1024_vec'}
            new.update(content_with_weight='New validated Wiki', q_3072_vec=[0.01] * 3072)
            assert not settings.docStoreConn.insert([new], BUILD.get().index, kb_id)
            assert visible() == ['Previous validated Wiki']
            ctx.progress_cb(1, 'finished')
        await generate_safely(ctx, success)
        assert visible() == ['New validated Wiki']
        assert settings.docStoreConn.get(old_page['id'], base, [kb_id])['content_with_weight'] == 'New validated Wiki'
        assert store.rows(base, kb_id)[old_page['id']]['content_with_weight'] == 'Previous validated Wiki'
        assert all(r.get('compile_kwd', '').startswith('wiki_') for r in store.rows(readable_index(tenant, kb_id), kb_id).values())
        assert FileCommit.select().where(FileCommit.folder_id == kb_id).count() == 1
        reports['successful_switch'] = 'only new Wiki visible; old physical body retained; one committed version'

        # Failed version persistence must abort publication, too.
        before = readable_index(tenant, kb_id)
        with patch('api.db.services.file_commit_service._store_content_after', side_effect=RuntimeError('storage unavailable')):
            async def history_failure():
                assert not settings.docStoreConn.insert([dict(old_page, content_with_weight='must not publish')], BUILD.get().index, kb_id)
                ctx.progress_cb(1, 'finished')
            try:
                await generate_safely(ctx, history_failure)
                raise AssertionError('history failure published')
            except RuntimeError:
                pass
        assert readable_index(tenant, kb_id) == before
        assert visible() == ['New validated Wiki']
        reports['version_storage_failure'] = 'publication transaction rolled back'
        assert store.rows(base, original.id) == baseline
        reports['existing_dataset_untouched'] = True
        print('WIKI_SAFETY_REPORT=' + json.dumps(reports, ensure_ascii=False))
    finally:
        # Exact fresh fixture IDs only. No existing workspace rows or indexes removed.
        ids = [r.id for r in FileCommit.select().where(FileCommit.folder_id == kb_id)]
        FileCommitItem.delete().where(FileCommitItem.commit_id.in_(ids)).execute()
        FileCommit.delete().where(FileCommit.id.in_(ids)).execute()
        WikiGeneration.delete().where(WikiGeneration.kb_id == kb_id).execute()
        File2Document.delete().where(File2Document.document_id == doc_id).execute()
        File.delete().where(File.id == file_id).execute()
        Document.delete().where(Document.id == doc_id).execute()
        Knowledgebase.delete().where(Knowledgebase.id == kb_id).execute()
        UserCanvas.delete().where(UserCanvas.id == pipeline_id).execute()
        if group:
            CompilationTemplate.delete().where(CompilationTemplate.group_id == group['id']).execute()
            CompilationTemplateGroup.delete().where(CompilationTemplateGroup.id == group['id']).execute()
        settings.docStoreConn.es.delete_by_query(index=base, query={'term': {'kb_id': kb_id}}, refresh=True)
        for index in settings.docStoreConn.es.indices.get(index=f'wiki_build_{kb_id}_*', allow_no_indices=True):
            assert index.startswith(f'wiki_build_{kb_id}_')
            settings.docStoreConn.es.indices.delete(index=index)


asyncio.run(main())
