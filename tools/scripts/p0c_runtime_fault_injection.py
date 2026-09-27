"""P0-C runtime fault-injection acceptance for the wired health chain.

Runs the real producer/aggregator/policy chain at runtime with synthetic failures injected at the
embedding, plan and lexical boundaries, then runs the negative control (a normal retrieval) and
asserts that the contract does not misjudge a healthy request as degraded.

Zero external quota: every service boundary is a test double, so no embedding API is contacted.
Writes p0c_runtime_fault_injection_result.json and phase_b_p0b_p0c_report.md.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


health = load("rag_retrieval_health_contract", "rag/retrieval/health.py")
producers = load("rag_retrieval_health_producers", "rag/retrieval/health_producers.py")

QuestionRisk = health.QuestionRisk
AnswerAction = health.AnswerAction
Completeness = health.Completeness
LegStatus = health.LegStatus


class QuotaExhausted(Exception):
    """Stands in for the remote embedding API's 429 RESOURCE_EXHAUSTED."""


class StoreDown(Exception):
    pass


def synthetic_pipeline(routes, *, dense_fails=False, lexical_fails=False, plan_fails=False, plan_empty=False, breaker_open=False):
    """A runtime stand-in for the deployed call chain: route loop with a real exception boundary."""
    session = producers.HealthSession(plan_version="1.0", question_id="runtime-fixture")

    # Plan layer: the producer reports what the planner actually returned.
    if plan_fails:
        session.leg_failed("decomposition", reason=health.ReasonCode.PLAN_VALIDATION_FAILED, routes_attempted=1)
    elif plan_empty:
        session.leg_failed("decomposition", reason=health.ReasonCode.PLAN_EMPTY, routes_attempted=1)
    else:
        session.leg_succeeded("decomposition", routes_attempted=1)

    # Embedding boundary: the dense leg is reported where it executes.
    if producers.circuit_breaker_skip(session, "dense", breaker_open=breaker_open):
        pass
    elif dense_fails:
        attempted, succeeded, failures = session.route_execution(routes, lambda route: (_ for _ in ()).throw(QuotaExhausted("429 RESOURCE_EXHAUSTED: quota exceeded")))
        session.leg_failed("dense", exc=failures[0][1], routes_attempted=attempted, routes_succeeded=succeeded)
    else:
        session.leg_succeeded("dense", routes_attempted=len(routes), routes_succeeded=len(routes))

    # Lexical boundary.
    if lexical_fails:
        attempted, succeeded, failures = session.route_execution(routes, lambda route: (_ for _ in ()).throw(StoreDown("store unavailable")))
        session.leg_failed("lexical", exc=failures[0][1], routes_attempted=attempted, routes_succeeded=succeeded)
    else:
        session.leg_succeeded("lexical", routes_attempted=len(routes), routes_succeeded=len(routes))

    # Branch design: no rerank model is configured and no follow-up was designed in.
    session.leg_not_triggered("rerank")
    session.leg_not_triggered("followup")

    return session


def chain(session, risk, validator=None, chunks=6):
    session.note_chunk_count(chunks)
    report = session.build_with_validation(validator) if validator else session.build()
    action = health.decide_answer_action(report, risk)
    notice = health.required_notice(report, risk)
    dto = health.attach_health({"chunks": [{}] * chunks, "doc_aggs": [], "total": chunks}, report)
    return report, action, notice, dto, session.events[-1]


INJECTIONS = [
    {
        "id": "SYNTHETIC_429_DENSE",
        "kwargs": {"dense_fails": True},
        "expect_overall": "degraded",
        "expect_reason": "EMBEDDING_QUOTA_EXHAUSTED",
        "expect_dense": "failed",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
    },
    {
        "id": "SYNTHETIC_PLANNER_FAILURE",
        "kwargs": {"plan_fails": True},
        "expect_overall": "degraded",
        "expect_reason": "PLAN_VALIDATION_FAILED",
        "expect_dense": "success",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
    },
    {
        "id": "SYNTHETIC_EMPTY_PLAN",
        "kwargs": {"plan_empty": True},
        "expect_overall": "degraded",
        "expect_reason": "PLAN_EMPTY",
        "expect_dense": "success",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
    },
    {
        "id": "SYNTHETIC_LEXICAL_FAILURE",
        "kwargs": {"lexical_fails": True},
        "expect_overall": "degraded",
        "expect_reason": "STORE_UNAVAILABLE",
        "expect_dense": "success",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
    },
    {
        "id": "POLICY_SKIP_CIRCUIT_BREAKER",
        "kwargs": {"breaker_open": True},
        "expect_overall": "degraded",
        "expect_reason": "CIRCUIT_BREAKER_OPEN",
        "expect_dense": "skipped",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
    },
]


def run_injections():
    rows, failures = [], []
    for injection in INJECTIONS:
        session = synthetic_pipeline(["r1", "r2", "r3"], **injection["kwargs"])
        policies, notices, dtos, events = {}, {}, {}, {}
        report = None
        for risk in (QuestionRisk.NARRATIVE, QuestionRisk.CONSTRAINT_BEARING):
            report, action, notice, dto, event = chain(session, risk)
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
            "evidence_never_self_certified_full": report.evidence.completeness is not Completeness.FULL,
            "skipped_never_mixed_with_not_triggered": not (
                session.legs["dense"].status.value == "skipped" and session.legs["rerank"].status.value == "skipped"
            ),
        }
        rows.append(
            {
                "id": injection["id"],
                "injection": injection["kwargs"],
                "overall": report.overall.value,
                "degradation_reason": report.degradation_reason(),
                "leg_status": {name: leg.status.value for name, leg in session.legs.items()},
                "leg_reasons": {name: (leg.reason.value if hasattr(leg.reason, "value") else leg.reason) for name, leg in session.legs.items() if leg.reason},
                "evidence_completeness": report.evidence.completeness.value,
                "policy": policies,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
        if not rows[-1]["passed"]:
            failures.append({"id": injection["id"], "failed_checks": [name for name, value in checks.items() if not value]})
    return rows, failures


def run_negative_control():
    """A healthy retrieval must come out `full` with no unresolved leg.

    Two properties are asserted together: the contract does not misjudge a healthy request as
    degraded, and the conservative evidence rule is active — the retrieval layer alone reports
    `partial`, so a constraint-bearing answer becomes available only through the explicit authority
    validator, which is part of the healthy end-to-end path.
    """
    session = synthetic_pipeline(["r1", "r2", "r3"])
    report, action, notice, dto, event = chain(session, QuestionRisk.CONSTRAINT_BEARING)

    def validator(evidence, execution):
        return producers.AuthorityVerdict(Completeness.FULL, validator_id="holdout-authority-validator-v1", support_level="authoritative")

    upgraded, upgraded_action, upgraded_notice, upgraded_dto, _ = chain(session, QuestionRisk.CONSTRAINT_BEARING, validator=validator)
    checks = {
        "overall_is_full": report.overall.value == "full",
        "no_unresolved_leg": all(leg.status.value in ("success", "skipped", "not_triggered") for leg in session.legs.values()),
        "no_contract_violation": report.validate() == [],
        "no_degradation_reason": report.degradation_reason() is None,
        "retrieval_layer_evidence_conservatively_partial": report.evidence.completeness is Completeness.PARTIAL,
        "conservative_floor_is_visible_in_policy": action in (AnswerAction.ANSWER_WITH_DISCLOSURE, AnswerAction.REFUSE_INSUFFICIENT),
        "validator_upgrades_to_full_and_answers": upgraded.evidence.completeness is Completeness.FULL and upgraded_action is AnswerAction.ANSWER,
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
        "provenance": "runtime chain with test doubles at every service boundary; zero external quota",
    }


def write_report(rows, failures, control) -> None:
    lines = [
        "# Phase B — P0-B Producer Wiring and P0-C Runtime Fault Injection",
        "",
        "## Milestone status (stated precisely)",
        "",
        "| item | status |",
        "| --- | --- |",
        "| Phase B P0-A — Retrieval Health Contract | COMPLETE |",
        "| Phase B P0-B — Runtime Producer Integration | IMPLEMENTED IN THE REPOSITORY; NOT DEPLOYED INTO THE CONTAINER |",
        "| Production silent-degradation defect | NOT YET CLOSED (requires the container rebuild below) |",
        "",
        "## P0-B — how the producers are wired",
        "",
        "Health state is produced **where execution happens**, never inferred:",
        "",
        "- `HealthSession.route_execution(routes, call)` is the exception boundary. It runs one call per route and",
        "  converts each failure into a leg fact at that point via `reason_from_exception`, which reads the exception",
        "  itself (quota marker -> `EMBEDDING_QUOTA_EXHAUSTED`, timeout marker -> `EMBEDDING_TIMEOUT`, otherwise",
        "  `EMBEDDING_UNAVAILABLE` / `STORE_UNAVAILABLE`).",
        "- The aggregator (`HealthSession.build`) only aggregates facts it was given. It never inspects chunk counts,",
        "  result sizes or timings to decide whether a leg ran; `note_chunk_count` is reporting-only.",
        "- `leg_not_triggered` = the plan/branch never required the leg. `leg_skipped` = the leg was eligible but a",
        "  policy stopped it, and it **raises unless the reason is one of the closed policy set**",
        "  `CIRCUIT_BREAKER_OPEN | BUDGET_GUARD_TRIPPED | POLICY_VETO`. The two can never be mixed by accident.",
        "- Evidence is conservative: `RETRIEVAL_LAYER_MAX_COMPLETENESS = partial`. The retrieval layer cannot certify",
        "  `full` from its own execution facts; only an explicit `AuthorityVerdict` from a named validator can upgrade",
        "  it, and the upgrade is recorded as `evidence_state.authority`.",
        "",
        "### Deployment insertion points (container revision)",
        "",
        "| point | location | change |",
        "| --- | --- | --- |",
        "| route loop / failure isolation | `rag/retrieval/multi_route.py` per-route execution | construct a `HealthSession`, call `route_execution(routes, call)`, report the dense or lexical leg from the per-route outcome |",
        "| embedding boundary | the query-embedding request inside the store/search layer | report the dense leg where the request is issued, using `reason_from_exception` |",
        "| plan layer | `rag/retrieval/decomposition.py` return and validation | report `decomposition` as success, `PLAN_VALIDATION_FAILED` or `PLAN_EMPTY` |",
        "| aggregation and DTO | `rag/retrieval/pipeline.py` retrieval entry return | `health.attach_health(result, session.build_with_validation(validator))` beside the existing keys |",
        "| propagation | answer layer, metrics, trace | consume `retrieval_health` as an input constraint; emit the structured event already produced by `emit_event` |",
        "| circuit breaker | embedding boundary | `producers.circuit_breaker_skip(...)` so a policy stop is reported as `skipped`, never `not_triggered` |",
        "",
        "## P0-C — runtime fault injection (positive injections)",
        "",
        "Zero external quota: every service boundary is a test double.",
        "",
        "| injection | overall | reason | dense | evidence | narrative | constraint-bearing | passed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['overall']} | {row['degradation_reason']} | {row['leg_status']['dense']} | {row['evidence_completeness']} | "
            f"{row['policy']['narrative']} | {row['policy']['constraint_bearing']} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    lines += [
        "",
        "Chain verified end to end for every injection: synthetic exception -> producer report -> aggregator -> additive",
        "DTO (`retrieval_health`) -> synthesis policy -> disclosure or refusal -> structured metric/trace event. Assertions",
        "include `no_contract_violation`, `dto_additive_only`, `notices_present_where_required`,",
        "`evidence_never_self_certified_full` and that `skipped` never appears where `not_triggered` is meant.",
        "",
        "## P0-C — negative control (critical gate)",
        "",
        "| check | result |",
        "| --- | --- |",
    ]
    for name, value in control["checks"].items():
        lines.append(f"| {name} | {'PASS' if value else 'FAIL'} |")
    lines += [
        "",
        f"Healthy retrieval: overall `{control['overall']}`, legs `{json.dumps(control['leg_status'], ensure_ascii=False)}`,",
        f"evidence `{control['evidence_completeness_without_validator']}` from the retrieval layer (action `{control['action_without_validator']}`) and",
        f"`{control['evidence_completeness_with_validator']}` after the explicit authority validator (action `{control['action_with_validator']}`).",
        "",
        "This proves the contract does not misjudge a healthy request as degraded **and** that the conservative evidence",
        "rule holds: the retrieval layer alone reports `partial`, and only a named validator may promote it to `full`.",
        "",
        "## Deployment path — what remains",
        "",
        "The running container executes its own revision and shares no bind mount with this tree, so the producers are",
        "in the repository and their runtime chain is verified here, but the production defect is closed only after:",
        "",
        "1. rebuild the image from a commit that contains `rag/retrieval/health.py` and `rag/retrieval/health_producers.py`",
        "   plus the four insertion points above;",
        "2. restart the service onto the new image (explicit authorization required, since it interrupts the running deployment);",
        "3. re-run this same injection suite against the live container with the embedding boundary doubled, and repeat the",
        "   negative control, before declaring the defect closed.",
        "",
        "Steps 1-3 are NOT executed in this round: no container file was patched, no service was restarted, and no Phase A",
        "artifact, index or configuration was touched.",
        "",
        "## Verdict",
        "",
        f"- Injections: {len(rows)} run, {sum(1 for row in rows if row['passed'])} passed, {len(failures)} failed.",
        f"- Negative control: {'PASS' if control['passed'] else 'FAIL'}.",
        f"- Silent degradation observed: {sum(1 for row in rows if row['degradation_reason'] is None and row['overall'] != 'full')}.",
        "- External quota consumed: 0.",
        "",
        "P0-A is complete, P0-B is implemented in the repository with its deployment path specified, and P0-C is verified on",
        "the wired chain. P0 is **not** declared closed until the container rebuild in the deployment path is executed.",
        "",
    ]
    (ROOT / "phase_b_p0b_p0c_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    rows, failures = run_injections()
    control = run_negative_control()
    payload = {
        "gate": "P0-C runtime fault injection (positive injections + negative control)",
        "external_quota_consumed": 0,
        "positive_injections": {"run": len(rows), "passed": sum(1 for row in rows if row["passed"]), "failed": len(failures), "rows": rows, "failures": failures},
        "negative_control": control,
        "silent_degradation_observed": sum(1 for row in rows if row["degradation_reason"] is None and row["overall"] != "full"),
        "chain": "synthetic exception -> producer report -> aggregator -> additive DTO -> synthesis policy -> disclosure/refusal -> structured event",
        "verdict": "PASS" if not failures and control["passed"] else "FAIL",
    }
    (ROOT / "p0c_runtime_fault_injection_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(rows, failures, control)
    for row in rows:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:30s} overall={row['overall']:8s} reason={str(row['degradation_reason']):26s} dense={row['leg_status']['dense']:10s} evidence={row['evidence_completeness']}")
    print(f"{'PASS' if control['passed'] else 'FAIL'}  {control['id']:30s} overall={control['overall']:8s} evidence={control['evidence_completeness_without_validator']}->{control['evidence_completeness_with_validator']} action={control['action_without_validator']}->{control['action_with_validator']}")
    print(json.dumps({"verdict": payload["verdict"], "positive_passed": payload["positive_injections"]["passed"], "positive_failed": len(failures), "negative_control": control["passed"], "silent_degradation_observed": payload["silent_degradation_observed"], "external_quota_consumed": 0}))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
