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

"""Provider Health at the parse embedding boundary: it rides along, it changes nothing.

The fixture is the live event this feature exists for - a document parse whose
embedding batches Gemini refused with ``429 RESOURCE_EXHAUSTED`` and "Embedding
quota exhausted" - and the identity it is asserted against is the live one:
workspace ``a9e28731...``, provider ``ee6cb91b...`` (``Gemini``), instance
``f7825d47...``.

Every test here drives the REAL ``TaskHandler._bind_embedding_model``: only the
provider, the model config and the store are faked. What is asserted is never
"health was called" on its own but "the parse behaves exactly as it did before
health existed, and the fact that was recorded is the one the identity proves".
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

#: The refusal body Gemini actually answered with.
GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"

#: Sentinels: if any of these reaches a health writer, the side-channel is leaking
#: a credential, a raw provider body, or the document's own text into the store.
API_KEY_SENTINEL = "__MUST_NEVER_REACH_HEALTH__"
PROMPT_SENTINEL = "customer-private-cable-specification"
CHUNK_SENTINEL = "表1 电缆结构技术参数"

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "Gemini"
OTHER_INSTANCE_ID = "11111111111111111111111111111111"
OTHER_PROVIDER_ID = "22222222222222222222222222222222"
OTHER_WORKSPACE = "33333333333333333333333333333333"
MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"

IDENTITY = ModelIdentity(
    tenant_id=WORKSPACE,
    provider_id=PROVIDER_ID,
    instance_id=INSTANCE_ID,
    provider_name=PROVIDER_NAME,
    capability="embedding",
)

#: The config carries the key exactly as the real resolver would return it, so the
#: "no key reaches the store" assertion is made against a value that is really there.
MODEL_CONFIG = {
    "llm_factory": "Gemini",
    "api_key": API_KEY_SENTINEL,
    "llm_name": "gemini-embedding-001",
    "api_base": "",
    "model_type": "embedding",
}

#: The task's model reference is a tenant_model PRIMARY KEY, which is the only
#: thing that can prove an identity.
MODEL_REFERENCE = MODEL_ID


class FakeEmbeddingBundle:
    """A real object shaped like an embedding bundle.

    Deliberately not a ``MagicMock``: the observer shadows methods on the instance,
    and asserting that the parse still works through that requires a real object
    with real attributes, a real context-manager protocol and a real call count.
    """

    def __init__(self, vector_size=3, failure=None, failure_after=0):
        self.model_config = MODEL_CONFIG
        self.max_length = 2048
        self.llm_name = "gemini-embedding-001"
        self.calls = 0
        self.closed = False
        self.entered = False
        self._vector_size = vector_size
        self._failure = failure
        self._failure_after = failure_after

    def encode(self, texts):
        """Batch-encode texts into vectors."""
        self.calls += 1
        if self._failure is not None and self.calls > self._failure_after:
            raise self._failure
        return [[float(i)] * self._vector_size for i in range(len(texts))], len(texts)

    def encode_queries(self, text):
        self.calls += 1
        if self._failure is not None and self.calls > self._failure_after:
            raise self._failure
        return [1.0] * self._vector_size, 1

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False


class Recorder:
    """Captures exactly what a health writer was handed."""

    def __init__(self, raises=None):
        self.calls = []
        self.raises = raises

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.raises is not None:
            raise self.raises

    @property
    def kwargs(self):
        return [kwargs for _args, kwargs in self.calls]


def fingerprint(exc):
    """Everything a caller can observe about a provider failure."""
    return (
        type(exc),
        str(exc),
        getattr(exc, "error_type", None),
        getattr(exc, "retryable", None),
    )


def quota_failure():
    """The refusal the typed provider path actually raises for the live body."""
    return EmbeddingQuotaExhausted("GeminiEmbed", f"{GEMINI_BODY} prompt='{PROMPT_SENTINEL}' chunk='{CHUNK_SENTINEL}'")


@contextlib.contextmanager
def parse_boundary(bundle, *, identity=IDENTITY, identity_error=None):
    """Drive the real bind boundary with the provider and the resolver faked.

    ``identity_error`` models an identity resolver that itself blows up, which the
    boundary must survive without the parse noticing.
    """

    def _resolve(*_args, **_kwargs):
        if identity_error is not None:
            raise identity_error
        return identity

    with (
        patch.object(provider_health_observation, "resolve_model_identity_by_id", _resolve),
        patch.object(task_handler_module, "get_model_config_by_id", return_value=MODEL_CONFIG),
        patch.object(task_handler_module, "resolve_model_config", return_value=MODEL_CONFIG),
        patch.object(task_handler_module, "get_tenant_default_model_by_type", return_value=MODEL_CONFIG),
        patch.object(task_handler_module, "LLMBundle", return_value=bundle),
    ):
        yield


@pytest.fixture
def sealed_task_context(task_context):
    """A task whose embedding binding is a tenant_model id."""
    task_context.raw_task["tenant_embd_id"] = MODEL_REFERENCE
    task_context.raw_task["embd_id"] = MODEL_REFERENCE
    return task_context


# ---------------------------------------------------------------------------
# 1. A typed failure: recorded, and propagated exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_real_refusal_is_recorded_once_and_reaches_the_caller_unchanged(sealed_task_context):
    observed = Recorder()
    failure = quota_failure()
    bundle = FakeEmbeddingBundle(failure=failure)

    with patch.object(health, "emit_failure", observed), patch.object(health, "resolve_on_success", Recorder()):
        with parse_boundary(bundle):
            with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
                await TaskHandler(sealed_task_context)._bind_embedding_model()

    # The very same exception object, with the caller-visible surface untouched.
    assert excinfo.value is failure
    assert fingerprint(excinfo.value) == (
        EmbeddingQuotaExhausted,
        str(failure),
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
        False,
    )

    # One problem is one fact, keyed by the identity a model id proves.
    assert len(observed.calls) == 1
    args, kwargs = observed.calls[0]
    assert args == (
        WORKSPACE,
        PROVIDER_NAME,
        "embedding",
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
    )
    assert kwargs == {"provider_id": PROVIDER_ID, "instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_a_burst_of_refusals_is_one_fact_for_the_task(sealed_task_context):
    observed = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure(), failure_after=0)

    with patch.object(health, "emit_failure", observed), patch.object(health, "resolve_on_success", Recorder()):
        with parse_boundary(bundle):
            handler = TaskHandler(sealed_task_context)
            with pytest.raises(EmbeddingQuotaExhausted):
                await handler._bind_embedding_model()
            # Later calls of the same task keep failing; none of them reports again.
            with pytest.raises(EmbeddingQuotaExhausted):
                bundle.encode_queries("another batch")
            with pytest.raises(EmbeddingQuotaExhausted):
                bundle.encode_queries("one more")

    assert len(observed.calls) == 1


@pytest.mark.asyncio
async def test_an_unrecognised_failure_is_not_a_health_fact(sealed_task_context):
    observed = Recorder()
    bundle = FakeEmbeddingBundle(failure=ValueError("local bug in the chunk pipeline"))

    with patch.object(health, "emit_failure", observed):
        with parse_boundary(bundle):
            with pytest.raises(ValueError, match="local bug"):
                await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert observed.calls == []


# ---------------------------------------------------------------------------
# 2. A healthy parse: unchanged, and it resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_healthy_parse_is_unchanged_and_resolves_the_capability(sealed_task_context):
    resolved = Recorder()
    bundle = FakeEmbeddingBundle(vector_size=5)

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        with parse_boundary(bundle):
            result = await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert result == (bundle, 5)
    assert len(resolved.calls) == 1
    args, kwargs = resolved.calls[0]
    assert args == (WORKSPACE, PROVIDER_ID, "embedding")
    assert kwargs == {"instance_id": INSTANCE_ID}


@pytest.mark.asyncio
async def test_many_successes_report_one_recovery_for_the_task(sealed_task_context):
    resolved = Recorder()
    bundle = FakeEmbeddingBundle()

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", resolved):
        with parse_boundary(bundle):
            await TaskHandler(sealed_task_context)._bind_embedding_model()
            for _ in range(20):
                bundle.encode(["a", "b"])

    assert len(resolved.calls) == 1


@pytest.mark.asyncio
async def test_the_boundary_still_uses_the_bundle_like_a_bundle(sealed_task_context):
    """Shadowing must not cost the object its other roles."""
    bundle = FakeEmbeddingBundle()

    with patch.object(health, "emit_failure", Recorder()), patch.object(health, "resolve_on_success", Recorder()):
        with parse_boundary(bundle):
            result = await TaskHandler(sealed_task_context)._bind_embedding_model()

    observed_bundle, _vector_size = result
    assert observed_bundle is bundle
    assert bundle.calls == 1, "the bind probe still ran exactly once"
    with observed_bundle as entered:
        assert entered is bundle
    assert bundle.entered and bundle.closed
    assert bundle.max_length == 2048
    assert bundle.model_config is MODEL_CONFIG


@pytest.mark.asyncio
async def test_a_caller_cannot_tell_the_method_is_being_observed(sealed_task_context):
    """Shadowing must leave the method's identity and signature looking intact."""
    import inspect

    bundle = FakeEmbeddingBundle()
    before = inspect.signature(bundle.encode)

    with (
        patch.object(health, "emit_failure", Recorder()),
        patch.object(health, "resolve_on_success", Recorder()),
        parse_boundary(bundle),
    ):
        await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert bundle.encode.__name__ == "encode"
    assert inspect.signature(bundle.encode) == before
    assert bundle.encode.__doc__ == "Batch-encode texts into vectors."


# ---------------------------------------------------------------------------
# 3. The store failing must not replace the provider's exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_store_that_raises_never_replaces_the_provider_exception(sealed_task_context):
    failure = quota_failure()
    bundle = FakeEmbeddingBundle(failure=failure)
    control = FakeEmbeddingBundle(failure=failure)

    # Control: the same call with Provider Health switched off entirely.
    with parse_boundary(control, identity=None):
        with pytest.raises(EmbeddingQuotaExhausted) as control_info:
            await TaskHandler(sealed_task_context)._bind_embedding_model()

    with patch.object(health, "emit_failure", Recorder(raises=RuntimeError("health store unavailable"))):
        with parse_boundary(bundle):
            with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
                await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert excinfo.value is failure, "the provider's own exception, not the store's"
    assert fingerprint(excinfo.value) == fingerprint(control_info.value)


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_successful_parse_successful(sealed_task_context):
    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        with parse_boundary(FakeEmbeddingBundle()):
            result = await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert result is not None
    bundle, vector_size = result
    assert vector_size == 3


@pytest.mark.asyncio
async def test_a_resolution_that_raises_leaves_a_failed_parse_failing_the_same_way(sealed_task_context):
    failure = quota_failure()
    bundle = FakeEmbeddingBundle(failure=failure)
    control = FakeEmbeddingBundle(failure=quota_failure())

    with parse_boundary(control, identity=None):
        with pytest.raises(EmbeddingQuotaExhausted) as control_info:
            await TaskHandler(sealed_task_context)._bind_embedding_model()

    with patch.object(health, "resolve_on_success", Recorder(raises=RuntimeError("health store unavailable"))):
        with parse_boundary(bundle):
            with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
                await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert excinfo.value is failure
    assert fingerprint(excinfo.value) == fingerprint(control_info.value)


# ---------------------------------------------------------------------------
# 4. An identity that cannot be proven is simply not observed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_identity_resolver_that_raises_does_not_touch_the_parse(sealed_task_context):
    observed = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with (
        patch.object(health, "emit_failure", observed),
        parse_boundary(bundle, identity_error=RuntimeError("identity lookup exploded")),
    ):
        with pytest.raises(EmbeddingQuotaExhausted) as excinfo:
            await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert fingerprint(excinfo.value)[2] == model_errors.EMBEDDING_QUOTA_EXHAUSTED
    assert observed.calls == [], "no identity means no fact, never a guessed one"


@pytest.mark.asyncio
async def test_an_identity_resolver_that_raises_leaves_a_healthy_parse_successful(sealed_task_context):
    observed = Recorder()

    with (
        patch.object(health, "emit_failure", observed),
        patch.object(health, "resolve_on_success", observed),
        parse_boundary(FakeEmbeddingBundle(), identity_error=RuntimeError("identity lookup exploded")),
    ):
        result = await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert result is not None
    assert result[1] == 3
    assert observed.calls == []


@pytest.mark.asyncio
async def test_an_unresolvable_identity_is_not_observed_rather_than_guessed(sealed_task_context):
    observed = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with patch.object(health, "emit_failure", observed), parse_boundary(bundle, identity=None):
        with pytest.raises(EmbeddingQuotaExhausted):
            await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert observed.calls == []


# ---------------------------------------------------------------------------
# 5. Secret-argument proof
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_scalar_identity_and_the_class_reach_the_store(sealed_task_context):
    recorder = Recorder()
    bundle = FakeEmbeddingBundle(failure=quota_failure())

    with (
        patch.object(health, "emit_failure", recorder),
        patch.object(health, "resolve_on_success", recorder),
        parse_boundary(bundle),
    ):
        with pytest.raises(EmbeddingQuotaExhausted):
            await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]

    # The argument NAMES are the whitelist: nothing here can hold a key, a config,
    # a raw body, a prompt or a chunk.
    assert set(kwargs) == {"provider_id", "instance_id"}
    assert tuple(args) == (WORKSPACE, PROVIDER_NAME, "embedding", model_errors.EMBEDDING_QUOTA_EXHAUSTED)

    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    for secret in (API_KEY_SENTINEL, PROMPT_SENTINEL, CHUNK_SENTINEL, GEMINI_BODY, "raw_message", "model_config", "api_key"):
        assert secret not in rendered, secret

    # The safe sentence is derived from the CLASS, never from the body.
    assert health.safe_message_of(model_errors.EMBEDDING_QUOTA_EXHAUSTED) == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]
    assert PROMPT_SENTINEL not in health.safe_message_of(model_errors.EMBEDDING_QUOTA_EXHAUSTED)


@pytest.mark.asyncio
async def test_no_key_travels_with_the_success_path_either(sealed_task_context):
    recorder = Recorder()

    with patch.object(health, "resolve_on_success", recorder), parse_boundary(FakeEmbeddingBundle()):
        await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert set(kwargs) == {"instance_id"}
    rendered = " ".join(str(part) for part in (*args, *kwargs.values()))
    assert API_KEY_SENTINEL not in rendered


def test_the_observer_cannot_be_handed_a_config_at_all():
    """The shape is the guarantee: there is no parameter for one."""
    import inspect

    observer_params = set(inspect.signature(health.CapabilityObserver.__init__).parameters)
    assert observer_params == {
        "self",
        "tenant_id",
        "provider_id",
        "instance_id",
        "provider_name",
        "capability",
    }
    for forbidden in ("model_config", "raw_message", "api_key", "identity", "exc", "error"):
        assert forbidden not in observer_params


# ---------------------------------------------------------------------------
# 6. A success closes only the incident its own identity raised
# ---------------------------------------------------------------------------


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "health-boundary.sqlite", timeout=20)
    with db.bind_ctx([ProviderHealthEvent]):
        db.create_tables([ProviderHealthEvent])
        monkeypatch.setattr(health, "DB", db)
        yield db
        if not db.is_closed():
            db.close()


def _seed_incident(tenant_id, provider_id, instance_id, capability):
    """Write a real incident straight through the real writer."""
    return health.emit_failure(
        tenant_id,
        PROVIDER_NAME,
        capability,
        model_errors.EMBEDDING_QUOTA_EXHAUSTED,
        provider_id=provider_id,
        instance_id=instance_id,
    )


def _states():
    return {row.id: row.state for row in ProviderHealthEvent.select()}


@pytest.mark.asyncio
async def test_a_recovery_closes_only_its_own_incident(health_db, sealed_task_context):
    mine = _seed_incident(WORKSPACE, PROVIDER_ID, INSTANCE_ID, "embedding")
    other_instance = _seed_incident(WORKSPACE, PROVIDER_ID, OTHER_INSTANCE_ID, "embedding")
    other_provider = _seed_incident(WORKSPACE, OTHER_PROVIDER_ID, INSTANCE_ID, "embedding")
    other_workspace = _seed_incident(OTHER_WORKSPACE, PROVIDER_ID, INSTANCE_ID, "embedding")
    other_capability = _seed_incident(WORKSPACE, PROVIDER_ID, INSTANCE_ID, "chat")

    with parse_boundary(FakeEmbeddingBundle()):
        result = await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert result is not None, "the parse itself is unaffected"
    states = _states()
    assert states[mine] == health.RESOLVED
    for untouched, label in (
        (other_instance, "another instance of the same provider"),
        (other_provider, "another provider"),
        (other_workspace, "another workspace"),
        (other_capability, "another capability on the same provider and instance"),
    ):
        assert states[untouched] == health.ACTIVE, label


@pytest.mark.asyncio
async def test_another_instance_recovering_does_not_close_this_one(health_db, sealed_task_context):
    mine = _seed_incident(WORKSPACE, PROVIDER_ID, INSTANCE_ID, "embedding")

    other = ModelIdentity(
        tenant_id=WORKSPACE,
        provider_id=PROVIDER_ID,
        instance_id=OTHER_INSTANCE_ID,
        provider_name=PROVIDER_NAME,
        capability="embedding",
    )
    with parse_boundary(FakeEmbeddingBundle(), identity=other):
        await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert _states()[mine] == health.ACTIVE


@pytest.mark.asyncio
async def test_a_fact_without_a_proven_instance_stays_closable(health_db, sealed_task_context):
    """A weakly-attributed row must not be able to pin an incident open forever."""
    unproven = _seed_incident(WORKSPACE, PROVIDER_ID, "", "embedding")

    with parse_boundary(FakeEmbeddingBundle()):
        await TaskHandler(sealed_task_context)._bind_embedding_model()

    assert _states()[unproven] == health.RESOLVED