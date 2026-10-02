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

"""A parse task and a retrieval query on one provider instance are ONE incident.

The reason Provider Health can be shared across entry points at all is that
identity is not derived from the entry point: it is derived from the
``tenant_model`` id a workspace's dataset stores, through one resolver, and handed
to one observer. So the parse worker running out of embedding quota and a retrieval
query succeeding afterwards must not open two histories for one provider.

These tests drive BOTH real boundaries - ``TaskHandler._bind_embedding_model`` and
the observer the serving layer installs - against one real store, and assert they
meet on a single row. They live in this package because it is the one that can
import the parse handler (its conftest stubs the ``umap`` import warning this
suite would otherwise turn into a collection error).

The identity is production's: workspace ``a9e28731...``, provider ``ee6cb91b...``
(``Gemini``), instance ``f7825d47...``, model ``f79e37e5...``.
"""

import contextlib
from unittest.mock import patch

import pytest
from peewee import SqliteDatabase

from api.db.db_models import ProviderHealthEvent
from api.db.joint_services import provider_health_observation
from api.db.joint_services.tenant_model_service import ModelIdentity
from api.db.services import provider_health_service as health
from common import model_errors
from rag.llm.embedding_model import EmbeddingQuotaExhausted
from rag.svr.task_executor_refactor import task_handler as task_handler_module
from rag.svr.task_executor_refactor.task_handler import TaskHandler

GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"
QUERY_SENTINEL = "客户私有电缆规格查询"

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "Gemini"
MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"

IDENTITY = ModelIdentity(
    tenant_id=WORKSPACE,
    provider_id=PROVIDER_ID,
    instance_id=INSTANCE_ID,
    provider_name=PROVIDER_NAME,
    capability="embedding",
)

MODEL_CONFIG = {
    "llm_factory": "Gemini",
    "api_key": "__MUST_NEVER_REACH_HEALTH__",
    "llm_name": "gemini-embedding-001",
    "api_base": "",
    "model_type": "embedding",
}


class FakeEmbeddingBundle:
    """A real object shaped like an embedding bundle."""

    def __init__(self, failure=None, vector_size=3):
        self.model_config = MODEL_CONFIG
        self.max_length = 2048
        self.llm_name = "gemini-embedding-001"
        self.calls = 0
        self._vector_size = vector_size
        self._failure = failure

    def encode(self, texts):
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [[1.0] * self._vector_size for _ in texts], len(texts)

    def encode_queries(self, text):
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [1.0] * self._vector_size, 7


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "parity-health.sqlite", timeout=20)
    with db.bind_ctx([ProviderHealthEvent]):
        db.create_tables([ProviderHealthEvent])
        monkeypatch.setattr(health, "DB", db)
        yield db
        if not db.is_closed():
            db.close()


def _row():
    rows = list(ProviderHealthEvent.select())
    assert len(rows) == 1, "one provider instance is one incident, not two histories"
    return rows[0]


def _install_retrieval_observation(bundle):
    """Install exactly what every serving retrieval call site installs."""
    with patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: IDENTITY):
        provider_health_observation.observe_embedding_calls(bundle, WORKSPACE, MODEL_ID)
    return bundle


@contextlib.contextmanager
def parse_boundary(bundle):
    """Drive the real parse bind boundary with a fake provider and the live identity."""
    with (
        patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: IDENTITY),
        patch.object(task_handler_module, "get_model_config_by_id", return_value=MODEL_CONFIG),
        patch.object(task_handler_module, "LLMBundle", return_value=bundle),
    ):
        yield


@pytest.mark.asyncio
async def test_a_parse_failure_and_a_retrieval_success_are_one_incident(health_db, task_context):
    """The live scenario: the parse worker exhausts the instance, a query then works."""
    task_context.raw_task["tenant_embd_id"] = MODEL_ID
    task_context.raw_task["embd_id"] = MODEL_ID
    parse_bundle = FakeEmbeddingBundle(failure=EmbeddingQuotaExhausted("GeminiEmbed", GEMINI_BODY))

    with parse_boundary(parse_bundle):
        with pytest.raises(EmbeddingQuotaExhausted):
            await TaskHandler(task_context)._bind_embedding_model()

    incident = _row()
    assert incident.state == health.ACTIVE
    assert (
        incident.tenant_id,
        incident.provider_id,
        incident.instance_id,
        incident.capability,
        incident.error_class,
    ) == (WORKSPACE, PROVIDER_ID, INSTANCE_ID, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED)

    # The very same instance now answers a retrieval query.
    _install_retrieval_observation(FakeEmbeddingBundle()).encode_queries(QUERY_SENTINEL)

    assert _row().id == incident.id
    assert _row().state == health.RESOLVED


@pytest.mark.asyncio
async def test_a_retrieval_failure_and_a_parse_success_are_one_incident(health_db, task_context):
    """The same parity in the other direction."""
    with pytest.raises(EmbeddingQuotaExhausted):
        _install_retrieval_observation(FakeEmbeddingBundle(failure=EmbeddingQuotaExhausted("GeminiEmbed", GEMINI_BODY))).encode_queries(QUERY_SENTINEL)
    assert _row().state == health.ACTIVE

    task_context.raw_task["tenant_embd_id"] = MODEL_ID
    task_context.raw_task["embd_id"] = MODEL_ID
    with parse_boundary(FakeEmbeddingBundle()):
        result = await TaskHandler(task_context)._bind_embedding_model()

    assert result is not None, "the parse itself is unaffected"
    assert _row().state == health.RESOLVED


@pytest.mark.asyncio
async def test_repeated_failures_from_both_paths_stay_one_incident(health_db, task_context):
    """Two entry points, two occurrences, one row - the count is the evidence."""
    task_context.raw_task["tenant_embd_id"] = MODEL_ID
    task_context.raw_task["embd_id"] = MODEL_ID

    for _ in range(2):
        with pytest.raises(EmbeddingQuotaExhausted):
            _install_retrieval_observation(FakeEmbeddingBundle(failure=EmbeddingQuotaExhausted("GeminiEmbed", GEMINI_BODY))).encode_queries(QUERY_SENTINEL)

    with parse_boundary(FakeEmbeddingBundle(failure=EmbeddingQuotaExhausted("GeminiEmbed", GEMINI_BODY))):
        with pytest.raises(EmbeddingQuotaExhausted):
            await TaskHandler(task_context)._bind_embedding_model()

    incident = _row()
    assert incident.occurrence_count == 3, "one problem seen three times, from two entry points"
    assert incident.state == health.ACTIVE
    assert incident.tenant_id == WORKSPACE
