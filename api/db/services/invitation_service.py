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
    def _pending_for_email(email):
        """The newest pending invitation addressed to an email, or None.

        Used by the OAuth/OIDC path, which knows the address the identity provider
        authenticated but never sees an invitation token: without a pending invitation for
        that address there is nothing to register the account INTO, so the caller must
        refuse rather than create a workspace of its own.
        """
        email = normalize_email(email)
        return (
            TenantInvite.select()
            .where(
                fn.LOWER(TenantInvite.email) == email,
                TenantInvite.status == "pending",
                TenantInvite.expires_at > utcnow(),
            )
            .order_by(TenantInvite.create_time.desc())
            .first()
        )

    @staticmethod
    def _claim_and_create(invite, nickname, *, password=None, login_channel="password", avatar=""):
        """Claim ONE pending invitation and create its account and membership.

        The conditional UPDATE is the single-use claim: two racing redemptions cannot both
        see ``pending``, and any later failure inside the transaction rolls the claim back.
        The workspace, the role and the department all come from the invitation record — the
        caller supplies a nickname and (for password sign-up) a password, nothing else.
        """
        error, _ = validate_nickname(nickname)
        if error:
            raise ValueError(error)
        try:
            with DB.atomic():
                # Re-read inside the transaction: the row checked a moment ago may be gone.
                row = TenantInvite.get_or_none(
                    TenantInvite.id == invite.id,
                    TenantInvite.status == "pending",
                    TenantInvite.expires_at > utcnow(),
                )
                if row is None:
                    raise PermissionError("Invitation is invalid, expired, or already accepted.")
                _validate_scope(row.tenant_id, row.invited_by, row.role, row.department_id)
                claimed = (
                    TenantInvite.update(status="accepted")
                    .where(
                        TenantInvite.id == row.id,
                        TenantInvite.status == "pending",
                        TenantInvite.expires_at > utcnow(),
                    )
                    .execute()
                )
                if not claimed or User.select().where(fn.LOWER(User.email) == row.email).exists():
                    raise PermissionError("Invitation cannot be redeemed. Ask the administrator to invite again.")
                user = User.create(
                    id=get_uuid(),
                    email=row.email,
                    nickname=nickname.strip(),
                    password=password or "",
                    avatar=avatar or "",
                    access_token=get_uuid(),
                    current_tenant_id=row.tenant_id,
                    login_channel=login_channel,
                    last_login_time=utcnow(),
                )
                UserTenant.create(id=get_uuid(), user_id=user.id, tenant_id=row.tenant_id, role=row.role, department_id=row.department_id, invited_by=row.invited_by, status="1")
                return user
        except IntegrityError:
            raise PermissionError("Invitation cannot be redeemed. Ask the administrator to invite again.") from None

    @staticmethod
    @DB.connection_context()
    def metadata(token):
        invite = InvitationService._pending(token)
        department = Department.get_or_none(Department.id == invite.department_id) if invite.department_id else None
        return {"tenant_name": Tenant.get_by_id(invite.tenant_id).name, "email": invite.email, "role": invite.role, "department_name": department.name if department else None}

    @staticmethod
    @DB.connection_context()
    def accept(token, nickname, password):
        invite = InvitationService._pending(token)
        return InvitationService._claim_and_create(
            invite, nickname, password=generate_password_hash(password_value(password))
        )

    @staticmethod
    @DB.connection_context()
    def accept_oauth(email, nickname, login_channel, avatar=""):
        """Register the identity provider's address, but only into a workspace that invited it.

        There is no password: the account authenticates through the provider from now on, so
        the password column stays empty rather than holding a hash of something the user never
        chose. An unusable nickname (the provider may send none, or one this product rejects)
        falls back to the address' local part, because a missing display name must not turn an
        otherwise valid invitation into a failed registration.
        """
        invite = InvitationService._pending_for_email(email)
        if invite is None:
            raise PermissionError("No pending invitation for this address.")
        error, _ = validate_nickname(nickname)
        if error:
            nickname = str(email).split("@", 1)[0]
        return InvitationService._claim_and_create(
            invite, nickname, password="", login_channel=login_channel, avatar=avatar
        )
