import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
import valkey
from peewee import SqliteDatabase

from api.db.db_models import (
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
    WorkspaceBudget,
    WorkspaceUsage,
    WorkspaceUsageLedger,
)
from api.db.services import workspace_budget_service as budget
from api.db.services import workspace_member_service as members
from common.exceptions import WorkspaceAccessDenied
from common.model_budget import budgeted, charge_provider_call
from common.workspace_context import execution_user


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    models = [Tenant, User, UserTenant, TenantInvite, APIToken, Dialog, Knowledgebase, KnowledgebaseAuthorization, UserCanvas, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage, WorkspaceUsageLedger]
    db = SqliteDatabase(tmp_path / "workspace.sqlite", timeout=20)
    with db.bind_ctx(models):
        db.create_tables(models)
        for module in (budget, members):
            monkeypatch.setattr(module, "DB", db)
        for tenant in ("workspace", "other"):
            Tenant.create(id=tenant, name=tenant, llm_id="", embd_id="", asr_id="", img2txt_id="", rerank_id="", parser_ids="")
        for user, role in (("owner", "owner"), ("admin", "admin"), ("member", "normal")):
            User.create(id=user, nickname=user, email=user + "@example.test", current_tenant_id="workspace")
            UserTenant.create(id=user, user_id=user, tenant_id="workspace", role=role, invited_by="owner")
        UserTenant.create(id="other", user_id="member", tenant_id="other", role="normal", invited_by="owner")
        for tenant in ("workspace", "other"):
            Knowledgebase.create(id=tenant, name=tenant, tenant_id=tenant, created_by="member", embd_id="", permission="me")
            Dialog.create(id=tenant, tenant_id=tenant, created_by="member", llm_id="", rerank_id="")
            UserCanvas.create(id=tenant, tenant_id=tenant, user_id="member", permission="me")
        KnowledgebaseAuthorization.create(id="grant", kb_id="workspace", subject_type="user", subject_id="member")
        APIToken.create(tenant_id="member", token="old-token", dialog_id="workspace")
        yield db
        if not db.is_closed():
            db.close()


def test_removal_transfers_only_workspace_and_revokes(workspace):
    assert members.remove_member("workspace", "member", "owner", "admin") == {"datasets": 1, "assistants": 1, "agents": 1}
    assert Knowledgebase.get_by_id("workspace").created_by == "admin"
    assert Knowledgebase.get_by_id("workspace").permission == "me"
    assert Dialog.get_by_id("workspace").created_by == "admin"
    assert UserCanvas.get_by_id("workspace").user_id == "admin"
    assert UserCanvas.get_by_id("other").user_id == "member"
    assert Knowledgebase.get_by_id("other").created_by == "member"
    assert UserTenant.get_by_id("other").user_id == "member"
    assert not UserTenant.select().where(UserTenant.id == "member").exists()
    assert not KnowledgebaseAuthorization.select().exists()
    assert not APIToken.select().exists()
    assert User.get_by_id("member").current_tenant_id is None
    assert WorkspaceAudit.get().details["to"] == "admin"
    with pytest.raises(WorkspaceAccessDenied):
        budget.reserve_call("workspace", "member")


def test_transfer_failure_rolls_back_everything(workspace, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(WorkspaceAudit, "create", fail)
    with pytest.raises(RuntimeError):
        members.remove_member("workspace", "member", "owner")
    assert UserTenant.get_by_id("member")
    assert Knowledgebase.get_by_id("workspace").created_by == "member"
    assert APIToken.get().token == "old-token"


@pytest.mark.parametrize("departing,actor,recipient", [("owner", "admin", None), ("admin", "member", None), ("member", "owner", "member"), ("member", "owner", "stranger")])
def test_invalid_removal_denied(workspace, departing, actor, recipient):
    with pytest.raises(WorkspaceAccessDenied):
        members.remove_member("workspace", departing, actor, recipient)
    assert UserTenant.select().count() == 4


def test_ambiguous_legacy_canvas_blocks_removal(workspace):
    UserCanvas.create(id="legacy", user_id="member")
    with pytest.raises(WorkspaceAccessDenied, match="历史代理"):
        members.remove_member("workspace", "member", "owner")
    assert UserTenant.get_by_id("member")


def test_removed_member_cannot_create_late_orphan(workspace):
    members.remove_member("workspace", "member", "owner")
    with pytest.raises(WorkspaceAccessDenied):
        members.save_owned_asset(UserCanvas, {"id": "late", "tenant_id": "workspace", "user_id": "member"})
    assert not UserCanvas.select().where(UserCanvas.id == "late").exists()


@pytest.fixture
def redis_budget(workspace, monkeypatch):
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL must identify an isolated test Redis")
    client = valkey.Redis.from_url(url)
    prefix = "security-test:" + uuid4().hex + ":"

    class ScopedRedis:
        def eval(self, script, nkeys, key, *args):
            return client.eval(script, nkeys, prefix + key, *args)

    monkeypatch.setattr(budget, "REDIS_CONN", SimpleNamespace(REDIS=ScopedRedis()))
    yield client, prefix
    keys = list(client.scan_iter(prefix + "*"))
    if keys:
        client.delete(*keys)
    client.close()


def test_rate_and_durable_quotas(redis_budget):
    budget.configure_budget("workspace", "owner", {"calls_per_minute": 2, "calls_per_day": 3, "calls_per_month": 4})
    budget.reserve_call("workspace", "member")
    budget.reserve_call("workspace", "member")
    with pytest.raises(WorkspaceAccessDenied, match="频繁"):
        budget.reserve_call("workspace", "member")
    client, prefix = redis_budget
    client.delete(*client.scan_iter(prefix + "*"))
    budget.reserve_call("workspace", "member")
    with pytest.raises(WorkspaceAccessDenied, match="今日"):
        budget.reserve_call("workspace", "member")
    assert {u.calls for u in WorkspaceUsage.select()} == {3}
    budget.configure_budget("workspace", "owner", {"calls_per_minute": 20, "calls_per_day": 10, "calls_per_month": 4})
    budget.reserve_call("workspace", "member")
    with pytest.raises(WorkspaceAccessDenied, match="本月"):
        budget.reserve_call("workspace", "member")


def test_concurrent_calls_cannot_exceed_quota(redis_budget):
    budget.configure_budget("workspace", "owner", {"calls_per_minute": 50, "calls_per_day": 3, "calls_per_month": 50})

    def invoke(_):
        try:
            budget.reserve_call("workspace", "member")
            return True
        except WorkspaceAccessDenied:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(invoke, range(12))) == 3
    assert {u.calls for u in WorkspaceUsage.select()} == {3}


def test_store_outage_and_normal_configuration_denied(workspace, monkeypatch):
    monkeypatch.setattr(budget, "REDIS_CONN", SimpleNamespace(REDIS=None))
    with pytest.raises(WorkspaceAccessDenied, match="暂不可用"):
        budget.reserve_call("workspace", "member")
    assert WorkspaceUsage.select().count() == 0
    with pytest.raises(WorkspaceAccessDenied):
        budget.configure_budget("workspace", "member", {})
    budget.reserve_call("workspace", "owner")  # documented manager exemption


@pytest.mark.asyncio
async def test_subcalls_and_streams_recheck_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "reserve_call", lambda tenant, actor, **_kwargs: calls.append((tenant, actor)))

    class Model:
        tenant_id = "workspace"

        @budgeted
        def sync(self):
            return "ok"

        @budgeted
        async def stream(self):
            yield "ok"

    token = execution_user.set("member")
    try:
        assert Model().sync() == "ok"
        assert [part async for part in Model().stream()] == ["ok"]
        assert calls == [("workspace", "member"), ("workspace", "member")]

        def deny(*_args, **_kwargs):
            raise WorkspaceAccessDenied("removed")

        monkeypatch.setattr(budget, "reserve_call", deny)
        with pytest.raises(WorkspaceAccessDenied):
            await anext(Model().stream())
    finally:
        execution_user.reset(token)


def test_provider_tool_rounds_and_retries_each_consume_budget(monkeypatch):
    calls = []

    def reserve(tenant, user, **_kwargs):
        if len(calls) == 2:
            raise WorkspaceAccessDenied("quota")
        calls.append((tenant, user))

    monkeypatch.setattr(budget, "reserve_call", reserve)
    dispatched = []

    class Model:
        tenant_id = "workspace"
        execution_user_id = "member"

        @budgeted
        def tool_loop(self):
            for _ in range(10):
                charge_provider_call()
                dispatched.append("provider")

    with pytest.raises(WorkspaceAccessDenied):
        Model().tool_loop()
    assert len(dispatched) == len(calls) == 2


@pytest.mark.asyncio
async def test_denial_is_http_200_code_108():
    from quart import Quart
    from api.utils.api_utils import server_error_response

    app = Quart(__name__)
    async with app.app_context():
        response = server_error_response(WorkspaceAccessDenied("今日使用额度已用尽"))
        assert response.status_code == 200
        assert (await response.get_json())["code"] == 108


@pytest.mark.asyncio
async def test_deferred_stream_keeps_identity_and_surfaces_swallowed_denial():
    from quart import Quart, Response
    from api.utils.workspace_execution import guard_response
    from common.workspace_context import execution_refusal

    async def body():
        assert execution_user.get() == "member"
        yield b'data:{"code":0}\n\n'
        execution_refusal.get()["message"] = "今日使用额度已用尽"
        # A tool fallback may swallow an exception, but cannot turn denial into success.
        yield b'data:{"code":0,"data":"fallback"}\n\n'

    app = Quart(__name__)
    async with app.app_context():
        result = guard_response(Response(body(), mimetype="text/event-stream"), "member", {})
        data = (await result.get_data()).decode()
        assert '"code": 108' in data
        assert "fallback" not in data
        assert execution_user.get() is None
