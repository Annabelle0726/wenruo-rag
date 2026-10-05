"""Phase B / P0-B producers: health state is produced where execution happens.

Design constraints this module exists to enforce (Revision 2 + P0-B):

1. **No heuristic inference.** A leg's status is produced at its own execution point — the exception
   boundary for a failing leg, the return for a succeeding one. Nothing here inspects chunk counts,
   result sizes or timings to guess whether a leg ran or failed. The aggregator only aggregates.
2. **`not_triggered` and `skipped` are different facts and must never be mixed.**
   `not_triggered` = the current plan/branch never required the leg (for example no follow-up route was
   designed for this question, or the deployment has no rerank model configured).
   `skipped` = the leg was eligible to run but a policy explicitly stopped it (circuit breaker open,
   budget guard tripped, policy veto). `skipped` therefore requires a policy reason from a closed set.
3. **Conservative evidence.** The retrieval layer may not self-certify `evidence_completeness = full`
   merely because lexical search returned chunks. Execution-side evidence is capped at `partial`, and
   only an explicit authority/support validator may upgrade it to `full`. This keeps silent degradation
   from migrating from the execution layer into the semantic layer.

The module is dependency-free apart from the contract itself.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import sys

_LOG = logging.getLogger(__name__)

_CONTRACT = pathlib.Path(__file__).resolve().parent / "health.py"
if "rag_retrieval_health_contract" not in sys.modules:  # tolerate both package and file loading
    try:
        from rag.retrieval import health as contract  # type: ignore
    except Exception:  # noqa: BLE001
        spec = importlib.util.spec_from_file_location("rag_retrieval_health_contract", _CONTRACT)
        contract = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = contract
        spec.loader.exec_module(contract)
else:
    contract = sys.modules["rag_retrieval_health_contract"]

LegHealth = contract.LegHealth
LegStatus = contract.LegStatus
ExecutionHealth = contract.ExecutionHealth
EvidenceState = contract.EvidenceState
Completeness = contract.Completeness
RetrievalHealth = contract.RetrievalHealth
ReasonCode = contract.ReasonCode
QuestionRisk = contract.QuestionRisk
AnswerAction = contract.AnswerAction

#: `skipped` may only carry one of these: a policy decision, never a guess.
POLICY_SKIP_REASONS = ("CIRCUIT_BREAKER_OPEN", "BUDGET_GUARD_TRIPPED", "POLICY_VETO")

#: The retrieval layer cannot certify more than this by itself (constraint 3).
RETRIEVAL_LAYER_MAX_COMPLETENESS = Completeness.PARTIAL

_QUOTA_MARKERS = ("quota", "429", "resource_exhausted", "rate limit", "rate_limit")
_TIMEOUT_MARKERS = ("timeout", "timed out", "deadline")


def reason_from_exception(exc: BaseException, leg: str) -> ReasonCode:
    """Map a failure to a reason code **at the exception boundary**, from the exception itself.

    This is deliberately the only place a failure becomes a status: no caller above it may infer a
    failure from a smaller-than-expected result.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _QUOTA_MARKERS):
        return ReasonCode.EMBEDDING_QUOTA_EXHAUSTED if leg == "dense" else ReasonCode.INTERNAL_ERROR
    if any(marker in text for marker in _TIMEOUT_MARKERS):
        if leg == "dense":
            return ReasonCode.EMBEDDING_TIMEOUT
        if leg in ("lexical", "followup"):
            return ReasonCode.STORE_UNAVAILABLE if leg == "lexical" else ReasonCode.FOLLOWUP_FAILED
        return ReasonCode.ROUTE_TIMEOUT
    if leg == "dense":
        return ReasonCode.EMBEDDING_UNAVAILABLE
    if leg in ("lexical", "followup"):
        return ReasonCode.STORE_UNAVAILABLE if leg == "lexical" else ReasonCode.FOLLOWUP_FAILED
    if leg == "decomposition":
        return ReasonCode.PLAN_VALIDATION_FAILED
    return ReasonCode.INTERNAL_ERROR


def parse_reason(value) -> ReasonCode | None:
    if value is None or isinstance(value, ReasonCode):
        return value
    try:
        return ReasonCode(str(value))
    except ValueError:
        return None


class HealthSession:
    """Accumulates per-leg facts produced at their execution points, then aggregates once."""

    def __init__(self, plan_version: str | None = None, question_id: str | None = None):
        self.plan_version = plan_version
        self.question_id = question_id
        self.legs: dict = {}
        self.events: list = []
        self.alerts: list = []
        self.chunk_count = 0
        self._evidence_leg_results: dict = {}

    # ---- producers: one call per fact, made where the fact happens -------------------------------

    def leg_succeeded(self, name: str, routes_attempted: int = 0, routes_succeeded: int | None = None, detail: dict | None = None) -> None:
        self.legs[name] = LegHealth(
            name=name,
            status=LegStatus.SUCCESS,
            routes_attempted=routes_attempted,
            routes_succeeded=routes_attempted if routes_succeeded is None else routes_succeeded,
            detail=detail or {},
        )
        if name in contract.EVIDENCE_LEGS:
            self._evidence_leg_results[name] = True

    def leg_partially_failed(self, name: str, exc: BaseException | None = None, reason=None, routes_attempted: int = 0, routes_succeeded: int = 0) -> None:
        code = parse_reason(reason) or (reason_from_exception(exc, name) if exc is not None else ReasonCode.INTERNAL_ERROR)
        self.legs[name] = LegHealth(name=name, status=LegStatus.DEGRADED, reason=code, routes_attempted=routes_attempted, routes_succeeded=routes_succeeded)
        if name in contract.EVIDENCE_LEGS:
            self._evidence_leg_results[name] = False

    def leg_failed(self, name: str, exc: BaseException | None = None, reason=None, routes_attempted: int = 0, routes_succeeded: int = 0) -> None:
        code = parse_reason(reason) or (reason_from_exception(exc, name) if exc is not None else ReasonCode.INTERNAL_ERROR)
        self.legs[name] = LegHealth(name=name, status=LegStatus.FAILED, reason=code, routes_attempted=routes_attempted, routes_succeeded=routes_succeeded)
        if name in contract.EVIDENCE_LEGS:
            self._evidence_leg_results[name] = False

    def leg_not_triggered(self, name: str, reason=None) -> None:
        """The plan/branch design never required this leg. Not a policy decision."""
        self.legs[name] = LegHealth(name=name, status=LegStatus.NOT_TRIGGERED, reason=parse_reason(reason))
        if name in contract.EVIDENCE_LEGS:
            self._evidence_leg_results[name] = False

    def leg_skipped(self, name: str, policy_reason: str) -> None:
        """The leg was eligible but policy stopped it. Only the closed policy set is accepted."""
        if policy_reason not in POLICY_SKIP_REASONS:
            raise ValueError(f"leg_skipped requires one of {POLICY_SKIP_REASONS}, got {policy_reason!r}: use leg_not_triggered when the branch never required the leg")
        self.legs[name] = LegHealth(name=name, status=LegStatus.SKIPPED, reason=policy_reason)
        if name in contract.EVIDENCE_LEGS:
            self._evidence_leg_results[name] = False

    def note_chunk_count(self, count: int) -> None:
        """Recorded for reporting only. Never used to decide any leg status (constraint 1)."""
        self.chunk_count = int(count)

    # ---- exception boundary ----------------------------------------------------------------------

    def route_execution(self, routes, call):
        """Run one call per route, converting each failure into a leg fact at the boundary.

        Intended as the deployment insertion point: the caller passes the route list and the callable
        that performs a single route lookup, and this method reports per-route outcomes. Aggregate leg
        status is derived only from these per-route outcomes.
        """
        attempted = 0
        succeeded = 0
        failures: list = []
        for route in routes:
            attempted += 1
            try:
                call(route)
            except Exception as exc:  # noqa: BLE001 - the boundary is the point
                failures.append((route, exc))
            else:
                succeeded += 1
        return attempted, succeeded, failures

    # ---- aggregation ----------------------------------------------------------------------------

    def execution(self) -> ExecutionHealth:
        return ExecutionHealth(legs=dict(self.legs))

    def evidence_state(self) -> EvidenceState:
        """Conservative by construction: execution facts can never yield `full`."""
        if not self._evidence_leg_results:
            completeness = Completeness.INSUFFICIENT
        elif any(self._evidence_leg_results.values()) and not all(self._evidence_leg_results.values()):
            completeness = Completeness.PARTIAL if self.chunk_count else Completeness.INSUFFICIENT
        elif all(self._evidence_leg_results.values()):
            completeness = Completeness.PARTIAL if self.chunk_count else Completeness.INSUFFICIENT
        else:
            completeness = Completeness.INSUFFICIENT
        return EvidenceState(
            completeness=completeness,
            support_level="unvalidated",
            authority=None,
            chunk_count=self.chunk_count,
        )

    def build(self) -> RetrievalHealth:
        health = RetrievalHealth(
            execution=self.execution(),
            evidence=self.evidence_state(),
            alerts=list(self.alerts),
            plan_version=self.plan_version,
        )
        self.emit_event(health)
        return health

    def emit_event(self, health: RetrievalHealth) -> dict:
        event = {
            "event": "retrieval_health",
            "question_id": self.question_id,
            "plan_version": health.plan_version,
            "overall": health.overall.value,
            "evidence_completeness": health.evidence.completeness.value,
            "degradation_reason": health.degradation_reason(),
            "degraded_legs": health.degraded_leg_names(),
            "leg_status": {name: leg.status.value for name, leg in self.legs.items()},
            "contract_violations": health.validate(),
        }
        self.events.append(event)
        self._log_operator_event(health)
        return event

    #: P0-7 operator event: the complete set of fields that may reach the log sink.
    OPERATOR_EVENT_FIELDS = (
        "event",
        "schema_version",
        "overall",
        "reason",
        "evidence_completeness",
        "legs",
        "contract_valid",
        "routes_attempted",
        "routes_succeeded",
    )

    def _log_operator_event(self, health: RetrievalHealth) -> None:
        """Write exactly ONE structured line per retrieval to the operator log.

        The payload is built as an explicit literal, never by spreading a session or a report object,
        so no exception text, provider body, query text, chunk content or credential can reach the log
        even if such a field is ever added downstream. `legs` carries member names and status enums
        only, which is why it is safe to include.

        Exactly-once is structural: the first emission wins and any later `build()`/`emit_event()` on
        the same session is a no-op for the sink.
        """
        if self.__dict__.get("_operator_event_logged"):
            return
        self.__dict__["_operator_event_logged"] = True

        counters = self.__dict__.get("_route_counters") or {}
        payload = {
            "event": "retrieval_health",
            "schema_version": health.schema_version,
            "overall": health.overall.value,
            "reason": health.degradation_reason(),
            "evidence_completeness": health.evidence.completeness.value,
            "legs": {name: leg.status.value for name, leg in self.legs.items()},
            "contract_valid": health.validate() == [],
            "routes_attempted": int(counters.get("attempted", 0) or 0),
            "routes_succeeded": int(counters.get("succeeded", 0) or 0),
        }
        _LOG.info("[RetrievalHealth] %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def build_with_validation(self, validator) -> RetrievalHealth:
        """Aggregate and, only via an explicit validator, allow the evidence to be upgraded.

        `validator(evidence, execution)` must return an explicit verdict object exposing
        `completeness`, `support_level`, `authority` and `validator_id`, or `None` to decline.
        """
        health = self.build()
        verdict = validator(health.evidence, health.execution) if validator is not None else None
        if verdict is None:
            return health
        upgraded = EvidenceState(
            completeness=verdict.completeness,
            support_level=getattr(verdict, "support_level", "validated"),
            authority=getattr(verdict, "validator_id", None),
            families=list(getattr(verdict, "families", []) or []),
            chunk_count=health.evidence.chunk_count,
        )
        return RetrievalHealth(execution=health.execution, evidence=upgraded, alerts=list(health.alerts), plan_version=health.plan_version)


class AuthorityVerdict:
    """An explicit, attributable evidence upgrade from a named validator."""

    def __init__(self, completeness: Completeness, validator_id: str, support_level: str = "validated", families=None):
        self.completeness = completeness
        self.validator_id = validator_id
        self.support_level = support_level
        self.families = list(families or [])


def circuit_breaker_skip(session: HealthSession, leg: str, breaker_open: bool, budget_exhausted: bool = False) -> bool:
    """Policy gate helper: reports `skipped` with a policy reason, never `not_triggered`."""
    if breaker_open:
        session.leg_skipped(leg, "CIRCUIT_BREAKER_OPEN")
        return True
    if budget_exhausted:
        session.leg_skipped(leg, "BUDGET_GUARD_TRIPPED")
        return True
    return False
