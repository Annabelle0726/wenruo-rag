"""Guard synchronous, asynchronous and streamed LLMBundle dispatches alike.

One dispatch reserves a bound (one call, an estimated token count, and - when
the model carries pricing - a cost bound) and settles it with what the provider
actually reported. Settlement is idempotent by reservation id, so a stream that
is closed early, a retried callback or a duplicate provider round cannot charge
twice; a dispatch that reports nothing keeps its whole reservation, because a
timeout does not prove the provider spent nothing.

Extra provider rounds (LiteLLM retries, tool rounds) are charged as extra CALLS
through `charge_provider_call`; their tokens are already inside the usage the
dispatch reports at the end.
"""

import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from common.workspace_context import execution_user


_dispatch = ContextVar("model_dispatch_budget", default=None)

# The output bound a dispatch reserves before it knows what it will generate.
# Deliberately NOT the model's context window: reserving a 128k-window model's
# `max_tokens` for every call would exhaust a daily token quota after a couple
# of turns. Settlement charges the real number when the provider reports more
# than the bound, so under-reserving costs accounting precision, never money.
TOKEN_RESERVE_CAP = 8192
# Per-message overhead of the chat template (role markers, separators).
MESSAGE_OVERHEAD_TOKENS = 4
MAX_RESERVE_TOKENS = 1000000
# Fallback when tiktoken cannot encode the text: ~4 characters per token.
CHARS_PER_TOKEN = 4


def _safe_token_count(text) -> int:
    """Token count of one string, never raising and never doing network I/O."""
    if not isinstance(text, str) or not text:
        return 0
    try:
        from common.token_utils import num_tokens_from_string

        return max(0, int(num_tokens_from_string(text)))
    except Exception:  # noqa: BLE001 - an estimate must not break a model call
        return max(1, len(text) // CHARS_PER_TOKEN)


def _message_text(message) -> str:
    """The text of one history entry, for any of the shapes a caller passes."""
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
    elif isinstance(message, (list, tuple)) and len(message) > 1:
        content = message[1]
    else:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def estimate_prompt_tokens(bound_arguments: dict) -> int:
    """Estimate the input tokens of one dispatch from its bound call arguments.

    Chat calls carry `system`/`history`; embedding and OCR/text calls carry the
    text under `texts`/`query`/`prompt`/`text`. Anything else (an image, audio
    bytes) has no text to count and is bounded by its output reservation alone.
    """
    total = 0
    if "system" in bound_arguments or "history" in bound_arguments:
        total += _safe_token_count(bound_arguments.get("system"))
        history = bound_arguments.get("history") or []
        if isinstance(history, (list, tuple)):
            for message in history:
                total += _safe_token_count(_message_text(message)) + MESSAGE_OVERHEAD_TOKENS
        return total
    for key in ("texts", "query", "prompt", "text"):
        value = bound_arguments.get(key)
        if isinstance(value, str):
            total += _safe_token_count(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                total += _safe_token_count(item)
    return total


def pricing_of(model_config: dict) -> tuple[float, float]:
    """(input, output) price in micro-USD per token, when the model states one.

    A provider/model's `extra` may carry `price_input_per_million` /
    `price_output_per_million` in USD per million tokens; one USD per million
    tokens IS one micro-USD per token, so the numbers are used as they are and
    the ledger stays integer.
    """
    pricing = (model_config or {}).get("pricing") or {}
    try:
        return float(pricing.get("input_per_million") or 0), float(pricing.get("output_per_million") or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0


def estimate_cost_micros(prompt_tokens: int, completion_tokens: int, price_in: float, price_out: float) -> int:
    return int(round(max(0, prompt_tokens) * price_in + max(0, completion_tokens) * price_out))


def _output_bound(bound_arguments: dict, model_config: dict) -> int:
    gen_conf = bound_arguments.get("gen_conf") or {}
    candidate = None
    if isinstance(gen_conf, dict):
        candidate = gen_conf.get("max_tokens")
    if not candidate:
        candidate = (model_config or {}).get("max_tokens")
    try:
        candidate = int(candidate)
    except (TypeError, ValueError):
        candidate = TOKEN_RESERVE_CAP
    if candidate <= 0:
        candidate = TOKEN_RESERVE_CAP
    return min(candidate, TOKEN_RESERVE_CAP)


def dispatch_reservation(model_config: dict, function, args, kwargs) -> tuple[int, int]:
    """The (tokens, cost) bound one dispatch reserves before it runs."""
    try:
        bound = inspect.signature(function).bind_partial(*args, **kwargs)
        arguments = dict(bound.arguments)
    except (TypeError, ValueError):
        arguments = dict(kwargs)
    prompt_tokens = estimate_prompt_tokens(arguments)
    output_bound = _output_bound(arguments, model_config)
    reserved_tokens = min(prompt_tokens + output_bound, MAX_RESERVE_TOKENS)
    price_in, price_out = pricing_of(model_config)
    reserved_cost = estimate_cost_micros(prompt_tokens, output_bound, price_in, price_out) if (price_in or price_out) else 0
    return reserved_tokens, reserved_cost


def charge_provider_call():
    """Charge retries/tool rounds; the first call was reserved by the bundle."""
    state = _dispatch.get()
    if state is None:
        return
    if state["first"]:
        state["first"] = False
        return
    from api.db.services.workspace_budget_service import release_dispatch, reserve_call

    reservation = reserve_call(state["tenant"], state["actor"])
    # The extra round is charged as a CALL. Its tokens are inside the usage the
    # dispatch reports when it finishes, so this reservation is closed as having
    # no settlement of its own instead of staying open forever.
    release_dispatch(reservation)


def record_dispatch_usage(prompt_tokens=0, completion_tokens=0, total_tokens=0):
    """Report the usage one provider round of the ACTIVE dispatch actually used.

    Called by LLMBundle at the end of a call. Summing is deliberate: a dispatch
    that reports twice (a retry that came back with its own usage) really did
    spend twice.
    """
    state = _dispatch.get()
    if state is None:
        return
    reported = state["reported"]
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    total = max(0, int(total_tokens or 0)) or (prompt + completion)
    reported["prompt_tokens"] += prompt
    reported["completion_tokens"] += completion
    reported["total_tokens"] += total
    state["reported_rounds"] += 1


@contextmanager
def _call_budget(bundle, function=None, args=(), kwargs=None):
    actor = execution_user.get() or getattr(bundle, "execution_user_id", None)
    tenant_id = getattr(bundle, "tenant_id", None)
    state = None
    if actor and tenant_id:
        from api.db.services.workspace_budget_service import reserve_call

        model_config = getattr(bundle, "model_config", None) or {}
        reserved_tokens, reserved_cost = dispatch_reservation(model_config, function, (bundle, *args), kwargs or {}) if function else (0, 0)
        reservation = reserve_call(
            tenant_id,
            actor,
            model_name=model_config.get("llm_name"),
            model_type=model_config.get("model_type"),
            reserved_tokens=reserved_tokens,
            reserved_cost_micros=reserved_cost,
        )
        state = {
            "tenant": tenant_id,
            "actor": actor,
            "first": True,
            "reservation": reservation,
            "reserved_tokens": reserved_tokens,
            "pricing": pricing_of(model_config),
            "reported": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "reported_rounds": 0,
        }
    token = _dispatch.set(state)
    try:
        yield state
    finally:
        _dispatch.reset(token)
        if state is not None and state.get("reservation"):
            _close_dispatch(state)


def _close_dispatch(state):
    """Settle the reservation with what the provider reported, else keep it."""
    from api.db.services.workspace_budget_service import release_dispatch, settle_dispatch

    reported = state["reported"]
    if not (reported["total_tokens"] or reported["prompt_tokens"] or reported["completion_tokens"]):
        release_dispatch(state["reservation"])
        return
    price_in, price_out = state["pricing"]
    cost_micros = None
    if price_in or price_out:
        cost_micros = estimate_cost_micros(reported["prompt_tokens"], reported["completion_tokens"], price_in, price_out)
    settle_dispatch(
        state["reservation"],
        prompt_tokens=reported["prompt_tokens"],
        completion_tokens=reported["completion_tokens"],
        total_tokens=reported["total_tokens"],
        cost_micros=cost_micros,
    )


def budgeted(func):
    if inspect.isasyncgenfunction(func):

        @wraps(func)
        async def streaming(self, *args, **kwargs):
            with _call_budget(self, func, args, kwargs):
                async for item in func(self, *args, **kwargs):
                    yield item

        return streaming
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def asynchronous(self, *args, **kwargs):
            with _call_budget(self, func, args, kwargs):
                return await func(self, *args, **kwargs)

        return asynchronous
    if inspect.isgeneratorfunction(func):

        @wraps(func)
        def generator(self, *args, **kwargs):
            with _call_budget(self, func, args, kwargs):
                yield from func(self, *args, **kwargs)

        return generator

    @wraps(func)
    def synchronous(self, *args, **kwargs):
        with _call_budget(self, func, args, kwargs):
            return func(self, *args, **kwargs)

    return synchronous
