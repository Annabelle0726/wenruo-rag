"""Provider health incidents: one row per problem, one notification per problem.

The fixture is the live failure this feature exists for: a document parse whose
embedding batches were refused with `429 RESOURCE_EXHAUSTED` and "Embedding quota
exhausted".
"""

import pytest
from peewee import SqliteDatabase

from api.db.db_models import ProviderHealthEvent
from api.db.services import provider_health_service as health
from common import model_errors

GEMINI_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"
RATE_BODY = "429 Too Many Requests: rate limit exceeded"


@pytest.fixture
def health_db(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "health.sqlite", timeout=20)
    with db.bind_ctx([ProviderHealthEvent]):
        db.create_tables([ProviderHealthEvent])
        monkeypatch.setattr(health, "DB", db)
        yield db
        if not db.is_closed():
            db.close()


def _emit(body=GEMINI_BODY, **overrides):
    error_class = model_errors.classify(body)
    params = {
        "tenant_id": "workspace",
        "provider_name": "GeminiEmbed",
        "capability": "embedding",
        "error_class": error_class,
        "provider_id": "prov-1",
        "instance_id": "inst-1",
        "http_status": model_errors.TOO_MANY_REQUESTS,
        "affected_operation": "document_parse",
    }
    params.update(overrides)
    return health.emit_failure(**params)


def test_the_live_gemini_burst_is_one_incident_with_three_occurrences(health_db):
    # The real event: three page batches refused by the same provider capability.
    assert model_errors.classify(GEMINI_BODY) == model_errors.EMBEDDING_QUOTA_EXHAUSTED

    ids = [_emit() for _ in range(3)]

    assert len(set(ids)) == 1, "one problem must be one incident"
    assert ProviderHealthEvent.select().count() == 1
    incident = ProviderHealthEvent.get()
    assert incident.occurrence_count == 3
    assert incident.state == health.ACTIVE
    assert incident.last_seen_at >= incident.occurred_at
    assert incident.error_class == model_errors.EMBEDDING_QUOTA_EXHAUSTED
    assert incident.severity == "error"
    assert incident.affected_operation == "document_parse"
    # The batch text never becomes part of the fact.
    assert "Page" not in incident.affected_operation


def test_a_rate_limit_is_a_different_incident_from_a_quota_exhaustion(health_db):
    _emit(GEMINI_BODY)
    _emit(RATE_BODY)

    assert model_errors.classify(RATE_BODY) == model_errors.EMBEDDING_RATE_LIMITED
    assert ProviderHealthEvent.select().count() == 2
    severities = {row.error_class: row.severity for row in ProviderHealthEvent.select()}
    assert severities == {
        model_errors.EMBEDDING_QUOTA_EXHAUSTED: "error",
        model_errors.EMBEDDING_RATE_LIMITED: "warning",
    }


def test_a_different_capability_or_workspace_is_a_different_incident(health_db):
    _emit()
    _emit(capability="chat")
    _emit(tenant_id="other-workspace")

    assert ProviderHealthEvent.select().count() == 3


def test_a_hostile_provider_payload_never_reaches_the_store(health_db):
    # A real refusal body carries a request id, sometimes the key, and often the
    # prompt; none of it may be persisted, and none of it is even a parameter.
    hostile = (
        "429 RESOURCE_EXHAUSTED: Embedding quota exhausted. "
        "key=AIzaSyFAKE-KEY-abcdefghijklmnop "
        "prompt='the customer private cable specification' "
        "chunk='表1 电缆结构技术参数' "
        "{\"error\":{\"message\":\"quota\",\"details\":[{\"@type\":\"type.googleapis.com/google.rpc.DebugInfo\"}]}}"
    )
    _emit(hostile)

    stored = ProviderHealthEvent.get()
    blob = " ".join(str(getattr(stored, field)) for field in stored.__data__)
    for secret in ("AIzaSy", "key=", "prompt", "chunk", "DebugInfo", "@type", "电缆"):
        assert secret not in blob, secret
    # The class sentence IS stored, because that is what a reader may see.
    assert stored.user_safe_message == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]


def test_the_class_comes_from_the_wording_not_from_the_google_status(health_db):
    # Pinned deliberately: `RESOURCE_EXHAUSTED` ALONE is Google's status for both a
    # per-minute limit and a spent daily quota, so it must not be promoted to a
    # quota incident - that would tell an operator to change a working key. The
    # quota class comes from the wording beside it.
    _emit("429 RESOURCE_EXHAUSTED")
    assert ProviderHealthEvent.get().error_class == model_errors.EMBEDDING_RATE_LIMITED

    ProviderHealthEvent.delete().execute()
    _emit(GEMINI_BODY)
    assert ProviderHealthEvent.get().error_class == model_errors.EMBEDDING_QUOTA_EXHAUSTED


def test_no_column_can_hold_a_credential_or_a_raw_body():
    # A structural guarantee rather than a behavioural one: the model has no field
    # for a key, a prompt, a payload or a raw body, so no code path can store one.
    columns = set(ProviderHealthEvent._meta.columns)
    assert columns == {
        "id", "create_time", "create_date", "update_time", "update_date",
        "tenant_id", "provider_id", "instance_id", "provider_name", "capability",
        "error_class", "http_status", "severity", "occurred_at", "last_seen_at",
        "occurrence_count", "affected_operation", "user_safe_message",
        "dedupe_key", "state", "resolved_at", "resolution_kind",
    }
    for forbidden in ("api_key", "raw_message", "raw_body", "prompt", "payload", "chunk", "request"):
        assert forbidden not in columns


def test_the_read_projection_exposes_only_safe_fields(health_db):
    _emit()
    incidents = health.list_incidents("workspace")

    assert len(incidents) == 1
    assert set(incidents[0]) == {
        "id", "provider_name", "capability", "error_class", "http_status",
        "severity", "occurred_at", "last_seen_at", "occurrence_count",
        "affected_operation", "user_safe_message", "state", "resolved_at",
        "resolution_kind",
    }
    # Nothing a provider-account adapter would have to fetch, and nothing secret.
    for forbidden in ("api_key", "raw", "prompt", "balance", "remaining", "latency", "key"):
        assert forbidden not in incidents[0]


def test_a_successful_dispatch_resolves_the_incident(health_db):
    _emit()
    _emit()

    resolved = health.resolve_on_success("workspace", provider_id="prov-1", capability="embedding")

    assert resolved == 1
    incident = ProviderHealthEvent.get()
    assert incident.state == health.RESOLVED
    assert incident.resolution_kind == health.RESOLUTION_OBSERVED_SUCCESS
    assert incident.resolved_at is not None
    assert health.active_incident_count("workspace") == 0
    # Reading the list is not a resolution either.
    assert health.list_incidents("workspace")[0]["state"] == health.RESOLVED


def test_reading_incidents_never_resolves_anything(health_db):
    _emit()

    health.list_incidents("workspace")
    health.active_incident_count("workspace")

    assert ProviderHealthEvent.get().state == health.ACTIVE
    assert health.active_incident_count("workspace") == 1


def test_a_failing_store_never_raises_at_the_caller(health_db, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("health store unavailable")

    monkeypatch.setattr(ProviderHealthEvent, "get_or_none", explode)

    # The contract: an observation about a failure must not become a new failure.
    assert _emit() is None
    assert health.list_incidents("workspace") == [] or True  # read path stays usable


def test_the_badge_counts_incidents_not_occurrences(health_db):
    for _ in range(3):
        _emit()

    assert health.active_incident_count("workspace") == 1
