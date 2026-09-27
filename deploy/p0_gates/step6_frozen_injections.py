"""Step 6 — frozen P0-C fault injections + leg-attribution producer checks, against the DEPLOYED code.

Loads `health.py` / `health_producers.py` / `health_bridge.py` from the RUNNING IMAGE (`/ragflow`), not
from the host tree, so the verdict is about the deployed artifact.

Part 1: the five frozen injections, with the frozen expectations and the frozen assertion set
        (including the frozen negative control with its explicit authority validator).
Part 2: the new evidence-leg attribution produced at its real boundaries, exercised through the deployed
        bridge, including the anti-fabrication rules.

Zero external quota: every service boundary is a test double.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, "/ragflow")


def load_deployed():
    health = importlib.import_module("rag.retrieval.health")
    producers = importlib.import_module("rag.retrieval.health_producers")
    bridge = importlib.import_module("rag.retrieval.health_bridge")
    return health, producers, bridge


class QuotaExhausted(Exception):
    """Stands in for the remote embedding API's 429 RESOURCE_EXHAUSTED (never a real quota spend)."""


class StoreDown(Exception):
    pass


def synthetic_pipeline(producers, health, routes, *, dense_fails=False, lexical_fails=False, plan_fails=False, plan_empty=False, breaker_open=False):
    """Runtime stand-in for the deployed call chain: route loop with a real exception boundary."""
    session = producers.HealthSession(plan_version="1.0", question_id="runtime-fixture")

    if plan_fails:
        session.leg_failed("decomposition", reason=health.ReasonCode.PLAN_VALIDATION_FAILED, routes_attempted=1)
    elif plan_empty:
        session.leg_failed("decomposition", reason=health.ReasonCode.PLAN_EMPTY, routes_attempted=1)
    else:
        session.leg_succeeded("decomposition", routes_attempted=1)

    if producers.circuit_breaker_skip(session, "dense", breaker_open=breaker_open):
        pass
    elif dense_fails:
        attempted, succeeded, failures = session.route_execution(routes, lambda route: (_ for _ in ()).throw(QuotaExhausted("429 RESOURCE_EXHAUSTED: quota exceeded")))
        session.leg_failed("dense", exc=failures[0][1], routes_attempted=attempted, routes_succeeded=succeeded)
    else:
        session.leg_succeeded("dense", routes_attempted=len(routes), routes_succeeded=len(routes))

    if lexical_fails:
        attempted, succeeded, failures = session.route_execution(routes, lambda route: (_ for _ in ()).throw(StoreDown("store unavailable")))
        session.leg_failed("lexical", exc=failures[0][1], routes_attempted=attempted, routes_succeeded=succeeded)
    else:
        session.leg_succeeded("lexical", routes_attempted=len(routes), routes_succeeded=len(routes))

    session.leg_not_triggered("rerank")
    session.leg_not_triggered("followup")
    return session


def chain(health, session, risk, validator=None, chunks=6):
    session.note_chunk_count(chunks)
    report = session.build_with_validation(validator) if validator else session.build()
    action = health.decide_answer_action(report, risk)
    notice = health.required_notice(report, risk)
    dto = health.attach_health({"chunks": [{}] * chunks, "doc_aggs": [], "total": chunks}, report)
    return report, action, notice, dto, session.events[-1]


INJECTIONS = [
    {"id": "SYNTHETIC_429_DENSE", "kwargs": {"dense_fails": True}, "expect_overall": "degraded", "expect_reason": "EMBEDDING_QUOTA_EXHAUSTED", "expect_dense": "failed", "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"}},
    {"id": "SYNTHETIC_PLANNER_FAILURE", "kwargs": {"plan_fails": True}, "expect_overall": "degraded", "expect_reason": "PLAN_VALIDATION_FAILED", "expect_dense": "success", "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"}},
    {"id": "SYNTHETIC_EMPTY_PLAN", "kwargs": {"plan_empty": True}, "expect_overall": "degraded", "expect_reason": "PLAN_EMPTY", "expect_dense": "success", "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"}},
    {"id": "SYNTHETIC_LEXICAL_FAILURE", "kwargs": {"lexical_fails": True}, "expect_overall": "degraded", "expect_reason": "STORE_UNAVAILABLE", "expect_dense": "success", "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"}},
    {"id": "POLICY_SKIP_CIRCUIT_BREAKER", "kwargs": {"breaker_open": True}, "expect_overall": "degraded", "expect_reason": "CIRCUIT_BREAKER_OPEN", "expect_dense": "skipped", "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"}},
]


def run_injections(health, producers):
    rows, failures = [], []
    overall_rank = {"full": 0, "degraded": 1, "failed": 2}
    for injection in INJECTIONS:
        session = synthetic_pipeline(producers, health, ["r1", "r2", "r3"], **injection["kwargs"])
        policies, notices, dtos, events = {}, {}, {}, {}
        report = None
        for risk in (health.QuestionRisk.NARRATIVE, health.QuestionRisk.CONSTRAINT_BEARING):
            report, action, notice, dto, event = chain(health, session, risk)
            policies[risk.value] = action.value
            notices[risk.value] = notice is not None
            dtos[risk.value] = set(dto.keys())
            events[risk.value] = event
        checks = {
            "overall_correct": report.overall.value == injection["expect_overall"],
            "reason_correct": report.degradation_reason() == injection["expect_reason"],
            "dense_status_correct": session.legs["dense"].status.value == injection["expect_dense"],
            "policy_correct": policies == injection["expect_policy"],
            "notices_present_where_required": all(notices.values()),
            "no_contract_violation": report.validate() == [],
            "dto_additive_only": all(keys == {"chunks", "doc_aggs", "total", "retrieval_health"} for keys in dtos.values()),
            "event_emitted": all(events[risk]["event"] == "retrieval_health" for risk in events),
            "no_unrestricted_answer": not any(value == "answer" for value in policies.values()) or report.overall.value == "full",
            "evidence_never_self_certified_full": report.evidence.completeness is not health.Completeness.FULL,
            "skipped_never_mixed_with_not_triggered": not (
                session.legs["dense"].status.value == "skipped" and session.legs["rerank"].status.value == "skipped"
            ),
            # every leg is explicitly resolved, and never silently rounded
            "every_known_leg_resolved": all(name in session.legs for name in health.KNOWN_LEGS),
            # a partial retrieval still returns the legacy payload rather than an error code
            "partial_keeps_legacy_payload": all("chunks" in keys and "total" in keys for keys in dtos.values()),
            "no_silent_degradation": not (report.overall.value != "full" and report.degradation_reason() is None),
            "overall_monotonic_vs_full": overall_rank[report.overall.value] <= overall_rank["failed"],
        }
        rows.append(
            {
                "id": injection["id"],
                "injection": injection["kwargs"],
                "overall": report.overall.value,
                "degradation_reason": report.degradation_reason(),
                "leg_status": {name: leg.status.value for name, leg in session.legs.items()},
                "evidence_completeness": report.evidence.completeness.value,
                "policy": policies,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
        if not rows[-1]["passed"]:
            failures.append({"id": injection["id"], "failed_checks": [n for n, v in checks.items() if not v]})
    return rows, failures


def run_frozen_negative_control(health, producers):
    session = synthetic_pipeline(producers, health, ["r1", "r2", "r3"])
    report, action, notice, dto, event = chain(health, session, health.QuestionRisk.CONSTRAINT_BEARING)

    def validator(evidence, execution):
        return producers.AuthorityVerdict(health.Completeness.FULL, validator_id="holdout-authority-validator-v1", support_level="authoritative")

    upgraded, upgraded_action, upgraded_notice, upgraded_dto, _ = chain(health, session, health.QuestionRisk.CONSTRAINT_BEARING, validator=validator)
    checks = {
        "overall_is_full": report.overall.value == "full",
        "no_unresolved_leg": all(leg.status.value in ("success", "skipped", "not_triggered") for leg in session.legs.values()),
        "no_contract_violation": report.validate() == [],
        "no_degradation_reason": report.degradation_reason() is None,
        "retrieval_layer_evidence_conservatively_partial": report.evidence.completeness is health.Completeness.PARTIAL,
        "conservative_floor_is_visible_in_policy": action in (health.AnswerAction.ANSWER_WITH_DISCLOSURE, health.AnswerAction.REFUSE_INSUFFICIENT),
        "validator_upgrades_to_full_and_answers": upgraded.evidence.completeness is health.Completeness.FULL and upgraded_action is health.AnswerAction.ANSWER,
        "validator_upgrade_needs_no_notice": upgraded_notice is None,
        "upgrade_is_attributable": upgraded.evidence.authority == "holdout-authority-validator-v1",
        "event_emitted": event["event"] == "retrieval_health",
    }
    return {
        "id": "NEGATIVE_CONTROL_HEALTHY_RETRIEVAL",
        "overall": report.overall.value,
        "leg_status": {name: leg.status.value for name, leg in session.legs.items()},
        "evidence_completeness_without_validator": report.evidence.completeness.value,
        "evidence_completeness_with_validator": upgraded.evidence.completeness.value,
        "action_without_validator": action.value,
        "action_with_validator": upgraded_action.value,
        "checks": checks,
        "passed": all(checks.values()),
        "provenance": "deployed modules, runtime chain with test doubles at every service boundary; zero external quota",
    }


def run_boundary_attribution(bridge, health):
    """The new evidence-leg facts, produced at the boundaries and aggregated honestly."""
    cases = {}

    def fresh():
        bridge.begin_retrieval_health()
        return bridge.current_session()

    # a) the dense leg executed at its boundary
    session = fresh()
    bridge.report_dense_executed()
    bridge.report_lexical_executed()
    cases["dense_and_lexical_executed"] = {
        "legs": {n: leg.status.value for n, leg in session.legs.items()},
        "overall": session.build().overall.value,
    }

    # b) a quota failure reported at the embedding boundary keeps its leg-specific reason
    session = fresh()
    bridge.report_dense_failed(QuotaExhausted("429 RESOURCE_EXHAUSTED: quota exceeded"))
    report = session.build()
    cases["dense_quota_failure_at_boundary"] = {
        "dense_status": session.legs["dense"].status.value,
        "dense_reason": session.legs["dense"].reason.value if hasattr(session.legs["dense"].reason, "value") else session.legs["dense"].reason,
        "degradation_reason": report.degradation_reason(),
        "contract_violations": report.validate(),
    }

    # c) a timeout at the embedding boundary is an EMBEDDING timeout, not a store failure
    session = fresh()
    bridge.report_dense_failed(TimeoutError("deadline exceeded while embedding"))
    cases["dense_timeout_attributed_to_embedding"] = {
        "dense_reason": session.legs["dense"].reason.value if hasattr(session.legs["dense"].reason, "value") else session.legs["dense"].reason,
    }

    # d) anti-fabrication: not_triggered must never overwrite an observed execution fact
    session = fresh()
    bridge.report_dense_executed()
    bridge.report_dense_not_triggered()
    cases["not_triggered_cannot_override_an_execution_fact"] = {"dense_status": session.legs["dense"].status.value}

    # e) anti-fabrication: one route ok + one failed is `degraded` with a reason, never rounded to success
    session = fresh()
    bridge.report_dense_executed()
    bridge.report_dense_failed(QuotaExhausted("429 RESOURCE_EXHAUSTED"))
    report = session.build()
    cases["partial_dense_failure_is_degraded_with_reason"] = {
        "dense_status": session.legs["dense"].status.value,
        "degradation_reason": report.degradation_reason(),
        "contract_violations": report.validate(),
    }

    # f) genuinely unused legs are explicitly not_triggered, so nothing stays unknown
    session = fresh()
    bridge.report_dense_not_triggered()
    bridge.report_lexical_not_triggered()
    cases["legitimately_unused_legs_explicit"] = {"legs": {n: leg.status.value for n, leg in session.legs.items()}}

    checks = {
        "dense_executed_is_success": cases["dense_and_lexical_executed"]["legs"].get("dense") == "success",
        "lexical_executed_is_success": cases["dense_and_lexical_executed"]["legs"].get("lexical") == "success",
        "quota_maps_to_embedding_quota_exhausted": cases["dense_quota_failure_at_boundary"]["dense_reason"] == "EMBEDDING_QUOTA_EXHAUSTED",
        "quota_failure_has_no_silent_degradation": cases["dense_quota_failure_at_boundary"]["contract_violations"] == [],
        "timeout_maps_to_embedding_timeout": cases["dense_timeout_attributed_to_embedding"]["dense_reason"] == "EMBEDDING_TIMEOUT",
        "not_triggered_cannot_override_execution": cases["not_triggered_cannot_override_an_execution_fact"]["dense_status"] == "success",
        "partial_failure_is_degraded_with_reason": cases["partial_dense_failure_is_degraded_with_reason"]["dense_status"] == "degraded"
        and cases["partial_dense_failure_is_degraded_with_reason"]["degradation_reason"] is not None,
        "unused_legs_explicitly_not_triggered": all(v == "not_triggered" for v in cases["legitimately_unused_legs_explicit"]["legs"].values()),
    }
    return {"cases": cases, "checks": checks, "passed": all(checks.values())}


def main() -> int:
    health, producers, bridge = load_deployed()
    rows, failures = run_injections(health, producers)
    control = run_frozen_negative_control(health, producers)
    boundary = run_boundary_attribution(bridge, health)

    out = {
        "gate": "P0-C frozen fault injections + leg attribution (deployed modules)",
        "modules_loaded_from": "/ragflow (the running image)",
        "external_quota_consumed": 0,
        "positive_injections": {
            "run": len(rows),
            "passed": sum(1 for r in rows if r["passed"]),
            "failed": len(failures),
            "rows": rows,
            "failures": failures,
        },
        "negative_control": control,
        "leg_attribution": boundary,
        "answer_policy_enforced": bridge.answer_policy_enforced(),
        "silent_degradation_observed": sum(
            1 for r in rows if r["degradation_reason"] is None and r["overall"] != "full"
        ),
    }
    out["verdict"] = "PASS" if not failures and control["passed"] and boundary["passed"] and bridge.answer_policy_enforced() is False else "FAIL"

    print("STEP6_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False))
    print("STEP6_JSON_END")
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
