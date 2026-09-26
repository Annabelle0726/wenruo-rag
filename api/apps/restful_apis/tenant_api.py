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
import asyncio
import logging
from typing import Set

from api.apps import current_user, login_required, requested_tenant_id
from api.db import UserTenantRole
from api.db.db_models import UserTenant
from api.db.services.department_service import DepartmentService
from api.db.services.user_service import TenantService, UserService, UserTenantService
from api.utils.api_utils import (
    get_data_error_result,
    get_error_permission_result,
    get_json_result,
    get_request_json,
    server_error_response,
    validate_request,
)
from api.utils.web_utils import send_invite_email
from common import settings
from common.constants import RetCode, StatusEnum
from common.misc_utils import get_uuid
from common.time_utils import delta_seconds

# Keeps strong references to fire-and-forget tasks so they are not GC'd before completion.
_background_tasks: Set[asyncio.Task] = set()

# A tenant owner is reached by creating a tenant, never by promotion, so the
# role endpoint only ever assigns these.
ASSIGNABLE_ROLES = (UserTenantRole.ADMIN, UserTenantRole.NORMAL)


def _require_membership(tenant_id):
    """Returns an error response unless the caller belongs to `tenant_id`."""
    if not UserTenantService.get_role(current_user.id, tenant_id):
        return get_error_permission_result("you are not a member of this workspace")
    return None


def _require_manager(tenant_id):
    """Returns an error response unless the caller may administer `tenant_id`."""
    if not UserTenantService.can_manage_tenant(current_user.id, tenant_id):
        return get_error_permission_result("admin role required for this workspace")
    return None


def _member_list(tenant_id):
    members = UserTenantService.get_by_tenant_id(tenant_id)
    owner_ids = [m["user_id"] for m in members if m["role"] == UserTenantRole.OWNER]
    for member in members:
        member["delta_seconds"] = delta_seconds(str(member["update_date"]))
        member["is_owner"] = member["user_id"] in owner_ids
    return members


@manager.route("/tenants/<tenant_id>/departments", methods=["GET"])  # noqa: F821
@login_required
def department_list(tenant_id):
    """The workspace's departments.

    Readable by every member: the roster filter and the dataset authorization
    dialog both need the names.
    """
    denied = _require_membership(tenant_id)
    if denied:
        return denied

    try:
        return get_json_result(data=DepartmentService.list_by_tenant_id(tenant_id))
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/departments", methods=["POST"])  # noqa: F821
@login_required
@validate_request("name")
async def create_department(tenant_id):
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    req = await get_request_json()
    name = (req["name"] or "").strip()
    if not name:
        return get_data_error_result(message="A department needs a name.")
    if DepartmentService.find_by_tenant_and_name(tenant_id, name):
        return get_data_error_result(message=f"Department '{name}' already exists.")
    parent_id = req.get("parent_id") or None
    if parent_id and not DepartmentService.get_by_tenant_and_id(tenant_id, parent_id):
        return get_data_error_result(message="The parent department does not exist in this workspace.")

    try:
        department_id = get_uuid()
        DepartmentService.save(id=department_id, tenant_id=tenant_id, name=name, parent_id=parent_id, status=StatusEnum.VALID.value)
        return get_json_result(data={"id": department_id, "name": name, "parent_id": parent_id})
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/departments/<department_id>", methods=["PUT"])  # noqa: F821
@login_required
async def update_department(tenant_id, department_id):
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    department = DepartmentService.get_by_tenant_and_id(tenant_id, department_id)
    if not department:
        return get_data_error_result(message="This department does not exist in this workspace.")

    req = await get_request_json()
    update = {}
    if "name" in req:
        name = (req["name"] or "").strip()
        if not name:
            return get_data_error_result(message="A department needs a name.")
        existing = DepartmentService.find_by_tenant_and_name(tenant_id, name)
        if existing and existing.id != department_id:
            return get_data_error_result(message=f"Department '{name}' already exists.")
        update["name"] = name
    if "parent_id" in req:
        parent_id = req["parent_id"] or None
        if parent_id == department_id:
            return get_data_error_result(message="A department cannot be its own parent.")
        if parent_id and not DepartmentService.get_by_tenant_and_id(tenant_id, parent_id):
            return get_data_error_result(message="The parent department does not exist in this workspace.")
        update["parent_id"] = parent_id

    if not update:
        return get_data_error_result(message="Nothing to update.")

    try:
        DepartmentService.update_by_id(department_id, update)
        return get_json_result(data={"id": department_id, **update})
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/departments/<department_id>", methods=["DELETE"])  # noqa: F821
@login_required
def delete_department(tenant_id, department_id):
    """Delete a department.

    Refused while members are still placed in it, rather than silently leaving
    them unassigned - a silent unassignment would drop their dataset access
    without anyone asking for it.
    """
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    if not DepartmentService.get_by_tenant_and_id(tenant_id, department_id):
        return get_data_error_result(message="This department does not exist in this workspace.")

    members = DepartmentService.count_members(tenant_id, department_id)
    if members:
        return get_data_error_result(message=f"{members} member(s) still belong to this department. Move them first.")

    try:
        DepartmentService.update_by_id(department_id, {"status": StatusEnum.INVALID.value})
        return get_json_result(data=True)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/users/<user_id>/profile", methods=["PUT"])  # noqa: F821
@login_required
async def set_member_profile(tenant_id, user_id):
    """Set a member's department and title.

    Separate from the role endpoint because these are attributes, not
    authorization: a manager may reorganise the workspace without touching who
    can administer it. `title` is free text on purpose - the org chart decides
    it, not this system.
    """
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    if UserTenantService.get_role(user_id, tenant_id) is None:
        return get_data_error_result(message="This user is not a member of the workspace.")

    req = await get_request_json()
    update = {}
    if "department_id" in req:
        department_id = req["department_id"] or None
        if department_id and not DepartmentService.get_by_tenant_and_id(tenant_id, department_id):
            return get_data_error_result(message="This department does not exist in this workspace.")
        update["department_id"] = department_id
    if "title" in req:
        title = (req["title"] or "").strip() or None
        if title and len(title) > 64:
            return get_data_error_result(message="The title is too long.")
        update["title"] = title

    if not update:
        return get_data_error_result(message="Nothing to update.")

    try:
        UserTenantService.filter_update([UserTenant.tenant_id == tenant_id, UserTenant.user_id == user_id], update)
        return get_json_result(data={"user_id": user_id, **update})
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/users", methods=["GET"])  # noqa: F821
@login_required
def user_list(tenant_id):
    """The roster of a workspace.

    Readable by every member, including a NORMAL one: the team page shows the
    roster to all and only hides the controls, and the server is what decides
    whether a control would work.
    """
    denied = _require_membership(tenant_id)
    if denied:
        return denied

    try:
        return get_json_result(data=_member_list(tenant_id))
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/users", methods=["POST"])  # noqa: F821
@login_required
@validate_request("email")
async def create(tenant_id):
    """Add an existing account to the workspace with a role.

    The account must already exist (`UserService.query`): inviting an unknown
    address is the registration-invite flow, which is not this endpoint.
    """
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    req = await get_request_json()
    invite_user_email = req["email"]
    role = req.get("role") or UserTenantRole.NORMAL
    if role not in ASSIGNABLE_ROLES:
        return get_data_error_result(message=f"role '{role}' cannot be assigned")

    department_id = req.get("department_id") or None
    if department_id and not DepartmentService.get_by_tenant_and_id(tenant_id, department_id):
        return get_data_error_result(message="This department does not exist in this workspace.")
    title = (req.get("title") or "").strip() or None

    invite_users = UserService.query(email=invite_user_email)
    if not invite_users:
        return get_data_error_result(message="User not found.")

    user_id_to_invite = invite_users[0].id
    if user_id_to_invite == current_user.id:
        return get_data_error_result(message="You are already in this team.")

    user_tenants = UserTenantService.query(user_id=user_id_to_invite, tenant_id=tenant_id)
    if user_tenants:
        user_tenant_role = user_tenants[0].role
        if user_tenant_role == UserTenantRole.OWNER:
            return get_data_error_result(message=f"{invite_user_email} is the owner of the team.")
        if user_tenant_role == role:
            return get_data_error_result(message=f"{invite_user_email} is already in the team as {user_tenant_role}.")
        # Re-inviting an existing member (including one who never accepted) is a
        # role change, which is what the caller asked for.
        UserTenantService.set_role(user_id_to_invite, tenant_id, role)
        UserTenantService.filter_update(
            [UserTenant.tenant_id == tenant_id, UserTenant.user_id == user_id_to_invite],
            {"department_id": department_id, "title": title},
        )
    else:
        UserTenantService.save(
            id=get_uuid(),
            user_id=user_id_to_invite,
            tenant_id=tenant_id,
            invited_by=current_user.id,
            role=role,
            department_id=department_id,
            title=title,
            status=StatusEnum.VALID.value,
        )

    try:
        user_name = ""
        _, user = UserService.get_by_id(current_user.id)
        if user:
            user_name = user.nickname

        def _on_invite_email_done(done_task: asyncio.Task) -> None:
            _background_tasks.discard(done_task)
            try:
                done_task.result()
            except asyncio.CancelledError:
                logging.warning("Invite email task cancelled: tenant_id=%s to=%s", tenant_id, invite_user_email)
            except Exception:
                logging.exception("Invite email task failed: tenant_id=%s to=%s", tenant_id, invite_user_email)

        task = asyncio.create_task(
            send_invite_email(
                to_email=invite_user_email,
                invite_url=settings.MAIL_FRONTEND_URL,
                tenant_id=tenant_id,
                inviter=user_name or current_user.email,
            )
        )
        if isinstance(task, asyncio.Task):
            _background_tasks.add(task)
            task.add_done_callback(_on_invite_email_done)
    except Exception as exc:
        logging.exception(f"Failed to send invite email to {invite_user_email}: {exc}")
        return get_json_result(
            data=False,
            message="Failed to send invite email.",
            code=RetCode.SERVER_ERROR,
        )

    user = invite_users[0].to_dict()
    user = {k: v for k, v in user.items() if k in ["id", "avatar", "email", "nickname"]}
    return get_json_result(data=user)


@manager.route("/tenants/<tenant_id>/users", methods=["DELETE"])  # noqa: F821
@login_required
@validate_request("user_id")
async def rm(tenant_id):
    """Remove a member, or leave the workspace.

    A manager may remove anyone but the owner; anyone may remove themselves
    (`user_id == current_user.id`) except the owner, who cannot leave the
    workspace they own - it would be left without one.
    """
    req = await get_request_json()
    user_id = req["user_id"]

    from api.db.services.workspace_member_service import remove_member

    try:
        remove_member(tenant_id, user_id, current_user.id, req.get("transfer_to_user_id"))
        return get_json_result(data=True)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage-budget", methods=["GET", "PUT"])  # noqa: F821
@login_required
async def usage_budget(tenant_id):
    """Read or update a workspace's model-call limits (OWNER/ADMIN only).

    A PUT takes any subset of `calls_per_minute`, `calls_per_day`,
    `calls_per_month` (positive integers), `tokens_per_day`,
    `tokens_per_month`, `cost_micros_per_day`, `cost_micros_per_month` (0 means
    "not enforced") and `timezone` (an IANA name, e.g. `Asia/Shanghai`, which is
    the zone the day/month counters reset in). The response echoes every limit,
    its unit, and the usage of the current period(s) separated into day and
    month, because a single summed total would double count a call that
    increments both.
    """
    from quart import request
    from api.db.services.workspace_budget_service import configure_budget

    try:
        values = await get_request_json() if request.method == "PUT" else None
        return get_json_result(data=configure_budget(tenant_id, current_user.id, values))
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/users/<user_id>/role", methods=["PUT"])  # noqa: F821
@login_required
@validate_request("role")
async def set_member_role(tenant_id, user_id):
    """Assign ADMIN or NORMAL to a member of the workspace.

    Only the workspace's managers reach this, the owner's role is never
    assignable (an owner is reached by creating a workspace, not by promotion),
    and nobody may change their own role - a manager demoting themselves would
    lock the workspace out of its own administration.
    """
    denied = _require_manager(tenant_id)
    if denied:
        return denied

    req = await get_request_json()
    role = req["role"]
    if role not in ASSIGNABLE_ROLES:
        return get_data_error_result(message=f"role '{role}' cannot be assigned")
    if user_id == current_user.id:
        return get_data_error_result(message="You cannot change your own role.")

    current_role = UserTenantService.get_role(user_id, tenant_id)
    if current_role is None:
        return get_data_error_result(message="This user is not a member of the workspace.")
    if current_role == UserTenantRole.OWNER:
        return get_data_error_result(message="The owner's role cannot be changed.")

    try:
        UserTenantService.set_role(user_id, tenant_id, role)
        return get_json_result(data={"user_id": user_id, "tenant_id": tenant_id, "role": role})
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants", methods=["GET"])  # noqa: F821
@login_required
def tenant_list():
    """Every workspace the caller belongs to, with the active one flagged."""
    try:
        tenants = UserTenantService.get_tenants_by_user_id(current_user.id)
        active_tenant_id = TenantService.resolve_active_tenant_id(current_user.id, requested_tenant_id())
        for tenant in tenants:
            tenant["delta_seconds"] = delta_seconds(str(tenant["update_date"]))
            tenant["is_active"] = tenant["tenant_id"] == active_tenant_id
        return get_json_result(data=tenants)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>", methods=["PATCH"])  # noqa: F821
@login_required
def agree(tenant_id):
    """Accept a pending invitation, and switch to that workspace."""
    try:
        role = UserTenantService.get_role(current_user.id, tenant_id)
        if role != UserTenantRole.INVITE:
            return get_data_error_result(message="There is no invitation for this workspace.")
        UserTenantService.set_role(current_user.id, tenant_id, UserTenantRole.NORMAL)
        TenantService.set_active_tenant_id(current_user.id, tenant_id)
        return get_json_result(data=True)
    except Exception as exc:
        return server_error_response(exc)
