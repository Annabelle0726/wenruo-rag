"""G1 — ordered topology invariance (P1-2 offline gate).

FROZEN PASS CONDITION (P1-1 §2 rule T-a / §7 G1):

    PASS  <=>  element-wise equality of the ORDERED route list across all runs, same length and
               same sequence, AND an identical ``plan_hash``.

Unordered Jaccard and symmetric difference are DIAGNOSTIC ONLY (rule T-b) and are reported, never
used to pass the gate. A pure reordering with an identical set of routes must FAIL, and case R4
below asserts exactly that.

What is varied, and what must not move:

* cold-cache repetition - N compiles of the same input in the same process;
* the model's proposal - several LEGAL model outputs (empty, paraphrases, the question echoed,
  exact agreement, reversed order, junk types) via the planner's injection seam;
* the input - the six frozen P1-0 queries plus adversarial inputs (empty, whitespace, punctuation,
  a designation-only string, English).

Every one of those must produce the SAME ordered executable plan and the SAME ``plan_hash``. The
model may move ``slot_sources`` (provenance) and nothing else - asserted, so a future edit that let
provenance reach the topology fails here.

Offline by construction: no network, no store, no Redis, no model call (``chat_mdl=None`` plus an
injected proposal), no clock dependence in any assertion.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys

sys.path.insert(0, "/ragflow")
sys.dont_write_bytecode = True

from rag.retrieval.decomposition import (  # noqa: E402
    CONJUNCTION_RE,
    DISTRIBUTIVE_ADVERB_RE,
    ENUMERATING_CONJUNCTION_RE,
    _COMPARATIVE_VERB_PATTERN,
    _DISTRIBUTIVE_ADVERB_PATTERN,
    _ENUMERATING_PATTERN,
)
from rag.retrieval.planner import (  # noqa: E402
    PLAN_HASH_DOMAIN,
    PLAN_HASH_HEX_CHARS,
    PLAN_HASH_SEPARATOR,
    PLAN_HASH_VERSION,
    PLAN_VERSION,
    canonical_json,
    compile_retrieval_plan,
    compute_plan_hash,
    profile_question,
    route_fingerprint,
    validate_plan,
)

REPEATS = 25

FROZEN_QUERIES = [
    {"id": "C_STD", "kind": "COMPOSITE", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？"},
    {"id": "C_COMPARE", "kind": "COMPOSITE", "text": "220kV 单芯和三芯海底电缆的内衬层要求有什么区别？"},
    {"id": "C_PARTS", "kind": "COMPOSITE", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "C_MULTI", "kind": "COMPOSITE", "text": "单芯电缆与三芯电缆在金属套厚度和铠装层结构上有什么不同，各自依据哪份规范？"},
    {"id": "N_STD", "kind": "NON_COMPOSITE_CONTROL", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "N_ARMOUR", "kind": "NON_COMPOSITE_CONTROL", "text": "220kV 三芯海底电缆的铠装层要求是什么？"},
]

ADVERSARIAL_INPUTS = [
    {"id": "A_EMPTY", "text": ""},
    {"id": "A_SPACES", "text": "   \t  \n "},
    {"id": "A_PUNCT", "text": "？？。"},
    {"id": "A_DESIGNATION_ONLY", "text": "Q/GDW 73286.2-2026"},
    {"id": "A_ENGLISH", "text": "What is the nominal thickness of the inner sheath, and what is required for the armour layer?"},
    {"id": "A_LONG_ENUM", "text": "导体、屏蔽层、绝缘层、内衬层、铠装层和外被层分别有什么技术要求？"},
    {"id": "A_CASE_AND_SPACE", "text": "q/gdw   73286.2-2026  中 220KV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少"},
    {"id": "A_EDGE_PUNCT", "text": "。。。内衬层厚度和铠装层要求分别是多少。。。!!!"},
    # Not in the frozen C3 set, so it must SURVIVE canonicalisation: an honest boundary case
    # showing what the frozen rule does and does not strip.
    {"id": "A_ELLIPSIS_BOUNDARY", "text": "……内衬层厚度和铠装层要求分别是多少"},
]

#: Several LEGAL model outputs for one input. Every one of them must leave the plan untouched.
def proposal_variants(plan_texts: list[str]) -> list[dict]:
    exact = list(plan_texts)
    return [
        {"id": "P_EMPTY", "proposal": []},
        {"id": "P_WHITESPACE", "proposal": ["   ", "。", "？？"]},
        {"id": "P_NONE_LIKE", "proposal": [None, "", "  "]},
        {"id": "P_PARAPHRASE", "proposal": ["内衬层厚度要求", "铠装层的技术要求", "铠装层结构"]},
        {"id": "P_ECHO_QUESTION", "proposal": ["请把问题拆成若干原子子问题", "单芯海底电缆内衬层厚度是多少"]},
        {"id": "P_EXACT_AGREEMENT", "proposal": exact},
        {"id": "P_EXACT_REVERSED", "proposal": list(reversed(exact))},
        {"id": "P_EXACT_DUPLICATED", "proposal": exact + exact},
        {"id": "P_EXACT_REPUNCTUATED", "proposal": [f"  {text}。 " for text in exact]},
        {"id": "P_JUNK_TYPES", "proposal": [{"query": "内衬层"}, 17, ["nested"], {"weird": 1}]},
        {"id": "P_OVERLONG", "proposal": ["铠" * 500]},
    ]


def jaccard(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def ordered_identity_fails(left: list[str], right: list[str]) -> bool:
    """The G1 FAIL trigger, applied as the gate would apply it."""
    return len(left) != len(right) or any(a != b for a, b in zip(left, right))


async def reference_plan(question: str):
    return await compile_retrieval_plan(question=question, chat_mdl=None, use_cache=False, consult_model=False)


async def exercise(entry: dict) -> dict:
    question = entry["text"]
    profile = profile_question(question)
    reference = await reference_plan(question)
    texts = list(reference.texts)
    check = validate_plan(reference)
    base = {
        "id": entry["id"],
        "question": question,
        "canonical_question": profile.canonical_question,
        "composite": profile.composite,
        "plan_version": reference.plan_version,
        "plan_hash_version": reference.plan_hash_version,
        "plan_hash": reference.plan_hash,
        "topology_size": reference.topology_size,
        "ordered_routes": texts,
        "slot_ids": [route.slot_id for route in reference.routes],
        # An input that canonicalises to nothing legitimately declares no slot, so the empty plan
        # is the correct one for it; every other input must carry at least the base route.
        "validated": check.valid if profile.canonical_question else reference.topology_size == 0,
    }

    failures: list[str] = []

    # (1) Cold-cache repetition, same process.
    repeat_hashes, repeat_orders = set(), set()
    for _ in range(REPEATS):
        again = await reference_plan(question)
        repeat_hashes.add(again.plan_hash)
        repeat_orders.add(tuple(again.texts))
    base["cold_repeats"] = REPEATS
    base["distinct_plan_hashes_over_repeats"] = len(repeat_hashes)
    base["distinct_ordered_topologies_over_repeats"] = len(repeat_orders)
    if len(repeat_hashes) != 1:
        failures.append("cold repetition produced more than one plan_hash")
    if len(repeat_orders) != 1:
        failures.append("cold repetition produced more than one ordered topology")

    # (2) Model-proposal variants - the R1 case.
    variants = []
    for variant in proposal_variants(texts):
        produced = await compile_retrieval_plan(
            question=question,
            chat_mdl=None,
            injected_proposal=variant["proposal"],
            use_cache=False,
        )
        row = {
            "id": variant["id"],
            "plan_hash": produced.plan_hash,
            "ordered_routes": list(produced.texts),
            "slot_sources": list(produced.slot_sources),
            "triggers": list(produced.provenance.fallback_reasons),
            "consulted": produced.provenance.consulted,
            "proposals_recorded": len(produced.provenance.proposals),
            "hash_matches_reference": produced.plan_hash == reference.plan_hash,
            "order_matches_reference": list(produced.texts) == texts,
        }
        variants.append(row)
        if not row["hash_matches_reference"]:
            failures.append(f"variant {variant['id']} changed plan_hash")
        if not row["order_matches_reference"]:
            failures.append(f"variant {variant['id']} changed the ordered topology")
    base["proposal_variants"] = variants
    base["distinct_plan_hashes_over_variants"] = len({row["plan_hash"] for row in variants})

    # Provenance must actually be recorded WHERE THE MODEL IS CONSULTED, or (2) is vacuous: the
    # empty proposal and the exact agreement must be distinguishable in slot_sources while sharing
    # one plan_hash. On an input that declares no decomposition the model is not consulted at all
    # (T6), so every variant is identical there - which is the stronger statement, and it is
    # asserted separately by `model_not_consulted_on_non_composite_controls`.
    sources_by_variant = {row["id"]: tuple(row["slot_sources"]) for row in variants}
    agreement = sources_by_variant.get("P_EXACT_AGREEMENT", ())
    empty = sources_by_variant.get("P_EMPTY", ())
    base["provenance_is_recorded"] = (bool(agreement) and agreement != empty) if profile.composite else None
    base["agreement_sources"] = list(agreement)
    base["empty_sources"] = list(empty)
    if profile.composite and texts and not base["provenance_is_recorded"]:
        failures.append("provenance did not distinguish exact agreement from an empty proposal")

    # (3) R4 - a pure REORDERING with an identical route set must FAIL ordered identity.
    if len(reference.routes) >= 2:
        swapped = list(reference.routes)
        swapped[0], swapped[1] = swapped[1], swapped[0]
        swapped_hash = compute_plan_hash(swapped)
        base["reorder_case"] = {
            "unordered_jaccard": round(jaccard(set(texts), {route.text for route in swapped}), 4),
            "ordered_identity_fails": ordered_identity_fails(list(reference.texts), [route.text for route in swapped]),
            "plan_hash_changed": swapped_hash != reference.plan_hash,
            "original_hash": reference.plan_hash,
            "reordered_hash": swapped_hash,
        }
        if base["reorder_case"]["unordered_jaccard"] != 1.0:
            failures.append("the reorder case was not set-equal, so it does not test ordering")
        if not base["reorder_case"]["ordered_identity_fails"]:
            failures.append("a pure reordering did not fail ordered identity")
        if not base["reorder_case"]["plan_hash_changed"]:
            failures.append("a pure reordering did not change plan_hash (rule S4 broken)")
    else:
        base["reorder_case"] = None

    # (4) R5 - serialization-only differences must NOT change the hash (rules S1-S3).
    record = {"routes": [route_fingerprint(route) for route in reference.routes]}
    reordered_keys = {"routes": [{k: item[k] for k in reversed(list(item.keys()))} for item in record["routes"]]}
    spaced = json.dumps(json.loads(json.dumps(record)), indent=4, ensure_ascii=False, sort_keys=False)
    round_tripped = json.loads(spaced)
    base["serialization_invariance"] = {
        "key_order_changed_but_hash_equal": compute_plan_hash_from_record(reordered_keys) == reference.plan_hash,
        "whitespace_changed_but_hash_equal": compute_plan_hash_from_record(round_tripped) == reference.plan_hash,
    }
    if not all(base["serialization_invariance"].values()):
        failures.append("serialization-only differences changed plan_hash (rules S1-S3 broken)")

    # (5) The plan must survive its own read-path validation.
    if not base["validated"]:
        failures.append(f"the compiled plan failed validation: {check.reason}")

    base["failures"] = failures
    base["passed"] = not failures
    return base


def compute_plan_hash_from_record(record: dict) -> str:
    """Recompute the hash from an arbitrary serialization of the same record (rule S1)."""
    body = canonical_json(record)
    payload = PLAN_HASH_SEPARATOR.join((PLAN_HASH_DOMAIN, PLAN_HASH_VERSION, PLAN_VERSION, body))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:PLAN_HASH_HEX_CHARS]


def main() -> int:
    out: dict = {
        "gate": "P1_2_G1_ORDERED_TOPOLOGY_INVARIANCE",
        "plan_version": PLAN_VERSION,
        "plan_hash_version": PLAN_HASH_VERSION,
        "pass_condition": "ordered identity (element-wise, same length) AND identical plan_hash",
        "diagnostic_only": "unordered Jaccard and symmetric difference",
        "repeats_per_input": REPEATS,
        "model_calls_made": 0,
        "network": "none",
        "inputs": [],
    }

    for entry in FROZEN_QUERIES + ADVERSARIAL_INPUTS:
        out["inputs"].append(asyncio.run(exercise(entry)))

    checks = {
        # No new vocabulary: the planner's structural patterns are a partition of the classifier's
        # existing conjunction pattern, proven by string equality rather than asserted in prose.
        "no_new_vocabulary_conjunction_partition_exact": (
            CONJUNCTION_RE.pattern
            == f"{_ENUMERATING_PATTERN}|{_DISTRIBUTIVE_ADVERB_PATTERN}|{_COMPARATIVE_VERB_PATTERN}"
        ),
        "enumerating_slice_is_a_subset_object": ENUMERATING_CONJUNCTION_RE.pattern == _ENUMERATING_PATTERN,
        "adverb_slice_is_a_subset_object": DISTRIBUTIVE_ADVERB_RE.pattern == _DISTRIBUTIVE_ADVERB_PATTERN,
        "every_input_compiled": all(row["topology_size"] >= 1 or not row["canonical_question"] for row in out["inputs"]),
        "every_input_has_one_plan_hash_across_repeats": all(row["distinct_plan_hashes_over_repeats"] == 1 for row in out["inputs"]),
        "every_input_has_one_ordered_topology_across_repeats": all(row["distinct_ordered_topologies_over_repeats"] == 1 for row in out["inputs"]),
        "every_model_variant_preserved_the_plan_hash": all(row["distinct_plan_hashes_over_variants"] == 1 for row in out["inputs"]),
        "every_plan_passed_validation": all(row["validated"] for row in out["inputs"]),
        "provenance_is_recorded_without_reaching_topology": all(
            row["provenance_is_recorded"] for row in out["inputs"] if row["provenance_is_recorded"] is not None
        ),
        "every_composite_input_records_provenance": all(
            row["provenance_is_recorded"] is True for row in out["inputs"] if row["composite"]
        ),
        "pure_reordering_fails_ordered_identity": all(
            row["reorder_case"] is None or row["reorder_case"]["ordered_identity_fails"] for row in out["inputs"]
        ),
        "pure_reordering_changes_plan_hash": all(row["reorder_case"] is None or row["reorder_case"]["plan_hash_changed"] for row in out["inputs"]),
        "serialization_only_differences_do_not_change_plan_hash": all(
            all(row["serialization_invariance"].values()) for row in out["inputs"]
        ),
        "non_composite_controls_declare_one_route": all(
            row["topology_size"] == 1 for row in out["inputs"] if row["id"] in ("N_STD", "N_ARMOUR")
        ),
        # T6, asserted where it matters: on an input that declares no decomposition the model is
        # not consulted AT ALL, so not even a hostile proposal can reach the plan.
        "model_not_consulted_on_non_composite_controls": all(
            not variant["consulted"]
            for row in out["inputs"]
            if row["id"] in ("N_STD", "N_ARMOUR")
            for variant in row["proposal_variants"]
        ),
        "no_input_reported_failures": all(not row["failures"] for row in out["inputs"]),
    }
    out["checks"] = checks
    out["passed"] = all(checks.values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"
    out["failures"] = [{"id": row["id"], "failures": row["failures"]} for row in out["inputs"] if row["failures"]]

    print("P12_G1_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("P12_G1_JSON_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
