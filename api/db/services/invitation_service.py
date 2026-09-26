"""Workspace invitations. A bearer token grants only its recorded membership."""

import base64
import re
import secrets
from datetime import datetime, timezone

from peewee import IntegrityError, fn
from werkzeug.security import generate_password_hash

from api.db.db_models import DB, Department, Tenant, TenantInvite, User, UserTenant
from api.utils.crypt import decrypt
from api.utils.nickname_validation import validate_nickname
from common.misc_utils import get_uuid


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_email(value):
    if not isinstance(value, str) or len(value) > 255 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
        raise ValueError("A valid email is required.")
    return value.strip().lower()


def password_value(ciphertext):
    if not isinstance(ciphertext, str) or len(ciphertext) > 1024:
        raise ValueError("Invalid password.")
    encoded = decrypt(ciphertext)
    password = base64.b64decode(encoded, validate=True).decode("utf-8")
    if not 8 <= len(password) <= 128:
        raise ValueError("Password must contain 8 to 128 characters.")
    # Login hashes the RSA-decoded base64 value, not the decoded text.
    return encoded


def _validate_scope(tenant_id, inviter, role, department_id):
    if role not in ("normal", "admin"):
        raise ValueError("Invalid invitation role.")
    if department_id is not None and (not isinstance(department_id, str) or len(department_id) > 32):
        raise ValueError("Invalid department.")
    if not User.select().where(User.id == inviter, User.status == "1", User.is_active == "1").exists():
        raise PermissionError("Inviting administrator unavailable.")
    if not Tenant.select().where(Tenant.id == tenant_id, Tenant.status == "1").exists():
        raise PermissionError("Workspace unavailable.")
    if (
        not UserTenant.select()
        .where(
            UserTenant.tenant_id == tenant_id,
            UserTenant.user_id == inviter,
            UserTenant.status == "1",
            UserTenant.role.in_(("owner", "admin")),
        )
        .exists()
    ):
        raise PermissionError("Workspace administrator required.")
    if (
        department_id
        and not Department.select()
        .where(
            Department.id == department_id,
            Department.tenant_id == tenant_id,
            Department.status == "1",
        )
        .exists()
    ):
        raise PermissionError("Department unavailable in this workspace.")


class InvitationService:
    @staticmethod
    @DB.connection_context()
    def create(tenant_id, inviter, email, role="normal", department_id=None):
        email = normalize_email(email)
        with DB.atomic():
            _validate_scope(tenant_id, inviter, role, department_id)
            # Serialize invitations in a workspace, including direct memberships.
            Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
            user = User.get_or_none(fn.LOWER(User.email) == email)
            if user:
                if user.status != "1" or user.is_active != "1":
                    raise PermissionError("Account unavailable.")
                if UserTenant.select().where(UserTenant.tenant_id == tenant_id, UserTenant.user_id == user.id).exists():
                    raise ValueError("This user is already a workspace member.")
                UserTenant.create(id=get_uuid(), user_id=user.id, tenant_id=tenant_id, role=role, department_id=department_id, invited_by=inviter, status="1")
                TenantInvite.update(status="revoked").where(
                    TenantInvite.tenant_id == tenant_id,
                    TenantInvite.email == email,
                    TenantInvite.status == "pending",
                ).execute()
                return {"joined": True}
            TenantInvite.update(status="revoked").where(
                TenantInvite.tenant_id == tenant_id,
                TenantInvite.email == email,
                TenantInvite.status == "pending",
            ).execute()
            token = secrets.token_hex(16)
            TenantInvite.create(id=get_uuid(), tenant_id=tenant_id, invited_by=inviter, email=email, role=role, department_id=department_id, token=token)
            return {"joined": False, "token": token, "invite_path": f"/accept-invite?token={token}"}

    @staticmethod
    def _pending(token):
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            raise PermissionError("Invitation is invalid or expired.")
        invite = TenantInvite.get_or_none(TenantInvite.token == token, TenantInvite.status == "pending")
        if not invite or invite.expires_at <= utcnow():
            raise PermissionError("Invitation is invalid, expired, or already accepted.")
        _validate_scope(invite.tenant_id, invite.invited_by, invite.role, invite.department_id)
        return invite

    @staticmethod
    @DB.connection_context()
    def metadata(token):
        invite = InvitationService._pending(token)
        department = Department.get_or_none(Department.id == invite.department_id) if invite.department_id else None
        return {"tenant_name": Tenant.get_by_id(invite.tenant_id).name, "email": invite.email, "role": invite.role, "department_name": department.name if department else None}

    @staticmethod
    @DB.connection_context()
    def accept(token, nickname, password):
        error, _ = validate_nickname(nickname)
        if error:
            raise ValueError(error)
        encoded = password_value(password)
        try:
            with DB.atomic():
                invite = InvitationService._pending(token)
                # Conditional write is the single-use claim. Any later failure rolls it back.
                claimed = (
                    TenantInvite.update(status="accepted")
                    .where(
                        TenantInvite.id == invite.id,
                        TenantInvite.status == "pending",
                        TenantInvite.expires_at > utcnow(),
                    )
                    .execute()
                )
                if not claimed or User.select().where(fn.LOWER(User.email) == invite.email).exists():
                    raise PermissionError("Invitation cannot be redeemed. Ask the administrator to invite again.")
                user = User.create(
                    id=get_uuid(),
                    email=invite.email,
                    nickname=nickname.strip(),
                    password=generate_password_hash(encoded),
                    access_token=get_uuid(),
                    current_tenant_id=invite.tenant_id,
                    login_channel="password",
                    last_login_time=utcnow(),
                )
                UserTenant.create(id=get_uuid(), user_id=user.id, tenant_id=invite.tenant_id, role=invite.role, department_id=invite.department_id, invited_by=invite.invited_by, status="1")
                return user
        except IntegrityError:
            raise PermissionError("Invitation cannot be redeemed. Ask the administrator to invite again.") from None
