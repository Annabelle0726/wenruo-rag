from api.db.services.password_reset_service import reset_password, send_code
from api.utils.api_utils import get_data_error_result, get_error_permission_result, get_json_result, get_request_json, validate_request


@manager.route("/auth/reset-password-code", methods=["POST"])  # noqa: F821
@validate_request("email")
async def request_reset_code():
    req = await get_request_json()
    try:
        await send_code(req.get("email"))
        return get_json_result(data=True, message="If the account supports recovery, a code has been sent.")
    except ValueError as exc:
        return get_data_error_result(str(exc))


@manager.route("/auth/reset-password", methods=["POST"])  # noqa: F821
@validate_request("email", "code", "new_password")
async def reset():
    req = await get_request_json()
    try:
        reset_password(req.get("email"), req.get("code"), req.get("new_password"))
        return get_json_result(data=True)
    except PermissionError as exc:
        return get_error_permission_result(str(exc))
    except ValueError as exc:
        return get_data_error_result(str(exc))
