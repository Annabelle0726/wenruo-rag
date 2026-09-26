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
"""Active workspace resolution.

`user.id` is a workspace id only for a user who holds a membership on it. These
tests pin the resolution order a request relies on: an explicitly requested
tenant (the client's ``X-Tenant-Id``), the stored selection, a membership on the
caller's own id, then the first joined tenant.
"""

from types import SimpleNamespace

import pytest

from api.db import UserTenantRole
from api.db.services.user_service import TenantService, UserService, UserTenantService
from common.exceptions import WorkspaceAccessDenied


def _resolver(monkeypatch, *, own_role, joined, stored_tenant_id=None, memberships=()):
    """Reach the resolver without a database connection.

    ``resolve_active_tenant_id`` is wrapped by ``DB.connection_context()``, so the
    undecorated function is used the same way the neighbouring dataset-access
    tests reach ``KnowledgebaseService.accessible``.
    """

    def _get_role(_cls, user_id, tenant_id):
        if tenant_id == user_id:
            return own_role
        return UserTenantRole.NORMAL if tenant_id in memberships else None

    monkeypatch.setattr(UserTenantService, "get_role", classmethod(_get_role))
    monkeypatch.setattr(TenantService, "get_joined_tenants_by_user_id", classmethod(lambda cls, user_id: joined))
    monkeypatch.setattr(
        UserService,
        "get_by_id",
        classmethod(lambda cls, user_id: (True, SimpleNamespace(id=user_id, current_tenant_id=stored_tenant_id))),
    )
    return TenantService.resolve_active_tenant_id.__func__.__wrapped__


def test_an_explicitly_requested_workspace_wins_when_the_caller_belongs_to_it(monkeypatch):
    resolve = _resolver(monkeypatch, own_role=UserTenantRole.OWNER, joined=[], memberships=("tenant-shared",))

    assert resolve(TenantService, "user-1", "tenant-shared") == "tenant-shared"


def test_a_requested_workspace_the_caller_does_not_belong_to_is_refused(monkeypatch):
    """Naming a workspace the caller is not a member of is refused, not re-targeted.

    A rejected selection MUST NOT silently fall back to another workspace and
    execute there: the caller would be served a workspace it never named, and
    after a revocation that fallback is exactly how a removed member would keep
    working. The refusal is a `WorkspaceAccessDenied`, which the API layer
    reports as HTTP 200 + code 108.
    """
    resolve = _resolver(monkeypatch, own_role=UserTenantRole.OWNER, joined=[])

    with pytest.raises(WorkspaceAccessDenied):
        resolve(TenantService, "user-1", "tenant-someone-else")


def test_the_stored_selection_is_honoured(monkeypatch):
    resolve = _resolver(
        monkeypatch,
        own_role=None,
        joined=[{"tenant_id": "tenant-first", "role": UserTenantRole.NORMAL}],
        stored_tenant_id="tenant-second",
        memberships=("tenant-second",),
    )

    assert resolve(TenantService, "user-1") == "tenant-second"


def test_a_stale_stored_selection_falls_back_instead_of_granting_access(monkeypatch):
    # The selection grants nothing on its own: once the membership is gone, the
    # stored id must not keep resolving to that tenant.
    resolve = _resolver(
        monkeypatch,
        own_role=UserTenantRole.OWNER,
        joined=[],
        stored_tenant_id="tenant-revoked",
        memberships=(),
    )

    assert resolve(TenantService, "user-1") == "user-1"


@pytest.mark.parametrize("role", [UserTenantRole.OWNER, UserTenantRole.ADMIN, UserTenantRole.NORMAL])
def test_a_membership_on_the_callers_own_id_resolves_to_its_own_workspace(monkeypatch, role):
    def _must_not_consult_joined(_cls, _user_id):
        raise AssertionError("a caller holding a membership on its own id must not fall back to a joined tenant")

    resolve = _resolver(monkeypatch, own_role=role, joined=[])
    monkeypatch.setattr(TenantService, "get_joined_tenants_by_user_id", classmethod(_must_not_consult_joined))

    assert resolve(TenantService, "tenant-self") == "tenant-self"


def test_a_member_without_a_workspace_of_its_own_resolves_to_the_tenant_it_joined(monkeypatch):
    resolve = _resolver(monkeypatch, own_role=None, joined=[{"tenant_id": "tenant-shared", "role": UserTenantRole.NORMAL}])

    assert resolve(TenantService, "user-member") == "tenant-shared"


def test_a_member_of_several_tenants_resolves_to_the_oldest_membership(monkeypatch):
    # `get_joined_tenants_by_user_id` orders by tenant create_time, so the first
    # entry is the stable choice rather than whichever row the database returns
    # first.
    resolve = _resolver(
        monkeypatch,
        own_role=None,
        joined=[
            {"tenant_id": "tenant-first", "role": UserTenantRole.NORMAL},
            {"tenant_id": "tenant-second", "role": UserTenantRole.NORMAL},
        ],
    )

    assert resolve(TenantService, "user-member") == "tenant-first"


def test_a_caller_with_no_membership_resolves_to_its_own_id(monkeypatch):
    resolve = _resolver(monkeypatch, own_role=None, joined=[])

    assert resolve(TenantService, "user-orphan") == "user-orphan"


def test_resolving_an_already_resolved_id_is_not_a_fixed_point(monkeypatch):
    """Why the resolver must never be applied to a resolved workspace id.

    ``@add_tenant_id_to_kwargs`` injects the caller's USER id, and services call
    this resolver on it. That is the whole reason it can inject the user id
    rather than the workspace: the value is a person, not a workspace.

    It cannot be "simplified" into injecting an already-resolved workspace id,
    because the workspace id of an owner IS that owner's user id
    (``user_register`` creates the tenant with ``id = user_id``), so a second
    resolution of it re-enters with the OWNER as the caller and returns the
    owner's own active workspace instead - a silent switch into a workspace the
    original caller never named.

    Here ``user-member`` belongs to ``tenant-own``, whose id is its owner's user
    id. The member resolves to ``tenant-own``; feeding that same value back
    resolves to ``tenant-second``, the workspace that owner happens to be
    working in.
    """
    memberships = {
        ("user-member", "tenant-own"): UserTenantRole.NORMAL,
        ("tenant-own", "tenant-own"): UserTenantRole.OWNER,
        ("tenant-own", "tenant-second"): UserTenantRole.NORMAL,
    }
    # Only the owner of `tenant-own` has an explicitly stored selection.
    stored = {"tenant-own": "tenant-second"}

    monkeypatch.setattr(
        UserTenantService,
        "get_role",
        classmethod(lambda _cls, user_id, tenant_id: memberships.get((user_id, tenant_id))),
    )
    monkeypatch.setattr(
        UserService,
        "get_by_id",
        classmethod(lambda _cls, user_id: (True, SimpleNamespace(id=user_id, current_tenant_id=stored.get(user_id)))),
    )
    monkeypatch.setattr(
        TenantService,
        "get_joined_tenants_by_user_id",
        classmethod(lambda _cls, user_id: [{"tenant_id": "tenant-own", "role": UserTenantRole.NORMAL}] if user_id == "user-member" else []),
    )
    resolve = TenantService.resolve_active_tenant_id.__func__.__wrapped__

    member_workspace = resolve(TenantService, "user-member")

    assert member_workspace == "tenant-own"
    # The same value, resolved again, lands somewhere else.
    assert resolve(TenantService, member_workspace) == "tenant-second"
