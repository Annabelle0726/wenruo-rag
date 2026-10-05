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
"""Dataset read and write authorization (P3-03).

One predicate decides visibility and another decides mutability, and they are
deliberately not the same function. A dataset may grant retrieval to a
department or to an individual; that grant is a *read* grant and must never
carry upload, parse, edit or delete authority. `can_read_dataset` therefore
guards the listing query and the retrieval path, while `can_write_dataset`
guards every mutating path and answers to the creator and the workspace
managers alone.

The modes are stored on `knowledgebase.permission`:

    me       the creator and the managers of the owning workspace
    team     every member of the owning workspace
    custom   the departments and the individuals named in
             `knowledgebase_authorization`, plus the creator and the managers

Read access is the union of the three; write access never consults
`permission` at all.
"""

import logging
from datetime import datetime
from functools import wraps

from api.db import TenantPermission, UserTenantRole
from api.db.db_models import DB, Knowledgebase, KnowledgebaseAuthorization, UserTenant
from common.constants import StatusEnum
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format

logger = logging.getLogger(__name__)


SUBJECT_DEPARTMENT = "department"
SUBJECT_USER = "user"
SUBJECT_TYPES = (SUBJECT_DEPARTMENT, SUBJECT_USER)

#: The roles that make a `user_tenant` row a membership. An `invite` row is a
#: pending invitation rather than a membership -- accepting it rewrites that row
#: as NORMAL -- so it must not carry workspace access. The listing SQL and the
#: predicate both read this tuple, so the two cannot drift apart.
MEMBER_ROLES = (UserTenantRole.OWNER, UserTenantRole.ADMIN, UserTenantRole.NORMAL)


def _with_connection(fn):
    """Run `fn` on a connection this module owns, or on the caller's.

    A plain `@DB.connection_context()` closes the connection on exit, which
    raises "Attempting to close database while transaction is open." when it is
    called from inside an enclosing `DB.atomic()` -- the trap
    `document_counter_service.release_reparse_counters` already documents. The
    grant set has to stay replaceable inside a caller's transaction (the
    authorization PUT replaces the subjects and the mode together), so this
    opens a connection only when none is open, and closes it only when it was
    the one that opened it.
    """

    @wraps(fn)
    def inner(*args, **kwargs):
        owns_connection = DB.is_closed()
        if owns_connection:
            DB.connect()
        try:
            return fn(*args, **kwargs)
        finally:
            if owns_connection and not DB.in_transaction():
                DB.close()

    return inner


def _field(kb, name):
    """Read a knowledge base attribute from a model instance or a row dict.

    Both shapes reach these predicates: the listing and retrieval paths hold a
    `Knowledgebase` model, while `.dicts()` queries hand back plain dicts.
    """
    if isinstance(kb, dict):
        return kb.get(name)
    return getattr(kb, name, None)


def _can_manage_tenant(user_id, tenant_id) -> bool:
    """True when the caller holds OWNER or ADMIN on `tenant_id`.

    Read straight from `user_tenant` rather than through
    `UserTenantService.can_manage_tenant`: that method is decorated with
    `@DB.connection_context()`, which closes the connection on exit and so
    raises inside a caller's open transaction. A predicate must be answerable
    from anywhere, including from the middle of the write path's transaction.
    """
    if not user_id or not tenant_id:
        return False
    return (
        UserTenant.select()
        .where(
            (UserTenant.user_id == user_id) & (UserTenant.tenant_id == tenant_id) & (UserTenant.role.in_([UserTenantRole.OWNER, UserTenantRole.ADMIN])) & (UserTenant.status == StatusEnum.VALID.value)
        )
        .exists()
    )


def _membership_role(user_id, tenant_id):
    """The caller's membership role on `tenant_id`, or None when not a member.

    A pending `invite` row is not a membership, so it reads as None here. A
    direct read for the same reason as `_can_manage_tenant`.
    """
    if not user_id or not tenant_id:
        return None
    row = (
        UserTenant.select(UserTenant.role)
        .where((UserTenant.user_id == user_id) & (UserTenant.tenant_id == tenant_id) & (UserTenant.role.in_(MEMBER_ROLES)) & (UserTenant.status == StatusEnum.VALID.value))
        .first()
    )
    return row.role if row else None


def _is_dataset_creator(user_id, kb) -> bool:
    """True when the caller is recorded as the dataset's creator.

    `created_by` is filled from the tenant id at creation
    (`KnowledgebaseService.create_with_name`), and the create route passes the
    caller's own id as that tenant, so in practice it holds the creator's user
    id. A dataset created under a shared tenant carries that tenant id instead,
    and is then writable by that workspace's managers only -- which is the
    intended reading of "the creator or a manager".
    """
    return bool(user_id) and _field(kb, "created_by") == user_id


def _manages_dataset_workspace(user_id, active_tenant_id, kb) -> bool:
    """True when the caller administers the workspace that owns the dataset.

    A manager governs the datasets of the workspace it manages, and only while
    that workspace is the active one: an id the caller switched to must not
    widen access to another tenant's datasets, so when an active workspace is
    supplied it has to be the owning one.
    """
    kb_tenant_id = _field(kb, "tenant_id")
    if not kb_tenant_id:
        return False
    if active_tenant_id and active_tenant_id != kb_tenant_id:
        return False
    return _can_manage_tenant(user_id, kb_tenant_id)


def _is_workspace_member(user_id, tenant_id) -> bool:
    """True when the caller holds a membership row on `tenant_id`.

    The membership is read on the dataset's own tenant, so a member of a joined
    workspace keeps the shared-dataset access it has today.
    """
    return _membership_role(user_id, tenant_id) is not None


def _department_id_of(user_id, tenant_id):
    """The caller's department inside `tenant_id`, or None when unplaced.

    Reading the membership row rather than a copy of it is what makes a
    department grant dynamic: a member who transfers into the department
    inherits its datasets, and one who leaves it loses them. A NULL department
    means the member was never placed, so no department grant can capture them.
    """
    if not user_id or not tenant_id:
        return None
    row = (
        UserTenant.select(UserTenant.department_id)
        .where((UserTenant.user_id == user_id) & (UserTenant.tenant_id == tenant_id) & (UserTenant.role.in_(MEMBER_ROLES)) & (UserTenant.status == StatusEnum.VALID.value))
        .first()
    )
    return row.department_id if row else None


def _is_granted(kb_id, user_id, department_id) -> bool:
    """True when `kb_id` names the caller or the caller's department.

    An unplaced member is matched on the individual grant only, never on a
    department: the department id is left out of the filter rather than compared
    against NULL.
    """
    if not kb_id or not user_id:
        return False

    granted = (KnowledgebaseAuthorization.subject_type == SUBJECT_USER) & (KnowledgebaseAuthorization.subject_id == user_id)
    if department_id:
        granted |= (KnowledgebaseAuthorization.subject_type == SUBJECT_DEPARTMENT) & (KnowledgebaseAuthorization.subject_id == department_id)

    return KnowledgebaseAuthorization.select().where((KnowledgebaseAuthorization.kb_id == kb_id) & granted).exists()


@_with_connection
def can_read_dataset(user_id: str, active_tenant_id: str, kb) -> bool:
    """Visibility and retrieval gate for one dataset.

    Allowed for the creator and for the managers of the owning workspace, then
    by mode: `team` reaches every member of that workspace, `custom` reaches the
    granted departments and individuals, `me` reaches nobody else. Anything
    unrecognised is denied rather than defaulted open.
    """
    if not user_id or not kb:
        return False

    if _is_dataset_creator(user_id, kb):
        return True
    if _manages_dataset_workspace(user_id, active_tenant_id, kb):
        return True

    permission = _field(kb, "permission")
    if permission == TenantPermission.TEAM:
        return _is_workspace_member(user_id, _field(kb, "tenant_id"))
    if permission == TenantPermission.CUSTOM:
        return _is_granted(_field(kb, "id"), user_id, _department_id_of(user_id, _field(kb, "tenant_id")))

    # 'me', and any value this build does not know: the creator and the managers
    # above are the whole audience.
    return False


@_with_connection
def can_write_dataset(user_id: str, active_tenant_id: str, kb) -> bool:
    """Mutating gate for one dataset: upload, parse, edit and delete.

    The creator and the managers of the owning workspace, and nobody else. This
    deliberately ignores `permission`: a member granted custom read access may
    retrieve the dataset but must never be able to change it.
    """
    if not user_id or not kb:
        return False

    allowed = _is_dataset_creator(user_id, kb) or _manages_dataset_workspace(user_id, active_tenant_id, kb)
    if not allowed:
        logger.debug(
            "dataset write denied: user=%s kb=%s tenant=%s permission=%s",
            user_id,
            _field(kb, "id"),
            _field(kb, "tenant_id"),
            _field(kb, "permission"),
        )
    return allowed


def _normalize_subjects(subjects) -> list[dict]:
    """Validate and de-duplicate a subject set before it is written.

    A repeated subject would otherwise collide with the unique index on
    `(kb_id, subject_type, subject_id)` and abort the whole replacement, so
    duplicates are collapsed here instead of surfacing as a failed save.
    """
    normalized = []
    seen = set()
    for subject in subjects or []:
        if not isinstance(subject, dict):
            raise ValueError("each subject must be a dict with subject_type and subject_id")
        subject_type = (subject.get("subject_type") or "").strip()
        subject_id = (subject.get("subject_id") or "").strip()
        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"subject_type must be one of {SUBJECT_TYPES}, got {subject_type!r}")
        if not subject_id:
            raise ValueError("subject_id is required")
        if (subject_type, subject_id) in seen:
            continue
        seen.add((subject_type, subject_id))
        normalized.append({"subject_type": subject_type, "subject_id": subject_id})
    return normalized


def _write_subjects(kb_id: str, rows: list[dict]) -> int:
    """Swap a dataset's grant rows for `rows`, inside the caller's transaction."""
    timestamp = current_timestamp()
    stamp = datetime_format(datetime.now())
    payload = [
        {
            "id": get_uuid(),
            "kb_id": kb_id,
            "subject_type": subject["subject_type"],
            "subject_id": subject["subject_id"],
            "create_time": timestamp,
            "create_date": stamp,
            "update_time": timestamp,
            "update_date": stamp,
        }
        for subject in rows
    ]

    KnowledgebaseAuthorization.delete().where(KnowledgebaseAuthorization.kb_id == kb_id).execute()
    if payload:
        KnowledgebaseAuthorization.insert_many(payload).execute()
    return len(payload)


@_with_connection
def replace_kb_authorizations(kb_id: str, subjects: list[dict]) -> None:
    """Replace the whole subject set of one dataset in a single transaction.

    This is a replace, not an append: the previous grants are deleted and the
    new ones inserted atomically, so a failed write leaves the old set intact
    rather than a half-applied one. Passing an empty set clears the dataset's
    grants, which is what a mode other than `custom` requires.
    """
    if not kb_id:
        raise ValueError("kb_id is required")

    rows = _normalize_subjects(subjects)
    with DB.atomic():
        written = _write_subjects(kb_id, rows)

    logger.info("dataset authorization replaced: kb=%s subjects=%d", kb_id, written)


@_with_connection
def set_dataset_authorization(kb_id: str, permission: str, subjects: list[dict]) -> None:
    """Set a dataset's visibility mode and its subject set in one transaction.

    The mode lives on the dataset row and the subjects in the grant table, so
    they are written together: a mode other than `custom` carries no subjects,
    and a half-applied write would leave a mode that disagrees with its subject
    set. Calls `replace_kb_authorizations`' write step on the same connection, so
    this is safe from inside a larger transaction as well.
    """
    if not kb_id:
        raise ValueError("kb_id is required")
    if permission not in (TenantPermission.ME, TenantPermission.TEAM, TenantPermission.CUSTOM):
        raise ValueError(f"permission must be one of me/team/custom, got {permission!r}")

    # Only `custom` carries a subject set; the other modes are decided by the
    # dataset row alone, so any stored subjects would be dead data.
    rows = _normalize_subjects(subjects) if permission == TenantPermission.CUSTOM else []

    with DB.atomic():
        Knowledgebase.update(permission=permission).where(Knowledgebase.id == kb_id).execute()
        written = _write_subjects(kb_id, rows)

    logger.info("dataset authorization set: kb=%s permission=%s subjects=%d", kb_id, permission, written)


@_with_connection
def get_kb_authorizations(kb_id: str) -> list[dict]:
    """The subjects currently granted read access to one dataset.

    Ordered by subject type so the two groups -- departments and individuals --
    come back in a stable order for the settings dialog to render.
    """
    if not kb_id:
        return []
    return list(KnowledgebaseAuthorization.select().where(KnowledgebaseAuthorization.kb_id == kb_id).order_by(KnowledgebaseAuthorization.subject_type, KnowledgebaseAuthorization.create_time).dicts())
