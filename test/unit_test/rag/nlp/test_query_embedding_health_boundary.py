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

"""Provider Health at the retrieval boundary: it rides along, and changes nothing.

Everything here runs through the REAL shared query-embedding funnel,
``Dealer._query_embedding`` (``rag/nlp/search.py``), which is the one function every
serving entry point's query embedding passes through - its own thread, its own
admission check and its own deadline included. The bundle is a fake and the identity
is the live one, so what is asserted is the contract and not the wiring: a retrieval
that failed still fails with the same exception, a retrieval that worked still
returns the same vectors, and the fact recorded names the provider instance the
reference proves.

The identity values are production's: workspace ``a9e28731...``, provider
``ee6cb91b...`` (``Gemini``), instance ``f7825d47...``, model ``f79e37e5...``
(``gemini-embedding-001``) - the provider that answered the live
``429 RESOURCE_EXHAUSTED`` / "Embedding quota exhausted" refusal.
"""

from unittest.mock import MagicMock, patch

import pytest

from api.db.joint_services import provider_health_observation
from api.db.joint_services.tenant_model_service import ModelIdentity
from api.db.services import provider_health_service as health
from common import model_errors
from rag.llm.embedding_model import EmbeddingQuotaExhausted
from rag.nlp.search import Dealer

GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"

#: Sentinels: if any of these reaches a health writer, the side-channel is leaking a
#: credential, the provider's raw body, or the user's own question.
API_KEY_SENTINEL = "__MUST_NEVER_REACH_HEALTH__"
QUERY_SENTINEL = "客户私有电缆规格查询"
CHUNK_SENTINEL = "表1 电缆结构技术参数"

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "Gemini"
MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"
COMPOSITE_NAME = "gemini-embedding-001@G@Gemini"

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


class FakeEmbeddingBundle:
    """A real object shaped like an embedding bundle, with a real call count."""

    def __init__(self, failure=None, vector_size=3):
        self.model_config = MODEL_CONFIG
        self.max_length = 2048
        self.llm_name = "gemini-embedding-001"
        self.calls = 0
        self._vector_size = vector_size
        self._failure = failure

    def encode_queries(self, text):
        """Embed one query into a vector."""
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [1.0] * self._vector_size, 7

    def encode(self, texts):
        """Batch-embed documents into vectors."""
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return [[1.0] * self._vector_size for _ in texts], len(texts)


class Recorder:
    """Captures exactly what a health writer was handed."""

    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises


def quota_failure():
    """What the provider connectors raise for the live Gemini refusal."""
    return EmbeddingQuotaExhausted(
        "GeminiEmbed",
        f"{GEMINI_BODY} prompt='{QUERY_SENTINEL}' chunk='{CHUNK_SENTINEL}'",
    )


def fingerprint(exc):
    """Everything a caller can observe about a provider failure."""
    return (
        type(exc),
        str(exc),
        getattr(exc, "error_type", None),
        getattr(exc, "retryable", None),
    )


def observed(bundle, *, identity=IDENTITY, ref=MODEL_ID, identity_error=None):
    """Install observation on *bundle* exactly as the serving call sites do."""

    def _resolve(*_args, **_kwargs):
        if identity_error is not None:
            raise identity_error
        return identity

    with patch.object(provider_health_observation, "resolve_model_identity_by_id", _resolve):
        provider_health_observation.observe_embedding_calls(bundle, WORKSPACE, ref)
    return bundle


async def query(bundle, text=QUERY_SENTINEL):
    """Run one query embedding through the real retrieval funnel."""
    return await Dealer(MagicMock())._query_embedding(bundle, text)


# ---------------------------------------------------------------------------
# 1. A typed refusal: recorded, and propagated exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_query_embedding_refusal_is_recorded_once_and_propagates_unchanged():
    emitted = Recorder()
    failure = quota_failure()
    control_failure = quota_failure()

    # Control: the identical call with Provider Health switched off entirely.
    with pytest.raises(EmbeddingQuotaExhausted) as control:
        await query(FakeEmbeddingBundle(failure=control_failure))

    bundle = FakeEmbeddingBundle(failure=failure)
    with patch.object(health, "emit_failure", emitted), patch.object(health, "resolve_on_success", Recorder()):
        observed(bundle)
        with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
            await query(bundle)

    # The very same exception object, with the caller-visible surface untouched.
    assert excinfo.value is failure
    assert fingerprint(excinfo.value) == fingerprint(control.value)
    assert fingerprint(excinfo.value) == (
        EmbeddingQuotaExhausted,
        str(failure),
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
        False,
    )

    # One problem, one fact, keyed by the identity a model id proves.
    assert len(emitted.calls) == 1
    args, kwargs = emitted.calls[0]
    assert args == (WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED)
    assert kwargs == {"provider_id": PROVIDER_ID, "instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_the_funnel_itself_does_not_rewrite_the_failure():
    """The exception survives the retrieval deadline machinery, not just our wrapper."""
    failure = quota_failure()

    with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
        await query(FakeEmbeddingBundle(failure=failure))

    assert excinfo.value is failure
    assert fingerprint(excinfo.value)[2] == model_errors.EMBEDDING_QUOTA_EXHAUSTED


@pytest.mark.asyncio
async def test_a_burst_of_calls_from_one_request_is_one_fact():
    emitted = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", emitted):
        observed(bundle)
        for _ in range(5):
            with pytest.raises(EmbeddingQuotaExhausted):
                await query(bundle)

    assert len(emitted.calls) == 1


@pytest.mark.asyncio
async def test_an_unrecognised_failure_is_not_a_health_fact():
    emitted = Recorder()
    bundle = FakeEmbeddingBundle(failure=ValueError("local bug in the query pipeline"))

    with patch.object(health, "emit_failure", emitted):
        observed(bundle)
        with pytest.raises(ValueError, match="local bug"):
            await query(bundle)

    assert emitted.calls == []


# ---------------------------------------------------------------------------
# 2. A healthy query: unchanged, and it resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_healthy_query_is_unchanged_and_resolves_the_capability():
    resolved = Recorder()
    bundle = FakeEmbeddingBundle(vector_size=5)

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        observed(bundle)
        vector, tokens = await query(bundle)

    assert vector == [1.0] * 5
    assert tokens == 7
    assert len(resolved.calls) == 1
    args, kwargs = resolved.calls[0]
    assert args == (WORKSPACE, PROVIDER_ID, "embedding")
    assert kwargs == {"instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_the_observer_covers_query_and_document_embeddings_alike():
    """One installation, both methods - the bundle is a bundle wherever it is used."""
    bundle = observed(FakeEmbeddingBundle())

    assert hasattr(bundle.encode_queries, "__wrapped__")
    assert hasattr(bundle.encode, "__wrapped__")
    assert bundle.encode_queries.__name__ == "encode_queries"
    assert bundle.max_length == 2048
    assert bundle.model_config is MODEL_CONFIG


# ---------------------------------------------------------------------------
# 3. The store failing must not change the retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_store_that_raises_never_replaces_the_provider_exception():
    failure = quota_failure()
    bundle = FakeEmbeddingBundle(failure=failure)

    with pytest.raises(EmbeddingQuotaExhausted) as control:
        await query(FakeEmbeddingBundle(failure=quota_failure()))

    with patch.object(health, "emit_failure", Recorder(raises=RuntimeError("health store unavailable"))):
        observed(bundle)
        with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
            await query(bundle)

    assert excinfo.value is failure, "the provider's own exception, not the store's"
    assert fingerprint(excinfo.value) == fingerprint(control.value)


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_successful_query_successful():
    bundle = FakeEmbeddingBundle(vector_size=4)

    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        observed(bundle)
        vector, tokens = await query(bundle)

    assert vector == [1.0] * 4
    assert tokens == 7


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_failed_query_failing_the_same_way():
    failure = quota_failure()
    bundle = FakeEmbeddingBundle(failure=failure)

    with pytest.raises(EmbeddingQuotaExhausted) as control:
        await query(FakeEmbeddingBundle(failure=quota_failure()))

    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        observed(bundle)
        with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
            await query(bundle)

    assert excinfo.value is failure
    assert fingerprint(excinfo.value) == fingerprint(control.value)


# ---------------------------------------------------------------------------
# 4. An identity that cannot be proven is simply not observed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identity_resolver_that_raises_does_not_touch_the_query():
    emitted = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", emitted):
        observed(bundle, identity_error=RuntimeError("identity lookup exploded"))
        with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
            await query(bundle)

    assert fingerprint(excinfo.value)[2] == model_errors.EMBEDDING_QUOTA_EXHAUSTED
    assert emitted.calls == [], "no identity means no fact, never a guessed one"


@pytest.mark.asyncio
async def test_an_identity_resolver_that_raises_leaves_a_healthy_query_successful():
    recorder = Recorder()

    with patch.object(health, "emit_failure", recorder), patch.object(health, "resolve_on_success", recorder):
        bundle = observed(FakeEmbeddingBundle(vector_size=6), identity_error=RuntimeError("identity lookup exploded"))
        vector, _tokens = await query(bundle)

    assert vector == [1.0] * 6
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_a_reference_that_proves_no_identity_is_not_observed_or_guessed():
    """A legacy composite name is not an identity, so it buys no observation."""
    emitted = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", emitted):
        observed(bundle, identity=None, ref=COMPOSITE_NAME)
        with pytest.raises(EmbeddingQuotaExhausted):
            await query(bundle)

    assert emitted.calls == []
    assert not hasattr(bundle.encode_queries, "__wrapped__")


@pytest.mark.asyncio
async def test_a_tenant_default_binding_with_no_id_is_not_observed():
    emitted = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", emitted):
        provider_health_observation.observe_embedding_calls(bundle, WORKSPACE, None)
        with pytest.raises(EmbeddingQuotaExhausted):
            await query(bundle)

    assert emitted.calls == []


# ---------------------------------------------------------------------------
# 5. Secret-argument proof
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neither_the_key_nor_the_question_reaches_the_store():
    recorder = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", recorder), patch.object(health, "resolve_on_success", recorder):
        observed(bundle)
        with pytest.raises(EmbeddingQuotaExhausted):
            await query(bundle)

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]

    # The argument NAMES are the whitelist: nothing here can hold a key, a config,
    # a raw body, or the text a user searched for.
    assert set(kwargs) == {"provider_id", "instance_id"}
    assert tuple(args) == (WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED)

    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    for secret in (API_KEY_SENTINEL, QUERY_SENTINEL, CHUNK_SENTINEL, GEMINI_BODY, "raw_message", "model_config", "api_key"):
        assert secret not in rendered, secret


@pytest.mark.asyncio
async def test_no_key_travels_with_the_success_path_either():
    recorder = Recorder()
    bundle = FakeEmbeddingBundle()

    with patch.object(health, "resolve_on_success", recorder):
        observed(bundle)
        await query(bundle)

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert set(kwargs) == {"instance_id"}
    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    assert API_KEY_SENTINEL not in rendered
