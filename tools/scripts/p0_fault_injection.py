"""P0 gate — fault injection against the retrieval health contract.

Injects the four failure classes required by the P0 acceptance gate and asserts that each one is
carried losslessly to the answer policy with **no silent degradation**:

    dense 429 (remote embedding quota exhausted)
    planner validation failure
    empty plan
    lexical leg failure

No external service is contacted and no embedding quota is consumed: the injections are constructed
states, and the assertions are pure contract logic. Writes p0_fault_injection_result.json.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("retrieval_health_contract", ROOT / "rag" / "retrieval" / "health.py")
health = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = health  # dataclass annotation resolution needs the module registered
spec.loader.exec_module(health)

LegHealth, LegStatus = health.LegHealth, health.LegStatus
ExecutionHealth, EvidenceState = health.ExecutionHealth, health.EvidenceState
Completeness, RetrievalHealth = health.Completeness, health.RetrievalHealth
ReasonCode, QuestionRisk = health.ReasonCode, health.QuestionRisk
AnswerAction = health.AnswerAction


def build(legs: dict, completeness: Completeness, chunks: int = 6) -> RetrievalHealth:
    execution = ExecutionHealth(legs={name: LegHealth(name=name, **body) for name, body in legs.items()})
    return RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=completeness, chunk_count=chunks))


def ok(status=LegStatus.SUCCESS, attempted=5, succeeded=5, reason=None):
    return {"status": status, "reason": reason, "routes_attempted": attempted, "routes_succeeded": succeeded}


INJECTIONS = [
    {
        "id": "DENSE_429_EVIDENCE_FULL",
        "injection": "dense leg fails with the remote embedding quota exhausted, lexical recall fully sufficient",
        "expect_overall": "degraded",
        "expect_reason": "EMBEDDING_QUOTA_EXHAUSTED",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "answer"},
        "report": lambda: build(
            {"lexical": ok(), "dense": ok(LegStatus.FAILED, 5, 0, ReasonCode.EMBEDDING_QUOTA_EXHAUSTED), "rerank": ok(LegStatus.SKIPPED, 0, 0, ReasonCode.RERANK_UNAVAILABLE)},
            Completeness.FULL,
        ),
    },
    {
        "id": "DENSE_429_EVIDENCE_PARTIAL",
        "injection": "dense leg fails and the surviving evidence covers only part of the question",
        "expect_overall": "degraded",
        "expect_reason": "EMBEDDING_QUOTA_EXHAUSTED",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
        "report": lambda: build(
            {"lexical": ok(), "dense": ok(LegStatus.FAILED, 5, 0, ReasonCode.EMBEDDING_QUOTA_EXHAUSTED)},
            Completeness.PARTIAL,
        ),
    },
    {
        "id": "PLANNER_VALIDATION_FAILED",
        "injection": "planner output rejected by schema validation and replaced by the deterministic pass-through plan",
        "expect_overall": "degraded",
        "expect_reason": "PLAN_VALIDATION_FAILED",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
        "report": lambda: build(
            {"decomposition": ok(LegStatus.DEGRADED, 1, 1, ReasonCode.PLAN_VALIDATION_FAILED), "lexical": ok(), "dense": ok()},
            Completeness.PARTIAL,
        ),
    },
    {
        "id": "EMPTY_PLAN",
        "injection": "planner returns no sub-queries; the pass-through plan is used but evidence is insufficient",
        "expect_overall": "degraded",
        "expect_reason": "PLAN_EMPTY",
        "expect_policy": {"narrative": "refuse_insufficient", "constraint_bearing": "refuse_insufficient"},
        "report": lambda: build(
            {"decomposition": ok(LegStatus.FAILED, 1, 0, ReasonCode.PLAN_EMPTY), "lexical": ok(LegStatus.SUCCESS, 5, 5), "dense": ok()},
            Completeness.INSUFFICIENT,
            chunks=0,
        ),
    },
    {
        "id": "LEXICAL_FAILED",
        "injection": "lexical leg fails while the dense leg succeeds; evidence is partial",
        "expect_overall": "degraded",
        "expect_reason": "STORE_UNAVAILABLE",
        "expect_policy": {"narrative": "answer_with_disclosure", "constraint_bearing": "refuse_insufficient"},
        "report": lambda: build(
            {"lexical": ok(LegStatus.FAILED, 5, 0, ReasonCode.STORE_UNAVAILABLE), "dense": ok()},
            Completeness.PARTIAL,
        ),
    },
    {
        "id": "TOTAL_FAILURE",
        "injection": "both evidence legs fail",
        "expect_overall": "failed",
        "expect_reason": "STORE_UNAVAILABLE",
        "expect_policy": {"narrative": "refuse_failed", "constraint_bearing": "refuse_failed"},
        "report": lambda: build(
            {"lexical": ok(LegStatus.FAILED, 5, 0, ReasonCode.STORE_UNAVAILABLE), "dense": ok(LegStatus.FAILED, 5, 0, ReasonCode.EMBEDDING_TIMEOUT)},
            Completeness.INSUFFICIENT,
            chunks=0,
        ),
    },
]


def main() -> int:
    rows, failures = [], []
    for injection in INJECTIONS:
        report = injection["report"]()
        problems = report.validate()
        policies = {
            risk.value: health.decide_answer_action(report, risk).value
            for risk in (QuestionRisk.NARRATIVE, QuestionRisk.CONSTRAINT_BEARING)
        }
        attached = health.attach_health({"chunks": [], "doc_aggs": [], "total": 0}, report)
        checks = {
            "overall_correct": report.overall.value == injection["expect_overall"],
            "reason_correct": report.degradation_reason() == injection["expect_reason"],
            "policy_correct": policies == injection["expect_policy"],
            "no_contract_violation": problems == [],
            "no_silent_degradation": report.degradation_reason() is not None,
            "notices_present": all(
                health.required_notice(report, risk) is not None
                for risk in (QuestionRisk.NARRATIVE, QuestionRisk.CONSTRAINT_BEARING)
                if policies[risk.value].startswith("refuse") or policies[risk.value].endswith("disclosure")
            ),
            "additive_field_only": set(attached.keys()) == {"chunks", "doc_aggs", "total", "retrieval_health"},
            "no_unrestricted_answer_after_failure": not (
                report.overall.value == "failed" and "answer" in policies.values()
            ),
        }
        rows.append(
            {
                "id": injection["id"],
                "injection": injection["injection"],
                "overall": report.overall.value,
                "degradation_reason": report.degradation_reason(),
                "degraded_legs": report.degraded_leg_names(),
                "evidence_completeness": report.evidence.completeness.value,
                "policy": policies,
                "contract_violations": problems,
                "checks": checks,
                "passed": all(checks.values()),
            }
        )
        if not rows[-1]["passed"]:
            failures.append({"id": injection["id"], "failed_checks": [name for name, value in checks.items() if not value]})

    payload = {
        "gate": "P0 fault-injection acceptance",
        "external_quota_consumed": 0,
        "injections": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "silent_degradation_observed": sum(1 for row in rows if row["degradation_reason"] is None and row["overall"] != "full"),
        "rows": rows,
        "failures": failures,
        "verdict": "PASS" if not failures else "FAIL",
    }
    (ROOT / "p0_fault_injection_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in rows:
        print(f"{'PASS' if row['passed'] else 'FAIL'}  {row['id']:26s} overall={row['overall']:8s} reason={str(row['degradation_reason']):26s} policy={row['policy']}")
    print(json.dumps({"verdict": payload["verdict"], "injections": payload["injections"], "passed": payload["passed"], "failed": payload["failed"], "silent_degradation_observed": payload["silent_degradation_observed"], "external_quota_consumed": payload["external_quota_consumed"]}))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
