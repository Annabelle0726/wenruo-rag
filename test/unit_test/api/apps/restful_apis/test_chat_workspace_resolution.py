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
"""An assistant consumes its workspace's MODELS and belongs to its CREATOR alone.

Two subjects, two jobs, and conflating them is what broke this twice:

* the workspace supplies the MODELS. `tenant_id` is the workspace the caller is
  working in, because that is the tenant its chat, rerank and TTS models are
  resolved in. A NORMAL member owns no tenant, so binding the assistant to the
  member's user id (as `create` used to) made `GET /chats/<id>` answer 109,
  `PATCH` with an `llm_id` answer 102 and `/chat/title` answer 101;
* the CREATOR owns the DATA. `created_by` is the caller's user id and both the
  listing and every per-assistant route read it. A workspace shares its models
  and its datasets, never the assistants built on them - a colleague, including
  an administrator of the same workspace, must not see, edit, chat with or
  delete another member's assistant. Reading the assistant back through
  membership (`chat.tenant_id` is a workspace the caller belongs to) is exactly
  the isolation defect these tests pin.

A caller who is not the creator is refused with code **108**: 109 means "not
authenticated", and it is what these routes once answered for an assistant the
caller had just created itself.
"""

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from api.apps.restful_apis import chat_api

MEMBER_ID = "member-1"
COLLEAGUE_ID = "colleague-1"
WORKSPACE_ID = "ws-1"
CHAT_ID = "chat-1"

_DEFAULT_CHAT = {
    "id": CHAT_ID,
    "tenant_id": WORKSPACE_ID,
    "created_by": MEMBER_ID,
    "status": "1",
    "name": "member_chat",
    "description": "A helpful Assistant",
    "icon": "",
    "kb_ids": [],
    "llm_id": "ws-model",
    "llm_setting": {},
    "prompt_config": {"system": "", "prologue": "", "parameters": []},
}


def _chat_payload(**overrides):
    data = deepcopy(_DEFAULT_CHAT)
    data.update(overrides)
    return data


class _FakeDialog:
    def __init__(self, data=None):
        self._data = _chat_payload() if data is None else deepcopy(data)

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self):
        return deepcopy(self._data)


class _FakeDialogService:
    """The dialog table, recording the ownership the routes write and read."""

    def __init__(self, existing=None):
        self.saved = {}
        self.updated = {}
        self.queries = []
        self.list_calls = []
        self._existing = existing or _FakeDialog()

    def query(self, **kwargs):
        self.queries.append(kwargs)
        # A name lookup is the duplicate-name guard; anything else is an
        # existence check for a specific row.
        return [] if kwargs.get("name") else [self._existing]

    def save(self, **kwargs):
        self.saved.update(kwargs)
        return True

    def get_by_id(self, _chat_id):
        return True, self._existing

    def update_by_id(self, _chat_id, payload):
        self.updated.update(payload)
        return True

    def get_by_tenant_ids(self, joined_tenant_ids, user_id, *args, **kwargs):
        self.list_calls.append((list(joined_tenant_ids), user_id, kwargs.get("created_by")))
        return [], 0


class _AwaitableValue:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _co():
            return self._value

        return _co().__await__()


@pytest.fixture
def workspace(monkeypatch):
    """The caller `member-1`, working in `ws-1`, whose assistants it created."""
    from api.db.services.user_service import UserTenantService

    monkeypatch.setattr(UserTenantService, "get_role", lambda user, tenant: "normal" if user == MEMBER_ID and tenant == WORKSPACE_ID else None)
    state = SimpleNamespace(
        resolved=[],
        tenant_lookups=[],
        normalizations=[],
        dialogs=_FakeDialogService(),
    )

    def resolve_active_tenant_id(user_id, requested_tenant_id=None):
        state.resolved.append((user_id, requested_tenant_id))
        return WORKSPACE_ID

    def get_by_id(tenant_id):
        state.tenant_lookups.append(tenant_id)
        if tenant_id == WORKSPACE_ID:
            return True, SimpleNamespace(id=WORKSPACE_ID, llm_id="ws-model", tenant_llm_id="ws-model")
        # The member's own id is not a tenant: this is what answered 102 before.
        return False, None

    def get_model_config_by_id(tenant_id, model_type, _model_id):
        state.normalizations.append((tenant_id, model_type))
        raise LookupError("not a tenant model id")

    def resolve_model_id(tenant_id, model_type, model_name):
        state.normalizations.append((tenant_id, model_type))
        return model_name

    async def thread_pool_exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(chat_api, "current_user", SimpleNamespace(id=MEMBER_ID))
    monkeypatch.setattr(chat_api, "requested_tenant_id", lambda: WORKSPACE_ID)
    monkeypatch.setattr(chat_api, "TenantService", SimpleNamespace(resolve_active_tenant_id=resolve_active_tenant_id, get_by_id=get_by_id))
    monkeypatch.setattr(chat_api, "DialogService", state.dialogs)
    monkeypatch.setattr(chat_api, "thread_pool_exec", thread_pool_exec)
    monkeypatch.setattr(chat_api, "get_model_config_by_id", get_model_config_by_id)
    monkeypatch.setattr(chat_api, "resolve_model_id", resolve_model_id)
    return state


@pytest.fixture
def colleague(workspace):
    """The same workspace, but the assistant was created by somebody else."""
    workspace.dialogs._existing = _FakeDialog(_chat_payload(created_by=COLLEAGUE_ID))
    return workspace


def _set_request(monkeypatch, payload):
    monkeypatch.setattr(chat_api, "get_request_json", lambda: _AwaitableValue(payload))


class _Args(dict):
    """A `request.args` stand-in: the listing reads `.get` and `.getlist`."""

    def getlist(self, key):
        value = self.get(key)
        if value is None:
            return []
        return value if isinstance(value, list) else [value]


def _set_query(monkeypatch, args=None):
    monkeypatch.setattr(chat_api, "request", SimpleNamespace(args=_Args(args or {})))


# ---------------------------------------------------------------------------
# Creating: the workspace's models, the caller's data
# ---------------------------------------------------------------------------


def test_member_creates_an_assistant_in_the_resolved_workspace(workspace, monkeypatch):
    _set_request(monkeypatch, {"name": "member_chat"})

    res = asyncio.run(chat_api.create.__wrapped__())

    assert res["code"] == 0, res
    # The workspace is resolved for the member and it is the tenant row that was
    # read -- `member-1` is never looked up as a tenant.
    assert workspace.resolved == [(MEMBER_ID, WORKSPACE_ID)]
    assert workspace.tenant_lookups == [WORKSPACE_ID]
    # ... and its model defaults come from there.
    assert workspace.dialogs.saved["llm_id"] == "ws-model"
    assert workspace.dialogs.saved["tenant_llm_id"] == "ws-model"
    assert workspace.dialogs.saved["name"] == "member_chat"


def test_the_created_assistant_is_bound_to_the_workspace_and_owned_by_the_caller(workspace, monkeypatch):
    """Models come from the workspace; ownership is the creator's alone.

    Keyed on the creator's user id for BOTH, the tenant of this row is a user id
    that is not a tenant at all (109 on read, 102 on a model save, no answer at
    all). Keyed on the workspace for BOTH, every colleague can see it - the
    isolation defect. The two columns are two different answers.
    """
    _set_request(monkeypatch, {"name": "member_chat"})

    asyncio.run(chat_api.create.__wrapped__())

    assert workspace.dialogs.saved["tenant_id"] == WORKSPACE_ID
    assert workspace.dialogs.saved["created_by"] == MEMBER_ID


def test_a_client_cannot_choose_its_own_creator(workspace, monkeypatch):
    """`created_by` is server-set: the readonly strip runs before it is written."""
    _set_request(monkeypatch, {"name": "member_chat", "created_by": COLLEAGUE_ID})

    asyncio.run(chat_api.create.__wrapped__())

    assert workspace.dialogs.saved["created_by"] == MEMBER_ID


def test_the_model_pair_is_validated_in_the_workspace_not_the_caller(workspace, monkeypatch):
    _set_request(monkeypatch, {"name": "member_chat", "llm_id": "ws-model"})

    asyncio.run(chat_api.create.__wrapped__())

    assert [tenant_id for tenant_id, _field in workspace.normalizations] == [WORKSPACE_ID, WORKSPACE_ID]


def test_a_member_without_a_workspace_is_refused_cleanly(workspace, monkeypatch):
    # No membership at all: the resolver falls back to the caller's id, which is
    # no tenant. The route must answer 102, not raise an IndexError.
    monkeypatch.setattr(chat_api.TenantService, "resolve_active_tenant_id", lambda _user_id, _requested_tenant_id=None: MEMBER_ID)
    _set_request(monkeypatch, {"name": "member_chat"})

    res = asyncio.run(chat_api.create.__wrapped__())

    assert res["code"] == 102, res
    assert res["message"] == "Tenant not found!"
    assert workspace.dialogs.saved == {}


# ---------------------------------------------------------------------------
# Reading and updating: the creator alone
# ---------------------------------------------------------------------------


def test_the_creator_can_read_its_own_assistant(workspace):
    res = asyncio.run(chat_api.get_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 0, res
    assert res["data"]["id"] == CHAT_ID


def test_a_colleague_of_the_same_workspace_cannot_read_it(colleague):
    """The reported defect: the workspace's assistants were visible to everyone."""
    res = asyncio.run(chat_api.get_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res
    assert res["message"] == "no authorization"


def test_a_colleague_cannot_save_settings_on_it(colleague, monkeypatch):
    _set_request(monkeypatch, {"name": "hijacked"})

    res = asyncio.run(chat_api.patch_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res
    assert colleague.dialogs.updated == {}


def test_a_colleague_cannot_chat_with_it(colleague, monkeypatch):
    _set_request(monkeypatch, {"chat_id": CHAT_ID, "messages": [{"role": "user", "content": "hi"}]})

    res = asyncio.run(chat_api.session_completion.__wrapped__())

    assert res["code"] == 108, res


def test_a_colleague_cannot_list_its_sessions(colleague, monkeypatch):
    _set_query(monkeypatch)

    res = asyncio.run(chat_api.list_sessions.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res


def test_a_colleague_cannot_delete_it(colleague):
    res = asyncio.run(chat_api.delete_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res
    assert colleague.dialogs.updated == {}


def test_the_creator_can_save_a_model_and_it_resolves_in_the_workspace(workspace, monkeypatch):
    _set_request(monkeypatch, {"llm_id": "ws-model", "name": "renamed"})

    res = asyncio.run(chat_api.patch_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 0, res
    assert workspace.dialogs.updated["name"] == "renamed"
    # The member's user id owns no models at all; the assistant's workspace does.
    assert [tenant_id for tenant_id, _field in workspace.normalizations] == [WORKSPACE_ID, WORKSPACE_ID]


def test_an_assistant_without_a_creator_belongs_to_nobody(workspace):
    """Legacy rows are covered by the migration, not by a fallback grant.

    `created_by` NULL means the backfill has not claimed this row yet; granting
    access on that basis would re-open the hole for exactly the rows nobody owns.
    """
    workspace.dialogs._existing = _FakeDialog(_chat_payload(created_by=None))

    res = asyncio.run(chat_api.get_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res


def test_a_deleted_assistant_is_not_accessible(workspace):
    workspace.dialogs._existing = _FakeDialog(_chat_payload(status="0"))

    res = asyncio.run(chat_api.get_chat.__wrapped__(CHAT_ID))

    assert res["code"] == 108, res


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def test_the_chat_list_is_scoped_to_the_caller_and_its_workspace(workspace, monkeypatch):
    """Personally private, inside the workspace whose models it consumes."""
    _set_query(monkeypatch)

    asyncio.run(chat_api.list_chats.__wrapped__())

    assert workspace.dialogs.list_calls == [([WORKSPACE_ID], MEMBER_ID, MEMBER_ID)]


def test_the_list_still_honours_an_explicit_owner_filter(workspace, monkeypatch):
    _set_query(monkeypatch, {"owner_ids": WORKSPACE_ID})

    asyncio.run(chat_api.list_chats.__wrapped__())

    assert workspace.dialogs.list_calls == [([WORKSPACE_ID], MEMBER_ID, MEMBER_ID)]
