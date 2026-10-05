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
import hashlib
from datetime import datetime
import logging

import peewee
from werkzeug.security import generate_password_hash, check_password_hash

from api.db import UserTenantRole
from api.db.db_models import DB, UserTenant
from api.db.db_models import User, Tenant, Department
from peewee import JOIN
from api.db.services.common_service import CommonService
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format
from common.constants import StatusEnum
from common import settings


class UserService(CommonService):
    """Service class for managing user-related database operations.

    This class extends CommonService to provide specialized functionality for user management,
    including authentication, user creation, updates, and deletions.

    Attributes:
        model: The User model class for database operations.
    """

    model = User

    @classmethod
    @DB.connection_context()
    def query(cls, cols=None, reverse=None, order_by=None, **kwargs):
        if "access_token" in kwargs:
            access_token = kwargs["access_token"]

            # Reject empty, None, or whitespace-only access tokens
            if not access_token or not str(access_token).strip():
                logging.warning("UserService.query: Rejecting empty access_token query")
                return cls.model.select().where(cls.model.id == "INVALID_EMPTY_TOKEN")  # Returns empty result

            # Reject tokens that are too short (should be UUID, 32+ chars)
            if len(str(access_token).strip()) < 32:
                logging.warning(f"UserService.query: Rejecting short access_token query: {len(str(access_token))} chars")
                return cls.model.select().where(cls.model.id == "INVALID_SHORT_TOKEN")  # Returns empty result

            # Reject tokens that start with "INVALID_" (from logout)
            if str(access_token).startswith("INVALID_"):
                logging.warning("UserService.query: Rejecting invalidated access_token")
                return cls.model.select().where(cls.model.id == "INVALID_LOGOUT_TOKEN")  # Returns empty result

        # Call parent query method for valid requests
        return super().query(cols=cols, reverse=reverse, order_by=order_by, **kwargs)

    @classmethod
    @DB.connection_context()
    def filter_by_id(cls, user_id):
        """Retrieve a user by their ID.

        Args:
            user_id: The unique identifier of the user.

        Returns:
            User object if found, None otherwise.
        """
        try:
            user = cls.model.select().where(cls.model.id == user_id).get()
            return user
        except peewee.DoesNotExist:
            return None

    @classmethod
    @DB.connection_context()
    def query_user(cls, email, password):
        """Authenticate a user with email and password.

        Args:
            email: User's email address.
            password: User's password in plain text.

        Returns:
            User object if authentication successful, None otherwise.
        """
        user = cls.model.select().where((cls.model.email == email), (cls.model.status == StatusEnum.VALID.value)).first()
        if user and check_password_hash(str(user.password), password):
            return user
        else:
            return None

    @classmethod
    @DB.connection_context()
    def query_user_by_email(cls, email):
        users = cls.model.select().where((cls.model.email == email))
        return list(users)

    @classmethod
    @DB.connection_context()
    def save(cls, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = get_uuid()
        if "password" in kwargs:
            kwargs["password"] = generate_password_hash(str(kwargs["password"]))

        current_ts = current_timestamp()
        current_date = datetime_format(datetime.now())

        kwargs["create_time"] = current_ts
        kwargs["create_date"] = current_date
        kwargs["update_time"] = current_ts
        kwargs["update_date"] = current_date
        obj = cls.model(**kwargs).save(force_insert=True)
        return obj

    @classmethod
    @DB.connection_context()
    def delete_user(cls, user_ids, update_user_dict):
        with DB.atomic():
            cls.model.update({"status": 0}).where(cls.model.id.in_(user_ids)).execute()

    @classmethod
    @DB.connection_context()
    def update_user(cls, user_id, user_dict):
        with DB.atomic():
            if user_dict:
                user_dict["update_time"] = current_timestamp()
                user_dict["update_date"] = datetime_format(datetime.now())
                cls.model.update(user_dict).where(cls.model.id == user_id).execute()

    @classmethod
    @DB.connection_context()
    def update_user_password(cls, user_id, new_password):
        with DB.atomic():
            update_dict = {"password": generate_password_hash(str(new_password)), "update_time": current_timestamp(), "update_date": datetime_format(datetime.now())}
            cls.model.update(update_dict).where(cls.model.id == user_id).execute()

    @classmethod
    @DB.connection_context()
    def is_admin(cls, user_id):
        return cls.model.select().where(cls.model.id == user_id, cls.model.is_superuser == 1).count() > 0

    @classmethod
    @DB.connection_context()
    def get_all_users(cls):
        users = cls.model.select().order_by(cls.model.email)
        return list(users)


class TenantService(CommonService):
    """Service class for managing tenant-related database operations.

    This class extends CommonService to provide functionality for tenant management,
    including tenant information retrieval and credit management.

    Attributes:
        model: The Tenant model class for database operations.
    """

    model = Tenant

    @classmethod
    @DB.connection_context()
    def get_info_by(cls, user_id):
        fields = [
            cls.model.id.alias("tenant_id"),
            cls.model.name,
            cls.model.llm_id,
            cls.model.tenant_llm_id,
            cls.model.embd_id,
            cls.model.tenant_embd_id,
            cls.model.rerank_id,
            cls.model.tenant_rerank_id,
            cls.model.asr_id,
            cls.model.tenant_asr_id,
            cls.model.img2txt_id,
            cls.model.tenant_img2txt_id,
            cls.model.tts_id,
            cls.model.tenant_tts_id,
            cls.model.ocr_id,
            cls.model.tenant_ocr_id,
            cls.model.parser_ids,
            UserTenant.role,
        ]
        return list(
            cls.model.select(*fields)
            .join(UserTenant, on=((cls.model.id == UserTenant.tenant_id) & (UserTenant.user_id == user_id) & (UserTenant.status == StatusEnum.VALID.value) & (UserTenant.role == UserTenantRole.OWNER)))
            .where(cls.model.status == StatusEnum.VALID.value)
            .dicts()
        )

    @classmethod
    @DB.connection_context()
    def get_joined_tenants_by_user_id(cls, user_id):
        fields = [cls.model.id.alias("tenant_id"), cls.model.name, cls.model.llm_id, cls.model.embd_id, cls.model.asr_id, cls.model.img2txt_id, UserTenant.role]
        return list(
            cls.model.select(*fields)
            .join(
                UserTenant,
                on=(
                    (cls.model.id == UserTenant.tenant_id)
                    & (UserTenant.user_id == user_id)
                    & (UserTenant.status == StatusEnum.VALID.value)
                    & (UserTenant.role.in_([UserTenantRole.NORMAL, UserTenantRole.ADMIN]))
                ),
            )
            .where(cls.model.status == StatusEnum.VALID.value)
            .order_by(cls.model.create_time)
            .dicts()
        )

    @classmethod
    @DB.connection_context()
    def resolve_active_tenant_id(cls, user_id, requested_tenant_id=None):
        """The workspace `user_id` is operating in.

        Resolution order:

        1. `requested_tenant_id` (the client's ``X-Tenant-Id``), when the caller
           actually holds a membership on it — a request must never be able to
           name a workspace the caller does not belong to;
        2. the selection stored on the user row (``user.current_tenant_id``);
        3. the first tenant the caller joined as NORMAL or ADMIN;
        4. the caller's own id, which is their workspace only when they hold a
           membership on it (the convention for an owner, see
           `get_info_by`).

        This replaces the previous assumption that ``user.id`` IS the tenant id.
        A member with no tenant of their own therefore resolves to the shared
        tenant it joined, while an owner and an admin keep resolving to their
        own — so no existing caller changes behaviour.
        """
        if requested_tenant_id:
            membership = UserTenantService.get_role(user_id, requested_tenant_id)
            if membership:
                return requested_tenant_id
            from common.exceptions import WorkspaceAccessDenied

            raise WorkspaceAccessDenied("您已无权访问此工作区")

        _, user = UserService.get_by_id(user_id)
        if user and user.current_tenant_id and UserTenantService.get_role(user_id, user.current_tenant_id):
            return user.current_tenant_id

        if UserTenantService.get_role(user_id, user_id):
            return user_id

        joined = cls.get_joined_tenants_by_user_id(user_id)
        return joined[0]["tenant_id"] if joined else user_id

    @classmethod
    @DB.connection_context()
    def resolve_config_tenant_id(cls, user_id, owner_tenant_id):
        """Validate a caller against the resource's authoritative workspace."""
        from common.exceptions import WorkspaceAccessDenied

        if not owner_tenant_id or UserTenantService.get_role(user_id, owner_tenant_id) not in (UserTenantRole.OWNER, UserTenantRole.ADMIN, UserTenantRole.NORMAL):
            raise WorkspaceAccessDenied("您已无权访问此工作区")
        return owner_tenant_id

    @classmethod
    @DB.connection_context()
    def set_active_tenant_id(cls, user_id, tenant_id):
        """Persist the caller's workspace selection.

        Raises ``ValueError`` when the caller holds no membership on the tenant,
        so a client cannot switch itself into a workspace it does not belong to.
        """
        if not UserTenantService.get_role(user_id, tenant_id):
            raise ValueError(f"user {user_id} is not a member of tenant {tenant_id}")
        UserService.update_by_id(user_id, {"current_tenant_id": tenant_id})
        return tenant_id

    @classmethod
    @DB.connection_context()
    def decrease(cls, user_id, num):
        num = cls.model.update(credit=cls.model.credit - num).where(cls.model.id == user_id).execute()
        if num == 0:
            raise LookupError("Tenant not found which is supposed to be there")

    @classmethod
    @DB.connection_context()
    def user_gateway(cls, tenant_id):
        hash_obj = hashlib.sha256(tenant_id.encode("utf-8"))
        return int(hash_obj.hexdigest(), 16) % len(settings.MINIO)

    @classmethod
    @DB.connection_context()
    def get_null_tenant_model_id_rows(cls):
        objs = cls.model.select().orwhere(
            cls.model.tenant_llm_id.is_null(),
            cls.model.tenant_embd_id.is_null(),
            cls.model.tenant_asr_id.is_null(),
            cls.model.tenant_tts_id.is_null(),
            cls.model.tenant_rerank_id.is_null(),
            cls.model.tenant_img2txt_id.is_null(),
        )
        return list(objs)


class UserTenantService(CommonService):
    """Service class for managing user-tenant relationship operations.

    This class extends CommonService to handle the many-to-many relationship
    between users and tenants, managing user roles and tenant memberships.

    Attributes:
        model: The UserTenant model class for database operations.
    """

    model = UserTenant

    @classmethod
    @DB.connection_context()
    def filter_by_id(cls, user_tenant_id):
        try:
            user_tenant = cls.model.select().where((cls.model.id == user_tenant_id) & (cls.model.status == StatusEnum.VALID.value)).get()
            return user_tenant
        except peewee.DoesNotExist:
            return None

    @classmethod
    @DB.connection_context()
    def save(cls, **kwargs):
        if "id" not in kwargs:
            kwargs["id"] = get_uuid()
        obj = cls.model(**kwargs).save(force_insert=True)
        return obj

    @classmethod
    @DB.connection_context()
    def get_by_tenant_id(cls, tenant_id):
        """The workspace roster, owner included, with organisational attributes.

        The owner is a member like any other and the team page must show them,
        so unlike the pre-existing roster this does not filter OWNER out. The
        department name comes from a left join: a member without a department is
        still a row.
        """
        fields = [
            cls.model.id,
            cls.model.user_id,
            cls.model.status,
            cls.model.role,
            cls.model.department_id,
            cls.model.title,
            Department.name.alias("department_name"),
            User.nickname,
            User.email,
            User.avatar,
            User.is_authenticated,
            User.is_active,
            User.is_anonymous,
            User.status,
            User.update_date,
            User.is_superuser,
        ]
        return list(
            cls.model.select(*fields)
            .join(User, on=((cls.model.user_id == User.id) & (cls.model.status == StatusEnum.VALID.value)))
            .switch(cls.model)
            .join(Department, JOIN.LEFT_OUTER, on=((cls.model.department_id == Department.id) & (Department.status == StatusEnum.VALID.value)))
            .where(cls.model.tenant_id == tenant_id)
            .dicts()
        )

    @classmethod
    @DB.connection_context()
    def get_tenants_by_user_id(cls, user_id):
        """Every workspace `user_id` belongs to.

        A row's identity is the WORKSPACE, so `name` is read from the `tenant`
        row. The `nickname`/`email`/`avatar` beside it belong to the workspace's
        owner (a membership carries no profile of its own) and are carried for
        callers that show who runs the workspace; they are not its name, which is
        what a switcher used to render as the row's identity.
        """
        fields = [cls.model.tenant_id, cls.model.role, Tenant.name, User.nickname, User.email, User.avatar, User.update_date]
        return list(
            cls.model.select(*fields)
            .join(Tenant, on=((cls.model.tenant_id == Tenant.id) & (Tenant.status == StatusEnum.VALID.value)))
            .switch(cls.model)
            .join(User, on=(cls.model.tenant_id == User.id))
            .where((cls.model.user_id == user_id) & (cls.model.status == StatusEnum.VALID.value))
            .dicts()
        )

    @classmethod
    @DB.connection_context()
    def get_user_tenant_relation_by_user_id(cls, user_id):
        fields = [cls.model.id, cls.model.user_id, cls.model.tenant_id, cls.model.role]
        return list(cls.model.select(*fields).where(cls.model.user_id == user_id).dicts().dicts())

    @classmethod
    @DB.connection_context()
    def get_num_members(cls, user_id: str):
        cnt_members = cls.model.select(peewee.fn.COUNT(cls.model.id)).where(cls.model.tenant_id == user_id).scalar()
        return cnt_members

    @classmethod
    @DB.connection_context()
    def filter_by_tenant_and_user_id(cls, tenant_id, user_id):
        try:
            user_tenant = cls.model.select().where((cls.model.tenant_id == tenant_id) & (cls.model.status == StatusEnum.VALID.value) & (cls.model.user_id == user_id)).first()
            return user_tenant
        except peewee.DoesNotExist:
            return None

    @classmethod
    @DB.connection_context()
    def can_manage_tenant(cls, user_id, tenant_id) -> bool:
        """Returns True if the user holds OWNER or ADMIN on the given tenant.

        This supports delegated administration across tenants in multi-tenant
        deployments. OWNER implies ADMIN: the role hierarchy is
        OWNER > ADMIN > NORMAL, so a tenant owner needs no extra row to manage
        the tenant it owns.
        """
        return (
            cls.model.select()
            .where(
                (cls.model.user_id == user_id) & (cls.model.tenant_id == tenant_id) & (cls.model.role.in_([UserTenantRole.OWNER, UserTenantRole.ADMIN])) & (cls.model.status == StatusEnum.VALID.value)
            )
            .exists()
        )

    @classmethod
    @DB.connection_context()
    def get_role(cls, user_id, tenant_id):
        row = (
            cls.model.select(cls.model.role)
            .where(
                (cls.model.user_id == user_id)
                & (cls.model.tenant_id == tenant_id)
                & cls.model.role.in_((UserTenantRole.OWNER, UserTenantRole.ADMIN, UserTenantRole.NORMAL))
                & (cls.model.status == StatusEnum.VALID.value)
            )
            .first()
        )
        return row.role if row else None

    @classmethod
    @DB.connection_context()
    def set_role(cls, user_id, tenant_id, role):
        """Set a tenant-level role. Only ADMIN and NORMAL are assignable.

        OWNER is reached by creating a tenant, never by promotion, and INVITE is
        owned by the invitation flow.
        """
        if role not in (UserTenantRole.ADMIN, UserTenantRole.NORMAL):
            raise ValueError(f"role {role} is not assignable")
        return cls.model.update(role=role).where((cls.model.user_id == user_id) & (cls.model.tenant_id == tenant_id) & (cls.model.status == StatusEnum.VALID.value)).execute()
