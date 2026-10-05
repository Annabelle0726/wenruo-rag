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
"""Read-only provider-health endpoints for a workspace's administrators.

One route, because one view is enough: the incidents a workspace's administrators
need to see are its ACTIVE ones first and its RECENTLY RESOLVED ones second, and
the same response carries the exact active count a notification badge needs. A
separate count endpoint would be a second read of the same rows for the same
audience, so it is deliberately absent rather than deferred for convenience.

The workspace in the path is the subject: the caller must hold OWNER or ADMIN on
THAT workspace, checked live per request (see `require_workspace_manager`). The
`X-Tenant-Id` header names the workspace a client is working in and never widens
this read, and the caller's own id is never compared with a workspace id.

A refusal is the standard HTTP 200 + code 108, the same envelope every other
admin-only workspace route answers with.
"""

from quart import request

from api.apps import current_user, login_required
from api.db.services.provider_health_read_service import read_incidents
from api.utils.api_utils import get_json_result, server_error_response
from common.exceptions import WorkspaceAccessDenied

# Query parameter -> the keyword the reader takes. Listing them is what lets an
# unknown parameter be REFUSED instead of ignored: a caller that mistypes a window
# must not silently be served a different one than it asked for.
QUERY_PARAMS = {
    "limit": "limit",
    "offset": "offset",
    "resolved_window_days": "window_days",
}


def _read(tenant_id):
    """Validate the query string, then read. Read-only throughout."""
    unknown = sorted(set(request.args.keys()) - set(QUERY_PARAMS))
    if unknown:
        raise WorkspaceAccessDenied(f"未知的查询参数：{', '.join(unknown)}")
    supplied = {QUERY_PARAMS[key]: request.args.get(key) for key in QUERY_PARAMS if key in request.args}
    return get_json_result(data=read_incidents(current_user.id, tenant_id, **supplied))


@manager.route("/tenants/<tenant_id>/provider-health/incidents", methods=["GET"])  # noqa: F821
@login_required
def provider_health_incidents(tenant_id):
    """Active provider incidents first, then recently resolved ones (OWNER/ADMIN).

    The response carries the incidents, the exact `active_count` a badge reads, the
    resolved window it used, and the honesty notes that go with them. Absence of
    incidents is reported as an empty list and a count of 0 - never as a synthetic
    "healthy" row, because no provider is polled to know that.
    """
    try:
        return _read(tenant_id)
    except Exception as exc:
        return server_error_response(exc)
