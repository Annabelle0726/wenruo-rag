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
"""The datasets a conversation session retrieves from (api/apps/restful_apis/chat_api.py).

The binding is per session ("绑定到该会话上下文中"), not per assistant: the same
assistant can be asked in one session against one set of datasets and in another
against a different set. `conversation.kb_ids` stores it, and the three answers
it can hold are genuinely different:

* NULL -- the session has no binding of its own and inherits the assistant's
  datasets. That is what opening the drawer and confirming without a change
  must give.
* `[]` -- the user deliberately bound no dataset. This must NOT degrade into
  "inherit", so the column is nullable and is never defaulted to `[]`.
* a list -- the session's own set.

These tests pin the contract of the session routes: create persists and echoes
the binding, patch rebinds, `null` clears back to inherit, an omitted field
changes nothing, reading publishes `dataset_ids` (`null` when inheriting,
mirroring `_build_chat_response`), and an id the caller may not read is refused
by the same gate -- same code, 102 -- the assistant's own `dataset_ids` passes,
so a session can never be used to retrieve past the read permission.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from api.apps.restful_apis import chat_api

MEMBER_ID = "member-1"
CHAT_ID = "chat-1"
SESSION_ID = "sess-1"
ASSISTANT_DATASETS = ["kb-agent"]
READABLE = {"kb-a", "kb-b"}


class _AwaitableValue:
    def __init__(self, value):
        self._value = value

    def __await__(self):
        async def _co():
            return self._value

        return _co().__await__()


def _set_request(monkeypatch, payload):
    monkeypatch.setattr(chat_api, "get_request_json", lambda: _AwaitableValue(payload))


class _FakeConversation:
    """A conversation row, holding only the columns the routes read and write."""

    def __init__(self, **fields):
        self._fields = deepcopy(fields)

    def __getattr__(self, name):
        try:
            return self._fields[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self):
        return deepcopy(self._fields)


class _FakeConversationService:
    """The conversation table, recording exactly what the routes persist."""

    def __init__(self, rows=None):
        self.rows = {row["id"]: dict(row) for row in (rows or [])}
        self.saved = []
        self.updated = []

    def save(self, **kwargs):
        self.saved.append(dict(kwargs))
        self.rows[kwargs["id"]] = dict(kwargs)
        return True

    def get_by_id(self, session_id):
        row = self.rows.get(session_id)
        return (False, None) if row is None else (True, _FakeConversation(**row))

    def query(self, **kwargs):
        return [_FakeConversation(**row) for row in self.rows.values() if all(row.get(key) == value for key, value in kwargs.items())]

    def update_by_id(self, session_id, fields):
        if session_id not in self.rows:
            return 0
        self.updated.append(dict(fields))
        # `kb_ids: None` IS the column's inherit value, so it must be stored as
        # NULL rather than dropped from the row.
        for key, value in fields.items():
            if key not in {"update_time", "update_date"}:
                self.rows[session_id][key] = value
        return 1


class _FakeDialogService:
    def __init__(self, chat_id=CHAT_ID):
        self.dialog = SimpleNamespace(
            id=chat_id,
            tenant_id=MEMBER_ID,
            # The caller created it: chat is personally private, so `created_by`
            # is what every per-assistant route authorizes against.
            created_by=MEMBER_ID,
            status="1",
            icon="",
            kb_ids=list(ASSISTANT_DATASETS),
            prompt_config={"prologue": "hi"},
            llm_id="chat-model",
            llm_setting={},
        )

    def query(self, **kwargs):
        return [self.dialog] if kwargs.get("id") == self.dialog.id else []

    def get_by_id(self, chat_id):
        return (True, self.dialog) if chat_id == self.dialog.id else (False, None)


class _FakeKnowledgebaseService:
    """Dataset reads, recording which ids were put through the read gate."""

    def __init__(self, readable):
        self.readable = set(readable)
        self.accessed = []

    def accessible(self, kb_id, user_id, active_tenant_id=None):
        self.accessed.append((kb_id, user_id))
        return kb_id in self.readable

    def query(self, **kwargs):
        kb_id = kwargs.get("id")
        if kb_id not in self.readable:
            return []
        return [SimpleNamespace(id=kb_id, name=f"dataset {kb_id}", chunk_num=3)]


@pytest.fixture(autouse=True)
def live_membership(monkeypatch):
    """Membership is revalidated on every per-assistant route.

    `_accessible_chat` asks `UserTenantService.get_role` for the caller's LIVE
    role in the assistant's workspace, so creator identity alone cannot outlive a
    revocation. The fixtures here model one caller (`member-1`) whose assistant
    lives in its own workspace.
    """
    from api.db.services.user_service import UserTenantService

    monkeypatch.setattr(
        UserTenantService,
        "get_role",
        lambda user_id, tenant_id: "normal" if user_id == MEMBER_ID and tenant_id == MEMBER_ID else None,
    )


@pytest.fixture
def sessions(monkeypatch):
    """The session routes wired to in-memory tables, as the caller `member-1`."""
    conversations = _FakeConversationService()
    dialogs = _FakeDialogService()
    knowledgebases = _FakeKnowledgebaseService(READABLE)

    async def thread_pool_exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(chat_api, "current_user", SimpleNamespace(id=MEMBER_ID))
    monkeypatch.setattr(chat_api, "thread_pool_exec", thread_pool_exec)
    monkeypatch.setattr(chat_api, "DialogService", dialogs)
    monkeypatch.setattr(chat_api, "ConversationService", conversations)
    monkeypatch.setattr(chat_api, "KnowledgebaseService", knowledgebases)
    monkeypatch.setattr(chat_api, "validate_dataset_embedding_models", lambda _kbs: None)
    return SimpleNamespace(conversations=conversations, dialogs=dialogs, knowledgebases=knowledgebases)


def _own_session(monkeypatch):
    monkeypatch.setattr(
        chat_api,
        "_accessible_chat",
        lambda _chat_id: _AwaitableValue(SimpleNamespace(id=CHAT_ID, tenant_id=MEMBER_ID, status="1", icon="", prompt_config={"prologue": ""})),
    )


def _rows(sessions, **fields):
    row = {"id": SESSION_ID, "dialog_id": CHAT_ID, "name": "New session", "message": [], "reference": [], "user_id": MEMBER_ID}
    row.update(fields)
    sessions.conversations.rows[SESSION_ID] = row
    return row


@pytest.mark.p1
@pytest.mark.asyncio
async def test_create_session_persists_the_datasets_it_was_given(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report", "dataset_ids": ["kb-a", "kb-b"]})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 0, res
    assert sessions.conversations.saved[0]["kb_ids"] == ["kb-a", "kb-b"]
    assert res["data"]["dataset_ids"] == ["kb-a", "kb-b"]
    # `kb_ids` is the stored column name; the API publishes `dataset_ids`.
    assert "kb_ids" not in res["data"]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_create_session_without_dataset_ids_inherits_the_assistant(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report"})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 0, res
    # Nothing is written: NULL is the inherit value, so an absent field must not
    # freeze a copy of the assistant's datasets into the session.
    assert "kb_ids" not in sessions.conversations.saved[0]
    assert res["data"]["dataset_ids"] is None


@pytest.mark.p1
@pytest.mark.asyncio
async def test_create_session_can_bind_no_dataset_at_all(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report", "dataset_ids": []})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 0, res
    # `[]` is a binding, not the absence of one: it must survive as an empty
    # list so the turn retrieves from nothing instead of the assistant's set.
    assert sessions.conversations.saved[0]["kb_ids"] == []
    assert res["data"]["dataset_ids"] == []


@pytest.mark.p1
@pytest.mark.asyncio
async def test_create_session_rejects_a_dataset_the_caller_may_not_read(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report", "dataset_ids": ["kb-a", "kb-foreign"]})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 102, res
    assert res["message"] == "You don't own the dataset kb-foreign"
    assert sessions.conversations.saved == []


@pytest.mark.p1
@pytest.mark.asyncio
async def test_create_session_rejects_dataset_ids_that_are_not_a_list(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report", "dataset_ids": "kb-a"})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 102, res
    assert res["message"] == "`dataset_ids` should be a list."
    assert sessions.conversations.saved == []


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_rebinds_it(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=None)
    _set_request(monkeypatch, {"dataset_ids": ["kb-b"]})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 0, res
    assert sessions.conversations.updated[-1]["kb_ids"] == ["kb-b"]
    assert res["data"]["dataset_ids"] == ["kb-b"]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_clears_the_binding_back_to_inherit(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=["kb-a"])
    _set_request(monkeypatch, {"dataset_ids": None})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 0, res
    assert sessions.conversations.updated[-1]["kb_ids"] is None
    assert res["data"]["dataset_ids"] is None


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_without_dataset_ids_leaves_the_binding_alone(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=["kb-a"])
    _set_request(monkeypatch, {"name": "renamed"})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 0, res
    assert "kb_ids" not in sessions.conversations.updated[-1]
    assert res["data"]["dataset_ids"] == ["kb-a"]
    assert res["data"]["name"] == "renamed"


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_rejects_a_dataset_the_caller_may_not_read(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=["kb-a"])
    _set_request(monkeypatch, {"dataset_ids": ["kb-foreign"]})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 102, res
    assert res["message"] == "You don't own the dataset kb-foreign"
    assert sessions.conversations.updated == []


@pytest.mark.p1
def test_reading_a_session_publishes_dataset_ids():
    """`dataset_ids` is the read shape, and `null` is the inherit answer."""
    inheriting = chat_api._build_session_response({"id": SESSION_ID, "dialog_id": CHAT_ID, "kb_ids": None})
    bound = chat_api._build_session_response({"id": SESSION_ID, "dialog_id": CHAT_ID, "kb_ids": ["kb-a"]})
    bound_to_none = chat_api._build_session_response({"id": SESSION_ID, "dialog_id": CHAT_ID, "kb_ids": []})
    legacy_row = chat_api._build_session_response({"id": SESSION_ID, "dialog_id": CHAT_ID})

    assert inheriting["dataset_ids"] is None
    assert bound["dataset_ids"] == ["kb-a"]
    # A session bound to no dataset is not the same answer as one that inherits.
    assert bound_to_none["dataset_ids"] == []
    # A row read before the column existed inherits too.
    assert legacy_row["dataset_ids"] is None
    for payload in (inheriting, bound, bound_to_none, legacy_row):
        assert "kb_ids" not in payload
        assert payload["chat_id"] == CHAT_ID
        assert payload["messages"] == []


class _CapturingRagAgent:
    """The turn: records the datasets retrieval was handed."""

    def __init__(self):
        self.retrieved = []

    def __call__(self, dialog, _messages, _stream, **_kwargs):
        self.retrieved.append(list(dialog.kb_ids))

        async def _streamed():
            yield {"answer": "ok", "reference": {}}

        return _streamed()


class _CompletionConversations:
    def __init__(self, conv):
        self.conv = conv

    def get_by_id(self, _session_id):
        return True, self.conv

    def update_by_id(self, *_args, **_kwargs):
        return 1

    def query(self, **_kwargs):
        return [self.conv]


@pytest.fixture
def completion(monkeypatch):
    """`POST /chat/completions` wired to in-memory tables."""
    rag_agent = _CapturingRagAgent()

    async def thread_pool_exec(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(chat_api, "current_user", SimpleNamespace(id=MEMBER_ID))
    monkeypatch.setattr(chat_api, "thread_pool_exec", thread_pool_exec)
    monkeypatch.setattr(chat_api, "rag_agent", rag_agent)
    monkeypatch.setattr(chat_api, "DialogService", _FakeDialogService())

    def install(session_kb_ids):
        conv = SimpleNamespace(
            id=SESSION_ID,
            dialog_id=CHAT_ID,
            kb_ids=session_kb_ids,
            message=[{"role": "assistant", "content": "prologue"}],
            reference=[],
            to_dict=lambda: {"id": SESSION_ID, "message": []},
        )
        monkeypatch.setattr(chat_api, "ConversationService", _CompletionConversations(conv))
        return conv

    return SimpleNamespace(rag_agent=rag_agent, install=install)


async def _complete(monkeypatch):
    _set_request(
        monkeypatch,
        {
            "chat_id": CHAT_ID,
            "session_id": SESSION_ID,
            "messages": [{"role": "user", "content": "hi", "id": "msg-1"}],
            "stream": False,
        },
    )
    return await chat_api.session_completion.__wrapped__()


@pytest.mark.p1
@pytest.mark.asyncio
async def test_completion_retrieves_from_the_sessions_own_datasets(completion, monkeypatch):
    completion.install(["kb-session"])

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    # The session's binding REPLACES the assistant's -- never a union with it.
    assert completion.rag_agent.retrieved == [["kb-session"]]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_completion_without_a_session_binding_uses_the_assistants_datasets(completion, monkeypatch):
    completion.install(None)

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    assert completion.rag_agent.retrieved == [ASSISTANT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_completion_in_a_session_bound_to_no_dataset_retrieves_from_none(completion, monkeypatch):
    completion.install([])

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    # No fallback to the assistant's datasets.
    assert completion.rag_agent.retrieved == [[]]
