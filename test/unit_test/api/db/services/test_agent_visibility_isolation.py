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
"""An unpublished agent is its creator's alone.

`permission=team` states an intention to share an agent with the workspace;
`release` performs it. The list predicate used to honour the first without the
second, so a draft with `permission=team` appeared in every colleague's agent
list (and was runnable by them) before anyone published it. Both halves are
pinned here: the predicate's SQL, which all four list/filter queries share, and
`accessible`, which the per-agent routes use.
"""

from types import SimpleNamespace

import pytest

from api.db.db_models import UserCanvas
from api.db.services import user_service
from api.db.services.canvas_service import UserCanvasService

CREATOR_ID = "member-1"
COLLEAGUE_ID = "colleague-1"
STRANGER_ID = "stranger-1"
WORKSPACE_ID = "ws-1"
AGENT_ID = "agent-1"


class _FakeUserTenantService:
    """`user_tenant`: the colleague belongs to the workspace, the stranger does not."""

    @staticmethod
    def get_role(user_id, tenant_id):
        return "normal" if user_id in (CREATOR_ID, COLLEAGUE_ID) and tenant_id == WORKSPACE_ID else None

    @staticmethod
    def query(user_id=None, **_kwargs):
        return [SimpleNamespace(tenant_id=WORKSPACE_ID)] if user_id == COLLEAGUE_ID else []


@pytest.fixture
def agents(monkeypatch):
    # An agent carries its OWNER's user id, and a personal workspace's id IS its
    # owner's user id - which is why a team agent of this workspace is filed
    # under `ws-1`, the id the colleague's `user_tenant` rows name.
    record = {"user_id": WORKSPACE_ID, "tenant_id": WORKSPACE_ID, "permission": "team", "release": False}
    monkeypatch.setattr(UserCanvasService, "get_by_canvas_id", lambda _canvas_id: (True, dict(record)))
    monkeypatch.setattr(user_service, "UserTenantService", _FakeUserTenantService)
    return record


# ---------------------------------------------------------------------------
# The visibility predicate (shared by the list, the filters and the tag counts)
# ---------------------------------------------------------------------------


def test_the_visibility_predicate_gates_team_agents_on_release():
    query = UserCanvas.select().where(UserCanvasService._visible_to([WORKSPACE_ID], CREATOR_ID))
    sql, params = query.sql()

    assert "release" in sql
    assert "'team'" in sql or "team" in params
    assert True in params
    # The caller's own agents are visible regardless of permission or release.
    assert CREATOR_ID in params


# ---------------------------------------------------------------------------
# `accessible`, which the per-agent routes go through
# ---------------------------------------------------------------------------


def test_the_creator_reaches_its_own_unpublished_agent(agents):
    """Ownership alone is enough: a draft is always its author's."""
    agents["user_id"] = CREATOR_ID

    assert UserCanvasService.accessible(AGENT_ID, CREATOR_ID) is True


def test_a_colleague_cannot_reach_an_unpublished_team_agent(agents):
    """The requirement: unreleased means the creator only."""
    assert UserCanvasService.accessible(AGENT_ID, COLLEAGUE_ID) is False


def test_a_colleague_reaches_it_once_it_is_released(agents):
    agents["release"] = True

    assert UserCanvasService.accessible(AGENT_ID, COLLEAGUE_ID) is True


def test_a_colleague_never_reaches_a_private_agent(agents):
    """`permission=me` stays private even after a release."""
    agents["release"] = True
    agents["permission"] = "me"

    assert UserCanvasService.accessible(AGENT_ID, COLLEAGUE_ID) is False


def test_someone_outside_the_workspace_never_reaches_it(agents):
    agents["release"] = True

    assert UserCanvasService.accessible(AGENT_ID, STRANGER_ID) is False


def test_creator_identity_cannot_bypass_removed_membership(agents):
    agents["user_id"] = STRANGER_ID
    assert UserCanvasService.accessible(AGENT_ID, STRANGER_ID) is False
