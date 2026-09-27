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
"""The datasets an application answers from (api/apps/restful_apis/chat_api.py).

The CHAT owns the retrieval scope, and the conversation only inherits it: every
conversation under a chat answers from the datasets that chat is bound to. The
per-session binding that used to exist ("绑定到该会话上下文中") is retired, because
a conversation pointing at a set of its own is how one application's documents
end up in another's answers - and because "the chat is bound, why am I still
being asked to pick datasets?" is what a per-conversation scope produces.

These tests pin the contract:

* a session request that says anything about datasets is REFUSED rather than
  silently ignored, so a caller that expects a per-session scope is told the
  truth instead of being answered from a different set than it asked for;
* a refused request persists nothing;
* the read shape of a session carries no dataset field at all, while the CHAT's
  own `dataset_ids` (the one the web UI counts to decide whether to prompt) is
  published unchanged, `[]` and all;
* a turn retrieves from the assistant's datasets, and a legacy
  `conversation.kb_ids` cannot widen or blank that scope.
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

    def get_by_id(self, kb_id):
        if kb_id not in self.readable:
            return False, None
        return True, SimpleNamespace(id=kb_id, name=f"dataset {kb_id}", status="1")


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
async def test_create_session_stores_no_dataset_column(sessions, monkeypatch):
    _set_request(monkeypatch, {"name": "report"})

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    assert res["code"] == 0, res
    # A conversation has no dataset set of its own: it answers from its chat's,
    # so nothing about datasets is written on the row.
    assert "kb_ids" not in sessions.conversations.saved[0]
    assert "dataset_ids" not in res["data"]
    assert "kb_ids" not in res["data"]


@pytest.mark.p1
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"name": "report", "dataset_ids": ["kb-a", "kb-b"]},
        {"name": "report", "dataset_ids": []},
        {"name": "report", "dataset_ids": None},
        {"name": "report", "kb_ids": ["kb-a"]},
    ],
)
async def test_create_session_refuses_a_dataset_field(sessions, monkeypatch, payload):
    _set_request(monkeypatch, payload)

    res = await chat_api.create_session.__wrapped__(CHAT_ID)

    # Refused rather than ignored: a caller that asked for a per-session scope
    # must not be answered from a different set without being told.
    assert res["code"] == 102, res
    assert res["message"] == "`dataset_ids` is not supported here: a conversation answers from its chat's datasets."
    assert sessions.conversations.saved == []


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_refuses_a_dataset_field(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=["kb-legacy"])
    _set_request(monkeypatch, {"dataset_ids": ["kb-b"]})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 102, res
    assert sessions.conversations.updated == []
    # The legacy column keeps its stored value: it is inert, not rewritten.
    assert sessions.conversations.rows[SESSION_ID]["kb_ids"] == ["kb-legacy"]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_patch_session_still_updates_the_fields_it_owns(sessions, monkeypatch):
    _own_session(monkeypatch)
    _rows(sessions, kb_ids=["kb-legacy"])
    _set_request(monkeypatch, {"name": "renamed", "is_pinned": True})

    res = await chat_api.update_session.__wrapped__(CHAT_ID, SESSION_ID)

    assert res["code"] == 0, res
    assert sessions.conversations.updated[-1]["name"] == "renamed"
    assert "kb_ids" not in sessions.conversations.updated[-1]
    assert res["data"]["name"] == "renamed"
    assert "dataset_ids" not in res["data"]


@pytest.mark.p1
def test_reading_a_session_publishes_no_dataset_field():
    """A session has no dataset answer to publish, whatever its row holds."""
    for row in ({"kb_ids": None}, {"kb_ids": ["kb-a"]}, {"kb_ids": []}, {}):
        payload = chat_api._build_session_response({"id": SESSION_ID, "dialog_id": CHAT_ID, **row})

        assert "dataset_ids" not in payload
        assert "kb_ids" not in payload
        assert payload["chat_id"] == CHAT_ID
        assert payload["messages"] == []


@pytest.mark.p1
def test_reading_a_chat_publishes_the_datasets_it_is_bound_to(sessions):
    """The chat's own set is the scope, and the UI reads it to know whether to prompt."""
    bound = chat_api._build_chat_response({"id": CHAT_ID, "kb_ids": ["kb-a", "kb-b"]})
    unbound = chat_api._build_chat_response({"id": CHAT_ID, "kb_ids": []})

    assert bound["dataset_ids"] == ["kb-a", "kb-b"]
    assert bound["kb_names"] == ["dataset kb-a", "dataset kb-b"]
    # `[]` is the "nothing to answer from" answer, and it is what the drawer's
    # notice is allowed to be about.
    assert unbound["dataset_ids"] == []
    for payload in (bound, unbound):
        assert "kb_ids" not in payload


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
async def test_completion_retrieves_from_the_chats_datasets(completion, monkeypatch):
    completion.install(None)

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    assert completion.rag_agent.retrieved == [ASSISTANT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_completion_ignores_a_legacy_session_binding(completion, monkeypatch):
    completion.install(["kb-other-app"])

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    # The stored per-session set must not widen the scope to another app's files.
    assert completion.rag_agent.retrieved == [ASSISTANT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_completion_ignores_a_legacy_empty_session_binding(completion, monkeypatch):
    completion.install([])

    res = await _complete(monkeypatch)

    assert res["code"] == 0, res
    # And it must not blank the scope either.
    assert completion.rag_agent.retrieved == [ASSISTANT_DATASETS]
