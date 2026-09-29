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
"""Read-only usage endpoints for a workspace.

Every route below is a pure read of the accounting records the enforcement path
already writes, reached through `workspace_usage_read_service`. None of them
writes, takes a lock or touches a credential - in particular none calls
`configure_budget`, whose read path takes a write lock on the tenant row.

The workspace in the path is a RESOURCE key and the caller's own id is a MEMBER
key: separate identity domains that are never substituted for each other.
`resolve_read_scope` re-checks a LIVE membership for the path workspace on every
request, so a cached grant, a creator-only shortcut or a removed member's token
cannot open this read path. A refusal is the standard HTTP 200 + code 108. The
`X-Tenant-Id` header is a request hint only (`login_required` already validates
it) and never widens access to the workspace named in the path.
"""

from quart import request

from api.apps import current_user, login_required
from api.db.services.workspace_usage_read_service import build_view
from api.utils.api_utils import get_json_result, server_error_response
from common.exceptions import WorkspaceAccessDenied

# Query parameter -> the keyword the view builder takes. Listing them per view
# is what lets an unknown parameter be REFUSED instead of ignored: a caller that
# mistypes `from_day` must not silently be served a different window than the
# one it asked for.
VIEW_PARAMS = {
    "my_usage": {"start_day": "start_day", "end_day": "end_day"},
    "workspace_summary": {"start_day": "start_day", "end_day": "end_day"},
    "member_breakdown": {"start_day": "start_day", "end_day": "end_day", "limit": "limit", "offset": "offset"},
    "daily_series": {"start_day": "start_day", "end_day": "end_day"},
    "monthly_series": {"start_month": "start_month", "end_month": "end_month"},
    "recorded_model_breakdown": {"start_day": "start_day", "end_day": "end_day", "limit": "limit", "offset": "offset"},
    "quota_status": {"user_id": "member_user_id"},
}


def _read(view, tenant_id):
    """Validate the query string, then build the view. Read-only throughout."""
    params = VIEW_PARAMS[view]
    unknown = sorted(set(request.args.keys()) - set(params))
    if unknown:
        raise WorkspaceAccessDenied(f"未知的查询参数：{', '.join(unknown)}")
    supplied = {params[key]: request.args.get(key) for key in params if key in request.args}
    return get_json_result(data=build_view(view, current_user.id, tenant_id, **supplied))


@manager.route("/tenants/<tenant_id>/usage/my", methods=["GET"])  # noqa: F821
@login_required
def usage_my(tenant_id):
    """The caller's own metered usage over a bounded day window."""
    try:
        return _read("my_usage", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/summary", methods=["GET"])  # noqa: F821
@login_required
def usage_summary(tenant_id):
    """The workspace aggregate over a bounded day window (OWNER/ADMIN only)."""
    try:
        return _read("workspace_summary", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/members", methods=["GET"])  # noqa: F821
@login_required
def usage_members(tenant_id):
    """Per-member usage for the workspace, paginated (OWNER/ADMIN only)."""
    try:
        return _read("member_breakdown", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/daily", methods=["GET"])  # noqa: F821
@login_required
def usage_daily(tenant_id):
    """Per-day usage over a bounded day window (OWNER/ADMIN only)."""
    try:
        return _read("daily_series", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/monthly", methods=["GET"])  # noqa: F821
@login_required
def usage_monthly(tenant_id):
    """Per-month usage over a bounded month window (OWNER/ADMIN only).

    Month and day buckets must never be summed together: one reservation
    increments both a day row and a month row.
    """
    try:
        return _read("monthly_series", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/models", methods=["GET"])  # noqa: F821
@login_required
def usage_models(tenant_id):
    """Usage by RECORDED model name, paginated (OWNER/ADMIN only).

    The name is what the ledger recorded. Provider, API-key-instance and
    workload attribution are not recorded and are not reconstructed.
    """
    try:
        return _read("recorded_model_breakdown", tenant_id)
    except Exception as exc:
        return server_error_response(exc)


@manager.route("/tenants/<tenant_id>/usage/quota", methods=["GET"])  # noqa: F821
@login_required
def usage_quota(tenant_id):
    """Current-period limits against occupancy for one member (OWNER/ADMIN may name one)."""
    try:
        return _read("quota_status", tenant_id)
    except Exception as exc:
        return server_error_response(exc)
