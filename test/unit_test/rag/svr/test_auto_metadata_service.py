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
"""The auto metadata service: the model it spends, the write it makes, what it reports.

The reported failure this file answers was a file list stuck at "0 fields" with a
healthy-looking log, so the assertions are about exactly the things that made it
invisible: which chat model the optional call may use (the task's, else the
workspace default), that a rejected write is REPORTED rather than dropped, and that
a document which yields nothing does not touch the store at all.
"""

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rag.nlp import auto_metadata as am
from rag.svr import auto_metadata_service as service

pytestmark = pytest.mark.p2

TENANT = "tenant_1"
DOC_ID = "doc_1"
#: A name the zero-token fast path identifies completely (standard number, voltage
#: rating, document type), so no model call is needed to tag it.
NAMED_DOC = "Q_GDW 73289.2-2026 450_750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范_2.pdf"
#: A name that identifies nothing: `voltage_level`/`standard_no` are only in the body.
ANONYMOUS_DOC = "scan_0001.pdf"


@pytest.fixture
def store(monkeypatch):
    """A stubbed document-metadata store: nothing here reaches ES/Infinity."""
    store = MagicMock()
    store.get_document_metadata.return_value = {}
    store.update_document_metadata.return_value = True
    monkeypatch.setattr(service, "DocMetadataService", store)
    return store


@pytest.fixture(autouse=True)
def model_stack(monkeypatch):
    """The chat-model plumbing, stubbed: no provider call and no tenant lookup.

    Autouse, because every test in this file must be hermetic: resolving the model
    is the first thing the service does, so a test that forgot this stub would
    query the tenant table (and, without one, would be asserting on the caught
    failure path instead of the one it names).
    """
    resolve = MagicMock(return_value={"model_name": "task-chat-model"})
    default = MagicMock(return_value={"model_name": "workspace-default-model"})
    bundle = MagicMock(return_value=MagicMock(name="llm"))
    monkeypatch.setattr(service, "resolve_model_config", resolve)
    monkeypatch.setattr(service, "get_tenant_default_model_by_type", default)
    monkeypatch.setattr(service, "LLMBundle", bundle)
    return SimpleNamespace(resolve=resolve, default=default, bundle=bundle)


# ---------------------------------------------------------------------------
# Which chat model the one optional call may spend
# ---------------------------------------------------------------------------


def test_the_task_chat_model_is_preferred_and_the_default_is_not_consulted(model_stack):
    llm = service.resolve_chat_model(TENANT, "llm_9", "Chinese")

    assert llm is model_stack.bundle.return_value
    assert model_stack.resolve.call_args.args[0] == TENANT
    assert model_stack.resolve.call_args.args[2] == "llm_9"
    model_stack.default.assert_not_called()


def test_the_workspace_default_is_used_when_the_task_carries_no_chat_model(model_stack):
    """A plain naive parse task carries no chat model; the workspace default is the
    model the operator expects a chat-shaped extra to use."""
    llm = service.resolve_chat_model(TENANT, "", "Chinese")

    assert llm is model_stack.bundle.return_value
    model_stack.default.assert_called_once()
    model_stack.resolve.assert_not_called()


def test_a_task_model_that_no_longer_resolves_falls_back_to_the_default(model_stack, caplog):
    model_stack.resolve.side_effect = LookupError("model has been removed")

    with caplog.at_level(logging.WARNING):
        llm = service.resolve_chat_model(TENANT, "llm_gone", "Chinese")

    assert llm is model_stack.bundle.return_value
    model_stack.default.assert_called_once()
    assert "not usable in workspace" in caplog.text


def test_a_workspace_without_any_chat_model_says_so_and_returns_none(model_stack, caplog):
    model_stack.default.side_effect = Exception("No default chat model is set.")

    with caplog.at_level(logging.WARNING):
        llm = service.resolve_chat_model(TENANT, None, "Chinese")

    assert llm is None
    assert "the regex pass runs alone" in caplog.text


async def test_the_default_model_reaches_the_extractor(model_stack, store, monkeypatch):
    """The resolution above has to actually arrive at the one call that spends it."""
    seen = {}

    async def fake_auto_tag(name, text, *, llm=None, **kwargs):
        seen["llm"] = llm
        seen["name"] = name
        return am.AutoTagResult(fields={}, source="none")

    monkeypatch.setattr(service, "auto_tag", fake_auto_tag)

    await service.tag_document_metadata(doc_id=DOC_ID, name=ANONYMOUS_DOC, chunks=[{"content_with_weight": "正文"}], tenant_id=TENANT, llm_id="")

    assert seen["llm"] is model_stack.bundle.return_value
    assert seen["name"] == ANONYMOUS_DOC


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------


async def test_a_document_whose_name_identifies_it_is_persisted_without_a_model_call(store):
    written = await service.tag_document_metadata(doc_id=DOC_ID, name=NAMED_DOC, chunks=[{"content_with_weight": "正文"}], tenant_id=TENANT)

    assert written == {
        "standard_no": "Q/GDW 73289.2-2026",
        "voltage_level": "450/750V",
        "doc_type": "专用技术规范",
        "year": "2026",
    }
    doc_id, fields = store.update_document_metadata.call_args.args
    assert doc_id == DOC_ID
    assert fields["standard_no"] == "Q/GDW 73289.2-2026"
    assert fields["voltage_level"] == "450/750V"


async def test_existing_metadata_survives_the_write(store):
    """The operator's own fields, and the parser's outline, are written through the
    same row by other features: an automatic pass must not delete them."""
    store.get_document_metadata.return_value = {"standard_no": "GB/T 1-2020", "outline": [{"title": "第1章", "depth": 1}], "运维备注": "已校核"}

    await service.tag_document_metadata(doc_id=DOC_ID, name=NAMED_DOC, chunks=[{"content_with_weight": "正文"}], tenant_id=TENANT)

    fields = store.update_document_metadata.call_args.args[1]
    # A field that is already stored wins: a later page-range task re-reading a
    # standard the document only CITES must not relabel the document.
    assert fields["standard_no"] == "GB/T 1-2020"
    assert fields["outline"] == [{"title": "第1章", "depth": 1}]
    assert fields["运维备注"] == "已校核"
    assert fields["voltage_level"] == "450/750V", "a missing field is still filled"


async def test_a_document_that_yields_nothing_does_not_touch_the_store(store):
    written = await service.tag_document_metadata(doc_id=DOC_ID, name=ANONYMOUS_DOC, chunks=[{"content_with_weight": "本文没有可提取的字段。"}], tenant_id=TENANT)

    assert written == {}
    store.update_document_metadata.assert_not_called()
    store.get_document_metadata.assert_not_called()


async def test_a_rejected_write_is_reported_instead_of_being_dropped(store, caplog):
    """The store returns False rather than raising; unchecked, this is the silent
    "0 fields" the feature exists to remove."""
    store.update_document_metadata.return_value = False
    results = []

    with caplog.at_level(logging.WARNING):
        written = await service.tag_document_metadata(
            doc_id=DOC_ID,
            name=NAMED_DOC,
            chunks=[{"content_with_weight": "正文"}],
            tenant_id=TENANT,
            on_write_result=results.append,
        )

    assert written["standard_no"] == "Q/GDW 73289.2-2026", "the extraction is still reported"
    assert results == [False]
    assert "could not persist" in caplog.text
    assert DOC_ID in caplog.text, "the warning must name the document to investigate"


async def test_the_write_result_is_reported_to_the_caller_when_it_succeeds(store):
    results = []

    await service.tag_document_metadata(doc_id=DOC_ID, name=NAMED_DOC, chunks=[{"content_with_weight": "正文"}], tenant_id=TENANT, on_write_result=results.append)

    assert results == [True]


async def test_a_dry_run_consumes_the_recorded_write_instead_of_writing(store):
    """The refactored executor's compare mode replays every write; this one too."""
    store.get_document_metadata.return_value = {"标准号": "Q/GDW 1-2020"}
    interceptor = MagicMock()

    written = await service.tag_document_metadata(
        doc_id=DOC_ID,
        name=NAMED_DOC,
        chunks=[{"content_with_weight": "正文"}],
        tenant_id=TENANT,
        write_interceptor=interceptor,
    )

    assert written
    interceptor.intercept.assert_called_once_with(service.METADATA_WRITE)
    store.update_document_metadata.assert_not_called()
    store.get_document_metadata.assert_not_called()


async def test_a_failing_extraction_never_fails_the_ingest(store, monkeypatch, caplog):
    async def exploding_auto_tag(*args, **kwargs):
        raise RuntimeError("the extractor is on fire")

    monkeypatch.setattr(service, "auto_tag", exploding_auto_tag)

    with caplog.at_level(logging.ERROR):
        written = await service.tag_document_metadata(doc_id=DOC_ID, name=NAMED_DOC, chunks=[{"content_with_weight": "正文"}], tenant_id=TENANT)

    assert written == {}
    assert "continuing without it" in caplog.text
    store.update_document_metadata.assert_not_called()


# ---------------------------------------------------------------------------
# Both chunking paths call this, and neither carries its own copy
# ---------------------------------------------------------------------------


async def test_the_original_executor_delegates_to_this_service(monkeypatch):
    """``rag.svr.task_executor._auto_tag_document`` is a wrapper, not a second
    implementation: the extract/store/report logic exists once.

    Loaded from the source AST because importing the worker module pulls in the whole
    ingest stack; the decorators (``@timeout``/``@timed_with_recording``) are dropped
    so the body runs directly.
    """
    source = (Path(__file__).resolve().parents[4] / "rag" / "svr" / "task_executor.py").read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_auto_tag_document")
    node.decorator_list = []

    recorded = []
    namespace = {"get_recording_context": lambda: SimpleNamespace(save_func_return_value=lambda name, value: recorded.append((name, value)))}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "task_executor.py", "exec"), namespace)
    auto_tag_document = namespace["_auto_tag_document"]

    calls = []

    async def fake_tag(**kwargs):
        calls.append(kwargs)
        kwargs["on_write_result"](True)
        return {"voltage_level": "10kV"}

    monkeypatch.setattr(service, "tag_document_metadata", fake_tag)

    task = {"doc_id": DOC_ID, "name": NAMED_DOC, "tenant_id": TENANT, "llm_id": "llm_9"}
    written = await auto_tag_document(task, [{"content_with_weight": "正文"}], "Chinese")

    assert written == {"voltage_level": "10kV"}
    assert calls[0]["doc_id"] == DOC_ID
    assert calls[0]["name"] == NAMED_DOC
    assert calls[0]["tenant_id"] == TENANT
    assert calls[0]["llm_id"] == "llm_9"
    assert calls[0]["language"] == "Chinese"
    assert recorded == [("DocMetadataService.update_document_metadata", True)]
