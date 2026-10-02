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

"""What the retrieval boundary records, and that it records it as ONE provider.

Three things are asserted here that the contract tests cannot show on their own:

* incidents, against a real store - a repeated refusal on one instance counts on one
  row, and tenant, provider, instance and capability never merge;
* PARITY with the parse milestone - the parse worker failing on the workspace's
  embedding instance and a retrieval query succeeding on it are the same provider
  health identity, so one closes the other rather than opening a second history;
* that the serving entry points really install the observation, driven through
  ``dataset_api_service.search`` and guarded by an explicit coverage manifest.

The identity is production's: workspace ``a9e28731...``, provider ``ee6cb91b...``
(``Gemini``), instance ``f7825d47...``, model ``f79e37e5...``.
"""

import ast
import asyncio
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from peewee import SqliteDatabase

from api.apps.services import dataset_api_service
from api.db.db_models import ProviderHealthEvent
from api.db.joint_services import provider_health_observation
from api.db.joint_services.tenant_model_service import ModelIdentity
from api.db.services import provider_health_service as health
from api.db.services.knowledgebase_service import KnowledgebaseService
from common import model_errors, settings as common_settings
from rag.llm.embedding_model import EmbeddingQuotaExhausted
from rag.nlp.search import Dealer

GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"
API_KEY_SENTINEL = "__MUST_NEVER_REACH_HEALTH__"
QUERY_SENTINEL = "客户私有电缆规格查询"

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
OTHER_WORKSPACE = "89a9df92b5bb11f182935728a82b1fe8"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "Gemini"
MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"
OTHER_INSTANCE_ID = "11111111111111111111111111111111"
OTHER_PROVIDER_ID = "22222222222222222222222222222222"

IDENTITY = ModelIdentity(
    tenant_id=WORKSPACE,
    provider_id=PROVIDER_ID,
    instance_id=INSTANCE_ID,
    provider_name=PROVIDER_NAME,
    capability="embedding",
)

MODEL_CONFIG = {
    "llm_factory": "Gemini",
    "api_key": API_KEY_SENTINEL,
    "llm_name": "gemini-embedding-001",
    "api_base": "",
    "model_type": "embedding",
}

#: Which reference each serving site hands to the observer. The manifest is the
#: coverage claim, in code: a removed observation fails this test instead of
#: silently becoming a call path that never reports.
COVERAGE_MANIFEST = {
    "api/apps/restful_apis/chunk_api.py": {"retrieval_test", "get_document_structure_graph"},
    "api/apps/services/dataset_api_service.py": {
        "search",
        "check_embedding",
        "search_datasets",
        "get_dataset_structure",
        "search_dataset_layers",
    },
    "api/apps/restful_apis/dify_retrieval_api.py": {"retrieval"},
    "api/apps/restful_apis/bot_api.py": {"_retrieval"},
    "agent/tools/retrieval.py": {"_retrieve_kb"},
    "rag/svr/task_executor_refactor/task_handler.py": {"_bind_embedding_model"},
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

    def encode_queries(self, text):
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [1.0] * self._vector_size, 7

    def encode(self, texts):
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [[1.0] * self._vector_size for _ in texts], len(texts)


def quota_failure(detail=None):
    return EmbeddingQuotaExhausted("GeminiEmbed", detail or GEMINI_BODY)


def installed(bundle, *, identity=IDENTITY, ref=MODEL_ID, tenant_id=WORKSPACE):
    """Install observation exactly as every serving call site does."""
    with patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: identity):
        provider_health_observation.observe_embedding_calls(bundle, tenant_id, ref)
    return bundle


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "retrieval-health.sqlite", timeout=20)
    with db.bind_ctx([ProviderHealthEvent]):
        db.create_tables([ProviderHealthEvent])
        monkeypatch.setattr(health, "DB", db)
        yield db
        if not db.is_closed():
            db.close()


def _rows():
    return list(ProviderHealthEvent.select())


def _fingerprint(row):
    return (row.tenant_id, row.provider_id, row.instance_id, row.capability, row.error_class)


# ---------------------------------------------------------------------------
# 1. One problem is one incident, and its occurrences add up
# ---------------------------------------------------------------------------


def test_a_repeated_refusal_on_one_instance_counts_on_one_incident(health_db):
    # Three separate retrieval requests, each with its own bundle - which is how a
    # workspace's provider being out of quota actually presents.
    for _ in range(3):
        bundle = installed(FakeEmbeddingBundle(failure=quota_failure()))
        with pytest.raises(EmbeddingQuotaExhausted):
            bundle.encode_queries(QUERY_SENTINEL)

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].occurrence_count == 3
    assert rows[0].state == health.ACTIVE
    assert _fingerprint(rows[0]) == (
        WORKSPACE,
        PROVIDER_ID,
        INSTANCE_ID,
        "embedding",
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
    )
    # The user's own question is not part of the fact.
    assert QUERY_SENTINEL not in rows[0].user_safe_message


def test_tenant_provider_instance_and_capability_never_merge(health_db):
    other_instance = ModelIdentity(WORKSPACE, PROVIDER_ID, OTHER_INSTANCE_ID, PROVIDER_NAME, "embedding")
    other_provider = ModelIdentity(WORKSPACE, OTHER_PROVIDER_ID, INSTANCE_ID, PROVIDER_NAME, "embedding")
    other_tenant = ModelIdentity(OTHER_WORKSPACE, PROVIDER_ID, INSTANCE_ID, PROVIDER_NAME, "embedding")

    for identity, tenant_id in ((IDENTITY, WORKSPACE), (other_instance, WORKSPACE), (other_provider, WORKSPACE), (other_tenant, OTHER_WORKSPACE)):
        bundle = installed(FakeEmbeddingBundle(failure=quota_failure()), identity=identity, tenant_id=tenant_id)
        with pytest.raises(EmbeddingQuotaExhausted):
            bundle.encode_queries(QUERY_SENTINEL)

    # A different capability is a different problem on the same endpoint.
    health.emit_failure(
        WORKSPACE,
        PROVIDER_NAME,
        "chat",
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
        provider_id=PROVIDER_ID,
        instance_id=INSTANCE_ID,
    )

    assert len(_rows()) == 5, "each proven difference is its own incident"


def test_a_hostile_provider_body_never_reaches_the_store(health_db):
    hostile = (
        f"{GEMINI_BODY} key=AIzaSyFAKE-KEY-abcdefghijklmnop "
        f"prompt='{QUERY_SENTINEL}' chunk='表1 电缆结构技术参数' "
        '{"error":{"message":"quota","details":[{"@type":"type.googleapis.com/google.rpc.DebugInfo"}]}}'
    )
    bundle = installed(FakeEmbeddingBundle(failure=quota_failure(hostile)))
    with pytest.raises(EmbeddingQuotaExhausted):
        bundle.encode_queries(QUERY_SENTINEL)

    stored = _rows()[0]
    blob = " ".join(str(getattr(stored, field)) for field in stored.__data__)
    for secret in ("AIzaSy", "key=", "prompt", "chunk", "DebugInfo", "@type", "电缆", QUERY_SENTINEL):
        assert secret not in blob, secret
    assert stored.user_safe_message == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]


# ---------------------------------------------------------------------------
# 2. A success closes only its own incident
# ---------------------------------------------------------------------------


def test_a_successful_query_closes_only_its_own_incident(health_db):
    mine = health.emit_failure(
        WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID
    )
    other_instance = health.emit_failure(
        WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED, provider_id=PROVIDER_ID, instance_id=OTHER_INSTANCE_ID
    )
    other_provider = health.emit_failure(
        WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED, provider_id=OTHER_PROVIDER_ID, instance_id=INSTANCE_ID
    )
    other_workspace = health.emit_failure(
        OTHER_WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID
    )
    other_capability = health.emit_failure(
        WORKSPACE, PROVIDER_NAME, "chat", model_errors.EMBEDDING_QUOTA_EXHAUSTED, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID
    )

    bundle = installed(FakeEmbeddingBundle())
    bundle.encode_queries(QUERY_SENTINEL)

    states = {row.id: row.state for row in _rows()}
    assert states[mine] == health.RESOLVED
    for untouched, label in (
        (other_instance, "another instance of the same provider"),
        (other_provider, "another provider"),
        (other_workspace, "another workspace"),
        (other_capability, "another capability on the same provider and instance"),
    ):
        assert states[untouched] == health.ACTIVE, label


# ---------------------------------------------------------------------------
# 3. A serving entry point really does install the observation
# ---------------------------------------------------------------------------


class _DegradingRetriever(Dealer):
    """The real funnel plus the real degradation: a dense-leg refusal still answers.

    ``Dealer.retrieval`` degrades a recoverable embedding failure to lexical search,
    so the entry point must still return a result while the failure is reported.
    """

    def __init__(self):
        super().__init__(MagicMock())
        self.degraded = False

    async def retrieval(self, question, embd_mdl, *_args, **_kwargs):
        try:
            await self._query_embedding(embd_mdl, question)
        except EmbeddingQuotaExhausted:
            self.degraded = True
        return {"total": 0, "chunks": [], "doc_aggs": []}

    def retrieval_by_children(self, chunks, _tenant_ids):
        return chunks


@pytest.mark.asyncio
async def test_dataset_search_observes_its_query_embedding(health_db):
    kb = SimpleNamespace(
        id="kb-1",
        tenant_id=WORKSPACE,
        embd_id=MODEL_ID,
        tenant_embd_id=MODEL_ID,
        language="Chinese",
        parser_config={},
    )
    bundle = FakeEmbeddingBundle(failure=quota_failure())
    retriever = _DegradingRetriever()

    from api.db.services import llm_service as llm_service_module

    with (
        patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: IDENTITY),
        # The site imports the helper by name, so the seam that proves the wiring
        # is the site's own binding - and it must still call the real one.
        patch.object(
            dataset_api_service,
            "observe_embedding_calls",
            wraps=provider_health_observation.observe_embedding_calls,
        ) as observe_call,
        patch.object(KnowledgebaseService, "accessible", return_value=True),
        patch.object(KnowledgebaseService, "get_by_id", return_value=(True, kb)),
        patch.object(KnowledgebaseService, "query", return_value=True),
        patch.object(dataset_api_service.UserTenantService, "query", return_value=[SimpleNamespace(tenant_id=WORKSPACE)]),
        patch.object(llm_service_module, "LLMBundle", return_value=bundle),
        patch.object(dataset_api_service, "resolve_model_config", return_value=MODEL_CONFIG),
        patch.object(common_settings, "retriever", retriever),
        patch("rag.app.tag.label_question", return_value={"kb-1": 0.5}),
    ):
        ok, result = await dataset_api_service.search("kb-1", WORKSPACE, {"question": QUERY_SENTINEL})

    # The entry point behaves exactly as before: it answers, degraded to lexical.
    assert ok is True
    assert result["total"] == 0
    assert retriever.degraded is True

    # And the reference it handed over is the tenant_model id its own config used,
    # never the provider name and never the resolved config (which holds the key).
    observe_call.assert_called_once()
    assert observe_call.call_args.args == (bundle, WORKSPACE, MODEL_ID)

    # The refusal it met was reported against the identity that id proves.
    rows = _rows()
    assert len(rows) == 1
    assert _fingerprint(rows[0]) == (
        WORKSPACE,
        PROVIDER_ID,
        INSTANCE_ID,
        "embedding",
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
    )


# ---------------------------------------------------------------------------
# 4. Coverage manifest: the observation cannot be removed silently
# ---------------------------------------------------------------------------


def _observed_functions(path: str) -> set[str]:
    """Names of the innermost functions that install Provider Health observation."""
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    found = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "observe_embedding_calls"):
            continue
        cursor, innermost = node, None
        while cursor is not None and innermost is None:
            if isinstance(cursor, (ast.FunctionDef, ast.AsyncFunctionDef)):
                innermost = cursor.name
            cursor = getattr(cursor, "parent", None)
        found.add(innermost)
    return found


@pytest.mark.parametrize("path", sorted(COVERAGE_MANIFEST))
def test_every_audited_call_path_still_installs_the_observation(path):
    assert _observed_functions(path) == COVERAGE_MANIFEST[path], (
        "the Provider Health coverage manifest changed: a retrieval path lost its "
        "observation, or a new one was added without recording it here"
    )
