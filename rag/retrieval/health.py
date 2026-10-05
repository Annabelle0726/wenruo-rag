"""Retrieval health contract (Phase B / P0).

Dependency-free by design so the contract can be unit-tested and fault-injected without a running
stack or any external service.

Two layers are kept strictly separate, per Revision 2 R2.5:

    RetrievalHealth
     |- execution_health  (machine-determined: per-leg status)
     `- evidence_state    (semantic sufficiency: is the evidence enough for the claim type)

Neither layer may be collapsed into the other: a degraded execution layer can still carry fully
sufficient evidence, and sufficient-looking execution can carry insufficient evidence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

HEALTH_SCHEMA_VERSION = "1.0"
EVIDENCE_LEGS = ("lexical", "dense")
KNOWN_LEGS = ("decomposition", "lexical", "dense", "rerank", "followup")


class LegStatus(str, Enum):
    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_TRIGGERED = "not_triggered"
    UNKNOWN = "unknown"


class OverallStatus(str, Enum):
    FULL = "full"
    DEGRADED = "degraded"
    FAILED = "failed"


class ReasonCode(str, Enum):
    EMBEDDING_QUOTA_EXHAUSTED = "EMBEDDING_QUOTA_EXHAUSTED"
    EMBEDDING_UNAVAILABLE = "EMBEDDING_UNAVAILABLE"
    EMBEDDING_TIMEOUT = "EMBEDDING_TIMEOUT"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    ROUTE_TIMEOUT = "ROUTE_TIMEOUT"
    PLAN_VALIDATION_FAILED = "PLAN_VALIDATION_FAILED"
    PLAN_EMPTY = "PLAN_EMPTY"
    RERANK_UNAVAILABLE = "RERANK_UNAVAILABLE"
    THRESHOLD_EMPTY = "THRESHOLD_EMPTY"
    FOLLOWUP_FAILED = "FOLLOWUP_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class Completeness(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class QuestionRisk(str, Enum):
    NARRATIVE = "narrative"
    CONSTRAINT_BEARING = "constraint_bearing"


class AnswerAction(str, Enum):
    ANSWER = "answer"
    ANSWER_WITH_DISCLOSURE = "answer_with_disclosure"
    REFUSE_INSUFFICIENT = "refuse_insufficient"
    REFUSE_FAILED = "refuse_failed"


DISCLOSURE_NOTICE = (
    "Retrieval ran in a reduced mode: part of the retrieval path was unavailable, so the evidence behind this "
    "answer may be incomplete."
)
INSUFFICIENT_NOTICE = (
    "The evidence retrieved for this question is incomplete, so no definitive conclusion can be given."
)
UNAVAILABLE_NOTICE = "Retrieval failed, so no factual answer can be produced for this question."

RANK = {
    LegStatus.SKIPPED: -1,
    LegStatus.NOT_TRIGGERED: -1,
    LegStatus.SUCCESS: 0,
    LegStatus.UNKNOWN: 1,
    LegStatus.DEGRADED: 1,
    LegStatus.FAILED: 2,
}
#: `not_triggered` is always neutral: the plan or branch never required the leg.
#: `skipped` is neutral only for a leg that does not produce evidence. A policy stop on an evidence
#: leg means the evidence was never gathered, so it can never yield `full` — treating it as neutral
#: was a silent-degradation hole and is exactly why the P0-C gate exists.
NEUTRAL = (LegStatus.NOT_TRIGGERED,)


def _value(item):
    return item.value if isinstance(item, Enum) else item


def _status(value) -> LegStatus:
    if isinstance(value, LegStatus):
        return value
    try:
        return LegStatus(str(value))
    except ValueError:
        return LegStatus.UNKNOWN


def _reason(value):
    if value is None or isinstance(value, ReasonCode):
        return value
    try:
        return ReasonCode(str(value))
    except ValueError:
        return str(value)


@dataclass
class LegHealth:
    name: str
    status: LegStatus = LegStatus.UNKNOWN
    reason: object = None
    routes_attempted: int = 0
    routes_succeeded: int = 0
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "status": _value(self.status),
            "reason": _value(self.reason),
            "routes_attempted": self.routes_attempted,
            "routes_succeeded": self.routes_succeeded,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload

    @classmethod
    def from_dict(cls, name: str, payload: dict) -> "LegHealth":
        return cls(
            name=name,
            status=_status(payload.get("status")),
            reason=_reason(payload.get("reason")),
            routes_attempted=int(payload.get("routes_attempted") or 0),
            routes_succeeded=int(payload.get("routes_succeeded") or 0),
            detail=dict(payload.get("detail") or {}),
        )


@dataclass
class ExecutionHealth:
    legs: dict = field(default_factory=dict)

    def leg(self, name: str) -> LegHealth:
        return self.legs.get(name) or LegHealth(name=name, status=LegStatus.UNKNOWN)

    def active(self) -> list:
        """Every known leg counts: an unreported leg is unknown and therefore never `full`.

        This is what makes "no silent degradation" enforceable: a caller that simply forgets to
        report the dense leg cannot obtain a `full` verdict, and legs that are legitimately not
        applicable must be reported explicitly as skipped or not_triggered.
        """
        names = list(KNOWN_LEGS) + [name for name in self.legs if name not in KNOWN_LEGS]
        active = []
        for name in names:
            leg = self.legs.get(name) or LegHealth(name=name, status=LegStatus.UNKNOWN)
            if leg.status in NEUTRAL:
                continue
            if leg.status is LegStatus.SKIPPED and name not in EVIDENCE_LEGS:
                continue  # a policy stop on a non-evidence leg does not affect evidence coverage
            active.append(leg)
        return active

    def overall(self) -> OverallStatus:
        active = self.active()
        if not active:
            return OverallStatus.DEGRADED
        if all(leg.status is LegStatus.SUCCESS for leg in active):
            return OverallStatus.FULL
        evidence = [leg for leg in active if leg.name in EVIDENCE_LEGS]
        if evidence and all(leg.status is LegStatus.FAILED for leg in evidence):
            return OverallStatus.FAILED
        return OverallStatus.DEGRADED

    def degraded_legs(self) -> list:
        reportable = []
        for leg in self.legs.values():
            if leg.status in (LegStatus.FAILED, LegStatus.DEGRADED):
                reportable.append((leg, leg.reason))
            elif leg.status is LegStatus.SKIPPED and leg.name in EVIDENCE_LEGS:
                reportable.append((leg, leg.reason))
        return reportable

    def to_dict(self) -> dict:
        return {name: leg.to_dict() for name, leg in self.legs.items()}

    @classmethod
    def from_dict(cls, payload: dict) -> "ExecutionHealth":
        return cls(legs={name: LegHealth.from_dict(name, body) for name, body in (payload or {}).items()})


@dataclass
class EvidenceState:
    completeness: Completeness = Completeness.INSUFFICIENT
    support_level: str = "unknown"
    authority: str | None = None
    families: list = field(default_factory=list)
    chunk_count: int = 0

    def to_dict(self) -> dict:
        return {
            "completeness": _value(self.completeness),
            "support_level": self.support_level,
            "authority": self.authority,
            "families": list(self.families),
            "chunk_count": self.chunk_count,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "EvidenceState":
        payload = payload or {}
        try:
            completeness = Completeness(str(payload.get("completeness")))
        except ValueError:
            completeness = Completeness.INSUFFICIENT
        return cls(
            completeness=completeness,
            support_level=str(payload.get("support_level") or "unknown"),
            authority=payload.get("authority"),
            families=list(payload.get("families") or []),
            chunk_count=int(payload.get("chunk_count") or 0),
        )


@dataclass
class RetrievalHealth:
    execution: ExecutionHealth = field(default_factory=ExecutionHealth)
    evidence: EvidenceState = field(default_factory=EvidenceState)
    alerts: list = field(default_factory=list)
    plan_version: str | None = None
    schema_version: str = HEALTH_SCHEMA_VERSION

    @property
    def overall(self) -> OverallStatus:
        status = self.execution.overall()
        if self.evidence.completeness is Completeness.INSUFFICIENT and status is OverallStatus.FULL:
            # Gate G7 in code form: a near-empty window never reports full.
            return OverallStatus.DEGRADED
        return status

    def degradation_reason(self):
        degraded = self.execution.degraded_legs()
        for leg, reason in degraded:
            if leg.status is LegStatus.FAILED and reason is not None:
                return _value(reason)
        for leg, reason in degraded:
            if reason is not None:
                return _value(reason)
        return None

    def degraded_leg_names(self) -> list:
        return [leg.name for leg, _ in self.execution.degraded_legs()]

    def validate(self) -> list:
        """Return the contract violations. An empty list means the health object is honest."""
        problems = []
        if self.overall is not OverallStatus.FULL and self.degradation_reason() is None:
            problems.append("SILENT_DEGRADATION: status is not full but no reason code is present")
        for leg in self.execution.legs.values():
            reportable = leg.status in (LegStatus.FAILED, LegStatus.DEGRADED) or (leg.status is LegStatus.SKIPPED and leg.name in EVIDENCE_LEGS)
            if reportable and leg.reason is None:
                problems.append(f"MISSING_REASON: leg {leg.name} is {leg.status.value} without a reason code")
            if leg.status is LegStatus.UNKNOWN:
                problems.append(f"UNRESOLVED_LEG: leg {leg.name} has an unknown status")
        if self.evidence.completeness is Completeness.INSUFFICIENT and self.execution.overall() is OverallStatus.FULL:
            problems.append("INSUFFICIENT_EVIDENCE_REPORTED_FULL")
        return problems

    def api_view(self) -> dict:
        return {
            "overall": self.overall.value,
            "evidence_completeness": self.evidence.completeness.value,
            "degradation_reason": self.degradation_reason(),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "overall": self.overall.value,
            "execution_health": self.execution.to_dict(),
            "evidence_state": self.evidence.to_dict(),
            "alerts": list(self.alerts),
            "plan_version": self.plan_version,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "RetrievalHealth":
        payload = payload or {}
        return cls(
            execution=ExecutionHealth.from_dict(payload.get("execution_health")),
            evidence=EvidenceState.from_dict(payload.get("evidence_state")),
            alerts=list(payload.get("alerts") or []),
            plan_version=payload.get("plan_version"),
            schema_version=str(payload.get("schema_version") or HEALTH_SCHEMA_VERSION),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "RetrievalHealth":
        return cls.from_dict(json.loads(text))


def decide_answer_action(health: RetrievalHealth, risk: QuestionRisk) -> AnswerAction:
    """Revision 2 R2.1: the criterion is evidence sufficiency for the claim type, not leg status."""
    if health.overall is OverallStatus.FAILED:
        return AnswerAction.REFUSE_FAILED
    if health.evidence.completeness is Completeness.INSUFFICIENT:
        return AnswerAction.REFUSE_INSUFFICIENT
    if health.evidence.completeness is Completeness.PARTIAL:
        return AnswerAction.ANSWER_WITH_DISCLOSURE if risk is QuestionRisk.NARRATIVE else AnswerAction.REFUSE_INSUFFICIENT
    if health.overall is OverallStatus.FULL:
        return AnswerAction.ANSWER
    return AnswerAction.ANSWER_WITH_DISCLOSURE if risk is QuestionRisk.NARRATIVE else AnswerAction.ANSWER


def required_notice(health: RetrievalHealth, risk: QuestionRisk) -> str | None:
    action = decide_answer_action(health, risk)
    if action is AnswerAction.ANSWER_WITH_DISCLOSURE:
        return DISCLOSURE_NOTICE
    if action is AnswerAction.REFUSE_INSUFFICIENT:
        return INSUFFICIENT_NOTICE
    if action is AnswerAction.REFUSE_FAILED:
        return UNAVAILABLE_NOTICE
    return None


def attach_health(result: dict, health: RetrievalHealth, include_detail: bool = False) -> dict:
    """Additive attachment: every existing key is preserved untouched."""
    payload = dict(result)
    payload["retrieval_health"] = health.api_view()
    if include_detail:
        payload["retrieval_health_detail"] = health.to_dict()
    return payload


def empty_evidence(counts: int = 0) -> EvidenceState:
    return EvidenceState(completeness=Completeness.INSUFFICIENT, chunk_count=counts)
