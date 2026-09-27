"""Mirror the frozen Rev 3 P0 target behaviour and C1-C7 acceptance contract into phase_b_backlog.json.

One-way traceability: phase_b_architecture_plan.md stays authoritative, this file is a 1:1 mirror. No new
requirement is introduced and no P0 scope is widened. Prints a mapping check so every contract rule can be
proven to land on a backlog acceptance item.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKLOG = ROOT / "phase_b_backlog.json"

CONTRACT = [
    {
        "id": "C1",
        "condition": "overall = full",
        "required_outcome": "no degradation notice at all: no toast, no banner, no inline note, no badge",
        "backlog_item": "P0-6",
    },
    {
        "id": "C2",
        "condition": "overall = degraded and degradation_reason = EMBEDDING_QUOTA_EXHAUSTED",
        "required_outcome": "exactly one friendly semantic-retrieval-limited notice for that retrieval",
        "backlog_item": "P0-6",
    },
    {
        "id": "C3",
        "condition": "overall = degraded and degradation_reason = EMBEDDING_UNAVAILABLE",
        "required_outcome": "exactly one generic retrieval-degraded notice for that retrieval",
        "backlog_item": "P0-6",
    },
    {
        "id": "C4",
        "condition": "degraded with any other reason, or failed with no usable evidence",
        "required_outcome": (
            "exactly one generic retrieval-degraded notice in both states. The two underlying states must stay "
            "distinguishable: degraded means retrieval succeeded while running on partial evidence, failed means "
            "retrieval produced no usable evidence at all. Both obey the exactly-one disclosure rule, and neither "
            "may be collapsed into the other."
        ),
        "backlog_item": "P0-6",
    },
    {
        "id": "C5",
        "condition": "N routes or N legs failed on one retrieval",
        "required_outcome": "still exactly one notice; multiplicity is a hard failure, not a cosmetic issue",
        "backlog_item": "P0-6",
    },
    {
        "id": "C6",
        "condition": "notice rendering, any degraded state",
        "required_outcome": (
            "no API key or key fragment, no provider JSON error body, no endpoint or API version string, no stack "
            "trace, no infrastructure detail"
        ),
        "backlog_item": "P0-6",
    },
    {
        "id": "C7",
        "condition": "evidence_state = partial",
        "required_outcome": (
            "answer-policy enforcement stays DISABLED: partial evidence alone must not produce a refusal and must "
            "not change the baseline answer flow"
        ),
        "backlog_item": "P0-4",
    },
]

EVIDENCE = {
    "C1": "healthy-path run: notice count 0",
    "C2": "injected quota failure: notice count 1, text in the semantic-limited class",
    "C3": "injected unavailable failure: notice count 1, text in the generic class",
    "C4": "degraded-other injection and failed injection: one generic notice each, and the underlying states remain distinguishable",
    "C5": "injection failing all dense routes at once: notice count 1 (deduplication proof)",
    "C6": "rendered-text assertion against key material, provider JSON, endpoint/version strings and stack text",
    "C7": "assertion that a partial evidence state alone produces no refusal and no answer-flow change",
}

TARGET_BEHAVIOR = {
    "keep_route_isolation": "a dead dense leg must still let the lexical leg return evidence",
    "pass_health_through": "retrieval_health is collected at the execution points, aggregated once and attached additively",
    "exactly_one_notice": "granularity is one retrieval, never one route and never one leg; one attached health block yields at most one notice",
    "answer_policy_enforcement": "DISABLED (unchanged)",
    "forbidden_rollback": [
        "re-raising the dense exception to trigger a UI error",
        "returning a synthetic non-2xx status for a partial retrieval",
        "setting an error code for a partial retrieval",
        "emitting more than one notice per retrieval",
    ],
}

STATUS_GROUNDING = {
    "health_dto_and_contract": "IMPLEMENTED",
    "production_wiring": "CANDIDATE_IMAGE_PREPARED_NOT_DEPLOYED (my-wenruorag:p0b-891572a71 = 99d0ee210004)",
    "operator_observability_sink": "NOT_ACCEPTED_NOT_WIRED",
    "user_disclosure_ui": "DEFERRED_NOT_IMPLEMENTED",
    "live_p0c_acceptance": "BLOCKED_BY_GEMINI_404_MODEL_CREDENTIAL_ISSUE",
}

NEW_ITEMS = [
    {
        "id": "P0-6",
        "priority": "P0",
        "title": "Retrieval-level user disclosure (exactly-one notice)",
        "deliverable": "one user-facing degradation notice per retrieval, driven by the attached retrieval_health block",
        "status": "DEFERRED_NOT_IMPLEMENTED",
        "spec_revision": "R3.2 target behaviour, R3.3 acceptance contract",
        "acceptance_rules": ["C1", "C2", "C3", "C4", "C5", "C6"],
        "forbidden": TARGET_BEHAVIOR["forbidden_rollback"],
    },
    {
        "id": "P0-7",
        "priority": "P0",
        "title": "Operator observability sink (structured log line plus metrics and trace)",
        "deliverable": "ship the structured health event the candidate already builds to a log line and to a metrics/trace sink",
        "status": "NOT_ACCEPTED_NOT_WIRED",
        "spec_revision": "R3.3 separate acceptance tracks",
        "acceptance_rules": ["separate track from user disclosure", "dense-leg failure observable without a customer report"],
        "note": "the candidate builds the event in process only; nothing writes it to a sink yet",
    },
]


def main() -> int:
    data = json.loads(BACKLOG.read_text(encoding="utf-8"))
    data["authoritative_spec"] = "phase_b_architecture_plan.md (Revision 3 is binding); this file is a 1:1 mirror"
    data["spec_revision_mirrored"] = "R3 - P0 target behaviour and frozen acceptance contract C1-C7"
    data["status_grounding"] = STATUS_GROUNDING
    data["p0_target_behavior"] = TARGET_BEHAVIOR
    data["p0_acceptance_contract"] = [{**rule, "evidence_required": EVIDENCE[rule["id"]]} for rule in CONTRACT]

    existing = {item["id"] for item in data["items"]}
    for item in NEW_ITEMS:
        if item["id"] not in existing:
            data["items"].append(item)

    BACKLOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    item_ids = {item["id"] for item in data["items"]}
    mapped = sorted({rule["backlog_item"] for rule in CONTRACT})
    unmapped = [item for item in mapped if item not in item_ids]
    rules_with_evidence = [rule["id"] for rule in data["p0_acceptance_contract"] if rule.get("evidence_required")]
    report = {
        "contract_rules": len(data["p0_acceptance_contract"]),
        "rules_with_evidence": len(rules_with_evidence),
        "mapped_backlog_items": mapped,
        "unmapped_items": unmapped,
        "items_total": len(data["items"]),
        "c4_states_distinguished": "degraded" in data["p0_acceptance_contract"][3]["required_outcome"] and "failed" in data["p0_acceptance_contract"][3]["required_outcome"],
        "mirror": "OK" if len(data["p0_acceptance_contract"]) == 7 and not unmapped and len(rules_with_evidence) == 7 else "FAIL",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["mirror"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
