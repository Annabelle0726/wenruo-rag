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
"""Where a conversation's turn retrieves from (api/db/services/conversation_service.py).

The CHAT owns the retrieval scope: every conversation under it answers from the
datasets the chat is bound to. That is the whole rule, and it is what keeps one
application's files out of another's answers:

* a conversation with no dataset set of its own retrieves from the chat's;
* the legacy `conversation.kb_ids` column is NOT read, so a conversation that was
  given a set under the retired per-session binding cannot pull a different
  dataset -- another app's, possibly -- into this one;
* a per-request `kb_ids` (the bot/SDK callers) still unions onto that ONE
  request's scope;
* a chat bound to no dataset retrieves from none rather than falling back to
  anything else.

These tests drive the real `async_completion` with only its IO stubbed, so they
read the datasets the chat path was actually handed.
"""

from types import SimpleNamespace

import pytest

from api.db.services import conversation_service

CHAT_ID = "chat-1"
SESSION_ID = "sess-1"
CHAT_DATASETS = ["kb-agent"]


class _FakeDialogService:
    def __init__(self, kb_ids=None):
        self.dialog = SimpleNamespace(
            id=CHAT_ID,
            tenant_id="tenant-1",
            kb_ids=list(CHAT_DATASETS if kb_ids is None else kb_ids),
            prompt_config={"prologue": "hi"},
        )

    def query(self, **_kwargs):
        return [self.dialog]

    def get_by_id(self, _chat_id):
        return True, self.dialog


class _FakeConversation:
    """A session row, `kb_ids` included: a binding stored before this change."""

    def __init__(self, kb_ids=None):
        self.id = SESSION_ID
        self.dialog_id = CHAT_ID
        self.kb_ids = kb_ids
        self.message = [{"role": "assistant", "content": "prologue", "id": "msg-0"}]
        self.reference = []

    def to_dict(self):
        return {"id": self.id, "dialog_id": self.dialog_id, "message": list(self.message), "reference": list(self.reference)}


class _FakeConversationService:
    def __init__(self, conv):
        self.conv = conv

    def query(self, **_kwargs):
        return [self.conv]

    def save(self, **_kwargs):
        return True

    def update_by_id(self, *_args, **_kwargs):
        return 1


@pytest.fixture
def turn(monkeypatch):
    """A conversation turn whose retrieval call is captured instead of executed."""
    state = {"retrieved": []}

    def install(session_kb_ids=None, chat_kb_ids=None):
        conv = _FakeConversation(session_kb_ids)

        async def async_chat(dialog, _messages, _stream, **_kwargs):
            state["retrieved"].append(list(dialog.kb_ids))
            yield {"answer": "ok", "reference": {}}

        monkeypatch.setattr(conversation_service, "DialogService", _FakeDialogService(chat_kb_ids))
        monkeypatch.setattr(conversation_service, "ConversationService", _FakeConversationService(conv))
        monkeypatch.setattr(conversation_service, "async_chat", async_chat)
        return conv

    state["install"] = install
    return state


async def _run_turn(**kwargs):
    async for _chunk in conversation_service.async_completion("tenant-1", CHAT_ID, "question", session_id=SESSION_ID, stream=False, **kwargs):
        pass


@pytest.mark.p1
@pytest.mark.asyncio
async def test_a_conversation_retrieves_from_the_chats_datasets(turn):
    turn["install"]()

    await _run_turn()

    assert turn["retrieved"] == [CHAT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_a_legacy_session_binding_is_ignored(turn):
    turn["install"](session_kb_ids=["kb-other-app"])

    await _run_turn()

    # The retired per-session binding must not widen the scope: answering from
    # another application's dataset is the 串档 this rule exists to stop.
    assert turn["retrieved"] == [CHAT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_a_legacy_empty_session_binding_does_not_blank_the_scope(turn):
    turn["install"](session_kb_ids=[])

    await _run_turn()

    assert turn["retrieved"] == [CHAT_DATASETS]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_a_chat_with_no_dataset_retrieves_from_none(turn):
    turn["install"](chat_kb_ids=[])

    await _run_turn()

    assert turn["retrieved"] == [[]]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_an_explicit_request_binding_unions_onto_the_chats_datasets(turn):
    turn["install"]()

    await _run_turn(kb_ids=["kb-extra"])

    assert sorted(turn["retrieved"][0]) == ["kb-agent", "kb-extra"]


@pytest.mark.p1
@pytest.mark.asyncio
async def test_an_explicit_request_binding_cannot_replace_the_chats_datasets(turn):
    turn["install"](session_kb_ids=["kb-other-app"])

    await _run_turn(kb_ids=["kb-extra"])

    # The request's own scope adds to the chat's; it never drops it.
    assert sorted(turn["retrieved"][0]) == ["kb-agent", "kb-extra"]
