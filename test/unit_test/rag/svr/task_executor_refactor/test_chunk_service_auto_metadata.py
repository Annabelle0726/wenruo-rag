#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Wiring tests: the DEFAULT chunking path tags the document's metadata.

``TE_RUN_MODE`` defaults to ``"0"``, which runs
``ChunkService.build_chunks`` in ``rag/svr/task_executor_refactor/`` — not the
original executor. The auto metadata pass was first wired only into the original
one, so on the default path nothing was ever written: the parse succeeded, every log
line looked healthy, and the file list kept saying ``0 fields``. These tests pin the
call in the default path, the identity it carries, and its place in the flow.

The context binding itself is covered by ``test_chunk_service_doc_context.py``; here
it is a recorder, because what these tests are about is that the metadata pass runs
AFTER it (so the field and the chunk prefix cannot disagree) and BEFORE the chunk
preparation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag.svr import auto_metadata_service as service
from rag.svr.task_executor_refactor import chunk_service
from rag.svr.task_executor_refactor.chunk_service import ChunkService
from test.unit_test.rag.svr.task_executor_refactor.conftest import create_mock_settings, make_task_context

pytestmark = pytest.mark.p2

#: A name the zero-token fast path identifies completely, so the tagging needs no
#: model call at all.
NAMED_DOC = "Q_GDW 73289.2-2026 450_750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范_2.pdf"
CHUNKS = [{"content_with_weight": "额定电压450/750V及以下聚氯乙烯绝缘电缆\n第2部分：专用技术规范"}]


async def _build(name=NAMED_DOC, chunks=None, ctx_overrides=None, bind=None):
    """Run the real ``ChunkService.build_chunks`` over canned parser output.

    ``get_parser`` and ``thread_pool_exec`` are patched for the whole call (the real
    parser factory would import every chunker, and deepdoc with it), and
    ``apply_document_context`` is a recorder by default.
    """
    chunks = chunks if chunks is not None else [dict(ck) for ck in CHUNKS]
    ctx = make_task_context(name=name, language="Chinese", doc_id="doc_incident", kb_id="kb_1", **(ctx_overrides or {}))
    binder = bind if bind is not None else MagicMock(return_value=0)
    with (
        patch("rag.svr.task_executor_refactor.chunk_service.get_parser") as mock_get_parser,
        patch("rag.svr.task_executor_refactor.chunk_builder.thread_pool_exec", AsyncMock(return_value=chunks)),
        patch("rag.svr.task_executor_refactor.chunk_service.settings", create_mock_settings()),
        patch.object(chunk_service, "apply_document_context", binder),
    ):
        mock_get_parser.return_value = MagicMock()
        docs = await ChunkService(ctx).build_chunks(b"binary")
    return docs, chunks, ctx


@pytest.fixture(autouse=True)
def model_stack(monkeypatch):
    """Keep the call hermetic: no provider call and no tenant lookup."""
    monkeypatch.setattr(service, "resolve_model_config", MagicMock(return_value={"model_name": "task-chat-model"}))
    monkeypatch.setattr(service, "get_tenant_default_model_by_type", MagicMock(return_value={"model_name": "workspace-default-model"}))
    monkeypatch.setattr(service, "LLMBundle", MagicMock(return_value=MagicMock(name="llm")))


@pytest.fixture
def store(monkeypatch):
    """A stubbed document-metadata store: nothing here reaches ES/Infinity."""
    store = MagicMock()
    store.get_document_metadata.return_value = {}
    store.update_document_metadata.return_value = True
    monkeypatch.setattr(service, "DocMetadataService", store)
    return store


async def test_build_chunks_tags_the_document_with_the_task_identity(monkeypatch):
    calls = []

    async def fake_tag(**kwargs):
        calls.append(kwargs)
        return {"standard_no": "Q/GDW 73289.2-2026"}

    monkeypatch.setattr(chunk_service, "tag_document_metadata", fake_tag)

    await _build()

    assert len(calls) == 1
    assert calls[0]["doc_id"] == "doc_incident"
    assert calls[0]["name"] == NAMED_DOC
    assert calls[0]["tenant_id"] == "tenant_1"
    assert calls[0]["llm_id"] == "llm_1"
    assert calls[0]["language"] == "Chinese"
    assert calls[0]["chunks"], "the parsed chunks are what the pass scans"
    assert calls[0]["write_interceptor"] is None, "production writes for real"


async def test_the_pass_scans_the_chunks_after_the_document_context_is_bound(monkeypatch):
    """The metadata FIELD and the ``[标准号: …]`` chunk prefix must not disagree."""
    seen = []

    def bind(chunks, doc_name, language="English"):
        for ck in chunks:
            ck["content_with_weight"] = "[标准号: Q/GDW 73289.2-2026] " + ck["content_with_weight"]
        return len(chunks)

    async def fake_tag(**kwargs):
        seen.append(kwargs["chunks"])
        return {}

    monkeypatch.setattr(chunk_service, "tag_document_metadata", fake_tag)

    await _build(bind=bind)

    assert seen and seen[0][0]["content_with_weight"].startswith("[标准号: Q/GDW 73289.2-2026]")


async def test_a_named_document_is_persisted_with_the_fields_its_name_declares(store):
    """The regression for the reported ``0 fields``: the default path writes them."""
    await _build()

    store.update_document_metadata.assert_called_once()
    doc_id, fields = store.update_document_metadata.call_args.args
    assert doc_id == "doc_incident"
    assert fields["standard_no"] == "Q/GDW 73289.2-2026"
    assert fields["voltage_level"] == "450/750V"
    assert fields["doc_type"] == "专用技术规范"


async def test_the_pass_does_not_need_enable_metadata_to_be_configured(monkeypatch):
    """RAGFlow's own per-chunk metadata generation is gated on
    ``parser_config.enable_metadata``; this pass exists precisely for the datasets
    that never configured anything, so it must not inherit that gate."""
    calls = []

    async def fake_tag(**kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(chunk_service, "tag_document_metadata", fake_tag)

    await _build(ctx_overrides={"parser_config": {"chunk_token_num": 128}})

    assert len(calls) == 1


async def test_a_compare_run_consumes_the_recorded_write_instead_of_writing(monkeypatch):
    interceptor = MagicMock()

    await _build(ctx_overrides={"write_interceptor": interceptor})

    interceptor.intercept.assert_called_once_with(service.METADATA_WRITE)


async def test_the_metadata_is_written_before_the_chunks_are_prepared(monkeypatch):
    """The write must land before the chunk identity and the vectors are frozen."""
    order = []

    async def fake_tag(**kwargs):
        order.append("metadata")
        return {}

    monkeypatch.setattr(chunk_service, "tag_document_metadata", fake_tag)
    original = ChunkService._prepare_docs_and_upload

    async def spy(self, cks):
        order.append("prepare_chunks")
        return await original(self, cks)

    monkeypatch.setattr(ChunkService, "_prepare_docs_and_upload", spy)

    await _build()

    assert order == ["metadata", "prepare_chunks"]
