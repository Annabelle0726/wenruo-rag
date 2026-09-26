from types import SimpleNamespace

import pytest

from api.db.joint_services import tenant_model_service as models
from common.constants import ActiveStatusEnum
from common.exceptions import WorkspaceAccessDenied
from common.workspace_context import execution_user


@pytest.fixture
def chain(monkeypatch):
    model = SimpleNamespace(provider_id="provider", instance_id="instance", model_name="chat-model", model_type=models.calculate_model_type("chat"), status=ActiveStatusEnum.ACTIVE.value, extra="{}")
    provider = SimpleNamespace(id="provider", tenant_id="workspace", provider_name="OpenAI")
    instance = SimpleNamespace(id="instance", provider_id="provider", api_key="server-only-secret", extra="{}")
    monkeypatch.setattr(models.TenantModelService, "get_by_id", lambda _: (True, model))
    monkeypatch.setattr(models.TenantModelProviderService, "get_by_id", lambda _: (True, provider))
    monkeypatch.setattr(models.TenantModelInstanceService, "get_by_id", lambda _: (True, instance))
    return provider, instance


def test_foreign_model_id_never_uses_joined_workspace_fallback(chain, monkeypatch):
    monkeypatch.setattr(models.TenantService, "get_joined_tenants_by_user_id", lambda _: [{"tenant_id": "workspace"}])
    with pytest.raises(WorkspaceAccessDenied):
        models.resolve_model_config("other", "chat", "model")
    with pytest.raises(WorkspaceAccessDenied):
        models.get_api_key("other", "model")


def test_instance_must_belong_to_models_provider(chain):
    chain[1].provider_id = "foreign-provider"
    with pytest.raises(WorkspaceAccessDenied):
        models.get_model_config_by_id("workspace", "chat", "model")
    with pytest.raises(WorkspaceAccessDenied):
        models.get_api_key("workspace", "model")


def test_normal_member_uses_authorized_workspace_configuration(chain, monkeypatch):
    seen = []

    def resolve(user, tenant):
        seen.append((user, tenant))
        return tenant

    monkeypatch.setattr(models.TenantService, "resolve_config_tenant_id", resolve)
    token = execution_user.set("normal-member-with-no-personal-tenant")
    try:
        config = models.get_model_config_by_id("workspace", "chat", "model")
        assert config["api_key"] == "server-only-secret"  # internal execution, never an API serializer
        assert seen == [("normal-member-with-no-personal-tenant", "workspace")]
    finally:
        execution_user.reset(token)


def test_removed_member_stops_before_loading_provider_secret(chain, monkeypatch):
    def deny(*_):
        raise WorkspaceAccessDenied("removed")

    def secret_must_not_load(*_):
        pytest.fail("credentials loaded before membership validation")

    monkeypatch.setattr(models.TenantService, "resolve_config_tenant_id", deny)
    monkeypatch.setattr(models.TenantModelInstanceService, "get_by_id", secret_must_not_load)
    token = execution_user.set("removed-member")
    try:
        with pytest.raises(WorkspaceAccessDenied):
            models.resolve_model_config("workspace", "chat", "model")
    finally:
        execution_user.reset(token)


def test_explicit_revoked_workspace_never_falls_back(monkeypatch):
    from api.db.services.user_service import TenantService, UserTenantService, UserService

    monkeypatch.setattr(UserTenantService, "get_role", lambda user, tenant: "owner" if tenant == "personal" else None)

    def must_not_fall_back(*_):
        pytest.fail("invalid explicit workspace must be rejected, not replaced")

    monkeypatch.setattr(UserService, "get_by_id", must_not_fall_back)
    with pytest.raises(WorkspaceAccessDenied):
        TenantService.resolve_active_tenant_id.__wrapped__(TenantService, "member", "revoked")


def test_config_resolver_accepts_live_normal_and_rejects_pending_invite(monkeypatch):
    from api.db.services.user_service import TenantService, UserTenantService

    monkeypatch.setattr(UserTenantService, "get_role", lambda user, tenant: "normal")
    resolve = TenantService.resolve_config_tenant_id.__wrapped__
    assert resolve(TenantService, "member", "workspace") == "workspace"
    monkeypatch.setattr(UserTenantService, "get_role", lambda user, tenant: "invite")
    with pytest.raises(WorkspaceAccessDenied):
        resolve(TenantService, "member", "workspace")
