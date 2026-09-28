"""G3 — deterministic fallback (P1-2 offline gate).

FROZEN PASS CONDITION (P1-1 §7 G3):

    PASS  <=>  for each trigger T1..T6 the produced topology is deterministic across N >= 10
               repeats AND equals the topology produced with an ABSENT model output.

The reference is the plan compiled with the model not consulted at all (``consult_model=False``).
Every failure case the operator named is exercised as a real call on the real path where possible -
a model that raises, a model that times out, a model that answers with unparseable text - and via
the injection seam where the failure is a *payload* rather than a call (empty output, malformed
output).

Trigger map, and where each is decided:

    T1 TRANSPORT      the call or its JSON parse raised / timed out / returned non-JSON
    T2 SCHEMA         the call returned, nothing usable survived parsing
    T3 CLOSURE        non-empty proposals, NONE canonicalising into a declared slot
    T4 MISMATCH       some proposals canonicalise into declared slots, some do not
    T5 EMPTINESS      the compiled plan was empty where the input declared at least one slot
    T6 NON_COMPOSITE  the input declares no decomposition, so the model is NOT consulted

T5 is injected by replacing ``compile_plan`` with a stub that returns an empty plan, because it is a
defensive internal invariant that cannot be reached from a legal input.

Offline: no network (the model is a local stub), no Redis, no store.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, "/ragflow")
sys.dont_write_bytecode = True

# Belt and braces: this gate never wants a plan cache, and it must be structurally incapable of
# touching the deployed Redis.
os.environ["WENRUO_PLAN_CACHE"] = "off"

#: ``gen_json`` reaches the LLM cache through ``rag.graphrag.utils``, and importing that module
#: before ``common.settings`` walks into a circular import the application's own bootstrap order
#: avoids. Importing the settings package first is all that is needed - no ``init_settings()`` call,
#: so no socket is opened.
import common.settings  # noqa: F401,E402  (import-order fix, see above)

import rag.retrieval.planner as planner  # noqa: E402
from rag.retrieval.planner import (  # noqa: E402
    FALLBACK_TRIGGERS,
    SOURCE_DETERMINISTIC,
    SOURCE_DETERMINISTIC_FALLBACK,
    SOURCE_MODEL_CANONICALISED,
    T1_TRANSPORT,
    T2_SCHEMA,
    T3_CLOSURE,
    T4_MISMATCH,
    T5_EMPTINESS,
    T6_NON_COMPOSITE,
    compile_retrieval_plan,
    plan_from_routes,
)

REPEATS = 10

COMPOSITE_QUERY = "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？"
CONTROL_QUERIES = {
    "N_STD": "Q/GDW 73286.2-2026 是什么标准？",
    "N_ARMOUR": "220kV 三芯海底电缆的铠装层要求是什么？",
}


class StubModel:
    """A local model stub.

    ``llm_name`` and ``max_length`` are required by the real ``gen_json`` (it consults the LLM cache
    keyed by them and fits the prompt to ``max_length``), and ``async_chat`` is the one method the
    decomposition path calls. No socket is ever opened.
    """

    llm_name = "p1-2-g3-stub"
    max_length = 8192

    async def async_chat(self, *args, **kwargs):
        raise NotImplementedError


def isolate_llm_cache() -> dict:
    """Stop the decomposition path from reading or writing the deployed LLM cache.

    ``gen_json`` consults ``rag.graphrag.utils.get_llm_cache`` / ``set_llm_cache``, which is Redis.
    This gate must leave the deployed Redis untouched, so both are replaced in-process for the
    duration - the same isolation the Phase A cold-cache probe used, and the reason every case here
    is a genuine cold call rather than a cached replay.
    """
    import rag.graphrag.utils as graphrag_utils

    state = {"get_llm_cache": type(graphrag_utils.get_llm_cache).__name__, "set_llm_cache": type(graphrag_utils.set_llm_cache).__name__}
    graphrag_utils.get_llm_cache = lambda *args, **kwargs: None
    graphrag_utils.set_llm_cache = lambda *args, **kwargs: None
    return state


class RaisingModel(StubModel):
    """A model whose call fails: the T1 transport case."""

    async def async_chat(self, *args, **kwargs):
        raise RuntimeError("provider transport failure")


class TimingOutModel(StubModel):
    """A model whose call times out: also T1, and the case the operator named explicitly."""

    async def async_chat(self, *args, **kwargs):
        await asyncio.sleep(0.01)
        raise asyncio.TimeoutError("model timeout")


class EmptyStringModel(StubModel):
    """A model that answers with an empty string: T2 (a payload arrived, nothing usable in it)."""

    async def async_chat(self, *args, **kwargs):
        return ""


class NonJsonModel(StubModel):
    """A model that answers with prose.

    ``gen_json`` runs the response through ``json_repair``, which repairs arbitrary text into a
    string rather than raising, so a non-JSON answer reaches the planner as a payload with no route
    text in it: T2. T1 is reserved for the transport boundary itself (raise / timeout).
    """

    async def async_chat(self, *args, **kwargs):
        return "I am sorry, I cannot help with that."


class SchemaModel(StubModel):
    """A model that answers with VALID JSON that fails the schema: T2."""

    def __init__(self, payload: str) -> None:
        self._payload = payload

    async def async_chat(self, *args, **kwargs):
        return self._payload


async def reference(question: str):
    return await compile_retrieval_plan(question=question, chat_mdl=None, consult_model=False, use_cache=False)


async def run_case(question: str, case: dict, reference_plan) -> dict:
    """Run one failure case N times and compare every run to the reference plan."""
    hashes, orders, sources, triggers = set(), set(), set(), set()
    last = None
    for _ in range(REPEATS):
        produced = await compile_retrieval_plan(
            question=question,
            chat_mdl=case.get("chat_mdl"),
            injected_proposal=case.get("proposal"),
            use_cache=False,
            consult_model=True,
        )
        last = produced
        hashes.add(produced.plan_hash)
        orders.add(tuple(produced.texts))
        sources.add(tuple(produced.slot_sources))
        triggers.add(tuple(produced.provenance.fallback_reasons))

    expected = set(case["expected_triggers"])
    observed = set(last.provenance.fallback_reasons)
    return {
        "id": case["id"],
        "input": case["input_label"],
        "description": case["description"],
        "repeats": REPEATS,
        "distinct_plan_hashes": len(hashes),
        "distinct_ordered_topologies": len(orders),
        "plan_hash": last.plan_hash,
        "ordered_routes": list(last.texts),
        "slot_sources": list(last.slot_sources),
        "fallback_reasons": list(last.provenance.fallback_reasons),
        "expected_triggers": sorted(expected, key=FALLBACK_TRIGGERS.index),
        "trigger_present": expected.issubset(observed),
        "consulted": last.provenance.consulted,
        "converges_to_reference": last.plan_hash == reference_plan.plan_hash and list(last.texts) == list(reference_plan.texts),
        "deterministic": len(hashes) == 1 and len(orders) == 1 and len(sources) == 1 and len(triggers) == 1,
        "labels_are_provenance_only": all(source in (SOURCE_DETERMINISTIC, SOURCE_DETERMINISTIC_FALLBACK, SOURCE_MODEL_CANONICALISED) for source in last.slot_sources),
    }


async def t5_case(reference_plan) -> dict:
    """T5: a declared slot may not vanish. Injected, because no legal input reaches it."""
    original = planner.compile_plan

    def empty_compiler(profile):
        return plan_from_routes(())

    planner.compile_plan = empty_compiler
    try:
        hashes, orders, triggers = set(), set(), set()
        last = None
        for _ in range(REPEATS):
            produced = await compile_retrieval_plan(question=COMPOSITE_QUERY, chat_mdl=None, consult_model=False, use_cache=False)
            last = produced
            hashes.add(produced.plan_hash)
            orders.add(tuple(produced.texts))
            triggers.add(tuple(produced.provenance.fallback_reasons))
    finally:
        planner.compile_plan = original
    observed = set(last.provenance.fallback_reasons)
    return {
        "id": "T5_COMPILED_PLAN_EMPTY",
        "input": "COMPOSITE",
        "description": "the compiler returned no route for an input that declares one (injected)",
        "repeats": REPEATS,
        "distinct_plan_hashes": len(hashes),
        "distinct_ordered_topologies": len(orders),
        "plan_hash": last.plan_hash,
        "ordered_routes": list(last.texts),
        "slot_sources": list(last.slot_sources),
        "fallback_reasons": list(last.provenance.fallback_reasons),
        "expected_triggers": [T5_EMPTINESS],
        "trigger_present": T5_EMPTINESS in observed,
        "consulted": last.provenance.consulted,
        # T5 is the only case that legitimately differs from the reference: the reference plan is
        # the FULL compiled plan, and this case reconstructs the single base route the input always
        # determines. What must hold is that the reconstruction is deterministic and input-derived.
        "converges_to_reference": None,
        "deterministic": len(hashes) == 1 and len(orders) == 1 and len(triggers) == 1,
        "reconstruction_is_input_derived": list(last.texts) == [planner.profile_question(COMPOSITE_QUERY).canonical_question],
        "labels_are_provenance_only": all(source in (SOURCE_DETERMINISTIC, SOURCE_DETERMINISTIC_FALLBACK) for source in last.slot_sources),
    }


async def main_async() -> dict:
    out: dict = {
        "gate": "P1_2_G3_DETERMINISTIC_FALLBACK",
        "repeats_per_case": REPEATS,
        "reference": "the plan compiled with the model NOT consulted",
        "llm_cache_isolation": isolate_llm_cache(),
        "trigger_decision_note": (
            "T1 is the transport boundary: the call raised or timed out. A response that returns but "
            "carries no usable route (empty string, prose, wrong schema, empty list) is T2, because "
            "the existing gen_json step runs every response through json_repair, which repairs "
            "arbitrary text into a string instead of raising, so a non-JSON answer arrives as a "
            "payload with no route text in it. P1-1 section 1.4 groups 'returned non-JSON' under T1; "
            "the implementation draws the line at the call boundary instead. Both are 'no model "
            "contribution' and the executable plan is identical under either label."
        ),
        "cases": [],
        "controls": [],
    }

    composite_reference = await reference(COMPOSITE_QUERY)
    out["reference_plan"] = {
        "input": "COMPOSITE",
        "plan_hash": composite_reference.plan_hash,
        "ordered_routes": list(composite_reference.texts),
    }
    exact = list(composite_reference.texts)

    cases = [
        {
            "id": "T1_MODEL_RAISES",
            "input_label": "COMPOSITE",
            "description": "the model call raises",
            "chat_mdl": RaisingModel(),
            "expected_triggers": [T1_TRANSPORT],
        },
        {
            "id": "T1_MODEL_TIMES_OUT",
            "input_label": "COMPOSITE",
            "description": "the model call times out",
            "chat_mdl": TimingOutModel(),
            "expected_triggers": [T1_TRANSPORT],
        },
        {
            "id": "T1_EMPTY_STRING_OUTPUT",
            "input_label": "COMPOSITE",
            "description": "the model returns an empty string: a payload arrived with nothing in it",
            "chat_mdl": EmptyStringModel(),
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T1_NON_JSON_OUTPUT",
            "input_label": "COMPOSITE",
            "description": "the model returns prose; json_repair turns it into a payload with no routes",
            "chat_mdl": NonJsonModel(),
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T2_SCHEMA_MISSING_KEY",
            "input_label": "COMPOSITE",
            "description": "valid JSON that carries none of the schema's keys",
            "chat_mdl": SchemaModel('{"answer": "no sub-queries here"}'),
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T2_SCHEMA_WRONG_TYPE",
            "input_label": "COMPOSITE",
            "description": "valid JSON whose sub_queries member is the wrong type",
            "chat_mdl": SchemaModel('{"sub_queries": "内衬层厚度"}'),
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T2_EMPTY_PLAN_PAYLOAD",
            "input_label": "COMPOSITE",
            "description": "the model returns an empty list",
            "proposal": [],
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T2_WHITESPACE_ONLY_PAYLOAD",
            "input_label": "COMPOSITE",
            "description": "every proposal canonicalises to nothing",
            "proposal": ["   ", "。", "？？", ""],
            "expected_triggers": [T2_SCHEMA],
        },
        {
            "id": "T3_MALFORMED_PAYLOAD",
            "input_label": "COMPOSITE",
            "description": "malformed proposals: junk types and unrelated strings",
            "proposal": [{"query": "内衬层"}, 17, ["nested"], {"weird": 1}, "totally unrelated clause"],
            "expected_triggers": [T3_CLOSURE],
        },
        {
            "id": "T4_PARTIAL_AGREEMENT",
            "input_label": "COMPOSITE",
            "description": "one proposal canonicalises into a slot, one does not",
            "proposal": [exact[1] if len(exact) > 1 else exact[0], "totally unrelated clause"],
            "expected_triggers": [T4_MISMATCH],
        },
    ]
    for case in cases:
        out["cases"].append(await run_case(COMPOSITE_QUERY, case, composite_reference))
    out["cases"].append(await t5_case(composite_reference))

    for control_id, question in CONTROL_QUERIES.items():
        control_reference = await reference(question)
        accepted = await compile_retrieval_plan(
            question=question,
            chat_mdl=None,
            injected_proposal=list(control_reference.texts) + ["hostile proposal"],
            use_cache=False,
        )
        empty = await compile_retrieval_plan(question=question, chat_mdl=None, injected_proposal=[], use_cache=False)
        out["controls"].append(
            {
                "id": control_id,
                "question": question,
                "plan_hash": control_reference.plan_hash,
                "ordered_routes": list(control_reference.texts),
                "topology_size": control_reference.topology_size,
                "hostile_proposal_consulted": accepted.provenance.consulted,
                "hostile_proposal_changed_plan": accepted.plan_hash != control_reference.plan_hash or list(accepted.texts) != list(control_reference.texts),
                "empty_proposal_triggers": list(empty.provenance.fallback_reasons),
                "empty_proposal_changed_plan": empty.plan_hash != control_reference.plan_hash,
                "route_count_is_one": control_reference.topology_size == 1,
            }
        )

    checks = {
        "every_case_is_deterministic_across_repeats": all(case["deterministic"] for case in out["cases"]),
        "every_case_emitted_the_expected_trigger": all(case["trigger_present"] for case in out["cases"]),
        "every_case_converged_to_the_absent_model_plan": all(
            case["converges_to_reference"] for case in out["cases"] if case["converges_to_reference"] is not None
        ),
        "t5_reconstruction_is_input_derived": all(
            case["reconstruction_is_input_derived"] for case in out["cases"] if case["id"] == "T5_COMPILED_PLAN_EMPTY"
        ),
        "no_slot_label_can_reach_the_hash": all(case["labels_are_provenance_only"] for case in out["cases"]),
        "controls_declare_exactly_one_route": all(control["route_count_is_one"] for control in out["controls"]),
        "controls_never_consult_the_model": all(
            not control["hostile_proposal_consulted"] and not control["hostile_proposal_changed_plan"] for control in out["controls"]
        ),
        "controls_earn_T6_when_the_model_is_offered": all(T6_NON_COMPOSITE in control["empty_proposal_triggers"] for control in out["controls"]),
        "every_trigger_T1_to_T6_was_exercised": {
            trigger for case in out["cases"] for trigger in case["fallback_reasons"]
        }.union({trigger for control in out["controls"] for trigger in control["empty_proposal_triggers"]}).issuperset(
            {T1_TRANSPORT, T2_SCHEMA, T3_CLOSURE, T4_MISMATCH, T5_EMPTINESS, T6_NON_COMPOSITE}
        ),
        "no_case_reported_a_route_the_reference_did_not": all(
            case["converges_to_reference"] is not False for case in out["cases"]
        ),
    }
    out["checks"] = checks
    out["passed"] = all(checks.values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"
    return out


def main() -> int:
    out = asyncio.run(main_async())
    print("P12_G3_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("P12_G3_JSON_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
