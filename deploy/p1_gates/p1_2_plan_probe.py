"""P1-2 plan probe: print the compiled canonical plan for each frozen P1-0 query.

Offline, no network, no model, no store: it imports the planner from the mounted repository and
prints what the INPUT declares. Its purpose is auditability - the plan for every frozen query is
readable, with its slot ids, its sources and its hash, before any gate asserts anything about it.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/ragflow")
sys.dont_write_bytecode = True

from rag.retrieval.planner import (  # noqa: E402
    PLAN_HASH_VERSION,
    PLAN_VERSION,
    canonical_text,
    compile_plan,
    profile_question,
    validate_plan,
)

QUERIES = [
    {"id": "C_STD", "kind": "COMPOSITE", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？"},
    {"id": "C_COMPARE", "kind": "COMPOSITE", "text": "220kV 单芯和三芯海底电缆的内衬层要求有什么区别？"},
    {"id": "C_PARTS", "kind": "COMPOSITE", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "C_MULTI", "kind": "COMPOSITE", "text": "单芯电缆与三芯电缆在金属套厚度和铠装层结构上有什么不同，各自依据哪份规范？"},
    {"id": "N_STD", "kind": "NON_COMPOSITE_CONTROL", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "N_ARMOUR", "kind": "NON_COMPOSITE_CONTROL", "text": "220kV 三芯海底电缆的铠装层要求是什么？"},
]


def main() -> int:
    report = {"plan_version": PLAN_VERSION, "plan_hash_version": PLAN_HASH_VERSION, "queries": []}
    for query in QUERIES:
        profile = profile_question(query["text"])
        plan = compile_plan(profile)
        check = validate_plan(plan)
        # A second compile from the same input must be byte-identical, and the hash must be
        # reproducible from the routes alone.
        again = compile_plan(profile_question(query["text"]))
        report["queries"].append(
            {
                "id": query["id"],
                "kind": query["kind"],
                "question": query["text"],
                "canonical_question": profile.canonical_question,
                "composite": profile.composite,
                "comparative": profile.comparative,
                "clause": profile.clause,
                "requirement": profile.requirement,
                "designations": list(profile.designations),
                "sides": list(profile.sides),
                "dimension_heads": list(profile.dimension_heads),
                "predicate": profile.predicate,
                "profile_key": profile.profile_key,
                "topology_size": plan.topology_size,
                "plan_hash": plan.plan_hash,
                "valid": check.valid,
                "recompile_identical": plan.routes == again.routes and plan.plan_hash == again.plan_hash,
                "canonical_idempotent": all(canonical_text(route.text) == route.text for route in plan.routes),
                "slots": [
                    {"slot_id": route.slot_id, "kind": route.kind, "source": route.source, "text": route.text}
                    for route in plan.routes
                ],
            }
        )
    print("P12_PLAN_PROBE_BEGIN")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("P12_PLAN_PROBE_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
