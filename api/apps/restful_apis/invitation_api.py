"""Invitation creation and public, single-use onboarding."""

from api.apps import current_user, login_required, login_user, require_tenant_admin
from api.db.services.invitation_service import InvitationService
from api.utils.api_utils import get_data_error_result, get_error_permission_result, get_json_result, get_request_json, validate_request
from common.connection_utils import construct_response


@manager.route("/tenants/<tenant_id>/invitations", methods=["POST"])  # noqa: F821
@login_required
@require_tenant_admin
@validate_request("email")
async def create_invitation(tenant_id):
    req = await get_request_json()
    try:
        result = InvitationService.create(tenant_id, current_user.id, req.get("email"), req.get("role", "normal"), req.get("department_id") or None)
        return get_json_result(data=result)
    except PermissionError as exc:
        return get_error_permission_result(str(exc))
    except ValueError as exc:
        return get_data_error_result(str(exc))


@manager.route("/invitations/<token>", methods=["GET"])  # noqa: F821
async def invitation_metadata(token):
    try:
        response = get_json_result(data=InvitationService.metadata(token))
        response.headers["Cache-Control"] = "no-store"
        return response
    except (PermissionError, ValueError) as exc:
        return get_error_permission_result(str(exc))


@manager.route("/invitations/<token>/accept", methods=["POST"])  # noqa: F821
@validate_request("nickname", "password")
async def accept_invitation(token):
    req = await get_request_json()
    try:
        user = InvitationService.accept(token, req.get("nickname"), req.get("password"))
        login_user(user)
        response = await construct_response(data=user.to_safe_dict(for_self=True), auth=user.get_id())
        response.headers["Cache-Control"] = "no-store"
        return response
    except PermissionError as exc:
        return get_error_permission_result(str(exc))
    except ValueError as exc:
        return get_data_error_result(str(exc))
