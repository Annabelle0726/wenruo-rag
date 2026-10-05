#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
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
import logging
import re
import secrets
from datetime import datetime

from quart import redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from api.apps.auth import get_auth_client
from api.db import FileType, UserTenantRole
from api.db.services.file_service import FileService
from api.db.services.user_service import TenantService, UserService, UserTenantService
from api.db.joint_services.tenant_model_service import ensure_tenant_model_ids_for_params
from common.time_utils import current_timestamp, datetime_format, get_format_time
from common.misc_utils import download_img, get_uuid
from common.constants import RetCode
from common.connection_utils import construct_response
from api.utils.api_utils import (
    get_data_error_result,
    get_error_permission_result,
    get_json_result,
    get_request_json,
    server_error_response,
    validate_request,
)
from api.utils.nickname_validation import validate_nickname
from api.utils.crypt import decrypt
from api.apps import login_required, current_user, login_user, logout_user, requested_tenant_id

from common import settings


@manager.route("/auth/login", methods=["POST"])  # noqa: F821
async def login():
    """
    User login endpoint.
    ---
    tags:
      - User
    parameters:
      - in: body
        name: body
        description: Login credentials.
        required: true
        schema:
          type: object
          properties:
            email:
              type: string
              description: User email.
            password:
              type: string
              description: User password.
    responses:
      200:
        description: Login successful.
        schema:
          type: object
      401:
        description: Authentication failed.
        schema:
          type: object
    """
    json_body = await get_request_json()
    if not json_body:
        logging.warning("Login failed: invalid or empty JSON body")
        return get_json_result(data=False, code=RetCode.AUTHENTICATION_ERROR, message="Unauthorized!")

    email = json_body.get("email", "")

    users = UserService.query(email=email)
    if not users:
        logging.warning("Login failed: email not registered")
        return get_json_result(
            data=False,
            code=RetCode.AUTHENTICATION_ERROR,
            message=f"Email: {email} is not registered!",
        )

    password = json_body.get("password")
    try:
        password = decrypt(password)
    except BaseException:
        logging.warning("Login failed: password decryption error")
        return get_json_result(data=False, code=RetCode.SERVER_ERROR, message="Fail to crypt password")

    user = UserService.query_user(email, password)

    if user and hasattr(user, "is_active") and user.is_active == "0":
        logging.warning("Login failed: disabled account for user_id=%s", user.id)
        return get_json_result(
            data=False,
            code=RetCode.FORBIDDEN,
            message="This account has been disabled, please contact the administrator!",
        )
    elif user:
        user.access_token = get_uuid()
        login_user(user)
        user.last_login_time = get_format_time()
        user.update_time = current_timestamp()
        user.update_date = datetime_format(datetime.now())
        user.save()
        logging.info("Login successful: user_id=%s", user.id)
        msg = "Welcome back!"

        return await construct_response(data=user.to_safe_dict(for_self=True), auth=user.get_id(), message=msg)
    else:
        logging.warning("Login failed: wrong credentials")
        return get_json_result(
            data=False,
            code=RetCode.AUTHENTICATION_ERROR,
            message="Email and password do not match!",
        )


@manager.route("/auth/login/channels", methods=["GET"])  # noqa: F821
async def get_login_channels():
    """
    Get all supported authentication channels.
    """
    try:
        channels = []
        for channel, config in settings.OAUTH_CONFIG.items():
            channels.append(
                {
                    "channel": channel,
                    "display_name": config.get("display_name", channel.title()),
                    "icon": config.get("icon", "sso"),
                }
            )
        return get_json_result(data=channels)
    except Exception as e:
        logging.exception(e)
        return get_json_result(data=[], message=f"Load channels failure, error: {str(e)}", code=RetCode.EXCEPTION_ERROR)


@manager.route("/auth/login/<channel>", methods=["GET"])  # noqa: F821
async def oauth_login(channel):
    channel_config = settings.OAUTH_CONFIG.get(channel)
    if not channel_config:
        raise ValueError(f"Invalid channel name: {channel}")
    auth_cli = get_auth_client(channel_config)

    state = get_uuid()
    session["oauth_state"] = state
    auth_url = auth_cli.get_authorization_url(state)
    logging.info("OAuth login initiated: channel='%s'", channel)
    return redirect(auth_url)


@manager.route("/auth/oauth/<channel>/callback", methods=["GET"])  # noqa: F821
async def oauth_callback(channel):
    """
    Handle the OAuth/OIDC callback for various channels dynamically.
    """
    try:
        channel_config = settings.OAUTH_CONFIG.get(channel)
        if not channel_config:
            raise ValueError(f"Invalid channel name: {channel}")
        auth_cli = get_auth_client(channel_config)

        # Check the state
        state = request.args.get("state")
        if not state or state != session.get("oauth_state"):
            return redirect("/?error=invalid_state")
        session.pop("oauth_state", None)

        # Obtain the authorization code
        code = request.args.get("code")
        if not code:
            return redirect("/?error=missing_code")

        # Exchange authorization code for access token
        if hasattr(auth_cli, "async_exchange_code_for_token"):
            token_info = await auth_cli.async_exchange_code_for_token(code)
        else:
            token_info = auth_cli.exchange_code_for_token(code)
        access_token = token_info.get("access_token")
        if not access_token:
            return redirect("/?error=token_failed")

        id_token = token_info.get("id_token")

        # Fetch user info
        if hasattr(auth_cli, "async_fetch_user_info"):
            user_info = await auth_cli.async_fetch_user_info(access_token, id_token=id_token)
        else:
            user_info = auth_cli.fetch_user_info(access_token, id_token=id_token)
        if not user_info.email:
            return redirect("/?error=email_missing")

        # Login or register
        users = UserService.query(email=user_info.email)
        user_id = get_uuid()

        if not users:
            if not getattr(settings, "OAUTH_AUTO_REGISTER", True):
                logging.warning("OAuth/OIDC JIT registration blocked: email=%s, channel=%s", user_info.email, channel)
                return redirect("/?error=registration_disabled")
            try:
                try:
                    avatar = await download_img(user_info.avatar_url)
                except Exception as e:
                    logging.exception(e)
                    avatar = ""

                users = user_register(
                    user_id,
                    {
                        "access_token": get_uuid(),
                        "email": user_info.email,
                        "avatar": avatar,
                        "nickname": user_info.nickname,
                        "login_channel": channel,
                        "last_login_time": get_format_time(),
                        "is_superuser": False,
                    },
                )

                if not users:
                    raise Exception(f"Failed to register {user_info.email}")
                if len(users) > 1:
                    raise Exception(f"Same email: {user_info.email} exists!")

                # Try to log in
                user = users[0]
                login_user(user)
                return redirect(f"/?auth={user.get_id()}")

            except Exception as e:
                rollback_user_registration(user_id)
                logging.exception(e)
                return redirect(f"/?error={str(e)}")

        # User exists, try to log in
        user = users[0]
        user.access_token = get_uuid()
        if user and hasattr(user, "is_active") and user.is_active == "0":
            return redirect("/?error=user_inactive")

        login_user(user)
        user.save()
        return redirect(f"/?auth={user.get_id()}")
    except Exception as e:
        logging.exception(e)
        return redirect(f"/?error={str(e)}")


@manager.route("/auth/logout", methods=["POST"])  # noqa: F821
@login_required
async def log_out():
    """
    User logout endpoint.
    ---
    tags:
      - User
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Logout successful.
        schema:
          type: object
    """
    user = current_user._get_current_object() if hasattr(current_user, "_get_current_object") else current_user
    user_id = user.id
    user.access_token = f"INVALID_{secrets.token_hex(16)}"
    saved = user.save()
    if saved == 0:
        logging.error("Logout failed to persist access token update: user_id=%s", user_id)
        return get_json_result(code=RetCode.SERVER_ERROR, data=False, message="Failed to update access token")
    logout_user()
    logging.info("Logout: user_id=%s, access_token invalidated", user_id)
    return get_json_result(data=True)


@manager.route("/users/me", methods=["PATCH"])  # noqa: F821
@login_required
async def setting_user():
    """
    Update user settings.
    ---
    tags:
      - User
    security:
      - ApiKeyAuth: []
    parameters:
      - in: body
        name: body
        description: User settings to update.
        required: true
        schema:
          type: object
          properties:
            nickname:
              type: string
              description: New nickname.
            email:
              type: string
              description: New email.
    responses:
      200:
        description: Settings updated successfully.
        schema:
          type: object
    """
    update_dict = {}
    request_data = await get_request_json()
    password_changed = False
    if request_data.get("password"):
        new_password = request_data.get("new_password")
        if not check_password_hash(current_user.password, decrypt(request_data["password"])):
            return get_json_result(
                data=False,
                code=RetCode.AUTHENTICATION_ERROR,
                message="Password error!",
            )

        if new_password:
            update_dict["password"] = generate_password_hash(decrypt(new_password))
            update_dict["access_token"] = f"INVALID_{secrets.token_hex(16)}"
            password_changed = True

    for k in request_data.keys():
        if k in [
            "password",
            "new_password",
            "email",
            "status",
            "is_superuser",
            "login_channel",
            "is_anonymous",
            "is_active",
            "is_authenticated",
            "last_login_time",
        ]:
            continue
        update_dict[k] = request_data[k]

    if "nickname" in update_dict:
        error_message, error_code = validate_nickname(update_dict["nickname"])
        if error_message:
            return get_json_result(data=False, message=error_message, code=error_code)
        update_dict["nickname"] = update_dict["nickname"].strip()

    try:
        UserService.update_by_id(current_user.id, update_dict)
        if password_changed:
            logout_user()
        return get_json_result(data=True)
    except Exception as e:
        logging.exception(e)
        return get_json_result(data=False, message="Update failure!", code=RetCode.EXCEPTION_ERROR)


@manager.route("/users/me", methods=["GET"])  # noqa: F821
@login_required
async def user_profile():
    """
    Get user profile information.
    ---
    tags:
      - User
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: User profile retrieved successfully.
        schema:
          type: object
          properties:
            id:
              type: string
              description: User ID.
            nickname:
              type: string
              description: User nickname.
            email:
              type: string
              description: User email.
    """
    profile = current_user.to_safe_dict(for_self=True)
    # The caller's role in the tenant their model configuration comes from:
    # their own for anyone holding a membership on their own id, and the tenant
    # they joined for a member who owns none. Only the role itself is exposed: a
    # derived "can manage" boolean would duplicate the server-side hierarchy
    # rule in the payload.
    config_tenant_id = TenantService.resolve_active_tenant_id(current_user.id)
    profile["role"] = UserTenantService.get_role(current_user.id, config_tenant_id)
    return get_json_result(data=profile)


def rollback_user_registration(user_id):
    try:
        UserService.delete_by_id(user_id)
    except Exception:
        pass
    try:
        TenantService.delete_by_id(user_id)
    except Exception:
        pass
    try:
        u = UserTenantService.query(tenant_id=user_id)
        if u:
            UserTenantService.delete_by_id(u[0].id)
    except Exception:
        pass


def user_register(user_id, user):
    user["id"] = user_id
    tenant = {
        "id": user_id,
        "name": user["nickname"] + "‘s Kingdom",
        "llm_id": "",
        "embd_id": "",
        "asr_id": "",
        "parser_ids": "",
        "img2txt_id": "",
        "rerank_id": "",
    }
    usr_tenant = {
        "tenant_id": user_id,
        "user_id": user_id,
        "invited_by": user_id,
        "role": UserTenantRole.OWNER,
    }
    file_id = get_uuid()
    file = {
        "id": file_id,
        "parent_id": file_id,
        "tenant_id": user_id,
        "created_by": user_id,
        "name": "/",
        "type": FileType.FOLDER.value,
        "size": 0,
        "location": "",
    }

    # tenant_llm = get_init_tenant_llm(user_id)

    if not UserService.save(**user):
        return None
    TenantService.insert(**tenant)
    UserTenantService.insert(**usr_tenant)
    # TenantLLMService.insert_many(tenant_llm)
    FileService.insert(file)
    return UserService.query(email=user["email"])


@manager.route("/users", methods=["POST"])  # noqa: F821
@validate_request("nickname", "email", "password")
async def user_add():
    """
    Register a new user.
    ---
    tags:
      - User
    parameters:
      - in: body
        name: body
        description: Registration details.
        required: true
        schema:
          type: object
          properties:
            nickname:
              type: string
              description: User nickname.
            email:
              type: string
              description: User email.
            password:
              type: string
              description: User password.
    responses:
      200:
        description: Registration successful.
        schema:
          type: object
    """

    if not settings.REGISTER_ENABLED:
        return get_json_result(
            data=False,
            message="User registration is disabled!",
            code=RetCode.OPERATING_ERROR,
        )

    req = await get_request_json()
    email_address = req["email"]

    # Validate the email address
    if not re.match(r"^[\w\._-]+@([\w_-]+\.)+[\w-]{2,}$", email_address):
        return get_json_result(
            data=False,
            message=f"Invalid email address: {email_address}!",
            code=RetCode.OPERATING_ERROR,
        )

    # Check if the email address is already used
    if UserService.query(email=email_address):
        return get_json_result(
            data=False,
            message=f"Email: {email_address} has already registered!",
            code=RetCode.OPERATING_ERROR,
        )

    # Construct user info data
    nickname = req["nickname"]
    error_message, error_code = validate_nickname(nickname)
    if error_message:
        return get_json_result(data=False, message=error_message, code=error_code)
    nickname = nickname.strip()

    user_dict = {
        "access_token": get_uuid(),
        "email": email_address,
        "nickname": nickname,
        "password": decrypt(req["password"]),
        "login_channel": "password",
        "last_login_time": get_format_time(),
        "is_superuser": False,
    }

    user_id = get_uuid()
    try:
        users = user_register(user_id, user_dict)
        if not users:
            raise Exception(f"Fail to register {email_address}.")
        if len(users) > 1:
            raise Exception(f"Same email: {email_address} exists!")
        user = users[0]
        login_user(user)
        return await construct_response(
            data=user.to_safe_dict(for_self=True),
            auth=user.get_id(),
            message=f"{nickname}, welcome aboard!",
        )
    except Exception as e:
        rollback_user_registration(user_id)
        logging.exception(e)
        return get_json_result(
            data=False,
            message=f"User registration failure, error: {str(e)}",
            code=RetCode.EXCEPTION_ERROR,
        )


@manager.route("/users/me/models", methods=["GET"])  # noqa: F821
@login_required
async def tenant_info():
    """
    Get tenant information.
    ---
    tags:
      - Tenant
    security:
      - ApiKeyAuth: []
    responses:
      200:
        description: Tenant information retrieved successfully.
        schema:
          type: object
          properties:
            tenant_id:
              type: string
              description: Tenant ID.
            name:
              type: string
              description: Tenant name.
            llm_id:
              type: string
              description: LLM ID.
            embd_id:
              type: string
              description: Embedding model ID.

    The response describes the caller's ACTIVE workspace: the one they selected,
    or the tenant they joined when they own none. It is not restricted to a
    tenant the caller owns - a member has no workspace of their own, and
    `get_info_by` (which answers "which tenant do I own") answers nothing for
    them, which is what used to surface as `102 Tenant not found!`.
    """
    try:
        active_tenant_id = TenantService.resolve_active_tenant_id(current_user.id, requested_tenant_id())
        found, tenant = TenantService.get_by_id(active_tenant_id)
        if not found:
            return get_data_error_result(message="Tenant not found!")
        info = tenant.to_dict()
        # The frontend keys everything off `tenant_id`; the model's primary key
        # is `id`, and `get_info_by` exposed it under this alias.
        info["tenant_id"] = tenant.id
        info["role"] = UserTenantService.get_role(current_user.id, active_tenant_id)
        return get_json_result(data=info)
    except Exception as e:
        return server_error_response(e)


@manager.route("/users/me/tenant", methods=["PUT"])  # noqa: F821
@login_required
@validate_request("tenant_id")
async def set_active_tenant():
    """Switch the caller's active workspace.

    The target can be any tenant the caller belongs to, and the choice is
    persisted so subsequent requests without an ``X-Tenant-Id`` header resolve to
    the same workspace. A tenant the caller does not belong to is refused here
    rather than silently ignored, so the switcher can report a real error.
    """
    req = await get_request_json()
    tenant_id = req["tenant_id"]
    try:
        TenantService.set_active_tenant_id(current_user.id, tenant_id)
        return get_json_result(data={"tenant_id": tenant_id})
    except ValueError as e:
        return get_error_permission_result(str(e))
    except Exception as e:
        return server_error_response(e)


@manager.route("/users/me/models", methods=["PATCH"])  # noqa: F821
@login_required
@validate_request("tenant_id", "asr_id", "embd_id", "img2txt_id", "llm_id")
async def set_tenant_info():
    """
    Update tenant information.
    ---
    tags:
      - Tenant
    security:
      - ApiKeyAuth: []
    parameters:
      - in: body
        name: body
        description: Tenant information to update.
        required: true
        schema:
          type: object
          properties:
            tenant_id:
              type: string
              description: Workspace to update; the caller must hold OWNER or ADMIN on it (see GET /users/me/tenant).
            llm_id:
              type: string
              description: LLM ID.
            embd_id:
              type: string
              description: Embedding model ID.
            asr_id:
              type: string
              description: ASR model ID.
            img2txt_id:
              type: string
              description: Image to Text model ID.
    responses:
      200:
        description: Tenant information updated successfully.
        schema:
          type: object
    """
    req = await get_request_json()
    try:
        tid = req.pop("tenant_id")
        # GET /users/me/models answers the caller's ACTIVE workspace, which is
        # not the caller's own id whenever it is working in a shared one, so the
        # write accepts any workspace the caller administers -- the same
        # predicate @require_tenant_admin applies. Comparing against
        # current_user.id instead refused a legitimate echo of that id with a
        # permission error and left a shared workspace unconfigurable.
        if not UserTenantService.can_manage_tenant(current_user.id, tid):
            logging.warning("IDOR attempt blocked: user %s requested tenant_id %s on %s", current_user.id, tid, request.path)
            return get_error_permission_result("admin role required for this tenant")
        update_dict = ensure_tenant_model_ids_for_params(tid, req)
        TenantService.update_by_id(tid, update_dict)
        return get_json_result(data=True)
    except Exception as e:
        return server_error_response(e)
