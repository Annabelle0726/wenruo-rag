"""Per-member model-call budgets: Redis rolling minutes, durable UTC periods.

One dispatch attempt is one unit, including a failed/cancelled call. There are
no refunds: an upstream timeout does not prove that the provider spent nothing.
OWNER/ADMIN are explicitly exempt; membership is still checked for every call.
"""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from api.db.db_models import DB, Tenant, UserTenant, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage
from common.exceptions import WorkspaceAccessDenied
from common.workspace_context import execution_refusal
from rag.utils.redis_conn import REDIS_CONN

ROLLING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], 60000)
return 1
"""

BUDGET_FIELDS = ("calls_per_minute", "calls_per_day", "calls_per_month")


def configure_budget(tenant_id, operator_id, values=None):
    with DB.connection_context(), DB.atomic():
        Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
        if not UserTenant.select().where((UserTenant.tenant_id == tenant_id) & (UserTenant.user_id == operator_id) & (UserTenant.status == "1") & UserTenant.role.in_(("owner", "admin"))).exists():
            raise WorkspaceAccessDenied("仅工作区管理员可以查看或配置使用额度")
        if values is not None:
            if not isinstance(values, dict) or set(values) != set(BUDGET_FIELDS) or any(type(values[k]) is not int or not 1 <= values[k] <= 10000000 for k in BUDGET_FIELDS):
                raise WorkspaceAccessDenied("请为分钟、每日和每月额度填写正整数")
            budget, _ = WorkspaceBudget.get_or_create(tenant_id=tenant_id)
            WorkspaceBudget.update(**values).where(WorkspaceBudget.tenant_id == tenant_id).execute()
            WorkspaceAudit.create(id=uuid4().hex, tenant_id=tenant_id, operator_id=operator_id, action="update_budget", details=values)
        budget = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id) or WorkspaceBudget()
        return {**{k: getattr(budget, k) for k in BUDGET_FIELDS}, "unit": "model_calls", "timezone": "UTC", "applies_to": "normal"}


def reserve_call(tenant_id, user_id):
    """Authorize and reserve before dispatch; never accepts a tracing user ID."""
    refusal = execution_refusal.get()
    if refusal and refusal.get("message"):
        raise WorkspaceAccessDenied(refusal["message"])
    try:
        with DB.connection_context(), DB.atomic():
            Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
            member = UserTenant.get_or_none((UserTenant.user_id == user_id) & (UserTenant.tenant_id == tenant_id) & (UserTenant.status == "1"))
            if member is None or member.role not in ("owner", "admin", "normal"):
                raise WorkspaceAccessDenied("您已无权访问此工作区")
            if member.role in ("owner", "admin"):
                return
            budget = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id) or WorkspaceBudget()
            now = datetime.now(timezone.utc)
            counters = []
            for period, limit, message in (
                (now.strftime("%Y-%m-%d"), budget.calls_per_day, "今日使用额度已用尽"),
                (now.strftime("%Y-%m"), budget.calls_per_month, "本月使用额度已用尽"),
            ):
                key = sha256(f"{tenant_id}:{user_id}:{period}".encode()).hexdigest()
                counter, _ = WorkspaceUsage.get_or_create(id=key, defaults={"tenant_id": tenant_id, "user_id": user_id, "period": period})
                if counter.calls >= limit:
                    raise WorkspaceAccessDenied(message)
                counters.append(key)
            key = "workspace:model-rate:" + sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()
            if not REDIS_CONN.REDIS.eval(ROLLING_WINDOW, 1, key, budget.calls_per_minute, uuid4().hex):
                raise WorkspaceAccessDenied("请求过于频繁，请稍后重试")
            WorkspaceUsage.update(calls=WorkspaceUsage.calls + 1).where(WorkspaceUsage.id.in_(counters)).execute()
    except WorkspaceAccessDenied as exc:
        if refusal is not None:
            refusal["message"] = str(exc)
        raise
    except Exception:
        # No credentials or backend exception details in this public message.
        if refusal is not None:
            refusal["message"] = "使用额度服务暂不可用，请稍后重试"
        raise WorkspaceAccessDenied("使用额度服务暂不可用，请稍后重试") from None
