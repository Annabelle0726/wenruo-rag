"""Guard synchronous, asynchronous and streamed LLMBundle dispatches alike."""

import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from common.workspace_context import execution_user


_dispatch = ContextVar("model_dispatch_budget", default=None)


def charge_provider_call():
    """Charge retries/tool rounds; the first call was reserved by the bundle."""
    state = _dispatch.get()
    if state is None:
        return
    if state["first"]:
        state["first"] = False
        return
    from api.db.services.workspace_budget_service import reserve_call

    reserve_call(state["tenant"], state["actor"])


@contextmanager
def _call_budget(bundle):
    actor = execution_user.get() or getattr(bundle, "execution_user_id", None)
    state = None
    if actor:
        from api.db.services.workspace_budget_service import reserve_call

        reserve_call(bundle.tenant_id, actor)
        state = {"tenant": bundle.tenant_id, "actor": actor, "first": True}
    token = _dispatch.set(state)
    try:
        yield
    finally:
        _dispatch.reset(token)


def budgeted(func):
    if inspect.isasyncgenfunction(func):

        @wraps(func)
        async def streaming(self, *args, **kwargs):
            with _call_budget(self):
                async for item in func(self, *args, **kwargs):
                    yield item

        return streaming
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def asynchronous(self, *args, **kwargs):
            with _call_budget(self):
                return await func(self, *args, **kwargs)

        return asynchronous
    if inspect.isgeneratorfunction(func):

        @wraps(func)
        def generator(self, *args, **kwargs):
            with _call_budget(self):
                yield from func(self, *args, **kwargs)

        return generator

    @wraps(func)
    def synchronous(self, *args, **kwargs):
        with _call_budget(self):
            return func(self, *args, **kwargs)

    return synchronous
