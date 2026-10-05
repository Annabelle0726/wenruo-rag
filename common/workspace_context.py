"""Authenticated execution identity, distinct from caller-supplied tracing IDs."""

from contextvars import ContextVar

execution_user: ContextVar[str | None] = ContextVar("execution_user", default=None)
execution_refusal: ContextVar[dict | None] = ContextVar("execution_refusal", default=None)
