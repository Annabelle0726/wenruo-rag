from datetime import timedelta

import pytest
from peewee import SqliteDatabase
from werkzeug.security import check_password_hash

from api.db.db_models import Department, Tenant, TenantInvite, User, UserTenant
from api.db.services import invitation_service as service
from api.utils.crypt import crypt


@pytest.fixture
def database(monkeypatch):
    db = SqliteDatabase(":memory:")
    models = [Tenant, User, UserTenant, Department, TenantInvite]
    with db.bind_ctx(models), db:
        db.create_tables(models)
        monkeypatch.setattr(service, "DB", db)
        Tenant.create(id="workspace", name="Team", llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        User.create(id="owner", email="owner@example.com", nickname="Owner")
        UserTenant.create(id="owner-link", user_id="owner", tenant_id="workspace", role="owner", invited_by="owner")
        Department.create(id="department", tenant_id="workspace", name="Engineering")
        yield db


def create(email="new@example.com", **kwargs):
    return service.InvitationService.create.__wrapped__("workspace", "owner", email, **kwargs)


def accept(token):
    return service.InvitationService.accept.__wrapped__(token, "小明", crypt("Test-password-123"))


def test_registration_disabled_still_allows_single_use_scoped_invitation(database, monkeypatch):
    from common import settings

    monkeypatch.setattr(settings, "REGISTER_ENABLED", False)
    result = create(role="admin", department_id="department")
    assert len(result["token"]) == 32
    assert result["invite_path"] == "/accept-invite?token=" + result["token"]
    info = service.InvitationService.metadata.__wrapped__(result["token"])
    assert info["department_name"] == "Engineering"
    user = accept(result["token"])
    membership = UserTenant.get(UserTenant.user_id == user.id)
    assert (membership.role, membership.department_id, user.current_tenant_id) == ("admin", "department", "workspace")
    assert Tenant.select().count() == 1  # No personal owner workspace.
    assert check_password_hash(user.password, service.password_value(crypt("Test-password-123")))
    with pytest.raises(PermissionError):
        accept(result["token"])


@pytest.mark.parametrize("status", ["expired", "revoked", "accepted"])
def test_invalid_status_rejected(database, status):
    result = create()
    TenantInvite.update(status=status).execute()
    with pytest.raises(PermissionError):
        accept(result["token"])
    assert User.select().count() == 1


def test_expired_and_reissued_tokens_rejected(database):
    old = create()
    latest = create()
    with pytest.raises(PermissionError):
        accept(old["token"])
    TenantInvite.update(expires_at=service.utcnow() - timedelta(seconds=1)).execute()
    with pytest.raises(PermissionError):
        accept(latest["token"])


def test_normal_role_cannot_invite_and_foreign_department_is_rejected(database):
    with pytest.raises(PermissionError):
        create(department_id="other-workspace-department")
    with pytest.raises(ValueError):
        create(role="owner")
    UserTenant.update(role="normal").execute()
    with pytest.raises(PermissionError):
        create()


def test_inviter_losing_authority_invalidates_outstanding_invite(database):
    result = create()
    UserTenant.update(role="normal").execute()
    with pytest.raises(PermissionError):
        accept(result["token"])


def test_existing_account_joins_without_resetting_password(database):
    User.create(id="existing", nickname="Existing", email="existing@example.com", password="unchanged")
    assert create("EXISTING@example.com")["joined"]
    assert User.get_by_id("existing").password == "unchanged"
    with pytest.raises(ValueError):
        create("existing@example.com", role="admin")
    assert UserTenant.get(UserTenant.user_id == "existing").role == "normal"


def test_failed_membership_insert_rolls_back_user_and_token(database, monkeypatch):
    result = create()

    def fail(**kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(UserTenant, "create", fail)
    with pytest.raises(RuntimeError):
        accept(result["token"])
    assert User.select().count() == 1
    assert TenantInvite.get().status == "pending"


def test_registered_while_invitation_pending_cannot_overwrite_account(database):
    result = create()
    User.create(id="existing", nickname="Existing", email="new@example.com", password="unchanged")
    with pytest.raises(PermissionError):
        accept(result["token"])
    assert User.get_by_id("existing").password == "unchanged"
    assert TenantInvite.get().status == "pending"
