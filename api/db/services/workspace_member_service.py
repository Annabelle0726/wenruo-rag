"""Atomic membership revocation and asset reassignment within one workspace."""

from uuid import uuid4

from api.db.db_models import (
    DB,
    APIToken,
    Dialog,
    Knowledgebase,
    KnowledgebaseAuthorization,
    Tenant,
    TenantInvite,
    User,
    UserCanvas,
    UserTenant,
    WorkspaceAudit,
)
from common.exceptions import WorkspaceAccessDenied


def save_owned_asset(model, values):
    """Serialize creation with removal so a late insert cannot orphan assets."""
    tenant_id = values.get("tenant_id")
    owner = values.get("user_id") if model is UserCanvas else values.get("created_by")
    with DB.connection_context(), DB.atomic():
        Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
        if not UserTenant.select().where((UserTenant.tenant_id == tenant_id) & (UserTenant.user_id == owner) & (UserTenant.status == "1")).exists():
            raise WorkspaceAccessDenied("您已无权在此工作区创建资产")
        return model(**values).save(force_insert=True)


def remove_member(tenant_id, user_id, operator_id, transfer_to_user_id=None):
    with DB.connection_context(), DB.atomic():
        # Serialize removal/transfer in the workspace without nested service
        # connection_context decorators that could close this transaction.
        Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
        members = {m.user_id: m for m in UserTenant.select().where((UserTenant.tenant_id == tenant_id) & (UserTenant.status == "1"))}
        actor, departing = members.get(operator_id), members.get(user_id)
        if not actor or not departing or departing.role == "owner":
            raise WorkspaceAccessDenied("无法移除此工作区成员")
        if operator_id != user_id and actor.role not in ("owner", "admin"):
            raise WorkspaceAccessDenied("仅工作区管理员可以移除成员")
        recipient = members.get(transfer_to_user_id) if transfer_to_user_id else next((m for m in members.values() if m.role == "owner"), None)
        if not recipient or recipient.role not in ("owner", "admin") or recipient.user_id == user_id:
            raise WorkspaceAccessDenied("资产接收人必须是本工作区的业主或管理员")
        if not User.select().where((User.id == recipient.user_id) & (User.status == "1") & (User.is_active == "1")).exists():
            raise WorkspaceAccessDenied("资产接收人账号不可用")
        if UserCanvas.select().where((UserCanvas.user_id == user_id) & UserCanvas.tenant_id.is_null()).exists():
            raise WorkspaceAccessDenied("请先确认该成员历史代理的工作区归属，再移除成员")
        chat_ids = list(Dialog.select(Dialog.id).where((Dialog.tenant_id == tenant_id) & (Dialog.created_by == user_id)).scalars())
        canvas_ids = list(UserCanvas.select(UserCanvas.id).where((UserCanvas.tenant_id == tenant_id) & (UserCanvas.user_id == user_id)).scalars())
        transferred = {
            "datasets": Knowledgebase.update(created_by=recipient.user_id).where((Knowledgebase.tenant_id == tenant_id) & (Knowledgebase.created_by == user_id)).execute(),
            "assistants": Dialog.update(created_by=recipient.user_id).where(Dialog.id.in_(chat_ids)).execute(),
            "agents": UserCanvas.update(user_id=recipient.user_id).where(UserCanvas.id.in_(canvas_ids)).execute(),
        }
        KnowledgebaseAuthorization.delete().where(
            (KnowledgebaseAuthorization.subject_type == "user")
            & (KnowledgebaseAuthorization.subject_id == user_id)
            & KnowledgebaseAuthorization.kb_id.in_(Knowledgebase.select(Knowledgebase.id).where(Knowledgebase.tenant_id == tenant_id))
        ).execute()
        # Resource-scoped public/API credentials must not survive the transfer.
        APIToken.delete().where(APIToken.dialog_id.in_(chat_ids + canvas_ids)).execute()
        TenantInvite.update(status="revoked").where((TenantInvite.tenant_id == tenant_id) & (TenantInvite.invited_by == user_id) & (TenantInvite.status == "pending")).execute()
        UserTenant.delete().where((UserTenant.tenant_id == tenant_id) & (UserTenant.user_id == user_id)).execute()
        User.update(current_tenant_id=None).where((User.id == user_id) & (User.current_tenant_id == tenant_id)).execute()
        WorkspaceAudit.create(id=uuid4().hex, tenant_id=tenant_id, operator_id=operator_id, action="remove_member", details={"from": user_id, "to": recipient.user_id, "transferred": transferred})
        return transferred
