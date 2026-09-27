"""P0-B reporter-only bridge: observes the existing retrieval control flow, never owns it.

Hard rules encoded here (see the deployment readiness audit, §3):

* Nothing in this module raises, returns a control-flow value, or wraps a retrieval call. Every entry
  point is called *beside* existing statements, inside the branches that already exist.
* Exceptions are **accepted** here, never caught from business code: the only `try/except` in this file
  wraps reporter bookkeeping, so no retrieval exception can be swallowed by instrumentation.
* `RouteResult` is never constructed, replaced or mutated; the per-route result contract is untouched.
* The request-scoped session travels in a ContextVar, which is why no retrieval function signature
  changes. `asyncio.gather` copies the context per task, and the session object is mutable and shared,
  so route tasks report into the same session.
"""

from __future__ import annotations

import contextvars
import importlib.util
import logging
import pathlib
import sys

_LOG = logging.getLogger("rag.retrieval.health_bridge")


def _load(name: str, filename: str):
    try:
        module = __import__(f"rag.retrieval.{filename}", fromlist=[name])
        return module
    except Exception:  # noqa: BLE001
        spec = importlib.util.spec_from_file_location(name, pathlib.Path(__file__).resolve().parent / f"{filename}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


health = _load("rag_retrieval_health_contract", "health")
producers = _load("rag_retrieval_health_producers", "health_producers")

_SESSION: contextvars.ContextVar = contextvars.ContextVar("retrieval_health_session", default=None)

#: Exception classes whose failure belongs to the dense (embedding) leg rather than the store leg.
_EMBEDDING_HINTS = ("embed", "quota", "429", "resource_exhausted", "tei", "vector")


def leg_for_exception(exc: BaseException) -> str:
    """Attribute a caught exception to a leg. This classifies an observed failure; it never decides one."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return "dense" if any(hint in text for hint in _EMBEDDING_HINTS) else "lexical"


def begin_retrieval_health(question_id: str | None = None):
    session = producers.HealthSession(plan_version="deployed-1.0", question_id=question_id)
    _SESSION.set(session)
    return session


def current_session():
    return _SESSION.get()


def _safe(action, *args, **kwargs) -> None:
    """Run reporter bookkeeping only. Nothing here can alter retrieval behaviour."""
    try:
        action(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - reporter bookkeeping must never break retrieval
        _LOG.warning("[Health] reporter bookkeeping failed (retrieval unaffected): %s", exc)


def report_route_success() -> None:
    session = current_session()
    if session is None:
        return
    _safe(_bump, session, "success")


def report_route_failure(exc: BaseException) -> None:
    session = current_session()
    if session is None:
        return
    _safe(_bump, session, "failure", exc)


def _bump(session, outcome: str, exc: BaseException | None = None) -> None:
    counters = session.__dict__.setdefault("_route_counters", {"attempted": 0, "succeeded": 0, "failed": {}})
    counters["attempted"] += 1
    if outcome == "success":
        counters["succeeded"] += 1
    else:
        leg = leg_for_exception(exc) if exc is not None else "lexical"
        counters["failed"][leg] = counters["failed"].get(leg, 0) + 1
    session.legs.pop("lexical", None)
    session.legs.pop("dense", None)
    if counters["failed"]:
        for leg, count in counters["failed"].items():
            session.leg_partially_failed(leg, reason=producers.ReasonCode.EMBEDDING_QUOTA_EXHAUSTED if leg == "dense" and _is_quota(exc) else None, exc=None if leg == "dense" and _is_quota(exc) else (exc if exc is not None else RuntimeError("route failure")), routes_attempted=count, routes_succeeded=0)
    if counters["succeeded"]:
        leg = "lexical" if "lexical" not in counters["failed"] else "dense"
        session.leg_succeeded(leg, routes_attempted=counters["succeeded"], routes_succeeded=counters["succeeded"])


def _is_quota(exc: BaseException | None) -> bool:
    return exc is not None and producers.reason_from_exception(exc, "dense") is producers.ReasonCode.EMBEDDING_QUOTA_EXHAUSTED


def mark_no_question() -> None:
    session = current_session()
    if session is None:
        return
    _safe(session.leg_failed, "decomposition", None, producers.ReasonCode.PLAN_EMPTY, 1, 0)


def mark_empty_window() -> None:
    """All routes ran but the pool came back empty: say so instead of reporting a clean run."""
    session = current_session()
    if session is None:
        return
    _safe(session.leg_partially_failed, "selection", None, producers.ReasonCode.THRESHOLD_EMPTY, 1, 0)


def attach_retrieval_health(result: dict) -> dict:
    """Add the additive health field to the result. The three existing keys are copied unchanged."""
    session = current_session()
    if session is None or not isinstance(result, dict):
        return result
    if not session.legs.get("rerank"):
        _safe(session.leg_not_triggered, "rerank")
    if not session.legs.get("followup"):
        _safe(session.leg_not_triggered, "followup")
    if not session.legs.get("decomposition"):
        _safe(session.leg_succeeded, "decomposition", 1, 1)
    try:
        session.note_chunk_count(len(result.get("chunks") or []))
        return health.attach_health(result, session.build())
    except Exception as exc:  # noqa: BLE001 - the answer path must survive a reporter defect
        _LOG.warning("[Health] attach failed (retrieval unaffected): %s", exc)
        return result
