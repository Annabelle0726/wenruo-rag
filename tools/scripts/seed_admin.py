"""Create an explicit deployment administrator without calling model providers.

Run inside the application container. Read the password from stdin; never put
it in an image, Git, command-line argument or startup environment.
"""
import argparse
from datetime import datetime
import json
import sys

from werkzeug.security import check_password_hash, generate_password_hash

from api.common.base64 import encode_to_base64
from api.db import UserTenantRole
from api.db.db_models import DB, Tenant, User, UserTenant
from common import settings
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format


def seed_admin(email, nickname, password, workspace_id=None):
    if not password or len(password) < 12:
        raise ValueError("Use a password of at least 12 characters.")
    if "@" not in email or not nickname.strip():
        raise ValueError("Email and nickname are required.")
    timestamp = current_timestamp()
    date = datetime_format(datetime.now())
    timestamps = dict(create_time=timestamp, update_time=timestamp, create_date=date, update_date=date)
    with DB.connection_context(), DB.atomic():
        workspace = None
        if workspace_id:
            workspace = Tenant.get_or_none(Tenant.id == workspace_id, Tenant.status == "1")
            if not workspace:
                raise ValueError("The requested workspace does not exist or is inactive.")
            if not UserTenant.select().where(
                UserTenant.tenant_id == workspace_id,
                UserTenant.role == UserTenantRole.OWNER,
                UserTenant.status == "1",
            ).exists():
                raise ValueError("The existing workspace must retain its owner.")

        user = User.get_or_none(User.email == email)
        created = user is None
        if user:
            # Refuse to promote a coincidentally matching account or reset a password.
            if user.login_channel != "deployment-seed" or not user.is_superuser or user.status != "1":
                raise ValueError("This email belongs to an account not created by this seed.")
            if not check_password_hash(user.password, encode_to_base64(password)):
                raise ValueError("Existing seed password differs; use the normal password-change flow.")
            if not UserTenant.select().where(
                UserTenant.user_id == user.id, UserTenant.tenant_id == user.id,
                UserTenant.role == UserTenantRole.OWNER, UserTenant.status == "1",
            ).exists():
                raise ValueError("The seed account's own workspace is inconsistent.")
        else:
            user_id = get_uuid()
            User.create(
                id=user_id, email=email, nickname=nickname,
                password=generate_password_hash(encode_to_base64(password)), login_channel="deployment-seed",
                is_superuser=True, language="Chinese", status="1",
                current_tenant_id=workspace_id or user_id, **timestamps,
            )
            Tenant.create(
                id=user_id, name="Wenruo Administration",
                llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="",
                parser_ids=settings.PARSERS, **timestamps,
            )
            UserTenant.create(
                id=get_uuid(), user_id=user_id, tenant_id=user_id,
                invited_by=user_id, role=UserTenantRole.OWNER, **timestamps,
            )
            user = User.get_by_id(user_id)

        membership_created = False
        if workspace:
            membership = UserTenant.get_or_none(
                UserTenant.user_id == user.id, UserTenant.tenant_id == workspace_id,
            )
            if membership:
                if membership.role not in (UserTenantRole.ADMIN, UserTenantRole.OWNER) or membership.status != "1":
                    raise ValueError("Existing membership is not an active administrator; no implicit promotion.")
            else:
                UserTenant.create(
                    id=get_uuid(), user_id=user.id, tenant_id=workspace_id,
                    invited_by=workspace_id, role=UserTenantRole.ADMIN, **timestamps,
                )
                membership_created = True
        return {
            "created": created, "membership_created": membership_created,
            "email": email, "user_id": user.id, "is_superuser": True,
            "own_workspace_role": "owner",
            "existing_workspace_role": "admin" if workspace else None,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="admin@wenruo.local")
    parser.add_argument("--nickname", default="Wenruo Administrator")
    parser.add_argument("--workspace-id", help="Grant ADMIN on this existing workspace; preserve its OWNER.")
    args = parser.parse_args()
    password = sys.stdin.read().rstrip("\r\n")
    settings.init_settings()
    print(json.dumps(seed_admin(args.email, args.nickname, password, args.workspace_id)))


if __name__ == "__main__":
    main()
