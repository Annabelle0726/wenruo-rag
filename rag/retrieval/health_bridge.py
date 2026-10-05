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

#: Answer-policy enforcement is DELIBERATELY DISABLED for the Option-A deployment.
#:
#: This version observes and exposes retrieval health; it must never change what the user is told. In
#: particular the contract's `decide_answer_action` / `required_notice` machinery exists and is unit
#: tested, but nothing on the retrieval path calls it, so a `partial` evidence state cannot turn into a
#: refusal. Enforcement is P1 scope and requires the Authority/Support validator plus its own acceptance
#: gate before it may be switched on.
ANSWER_POLICY_ENFORCEMENT = "disabled"

#: Symbols that would mean the answer policy had leaked into this deployment. The build gate fails if any
#: of these appears in the candidate sources.
FORBIDDEN_POLICY_SYMBOLS = (
    "decide_answer_action",
    "required_notice",
    "AnswerAction",
    "refuse_insufficient",
    "refuse_failed",
)


def answer_policy_enforced() -> bool:
    """Always False in this deployment; exists so tests and traces can assert the decoupling."""
    return ANSWER_POLICY_ENFORCEMENT != "disabled"

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
    """Route-level bookkeeping only.

    A route result is *not* a leg fact: one hybrid route call covers the dense leg **and** the lexical
    leg, so the route layer cannot tell which of them ran and must never invent either one. Evidence
    legs are reported where they actually execute (see the leg reporters below). The previous version
    popped both legs and then re-declared one of them `success`; that erased the real dense fact and
    left the other leg `UNKNOWN`, so a perfectly healthy request aggregated to `degraded` with a null
    reason and the contract flagged it as silent degradation.
    """
    counters = session.__dict__.setdefault("_route_counters", {"attempted": 0, "succeeded": 0, "failed": 0})
    counters["attempted"] += 1
    if outcome == "success":
        counters["succeeded"] += 1
        return
    counters["failed"] += 1
    if exc is None:
        return
    # Attribute a route failure to a leg only when no deeper boundary already owns that leg: an
    # embedding-boundary failure has already been reported by the dense producer, with a more accurate
    # reason than this heuristic can produce.
    leg = leg_for_exception(exc)
    if not _leg_facts(session).get(leg):
        _record_leg_execution(leg, False, exc)


#: Evidence-leg facts are produced at the boundary where the leg actually runs:
#:   dense   -> the query-embedding request (``Dealer.get_vector`` in the store/search layer)
#:   lexical -> the store round trip that carries the lexical expression
#: Every attempt is counted and the counts aggregate into exactly one leg status, so a partially
#: failing leg reports `degraded` with a reason instead of being rounded to success or to silence.
_LEG_FACT_KEY = "_leg_facts"


def _leg_facts(session) -> dict:
    return session.__dict__.setdefault(_LEG_FACT_KEY, {})


def _apply_leg_facts(session, leg: str) -> None:
    facts = _leg_facts(session).get(leg)
    if not facts:
        return
    attempted = facts["ok"] + facts["failed"]
    if facts["failed"] and facts["ok"]:
        session.leg_partially_failed(leg, reason=facts["reason"], routes_attempted=attempted, routes_succeeded=facts["ok"])
    elif facts["failed"]:
        session.leg_failed(leg, reason=facts["reason"], routes_attempted=attempted, routes_succeeded=0)
    else:
        session.leg_succeeded(leg, routes_attempted=attempted, routes_succeeded=facts["ok"])


def _record_leg_execution(leg: str, ok: bool, exc: BaseException | None = None) -> None:
    """Record one real execution of an evidence leg, at the point where it happened."""
    session = current_session()
    if session is None:
        return

    def _record() -> None:
        facts = _leg_facts(session).setdefault(leg, {"ok": 0, "failed": 0, "reason": None})
        if ok:
            facts["ok"] += 1
        else:
            facts["failed"] += 1
            if facts["reason"] is None:
                facts["reason"] = producers.reason_from_exception(exc, leg) if exc is not None else producers.ReasonCode.INTERNAL_ERROR
        _apply_leg_facts(session, leg)

    _safe(_record)


def _record_leg_not_triggered(leg: str) -> None:
    """The branch never required this leg. Never overrides an execution fact that already exists."""
    session = current_session()
    if session is None:
        return

    def _record() -> None:
        if _leg_facts(session).get(leg):
            return
        session.leg_not_triggered(leg)

    _safe(_record)


def report_dense_executed() -> None:
    """The dense (embedding) leg ran and returned a usable query vector."""
    _record_leg_execution("dense", True)


def report_dense_failed(exc: BaseException) -> None:
    """The dense (embedding) leg ran and failed; the reason is read from the exception itself."""
    _record_leg_execution("dense", False, exc)


def report_dense_not_triggered() -> None:
    """No embedding model was supplied, so the dense leg was never required."""
    _record_leg_not_triggered("dense")


def report_lexical_executed() -> None:
    """The lexical leg ran: the store round trip carrying the lexical expression returned."""
    _record_leg_execution("lexical", True)


def report_lexical_failed(exc: BaseException) -> None:
    """The lexical leg ran and failed; the reason is read from the exception itself."""
    _record_leg_execution("lexical", False, exc)


def report_lexical_not_triggered() -> None:
    """The question produced no lexical expression, so the lexical leg was never required."""
    _record_leg_not_triggered("lexical")


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
