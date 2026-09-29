"""Workspace AI usage read model: query-only projections of the accounting records.

The U1 read model answers "what did this workspace/member consume" from the
records the enforcement path ALREADY writes - `workspace_usage` (durable
period counters) and `workspace_usage_ledger` (one row per metered dispatch
attempt, carrying both the reserved bound and what it settled to). It adds no
column, no table and no migration, and it never writes: every function here is
a SELECT.

Frozen accounting semantics (U0/U0.5/U0.6 - do not reinterpret):

* One ledger row is one metered dispatch ATTEMPT, so `attempted_calls` is the
  row count. A budget refusal happens before any row exists, so denials are not
  in the denominator.
* `settled` rows contribute their settled `tokens`/`cost_micros`. `reserved`
  and `unsettled` rows contribute `reserved_tokens`/`reserved_cost_micros` as
  budget OCCUPANCY. Outstanding occupancy is never reported as zero and never
  labelled as provider-reported usage - a stale `reserved` row may be an orphan
  left by a crashed process, so `reserved` does not mean "still running".
* `settled` is an accounting state, never a provider health signal.
* Day and month periods are reported separately and must NEVER be summed: one
  reservation increments both rows.
* Cost is `Estimated model cost`, derived from the model's configured
  per-million-token price - never a provider bill, invoice or actual charge. A
  scope with no pricing evidence reports `null` plus `cost_coverage`, never 0.
* A missing `workspace_budget` row means the BACKEND DEFAULTS apply (exactly
  what `reserve_call` falls back to). It is not zero limits and not unlimited.
* `model_name` is the RECORDED model name only. There is no provider,
  key-instance or workload attribution in these records, and none is inferred.
  An empty name is reported as the explicit `unrecorded` bucket.

Performance guard (no migration in U1): the day/month columns are not indexed,
so every read requires a bounded, validated period window, and every
member/model list is paginated. There is deliberately no unbounded historical
scan endpoint. The index and retention work is backlog, not implementation.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps

from peewee import Case, fn

from api.db.db_models import DB, User, UserTenant, WorkspaceBudget, WorkspaceUsage, WorkspaceUsageLedger
from api.db.services.workspace_budget_service import (
    BUDGET_FIELDS,
    DEFAULT_TIMEZONE,
    FIELDS_ALLOWING_ZERO,
    LIMIT_EXEMPT_ROLES,
    MEMBER_ROLES,
    current_periods,
    policy_revision,
    usage_snapshot,
)
from common.exceptions import WorkspaceAccessDenied

SETTLED = "settled"
RESERVED = "reserved"
UNSETTLED = "unsettled"
OUTSTANDING_STATUSES = (RESERVED, UNSETTLED)
# A live membership row. `UserTenant.status` is a string column, so the literal
# is "1" and not 1 - the same comparison `reserve_call` makes.
LIVE_MEMBERSHIP_STATUS = "1"

COVERAGE_COMPLETE = "complete"
COVERAGE_PARTIAL = "partial"
COVERAGE_UNAVAILABLE = "unavailable"

# The only approved monetary term. `Actual provider bill`, `Invoice` and
# `Actual charge` are forbidden while no provider billing reconciliation exists.
COST_TERM = "Estimated model cost"
COST_UNIT = "micro_usd"

# Bounds. `period_day`/`period_month`/`model_name` carry no index, so an
# unbounded window would be a full-table scan on a table with no retention
# policy. These caps are the read model's own guard, not a schema change.
DEFAULT_RANGE_DAYS = 31
MAX_RANGE_DAYS = 92
DEFAULT_RANGE_MONTHS = 6
MAX_RANGE_MONTHS = 24
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

UNRECORDED_MODEL = "unrecorded"

NOTES_SCOPE = (
    "attempted_calls counts metered dispatch attempts (one usage-ledger row each). "
    "A pre-dispatch budget refusal writes no row and is therefore not counted.",
    "outstanding_reserved_tokens is reserved budget occupancy: it covers attempts still in flight "
    "AND attempts that finished without reporting usage. It is NOT provider-reported usage.",
    "A stale reserved row may be an orphan left by a crashed process. `reserved` does not mean the "
    "call is still running.",
    "status is an accounting state and is never a provider health signal.",
    "Day and month periods are reported separately and must never be summed: one reservation "
    "increments both rows.",
    "model_name is the recorded model name only. Provider, API-key-instance and workload "
    "attribution are not recorded and are not reconstructed.",
)
NOTES_COST = (
    "Estimated model cost is derived from the model's configured per-million-token price "
    "(price_input_per_million / price_output_per_million). It is not a provider bill or invoice.",
    "Rows that consumed tokens but carry no pricing evidence are reported as `null` with "
    "cost_coverage = unavailable, never as 0.",
    "cost_coverage = unavailable means no counted attempt in this scope has pricing evidence; "
    "partial means some do and some do not; complete means all do.",
)

# The value a row contributes to the scope. `tokens` alone would report every
# reserved/unsettled attempt as 0 and systematically under-report the occupancy.
_EFFECTIVE_TOKENS = Case(
    None,
    [(WorkspaceUsageLedger.status == SETTLED, WorkspaceUsageLedger.tokens)],
    WorkspaceUsageLedger.reserved_tokens,
)
# A row whose cost value is grounded in a recorded price.
_SETTLED_EVIDENCE = (WorkspaceUsageLedger.status == SETTLED) & (WorkspaceUsageLedger.cost_micros > 0)
_OUTSTANDING_EVIDENCE = WorkspaceUsageLedger.status.in_(OUTSTANDING_STATUSES) & (WorkspaceUsageLedger.reserved_cost_micros > 0)
_IS_OUTSTANDING = WorkspaceUsageLedger.status.in_(OUTSTANDING_STATUSES)
_NO_SETTLED_EVIDENCE = ~_SETTLED_EVIDENCE
_NO_OUTSTANDING_EVIDENCE = ~_OUTSTANDING_EVIDENCE

# One grouped projection of the ledger. Every row falls into exactly one of
# established / unestablished / zero_usage, so the three counts always add up to
# `attempts` - a partition the tests assert, because a silent gap would hide rows
# from the cost coverage verdict.
_LEDGER_GROUP = (
    fn.COUNT(WorkspaceUsageLedger.id).alias("attempts"),
    fn.SUM(Case(None, [(WorkspaceUsageLedger.status == SETTLED, 1)], 0)).alias("settled_attempts"),
    fn.SUM(Case(None, [(WorkspaceUsageLedger.status == RESERVED, 1)], 0)).alias("reserved_attempts"),
    fn.SUM(Case(None, [(WorkspaceUsageLedger.status == UNSETTLED, 1)], 0)).alias("unsettled_attempts"),
    fn.SUM(Case(None, [(WorkspaceUsageLedger.status == SETTLED, WorkspaceUsageLedger.tokens)], 0)).alias("settled_tokens"),
    fn.SUM(_EFFECTIVE_TOKENS).alias("effective_tokens"),
    fn.SUM(Case(None, [(_IS_OUTSTANDING, WorkspaceUsageLedger.reserved_tokens)], 0)).alias("outstanding_reserved_tokens"),
    fn.SUM(Case(None, [(_SETTLED_EVIDENCE, WorkspaceUsageLedger.cost_micros)], 0)).alias("settled_cost_established_micros"),
    fn.SUM(Case(None, [(_OUTSTANDING_EVIDENCE, WorkspaceUsageLedger.reserved_cost_micros)], 0)).alias("outstanding_cost_established_micros"),
    fn.SUM(Case(None, [(_SETTLED_EVIDENCE, 1)], 0)).alias("settled_cost_established_rows"),
    fn.SUM(Case(None, [(_OUTSTANDING_EVIDENCE, 1)], 0)).alias("outstanding_cost_established_rows"),
    fn.SUM(Case(None, [((WorkspaceUsageLedger.status == SETTLED) & _NO_SETTLED_EVIDENCE & (WorkspaceUsageLedger.tokens > 0), 1)], 0)).alias("settled_cost_unestablished_rows"),
    fn.SUM(Case(None, [(_IS_OUTSTANDING & _NO_OUTSTANDING_EVIDENCE & (WorkspaceUsageLedger.reserved_tokens > 0), 1)], 0)).alias("outstanding_cost_unestablished_rows"),
    fn.SUM(
        Case(
            None,
            [
                (
                    ((WorkspaceUsageLedger.status == SETTLED) & _NO_SETTLED_EVIDENCE & (WorkspaceUsageLedger.tokens == 0))
                    | (_IS_OUTSTANDING & _NO_OUTSTANDING_EVIDENCE & (WorkspaceUsageLedger.reserved_tokens == 0)),
                    1,
                )
            ],
            0,
        )
    ).alias("zero_usage_rows"),
)


@dataclass(frozen=True, slots=True)
class ReadScope:
    """A validated read scope: WHOSE rows, in WHICH workspace, at WHICH role.

    The three identity domains stay separate. `workspace_id` is a workspace
    (tenant) key and `actor_user_id` is a member key; neither is ever derived
    from the other, because a personal workspace's id can equal its owner's
    user id, so equality proves nothing.
    """

    workspace_id: str
    actor_user_id: str
    role: str
    workspace_wide: bool
    subject_user_id: str | None
    timezone: str
    limits_source: str

    @property
    def is_manager(self):
        return self.role in LIMIT_EXEMPT_ROLES

    def to_dict(self):
        return {
            "workspace_id": self.workspace_id,
            "actor_user_id": self.actor_user_id,
            "role": self.role,
            "workspace_wide": self.workspace_wide,
            "subject_user_id": self.subject_user_id,
            "timezone": self.timezone,
            "limits_source": self.limits_source,
        }


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


def _in_db_context(func):
    """Run a read inside `DB.connection_context()`.

    `DB` is resolved from this module at CALL time (not at decoration time) so a
    test can bind the module to its own SQLite database, which is the same
    pattern `workspace_budget_service` uses for its enforcing path. The context
    is re-entrant, so a view may call another decorated function.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        with DB.connection_context():
            return func(*args, **kwargs)

    return wrapper


def _as_day(value, field):
    if not isinstance(value, str) or len(value) != 10:
        raise WorkspaceAccessDenied(f"请填写有效的日期（{field}，格式 YYYY-MM-DD）")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise WorkspaceAccessDenied(f"请填写有效的日期（{field}，格式 YYYY-MM-DD）") from None


def _as_month(value, field):
    if not isinstance(value, str) or len(value) != 7:
        raise WorkspaceAccessDenied(f"请填写有效的月份（{field}，格式 YYYY-MM）")
    try:
        moment = datetime.strptime(value, "%Y-%m")
    except ValueError:
        raise WorkspaceAccessDenied(f"请填写有效的月份（{field}，格式 YYYY-MM）") from None
    return moment.date()


def _to_period_day(value):
    return value.strftime("%Y-%m-%d")


def _to_period_month(value):
    return value.strftime("%Y-%m")


def resolve_day_range(start_day=None, end_day=None, timezone_name=DEFAULT_TIMEZONE, now=None, max_days=MAX_RANGE_DAYS):
    """A validated, BOUNDED list of `period_day` keys, oldest first.

    There is no unbounded mode: an omitted range means the default window, and a
    range longer than `max_days` is refused rather than served, because the
    period column is unindexed and this table has no retention policy.
    """
    today = current_periods(timezone_name, now=now)[0]
    end = _as_day(end_day, "end_day") if end_day is not None else _as_day(today, "end_day")
    if start_day is not None:
        start = _as_day(start_day, "start_day")
    else:
        start = end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise WorkspaceAccessDenied("start_day 不能晚于 end_day")
    days = (end - start).days + 1
    if days > max_days:
        raise WorkspaceAccessDenied(f"查询区间最长为 {max_days} 天，请缩小范围或分页查看")
    return [_to_period_day(start + timedelta(days=offset)) for offset in range(days)]


def resolve_month_range(start_month=None, end_month=None, timezone_name=DEFAULT_TIMEZONE, now=None, max_months=MAX_RANGE_MONTHS):
    """A validated, bounded list of `period_month` keys, oldest first."""
    this_month = current_periods(timezone_name, now=now)[1]
    end = _as_month(end_month, "end_month") if end_month is not None else _as_month(this_month, "end_month")
    start = _as_month(start_month, "start_month") if start_month is not None else None
    if start is None:
        months_back = DEFAULT_RANGE_MONTHS - 1
        start = end
        for _ in range(months_back):
            start = (start - timedelta(days=1)).replace(day=1)
    start = start.replace(day=1)
    if start > end:
        raise WorkspaceAccessDenied("start_month 不能晚于 end_month")
    months = (end.year - start.year) * 12 + (end.month - start.month) + 1
    if months > max_months:
        raise WorkspaceAccessDenied(f"查询区间最长为 {max_months} 个月，请缩小范围或分页查看")
    keys = []
    cursor = start
    for _ in range(months):
        keys.append(_to_period_month(cursor))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    return keys


def resolve_page(limit=None, offset=None):
    """A bounded page window, so a member/model list can never be unbounded."""
    try:
        size = DEFAULT_PAGE_SIZE if limit is None or limit == "" else int(limit)
    except (TypeError, ValueError):
        raise WorkspaceAccessDenied("limit 必须是整数") from None
    try:
        skip = 0 if offset is None or offset == "" else int(offset)
    except (TypeError, ValueError):
        raise WorkspaceAccessDenied("offset 必须是整数") from None
    if size < 1:
        raise WorkspaceAccessDenied("limit 必须大于 0")
    if size > MAX_PAGE_SIZE:
        raise WorkspaceAccessDenied(f"limit 最大为 {MAX_PAGE_SIZE}")
    if skip < 0:
        raise WorkspaceAccessDenied("offset 不能为负数")
    return size, skip


# --------------------------------------------------------------------------- #
# scope + budget
# --------------------------------------------------------------------------- #


def _budget_row(workspace_id):
    """The workspace's limit row, or the backend defaults.

    A workspace that never configured limits has no row, and enforcement then
    falls back to the model's own defaults (see `reserve_call`). Reporting that
    as "all limits are 0" would claim "not enforced" and reporting it as
    unlimited would be worse, so the source is always returned alongside.
    """
    row = WorkspaceBudget.get_or_none(WorkspaceBudget.tenant_id == workspace_id)
    if row is None:
        return WorkspaceBudget(), "backend_defaults"
    return row, "workspace_budget_row"


def _live_membership(workspace_id, user_id):
    if not user_id:
        return None
    return UserTenant.get_or_none(
        (UserTenant.tenant_id == workspace_id) & (UserTenant.user_id == user_id) & (UserTenant.status == LIVE_MEMBERSHIP_STATUS)
    )


@_in_db_context
def resolve_read_scope(actor_user_id, workspace_id, member_user_id=None, workspace_wide=False):
    """Validate the caller, the workspace and the requested subject.

    Live membership is re-checked on every call: a cached grant, a creator-only
    shortcut and a removed member's token must not open this read path. NORMAL
    callers are hard-scoped to their own rows and may not ask for a workspace
    aggregate; OWNER/ADMIN may read their own workspace aggregate and member
    breakdown. Nothing here compares a user id with a workspace id.
    """
    if not actor_user_id or not isinstance(actor_user_id, str):
        raise WorkspaceAccessDenied("请先登录")
    if not workspace_id or not isinstance(workspace_id, str):
        raise WorkspaceAccessDenied("请指定要查询的工作区")

    membership = _live_membership(workspace_id, actor_user_id)
    if membership is None or membership.role not in MEMBER_ROLES:
        raise WorkspaceAccessDenied("您已无权访问此工作区")
    role = membership.role

    if role in LIMIT_EXEMPT_ROLES:
        if workspace_wide and member_user_id:
            raise WorkspaceAccessDenied("请勿同时指定工作区聚合与单个成员")
        subject = None if workspace_wide else (member_user_id or actor_user_id)
    else:
        if workspace_wide:
            raise WorkspaceAccessDenied("仅工作区管理员可以查看工作区聚合使用量")
        if member_user_id and member_user_id != actor_user_id:
            raise WorkspaceAccessDenied("仅工作区管理员可以查看其他成员的使用量")
        # NORMAL reads own rows only, whatever the request asked for.
        subject = actor_user_id

    budget, limits_source = _budget_row(workspace_id)
    return ReadScope(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        role=role,
        workspace_wide=subject is None,
        subject_user_id=subject,
        timezone=budget.timezone or DEFAULT_TIMEZONE,
        limits_source=limits_source,
    )


def _subject_role(workspace_id, user_id):
    """The subject's live role, or None when they are no longer a member."""
    membership = _live_membership(workspace_id, user_id)
    return membership.role if membership is not None else None


# --------------------------------------------------------------------------- #
# aggregates
# --------------------------------------------------------------------------- #


def _ledger_predicate(period_column, periods, user_id=None, workspace_id=None):
    conditions = period_column.in_(list(periods))
    if workspace_id:
        conditions = conditions & (WorkspaceUsageLedger.tenant_id == workspace_id)
    if user_id:
        conditions = conditions & (WorkspaceUsageLedger.user_id == user_id)
    return conditions


def _count(value):
    return int(value or 0)


def _coverage(established_rows, unestablished_rows):
    """The frozen three-state pricing coverage of a set of rows.

    `unavailable` also covers the empty set: with nothing priced there is
    nothing to establish, and claiming `complete` would read as "cost is known".
    """
    if established_rows == 0:
        return COVERAGE_UNAVAILABLE
    if unestablished_rows == 0:
        return COVERAGE_COMPLETE
    return COVERAGE_PARTIAL


def _accounting(row):
    """The frozen metric block for one group of ledger rows.

    The two cost figures are gated INDEPENDENTLY on their own pricing evidence.
    A scope can hold a priced settled row and an unpriced reservation at the same
    time, and in that case the outstanding figure must stay null: reporting 0
    would claim that an occupancy whose price is unknown costs nothing.
    """
    attempts = _count(row.get("attempts"))
    settled_attempts = _count(row.get("settled_attempts"))
    reserved_attempts = _count(row.get("reserved_attempts"))
    unsettled_attempts = _count(row.get("unsettled_attempts"))
    outstanding_attempts = reserved_attempts + unsettled_attempts
    recognised = settled_attempts + outstanding_attempts
    settled_established = _count(row.get("settled_cost_established_rows"))
    outstanding_established = _count(row.get("outstanding_cost_established_rows"))
    settled_unestablished = _count(row.get("settled_cost_unestablished_rows"))
    outstanding_unestablished = _count(row.get("outstanding_cost_unestablished_rows"))
    return {
        "attempted_calls": attempts,
        "settled_attempts": settled_attempts,
        "reserved_attempts": reserved_attempts,
        "unsettled_attempts": unsettled_attempts,
        "outstanding_attempts": outstanding_attempts,
        "unrecognised_status_attempts": attempts - recognised,
        "settled_tokens": _count(row.get("settled_tokens")),
        "outstanding_reserved_tokens": _count(row.get("outstanding_reserved_tokens")),
        "effective_tokens": _count(row.get("effective_tokens")),
        "settled_estimated_cost_micros": _count(row.get("settled_cost_established_micros")) if settled_established else None,
        "outstanding_reserved_cost_micros": _count(row.get("outstanding_cost_established_micros")) if outstanding_established else None,
        "cost_coverage": _coverage(settled_established + outstanding_established, settled_unestablished + outstanding_unestablished),
        "settled_cost_coverage": _coverage(settled_established, settled_unestablished),
        "outstanding_cost_coverage": _coverage(outstanding_established, outstanding_unestablished),
        "cost_established_rows": settled_established + outstanding_established,
        "cost_unestablished_rows": settled_unestablished + outstanding_unestablished,
        "zero_usage_rows": _count(row.get("zero_usage_rows")),
    }


def _cost_block(accounting):
    """The cost envelope: the term, the unit, the coverage and why."""
    return {
        "term": COST_TERM,
        "unit": COST_UNIT,
        "coverage": accounting["cost_coverage"],
        "settled_coverage": accounting["settled_cost_coverage"],
        "outstanding_coverage": accounting["outstanding_cost_coverage"],
        "notes": list(NOTES_COST),
    }


def _ledger_row(predicate, group_by=None):
    query = WorkspaceUsageLedger.select(*_LEDGER_GROUP).where(predicate)
    if group_by is not None:
        query = query.group_by(*group_by)
    return query.dicts()


def _aggregate(predicate):
    rows = list(_ledger_row(predicate))
    return rows[0] if rows else {}


def _counter_totals(workspace_id, periods, user_id=None):
    """The durable period counters for the same period keys.

    These are the enforcement read source: their `tokens`/`cost_micros` are
    budget OCCUPANCY (reservation plus in-flight), not settled actuals, and the
    day and month rows overlap so only ONE kind of period key may be summed at
    a time.
    """
    query = WorkspaceUsage.select(
        fn.COUNT(WorkspaceUsage.id).alias("rows"),
        fn.SUM(WorkspaceUsage.calls).alias("calls"),
        fn.SUM(WorkspaceUsage.tokens).alias("tokens"),
        fn.SUM(WorkspaceUsage.cost_micros).alias("cost_micros"),
    ).where((WorkspaceUsage.tenant_id == workspace_id) & WorkspaceUsage.period.in_(list(periods)))
    if user_id:
        query = query.where(WorkspaceUsage.user_id == user_id)
    rows = list(query.dicts())
    row = rows[0] if rows else {}
    return {
        "counter_rows": _count(row.get("rows")),
        "counter_calls": _count(row.get("calls")),
        "counter_tokens": _count(row.get("tokens")),
        "counter_cost_micros": _count(row.get("cost_micros")),
    }


def _reconciliation(accounting, counters, member_attempts=None):
    """Counters vs ledger vs member breakdown, reported rather than reconciled.

    There is no automatic counter/ledger reconciliation job, and settlement
    skips a counter row an operator deleted, so these figures CAN diverge. The
    read model surfaces the divergence instead of silently choosing a side.
    """
    calls_match = accounting["attempted_calls"] == counters["counter_calls"]
    tokens_match = accounting["effective_tokens"] == counters["counter_tokens"]
    block = {
        "ledger_attempted_calls": accounting["attempted_calls"],
        "counter_calls": counters["counter_calls"],
        "calls_consistent": calls_match,
        "ledger_effective_tokens": accounting["effective_tokens"],
        "counter_tokens": counters["counter_tokens"],
        "tokens_consistent": tokens_match,
        # How many counter rows were summed. A day window reads DAY rows and a
        # month window reads MONTH rows; seeing more rows than that would mean the
        # two overlapping kinds had been added together and double counted.
        "counter_rows": counters["counter_rows"],
        "semantics": ("counters are budget occupancy (reservation plus in-flight); the ledger is the "
                      "per-attempt record. Both are reported, never merged."),
    }
    if member_attempts is not None:
        block["member_breakdown_attempted_calls"] = member_attempts
        block["member_breakdown_consistent"] = member_attempts == accounting["attempted_calls"]
    return block


def _timezones_in_scope(predicate):
    rows = list(WorkspaceUsageLedger.select(WorkspaceUsageLedger.timezone).where(predicate).distinct().dicts())
    return sorted({row["timezone"] for row in rows if row.get("timezone") is not None})


def _nicknames(user_ids):
    """Display names for a page of members.

    Deliberately a separate lookup rather than a join: a member's name is a
    MUTABLE dimension and an INNER JOIN would silently drop the history of a
    deleted user, which is exactly the history this read model must preserve.
    """
    if not user_ids:
        return {}
    rows = User.select(User.id, User.nickname).where(User.id.in_(list(user_ids))).dicts()
    return {row["id"]: row.get("nickname") for row in rows}


def _envelope(view, scope, period, accounting, counters=None, member_attempts=None, data=None):
    payload = {
        "view": view,
        "scope": scope.to_dict(),
        "period": period,
        "accounting": accounting,
        "cost": _cost_block(accounting),
        "notes": list(NOTES_SCOPE),
    }
    if counters is not None:
        payload["reconciliation"] = _reconciliation(accounting, counters, member_attempts)
    if data is not None:
        payload["data"] = data
    return payload


def _period_block(day_keys=None, month_keys=None, days_with_activity=None):
    block = {}
    if day_keys:
        block.update({"kind": "day", "start_day": day_keys[0], "end_day": day_keys[-1], "days": len(day_keys)})
    elif month_keys:
        block.update({"kind": "month", "start_month": month_keys[0], "end_month": month_keys[-1], "months": len(month_keys)})
    if days_with_activity is not None:
        block["days_with_activity"] = days_with_activity
    return block


def _days_with_activity(predicate):
    rows = list(WorkspaceUsageLedger.select(WorkspaceUsageLedger.period_day).where(predicate).distinct().dicts())
    return len({row["period_day"] for row in rows})


# --------------------------------------------------------------------------- #
# views
# --------------------------------------------------------------------------- #


@_in_db_context
def my_usage(actor_user_id, workspace_id, start_day=None, end_day=None, now=None):
    """The caller's own metered usage over a bounded day window.

    A NORMAL member's own usage is the only usage they may read; a manager
    reading their own rows goes through the same function.
    """
    scope = resolve_read_scope(actor_user_id, workspace_id)
    day_keys = resolve_day_range(start_day, end_day, scope.timezone, now=now)
    predicate = _ledger_predicate(WorkspaceUsageLedger.period_day, day_keys, user_id=scope.actor_user_id, workspace_id=workspace_id)
    accounting = _accounting(_aggregate(predicate))
    period = _period_block(day_keys=day_keys, days_with_activity=_days_with_activity(predicate))
    period["timezone"] = scope.timezone
    period["timezones_in_scope"] = _timezones_in_scope(predicate)
    counters = _counter_totals(workspace_id, day_keys, user_id=scope.actor_user_id)
    return _envelope("my_usage", scope, period, accounting, counters=counters)


@_in_db_context
def workspace_summary(actor_user_id, workspace_id, start_day=None, end_day=None, now=None):
    """The workspace aggregate over a bounded day window (OWNER/ADMIN only)."""
    scope = resolve_read_scope(actor_user_id, workspace_id, workspace_wide=True)
    day_keys = resolve_day_range(start_day, end_day, scope.timezone, now=now)
    predicate = _ledger_predicate(WorkspaceUsageLedger.period_day, day_keys, workspace_id=workspace_id)
    accounting = _accounting(_aggregate(predicate))
    period = _period_block(day_keys=day_keys, days_with_activity=_days_with_activity(predicate))
    period["timezone"] = scope.timezone
    period["timezones_in_scope"] = _timezones_in_scope(predicate)
    counters = _counter_totals(workspace_id, day_keys)

    members = list(
        WorkspaceUsageLedger.select(WorkspaceUsageLedger.user_id, *_LEDGER_GROUP)
        .where(predicate)
        .group_by(WorkspaceUsageLedger.user_id)
        .dicts()
    )
    models = list(
        WorkspaceUsageLedger.select(WorkspaceUsageLedger.model_name, *_LEDGER_GROUP)
        .where(predicate)
        .group_by(WorkspaceUsageLedger.model_name)
        .dicts()
    )
    data = {
        "member_count": len(members),
        "recorded_model_count": len({row["model_name"] for row in models if row.get("model_name")}),
        "unrecorded_model_attempts": sum(_count(row.get("attempts")) for row in models if not row.get("model_name")),
        "note": ("The aggregate covers every member of this workspace, including OWNER/ADMIN rows and the "
                 "retained history of members who have since been removed."),
    }
    member_attempts = sum(_count(row.get("attempts")) for row in members)
    return _envelope("workspace_summary", scope, period, accounting, counters=counters, member_attempts=member_attempts, data=data)


@_in_db_context
def member_breakdown(actor_user_id, workspace_id, start_day=None, end_day=None, limit=None, offset=None, now=None):
    """Per-member usage for the workspace, paginated (OWNER/ADMIN only)."""
    scope = resolve_read_scope(actor_user_id, workspace_id, workspace_wide=True)
    day_keys = resolve_day_range(start_day, end_day, scope.timezone, now=now)
    size, skip = resolve_page(limit, offset)
    predicate = _ledger_predicate(WorkspaceUsageLedger.period_day, day_keys, workspace_id=workspace_id)

    total_members = WorkspaceUsageLedger.select(fn.COUNT(fn.DISTINCT(WorkspaceUsageLedger.user_id))).where(predicate).scalar() or 0
    rows = list(
        WorkspaceUsageLedger.select(WorkspaceUsageLedger.user_id, *_LEDGER_GROUP)
        .where(predicate)
        .group_by(WorkspaceUsageLedger.user_id)
        .order_by(fn.COUNT(WorkspaceUsageLedger.id).desc(), WorkspaceUsageLedger.user_id.asc())
        .limit(size)
        .offset(skip)
        .dicts()
    )
    names = _nicknames([row["user_id"] for row in rows])
    members = []
    for row in rows:
        role = _subject_role(workspace_id, row["user_id"])
        members.append(
            {
                "user_id": row["user_id"],
                "nickname": names.get(row["user_id"]),
                "name_available": row["user_id"] in names,
                "live_member": role is not None,
                "role": role,
                "accounting": _accounting(row),
            }
        )

    period = _period_block(day_keys=day_keys, days_with_activity=_days_with_activity(predicate))
    period["timezone"] = scope.timezone
    accounting = _accounting(_aggregate(predicate))
    data = {
        "members": members,
        "total_members": _count(total_members),
        "limit": size,
        "offset": skip,
        "truncated": _count(total_members) > skip + len(members),
        "not_answered": ("A member whose user row no longer exists keeps their usage history here, keyed by "
                         "user_id, with name_available = false. Membership names are never joined destructively."),
    }
    return _envelope("member_breakdown", scope, period, accounting, data=data)


def _series(scope, keys, column, kind, month=False):
    """One bucket per period key in a bounded window, oldest first."""
    predicate = _ledger_predicate(column, keys, workspace_id=scope.workspace_id)
    grouped = {
        row[column.name]: row
        for row in WorkspaceUsageLedger.select(column, *_LEDGER_GROUP).where(predicate).group_by(column).dicts()
    }
    buckets = []
    for key in keys:
        accounting = _accounting(grouped.get(key, {}))
        buckets.append({"period": key, "attempted_calls": accounting["attempted_calls"], "accounting": accounting})
    period = _period_block(day_keys=None if month else keys, month_keys=keys if month else None)
    period.update({"timezone": scope.timezone, "timezones_in_scope": _timezones_in_scope(predicate)})
    if not month:
        period["days_with_activity"] = sum(1 for bucket in buckets if bucket["attempted_calls"])
    data = {
        "buckets": buckets,
        "granularity": kind,
        "zero_filled": ("Every period in the requested window is present. A bucket with attempted_calls = 0 "
                        "means no metered attempt was recorded in it - not that usage was measured as zero "
                        "before the ledger existed."),
    }
    accounting = _accounting(_aggregate(predicate))
    # The same period keys are compared against the durable counters. A day
    # window reads DAY rows and a month window reads MONTH rows; the two are
    # never combined, because one reservation increments both.
    counters = _counter_totals(scope.workspace_id, keys)
    return _envelope(f"{kind}_series", scope, period, accounting, counters=counters, data=data)


@_in_db_context
def daily_series(actor_user_id, workspace_id, start_day=None, end_day=None, now=None):
    """Per-day usage over a bounded day window (OWNER/ADMIN only)."""
    scope = resolve_read_scope(actor_user_id, workspace_id, workspace_wide=True)
    day_keys = resolve_day_range(start_day, end_day, scope.timezone, now=now)
    return _series(scope, day_keys, WorkspaceUsageLedger.period_day, "daily")


@_in_db_context
def monthly_series(actor_user_id, workspace_id, start_month=None, end_month=None, now=None):
    """Per-month usage over a bounded month window (OWNER/ADMIN only).

    Month buckets are reported on their own: they must never be added to the day
    buckets, because one reservation increments both.
    """
    scope = resolve_read_scope(actor_user_id, workspace_id, workspace_wide=True)
    month_keys = resolve_month_range(start_month, end_month, scope.timezone, now=now)
    return _series(scope, month_keys, WorkspaceUsageLedger.period_month, "monthly", month=True)


@_in_db_context
def recorded_model_breakdown(actor_user_id, workspace_id, start_day=None, end_day=None, limit=None, offset=None, now=None):
    """Usage grouped by the RECORDED model name, paginated (OWNER/ADMIN only).

    The name is what the ledger recorded - a bare model name, not a configured
    provider instance. Provider, key-instance and workload attribution are not
    recorded and are never inferred; they are reported as null. Rows with no
    recorded name (an extra provider round charged as an extra call) appear in
    the explicit `unrecorded` bucket.
    """
    scope = resolve_read_scope(actor_user_id, workspace_id, workspace_wide=True)
    day_keys = resolve_day_range(start_day, end_day, scope.timezone, now=now)
    size, skip = resolve_page(limit, offset)
    predicate = _ledger_predicate(WorkspaceUsageLedger.period_day, day_keys, workspace_id=workspace_id)

    total_models = WorkspaceUsageLedger.select(fn.COUNT(fn.DISTINCT(WorkspaceUsageLedger.model_name))).where(predicate).scalar() or 0
    rows = list(
        WorkspaceUsageLedger.select(WorkspaceUsageLedger.model_name, *_LEDGER_GROUP)
        .where(predicate)
        .group_by(WorkspaceUsageLedger.model_name)
        .order_by(fn.COUNT(WorkspaceUsageLedger.id).desc(), WorkspaceUsageLedger.model_name.asc())
        .limit(size)
        .offset(skip)
        .dicts()
    )
    models = []
    for row in rows:
        recorded = row.get("model_name") or ""
        models.append(
            {
                "recorded_model_name": recorded or None,
                "bucket": recorded or UNRECORDED_MODEL,
                "attribution": "recorded_model_name_only",
                "provider": None,
                "key_instance": None,
                "workload": None,
                "accounting": _accounting(row),
            }
        )

    period = _period_block(day_keys=day_keys, days_with_activity=_days_with_activity(predicate))
    period["timezone"] = scope.timezone
    accounting = _accounting(_aggregate(predicate))
    data = {
        "models": models,
        "total_buckets": _count(total_models),
        "limit": size,
        "offset": skip,
        "truncated": _count(total_models) > skip + len(models),
        "not_answered": ("provider, key_instance and workload are null by design: the records do not carry "
                         "them and this read model does not reconstruct them. An empty recorded name is the "
                         f"`{UNRECORDED_MODEL}` bucket."),
    }
    return _envelope("recorded_model_breakdown", scope, period, accounting, data=data)


@_in_db_context
def quota_status(actor_user_id, workspace_id, member_user_id=None, now=None):
    """The workspace's limits against the current period's occupancy.

    No range parameter: the limits apply to the current day/month periods only,
    which keeps this endpoint bounded by construction. The rolling-minute limit
    is reported as a limit whose usage is NOT available here - it lives in
    Redis, which this read model never reads.
    """
    scope = resolve_read_scope(actor_user_id, workspace_id, member_user_id=member_user_id)
    subject = scope.subject_user_id or scope.actor_user_id
    budget, limits_source = _budget_row(workspace_id)
    subject_role = _subject_role(workspace_id, subject)
    exempt = None if subject_role is None else subject_role in LIMIT_EXEMPT_ROLES

    snapshot = usage_snapshot(workspace_id, subject, now=now)
    current_day, current_month = snapshot["period_day"], snapshot["period_month"]
    limits = {field: int(getattr(budget, field) or 0) for field in BUDGET_FIELDS}

    standing = {}
    for field, used_value in (
        ("calls_per_minute", None),
        ("calls_per_day", snapshot["day"]["calls"]),
        ("calls_per_month", snapshot["month"]["calls"]),
        ("tokens_per_day", snapshot["day"]["tokens"]),
        ("tokens_per_month", snapshot["month"]["tokens"]),
        ("cost_micros_per_day", snapshot["day"]["cost_micros"]),
        ("cost_micros_per_month", snapshot["month"]["cost_micros"]),
    ):
        limit = limits[field]
        # Enforcement treats a 0 limit as "this dimension is not enforced"
        # (`if call_limit and ...`), so `enforced` follows the same rule and a
        # 0 limit is never rendered as "zero remaining".
        entry = {"limit": limit, "enforced": limit > 0, "used": used_value, "exempt": exempt}
        if field == "calls_per_minute":
            entry["used"] = None
            entry["used_available"] = False
            entry["note"] = "The rolling minute is tracked in Redis and is not read by this read model."
        else:
            entry["used_available"] = True
            entry["remaining"] = None if not entry["enforced"] else limit - int(used_value or 0)
        standing[field] = entry

    month_snap = _aggregate(_ledger_predicate(WorkspaceUsageLedger.period_month, [current_month], user_id=subject, workspace_id=workspace_id))
    accounting = _accounting(month_snap)

    data = {
        "limits": limits,
        "limits_scope": "per_member",
        "limits_source": limits_source,
        # The POLICY revision a write must echo back as `If-Match`. It covers the
        # limits and timezone only - never the counters or the ledger - so every
        # metered model call does not manufacture a conflict for a policy editor.
        "policy_revision": policy_revision(workspace_id),
        "zero_means_unlimited": list(FIELDS_ALLOWING_ZERO),
        "unit": "model_calls",
        "token_unit": "tokens",
        "cost_unit": COST_UNIT,
        "applies_to": "normal",
        "subject": {
            "user_id": subject,
            "role": subject_role,
            "live_member": subject_role is not None,
            "exempt": exempt,
        },
        "standing": standing,
        "current_month_accounting": accounting,
        "not_answered": (
            "Limits are PER MEMBER rules, not a workspace-wide monetary cap. OWNER/ADMIN are exempt from "
            "them but their attempts are still recorded. A limit of 0 on the token/cost dimensions means the "
            "dimension is NOT ENFORCED - it never means 'zero remaining'. A cost limit can only be enforced "
            "for models that carry pricing."
        ),
    }
    if subject_role is None:
        data["not_answered"] += " This member is no longer active in the workspace, so the limits no longer apply to them."

    workspace_occupancy = None
    if scope.is_manager:
        workspace_snapshot = usage_snapshot(workspace_id, None, now=now)
        workspace_occupancy = {
            "day": workspace_snapshot["day"],
            "month": workspace_snapshot["month"],
            "comparable_to_limits": False,
            "note": ("Workspace-wide occupancy across every member. It is NOT comparable to the per-member "
                     "limits above; do not present it as a percentage of them."),
        }

    period = {"day": current_day, "month": current_month, "timezone": snapshot["timezone"]}
    payload = _envelope("quota_status", scope, period, accounting, data=data)
    payload["data"]["workspace_occupancy"] = workspace_occupancy
    return payload


VIEWS = {
    "my_usage": my_usage,
    "workspace_summary": workspace_summary,
    "member_breakdown": member_breakdown,
    "daily_series": daily_series,
    "monthly_series": monthly_series,
    "recorded_model_breakdown": recorded_model_breakdown,
    "quota_status": quota_status,
}


def build_view(view, actor_user_id, workspace_id, **params):
    """Dispatch a named view; unknown views are refused, never guessed."""
    builder = VIEWS.get(view)
    if builder is None:
        raise WorkspaceAccessDenied(f"未知的使用量视图：{view}")
    logging.debug("workspace usage read model: view=%s workspace=%s actor=%s", view, workspace_id, actor_user_id)
    return builder(actor_user_id, workspace_id, **params)
