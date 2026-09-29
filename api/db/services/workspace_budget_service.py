"""Per-member model-call budgets: Redis rolling minutes, durable zoned periods.

One dispatch attempt is one unit, including a failed/cancelled call. There are
no refunds: an upstream timeout does not prove that the provider spent nothing.
OWNER/ADMIN are explicitly exempt; membership is still checked for every call.

Every attempt RESERVES a bound before dispatch - one call, an estimated token
count and, when the model carries pricing, a cost bound - and SETTLES that
reservation with the provider-reported usage afterwards. Settlement is
idempotent by reservation id, so a stream that ends twice, a retried callback or
a concurrent duplicate cannot charge twice; only the UNUSED part of the bound is
released, so a call that reports no usage still costs its reservation.
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone as utc_timezone
from hashlib import sha256
from uuid import uuid4

from api.db.db_models import DB, Tenant, UserTenant, WorkspaceAudit, WorkspaceBudget, WorkspaceUsage, WorkspaceUsageLedger
from common.exceptions import WorkspaceAccessDenied
from common.workspace_context import execution_refusal, execution_user
from rag.utils.redis_conn import REDIS_CONN

try:  # pragma: no cover - availability depends on the host's tz database
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python without zoneinfo

    class ZoneInfo:  # type: ignore[no-redef]
        def __init__(self, _name):
            raise ZoneInfoNotFoundError("zoneinfo is unavailable")

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass


ROLLING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], 60000)
return 1
"""

DEFAULT_TIMEZONE = "UTC"
CALL_FIELDS = ("calls_per_minute", "calls_per_day", "calls_per_month")
TOKEN_FIELDS = ("tokens_per_day", "tokens_per_month")
COST_FIELDS = ("cost_micros_per_day", "cost_micros_per_month")
BUDGET_FIELDS = CALL_FIELDS + TOKEN_FIELDS + COST_FIELDS
# 0 means "not enforced" on the token/cost dimensions; the call dimensions keep
# their positive floor because a workspace with 0 calls/minute is unreachable.
FIELDS_ALLOWING_ZERO = TOKEN_FIELDS + COST_FIELDS
MEMBER_ROLES = ("owner", "admin", "normal")
LIMIT_EXEMPT_ROLES = ("owner", "admin")


def _zone(name):
    """Resolve a stored zone name, falling back to UTC.

    A zone that cannot be resolved (a host without a tz database, or a name
    written by an older build) must not take model calls down: it changes the
    reset BOUNDARY, not whether a limit applies, so the fallback is logged and
    the call proceeds on UTC. Writes validate the name and refuse it up front.
    """
    if not name or name == DEFAULT_TIMEZONE:
        return utc_timezone.utc
    try:
        return ZoneInfo(str(name))
    except Exception:  # noqa: BLE001 - any failure means "cannot resolve", fall back
        logging.warning("Unknown workspace timezone %r; falling back to UTC for period boundaries", name)
        return utc_timezone.utc


def validate_timezone(name):
    """The canonical zone name, or a refusal naming the field."""
    if name is None:
        return DEFAULT_TIMEZONE
    if not isinstance(name, str) or not name.strip():
        raise WorkspaceAccessDenied("请填写有效的时区，例如 Asia/Shanghai 或 UTC")
    candidate = name.strip()
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError:
        raise WorkspaceAccessDenied(f"未知时区：{candidate}") from None
    except Exception:
        # A host without a tz database cannot verify any name but UTC.
        if candidate != DEFAULT_TIMEZONE:
            raise WorkspaceAccessDenied(f"未知时区：{candidate}") from None
    return candidate


def current_periods(timezone_name=DEFAULT_TIMEZONE, now=None):
    """The day and month period keys of the workspace's own calendar.

    The reset boundary is midnight in the workspace's zone, not in UTC: an
    employee in UTC+8 must get a new day at their own midnight. Periods are
    plain date strings, so a boundary crossing simply starts a new counter row.
    """
    moment = now or datetime.now(utc_timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=utc_timezone.utc)
    local = moment.astimezone(_zone(timezone_name))
    return local.strftime("%Y-%m-%d"), local.strftime("%Y-%m")


def _counter_id(tenant_id, user_id, period):
    return sha256(f"{tenant_id}:{user_id}:{period}".encode()).hexdigest()


def _serialize_limits(budget):
    return {field: int(getattr(budget, field) or 0) for field in BUDGET_FIELDS}


# The storage range of each numeric limit. `calls_*` live in an IntegerField and
# `tokens_*` in a BigIntegerField, so the WRITE validation has to match the
# column that will hold the value: accepting 10^10 for calls would be a database
# error at insert time instead of a controlled refusal.
CALL_MAX = 2_147_483_647
TOKEN_MAX = 10_000_000_000


class PolicyConflict(Exception):
    """The caller's `If-Match` revision no longer describes the stored policy.

    Raised INSIDE the same transaction that would have written the change, so a
    conflict updates nothing and writes no success audit row.
    """


def policy_revision(tenant_id, budget=None):
    """An opaque revision of the workspace's POLICY, not of its usage.

    It covers exactly what a policy editor owns - the workspace id, whether a
    budget row exists, the seven limits and the timezone - and deliberately NOTHING
    from the counters or the ledger. Including usage would make every metered model
    call produce a new revision, so two administrators could never save without a
    spurious conflict.

    It is a conflict DETECTOR, not a sequence number: reading A, changing to B and
    back to A is not a conflict, and it makes no claim to notice every intermediate
    write. It is also not a credential - the authorization check happens first and
    is unaffected by it.
    """
    row = budget if budget is not None else WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id)
    limits = _serialize_limits(row) if row is not None else {field: None for field in BUDGET_FIELDS}
    payload = {
        "tenant": tenant_id,
        "present": row is not None,
        "limits": limits,
        "timezone": (row.timezone or DEFAULT_TIMEZONE) if row is not None else None,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def configure_budget(tenant_id, operator_id, values=None, now=None, expected_revision=None):
    """Read or update every limit of a workspace; OWNER/ADMIN only, audited.

    `expected_revision` is the optional `If-Match` contract a policy editor uses:
    when it is supplied, the revision is recomputed INSIDE this transaction (under
    the same tenant lock the write takes) and a mismatch raises `PolicyConflict`
    with nothing written. A caller that supplies no revision keeps the original
    last-committed-write-wins behaviour, so the pre-existing API is not broken by
    the newer one.
    """
    with DB.connection_context(), DB.atomic():
        Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
        if not UserTenant.select().where((UserTenant.tenant_id == tenant_id) & (UserTenant.user_id == operator_id) & (UserTenant.status == "1") & UserTenant.role.in_(LIMIT_EXEMPT_ROLES)).exists():
            raise WorkspaceAccessDenied("仅工作区管理员可以查看或配置使用额度")
        stored = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id)
        if expected_revision is not None and str(expected_revision) != policy_revision(tenant_id, stored):
            raise PolicyConflict("使用策略已被其他管理员修改，请刷新后重新提交")
        if values is not None:
            if not isinstance(values, dict) or not values:
                raise WorkspaceAccessDenied("请填写需要更新的使用额度")
            unknown = set(values) - set(BUDGET_FIELDS) - {"timezone"}
            if unknown:
                raise WorkspaceAccessDenied(f"未知的额度字段：{', '.join(sorted(unknown))}")
            update = {}
            for field, value in values.items():
                if field == "timezone":
                    update[field] = validate_timezone(value)
                    continue
                if type(value) is not int:
                    raise WorkspaceAccessDenied("请为分钟、每日和每月额度填写整数")
                low = 0 if field in FIELDS_ALLOWING_ZERO else 1
                high = CALL_MAX if field in CALL_FIELDS else TOKEN_MAX
                # 0 on a token/cost dimension means "not enforced", never "zero
                # allowance"; a call limit of 0 stays refused because a workspace
                # with no calls at all is unreachable.
                if not low <= value <= high:
                    raise WorkspaceAccessDenied(f"请为 {field} 填写 {low} 至 {high} 之间的整数")
                update[field] = value
            WorkspaceBudget.get_or_create(tenant_id=tenant_id)
            WorkspaceBudget.update(**update).where(WorkspaceBudget.tenant_id == tenant_id).execute()
            WorkspaceAudit.create(id=uuid4().hex, tenant_id=tenant_id, operator_id=operator_id, action="update_budget", details=update)
        budget = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id) or WorkspaceBudget()
        payload = _serialize_limits(budget)
        payload.update(
            {
                "timezone": budget.timezone or DEFAULT_TIMEZONE,
                "unit": "model_calls",
                "token_unit": "tokens",
                "cost_unit": "micro_usd",
                "applies_to": "normal",
                "zero_means_unlimited": list(FIELDS_ALLOWING_ZERO),
                # The POST-write revision: the caller echoes this into the next
                # `If-Match`, so returning the value it already sent would make its
                # very next save conflict.
                "policy_revision": policy_revision(tenant_id),
            }
        )
        payload["used"] = usage_snapshot(tenant_id, None, budget=budget, now=now)
        return payload


def usage_snapshot(tenant_id, user_id=None, budget=None, now=None):
    """Counters of the current period(s), for the configuration read and reports.

    The day and month totals are reported separately: a reservation increments
    BOTH rows, so a single "total" that added them would double count it.
    """
    budget = budget or WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id) or WorkspaceBudget()
    day, month = current_periods(budget.timezone, now=now)
    query = WorkspaceUsage.select().where((WorkspaceUsage.tenant_id == tenant_id) & WorkspaceUsage.period.in_((day, month)))
    if user_id:
        query = query.where(WorkspaceUsage.user_id == user_id)
    fields = ("calls", "tokens", "prompt_tokens", "completion_tokens", "cost_micros")

    def _empty():
        return {field: 0 for field in fields}

    totals = {"day": _empty(), "month": _empty()}
    per_user = {}
    for row in query.dicts():
        bucket = per_user.setdefault(row["user_id"], {"day": _empty(), "month": _empty()})
        which = "day" if row["period"] == day else "month"
        for field in fields:
            value = int(row.get(field) or 0)
            bucket[which][field] += value
            totals[which][field] += value
    return {"period_day": day, "period_month": month, "timezone": budget.timezone or DEFAULT_TIMEZONE, **totals, "members": per_user}


def reserve_call(tenant_id, user_id, model_name=None, model_type=None, reserved_tokens=0, reserved_cost_micros=0, now=None):
    """Authorize and reserve before dispatch; never accepts a tracing user ID.

    Returns the reservation id, which the caller hands back to
    `settle_dispatch`/`release_dispatch`. Managers (OWNER/ADMIN) are exempt from
    the limits but their attempts are still recorded, so the ledger describes
    the workspace's whole model spend rather than only its employees'.
    """
    refusal = execution_refusal.get()
    if refusal and refusal.get("message"):
        raise WorkspaceAccessDenied(refusal["message"])
    reserved_tokens = max(0, int(reserved_tokens or 0))
    reserved_cost_micros = max(0, int(reserved_cost_micros or 0))
    try:
        with DB.connection_context(), DB.atomic():
            Tenant.update(name=Tenant.name).where(Tenant.id == tenant_id).execute()
            member = UserTenant.get_or_none((UserTenant.user_id == user_id) & (UserTenant.tenant_id == tenant_id) & (UserTenant.status == "1"))
            if member is None or member.role not in MEMBER_ROLES:
                raise WorkspaceAccessDenied("您已无权访问此工作区")
            budget = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == tenant_id) or WorkspaceBudget()
            day, month = current_periods(budget.timezone, now=now)
            exempt = member.role in LIMIT_EXEMPT_ROLES
            counters = []
            for period, key in ((day, "day"), (month, "month")):
                counter, _ = WorkspaceUsage.get_or_create(
                    id=_counter_id(tenant_id, user_id, period),
                    defaults={"tenant_id": tenant_id, "user_id": user_id, "period": period},
                )
                if not exempt:
                    call_limit = int(getattr(budget, f"calls_per_{key}") or 0)
                    token_limit = int(getattr(budget, f"tokens_per_{key}") or 0)
                    cost_limit = int(getattr(budget, f"cost_micros_per_{key}") or 0)
                    if call_limit and counter.calls >= call_limit:
                        raise WorkspaceAccessDenied("今日使用额度已用尽" if key == "day" else "本月使用额度已用尽")
                    if token_limit and counter.tokens + reserved_tokens > token_limit:
                        raise WorkspaceAccessDenied("今日 Token 额度已用尽" if key == "day" else "本月 Token 额度已用尽")
                    if cost_limit and counter.cost_micros + reserved_cost_micros > cost_limit:
                        raise WorkspaceAccessDenied("今日费用额度已用尽" if key == "day" else "本月费用额度已用尽")
                counters.append(counter.id)
            if not exempt:
                rate_key = "workspace:model-rate:" + sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()
                if not REDIS_CONN.REDIS.eval(ROLLING_WINDOW, 1, rate_key, budget.calls_per_minute, uuid4().hex):
                    raise WorkspaceAccessDenied("请求过于频繁，请稍后重试")
            # The reservation is a bound, not a charge: settlement releases
            # whatever the provider did not use. Adding it before dispatch is
            # what keeps concurrent callers from oversubscribing the same quota.
            WorkspaceUsage.update(
                calls=WorkspaceUsage.calls + 1,
                tokens=WorkspaceUsage.tokens + reserved_tokens,
                cost_micros=WorkspaceUsage.cost_micros + reserved_cost_micros,
            ).where(WorkspaceUsage.id.in_(counters)).execute()
            reservation_id = uuid4().hex
            WorkspaceUsageLedger.create(
                id=reservation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                call_kind=str(model_type or "")[:32],
                model_name=str(model_name or "")[:128],
                period_day=day,
                period_month=month,
                timezone=budget.timezone or DEFAULT_TIMEZONE,
                reserved_tokens=reserved_tokens,
                reserved_cost_micros=reserved_cost_micros,
                status="reserved",
            )
            return reservation_id
    except WorkspaceAccessDenied as exc:
        if refusal is not None:
            refusal["message"] = str(exc)
        raise
    except Exception:
        # No credentials or backend exception details in this public message.
        if refusal is not None:
            refusal["message"] = "使用额度服务暂不可用，请稍后重试"
        raise WorkspaceAccessDenied("使用额度服务暂不可用，请稍后重试") from None


def settle_dispatch(reservation_id, prompt_tokens=0, completion_tokens=0, total_tokens=0, cost_micros=None):
    """Charge what a reserved dispatch ACTUALLY used, at most once.

    The reservation is released down to the actual usage (or topped up when the
    provider reported more than the bound). A second settlement for the same
    reservation is a no-op, which is what makes streaming, retries and
    duplicate callbacks non-double-charging.
    """
    if not reservation_id:
        return {"status": "missing"}
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    total = max(0, int(total_tokens or 0)) or (prompt + completion)
    if prompt + completion != total:
        # The provider reported no usable split; keep the total, drop the split.
        prompt, completion = 0, 0
    try:
        with DB.connection_context(), DB.atomic():
            # Serialize settlement of this reservation the same way the rest of
            # the codebase locks a row (a self-assignment UPDATE), because
            # `FOR UPDATE` is not portable to every supported backend.
            WorkspaceUsageLedger.update(status=WorkspaceUsageLedger.status).where(WorkspaceUsageLedger.id == reservation_id).execute()
            reservation = WorkspaceUsageLedger.get_or_none(WorkspaceUsageLedger.id == reservation_id)
            if reservation is None:
                logging.warning("Settlement for unknown reservation %s ignored", reservation_id)
                return {"status": "missing"}
            if reservation.status != "reserved":
                return {"status": reservation.status, "duplicate": True}
            actual_cost = reservation.reserved_cost_micros if cost_micros is None else max(0, int(cost_micros))
            for period in (reservation.period_day, reservation.period_month):
                counter = WorkspaceUsage.get_or_none(WorkspaceUsage.id == _counter_id(reservation.tenant_id, reservation.user_id, period))
                if counter is None:
                    continue
                WorkspaceUsage.update(
                    tokens=WorkspaceUsage.tokens + (total - reservation.reserved_tokens),
                    prompt_tokens=WorkspaceUsage.prompt_tokens + prompt,
                    completion_tokens=WorkspaceUsage.completion_tokens + completion,
                    cost_micros=WorkspaceUsage.cost_micros + (actual_cost - reservation.reserved_cost_micros),
                ).where(WorkspaceUsage.id == counter.id).execute()
            WorkspaceUsageLedger.update(
                status="settled",
                settled_at=datetime.now(utc_timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                prompt_tokens=prompt,
                completion_tokens=completion,
                tokens=total,
                cost_micros=actual_cost,
            ).where((WorkspaceUsageLedger.id == reservation_id) & (WorkspaceUsageLedger.status == "reserved")).execute()
            return {"status": "settled", "tokens": total, "cost_micros": actual_cost, "released_tokens": reservation.reserved_tokens - total}
    except Exception as exc:  # noqa: BLE001 - accounting must never break the answer
        logging.warning("Failed to settle reservation %s: %s", reservation_id, exc)
        return {"status": "error"}


def release_dispatch(reservation_id):
    """Close a dispatch that reported no usage.

    The reservation STANDS - a timeout or a cancelled stream does not prove the
    provider spent nothing - but it is marked so it cannot be settled later and
    so an operator can tell it apart from a call that is still in flight.
    """
    if not reservation_id:
        return {"status": "missing"}
    try:
        with DB.connection_context(), DB.atomic():
            updated = (
                WorkspaceUsageLedger.update(status="unsettled", settled_at=datetime.now(utc_timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
                .where((WorkspaceUsageLedger.id == reservation_id) & (WorkspaceUsageLedger.status == "reserved"))
                .execute()
            )
            return {"status": "unsettled" if updated else "closed", "updated": updated}
    except Exception as exc:  # noqa: BLE001 - accounting must never break the answer
        logging.warning("Failed to close reservation %s: %s", reservation_id, exc)
        return {"status": "error"}


def resolve_job_actor(tenant_id, initiator_user_id):
    """Which member a detached job's model calls are charged to, or None.

    FENCING: an initiator who is no longer an active member refuses the job -
    queued work must not keep spending on behalf of a revoked identity.

    A job that cannot be attributed at all - no workspace on the task (an
    unknown task shape), or no recorded initiator and no owner row to fall back
    on - is NOT refused: there is no identity to fence, and failing it would
    break work that ran before this attribution existed. It is logged and stays
    unmetered. A job queued with no recorded initiator (a legacy row, or a
    background sync with no authenticated caller) is attributed to the workspace
    owner, who always exists for a live workspace and is exempt from the member
    limits, so an old row keeps running instead of failing for a reason nobody
    can act on.
    """
    if not tenant_id:
        logging.warning("Detached task carries no workspace; its model calls stay unmetered")
        return None
    with DB.connection_context():
        member = UserTenant.get_or_none((UserTenant.tenant_id == tenant_id) & (UserTenant.user_id == initiator_user_id) & (UserTenant.status == "1"))
        if member is not None and member.role in MEMBER_ROLES:
            return initiator_user_id
        if initiator_user_id:
            raise WorkspaceAccessDenied("发起该任务的成员已不在工作区，请由工作区成员重新发起")
        owner = UserTenant.get_or_none((UserTenant.tenant_id == tenant_id) & (UserTenant.role == "owner") & (UserTenant.status == "1"))
        if owner is None:
            logging.warning("Workspace %s has no owner membership; detached task stays unmetered", tenant_id)
            return None
        return owner.user_id


def enter_detached_job(tenant_id, initiator_user_id):
    """Install a detached job's identity; returns a handle for `exit_detached_job`.

    Split out from the context manager so a worker with an existing
    try/finally (the task executor) can use the same single implementation of
    "resolve the actor, set the identity, always reset it".
    """
    actor = resolve_job_actor(tenant_id, initiator_user_id)
    if not actor:
        return None
    return (actor, execution_user.set(actor), execution_refusal.set({}))


def exit_detached_job(tokens):
    if not tokens:
        return
    _actor, user_token, refusal_token = tokens
    if refusal_token is not None:
        execution_refusal.reset(refusal_token)
    if user_token is not None:
        execution_user.reset(user_token)


@contextmanager
def attribute_detached_job(tenant_id, initiator_user_id):
    """Make a worker's model calls belong to the member who queued the job.

    Sets the same authenticated-execution identity a request sets, so every
    LLMBundle call inside the job is metered against the initiator's quota in the
    job's workspace - and so the workspace/membership checks that identity
    already drives apply to detached work too. Yields the actor it resolved, or
    None when the job cannot be attributed at all (see `resolve_job_actor`).
    """
    tokens = enter_detached_job(tenant_id, initiator_user_id)
    try:
        yield tokens[0] if tokens else None
    finally:
        exit_detached_job(tokens)
