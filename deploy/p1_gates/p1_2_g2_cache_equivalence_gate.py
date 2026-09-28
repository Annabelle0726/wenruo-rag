"""G2 — cache-state equivalence (P1-2 offline gate).

FROZEN PASS CONDITION (P1-1 §7 G2, as narrowed by the P1-2 authorisation):

    PASS  <=>  topology(cold_miss) == topology(warm_hit) == topology(stale_entry)
               == topology(cache_unavailable)          [identical ORDERED topology AND plan_hash]

A fifth state, ``disabled`` (``WENRUO_PLAN_CACHE=off`` / ``use_cache=False``), and a sixth, the
``retry`` P1-1 §4 names (the same key requested again), are reported in the same matrix.

The gate also proves the two properties that make the equality meaningful rather than accidental:

1. **What Redis holds is a determined canonical plan, never a model response.** The stored record
   is read back and checked field by field: exactly the plan's versions, hash and route
   fingerprints, and nothing resembling a proposal.
2. **A stale or forged entry cannot be served.** Four corruption cases are injected - a tampered
   route text with the old hash, a self-consistent forgery whose hash matches its own routes, an
   entry from another ``plan_version``, and non-JSON garbage - and each must be rejected on read
   (state ``stale_entry``) and fall back to the deterministically recompiled plan.

Isolation. The gate runs the matrix twice: once against an in-process fake client (``--network
none``), and once - only when ``WENRUO_PLAN_CACHE_REDIS_URL`` is exported - against a REAL Redis,
which the runner points at a throwaway instance. It never touches the deployed Redis, and it asserts
that by checking that every key it observed in the real instance carries the ``p1plan:`` prefix.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/ragflow")
sys.dont_write_bytecode = True

import common.settings  # noqa: F401,E402  (import-order fix for rag.graphrag.utils)

from rag.retrieval.planner import (  # noqa: E402
    CACHE_KEY_PREFIX,
    CACHE_STATE_COLD_MISS,
    CACHE_STATE_DISABLED,
    CACHE_STATE_STALE_ENTRY,
    CACHE_STATE_UNAVAILABLE,
    CACHE_STATE_WARM_HIT,
    PLAN_HASH_VERSION,
    PLAN_VERSION,
    PlanCache,
    PlanRoute,
    cache_key,
    canonical_json,
    compile_plan,
    compile_retrieval_plan,
    compute_plan_hash,
    profile_question,
)

QUERIES = [
    {"id": "C_STD", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？"},
    {"id": "C_COMPARE", "text": "220kV 单芯和三芯海底电缆的内衬层要求有什么区别？"},
    {"id": "C_PARTS", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "C_MULTI", "text": "单芯电缆与三芯电缆在金属套厚度和铠装层结构上有什么不同，各自依据哪份规范？"},
    {"id": "N_STD", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "N_ARMOUR", "text": "220kV 三芯海底电缆的铠装层要求是什么？"},
]

SCOPE = ("tenants=t1", "kbs=kb1", "config=routes_top_k=12")


class MemoryClient:
    """An in-process stand-in for Redis: ``get``/``set(name, value, ex=...)`` and nothing else."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.gets = 0
        self.sets = 0

    def get(self, name):
        self.gets += 1
        return self.store.get(name)

    def set(self, name, value, ex=None):
        self.sets += 1
        self.store[name] = value
        return True

    def keys(self, pattern: str = "*"):
        import fnmatch

        return [key for key in self.store if fnmatch.fnmatch(key, pattern)]


class BrokenClient:
    """A cache whose reads fail: the unavailable state."""

    def __init__(self) -> None:
        self.gets = 0

    def get(self, name):
        self.gets += 1
        raise ConnectionError("redis unreachable")

    def set(self, name, value, ex=None):
        raise ConnectionError("redis unreachable")


async def compiled(question: str, cache: PlanCache | None, *, use_cache: bool = True, injected=None):
    return await compile_retrieval_plan(
        question=question,
        chat_mdl=None,
        plan_cache=cache,
        cache_scope=SCOPE,
        use_cache=use_cache,
        injected_proposal=injected,
        consult_model=False,
    )


async def matrix_for(query: dict) -> dict:
    question = query["text"]
    canonical = profile_question(question).canonical_question
    reference = compile_plan(profile_question(question))
    rows: list[dict] = []

    def record(label: str, plan, note: str = "", expected: str | None = None) -> None:
        rows.append(
            {
                "state": label,
                "observed_cache_state": plan.provenance.cache_state,
                "expected_cache_state": expected
                or {"cache_unavailable": CACHE_STATE_UNAVAILABLE, "retry": CACHE_STATE_WARM_HIT}.get(label, label),
                "plan_hash": plan.plan_hash,
                "topology_size": plan.topology_size,
                "ordered_routes": list(plan.texts),
                "slot_sources": list(plan.slot_sources),
                "consulted": plan.provenance.consulted,
                "note": note,
            }
        )

    # 1. cold miss
    client = MemoryClient()
    cache = PlanCache(client)
    cold = await compiled(question, cache)
    record("cold_miss", cold)

    # 2. warm hit - the same key requested again, which is also what P1-1 calls a retry
    warm = await compiled(question, cache)
    record("warm_hit", warm)
    retry = await compiled(question, cache)
    record("retry", retry)

    stored_raw = client.store.get(cache_key(canonical, SCOPE))
    stored_record = json.loads(stored_raw) if stored_raw else None

    # 3. deliberately broken clients
    broken = await compiled(question, PlanCache(BrokenClient()))
    record("cache_unavailable", broken)
    disabled = await compiled(question, None, use_cache=False)
    record("disabled", disabled)

    # 4. four corruption cases; each must be rejected on read and recompiled deterministically
    corruptions = []
    good_record = json.loads(canonical_json(reference.as_cache_record()))
    key = cache_key(canonical, SCOPE)

    tampered = json.loads(json.dumps(good_record))
    tampered["routes"][-1]["text"] = tampered["routes"][-1]["text"] + " tampered"
    corruptions.append({"id": "tampered_text_old_hash", "value": canonical_json(tampered)})

    forged = json.loads(json.dumps(good_record))
    forged["routes"][-1]["text"] = "a completely different but perfectly canonical query"
    forged_routes = tuple(
        PlanRoute(slot_id=item["slot_id"], kind=item["kind"], attribute_key=item["attribute_key"], text=item["text"]) for item in forged["routes"]
    )
    forged["plan_hash"] = compute_plan_hash(forged_routes)
    corruptions.append({"id": "self_consistent_forgery", "value": canonical_json(forged)})

    old_version = json.loads(json.dumps(good_record))
    old_version["plan_version"] = "p1-1.0"
    corruptions.append({"id": "other_plan_version", "value": canonical_json(old_version)})

    corruptions.append({"id": "non_json_garbage", "value": "not json at all"})

    for case in corruptions:
        victim = MemoryClient()
        victim.store[key] = case["value"]
        plan = await compiled(question, PlanCache(victim))
        rows.append(
            {
                "state": f"stale_entry:{case['id']}",
                "observed_cache_state": plan.provenance.cache_state,
                "expected_cache_state": CACHE_STATE_STALE_ENTRY,
                "plan_hash": plan.plan_hash,
                "topology_size": plan.topology_size,
                "ordered_routes": list(plan.texts),
                "slot_sources": list(plan.slot_sources),
                "consulted": plan.provenance.consulted,
                "note": "corrupted entry must be rejected on read",
                "entry_was_rejected": plan.provenance.cache_state == CACHE_STATE_STALE_ENTRY,
            }
        )

    return {
        "id": query["id"],
        "question": question,
        "canonical_question": canonical,
        "reference_plan_hash": reference.plan_hash,
        "reference_ordered_routes": list(reference.texts),
        "cache_key": key,
        "stored_record_for_inspection": stored_record,
        "rows": rows,
        "distinct_plan_hashes": len({row["plan_hash"] for row in rows}),
        "distinct_ordered_topologies": len({tuple(row["ordered_routes"]) for row in rows}),
        "all_states_agree": len({row["plan_hash"] for row in rows}) == 1 and len({tuple(row["ordered_routes"]) for row in rows}) == 1,
        "every_state_matches_the_compiled_plan": all(
            row["plan_hash"] == reference.plan_hash and row["ordered_routes"] == list(reference.texts) for row in rows
        ),
        "corruptions_all_rejected": all(row.get("entry_was_rejected", True) for row in rows),
    }


async def main_async() -> dict:
    out: dict = {
        "gate": "P1_2_G2_CACHE_STATE_EQUIVALENCE",
        "plan_version": PLAN_VERSION,
        "plan_hash_version": PLAN_HASH_VERSION,
        "equality_domain": "ordered executable topology AND plan_hash",
        "scope": list(SCOPE),
        "backends": [],
        "queries": [],
    }

    memory: dict = {"backend": "in_process_fake", "url": None}
    out["backends"].append(memory)
    for query in QUERIES:
        out["queries"].append(await matrix_for(query))

    # The real-Redis leg. Only run when the runner hands over an ISOLATED instance; the deployed
    # Redis is never addressed, and every key seen here is checked to carry the planner's prefix.
    url = str(os.environ.get("WENRUO_PLAN_CACHE_REDIS_URL", "")).strip()
    if url:
        try:
            import valkey as redis_client
        except ImportError:
            import redis as redis_client

        client = redis_client.Redis.from_url(url, decode_responses=True)
        real: dict = {"backend": "isolated_redis", "url": "redacted", "queries": [], "keys_seen": []}
        for query in QUERIES:
            reference = compile_plan(profile_question(query["text"]))
            cache = PlanCache(client)
            cold = await compiled(query["text"], cache)
            warm = await compiled(query["text"], cache)
            key = cache_key(profile_question(query["text"]).canonical_question, SCOPE)
            real["queries"].append(
                {
                    "id": query["id"],
                    "cache_key": key,
                    "cold_state": cold.provenance.cache_state,
                    "warm_state": warm.provenance.cache_state,
                    "cold_plan_hash": cold.plan_hash,
                    "warm_plan_hash": warm.plan_hash,
                    "reference_plan_hash": reference.plan_hash,
                    "agree": cold.plan_hash == warm.plan_hash == reference.plan_hash,
                }
            )
        keys = sorted(client.keys("*"))
        real["keys_seen"] = keys
        real["key_count"] = len(keys)
        real["every_key_carries_the_planner_prefix"] = all(key.startswith(f"{CACHE_KEY_PREFIX}:") for key in keys)
        real["dbsize"] = client.dbsize()
        rtt_samples = []
        for _ in range(20):
            started = time.perf_counter()
            client.get(keys[0] if keys else cache_key("x", SCOPE))
            rtt_samples.append((time.perf_counter() - started) * 1000)
        real["get_rtt_ms_median"] = round(sorted(rtt_samples)[len(rtt_samples) // 2], 3)
        real["all_queries_agree"] = all(row["agree"] for row in real["queries"])
        out["backends"].append(real)

    checks = {
        "every_state_produces_one_plan_hash": all(row["distinct_plan_hashes"] == 1 for row in out["queries"]),
        "every_state_produces_one_ordered_topology": all(row["distinct_ordered_topologies"] == 1 for row in out["queries"]),
        "every_state_matches_the_deterministically_compiled_plan": all(row["every_state_matches_the_compiled_plan"] for row in out["queries"]),
        "cold_miss_equals_warm_hit": all(
            next(row for row in q["rows"] if row["state"] == "cold_miss")["plan_hash"]
            == next(row for row in q["rows"] if row["state"] == "warm_hit")["plan_hash"]
            for q in out["queries"]
        ),
        "warm_hit_equals_stale_entry": all(
            next(row for row in q["rows"] if row["state"] == "warm_hit")["plan_hash"]
            == next(row for row in q["rows"] if row["state"].startswith("stale_entry"))["plan_hash"]
            for q in out["queries"]
        ),
        "warm_hit_equals_cache_unavailable": all(
            next(row for row in q["rows"] if row["state"] == "warm_hit")["plan_hash"]
            == next(row for row in q["rows"] if row["state"] == "cache_unavailable")["plan_hash"]
            for q in out["queries"]
        ),
        "every_corruption_was_rejected_on_read": all(row["corruptions_all_rejected"] for row in out["queries"]),
        "what_redis_holds_is_a_canonical_plan": all(
            q["stored_record_for_inspection"] is not None
            and set(q["stored_record_for_inspection"]) == {"plan_hash", "plan_hash_version", "plan_version", "routes"}
            for q in out["queries"]
        ),
        "no_model_output_is_stored": all(
            all(set(route) == {"attribute_key", "kind", "slot_id", "text"} for route in q["stored_record_for_inspection"]["routes"])
            for q in out["queries"]
        ),
        "warm_hit_skips_the_model_consultation": all(
            not next(row for row in q["rows"] if row["state"] == "warm_hit")["consulted"] for q in out["queries"]
        ),
        "a_hit_is_not_required_for_correctness": all(
            next(row for row in q["rows"] if row["state"] == "cache_unavailable")["plan_hash"] == q["reference_plan_hash"] for q in out["queries"]
        ),
        "an_unreachable_cache_reports_itself_as_unavailable": all(
            next(row for row in q["rows"] if row["state"] == "cache_unavailable")["observed_cache_state"] == CACHE_STATE_UNAVAILABLE
            for q in out["queries"]
        ),
        "observed_states_match_the_expected_labels": all(row["observed_cache_state"] == row["expected_cache_state"] for q in out["queries"] for row in q["rows"]),
        "cold_warm_and_retry_are_distinguished": all(
            [row["observed_cache_state"] for row in q["rows"] if row["state"] in ("cold_miss", "warm_hit", "retry")]
            == [CACHE_STATE_COLD_MISS, CACHE_STATE_WARM_HIT, CACHE_STATE_WARM_HIT]
            for q in out["queries"]
        ),
        "disabled_state_is_the_same_plan": all(
            next(row for row in q["rows"] if row["state"] == "disabled")["observed_cache_state"] == CACHE_STATE_DISABLED
            and next(row for row in q["rows"] if row["state"] == "disabled")["plan_hash"] == q["reference_plan_hash"]
            for q in out["queries"]
        ),
    }
    if url:
        real = next(backend for backend in out["backends"] if backend["backend"] == "isolated_redis")
        checks["isolated_redis_agrees_with_the_fake"] = real["all_queries_agree"]
        checks["isolated_redis_only_carries_planner_keys"] = real["every_key_carries_the_planner_prefix"]
    out["checks"] = checks
    out["passed"] = all(checks.values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"
    return out


def main() -> int:
    out = asyncio.run(main_async())
    print("P12_G2_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("P12_G2_JSON_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
