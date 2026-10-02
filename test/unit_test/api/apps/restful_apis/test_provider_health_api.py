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
"""The provider-health read API: what it serves, to whom, and what it cannot leak.

Two seams are exercised for real rather than mocked away. The ROUTE runs through
its own decorators inside a Quart request context, so `login_required` and the
JSON envelope are the production ones, and only the RBAC predicate and the
current-user proxy are stubbed - the same technique
`test/unit_test/api/apps/test_require_tenant_admin.py` documents. The READER runs
against a real store bound to SQLite, seeded through the production writer, so the
rows it serves are the rows the observation path actually creates.

The workspace ids are production's real pair (`a9e28731...` and `89a9df92...`), and
the hostile values are the ones a refusal body really carries.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from peewee import SqliteDatabase
from quart_auth import Unauthorized

import api.apps as apps_module
from api.db.db_models import ProviderHealthEvent
from api.db.services import provider_health_read_service as reader
from api.db.services import provider_health_service as health
from common import model_errors

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
OTHER_WORKSPACE = "89a9df92b5bb11f182935728a82b1fe8"
OWNER = "11111111111111111111111111111111"
ADMIN = "22222222222222222222222222222222"
MEMBER = "33333333333333333333333333333333"

PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
PROVIDER_NAME = "Gemini"

QUOTA_BODY = "429 RESOURCE_EXHAUSTED: Embedding quota exhausted for models/gemini-embedding-001"
RATE_BODY = "429 Too Many Requests: rate limit exceeded"
KEY_SENTINEL = "AIzaSyFAKE-KEY-abcdefghijklmnop"
PROMPT_SENTINEL = "客户私有电缆规格问题"
CHUNK_SENTINEL = "表1 电缆结构技术参数"
RAW_MESSAGE_SENTINEL = "raw_message-MUST-NOT-APPEAR"
PAYLOAD_SENTINEL = "request-payload-MUST-NOT-APPEAR"

FORBIDDEN_KEYS = (
    "api_key",
    "apikey",
    "raw_message",
    "raw_body",
    "raw_provider_body",
    "prompt",
    "chunk",
    "request",
    "payload",
    "model_config",
    "credential",
    "balance",
    "remaining",
    "remaining_quota",
    "quota_balance",
    "latency",
    "question",
    "user_query",
)

#: Every column the projection omits, named. `tenant_id` is the workspace in the
#: path, `http_status` is an integer, `dedupe_key` is an opaque hash and the rest
#: are bookkeeping timestamps - so the assertion below fails the day a new column
#: appears without a decision about whether it may be served.
UNEXPOSED_COLUMNS = {
    "tenant_id",
    "http_status",
    "dedupe_key",
    "create_time",
    "create_date",
    "update_time",
    "update_date",
}


@pytest.fixture(autouse=True)
def rbac(monkeypatch):
    """The RBAC predicate is stubbed: it owns its own tests, and this file is about
    which workspace it is asked about and what a denial looks like."""
    monkeypatch.setattr("api.db.services.user_service.UserTenantService.can_manage_tenant", lambda *_a, **_k: True)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


def _module():
    """The dynamically registered API module, after the app has loaded its pages."""
    return sys.modules["api.apps.restful_apis.provider_health_api"]


def _run(coro):
    """Run a coroutine on a fresh loop and close it.

    A loop that is only collected leaks the socket pair it opened, which surfaces
    as an unraisable-exception failure in whichever case triggers the collection.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _request(tenant_id, query="", body=None, *, user, can_manage=True, loader=...):
    """Call the real route inside a real request context; return (code, payload)."""
    module = _module()
    path = f"/api/v1/tenants/{tenant_id}/provider-health/incidents{query}"

    async def go():
        async with module.app.test_request_context(path):
            response = await module.provider_health_incidents(tenant_id=tenant_id)
            return json.loads(await response.get_data())

    with (
        patch("api.db.services.user_service.UserTenantService.can_manage_tenant", return_value=can_manage) as predicate,
        patch.object(module, "current_user", user),
        patch.object(apps_module, "_load_user", (lambda *_a, **_k: user) if loader is ... else loader),
    ):
        payload = _run(go())
    return payload, predicate


def _code(payload):
    return payload.get("code")


def _keys(value, found=None):
    """Every dict key anywhere in the decoded response."""
    found = set() if found is None else found
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(key)
            _keys(item, found)
    elif isinstance(value, list):
        for item in value:
            _keys(item, found)
    return found


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = SqliteDatabase(tmp_path / "provider-health-api.sqlite", timeout=20)
    with db.bind_ctx([ProviderHealthEvent]):
        db.create_tables([ProviderHealthEvent])
        monkeypatch.setattr(health, "DB", db)
        # The read service resolves DB from its own module at call time.
        monkeypatch.setattr(reader, "DB", db)
        yield db
        if not db.is_closed():
            db.close()


def _emit(tenant_id=WORKSPACE, capability="embedding", body=QUOTA_BODY, provider=PROVIDER_NAME, instance=INSTANCE_ID, moment=None):
    return health.emit_failure(
        tenant_id,
        provider,
        capability,
        model_errors.classify(body),
        provider_id=PROVIDER_ID,
        instance_id=instance,
        now=moment,
    )


def _read(user=OWNER, tenant_id=WORKSPACE, **kwargs):
    return reader.read_incidents(user, tenant_id, **kwargs)


def _ids(payload):
    """Incident ids from either layer: the service dict, or the route envelope."""
    data = payload.get("data") or payload
    return [incident["id"] for incident in data["incidents"]]


# ---------------------------------------------------------------------------
# 1-6, 13: what the view contains
# ---------------------------------------------------------------------------


def test_an_active_incident_is_readable_with_the_allowlisted_fields(store):
    incident_id = _emit(body=f"{QUOTA_BODY} prompt='{PROMPT_SENTINEL}'")

    with patch("api.db.services.user_service.UserTenantService.can_manage_tenant", return_value=True):
        payload = _read()

    assert _ids(payload) == [incident_id]
    incident = payload["incidents"][0]
    assert set(incident) == set(reader.INCIDENT_FIELDS)
    assert incident["provider_name"] == PROVIDER_NAME
    assert incident["capability"] == "embedding"
    assert incident["error_class"] == model_errors.EMBEDDING_QUOTA_EXHAUSTED
    assert incident["severity"] == "error"
    assert incident["state"] == "active"
    assert incident["occurrence_count"] == 1
    assert incident["affected_operation"] == ""
    assert incident["resolved_at"] is None
    assert incident["resolution_kind"] is None
    assert incident["user_safe_message"] == model_errors.MESSAGES[model_errors.EMBEDDING_QUOTA_EXHAUSTED]
    assert incident["occurred_at"] and incident["last_seen_at"]


def test_a_recently_resolved_incident_is_readable(store):
    incident_id = _emit()
    health.resolve_on_success(WORKSPACE, provider_id=PROVIDER_ID, capability="embedding", instance_id=INSTANCE_ID)

    payload = _read()

    assert _ids(payload) == [incident_id]
    incident = payload["incidents"][0]
    assert incident["state"] == "resolved"
    assert incident["resolved_at"] is not None
    assert incident["resolution_kind"] == health.RESOLUTION_OBSERVED_SUCCESS
    assert payload["active_count"] == 0
    assert payload["recently_resolved_count"] == 1


def test_active_incidents_come_first_and_each_side_is_most_recent_first(store):
    moment = datetime(2026, 3, 1, 12, 0, 0)
    older_active = _emit(body=RATE_BODY, moment=moment)
    newer_active = _emit(body=QUOTA_BODY, moment=moment + timedelta(minutes=30))
    resolved = _emit(body=RATE_BODY, capability="chat", moment=moment - timedelta(days=1))
    health.resolve_on_success(WORKSPACE, provider_id=PROVIDER_ID, capability="chat", instance_id=INSTANCE_ID, now=moment)

    payload = _read(now=moment + timedelta(hours=1))

    assert _ids(payload) == [newer_active, older_active, resolved], "active first, then recently resolved"


def test_occurrence_count_reaches_the_reader(store):
    moment = datetime(2026, 3, 1, 12, 0, 0)
    for offset in range(3):
        _emit(moment=moment + timedelta(seconds=offset))

    payload = _read(now=moment + timedelta(hours=1))

    assert payload["incidents"][0]["occurrence_count"] == 3


def test_active_count_counts_incidents_not_occurrences(store):
    """A badge reads this: one incident seen 30 times is one notification."""
    moment = datetime(2026, 3, 1, 12, 0, 0)
    for offset in range(30):
        _emit(moment=moment + timedelta(seconds=offset))
    _emit(body=RATE_BODY, moment=moment)  # a second, different problem
    _emit(body=RATE_BODY, capability="chat", moment=moment)  # and a third, on another capability

    payload = _read(now=moment + timedelta(hours=1))

    assert payload["active_count"] == 3
    assert payload["incidents"][0]["occurrence_count"] == 30, "the occurrences are still reported"
    assert payload["total_in_scope"] == 3


def test_an_empty_workspace_reports_an_honest_empty_state(store):
    payload = _read()

    assert payload["incidents"] == []
    assert payload["active_count"] == 0
    assert payload["recently_resolved_count"] == 0
    assert payload["total_in_scope"] == 0
    assert payload["truncated"] is False
    assert payload["lists_incomplete"] is False
    # Nothing invents a health verdict.
    assert not any(key in _keys(payload) for key in ("healthy", "status", "health"))


def test_the_resolved_window_is_a_real_bound(store):
    moment = datetime(2026, 3, 1, 12, 0, 0)
    stale = _emit(capability="chat")
    health.resolve_on_success(WORKSPACE, provider_id=PROVIDER_ID, capability="chat", instance_id=INSTANCE_ID, now=moment - timedelta(days=30))
    fresh = _emit(capability="chat", body=RATE_BODY)
    health.resolve_on_success(WORKSPACE, provider_id=PROVIDER_ID, capability="chat", instance_id=INSTANCE_ID, now=moment)

    payload = _read(now=moment, window_days=7)

    assert _ids(payload) == [fresh], "what falls outside the window is not part of the view"
    assert stale not in _ids(payload)
    assert payload["recently_resolved_window_days"] == 7
    assert ProviderHealthEvent.get(ProviderHealthEvent.id == stale).state == "resolved", "and it is not lost"


# ---------------------------------------------------------------------------
# 7,8: provider agnosticism
# ---------------------------------------------------------------------------


def test_both_capabilities_are_readable_in_one_view(store):
    moment = datetime(2026, 3, 1, 12, 0, 0)
    embedding = _emit(capability="embedding", moment=moment)
    chat = _emit(capability="chat", body=RATE_BODY, moment=moment + timedelta(seconds=1))

    payload = _read(now=moment + timedelta(minutes=1))

    assert {incident["id"]: incident["capability"] for incident in payload["incidents"]} == {
        embedding: "embedding",
        chat: "chat",
    }


def test_an_unknown_provider_and_capability_are_served_unchanged(store):
    """No provider-specific branch exists, so a new provider needs no API change."""
    future_provider = "SomeFutureProvider"
    incident_id = _emit(capability="rerank", body=RATE_BODY, provider=future_provider, instance="instance-2")

    payload = _read()

    incident = payload["incidents"][0]
    assert incident["id"] == incident_id
    assert incident["provider_name"] == future_provider
    assert incident["capability"] == "rerank"
    assert incident["instance_id"] == "instance-2"


# ---------------------------------------------------------------------------
# 9: reading never resolves
# ---------------------------------------------------------------------------


def test_reading_an_active_incident_does_not_resolve_or_change_it(store):
    incident_id = _emit()

    first = _read()
    second = _read()

    stored = ProviderHealthEvent.get(ProviderHealthEvent.id == incident_id)
    assert stored.state == "active", "opening the page is not fixing the provider"
    assert stored.resolved_at is None
    assert stored.resolution_kind is None
    assert stored.occurrence_count == 1, "reading is not an occurrence either"
    assert _ids(first) == _ids(second) == [incident_id]


# ---------------------------------------------------------------------------
# 10,11,12: hostile payload, allowlist, query validation
# ---------------------------------------------------------------------------


def test_a_hostile_incident_cannot_put_anything_but_the_allowlist_in_the_json(store):
    hostile = (
        f"{QUOTA_BODY} key={KEY_SENTINEL} prompt='{PROMPT_SENTINEL}' chunk='{CHUNK_SENTINEL}' "
        f"{RAW_MESSAGE_SENTINEL} {PAYLOAD_SENTINEL}"
    )
    _emit(body=hostile)

    payload = _read()

    assert set(payload["incidents"][0]) == set(reader.INCIDENT_FIELDS)
    keys = _keys(payload)
    for forbidden in FORBIDDEN_KEYS:
        assert forbidden not in keys, forbidden
    rendered = json.dumps(payload, ensure_ascii=False)
    for secret in (KEY_SENTINEL, PROMPT_SENTINEL, CHUNK_SENTINEL, RAW_MESSAGE_SENTINEL, PAYLOAD_SENTINEL, hostile):
        assert secret not in rendered, secret


def test_the_incident_row_has_nowhere_to_put_a_secret_in_the_first_place(store):
    """The projection is an allowlist, and nothing else exists to expose."""
    columns = set(ProviderHealthEvent._meta.columns)
    assert set(reader.INCIDENT_FIELDS) <= columns
    assert columns - set(reader.INCIDENT_FIELDS) == UNEXPOSED_COLUMNS
    for forbidden in ("api_key", "raw_message", "prompt", "payload", "chunk", "request", "model_config"):
        assert forbidden not in columns


def test_the_projection_is_named_explicitly_rather_than_dumped_from_the_model(store):
    """A model dump would emit whatever a future migration adds."""
    _emit()
    row = ProviderHealthEvent.get()

    projected = reader._project(row)

    assert set(projected) == set(reader.INCIDENT_FIELDS)
    assert set(projected) < set(row.__data__), "the projection is a strict subset of the row"


# ---------------------------------------------------------------------------
# 13-19: who may read it
# ---------------------------------------------------------------------------


def test_an_owner_can_read_their_workspace(store):
    incident_id = _emit()

    payload, predicate = _request(WORKSPACE, user=FakeUser(OWNER))

    assert _code(payload) == 0
    assert _ids(payload) == [incident_id]
    assert payload["data"]["active_count"] == 1
    predicate.assert_called_once_with(OWNER, WORKSPACE)


def test_an_admin_can_read_their_workspace(store):
    incident_id = _emit()

    payload, predicate = _request(WORKSPACE, user=FakeUser(ADMIN))

    assert _code(payload) == 0
    assert _ids(payload) == [incident_id]
    predicate.assert_called_once_with(ADMIN, WORKSPACE)


def test_an_ordinary_member_is_denied_with_code_108(store):
    incident_id = _emit()

    payload, _predicate = _request(WORKSPACE, user=FakeUser(MEMBER), can_manage=False)

    assert _code(payload) == 108
    assert incident_id not in json.dumps(payload), "a denied caller learns nothing about the incidents"


def test_an_admin_of_another_workspace_is_denied(store):
    """Cross-tenant: administrating A is not administrating B."""
    other_incident = _emit(tenant_id=OTHER_WORKSPACE, provider="SomeFutureProvider")

    payload, predicate = _request(OTHER_WORKSPACE, user=FakeUser(OWNER), can_manage=False)

    assert _code(payload) == 108
    predicate.assert_called_once_with(OWNER, OTHER_WORKSPACE)
    assert other_incident not in json.dumps(payload)


def test_a_missing_tenant_in_the_path_is_denied(store):
    payload, _predicate = _request("", user=FakeUser(OWNER))

    assert _code(payload) == 108


def test_an_unauthenticated_caller_is_rejected_before_the_reader_runs(store):
    incident_id = _emit()

    with pytest.raises(Unauthorized):
        _request(WORKSPACE, user=FakeUser(OWNER), loader=lambda *_a, **_k: None)

    assert ProviderHealthEvent.get(ProviderHealthEvent.id == incident_id).state == "active"


def test_the_header_cannot_name_a_workspace_the_path_does_not(store):
    """`X-Tenant-Id` is a working hint; the path workspace is the subject."""
    other_incident = _emit(tenant_id=OTHER_WORKSPACE)

    payload, predicate = _request(WORKSPACE, user=FakeUser(OWNER), can_manage=False)

    predicate.assert_called_once_with(OWNER, WORKSPACE)
    assert _code(payload) == 108
    assert other_incident not in json.dumps(payload)


# ---------------------------------------------------------------------------
# 20: the pagination contract is the existing one
# ---------------------------------------------------------------------------


def test_an_unknown_query_parameter_is_refused(store):
    _emit()

    payload, _predicate = _request(WORKSPACE, "?from_day=2026-01-01", user=FakeUser(OWNER))

    assert _code(payload) == 108
    assert "from_day" in payload["message"]


def test_paging_is_bounded_by_the_existing_contract(store):
    moment = datetime(2026, 3, 1, 12, 0, 0)
    # Three DISTINCT problems: one problem seen three times is one incident.
    for offset in range(3):
        _emit(body=RATE_BODY, instance=f"instance-{offset}", moment=moment + timedelta(seconds=offset))

    first, _predicate = _request(WORKSPACE, "?limit=2", user=FakeUser(OWNER))
    assert len(first["data"]["incidents"]) == 2
    assert first["data"]["truncated"] is True
    assert first["data"]["active_count"] == 3, "the count is exact whatever the page holds"

    too_large, _predicate = _request(WORKSPACE, "?limit=5000", user=FakeUser(OWNER))
    assert _code(too_large) == 108
