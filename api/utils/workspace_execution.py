"""Keep authenticated execution context across deferred Quart SSE iteration."""

import json

from quart import Response

from api.utils.api_utils import get_error_permission_result
from common.exceptions import WorkspaceAccessDenied
from common.workspace_context import execution_refusal, execution_user


def guard_response(response, user_id, refusal):
    if refusal.get("message"):
        return get_error_permission_result(refusal["message"])
    if not isinstance(response, Response) or response.mimetype != "text/event-stream":
        return response
    body = response.response

    async def stream():
        identity_token = execution_user.set(user_id)
        refusal_token = execution_refusal.set(refusal)
        try:
            try:
                async with body as iterator:
                    async for chunk in iterator:
                        if refusal.get("message"):
                            break
                        yield chunk
            except WorkspaceAccessDenied as exc:
                refusal["message"] = str(exc)
            if refusal.get("message"):
                yield ("data:" + json.dumps({"code": 108, "message": refusal["message"], "data": False}, ensure_ascii=False) + "\n\n").encode()
        finally:
            execution_refusal.reset(refusal_token)
            execution_user.reset(identity_token)

    response.response = response.iterable_body_class(stream())
    return response
