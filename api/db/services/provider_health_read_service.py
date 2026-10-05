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
"""Read a workspace's provider incidents for the administrators of that workspace.

Three rules shape this module.

**It reads, and only reads.** Nothing here writes, resolves, acknowledges or
touches a credential. Reading an incident must never close it: a workspace whose
administrator opens this page has learned something, it has not fixed anything, so
`resolution_kind` stays whatever the observation path recorded.

**It is an allowlist, not a model dump.** `INCIDENT_FIELDS` names every field this
API may emit and `_project` reads exactly those. The incident row has no secret
column today, and a projection that cannot name a column cannot start exposing one
the day a migration adds it - which is why `__data__`, `dict(row)` and any
"serialize the model" helper are absent.

**It refuses rather than degrades.** The caller must hold OWNER or ADMIN on the
workspace named in the path, checked live on every request through the same
predicate the tenant and workspace APIs use. Holding a membership is not holding a
role, and a workspace this caller may not administer is refused the same way
whether or not it exists, so this read cannot be used to enumerate workspaces.
"""

from datetime import datetime, timedelta, timezone as utc_timezone
from functools import wraps

from api.db.db_models import DB, ProviderHealthEvent
from api.db.services.provider_health_service import ACTIVE, RESOLVED
from api.db.services.user_service import UserTenantService
from api.db.services.workspace_usage_read_service import resolve_page
from common.exceptions import WorkspaceAccessDenied

#: How far back a resolved incident is still part of this view. The store keeps
#: every incident it ever recorded, so an unbounded read of the resolved side would
#: grow with the workspace's whole outage history. The window makes the bound an
#: explicit, named fact rather than an implicit one: what falls outside it is not
#: lost, it is simply not part of "recently resolved".
RECENTLY_RESOLVED_WINDOW_DAYS = 7

#: The widest window a caller may ask for. Still a bound, so "recently resolved"
#: cannot be widened into "all history" - the store keeps history, this view does
#: not serve it.
MAX_WINDOW_DAYS = 90

#: The hard ceiling on how many rows either side of the view may load. The lists are
#: additionally paged by `limit`/`offset`; this bounds the work a single request can
#: do even when the caller asks for the largest page allowed.
MAX_ROWS_PER_STATE = 200

#: The ONLY fields this API may emit. Everything else the incident row carries -
#: including anything a future migration adds - stays in the store.
INCIDENT_FIELDS = (
    "id",
    "provider_id",
    "instance_id",
    "provider_name",
    "capability",
    "error_class",
    "severity",
    "occurred_at",
    "last_seen_at",
    "occurrence_count",
    "affected_operation",
    "user_safe_message",
    "state",
    "resolved_at",
    "resolution_kind",
)

NOT_ANSWERED = (
    "incidents are provider RECORDED events, not a health verdict. An empty list means no incident was "
    "recorded for this workspace; it does not assert that any provider is healthy, and nothing here polls "
    "a provider to find out.",
    "active_count counts INCIDENTS, not occurrences: one incident whose occurrence_count is 30 counts once.",
    "recently resolved is a bounded window, stated in the response. Resolved incidents older than it are "
    "kept in the store and are simply not part of this view.",
    "Provider Health never fetches a provider's account, so this view carries no balance, no remaining "
    "quota, no rate-limit headroom and no latency - none of those is recorded, so none can be shown.",
    "Reading this view does not resolve, acknowledge or otherwise change an incident.",
)


def _in_db_context(func):
    """Run a read inside `DB.connection_context()`.

    `DB` is resolved from this module at CALL time (not at decoration time) so a
    test can bind the module to its own SQLite database, the same pattern
    `workspace_usage_read_service` uses.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        with DB.connection_context():
            return func(*args, **kwargs)

    return wrapper


def require_workspace_manager(actor_user_id, workspace_id):
    """The caller must hold OWNER or ADMIN on the workspace it is reading.

    This is the same predicate (`UserTenantService.can_manage_tenant`, live OWNER or
    ADMIN rows only) and the same refusal the tenant API uses for its admin-only
    routes, raised as `WorkspaceAccessDenied` so the route answers the standard
    HTTP 200 + code 108. It is deliberately NOT a new permission model: a NORMAL
    member fails it exactly as it fails every other admin-only workspace read.

    A workspace the caller cannot administer is refused identically whether or not
    it exists, so this cannot be used to discover which workspace ids are real.
    """
    if not actor_user_id or not isinstance(actor_user_id, str):
        raise WorkspaceAccessDenied("请先登录")
    if not workspace_id or not isinstance(workspace_id, str):
        raise WorkspaceAccessDenied("请指定要查询的工作区")
    if not UserTenantService.can_manage_tenant(actor_user_id, workspace_id):
        raise WorkspaceAccessDenied("仅工作区所有者或管理员可以查看 AI 服务健康事件")


def _ts(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _project(row):
    """One incident, field by field from the allowlist above.

    Every field is named here on purpose. `row.__data__`, `dict(row)` and
    `model_to_dict` would emit whatever the table happens to hold, which turns a
    future column into an accidental API field.
    """
    return {
        "id": row.id,
        "provider_id": row.provider_id or "",
        "instance_id": row.instance_id or "",
        "provider_name": row.provider_name or "",
        "capability": row.capability or "",
        "error_class": row.error_class or "",
        "severity": row.severity or "",
        "occurred_at": _ts(row.occurred_at),
        "last_seen_at": _ts(row.last_seen_at),
        "occurrence_count": int(row.occurrence_count or 0),
        "affected_operation": row.affected_operation or "",
        "user_safe_message": row.user_safe_message or "",
        "state": row.state or "",
        "resolved_at": _ts(row.resolved_at),
        # `resolution_kind` exists only once an incident was resolved, and the column
        # stores "" for one that never was. Reported as null so it reads the same way
        # `resolved_at` does, rather than as an empty kind a reader might take for one.
        "resolution_kind": row.resolution_kind or None,
    }


def _state_counts(workspace_id, cutoff):
    """Exact incident counts: active, and resolved inside the window.

    These are counted in the database rather than derived from the page, because
    they are what a notification badge reads and must not change with a page size.
    """
    active_count = ProviderHealthEvent.select().where((ProviderHealthEvent.tenant_id == workspace_id) & (ProviderHealthEvent.state == ACTIVE)).count()
    resolved_count = (
        ProviderHealthEvent.select()
        .where(
            (ProviderHealthEvent.tenant_id == workspace_id)
            & (ProviderHealthEvent.state == RESOLVED)
            & (ProviderHealthEvent.resolved_at.is_null(False))
            & (ProviderHealthEvent.resolved_at >= cutoff)
        )
        .count()
    )
    return active_count, resolved_count


def _rows_in_state(workspace_id, state, cutoff=None):
    """One state's rows, most recently seen first, bounded.

    `last_seen_at` desc is the order a reader wants - what is happening now, and
    what just stopped - and `id` breaks ties so two incidents seen in the same
    second do not swap places between requests.
    """
    query = ProviderHealthEvent.select().where((ProviderHealthEvent.tenant_id == workspace_id) & (ProviderHealthEvent.state == state))
    if cutoff is not None:
        query = query.where(ProviderHealthEvent.resolved_at.is_null(False) & (ProviderHealthEvent.resolved_at >= cutoff))
    return list(query.order_by(ProviderHealthEvent.last_seen_at.desc(), ProviderHealthEvent.id.asc()).limit(MAX_ROWS_PER_STATE))


@_in_db_context
def read_incidents(actor_user_id, workspace_id, limit=None, offset=None, window_days=None, now=None):
    """The workspace's active incidents, then its recently resolved ones.

    ACTIVE first, then RESOLVED, each ordered by `last_seen_at` desc - the order is
    built from two bounded reads rather than one CASE expression, because the two
    states are disjoint and each side has its own window rule.

    The caller is authorised BEFORE anything is read, and the two counts are exact
    while the lists are bounded, so a caller can always learn how many incidents
    exist without this read ever growing with the workspace's history.
    """
    require_workspace_manager(actor_user_id, workspace_id)

    size, skip = resolve_page(limit, offset)
    try:
        days = RECENTLY_RESOLVED_WINDOW_DAYS if window_days in (None, "") else int(window_days)
    except (TypeError, ValueError):
        raise WorkspaceAccessDenied("resolved_window_days 必须是整数") from None
    if days < 1 or days > MAX_WINDOW_DAYS:
        raise WorkspaceAccessDenied(f"resolved_window_days 必须在 1 到 {MAX_WINDOW_DAYS} 之间")
    moment = now or datetime.now(utc_timezone.utc).replace(tzinfo=None)
    cutoff = moment - timedelta(days=days)

    active_count, resolved_count = _state_counts(workspace_id, cutoff)
    active_rows = _rows_in_state(workspace_id, ACTIVE)
    resolved_rows = _rows_in_state(workspace_id, RESOLVED, cutoff=cutoff)

    ordered = active_rows + resolved_rows
    page = ordered[skip : skip + size]
    total_in_scope = len(ordered)

    return {
        "incidents": [_project(row) for row in page],
        # Counts are EXACT and independent of the page: a badge reads active_count.
        "active_count": active_count,
        "recently_resolved_count": resolved_count,
        "total_in_scope": total_in_scope,
        "limit": size,
        "offset": skip,
        "truncated": total_in_scope > skip + len(page),
        # Stated rather than implied: when a state holds more rows than one request
        # may load, the counts stay exact and the list is the bound. A reader can
        # tell the two apart without comparing numbers itself.
        "lists_incomplete": active_count > len(active_rows) or resolved_count > len(resolved_rows),
        "recently_resolved_window_days": days,
        "not_answered": NOT_ANSWERED,
    }
