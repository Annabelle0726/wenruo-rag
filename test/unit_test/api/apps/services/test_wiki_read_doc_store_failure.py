#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
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
"""The Wiki reads must not answer an unreachable doc store as an empty knowledge base.

``index_exist`` folds every failure into ``False`` (it retries, reconnects, and answers
"no such index"), so a datastore outage used to reach the client as ``code=0`` with
``total: 0`` — indistinguishable from a knowledge base whose Wiki has not been compiled
yet, and rendered by the console as its normal empty state. These tests pin the two
answers apart in both directions: an outage is a failure, a missing index is still an
empty success, and a refusal is still a refusal.

The service module is imported for real and its collaborators are patched in place,
rather than loading it against a set of ``sys.modules`` doubles the way its older tests
do: those doubles are installed while the module graph imports, so they leak into
whatever else imports ``common.*`` afterwards, and a test that cannot be run in any
order is not much of a regression net.
"""

import asyncio
import importlib

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

pytestmark = pytest.mark.p2

service = importlib.import_module("api.apps.services.dataset_api_service")

# Importing this graph asks asyncio for an event loop and never runs it. The loop is not
# ours and no test uses it, but leaving it unclosed makes pytest report an unraisable
# ResourceWarning as a session-level error at `pytest_unconfigure`, which fails the file
# however green its own tests are. Hold the reference — so nothing collects it early —
# and close it once the session is done with it.
try:
    _LOOP_LEFT_BY_THE_IMPORT = asyncio.get_event_loop_policy().get_event_loop()
except Exception:  # noqa: BLE001 - no loop means there is nothing to close
    _LOOP_LEFT_BY_THE_IMPORT = None


@pytest.fixture(scope="session", autouse=True)
def _close_loop_left_by_the_import():
    yield
    loop = _LOOP_LEFT_BY_THE_IMPORT
    if loop is not None and not loop.is_running() and not loop.is_closed():
        loop.close()


class _FakeConnection:
    """The narrowest stand-in for a doc-store connection."""

    def __init__(self, exists):
        self.exists = exists
        self.calls = []

    def index_exist(self, index_name, dataset_id=None):
        self.calls.append(index_name)
        return self.exists


@pytest.fixture
def doc_store(monkeypatch):
    """The doc store the Wiki reads ask, with the strict probe this change added.

    ``index_exist_strict`` answering ``True`` means "the index is there"; an exception
    means "the doc store could not be asked", which is the case under test.
    """
    conn = MagicMock()
    conn.index_exist_strict = MagicMock(return_value=True)
    conn.search = MagicMock(return_value={})
    conn.get_fields = MagicMock(return_value={})
    conn.get_total = MagicMock(return_value=0)

    kb = SimpleNamespace(tenant_id="tenant-1", id="kb-1")
    monkeypatch.setattr(service.settings, "docStoreConn", conn)
    monkeypatch.setattr(service.KnowledgebaseService, "accessible", MagicMock(return_value=True))
    monkeypatch.setattr(service.KnowledgebaseService, "get_by_id", MagicMock(return_value=(True, kb)))
    return conn


def test_base_index_exist_strict_delegates_to_index_exist():
    """A backend without a strict probe must stay on the old, swallowing behaviour.

    The default is deliberately not abstract: the strict question is an addition to the
    interface, and a backend that cannot answer it must keep working exactly as it did
    rather than answer it wrongly.
    """
    from common.doc_store.doc_store_base import DocStoreConnection

    conn = _FakeConnection(exists=True)
    assert DocStoreConnection.index_exist_strict(conn, "idx", "kb") is True
    assert conn.calls == ["idx"]

    conn = _FakeConnection(exists=False)
    assert DocStoreConnection.index_exist_strict(conn, "idx", "kb") is False
    assert conn.calls == ["idx"]


@pytest.mark.asyncio
async def test_topics_reports_unreachable_store_as_failure(monkeypatch, doc_store):
    doc_store.index_exist_strict = MagicMock(side_effect=RuntimeError("connection refused"))

    success, result = await service.list_wiki_topics("kb-1", "tenant-1")

    assert success is False
    assert str(result) == "The knowledge compilation store is unavailable"
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_topics_keeps_a_missing_index_as_an_empty_success(monkeypatch, doc_store):
    doc_store.index_exist_strict = MagicMock(return_value=False)

    success, result = await service.list_wiki_topics("kb-1", "tenant-1")

    assert success is True
    assert result == {"total": 0, "items": []}


@pytest.mark.asyncio
async def test_topics_reports_a_failing_aggregation_as_failure(monkeypatch, doc_store):
    """The store can also fail after the index was found, mid-request."""
    doc_store.search = MagicMock(side_effect=RuntimeError("aggregation blew up"))

    success, result = await service.list_wiki_topics("kb-1", "tenant-1")

    assert success is False
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_pages_reports_unreachable_store_as_failure(monkeypatch, doc_store):
    doc_store.index_exist_strict = MagicMock(side_effect=RuntimeError("connection refused"))

    success, result = await service.list_wiki_pages("kb-1", "tenant-1")

    assert success is False
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_pages_reports_a_failing_search_as_failure(monkeypatch, doc_store):
    doc_store.search = MagicMock(side_effect=RuntimeError("search blew up"))

    success, result = await service.list_wiki_pages("kb-1", "tenant-1")

    assert success is False
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_page_reports_unreachable_store_as_failure(monkeypatch, doc_store):
    doc_store.index_exist_strict = MagicMock(side_effect=RuntimeError("connection refused"))

    success, result = await service.get_wiki_page("kb-1", "tenant-1", "wiki", "overview")

    assert success is False
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_page_reports_a_failing_search_as_failure(monkeypatch, doc_store):
    doc_store.search = MagicMock(side_effect=RuntimeError("search blew up"))

    success, result = await service.get_wiki_page("kb-1", "tenant-1", "wiki", "overview")

    assert success is False
    assert getattr(result, "code", None) == 500


@pytest.mark.asyncio
async def test_page_keeps_a_missing_row_as_an_empty_success(monkeypatch, doc_store):
    """A page that is genuinely not there is not a failure: the console shows nothing."""
    success, result = await service.get_wiki_page("kb-1", "tenant-1", "wiki", "overview")

    assert success is True
    assert result is None


@pytest.mark.asyncio
async def test_permission_denial_is_not_reported_as_a_store_failure(monkeypatch, doc_store):
    monkeypatch.setattr(service.KnowledgebaseService, "accessible", MagicMock(return_value=False))
    doc_store.index_exist_strict = MagicMock(side_effect=RuntimeError("connection refused"))

    for call in (
        service.list_wiki_topics("kb-1", "tenant-1"),
        service.list_wiki_pages("kb-1", "tenant-1"),
        service.get_wiki_page("kb-1", "tenant-1", "wiki", "overview"),
    ):
        success, result = await call
        assert success is False
        assert getattr(result, "code", None) == 108
