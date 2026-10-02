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

"""Chat provider health: what the mechanism does, and what the chat path will not let it see.

Two things are established here, and the second is the reason the chat milestone is
NOT closed.

**The mechanism is ready for chat.** Identity comes from the same ``tenant_model``
id the chat config was resolved from, through the same resolver; the observer
handles the three shapes chat answers in - an awaited call, and the two streaming
generators - without changing the exception, the result, or the kind of object the
caller receives. A chat incident and an embedding incident on ONE provider instance
stay separate capabilities that never close each other.

**The chat path does not raise for a provider failure.** Every chat connector's
``async_chat``/``async_chat_streamly`` wraps the provider call in a broad
``except Exception`` and converts the failure into ENDPOINT TEXT
(``**ERROR**: {code} - {detail}``), which is returned - or yielded - as the answer.
The live connector for this workspace (``deepseek-v4-flash`` via ``LiteLLMBase``)
does exactly that, so an observer scoped to exceptions records nothing for the real
rate-limit/quota refusal. That is a finding about the chat architecture, not about
the observer, and it is pinned by the last section so it fails loudly if the
architecture changes.

The identity values are production's: workspace ``a9e28731...``, provider
``ee6cb91b...``, instance ``f7825d47...``, chat model ``2607a247...``
(``deepseek-v4-flash``).
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from peewee import SqliteDatabase

import api.db.services.dialog_service as dialog_service
from api.db.db_models import ProviderHealthEvent
from api.db.joint_services import provider_health_observation
from api.db.joint_services.tenant_model_service import ModelIdentity
from api.db.services import provider_health_service as health
from common import model_errors
from common.constants import LLMType
from common.exceptions import ModelException
from rag.llm import chat_model

GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"
CHAT_REFUSAL = 'status: 429, response: {"error": {"message": "Rate limit reached for deepseek-v4-flash"}}'

API_KEY_SENTINEL = "__MUST_NEVER_REACH_HEALTH__"
SYSTEM_PROMPT_SENTINEL = "SYSTEM-PROMPT-MUST-NOT-BE-PERSISTED"
USER_MESSAGE_SENTINEL = "客户私有电缆规格问题"
TOOL_PAYLOAD_SENTINEL = "TOOL-PAYLOAD-MUST-NOT-BE-PERSISTED"

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
OTHER_WORKSPACE = "89a9df92b5bb11f182935728a82b1fe8"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "DeepSeek"
CHAT_MODEL_ID = "2607a247ab7611f1a2c83887d563fb04"
EMBED_MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"
OTHER_INSTANCE_ID = "11111111111111111111111111111111"
OTHER_PROVIDER_ID = "22222222222222222222222222222222"

CHAT_IDENTITY = ModelIdentity(
    tenant_id=WORKSPACE,
    provider_id=PROVIDER_ID,
    instance_id=INSTANCE_ID,
    provider_name=PROVIDER_NAME,
    capability="chat",
)

MODEL_CONFIG = {
    "llm_factory": "DeepSeek",
    "api_key": API_KEY_SENTINEL,
    "llm_name": "deepseek-v4-flash",
    "api_base": "",
    "model_type": "chat",
}


class FakeChatBundle:
    """A real object shaped like a chat bundle, answering in all three shapes."""

    def __init__(self, failure=None, answer="标准的第 6.2.2 条如下。", chunks=("标准", "的第 6.2.2 条")):
        self.model_config = MODEL_CONFIG
        self.max_length = 8192
        self.llm_name = "deepseek-v4-flash"
        self.calls = 0
        self._failure = failure
        self._answer = answer
        self._chunks = chunks

    async def async_chat(self, system, history, gen_conf=None, **kwargs):
        """Answer once."""
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        return self._answer

    async def async_chat_streamly(self, system, history, gen_conf=None, **kwargs):
        """Answer as a growing string."""
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        answer = ""
        for chunk in self._chunks:
            answer += chunk
            yield answer

    async def async_chat_streamly_delta(self, system, history, gen_conf=None, **kwargs):
        """Answer as deltas."""
        self.calls += 1
        if self._failure is not None:
            raise self._failure
        for chunk in self._chunks:
            yield chunk


class Recorder:
    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises


def chat_refusal():
    """The exception type the tree raises for a provider refusal."""
    return ModelException(CHAT_REFUSAL, retryable=True)


def typed_refusal():
    """An exception carrying the typed classification the embedding path sets.

    No chat connector sets ``error_type`` today - that is part of the finding - so
    this pins the PRECEDENCE rule on the shape a typed carrier would have.
    """

    class TypedChatError(ModelException):
        error_type = model_errors.EMBEDDING_RATE_LIMITED

    return TypedChatError(CHAT_REFUSAL, retryable=True)


def fingerprint(exc):
    return (type(exc), str(exc), getattr(exc, "error_type", None), getattr(exc, "retryable", None))


def installed(bundle, *, identity=CHAT_IDENTITY, ref=CHAT_MODEL_ID, tenant_id=WORKSPACE):
    """Install observation exactly as every chat call site does."""
    with patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: identity):
        provider_health_observation.observe_chat_calls(bundle, tenant_id, ref)
    return bundle


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "chat-health.sqlite", timeout=20)
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
# 1. The awaited call: recorded, and unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_awaited_refusal_is_recorded_once_and_survives_unchanged():
    emitted = Recorder()
    failure = chat_refusal()
    control_failure = chat_refusal()

    with pytest.raises(ModelException) as control:
        await FakeChatBundle(failure=control_failure).async_chat(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}])

    bundle = FakeChatBundle(failure=failure)
    with patch.object(health, "emit_failure", emitted), patch.object(health, "resolve_on_success", Recorder()):
        installed(bundle)
        with pytest.raises(ModelException) as excinfo:
            await bundle.async_chat(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}])

    assert excinfo.value is failure, "the provider's own exception object"
    assert fingerprint(excinfo.value) == fingerprint(control.value)

    assert len(emitted.calls) == 1
    args, kwargs = emitted.calls[0]
    assert args == (WORKSPACE, PROVIDER_NAME, "chat", model_errors.EMBEDDING_RATE_LIMITED)
    assert kwargs == {"provider_id": PROVIDER_ID, "instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_a_healthy_awaited_answer_is_unchanged_and_resolves():
    resolved = Recorder()
    bundle = FakeChatBundle()

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        installed(bundle)
        answer = await bundle.async_chat(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}])

    assert answer == "标准的第 6.2.2 条如下。"
    assert len(resolved.calls) == 1
    args, kwargs = resolved.calls[0]
    assert args == (WORKSPACE, PROVIDER_ID, "chat")
    assert kwargs == {"instance_id": INSTANCE_ID}


# ---------------------------------------------------------------------------
# 2. The streaming calls: the shapes the product actually uses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_streamed_refusal_is_recorded_once_and_survives_unchanged():
    emitted = Recorder()
    failure = chat_refusal()
    bundle = FakeChatBundle(failure=failure)

    with patch.object(health, "emit_failure", emitted):
        observed = installed(bundle)
        with pytest.raises(ModelException) as excinfo:
            async for _item in observed.async_chat_streamly_delta(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}]):
                pass

    assert excinfo.value is failure
    assert len(emitted.calls) == 1
    assert emitted.calls[0][0][2] == "chat"


@pytest.mark.asyncio
async def test_a_healthy_stream_is_unchanged_and_resolves_on_the_first_chunk():
    resolved = Recorder()
    bundle = FakeChatBundle(chunks=("标准", "的第", " 6.2.2 条"))

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        observed = installed(bundle)
        deltas = [item async for item in observed.async_chat_streamly_delta(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}])]

    assert deltas == ["标准", "的第", " 6.2.2 条"]
    assert len(resolved.calls) == 1, "the whole stream is one call, not one per chunk"
    assert resolved.calls[0][1] == {"instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_the_cumulative_stream_keeps_its_shape_and_its_promises():
    bundle = FakeChatBundle(chunks=("标准", "的第", " 6.2.2 条"))
    observed = installed(bundle)

    answers = [item async for item in observed.async_chat_streamly("sys", [])]

    assert answers == ["标准", "标准的第", "标准的第 6.2.2 条"]


@pytest.mark.asyncio
async def test_a_stream_the_caller_abandons_is_not_a_provider_failure():
    """Walking away from a stream is the caller's decision, not a health fact."""
    emitted = Recorder()
    bundle = FakeChatBundle(chunks=("a", "b", "c"))

    with patch.object(health, "emit_failure", emitted):
        observed = installed(bundle)
        stream = observed.async_chat_streamly_delta("sys", [])
        assert await stream.__anext__() == "a"
        await stream.aclose()

    assert emitted.calls == []


@pytest.mark.asyncio
async def test_the_observed_method_still_looks_and_acts_like_the_original():
    bundle = FakeChatBundle()
    observed = installed(bundle)

    assert observed.async_chat.__name__ == "async_chat"
    assert observed.async_chat_streamly_delta.__name__ == "async_chat_streamly_delta"
    assert observed.max_length == 8192
    assert observed.model_config is MODEL_CONFIG


# ---------------------------------------------------------------------------
# 3. Classification precedence, and no second taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_typed_class_wins_over_the_wording():
    emitted = Recorder()
    bundle = FakeChatBundle(failure=typed_refusal())

    with patch.object(health, "emit_failure", emitted):
        observed = installed(bundle)
        with pytest.raises(ModelException):
            await observed.async_chat("sys", [])

    assert emitted.calls[0][0][3] == model_errors.EMBEDDING_RATE_LIMITED


@pytest.mark.asyncio
async def test_the_capability_constants_agree_with_the_model_type_vocabulary():
    """Two constants describe the same word; a drift between them would split incidents."""
    assert health.CAPABILITY_CHAT == LLMType.CHAT.value
    assert health.CAPABILITY_EMBEDDING == LLMType.EMBEDDING.value


# ---------------------------------------------------------------------------
# 4. Fail-open
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_store_that_raises_never_replaces_the_chat_exception():
    failure = chat_refusal()
    bundle = FakeChatBundle(failure=failure)

    with pytest.raises(ModelException) as control:
        await FakeChatBundle(failure=chat_refusal()).async_chat("sys", [])

    with patch.object(health, "emit_failure", Recorder(raises=RuntimeError("health store unavailable"))):
        observed = installed(bundle)
        with pytest.raises(ModelException) as excinfo:
            await observed.async_chat("sys", [])

    assert excinfo.value is failure
    assert fingerprint(excinfo.value) == fingerprint(control.value)


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_successful_answer_successful():
    bundle = FakeChatBundle()

    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        observed = installed(bundle)
        answer = await observed.async_chat("sys", [])

    assert answer == "标准的第 6.2.2 条如下。"


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_stream_unchanged():
    bundle = FakeChatBundle(chunks=("a", "b"))

    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        observed = installed(bundle)
        deltas = [item async for item in observed.async_chat_streamly_delta("sys", [])]

    assert deltas == ["a", "b"]


@pytest.mark.asyncio
async def test_an_identity_resolver_that_raises_does_not_touch_the_chat_call():
    emitted = Recorder()
    bundle = FakeChatBundle(failure=chat_refusal())

    with (
        patch.object(health, "emit_failure", emitted),
        patch.object(provider_health_observation, "resolve_model_identity_by_id", side_effect=RuntimeError("identity lookup exploded")),
    ):
        provider_health_observation.observe_chat_calls(bundle, WORKSPACE, CHAT_MODEL_ID)
        with pytest.raises(ModelException) as excinfo:
            await bundle.async_chat("sys", [])

    assert excinfo.value is bundle._failure
    assert emitted.calls == []


@pytest.mark.asyncio
async def test_a_reference_that_proves_no_identity_is_not_observed_or_guessed():
    emitted = Recorder()
    bundle = FakeChatBundle(failure=chat_refusal())

    with patch.object(health, "emit_failure", emitted):
        installed(bundle, identity=None, ref="deepseek-v4-flash@DS@DeepSeek")
        with pytest.raises(ModelException):
            await bundle.async_chat("sys", [])

    assert emitted.calls == []
    assert not hasattr(bundle.async_chat, "__wrapped__")


# ---------------------------------------------------------------------------
# 5. Secret whitelist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neither_the_key_nor_the_conversation_reaches_the_store():
    recorder = Recorder()
    bundle = FakeChatBundle(failure=ModelException(f"{CHAT_REFUSAL} system='{SYSTEM_PROMPT_SENTINEL}' user='{USER_MESSAGE_SENTINEL}' tool='{TOOL_PAYLOAD_SENTINEL}'", retryable=True))

    with patch.object(health, "emit_failure", recorder), patch.object(health, "resolve_on_success", recorder):
        observed = installed(bundle)
        with pytest.raises(ModelException):
            await observed.async_chat(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}], {"tools": TOOL_PAYLOAD_SENTINEL})

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert set(kwargs) == {"provider_id", "instance_id"}
    assert tuple(args) == (WORKSPACE, PROVIDER_NAME, "chat", model_errors.EMBEDDING_RATE_LIMITED)

    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    for secret in (API_KEY_SENTINEL, SYSTEM_PROMPT_SENTINEL, USER_MESSAGE_SENTINEL, TOOL_PAYLOAD_SENTINEL, CHAT_REFUSAL, "raw_message", "model_config", "api_key"):
        assert secret not in rendered, secret


# ---------------------------------------------------------------------------
# 6. Capability isolation against a real store
# ---------------------------------------------------------------------------


def _seed_embedding_incident(tenant_id=WORKSPACE, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID):
    return health.emit_failure(
        tenant_id,
        PROVIDER_NAME,
        "embedding",
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
        provider_id=provider_id,
        instance_id=instance_id,
    )


def _seed_chat_incident(tenant_id=WORKSPACE, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID, error_class=model_errors.EMBEDDING_RATE_LIMITED):
    return health.emit_failure(
        tenant_id,
        PROVIDER_NAME,
        "chat",
        error_class,
        provider_id=provider_id,
        instance_id=instance_id,
    )


@pytest.mark.asyncio
async def test_a_chat_success_never_closes_an_embedding_incident(health_db):
    """Same provider instance, different capability: two problems, two rows."""
    embedding = _seed_embedding_incident()
    chat = _seed_chat_incident()

    observed = installed(FakeChatBundle())
    await observed.async_chat("sys", [])

    states = {row.id: row.state for row in _rows()}
    assert states[chat] == health.RESOLVED
    assert states[embedding] == health.ACTIVE, "a chat answer says nothing about the embedding capability"


class FakeEmbeddingShim:
    """Minimal embedding-shaped bundle, used only to cross the capability line."""

    def __init__(self):
        self.max_length = 2048
        self.model_config = MODEL_CONFIG

    def encode(self, texts):
        return [[0.0]], 1

    def encode_queries(self, text):
        return [0.0], 1


@pytest.mark.asyncio
async def test_an_embedding_success_never_closes_a_chat_incident(health_db):
    embedding = _seed_embedding_incident()
    chat = _seed_chat_incident()

    embedding_identity = ModelIdentity(WORKSPACE, PROVIDER_ID, INSTANCE_ID, PROVIDER_NAME, "embedding")
    embedding_bundle = FakeEmbeddingShim()
    with patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: embedding_identity):
        provider_health_observation.observe_embedding_calls(embedding_bundle, WORKSPACE, EMBED_MODEL_ID)
    embedding_bundle.encode_queries("一条查询")

    states = {row.id: row.state for row in _rows()}
    assert states[embedding] == health.RESOLVED
    assert states[chat] == health.ACTIVE, "an embedding call says nothing about the chat capability"


@pytest.mark.asyncio
async def test_a_chat_success_does_not_close_another_instance_provider_or_workspace(health_db):
    other_instance = _seed_chat_incident(instance_id=OTHER_INSTANCE_ID)
    other_provider = _seed_chat_incident(provider_id=OTHER_PROVIDER_ID)
    other_workspace = _seed_chat_incident(tenant_id=OTHER_WORKSPACE)
    mine = _seed_chat_incident()

    await installed(FakeChatBundle()).async_chat("sys", [])

    states = {row.id: row.state for row in _rows()}
    assert states[mine] == health.RESOLVED
    for untouched, label in (
        (other_instance, "another instance of the same provider"),
        (other_provider, "another provider"),
        (other_workspace, "another workspace"),
    ):
        assert states[untouched] == health.ACTIVE, label


@pytest.mark.asyncio
async def test_a_repeated_chat_refusal_counts_on_one_incident(health_db):
    for _ in range(3):
        bundle = installed(FakeChatBundle(failure=chat_refusal()))
        with pytest.raises(ModelException):
            await bundle.async_chat("sys", [])

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].occurrence_count == 3
    assert _fingerprint(rows[0]) == (WORKSPACE, PROVIDER_ID, INSTANCE_ID, "chat", model_errors.EMBEDDING_RATE_LIMITED)


@pytest.mark.asyncio
async def test_the_shared_chat_model_factory_observes_its_chat_bundle():
    """``get_models`` is the one factory behind RAG chat, agent chat and the OpenAI API."""
    dialog = SimpleNamespace(
        tenant_id=WORKSPACE,
        kb_ids=[],
        llm_id=CHAT_MODEL_ID,
        tenant_llm_id=CHAT_MODEL_ID,
        rerank_id="",
        tenant_rerank_id=None,
        prompt_config={},
    )
    bundle = FakeChatBundle()

    with (
        patch.object(provider_health_observation, "resolve_model_identity_by_id", lambda *_a, **_k: CHAT_IDENTITY),
        patch.object(dialog_service, "observe_chat_calls", wraps=provider_health_observation.observe_chat_calls) as observe_call,
        patch.object(dialog_service.KnowledgebaseService, "get_by_ids", return_value=[]),
        patch.object(dialog_service, "get_model_config_by_id", return_value=MODEL_CONFIG),
        patch.object(dialog_service, "resolve_rerank_mdl", return_value=None),
        patch.object(dialog_service, "LLMBundle", return_value=bundle),
    ):
        _kbs, _embd, _rerank, chat_mdl, _tts = dialog_service.get_models(dialog)

    assert chat_mdl is bundle
    observe_call.assert_called_once_with(bundle, WORKSPACE, CHAT_MODEL_ID)


# ---------------------------------------------------------------------------
# 7. Why this milestone is NOT closed: the chat path returns failures as text
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. Capability-aware safe message
# ---------------------------------------------------------------------------


def test_the_shared_taxonomy_keeps_its_wording_for_every_existing_consumer():
    """The API error responses read MESSAGES, so Provider Health must not rewrite it."""
    assert model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED] == "AI 向量化服务额度已耗尽，请更换 API Key 或等待额度重置后重试。"
    assert model_errors.MESSAGES[model_errors.EMBEDDING_RATE_LIMITED] == "AI 向量化服务请求过于频繁，请稍后重试。"
    # And the embedding capability still gets exactly that sentence.
    assert health.safe_message_for(model_errors.EMBEDDING_QUOTA_EXHAUSTED, "embedding") == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]
    assert health.safe_message_for(model_errors.EMBEDDING_RATE_LIMITED, "embedding") == model_errors.MESSAGES[model_errors.EMBEDDING_RATE_LIMITED]


def test_the_chat_capability_gets_a_sentence_about_the_service_that_failed():
    assert health.safe_message_for(model_errors.EMBEDDING_QUOTA_EXHAUSTED, "chat") == "AI 对话服务额度已耗尽，请更换 API Key 或等待额度重置后重试。"
    assert health.safe_message_for(model_errors.EMBEDDING_RATE_LIMITED, "chat") == "AI 对话服务请求过于频繁，请稍后重试。"


@pytest.mark.asyncio
async def test_the_stored_sentence_names_the_capabilitys_own_service(health_db):
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])
    await installed(FakeChatBundle(answer=answer)).async_chat("sys", [])

    embedding_id = _seed_embedding_incident()
    rows = {row.id: row for row in _rows()}
    chat_row = next(row for incident_id, row in rows.items() if incident_id != embedding_id)

    assert chat_row.user_safe_message == "AI 对话服务额度已耗尽，请更换 API Key 或等待额度重置后重试。"
    assert rows[embedding_id].user_safe_message == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]
    assert chat_row.error_class == model_errors.EMBEDDING_QUOTA_EXHAUSTED, "same class, different wording"


def test_the_observation_marker_is_the_connectors_own():
    """Read from the connector, so renaming it there cannot disable detection."""
    assert provider_health_observation.CHAT_FAILURE_MARKER == chat_model.ERROR_PREFIX


# ---------------------------------------------------------------------------
# 10. Why returned-failure detection is needed at all
# ---------------------------------------------------------------------------


class _RefusingConnector(chat_model.Base):
    """The OpenAI-compatible connector shape, with the provider call refused."""

    def __init__(self, detail=CHAT_REFUSAL):
        # Bypass the SDK client: this test is about the error surface, not the wire.
        self.max_retries = 1
        self.base_delay = 0
        self.last_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._detail = detail

    async def _async_chat(self, history, gen_conf, **kwargs):
        raise ModelException(self._detail, retryable=True)

    async def _async_chat_streamly(self, history, gen_conf, **kwargs):
        raise ModelException(self._detail, retryable=True)
        yield  # pragma: no cover - makes this an async generator


QUOTA_DETAIL = "429 RESOURCE_EXHAUSTED: chat quota exhausted for deepseek-v4-flash"


@pytest.mark.asyncio
async def test_the_chat_connector_returns_a_refusal_as_answer_text_instead_of_raising():
    """Why returned-failure detection exists at all.

    If a connector ever starts RAISING instead, this test fails - and the
    exception path already covers it, so the removal would be safe.
    """
    answer, tokens = await _RefusingConnector().async_chat("sys", [{"role": "user", "content": "hi"}])

    assert isinstance(answer, str)
    assert answer.startswith(chat_model.ERROR_PREFIX)
    assert tokens == 0
    assert model_errors.classify(answer) == model_errors.EMBEDDING_RATE_LIMITED


@pytest.mark.asyncio
async def test_the_streaming_chat_connector_yields_a_refusal_as_a_delta_instead_of_raising():
    deltas = []
    async for item in _RefusingConnector().async_chat_streamly("sys", [{"role": "user", "content": "hi"}]):
        deltas.append(item)

    assert deltas and isinstance(deltas[0], str)
    assert deltas[0].startswith(chat_model.ERROR_PREFIX)


# ---------------------------------------------------------------------------
# 8. Returned-failure detection: the refusal that arrives as a VALUE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_A_the_real_connector_quota_refusal_becomes_one_chat_incident(health_db):
    """A. The real returned shape, from the real connector, classified as a quota."""
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [{"role": "user", "content": USER_MESSAGE_SENTINEL}])
    assert answer.startswith(chat_model.ERROR_PREFIX), "the shape this detection is built on"

    bundle = FakeChatBundle(answer=answer)
    observed = installed(bundle)
    returned = await observed.async_chat(SYSTEM_PROMPT_SENTINEL, [{"role": "user", "content": USER_MESSAGE_SENTINEL}])

    assert returned == answer, "the connector's answer is returned byte-for-byte"
    rows = _rows()
    assert len(rows) == 1
    assert _fingerprint(rows[0]) == (WORKSPACE, PROVIDER_ID, INSTANCE_ID, "chat", model_errors.EMBEDDING_QUOTA_EXHAUSTED)
    assert rows[0].state == health.ACTIVE


@pytest.mark.asyncio
async def test_B_a_returned_rate_limit_is_classified_as_a_rate_limit(health_db):
    """B. Pacing and a spent quota stay distinguishable through this path too."""
    answer, _tokens = await _RefusingConnector(CHAT_REFUSAL).async_chat("sys", [])

    bundle = FakeChatBundle(answer=answer)
    await installed(bundle).async_chat("sys", [])

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].error_class == model_errors.EMBEDDING_RATE_LIMITED
    assert rows[0].severity == "warning"


@pytest.mark.asyncio
async def test_C_three_identical_returned_refusals_are_one_incident_with_three_occurrences(health_db):
    """C. A burst of returned refusals is one problem, exactly like a raised one."""
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])

    for _ in range(3):
        await installed(FakeChatBundle(answer=answer)).async_chat("sys", [])

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].occurrence_count == 3
    assert rows[0].error_class == model_errors.EMBEDDING_QUOTA_EXHAUSTED


@pytest.mark.asyncio
async def test_D_a_store_that_raises_leaves_the_returned_refusal_untouched():
    """D. The value the caller gets is identical whether or not the store works."""
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])

    with patch.object(health, "emit_failure", Recorder(raises=RuntimeError("health store unavailable"))):
        returned = await installed(FakeChatBundle(answer=answer)).async_chat("sys", [])

    assert returned == answer
    assert isinstance(returned, str)


@pytest.mark.asyncio
async def test_D_a_raising_identity_resolver_leaves_the_returned_refusal_untouched():
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])
    bundle = FakeChatBundle(answer=answer)

    with patch.object(provider_health_observation, "resolve_model_identity_by_id", side_effect=RuntimeError("identity lookup exploded")):
        provider_health_observation.observe_chat_calls(bundle, WORKSPACE, CHAT_MODEL_ID)

    assert await bundle.async_chat("sys", []) == answer


@pytest.mark.asyncio
async def test_E_a_streamed_returned_refusal_is_one_incident_and_the_stream_is_unchanged(health_db):
    """E. The streamed refusal, replayed exactly as the real connector yields it."""
    replayed = [item async for item in _RefusingConnector(QUOTA_DETAIL).async_chat_streamly("sys", [])]
    assert replayed[0].startswith(chat_model.ERROR_PREFIX)

    delivered = []
    bundle = installed(FakeChatBundle(chunks=tuple(replayed)))
    async for item in bundle.async_chat_streamly_delta("sys", []):
        delivered.append(item)

    assert delivered == replayed, "every yielded item is the connector's own, unchanged"
    rows = _rows()
    assert len(rows) == 1
    assert _fingerprint(rows[0]) == (WORKSPACE, PROVIDER_ID, INSTANCE_ID, "chat", model_errors.EMBEDDING_QUOTA_EXHAUSTED)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ordinary_answer",
    [
        "HTTP 429 means rate limit, which the provider applies per minute.",
        "quota exhausted 是什么意思？在这份标准里它指的是接口调用额度用尽。",
        "The error text says resource_exhausted and insufficient_quota; neither is a real request.",
        "**ERROR** handling in the parser is documented in section 6.2.2.",
    ],
)
async def test_F_G_an_ordinary_answer_about_failures_is_never_an_incident(health_db, ordinary_answer):
    """F, G. A sentence that DISCUSSES a refusal is not a refusal.

    The marker alone would not be enough here - the fourth case carries the real
    marker - so the classifier must recognise a provider class as well.
    """
    resolved = Recorder()
    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        returned = await installed(FakeChatBundle(answer=ordinary_answer)).async_chat("sys", [])

    assert returned == ordinary_answer
    assert _rows() == [], "an answer is not a health fact"
    assert len(resolved.calls) == 1, "and it is still an answer, so it resolves"


@pytest.mark.asyncio
async def test_the_marker_is_required_not_just_the_classifier(health_db):
    """Without the connector's marker, a recognised class is not evidence."""
    answer = "429 RESOURCE_EXHAUSTED: quota exhausted"  # classifiable, but not the marker shape

    await installed(FakeChatBundle(answer=answer)).async_chat("sys", [])

    assert _rows() == []


@pytest.mark.asyncio
async def test_a_returned_refusal_never_resolves_the_incident_it_reports(health_db):
    """A refusal is not a recovery - including through the trailing token sentinel."""
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])

    # A pre-existing active incident for the same identity AND the same class, so
    # the refusal below is the same problem - and must count, not resolve.
    existing = _seed_chat_incident(error_class=model_errors.EMBEDDING_QUOTA_EXHAUSTED)

    observed = installed(FakeChatBundle(chunks=(answer, 17)))
    async for _item in observed.async_chat_streamly_delta("sys", []):
        pass

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].id == existing
    assert rows[0].state == health.ACTIVE, "the refusal must not be taken for a recovery"
    assert rows[0].occurrence_count == 2


@pytest.mark.asyncio
async def test_a_later_normal_answer_still_resolves_after_a_returned_refusal(health_db):
    """Suppression is per call, so a genuine answer afterwards still recovers."""
    answer, _tokens = await _RefusingConnector(QUOTA_DETAIL).async_chat("sys", [])
    observed = installed(FakeChatBundle(answer=answer))
    await observed.async_chat("sys", [])
    assert _rows()[0].state == health.ACTIVE

    observed._answer = "标准的第 6.2.2 条如下。"
    await observed.async_chat("sys", [])

    assert _rows()[0].state == health.RESOLVED


@pytest.mark.asyncio
async def test_the_returned_refusal_text_never_reaches_the_store(health_db):
    """§8: the text may carry a key fragment, a request id and prompt content."""
    hostile = (
        f"{chat_model.ERROR_PREFIX}: ERROR_QUOTA - quota exhausted; key=AIzaSyFAKE-KEY-abcdefghijklmnop "
        f"request_id=req-9f8e7d6c prompt='{SYSTEM_PROMPT_SENTINEL}' user='{USER_MESSAGE_SENTINEL}'"
    )

    recorder = Recorder()
    with patch.object(health, "emit_failure", recorder):
        await installed(FakeChatBundle(answer=hostile)).async_chat("sys", [])

    args, kwargs = recorder.calls[0]
    assert set(kwargs) == {"provider_id", "instance_id"}
    assert tuple(args) == (WORKSPACE, PROVIDER_NAME, "chat", model_errors.EMBEDDING_QUOTA_EXHAUSTED)
    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    for secret in ("AIzaSy", "req-9f8e7d6c", SYSTEM_PROMPT_SENTINEL, USER_MESSAGE_SENTINEL, "quota exhausted", chat_model.ERROR_PREFIX):
        assert secret not in rendered, secret
