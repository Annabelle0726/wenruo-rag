"""Unit tests for the P0 retrieval health contract.

The contract module is dependency-free and is loaded directly from its path so these tests run
without importing the wider application package.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest

PATH = pathlib.Path(__file__).resolve().parents[4] / "rag" / "retrieval" / "health.py"
spec = importlib.util.spec_from_file_location("retrieval_health_contract", PATH)
health = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = health  # dataclass annotation resolution needs the module registered
spec.loader.exec_module(health)

LegHealth = health.LegHealth
LegStatus = health.LegStatus
ExecutionHealth = health.ExecutionHealth
EvidenceState = health.EvidenceState
Completeness = health.Completeness
RetrievalHealth = health.RetrievalHealth
OverallStatus = health.OverallStatus
ReasonCode = health.ReasonCode
QuestionRisk = health.QuestionRisk
AnswerAction = health.AnswerAction


DEFAULTS = {
    "decomposition": {"status": LegStatus.SKIPPED},
    "rerank": {"status": LegStatus.SKIPPED, "reason": ReasonCode.RERANK_UNAVAILABLE},
    "followup": {"status": LegStatus.NOT_TRIGGERED},
}


def legs(**specs) -> ExecutionHealth:
    merged = {name: dict(body) for name, body in DEFAULTS.items()}
    merged.update({name: dict(body) for name, body in specs.items()})
    return ExecutionHealth(legs={name: LegHealth(name=name, **body) for name, body in merged.items()})


def ok(status=LegStatus.SUCCESS, attempted=5, succeeded=5):
    return {"status": status, "routes_attempted": attempted, "routes_succeeded": succeeded}


class TestAggregation(unittest.TestCase):
    def test_all_success_is_full(self):
        self.assertEqual(legs(lexical=ok(), dense=ok()).overall(), OverallStatus.FULL)

    def test_neutral_legs_do_not_deny_full(self):
        execution = legs(lexical=ok(), dense=ok(), rerank={"status": LegStatus.SKIPPED, "reason": ReasonCode.RERANK_UNAVAILABLE}, followup={"status": LegStatus.NOT_TRIGGERED})
        self.assertEqual(execution.overall(), OverallStatus.FULL)

    def test_policy_skipped_evidence_leg_denies_full_and_is_reportable(self):
        # Found by the P0-C gate: a policy stop on an evidence leg means evidence was never
        # gathered, so it may not be neutral. Regression guard for that silent-degradation hole.
        execution = legs(lexical=ok(), dense={"status": LegStatus.SKIPPED, "reason": "CIRCUIT_BREAKER_OPEN"})
        self.assertEqual(execution.overall(), OverallStatus.DEGRADED)
        report = RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=Completeness.PARTIAL))
        self.assertEqual(report.degradation_reason(), "CIRCUIT_BREAKER_OPEN")
        self.assertEqual(report.validate(), [])
        self.assertIn("dense", report.degraded_leg_names())

    def test_policy_skipped_evidence_leg_without_reason_is_a_violation(self):
        execution = legs(lexical=ok(), dense={"status": LegStatus.SKIPPED})
        report = RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=Completeness.PARTIAL))
        self.assertTrue(any(problem.startswith("MISSING_REASON") for problem in report.validate()))

    def test_one_failed_leg_is_at_least_degraded(self):
        execution = legs(lexical=ok(), dense=ok(LegStatus.FAILED, 5, 0))
        execution.legs["dense"].reason = ReasonCode.EMBEDDING_QUOTA_EXHAUSTED
        self.assertEqual(execution.overall(), OverallStatus.DEGRADED)

    def test_all_evidence_legs_failed_is_failed(self):
        execution = legs(lexical=ok(LegStatus.FAILED, 5, 0), dense=ok(LegStatus.FAILED, 5, 0))
        self.assertEqual(execution.overall(), OverallStatus.FAILED)

    def test_unknown_leg_status_is_never_full(self):
        execution = legs(lexical=ok(), dense={"status": LegStatus.UNKNOWN})
        self.assertEqual(execution.overall(), OverallStatus.DEGRADED)

    def test_unreported_leg_is_unknown_and_never_full(self):
        execution = ExecutionHealth(legs={"lexical": LegHealth(name="lexical", status=LegStatus.SUCCESS)})
        self.assertEqual(execution.leg("dense").status, LegStatus.UNKNOWN)
        self.assertEqual(execution.overall(), OverallStatus.DEGRADED)  # an unreported leg denies full
        for name in ("decomposition", "rerank", "followup"):
            execution.legs[name] = LegHealth(name=name, status=LegStatus.SKIPPED)
        execution.legs["dense"] = LegHealth(name="dense", status=LegStatus.SUCCESS)
        self.assertEqual(execution.overall(), OverallStatus.FULL)  # explicit reporting earns full


class TestInvariants(unittest.TestCase):
    def test_silent_degradation_is_reported(self):
        report = RetrievalHealth(
            execution=legs(lexical=ok(), dense=ok(LegStatus.DEGRADED, 5, 3)),
            evidence=EvidenceState(completeness=Completeness.PARTIAL),
        )
        self.assertEqual(report.overall, OverallStatus.DEGRADED)
        self.assertIn("SILENT_DEGRADATION: status is not full but no reason code is present", report.validate())

    def test_degraded_leg_without_reason_is_reported(self):
        report = RetrievalHealth(execution=legs(lexical=ok(), dense=ok(LegStatus.DEGRADED, 5, 3)))
        self.assertTrue(any(problem.startswith("MISSING_REASON") for problem in report.validate()))

    def test_honest_degraded_report_has_no_violations(self):
        execution = legs(lexical=ok(), dense=ok(LegStatus.FAILED, 5, 0), rerank={"status": LegStatus.SKIPPED, "reason": ReasonCode.RERANK_UNAVAILABLE})
        execution.legs["dense"].reason = ReasonCode.EMBEDDING_QUOTA_EXHAUSTED
        report = RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=Completeness.FULL))
        self.assertEqual(report.validate(), [])
        self.assertEqual(report.degradation_reason(), "EMBEDDING_QUOTA_EXHAUSTED")
        self.assertEqual(report.degraded_leg_names(), ["dense"])

    def test_insufficient_evidence_never_reports_full(self):
        report = RetrievalHealth(
            execution=legs(lexical=ok(), dense=ok()),
            evidence=EvidenceState(completeness=Completeness.INSUFFICIENT),
        )
        self.assertEqual(report.execution.overall(), OverallStatus.FULL)
        self.assertEqual(report.overall, OverallStatus.DEGRADED)
        self.assertIn("INSUFFICIENT_EVIDENCE_REPORTED_FULL", report.validate())


class TestAnswerPolicy(unittest.TestCase):
    def make(self, dense_status, completeness, reason=ReasonCode.EMBEDDING_QUOTA_EXHAUSTED, lexical_status=LegStatus.SUCCESS):
        execution = legs(lexical=ok(lexical_status, 5, 5 if lexical_status is LegStatus.SUCCESS else 0), dense=ok(dense_status, 5, 5 if dense_status is LegStatus.SUCCESS else 0))
        if dense_status in (LegStatus.FAILED, LegStatus.DEGRADED):
            execution.legs["dense"].reason = reason
        if lexical_status in (LegStatus.FAILED, LegStatus.DEGRADED):
            execution.legs["lexical"].reason = ReasonCode.STORE_UNAVAILABLE
        return RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=completeness))

    def test_full_everything_answers(self):
        report = self.make(LegStatus.SUCCESS, Completeness.FULL)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.NARRATIVE), AnswerAction.ANSWER)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.CONSTRAINT_BEARING), AnswerAction.ANSWER)

    def test_dense_failed_but_evidence_full_allows_constraint_answer(self):
        report = self.make(LegStatus.FAILED, Completeness.FULL)
        self.assertEqual(report.overall, OverallStatus.DEGRADED)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.CONSTRAINT_BEARING), AnswerAction.ANSWER)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.NARRATIVE), AnswerAction.ANSWER_WITH_DISCLOSURE)
        self.assertEqual(health.required_notice(report, QuestionRisk.NARRATIVE), health.DISCLOSURE_NOTICE)

    def test_partial_evidence_discloses_for_narrative_and_refuses_for_constraint(self):
        report = self.make(LegStatus.FAILED, Completeness.PARTIAL)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.NARRATIVE), AnswerAction.ANSWER_WITH_DISCLOSURE)
        self.assertEqual(health.decide_answer_action(report, QuestionRisk.CONSTRAINT_BEARING), AnswerAction.REFUSE_INSUFFICIENT)
        self.assertEqual(health.required_notice(report, QuestionRisk.CONSTRAINT_BEARING), health.INSUFFICIENT_NOTICE)

    def test_insufficient_evidence_refuses_for_both_risks(self):
        report = self.make(LegStatus.SUCCESS, Completeness.INSUFFICIENT)
        for risk in (QuestionRisk.NARRATIVE, QuestionRisk.CONSTRAINT_BEARING):
            self.assertEqual(health.decide_answer_action(report, risk), AnswerAction.REFUSE_INSUFFICIENT)

    def test_failed_retrieval_refuses_everything(self):
        report = self.make(LegStatus.FAILED, Completeness.INSUFFICIENT, lexical_status=LegStatus.FAILED)
        self.assertEqual(report.overall, OverallStatus.FAILED)
        for risk in (QuestionRisk.NARRATIVE, QuestionRisk.CONSTRAINT_BEARING):
            self.assertEqual(health.decide_answer_action(report, risk), AnswerAction.REFUSE_FAILED)
            self.assertEqual(health.required_notice(report, risk), health.UNAVAILABLE_NOTICE)


class TestInterop(unittest.TestCase):
    def test_attach_health_preserves_existing_keys(self):
        result = {"chunks": [{"chunk_id": "a"}], "doc_aggs": [], "total": 1}
        report = RetrievalHealth(execution=legs(lexical=ok(), dense=ok()), evidence=EvidenceState(completeness=Completeness.FULL))
        attached = health.attach_health(result, report)
        self.assertEqual(result.keys(), {"chunks", "doc_aggs", "total"})
        self.assertEqual(attached["chunks"], result["chunks"])
        self.assertEqual(attached["total"], 1)
        self.assertEqual(attached["retrieval_health"], {"overall": "full", "evidence_completeness": "full", "degradation_reason": None})

    def test_api_view_exposes_exactly_three_fields(self):
        report = RetrievalHealth(execution=legs(lexical=ok(), dense=ok()), evidence=EvidenceState(completeness=Completeness.FULL))
        self.assertEqual(set(report.api_view().keys()), {"overall", "evidence_completeness", "degradation_reason"})

    def test_json_round_trip_preserves_state(self):
        execution = legs(lexical=ok(), dense=ok(LegStatus.FAILED, 5, 0), followup={"status": LegStatus.NOT_TRIGGERED})
        execution.legs["dense"].reason = ReasonCode.EMBEDDING_QUOTA_EXHAUSTED
        report = RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=Completeness.PARTIAL, support_level="supporting", families=["f1"]), alerts=["DENSE_LEG_UNAVAILABLE"], plan_version="1.0")
        restored = RetrievalHealth.from_json(report.to_json())
        self.assertEqual(restored.overall, report.overall)
        self.assertEqual(restored.degradation_reason(), "EMBEDDING_QUOTA_EXHAUSTED")
        self.assertEqual(restored.evidence.families, ["f1"])
        self.assertEqual(restored.api_view(), report.api_view())

    def test_unknown_reason_code_is_kept_visible(self):
        execution = legs(lexical=ok(), dense=ok(LegStatus.FAILED, 5, 0))
        execution.legs["dense"].reason = "SOMETHING_NEW"
        report = RetrievalHealth(execution=execution, evidence=EvidenceState(completeness=Completeness.PARTIAL))
        self.assertEqual(report.degradation_reason(), "SOMETHING_NEW")


if __name__ == "__main__":
    unittest.main()
